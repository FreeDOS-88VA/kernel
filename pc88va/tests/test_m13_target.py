#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""ROM-free structural checks for the M13 common-core target plan."""

import json
import unittest
from pathlib import Path


TARGET = Path(__file__).resolve().parents[1]


class M13TargetTests(unittest.TestCase):
    def test_m13_plan_links_common_core(self):
        plan = json.loads((TARGET / "config/m13-build-plan.json").read_text())
        self.assertEqual(plan["milestone"], "M13")
        common = {item["source"] for item in plan["objects"] if item["classification"] == "common-core"}
        for source in ("kernel/main.c", "kernel/io.asm", "kernel/blockio.c", "kernel/fatfs.c", "kernel/inthndlr.c", "kernel/memmgr.c", "kernel/task.c", "kernel/procsupt.asm"):
            self.assertIn(source, common)
        self.assertNotIn("nec98/", " ".join(item["source"] for item in plan["objects"]))
        self.assertNotIn("ibmpc/", " ".join(item["source"] for item in plan["objects"]))

    def test_m13_makefile_has_real_entry_and_no_foreign_selector(self):
        text = (TARGET / "makefile.m13.wc").read_text()
        self.assertIn("COMMON_C=", text)
        self.assertIn("main", text)
        self.assertIn("inthndlr", text)
        self.assertIn("m13_platform.asm", text)
        self.assertIn("-DPC88VA", text)
        self.assertNotIn("-DNEC98", text)
        self.assertNotIn("-DIBMPC", text)

    def test_m13_read_contract_remains_reachable_after_m14_transition(self):
        text = (TARGET / "kernel/m13_platform.asm").read_text()
        # M13's historical read-only image remains the qualification control;
        # the active M14 source intentionally adds a separate VA write path.
        self.assertIn("global FL_READ", text)
        self.assertIn("global FL_WRITE", text)
        self.assertIn("global FL_VERIFY", text)
        self.assertIn("pc88va_kernel_disk_read_", text)

    def test_m12_target_remains_compile_only_contract(self):
        text = (TARGET / "makefile.wc").read_text()
        self.assertIn("bin/KERNEL.SYS", text)
        self.assertNotIn("makefile.m13.wc", text)


if __name__ == "__main__":
    unittest.main()
