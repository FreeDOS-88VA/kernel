#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Build parameterized flat loader stages from one explicit overlay.

No firmware discovery, emulator execution, or network access occurs here.
Private overlays and every product of them must remain in an ignored sink.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess

from loader_profile import ProfileError, definitions, nasm_definitions, stage2_symbols

BOOT = Path(__file__).resolve().parents[1] / "boot"


def validate_overlay(value):
    if not isinstance(value, dict) or set(value) != {"schema_version", "layout", "bootstrap", "firmware_callback"} or type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ProfileError("Loader overlay schema differs")
    definitions(value["layout"])
    bootstrap = value["bootstrap"]
    names = {"image_segment", "image_offset", "loaded_bytes", "drive_context", "call_flags"}
    if not isinstance(bootstrap, dict) or set(bootstrap) != names:
        raise ProfileError("Bootstrap schema differs")
    if any(type(v) is not int or not 0 <= v <= 65535 for v in bootstrap.values()):
        raise ProfileError("Bootstrap field is not a bounded word")
    if bootstrap["loaded_bytes"] < 1024 or bootstrap["image_offset"]+1024 > 65536:
        raise ProfileError("Initial loaded extent does not contain the bootstrap")
    start = bootstrap["image_segment"]*16+bootstrap["image_offset"]
    if start+bootstrap["loaded_bytes"] > 0x100000:
        raise ProfileError("Initial loaded extent exceeds real-mode memory")
    bootstrap_end = start + bootstrap["loaded_bytes"]
    regions = value["layout"]["regions"]
    in_place = regions["kernel_file"] == regions["kernel_allocation"]
    for name, (low, high) in regions.items():
        if low < bootstrap_end and start < high:
            # The PC-88VA boot sector is entered at the qualified bootstrap
            # segment.  Once stage 1 has transferred to stage 2, that code
            # and its one-sector image are dead.  A later transformed
            # allocation may therefore reuse the complete bootstrap interval,
            # even when the initial file staging interval is separate (the
            # 1340h -> 3000h split-loader path).  The allocation may begin
            # below the bootstrap, provided it fully contains the now-dead
            # bootstrap extent; a partial alias remains unsafe.
            complete_bootstrap_alias = low <= start and high >= bootstrap_end
            if not ((name == "kernel_allocation" or
                     (name == "kernel_file" and in_place)) and
                    complete_bootstrap_alias):
                raise ProfileError("Bootstrap lifetime overlaps a later owned region")
    callback = value["firmware_callback"]
    if not isinstance(callback, str) or len(callback) > 16384:
        raise ProfileError("Firmware callback is not bounded source text")
    lines = [line.strip() for line in callback.splitlines() if line.strip()]
    if not lines or lines[0] != "%macro PC88VA_FIRMWARE_READ_ONE 0" or lines[-1] != "%endmacro":
        raise ProfileError("Callback must define exactly the declared zero-argument macro")
    # This is a binding interface, not a mechanism for arbitrary include paths
    # or binary embedding. Values/instructions come only from this one overlay.
    instructions = {"mov", "cmp", "jne", "je", "ja", "jae", "jb", "jbe", "jc", "jnc",
                    "jnz", "jz", "jmp", "shl", "shr", "or", "and", "xor", "push",
                    "pop", "pushf", "popf", "int", "retf", "add", "sub", "clc", "stc"}
    for line in lines[1:-1]:
        if not re.fullmatch(r"[A-Za-z0-9_%:,\[\]+*() \-]+", line):
            raise ProfileError("Callback contains a forbidden token or external reference")
        if line.endswith(":"):
            if not re.fullmatch(r"%%[A-Za-z_][A-Za-z0-9_]*:", line):
                raise ProfileError("Callback labels must be macro-local")
        elif line.split()[0].lower() not in instructions:
            raise ProfileError("Callback contains an unsupported instruction or directive")
    if not any(line == "retf" for line in lines):
        raise ProfileError("Callback has no explicit far return")
    return value


def read_overlay(path):
    if path.is_symlink() or not path.is_file():
        raise ProfileError("Overlay is not a regular non-symlink file")
    value = validate_overlay(json.loads(path.read_text()))
    if value["layout"]["profile_class"] == "private_observation_overlay" and stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ProfileError("Private overlay permissions are not owner-only")
    return value


