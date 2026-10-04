# SPDX-License-Identifier: GPL-2.0-or-later
"""Execute the zero-relocation MZ validator using project-authored inputs."""
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
    UC_X86_REG_EFLAGS, UC_X86_REG_IP,
)

BOOT = pathlib.Path(__file__).resolve().parents[1] / "boot"
CODE, DATA, STACK, FILE, LOAD = 0x1200, 0x2800, 0x3800, 0x4800, 0x6800
REQUEST, TABLE, STOP = 0x1400, 0x1600, 0x1f00


def carrier(body_size=1027, updates=None):
    size = 32 + body_size
    words = [0x5a4d, size % 512, (size + 511) // 512, 0, 2,
             16, 0xffff, 0, 1024, 0, 0, 0, 32, 0, 0, 0]
    for index, value in (updates or {}).items():
        words[index] = value
    return struct.pack("<16H", *words) + bytes((i * 13 + 7) % 256 for i in range(body_size))


class MzValidationTests(unittest.TestCase):
    module = "mz_validate.inc"
    transforms = False
    handoff = False
    entry_offset = 0
    watcom = False

    @classmethod
    def setUpClass(cls):
        if unicorn.__version__ != "2.1.4":
            raise RuntimeError("M08 execution QA requires pinned Unicorn 2.1.4")
        cls.temporary = tempfile.TemporaryDirectory(prefix="pc88va-m08-mz-")
        target = pathlib.Path(cls.temporary.name) / "mz.bin"
        subprocess.run(["nasm", "-f", "bin", "-DPC88VA", "-I", str(BOOT) + "/",
                        "-o", str(target), str(BOOT / cls.module)],
                       check=True, capture_output=True)
        cls.code = target.read_bytes()
        second = target.with_name("mz-second.bin")
        subprocess.run(["nasm", "-f", "bin", "-DPC88VA", "-I", str(BOOT) + "/",
                        "-o", str(second), str(BOOT / cls.module)],
                       check=True, capture_output=True)
        if second.read_bytes() != cls.code:
            raise AssertionError("Two clean MZ assembly outputs differ")

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def execute(self, image=None, updates=None, intervals=None, corrupt=None):
        image = carrier() if image is None else image
        intervals = [(CODE * 16, (CODE + 0x200) * 16),
                     (DATA * 16, (DATA + 0x200) * 16),
                     (STACK * 16, (STACK + 0x400) * 16)] if intervals is None else intervals
        words = [1, 0x300, FILE, len(image), LOAD, 0x4000, 256,
                 0x1234, TABLE, len(intervals)] + [0] * 17
        for index, value in (updates or {}).items():
            words[index] = value
        machine = Uc(UC_ARCH_X86, UC_MODE_16)
        machine.mem_map(0, 0x110000)
        machine.mem_write(CODE * 16, self.code)
        machine.mem_write(DATA * 16 + REQUEST, struct.pack("<27H", *words))
        machine.mem_write(DATA * 16 + TABLE,
                          b"".join(struct.pack("<II", *interval) for interval in intervals) or b"\0")
        machine.mem_write(words[2] * 16 + words[1], image)
        sentinel = bytes([0xa5]) * 0x4000
        machine.mem_write(LOAD * 16, sentinel)
        machine.mem_write(STACK * 16 + 0x3000, struct.pack("<H", STOP))
        registers = {
            UC_X86_REG_BX: 0x1234, UC_X86_REG_CX: 0x2345, UC_X86_REG_DX: 0x3456,
            UC_X86_REG_SI: REQUEST, UC_X86_REG_DI: 0x4567, UC_X86_REG_BP: 0x5678,
            UC_X86_REG_DS: DATA, UC_X86_REG_ES: 0x7800, UC_X86_REG_SS: STACK,
        }
        if self.watcom:
            registers[UC_X86_REG_SI] = 0x6789
            machine.reg_write(UC_X86_REG_AX, REQUEST)
        for register, value in registers.items():
            machine.reg_write(register, value)
        machine.reg_write(UC_X86_REG_CS, CODE)
        machine.reg_write(UC_X86_REG_SP, 0x3000)
        machine.reg_write(UC_X86_REG_EFLAGS, 0x602)
        injected, reached = [False], [False]
        header = struct.unpack("<16H", (image + bytes(32))[:32])
        entry_address = (words[4] + header[11]) * 16 + header[10]

        def hook(cpu, address, size, _):
            if self.handoff and address == entry_address:
                reached[0] = True
                cpu.emu_stop()
                return
            opcode = b"\xf3\xa6" if corrupt == "body" else b"\xf3\xae"
            if corrupt and not injected[0] and bytes(cpu.mem_read(address, 2)) == opcode:
                offset = 0 if corrupt == "body" else len(image) - 32
                cpu.mem_write(words[4] * 16 + offset, b"\xff")
                injected[0] = True

        if corrupt or self.handoff:
            machine.hook_add(UC_HOOK_CODE, hook)
        machine.emu_start(CODE * 16 + self.entry_offset, CODE * 16 + STOP, count=100000)
        status = machine.reg_read(UC_X86_REG_AX)
        if self.handoff and status == 0:
            self.assertTrue(reached[0], "one-way transfer must reach the actual header entry")
            expected_registers = {
                UC_X86_REG_AX: 0, UC_X86_REG_BX: 0, UC_X86_REG_CX: 0,
                UC_X86_REG_DX: words[7], UC_X86_REG_SI: 0, UC_X86_REG_DI: 0,
                UC_X86_REG_BP: 0, UC_X86_REG_DS: words[4], UC_X86_REG_ES: words[4],
                UC_X86_REG_SS: words[4] + header[7], UC_X86_REG_SP: header[8],
                UC_X86_REG_CS: words[4] + header[11], UC_X86_REG_IP: header[10],
                UC_X86_REG_EFLAGS: 2,
            }
            for register, value in expected_registers.items():
                self.assertEqual(machine.reg_read(register), value)
        else:
            self.assertFalse(reached[0])
            self.assertEqual(machine.reg_read(UC_X86_REG_SP), 0x3002)
            for register, value in registers.items():
                self.assertEqual(machine.reg_read(register), value)
            self.assertEqual(machine.reg_read(UC_X86_REG_EFLAGS), 0x602 | int(status != 0))
        self.assertEqual(bytes(machine.mem_read(words[2] * 16 + words[1], len(image))), image)
        final = struct.unpack("<27H", machine.mem_read(DATA * 16 + REQUEST, 54))
        self.assertEqual(final[:10], tuple(words[:10]))
        self.assertEqual(final[17], int(status in (0, 48)))
        self.assertEqual(final[18], int(self.transforms and status == 0))
        expected = sentinel
        if self.transforms and status in (0, 48):
            body = image[final[10]:]
            expected = body + bytes(final[12] - len(body)) + sentinel[final[12]:]
            if self.handoff and status == 0:
                offset = header[7] * 16 + header[8] - 4
                frame = struct.pack("<HH", final[13], final[14])
                expected = expected[:offset] + frame + expected[offset + 4:]
            if corrupt:
                self.assertTrue(injected[0])
                offset = 0 if corrupt == "body" else len(body)
                expected = expected[:offset] + b"\xff" + expected[offset + 1:]
        self.assertEqual(bytes(machine.mem_read(LOAD * 16, len(sentinel))), expected)
        return status, final

    def test_valid_body_allocation_entry_stack(self):
        status, final = self.execute()
        self.assertEqual(status, 0)
        self.assertEqual(final[10:17], (32, 1027, 1296, 0, LOAD, 1024, LOAD))

    def test_exact_page_size_and_relative_segments(self):
        status, final = self.execute(carrier(1504, {7: 16, 8: 1024, 10: 3, 11: 2}))
        self.assertEqual(status, 0)
        self.assertEqual(final[13:17], (3, LOAD + 2, 1024, LOAD + 16))

    def test_invalid_context(self):
        for updates in ({0: 2}, {6: 0}, {6: 1}, {9: 0}, {9: 17}, {8: 0xfff8}):
            with self.subTest(updates=updates):
                self.assertEqual(self.execute(updates=updates)[0], 40)

    def test_bad_magic_overlay_header_or_table(self):
        for header in ({0: 0}, {13: 1}, {9: 1}, {4: 0}, {4: 1}, {4: 100},
                       {4: 4096}, {12: 27}, {12: 33}):
            with self.subTest(header=header):
                self.assertEqual(self.execute(carrier(updates=header))[0], 41)
        self.assertEqual(self.execute(bytes(31))[0], 41)

    def test_relocation_policy_is_fail_closed(self):
        for count in (1, 0xffff):
            self.assertEqual(self.execute(carrier(updates={3: count}))[0], 43)

    def test_encoded_size_must_equal_file(self):
        for header in ({1: 512}, {1: 0}, {2: 0}, {2: 4}, {2: 0xffff}):
            with self.subTest(header=header):
                self.assertEqual(self.execute(carrier(updates=header))[0], 42)
        for updates in ({1: 0xff00}, {2: 0xffff}, {3: 1058}):
            with self.subTest(updates=updates):
                self.assertEqual(self.execute(updates=updates)[0], 42)

    def test_allocation_capacity_min_max_and_wrap(self):
        for header in ({5: 2, 6: 1}, {5: 4095}, {5: 0xffff}):
            self.assertEqual(self.execute(carrier(updates=header))[0], 44)
        self.assertEqual(self.execute(updates={5: 1295})[0], 44)
        self.assertEqual(self.execute(updates={4: 0xfff0})[0], 44)

    def test_entry_outside_initialized_body(self):
        for header in ({10: 1027}, {11: 0xffff}, {10: 0xffff, 11: 1}):
            self.assertEqual(self.execute(carrier(updates=header))[0], 45)

    def test_stack_outside_allocation_or_segment_reserve(self):
        for header in ({8: 1297}, {8: 0}, {8: 255}, {7: 20, 8: 128},
                       {7: 0xffff}, {7: 1, 8: 0xffff}):
            with self.subTest(header=header):
                self.assertEqual(self.execute(carrier(updates=header))[0], 46)

    def test_entry_cannot_overlap_reserved_stack(self):
        for ip in (768, 800, 1023):
            self.assertEqual(self.execute(carrier(updates={10: ip}))[0], 46)
        for ip in (767, 1024):
            self.assertEqual(self.execute(carrier(updates={10: ip}))[0], 0)

    def test_source_destination_alias_rejected(self):
        # A different segment spelling still denotes an overlapping physical range.
        self.assertEqual(self.execute(updates={4: FILE + 0x20})[0], 47)

    def test_protected_interval_overlap_and_invalid_intervals(self):
        start, end = LOAD * 16, LOAD * 16 + 1296
        for interval in ((start, end), (start - 1, start + 1), (end - 1, end + 1),
                         (start - 100, end + 100), (7, 7), (9, 8), (0, 0x100001)):
            with self.subTest(interval=interval):
                self.assertEqual(self.execute(intervals=[interval])[0], 47)

    def test_half_open_touching_intervals_allowed(self):
        start, end = LOAD * 16, LOAD * 16 + 1296
        self.assertEqual(self.execute(intervals=[(start - 100, start), (end, end + 100)])[0], 0)


class MzTransformTests(MzValidationTests):
    module = "mz_transform.inc"
    transforms = True

    def test_body_corruption_is_detected(self):
        self.assertEqual(self.execute(corrupt="body")[0], 48)

    def test_zero_tail_corruption_is_detected(self):
        self.assertEqual(self.execute(corrupt="tail")[0], 48)

    def test_no_additional_allocation_or_rounding_tail(self):
        self.assertEqual(self.execute(carrier(1024, {5: 0}))[0], 0)


class MzHandoffTests(MzTransformTests):
    module = "loader_handoff.inc"
    handoff = True

    def test_far_frame_requires_four_reserved_bytes(self):
        self.assertEqual(self.execute(updates={6: 2})[0], 40)
        self.assertEqual(self.execute(updates={6: 3})[0], 40)


if __name__ == "__main__":
    unittest.main()
