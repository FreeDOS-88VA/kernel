#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Structural M14 checks for the PC-88VA write boundary."""

from __future__ import annotations

import unittest
from pathlib import Path


TARGET = Path(__file__).resolve().parents[1]


class M14TargetTests(unittest.TestCase):
    def test_write_core_is_shared_with_the_resident_entry(self):
        resident = (TARGET / "kernel/resident_disk.asm").read_text(encoding="utf-8")
        core = (TARGET / "boot/disk_write.inc").read_text(encoding="utf-8")
        adapter = (TARGET / "kernel/m13_platform.asm").read_text(encoding="utf-8")
        self.assertIn('%include "disk_write.inc"', resident)
        self.assertIn("pc88va_disk_write_core", resident)
        self.assertIn("call pc88va_disk_write_core", resident)
        self.assertIn("pc88va_kernel_firmware_write_one_", resident)
        self.assertIn("global FL_WRITE", adapter)
        self.assertIn("global FL_VERIFY", adapter)
        self.assertIn("8201h", resident)
        self.assertIn("RD_COMPLETED", core)

    def test_write_boundary_is_validated_and_bounded(self):
        core = (TARGET / "boot/disk_write.inc").read_text(encoding="utf-8")
        for text in ("RD_VERSION", "RD_TOTAL_SECTORS", "RD_COUNT",
                     "RD_CAPACITY", "RD_CURRENT_OFFSET", "RD_RETRIES_LEFT",
                     "DISK_RANGE", "DISK_CAPACITY", "DISK_SHORT"):
            self.assertIn(text, core)
        adapter = (TARGET / "kernel/m13_platform.asm").read_text(encoding="utf-8")
        self.assertIn("call pc88va_validate_buffer_size", adapter)
        self.assertIn("mov bx, dx\n        mov ax, cx", adapter)
        self.assertIn("add ax, bx\n        jnc .buffer_offset_valid", adapter)
        self.assertIn("add ax, cx\n        jc .write_bad", adapter)
        self.assertIn("add ax, cx\n        jc .verify_bad", adapter)
        self.assertIn("retf 14", adapter)

    def test_va_status_and_change_contract_are_not_silent_success(self):
        adapter = (TARGET / "kernel/m13_platform.asm").read_text(encoding="utf-8")
        self.assertIn("mov ah, 09h", adapter)
        self.assertIn("pc88va_map_va_write_status", adapter)
        self.assertIn("mov ax, 3", adapter)
        self.assertIn("mov ax, 80h", adapter)
        self.assertIn("mov ax, 10h", adapter)

    def test_common_media_and_partial_write_boundaries_are_explicit(self):
        initdisk = (TARGET.parent / "kernel/initdisk.c").read_text(encoding="utf-8")
        dsk = (TARGET.parent / "kernel/dsk.c").read_text(encoding="utf-8")
        fatfs = (TARGET.parent / "kernel/fatfs.c").read_text(encoding="utf-8")
        self.assertIn("make_ddt(&nddt[1], 1, 1, DF_NOACCESS)", initdisk)
        self.assertIn("rp->r_count > size - start", dsk)
        self.assertIn("retry_limit = 1", dsk)
        self.assertIn("count > 1", dsk)
        self.assertIn("VOID media_invalidate(", fatfs)
        self.assertIn("s->sft_flags |= SFT_FSTALE", fatfs)

    def test_resident_write_object_dependency_is_explicit(self):
        makefile = (TARGET / "makefile.m13.wc").read_text(encoding="utf-8")
        self.assertIn("boot/disk_write.inc", makefile)

    def test_va_does_not_use_the_ibm_diskette_parameter_vector(self):
        dsk = (TARGET.parent / "kernel/dsk.c").read_text(encoding="utf-8")
        before, after = dsk.split("getvec(0x1e)", 1)
        guard = before.rsplit("#if", 1)[1]
        self.assertTrue(guard.startswith(" !defined(PC88VA)"))
        self.assertNotIn("#endif", guard)
        self.assertIn("fl_reset(driveno);", after.split("#endif", 1)[0])


if __name__ == "__main__":
    unittest.main()
