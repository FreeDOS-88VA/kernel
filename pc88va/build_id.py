#!/usr/bin/env python3
"""Generate the PC-88VA kernel banner identity from the source commit."""

import argparse
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = "$Format:%H$"


def git_output(*args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def resolve_build_id(value: str) -> str:
    value = value.strip()
    if value == TEMPLATE:
        if git_output("status", "--porcelain", "--untracked-files=no"):
            raise ValueError("cannot stamp a dirty fdkernel working tree")
        value = git_output("rev-parse", "--verify", "HEAD^{commit}")
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("expected a full 40-character fdkernel SHA-1 commit ID")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("build/pc88va_build_id.h"),
        help="generated C header path (default: build/pc88va_build_id.h)",
    )
    args = parser.parse_args()
    try:
        build_id = resolve_build_id((Path(__file__).with_name("build_id.txt")).read_text())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="ascii", newline="\n") as output:
            output.write(f'#define PC88VA_BUILD_ID "{build_id}"\n')
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        print(f"PC-88VA build identity: {error}", file=sys.stderr)
        return 2
    print(f"PC-88VA build identity: {build_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