def check_sink(path, private):
    if path.is_symlink() or (private and any(p.is_symlink() for p in path.parents)):
        raise ProfileError("Output sink traverses a symlink")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not private:
        return
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ProfileError("Private output sink is not owner-only")
    resolved = path.resolve()
    if any(str(resolved) == root or str(resolved).startswith(root+"/") for root in ("/tmp", "/private/tmp")):
        raise ProfileError("Private canonical loader output cannot use temporary storage")
    if shutil.which("git") is None:
        # The accepted offline guest-build container intentionally has no Git.
        # Its exported tree has no repository metadata. Never use this path
        # when a Git marker exists but the ignore policy cannot be checked.
        if any((p / ".git").exists() for p in (resolved, *resolved.parents)):
            raise ProfileError("Git repository ignore policy cannot be verified")
        return
    git = subprocess.run(["git", "-C", str(path), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if git.returncode == 0:
        root = Path(git.stdout.strip())
        relative = resolved.relative_to(root.resolve())
        tracked = subprocess.run(["git", "-C", str(root), "ls-files", "--", str(relative)], capture_output=True)
        ignored = subprocess.run(["git", "-C", str(root), "check-ignore", "-q", str(relative / "sink-probe")], capture_output=True)
        if tracked.returncode or tracked.stdout or ignored.returncode:
            raise ProfileError("Private output sink is not excluded from Git")


def build_stage(overlay, output, stage, extent=None, nasm="nasm"):
    validate_overlay(overlay)
    if stage not in (1, 2):
        raise ProfileError("Unknown loader stage")
    check_sink(output, overlay["layout"]["profile_class"] == "private_observation_overlay")
    text = nasm_definitions(overlay["layout"]) + overlay["firmware_callback"] + "\n"
    if stage == 1:
        if not isinstance(extent, dict) or set(extent) != {"first_lba", "sector_count", "file_size"}:
            raise ProfileError("Stage 1 requires an explicit builder-derived stage-2 extent")
        if any(type(v) is not int or v <= 0 for v in extent.values()):
            raise ProfileError("Stage-2 extent is not positive bounded integers")
        layout = definitions(overlay["layout"])
        count, size, lba = extent["sector_count"], extent["file_size"], extent["first_lba"]
        bps = layout["S2_SECTOR_BYTES"]
        if bps != 1024 or count != (size+bps-1)//bps or count*bps > layout["S2_STAGE2_CAPACITY"] or lba+count > layout["S2_TOTAL_SECTORS"]:
            raise ProfileError("Stage-2 extent does not fit bootstrap media or ownership")
        b = overlay["bootstrap"]
        parameters = {"S1_IMAGE_OFFSET": b["image_offset"], "S1_ENTRY_SEGMENT": b["image_segment"],
                      "S1_DRIVE_CONTEXT": b["drive_context"], "S1_CALL_FLAGS": b["call_flags"],
                      "S1_STAGE2_LBA": lba, "S1_STAGE2_COUNT": count}
        text += "".join("%define " + k + " " + str(v) + "\n" for k, v in sorted(parameters.items()))
    include, binary = output / ("stage"+str(stage)+"-profile.inc"), output / ("stage"+str(stage)+".bin")
    if include.exists() or binary.exists():
        raise ProfileError("Refusing to replace a previous loader build")
    with include.open("x") as stream:
        os.chmod(include, 0o600)
        stream.write(text)
    command = [nasm, "-f", "bin", "-DPC88VA", "-DJAPAN", "-DDBCS", "-I"+str(BOOT)+"/",
               "-p", str(include), "-o", str(binary), str(BOOT / ("stage"+str(stage)+".asm"))]
    result = subprocess.run(command, capture_output=True)
    with (output / ("stage"+str(stage)+"-assemble.log")).open("xb") as stream:
        os.chmod(stream.name, 0o600)
        stream.write(result.stdout+result.stderr)
    if result.returncode:
        raise ProfileError("Loader assembly failed; diagnostics remain only in the selected sink")
    binary.chmod(0o600)
    image = binary.read_bytes()
    symbols = stage2_symbols(image) if stage == 2 else None
    if stage == 1 and len(image) != 1024:
        raise ProfileError("Bootstrap size differs")
    return {"stage": stage, "size": len(image), "sha256": hashlib.sha256(image).hexdigest(),
            "symbols": symbols, "overlay_class": overlay["layout"]["profile_class"],
            "command_identity": "nasm -f bin -DPC88VA -DJAPAN -DDBCS -Iboot/ -p overlay -o stage.bin boot/stage.asm"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--overlay", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stage", type=int, choices=(1, 2), required=True)
    parser.add_argument("--extent", type=Path)
    args = parser.parse_args()
    try:
        overlay = read_overlay(args.overlay)
        extent = json.loads(args.extent.read_text()) if args.extent else None
        manifest = build_stage(overlay, args.output, args.stage, extent)
        path = args.output / ("stage"+str(args.stage)+"-manifest.json")
        with path.open("x") as stream:
            os.chmod(path, 0o600)
            json.dump(manifest, stream, sort_keys=True, indent=2)
            stream.write("\n")
        print("Parameterized loader stage built; manifest retained in selected output sink")
    except (OSError, ValueError, ProfileError):
        parser.exit(1, "Loader build prerequisite or validation failed; no overlay values disclosed\n")


if __name__ == "__main__":
    main()
