# SPDX-License-Identifier: GPL-2.0-or-later
"""Execute the real shared disk core with project-authored far-call fixtures."""
import pathlib
import struct
import subprocess
import tempfile
import unittest

import unicorn
from unicorn import Uc, UC_ARCH_X86, UC_MODE_16, UC_HOOK_CODE
from unicorn.x86_const import (
    UC_X86_REG_AX, UC_X86_REG_BX, UC_X86_REG_CX, UC_X86_REG_DX,
    UC_X86_REG_SI, UC_X86_REG_DI, UC_X86_REG_BP, UC_X86_REG_SP,
    UC_X86_REG_CS, UC_X86_REG_DS, UC_X86_REG_ES, UC_X86_REG_SS,
    UC_X86_REG_EFLAGS,
)

BOOT = pathlib.Path(__file__).resolve().parents[1] / "boot"
CODE_SEG, DATA_SEG, STACK_SEG, BUFFER_SEG = 0x1200, 0x2800, 0x3800, 0x5800
REQUEST, CALLBACK, STOP = 0x1400, 0x1800, 0x1f00


class DiskCoreTests(unittest.TestCase):
    entry_offset = 0
    watcom = False
    @classmethod
    def setUpClass(cls):
        if unicorn.__version__ != "2.1.4":
            raise RuntimeError("M08 execution QA requires pinned Unicorn 2.1.4")
        cls.temporary = tempfile.TemporaryDirectory(prefix="pc88va-m08-unit-")
        cls.directory = pathlib.Path(cls.temporary.name)
        cls.binary = cls.directory / "disk.bin"
        cls.command = ["nasm", "-f", "bin", "-DPC88VA", "-I", str(BOOT) + "/",
                       "-o", str(cls.binary), str(BOOT / "disk_read.inc")]
        subprocess.run(cls.command, check=True, capture_output=True)
        cls.code = cls.binary.read_bytes()
        assert len(cls.code) < CALLBACK

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def execute(self, updates=None, results=None, clobber=False):
        # Entirely synthetic geometry and placement, unrelated to private media.
        words = [1, 0, 1, 0x300, BUFFER_SEG, 0x4000, 72, 6, 2, 512,
                 0x321, CALLBACK, CODE_SEG, 0] + [0] * 10
        for index, value in (updates or {}).items():
            words[index] = value
        machine = Uc(UC_ARCH_X86, UC_MODE_16)
        machine.mem_map(0, 0x110000)
        machine.mem_write(CODE_SEG * 16, self.code)
        machine.mem_write(CODE_SEG * 16 + CALLBACK, b"\xcb")  # Fixture far return.
        machine.mem_write(DATA_SEG * 16 + REQUEST, struct.pack("<24H", *words))
        stack = 0x3000
        machine.mem_write(STACK_SEG * 16 + stack, struct.pack("<H", STOP))
        preserved = {
            UC_X86_REG_BX: 0x1234, UC_X86_REG_CX: 0x2345,
            UC_X86_REG_DX: 0x3456, UC_X86_REG_SI: REQUEST,
            UC_X86_REG_DI: 0x4567, UC_X86_REG_BP: 0x5678,
            UC_X86_REG_DS: DATA_SEG, UC_X86_REG_ES: 0x6800,
            UC_X86_REG_SS: STACK_SEG,
        }
        if self.watcom:
            preserved[UC_X86_REG_SI] = 0x6789
            machine.reg_write(UC_X86_REG_AX, REQUEST)
        for register, value in preserved.items():
            machine.reg_write(register, value)
        machine.reg_write(UC_X86_REG_CS, CODE_SEG)
        machine.reg_write(UC_X86_REG_SP, stack)
        machine.reg_write(UC_X86_REG_EFLAGS, 0x602)
        calls = []
        outcomes = iter(results or [])

        def callback(cpu, address, size, _):
            if address != CODE_SEG * 16 + CALLBACK:
                return
            request = struct.unpack("<24H", cpu.mem_read(DATA_SEG * 16 + REQUEST, 48))
            calls.append((request[21], request[16], request[17], request[18],
                          request[19], request[20], request[10]))
            status, count = next(outcomes, (0, request[9]))
            if status == 0:
                destination = request[20] * 16 + request[19]
                cpu.mem_write(destination, bytes([request[21] & 255]) * min(count, request[9]))
            if clobber:
                for register in preserved:
                    if register != UC_X86_REG_SS:
                        cpu.reg_write(register, 0x7654)
            cpu.reg_write(UC_X86_REG_AX, status)
            cpu.reg_write(UC_X86_REG_CX, count)

        machine.hook_add(UC_HOOK_CODE, callback)
        machine.emu_start(CODE_SEG * 16 + self.entry_offset, CODE_SEG * 16 + STOP, count=50000)
        self.assertEqual(machine.reg_read(UC_X86_REG_SP), stack + 2, "bounded return")
        for register, value in preserved.items():
            self.assertEqual(machine.reg_read(register), value, "caller register preserved")
        flags = machine.reg_read(UC_X86_REG_EFLAGS)
        result = machine.reg_read(UC_X86_REG_AX)
        self.assertEqual(flags & ~1, 0x602, "only carry may change")
        self.assertEqual(flags & 1, int(result != 0))
        final = struct.unpack("<24H", machine.mem_read(DATA_SEG * 16 + REQUEST, 48))
        return result, calls, final, machine

    def test_first_sector_and_drive_context(self):
        status, calls, final, _ = self.execute()
        self.assertEqual(status, 0)
        self.assertEqual(calls, [(0, 0, 0, 1, 0x300, BUFFER_SEG, 0x321)])
        self.assertEqual(final[14], 512)

    def test_last_sector(self):
        status, calls, _, _ = self.execute({1: 71})
        self.assertEqual(status, 0)
        self.assertEqual(calls[0][1:4], (5, 1, 6))

    def test_track_and_head_crossings(self):
        status, calls, final, machine = self.execute({1: 5, 2: 8})
        self.assertEqual(status, 0)
        self.assertEqual([c[1:4] for c in calls],
                         [(0, 0, 6), (0, 1, 1), (0, 1, 2), (0, 1, 3),
                          (0, 1, 4), (0, 1, 5), (0, 1, 6), (1, 0, 1)])
        self.assertEqual(final[14], 4096)
        expected = b"".join(bytes([lba]) * 512 for lba in range(5, 13))
        self.assertEqual(bytes(machine.mem_read(BUFFER_SEG * 16 + 0x300, 4096)), expected)

    def test_invalid_contract_has_no_io(self):
        for update in ({0: 2}, {7: 0}, {8: 0}, {6: 0}, {9: 513}, {9: 64},
                       {9: 8192}, {7: 256}, {8: 257}, {11: 0, 12: 0}, {13: 4}):
            with self.subTest(update=update):
                status, calls, _, _ = self.execute(update)
                self.assertEqual((status, calls), (1, []))

    def test_zero_count(self):
        status, calls, _, _ = self.execute({2: 0})
        self.assertEqual((status, calls), (2, []))

    def test_range_and_overflow(self):
        for update in ({1: 72}, {1: 71, 2: 2}, {1: 65530, 2: 10, 6: 65535},
                       {4: 65535, 3: 0x100}):
            with self.subTest(update=update):
                status, calls, _, _ = self.execute(update)
                self.assertEqual((status, calls), (2, []))

    def test_capacity_and_segment_window(self):
        for update in ({5: 511}, {2: 128, 6: 512}, {3: 0xff00}):
            with self.subTest(update=update):
                status, calls, _, _ = self.execute(update)
                self.assertEqual((status, calls), (3, []))

    def test_short_and_oversized_completion_are_errors(self):
        for count in (0, 511, 513):
            with self.subTest(count=count):
                status, calls, final, _ = self.execute(results=[(0, count)])
                self.assertEqual(status, 4)
                self.assertEqual(len(calls), 1)
                self.assertEqual(final[14], 0)

    def test_zero_retry_ceiling(self):
        status, calls, final, _ = self.execute(results=[(7, 0)])
        self.assertEqual((status, len(calls), final[15]), (5, 1, 7))

    def test_retry_exhaustion(self):
        status, calls, final, _ = self.execute({13: 2}, [(7, 0)] * 3)
        self.assertEqual((status, len(calls), final[14]), (5, 3, 0))
        self.assertEqual(len(set(calls)), 1)

    def test_retry_then_success_and_partial_error(self):
        status, calls, final, _ = self.execute({13: 1}, [(7, 0), (0, 512)])
        self.assertEqual((status, len(calls), final[14]), (0, 2, 512))
        status, calls, final, _ = self.execute({2: 2}, [(0, 512), (7, 0)])
        self.assertEqual((status, len(calls), final[14]), (5, 2, 512))

    def test_adapter_register_clobbers_are_contained(self):
        status, calls, final, _ = self.execute({2: 3}, clobber=True)
        self.assertEqual((status, len(calls), final[14]), (0, 3, 1536))

    def test_two_assemblies_identical(self):
        subprocess.run(self.command, check=True, capture_output=True)
        self.assertEqual(self.binary.read_bytes(), self.code)

    def test_contradictory_selector_rejected(self):
        for selector in ("NEC98", "IBMPC"):
            result = subprocess.run(self.command + ["-D" + selector], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b"Contradictory machine-family selection", result.stderr)


if __name__ == "__main__":
    unittest.main()
