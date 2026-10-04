# SPDX-License-Identifier: GPL-2.0-or-later
"""Execute root lookup machine code with synthetic FAT directory records."""
import pathlib
import struct
import subprocess
import tempfile
import unittest

import unicorn
from unicorn import Uc, UC_ARCH_X86, UC_MODE_16
from unicorn.x86_const import (
    UC_X86_REG_AX, UC_X86_REG_BX, UC_X86_REG_CX, UC_X86_REG_DX,
    UC_X86_REG_SI, UC_X86_REG_DI, UC_X86_REG_BP, UC_X86_REG_SP,
    UC_X86_REG_CS, UC_X86_REG_DS, UC_X86_REG_ES, UC_X86_REG_SS,
    UC_X86_REG_EFLAGS,
)

BOOT = pathlib.Path(__file__).resolve().parents[1] / "boot"
CODE, DATA, STACK, ROOT = 0x1200, 0x2800, 0x3800, 0x4800
REQUEST, STOP = 0x1400, 0x1f00


def entry(name=b"KERNEL  SYS", attributes=0x20, first=2, size=777):
    data = bytearray(32)
    assert len(name) == 11
    data[:11] = name
    data[11] = attributes
    struct.pack_into("<HI", data, 26, first, size)
    return bytes(data)


class RootLookupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if unicorn.__version__ != "2.1.4":
            raise RuntimeError("M08 execution QA requires pinned Unicorn 2.1.4")
        cls.temporary = tempfile.TemporaryDirectory(prefix="pc88va-m08-root-")
        target = pathlib.Path(cls.temporary.name) / "root.bin"
        subprocess.run(["nasm", "-f", "bin", "-DPC88VA", "-I", str(BOOT) + "/",
                        "-o", str(target), str(BOOT / "root_directory.inc")],
                       check=True, capture_output=True)
        cls.code = target.read_bytes()

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def execute(self, entries, updates=None):
        records = b"".join(entries)
        words = [1, 0x300, ROOT, len(entries), len(records), 20, 0x4000, 0, 0, 0]
        for index, value in (updates or {}).items():
            words[index] = value
        machine = Uc(UC_ARCH_X86, UC_MODE_16)
        machine.mem_map(0, 0x110000)
        machine.mem_write(CODE * 16, self.code)
        machine.mem_write(DATA * 16 + REQUEST, struct.pack("<10H", *words))
        machine.mem_write(ROOT * 16 + words[1], records or b"\0")
        machine.mem_write(STACK * 16 + 0x3000, struct.pack("<H", STOP))
        registers = {
            UC_X86_REG_BX: 0x1234, UC_X86_REG_CX: 0x2345, UC_X86_REG_DX: 0x3456,
            UC_X86_REG_SI: REQUEST, UC_X86_REG_DI: 0x4567, UC_X86_REG_BP: 0x5678,
            UC_X86_REG_DS: DATA, UC_X86_REG_ES: 0x6800, UC_X86_REG_SS: STACK,
        }
        for register, value in registers.items():
            machine.reg_write(register, value)
        machine.reg_write(UC_X86_REG_CS, CODE)
        machine.reg_write(UC_X86_REG_SP, 0x3000)
        machine.reg_write(UC_X86_REG_EFLAGS, 0x602)
        machine.emu_start(CODE * 16, CODE * 16 + STOP, count=100000)
        self.assertEqual(machine.reg_read(UC_X86_REG_SP), 0x3002)
        for register, value in registers.items():
            self.assertEqual(machine.reg_read(register), value)
        status = machine.reg_read(UC_X86_REG_AX)
        self.assertEqual(machine.reg_read(UC_X86_REG_EFLAGS), 0x602 | int(status != 0))
        if records:
            self.assertEqual(bytes(machine.mem_read(ROOT * 16 + words[1], len(records))), records)
        final = struct.unpack("<10H", machine.mem_read(DATA * 16 + REQUEST, 20))
        self.assertEqual(final[:7], tuple(words[:7]))
        return status, final

    def test_exact_short_name(self):
        status, final = self.execute([entry()])
        self.assertEqual((status, final[7:]), (0, (2, 777, 1)))

    def test_hidden_system_readonly_attributes_allowed(self):
        status, _ = self.execute([entry(attributes=0x27)])
        self.assertEqual(status, 0)

    def test_nonmatching_and_skipped_records(self):
        records = [entry(b"OTHER   SYS"), entry(b"\xe5ERNEL  SYS"),
                   entry(attributes=0x0f), entry(attributes=0x10), entry(attributes=0x08),
                   entry(first=5, size=1234)]
        status, final = self.execute(records)
        self.assertEqual((status, final[7:]), (0, (5, 1234, 1)))

    def test_missing_and_exact_case(self):
        for record in (entry(b"OTHER   SYS"), entry(b"kernel  sys"), entry(attributes=0x10)):
            with self.subTest(record=record):
                status, _ = self.execute([record])
                self.assertEqual(status, 21)

    def test_end_marker_stops_search(self):
        status, _ = self.execute([bytes(32), entry()])
        self.assertEqual(status, 21)
        status, _ = self.execute([entry(), bytes(32), entry()])
        self.assertEqual(status, 0)

    def test_duplicate_match_rejected(self):
        status, _ = self.execute([entry(), entry(first=3)])
        self.assertEqual(status, 24)

    def test_bad_cluster(self):
        for first in (0, 1, 22, 0xff0, 0xff7, 0xfff):
            with self.subTest(first=first):
                status, _ = self.execute([entry(first=first)])
                self.assertEqual(status, 23)

    def test_zero_size_and_reserved_attributes(self):
        for record in (entry(size=0), entry(attributes=0x40), entry(attributes=0x80)):
            with self.subTest(record=record):
                status, _ = self.execute([record])
                self.assertEqual(status, 23)

    def test_oversized_32bit_size(self):
        for size in (0x4001, 0x10000, 0xffffffff):
            with self.subTest(size=size):
                status, _ = self.execute([entry(size=size)])
                self.assertEqual(status, 25)

    def test_truncated_overflowing_cache(self):
        for updates in ({4: 31}, {1: 0xfff0}, {3: 2048}, {2: 0xffff}):
            with self.subTest(updates=updates):
                status, _ = self.execute([entry()], updates)
                self.assertEqual(status, 22)

    def test_invalid_contract(self):
        for updates in ({0: 2}, {3: 0}, {5: 0}, {5: 4085}, {6: 0}):
            with self.subTest(updates=updates):
                status, _ = self.execute([entry()], updates)
                self.assertEqual(status, 20)

    def test_lookup_crosses_sector_boundary(self):
        records = [entry(b"OTHER   SYS")] * 17 + [entry(first=12, size=913)]
        status, final = self.execute(records)
        self.assertEqual((status, final[7:]), (0, (12, 913, 1)))


if __name__ == "__main__":
    unittest.main()
