# SPDX-License-Identifier: GPL-2.0-or-later
"""The VA medium-model build needs FAR calls from kernel assembly into C.

Upstream FreeDOS links resident C code into HMA_TEXT, so assembly may use a
NEAR call to it. The PC-88VA build keeps C bodies in separate code segments
that return with RETF, and runs HMA_TEXT from a relocated copy. A NEAR call
from assembly into an external C function therefore returns to the wrong
place and, from the copy, jumps to a meaningless offset.
"""
import pathlib
import re
import unittest

KERNEL = pathlib.Path(__file__).resolve().parents[2] / "kernel"
NEAR_CALL = re.compile(r"^\s*call\s+(_[A-Za-z_]\w*)\s*(;.*)?$", re.IGNORECASE)


class AssemblyFarCallTests(unittest.TestCase):
    def test_no_near_call_into_c_is_active_in_the_pc88va_build(self):
        texts = {path: path.read_text(encoding="latin-1")
                 for path in sorted(KERNEL.glob("*.asm"))}
        assembly = set()
        for text in texts.values():
            assembly.update(re.findall(r"^\s*(_\w+)\s*:", text, re.MULTILINE))
        missing = []
        for path, text in texts.items():
            # Track %ifdef/%ifndef PC88VA regions and their %else branches.
            stack = []
            for number, line in enumerate(text.splitlines(), 1):
                directive = line.strip().split(";")[0].split()
                word = directive[0].lower() if directive else ""
                if word in ("%if", "%ifdef", "%ifndef", "%ifidn", "%ifnidn"):
                    va = len(directive) > 1 and directive[1] == "PC88VA"
                    stack.append([word, va, False])
                elif word == "%else" and stack:
                    stack[-1][2] = True
                elif word == "%endif" and stack:
                    stack.pop()
                match = NEAR_CALL.match(line)
                if not match or match.group(1) in assembly:
                    continue
                active = True
                for kind, va, in_else in stack:
                    if va and ((kind == "%ifdef") == in_else):
                        active = False
                if active:
                    missing.append("%s:%d %s" % (path.name, number, match.group(1)))
        self.assertEqual(missing, [], "NEAR calls into C active in the VA build")

    def test_case_map_service_calls_its_c_body_far(self):
        text = (KERNEL / "nlssupt.asm").read_text(encoding="latin-1")
        self.assertRegex(text, r"%ifdef PC88VA[^%]*call\s+far\s+_DosUpChar")


if __name__ == "__main__":
    unittest.main()
