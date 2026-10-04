#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Structural tests for the compile-only PC-88VA target."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


TARGET = Path(__file__).resolve().parents[1]


class TargetTests(unittest.TestCase):
    def test_independent_selector(self) -> None:
        makefile = (TARGET / "makefile.wc").read_text(encoding="utf-8")
        self.assertIn("-DPC88VA", makefile)
        self.assertNotIn("-DNEC98", makefile)
        self.assertNotIn("-DIBMPC", makefile)

    def test_machine_selectors_are_mutually_exclusive(self) -> None:
        for relative in ("kernel/startup.asm", "kernel/stubs.c", "boot/disk_read.inc", "boot/mz_validate.inc"):
            text = (TARGET / relative).read_text(encoding="utf-8")
            self.assertIn("NEC98", text)
            self.assertIn("IBMPC", text)
            self.assertIn("PC88VA", text)

    def test_link_inputs_are_explicit_and_not_nec98(self) -> None:
        lines = (TARGET / "config/link.rsp").read_text(encoding="ascii").splitlines()
        self.assertEqual(lines.count("file build/startup.obj"), 1)
        self.assertEqual(lines.count("file build/loader_services.obj"), 1)
        self.assertEqual(lines.count("library build/platform.lib"), 1)
        self.assertFalse(any("nec98" in line.lower() or "ibmpc" in line.lower() for line in lines))

    def test_common_linker_keeps_pc88va_m16_aliases_optional(self) -> None:
        linker = (TARGET.parent / "kernel/kernel.ld").read_text(encoding="utf-8")
        self.assertIn("PROVIDE(PC88VA_M16_PROBE_READ = 0);", linker)
        self.assertIn("PROVIDE(PC88VA_M16_SET_PROFILE = 0);", linker)

    def test_extended_bpb_label_is_pc88va_only(self) -> None:
        source = (TARGET.parent / "kernel/dsk.c").read_text(encoding="utf-8")
        self.assertRegex(source, r"#ifdef PC88VA\s+read_extended_bpb:\s+#endif")

    def test_object_plan_has_closed_classifications(self) -> None:
        plan = json.loads((TARGET / "config/build-plan.json").read_text(encoding="utf-8"))
        allowed = {"common-core", "shared-portable", "pc88va-owned", "temporary-fail-closed-stub"}
        self.assertTrue(plan["objects"])
        self.assertTrue(all(item["classification"] in allowed for item in plan["objects"]))
        self.assertFalse(any("/nec98/" in item["source"] or "/ibmpc/" in item["source"] for item in plan["objects"]))

    def test_stub_ledger_matches_source_and_fails_closed(self) -> None:
        ledger = json.loads((TARGET / "config/stubs.json").read_text(encoding="utf-8"))
        source = (TARGET / "kernel/stubs.c").read_text(encoding="utf-8")
        self.assertEqual(ledger["failure_return"], -1)
        self.assertEqual(len(ledger["interfaces"]), 1)
        self.assertEqual({item["removal_milestone"] for item in ledger["interfaces"]}, {"M17"})
        for item in ledger["interfaces"]:
            self.assertRegex(item["removal_milestone"], r"^M(?:0[789]|1[0-7])$")
            self.assertIn(item["name"], source)
            self.assertIn(item["marker"], source)
        self.assertEqual(source.count("return PC88VA_UNAVAILABLE;"), 1)

    def test_only_m08_stubs_replaced_by_shared_cores(self) -> None:
        source = (TARGET / "kernel/stubs.c").read_text(encoding="utf-8")
        services = (TARGET / "kernel/loader_services.asm").read_text(encoding="utf-8")
        for name in ("pc88va_disk_read", "pc88va_loader_handoff"):
            self.assertNotIn(name, source)
            self.assertIn("global " + name + "_", services)
            self.assertIn("call " + name + "_core", services)
        self.assertIn('%include "disk_read.inc"', services)
        self.assertIn('%include "loader_handoff.inc"', services)

    def test_stubs_have_no_hardware_access(self) -> None:
        text = (TARGET / "kernel/stubs.c").read_text(encoding="utf-8").lower()
        forbidden = ("__int__", " out ", " in ", "outp(", "inp(", "firmware")
        self.assertFalse(any(token in text for token in forbidden))
        # ASMCFUNC is a declaration macro, not inline assembly.  Match the
        # standalone source token so the bridge's calling-convention marker
        # does not trigger this hardware-access check.
        self.assertIsNone(re.search(r"\basm\b", text))

    def test_no_ambient_time_macros(self) -> None:
        for path in sorted(TARGET.rglob("*")):
            if path.is_file() and path.suffix.lower() in {".c", ".h", ".asm", ".wc", ".rsp"}:
                text = path.read_text(encoding="utf-8")
                self.assertIsNone(re.search(r"__(?:DATE|TIME|TIMESTAMP)__", text))


if __name__ == "__main__":
    unittest.main()
