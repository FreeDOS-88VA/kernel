#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Collect deterministic PC-88VA carrier and parameterized loader evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import sys
from pathlib import Path


class EvidenceError(RuntimeError):
    """Raised when linked output violates the compile-only contract."""


TOOLS = ("wcc", "wmake", "wlink", "wlib", "nasm")
EXPECTED_MACROS = ["DBCS", "JAPAN", "PC88VA"]
COMMANDS = [
    "nasm -f obj -DPC88VA -DJAPAN -DDBCS -o build/startup.obj kernel/startup.asm",
    "nasm -f obj -DPC88VA -DJAPAN -DDBCS -Iboot/ -o build/loader_services.obj kernel/loader_services.asm",
    "nasm -f obj -DPC88VA -DJAPAN -DDBCS -o build/console.obj kernel/console.asm",
    "nasm -f obj -DPC88VA -DJAPAN -DDBCS -o build/machine_services.obj kernel/machine_services.asm",
    "nasm -f obj -DPC88VA -DJAPAN -DDBCS -o build/console_input.obj kernel/console_input.asm",
    "nasm -f obj -DPC88VA -DJAPAN -DDBCS -Iboot/ -o build/resident_disk.obj kernel/resident_disk.asm",
    "wcc -zq -0 -ms -bt=DOS -os -s -we -e5 -zp1 -zl -d1 -DPC88VA -DJAPAN -DDBCS -fo=build/stubs.obj kernel/stubs.c",
    "python3 -c import-os-set-build/stubs.obj-mtime-from-SOURCE_DATE_EPOCH",
    "wlib -q build/platform.lib +build/stubs.obj",
    "wlink @config/link.rsp",
]


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode("utf-8")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def identity(path: Path, relative: str | None = None) -> dict[str, object]:
    if not path.is_file() or path.is_symlink():
        raise EvidenceError(f"required regular file is missing: {path}")
    data = path.read_bytes()
    record: dict[str, object] = {"sha256": sha256_bytes(data), "size": len(data)}
    if relative is not None:
        record["path"] = relative
    return record


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"cannot read canonical input {path}: {exc}") from exc
    if canonical_bytes(value) != path.read_bytes():
        raise EvidenceError(f"JSON input is not canonical: {path}")
    return value


