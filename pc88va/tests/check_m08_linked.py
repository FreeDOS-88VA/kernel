# SPDX-License-Identifier: GPL-2.0-or-later
"""Execute the actual linked Watcom carrier and its two M08 C-call adapters."""
import argparse
import pathlib
import re
import struct
import unittest

import unicorn
from unicorn import Uc, UC_ARCH_X86, UC_MODE_16, UC_HOOK_CODE
from unicorn.x86_const import (
    UC_X86_REG_AX, UC_X86_REG_CS, UC_X86_REG_DS, UC_X86_REG_SS,
    UC_X86_REG_SP, UC_X86_REG_EFLAGS,
)
import test_m08_disk as disk
import test_m08_mz as mz
import test_m08_metadata as metadata

BUILD = None


def linked():
    if unicorn.__version__ != "2.1.4":
        raise RuntimeError("M08 execution QA requires pinned Unicorn 2.1.4")
    image = (BUILD / "KVA8616.exe").read_bytes()
    header = struct.unpack_from("<14H", image)
    if header[0] != 0x5a4d or header[3] != 0 or header[13] != 0:
        raise ValueError("Linked carrier is not a zero-relocation MZ")
    symbols = {}
    for line in (BUILD / "KVA8616.map").read_text().splitlines():
        match = re.fullmatch(r"([0-9A-Fa-f]{4}):([0-9A-Fa-f]{4})[+*s ]*\s+(\S+)", line)
        if match:
            symbols[match[3]] = int(match[1], 16) * 16 + int(match[2], 16)
    return image[header[4] * 16:], header, symbols


class LinkedDiskTests(unittest.TestCase):
    watcom = True
    execute = disk.DiskCoreTests.execute

    @classmethod
    def setUpClass(cls):
        cls.code, _, symbols = linked()
        if len(cls.code) >= disk.CALLBACK:
            raise ValueError("Synthetic callback fixture overlaps linked carrier")
        cls.entry_offset = symbols["pc88va_disk_read_"]

    test_first_sector_and_drive_context = disk.DiskCoreTests.test_first_sector_and_drive_context
    test_track_and_head_crossings = disk.DiskCoreTests.test_track_and_head_crossings
    test_invalid_contract_has_no_io = disk.DiskCoreTests.test_invalid_contract_has_no_io
    test_short_and_oversized_completion_are_errors = disk.DiskCoreTests.test_short_and_oversized_completion_are_errors


class LinkedHandoffTests(unittest.TestCase):
    watcom = True
    transforms = True
    handoff = True
    execute = mz.MzValidationTests.execute

    @classmethod
    def setUpClass(cls):
        cls.code, _, symbols = linked()
        cls.entry_offset = symbols["pc88va_loader_handoff_"]

    test_valid_body_allocation_entry_stack = mz.MzValidationTests.test_valid_body_allocation_entry_stack
    test_exact_page_size_and_relative_segments = mz.MzValidationTests.test_exact_page_size_and_relative_segments
    test_relocation_policy_is_fail_closed = mz.MzValidationTests.test_relocation_policy_is_fail_closed
    test_body_corruption_is_detected = mz.MzTransformTests.test_body_corruption_is_detected
    test_zero_tail_corruption_is_detected = mz.MzTransformTests.test_zero_tail_corruption_is_detected

    def test_actual_linked_carrier_is_accepted_and_entered(self):
        status, final = self.execute((BUILD / "KVA8616.exe").read_bytes())
        self.assertEqual(status, 0)
        self.assertEqual(final[17:19], (1, 1))


class LinkedEntryTests(unittest.TestCase):
    def test_original_entry_reaches_fail_closed_platform_probe(self):
        body, header, symbols = linked()
        base = 0x2000  # Project-authored ROM-free placement only.
        machine = Uc(UC_ARCH_X86, UC_MODE_16)
        machine.mem_map(0, 0x100000)
        machine.mem_write(base * 16, body)
        machine.reg_write(UC_X86_REG_CS, base + header[11])
        machine.reg_write(UC_X86_REG_DS, base)
        machine.reg_write(UC_X86_REG_SS, base + header[7])
        machine.reg_write(UC_X86_REG_SP, header[8])
        machine.reg_write(UC_X86_REG_EFLAGS, 0x602)
        stop = base * 16 + symbols["_pc88va_compile_only_fatal_stop"]
        reached = []

        def hook(cpu, address, size, _):
            if address == stop:
                reached.append(True)
                cpu.emu_stop()

        machine.hook_add(UC_HOOK_CODE, hook)
        machine.emu_start((base + header[11]) * 16 + header[10], 0xfffff, count=1000)
        self.assertEqual(reached, [True])
        self.assertEqual(machine.reg_read(UC_X86_REG_AX), 0xffff)
        self.assertEqual(machine.reg_read(UC_X86_REG_SP), header[8])
        self.assertEqual(machine.reg_read(UC_X86_REG_EFLAGS) & 0x600, 0)


class LinkedBootPipelineTests(metadata.BootHandoffPipelineTests):
    def test_actual_carrier_from_fragmented_disk_to_entry(self):
        image = (BUILD / "KVA8616.exe").read_bytes()
        status, stage, reads = self.execute(kernel=image)
        count = (len(image) + 511) // 512
        clusters = ([2, 4, 3] + list(range(5, count + 2)))[:count]
        self.assertEqual((status, stage), (0, 3))
        self.assertEqual(reads, [0, 1, 2, 3, 4] + [c + 3 for c in clusters])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-dir", type=pathlib.Path, required=True)
    args, remaining = parser.parse_known_args()
    BUILD = args.build_dir
    unittest.main(argv=[__file__, *remaining])