def parse_mz(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    if len(data) < 28 or data[:2] != b"MZ":
        raise EvidenceError("PC-88VA compile-only artifact is not a DOS MZ container")
    fields = struct.unpack_from("<14H", data, 0)
    (
        _magic,
        bytes_last_page,
        pages,
        relocation_count,
        header_paragraphs,
        minimum_allocation,
        maximum_allocation,
        initial_ss,
        initial_sp,
        checksum,
        initial_ip,
        initial_cs,
        relocation_table_offset,
        overlay,
    ) = fields
    encoded_size = (pages - 1) * 512 + (bytes_last_page or 512) if pages else 0
    if encoded_size != len(data):
        raise EvidenceError("MZ header file-size fields do not match the linked artifact")
    header_bytes = header_paragraphs * 16
    if not 28 <= header_bytes <= len(data):
        raise EvidenceError("MZ header extent is invalid")
    if relocation_table_offset + relocation_count * 4 > header_bytes:
        raise EvidenceError("MZ relocation table exceeds the header")
    return {
        "body_size": len(data) - header_bytes,
        "checksum": checksum,
        "container": "dos-mz",
        "entry": {"cs_relative": initial_cs, "ip": initial_ip},
        "file_size": len(data),
        "header_bytes": header_bytes,
        "maximum_allocation_paragraphs": maximum_allocation,
        "minimum_allocation_paragraphs": minimum_allocation,
        "overlay": overlay,
        "relocation_count": relocation_count,
        "relocation_table_offset": relocation_table_offset,
        "required_initial_stack": {"ss_relative": initial_ss, "sp": initial_sp},
    }


def parse_link_map(path: Path) -> dict[str, object]:
    """Extract semantic linker evidence while rejecting ambient map headers."""
    lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
    entry = None
    stack = None
    memory = None
    symbols = []
    for line in lines:
        match = re.fullmatch(r"([0-9A-Fa-f]{4}:[0-9A-Fa-f]{4})[+*s ]*\s+(\S+)", line)
        if match:
            symbols.append({"address": match.group(1), "name": match.group(2)})
        match = re.fullmatch(r"Entry point address:\s+([0-9A-Fa-f]{4}:[0-9A-Fa-f]{4})", line)
        if match:
            entry = match.group(1)
        match = re.fullmatch(r"Stack size:\s+([0-9A-Fa-f]+) \((\d+)\.\)", line)
        if match:
            stack = {"bytes": int(match.group(2)), "hex": match.group(1)}
        match = re.fullmatch(r"Memory size:\s+([0-9A-Fa-f]+) \((\d+)\.\)", line)
        if match:
            memory = {"bytes": int(match.group(2)), "hex": match.group(1)}
    required = {
        "_pc88va_compile_only_entry",
        "_pc88va_compile_only_fatal_stop",
        "pc88va_platform_probe_",
        "pc88va_disk_read_",
        "pc88va_loader_handoff_",
        "pc88va_kernel_disk_read_",
        "pc88va_kernel_firmware_read_one_",
    }
    names = {item["name"] for item in symbols}
    missing = sorted(required - names)
    if missing or entry is None or stack is None or memory is None:
        raise EvidenceError(f"link map lacks required semantic evidence: {missing}")
    return {
        "entry_point": entry,
        "libraries": ["pc88va/build/platform.lib"],
        "memory": memory,
        "schema_version": 1,
        "stack": stack,
        "symbols": symbols,
    }


def collect(repo_root: Path, output: Path, component_commit: str, source_archive_sha256: str) -> None:
    repo_root = repo_root.resolve()
    target = repo_root / "pc88va"
    plan = read_json(target / "config/build-plan.json")
    stubs = read_json(target / "config/stubs.json")
    if plan.get("target_macros") != EXPECTED_MACROS:
        raise EvidenceError("target macro set differs from the PC-88VA contract")
    if output.exists():
        raise EvidenceError(f"evidence output already exists: {output}")

    tools: dict[str, dict[str, object]] = {}
    for name in TOOLS:
        resolved = shutil.which(name)
        if resolved is None:
            raise EvidenceError(f"required build tool is unavailable: {name}")
        tools[name] = identity(Path(resolved))

    objects = []
    for item in plan["objects"]:
        path = repo_root / item["object"]
        record = dict(item)
        record.update(identity(path))
        record["source_inputs"] = [identity(repo_root / source, source)
                                   for source in [item["source"], *item.get("includes", [])]]
        objects.append(record)

    artifact = target / "bin/KERNEL.SYS"
    alias = target / "bin/KVA8616.SYS"
    artifact_id = identity(artifact, "pc88va/bin/KERNEL.SYS")
    alias_id = identity(alias, "pc88va/bin/KVA8616.SYS")
    if artifact.read_bytes() != alias.read_bytes():
        raise EvidenceError("PC-88VA kernel alias differs from KERNEL.SYS")
    binary = artifact.read_bytes()
    markers = [stubs["probe_marker"], *(item["marker"] for item in stubs["interfaces"])]
    for marker in markers:
        if binary.count(marker.encode("ascii")) != 1:
            raise EvidenceError(f"stub marker multiplicity is not one: {marker}")
    service_markers = ["M08SERVICE:DISK_READ:PARAMETERIZED",
                       "M08SERVICE:LOADER_HANDOFF:ZERO_RELOCATION_MZ",
                       "M09SERVICE:CONSOLE_PUTC:TEXT_BIOS",
                       "M10SERVICE:MACHINE_INIT:SINGLE_SHOT",
                       "M10SERVICE:MEMORY:OWNED_ARENA",
                       "M10SERVICE:INTERRUPTS:VALIDATED_ADOPTION",
                       "M10SERVICE:CLOCK:OBSERVED_VRTC_EDGE",
                       "M10SERVICE:FATAL_STOP:CLI_HLT",
                       "M11SERVICE:CONSOLE_GETC:MATRIX_POLL",
                       "M12SERVICE:DISK_READ:RESIDENT"]
    for marker in service_markers:
        if binary.count(marker.encode("ascii")) != 1:
            raise EvidenceError("Implemented service marker multiplicity is not one")
    for marker in (b"M06STUB:DISK_READ:M08", b"M06STUB:LOADER_HANDOFF:M08", b"M06STUB:CONSOLE_OUTPUT:M09",
                   b"M06STUB:MACHINE_INIT:M10", b"M06STUB:MEMORY:M10", b"M06STUB:INTERRUPTS:M10",
                   b"M06STUB:TIMER_CLOCK:M10", b"M06STUB:FATAL_STOP:M10", b"M06STUB:CONSOLE_INPUT:M11"):
        if marker in binary:
            raise EvidenceError("Implemented service still contains its retired stub")

    link_rsp = target / "config/link.rsp"
    link_lines = link_rsp.read_text(encoding="ascii").splitlines()
    expected_link_lines = [
        "option map=build/KVA8616.map",
        "option statics",
        "option verbose",
        "format dos",
        "file build/startup.obj",
        "file build/loader_services.obj",
        "file build/console.obj",
        "file build/machine_services.obj",
        "file build/console_input.obj",
        "file build/resident_disk.obj",
        "library build/platform.lib",
        "name build/KVA8616.exe",
    ]
    if link_lines != expected_link_lines:
        raise EvidenceError("ordered link response differs from the reviewed contract")

    symbol_evidence = parse_link_map(target / "build/KVA8616.map")
    compile_manifest = {
        "commands": COMMANDS,
        "component_commit": component_commit,
        "generated_inputs": [],
        "libraries": [identity(target / "build/platform.lib", "pc88va/build/platform.lib")],
        "link_inputs_in_order": ["pc88va/build/startup.obj", "pc88va/build/loader_services.obj",
                                 "pc88va/build/console.obj", "pc88va/build/machine_services.obj",
                                 "pc88va/build/console_input.obj",
                                 "pc88va/build/resident_disk.obj",
                                 "pc88va/build/platform.lib"],
        "link_symbol_evidence_sha256": sha256_bytes(canonical_bytes(symbol_evidence)),
        "link_response": {**identity(link_rsp, "pc88va/config/link.rsp"), "lines": link_lines},
        "objects": objects,
        "schema_version": 1,
        "source_archive_sha256": source_archive_sha256,
        "source_date_epoch": int(os.environ.get("SOURCE_DATE_EPOCH", "0")),
        "target_macros": EXPECTED_MACROS,
        "tools": tools,
    }
    mz = parse_mz(artifact)
    if mz["relocation_count"] != 0 or mz["overlay"] != 0 or mz["checksum"] != 0:
        raise EvidenceError("Linked carrier is incompatible with the M08 zero-relocation policy")
    interface = {
        "artifact": artifact_id,
        "artifact_role": plan["artifact_role"],
        "binary": mz,
        "boot_drive_identity": {"status": "opaque_context_in_DX", "concrete_value": "private_overlay_only"},
        "cpu_mode": "8086-compatible-real-mode-code",
        "entry_symbol": "_pc88va_compile_only_entry",
        "firmware_entry_state": {"status": "private_overlay_only", "source": "accepted_M07_contract"},
        "initial_register_contract": {
            "zero": ["AX", "BX", "CX", "SI", "DI", "BP"],
            "DS_ES": "allocation_segment",
            "DX": "opaque_boot_drive_context",
            "SS_SP": "validated_MZ_stack",
            "CS_IP": "validated_MZ_entry",
            "IF_DF": "clear"
        },
        "loader_responsibilities": [
            "Locate the exact root entry and validate the complete FAT12 chain.",
            "Reject relocations, overlays, optional checksum and inconsistent header sizes.",
            "Copy and compare the body; initialize and check the required allocation tail.",
            "Validate entry, stack and all disjoint memory ownership intervals.",
            "Transfer once to the entry with the declared register contract.",
        ],
        "memory_model": "16-bit small model for C; segmented DOS MZ",
        "physical_load_address": {"status": "parameterized_private_overlay_only"},
        "relocation_policy": "zero_only_reject_nonzero",
        "schema_version": 2,
        "service_markers": service_markers,
        "stub_ledger_sha256": identity(target / "config/stubs.json")["sha256"],
        "target": "pc88va",
    }
    evidence = {
        "alias": alias_id,
        "artifact": artifact_id,
        "build_plan_sha256": identity(target / "config/build-plan.json")["sha256"],
        "compile_manifest_sha256": sha256_bytes(canonical_bytes(compile_manifest)),
        "kernel_interface_sha256": sha256_bytes(canonical_bytes(interface)),
        "schema_version": 1,
        "stub_count": len(stubs["interfaces"]),
        "stub_ledger_sha256": identity(target / "config/stubs.json")["sha256"],
        "symbol_evidence_sha256": sha256_bytes(canonical_bytes(symbol_evidence)),
    }
    write_json(output / "compile-manifest.json", compile_manifest)
    write_json(output / "kernel-interface.json", interface)
    write_json(output / "symbol-evidence.json", symbol_evidence)
    write_json(output / "build-evidence.json", evidence)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--component-commit", required=True)
    parser.add_argument("--source-archive-sha256", required=True)
    args = parser.parse_args()
    try:
        collect(args.repo_root, args.output, args.component_commit, args.source_archive_sha256)
    except (EvidenceError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
