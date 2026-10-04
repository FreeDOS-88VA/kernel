# SPDX-License-Identifier: GPL-2.0-or-later
"""Actual 8086 FAT12 decoder and chain validator; all fixtures are synthetic."""
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
CODE, DATA, STACK, FAT, VISITED = 0x1200, 0x2800, 0x3800, 0x4800, 0x5800
REQUEST, STOP = 0x1400, 0x1f00


def encode(table, cluster, successor):
    offset = cluster + cluster // 2
    pair = int.from_bytes(table[offset:offset + 2], "little")
    if cluster & 1:
        pair = (pair & 15) | (successor << 4)
    else:
        pair = (pair & 0xf000) | successor
    table[offset:offset + 2] = pair.to_bytes(2, "little")


class FatCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if unicorn.__version__ != "2.1.4":
            raise RuntimeError("M08 execution QA requires pinned Unicorn 2.1.4")
        cls.temporary = tempfile.TemporaryDirectory(prefix="pc88va-m08-fat-")
        directory = pathlib.Path(cls.temporary.name)
        source = directory / "fixture.asm"
        source.write_text('org 0\n%include "fat12.inc"\ndw pc88va_fat_next_core, pc88va_fat_chain_core\n')
        target = directory / "fixture.bin"
        subprocess.run(["nasm", "-f", "bin", "-DPC88VA", "-I", str(BOOT) + "/",
                        "-o", str(target), str(source)], check=True, capture_output=True)
        cls.code = target.read_bytes()
        cls.entries = struct.unpack("<2H", cls.code[-4:])

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def execute(self, links=None, updates=None, decode=False):
        words = [1, 0x300, FAT, 32, 16, 2, 2, 0x500, VISITED, 512, 2, 0, 0]
        for index, value in (updates or {}).items():
            words[index] = value
        table = bytearray(max(32, words[3]))
        for cluster, successor in (links or {2: 3, 3: 0xfff}).items():
            encode(table, cluster, successor)
        machine = Uc(UC_ARCH_X86, UC_MODE_16)
        machine.mem_map(0, 0x110000)
        machine.mem_write(CODE * 16, self.code)
        machine.mem_write(DATA * 16 + REQUEST, struct.pack("<13H", *words))
        machine.mem_write(FAT * 16 + words[1], bytes(table))
        machine.mem_write(VISITED * 16 + 0x4ff, b"\xa5" * 514)
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
        entry = self.entries[0 if decode else 1]
        machine.emu_start(CODE * 16 + entry, CODE * 16 + STOP, count=100000)
        self.assertEqual(machine.reg_read(UC_X86_REG_SP), 0x3002, "bounded return")
        for register, value in registers.items():
            self.assertEqual(machine.reg_read(register), value)
        status = machine.reg_read(UC_X86_REG_AX)
        self.assertEqual(machine.reg_read(UC_X86_REG_EFLAGS), 0x602 | int(status != 0))
        self.assertEqual(bytes(machine.mem_read(FAT * 16 + words[1], len(table))), bytes(table))
        self.assertEqual(bytes(machine.mem_read(VISITED * 16 + 0x4ff, 1)), b"\xa5")
        self.assertEqual(bytes(machine.mem_read(VISITED * 16 + 0x700, 1)), b"\xa5")
        final = struct.unpack("<13H", machine.mem_read(DATA * 16 + REQUEST, 26))
        self.assertEqual(final[:10], tuple(words[:10]), "inputs remain immutable")
        return status, final

    def test_exact_chain(self):
        status, final = self.execute()
        self.assertEqual((status, final[12], final[11]), (0, 2, 0xfff))

    def test_even_and_odd_decode(self):
        for cluster, value in ((2, 0xabc), (3, 0xdef)):
            with self.subTest(cluster=cluster):
                status, final = self.execute({2: 0xabc, 3: 0xdef}, {10: cluster}, decode=True)
                self.assertEqual((status, final[11]), (0, value))

    def test_sector_boundary_decode(self):
        status, final = self.execute({341: 0xabc}, {3: 700, 4: 400, 10: 341}, decode=True)
        self.assertEqual((status, final[11]), (0, 0xabc))

    def test_truncated_fat_and_wrapping_buffer(self):
        for updates in ({3: 4}, {1: 0xfff0}):
            with self.subTest(updates=updates):
                status, _ = self.execute(updates=updates, decode=True)
                self.assertEqual(status, 12)

    def test_invalid_contract(self):
        for updates in ({0: 2}, {4: 0}, {4: 4085}, {6: 0}, {6: 17}):
            with self.subTest(updates=updates):
                status, _ = self.execute(updates=updates)
                self.assertEqual(status, 10)

    def test_invalid_start_cluster(self):
        for cluster in (0, 1, 18, 0xff0, 0xff7, 0xfff):
            with self.subTest(cluster=cluster):
                status, _ = self.execute(updates={5: cluster})
                self.assertEqual(status, 11)

    def test_reserved_and_bad_successor(self):
        for successor in (0, 1, 0xff0, 0xff1, 0xff6, 0xff7):
            with self.subTest(successor=successor):
                status, _ = self.execute({2: successor})
                self.assertEqual(status, 13)

    def test_out_of_range_successor(self):
        status, _ = self.execute({2: 18})
        self.assertEqual(status, 11)

    def test_cycle(self):
        status, final = self.execute({2: 3, 3: 2}, {6: 3})
        self.assertEqual((status, final[12]), (14, 2))

    def test_premature_eoc(self):
        status, final = self.execute({2: 0xff8})
        self.assertEqual((status, final[12]), (15, 1))

    def test_overlong_chain(self):
        status, final = self.execute({2: 3, 3: 4, 4: 0xfff})
        self.assertEqual((status, final[12]), (16, 2))

    def test_bitmap_capacity(self):
        status, _ = self.execute(updates={9: 1})
        self.assertEqual(status, 12)

    def test_all_eoc_encodings(self):
        for successor in range(0xff8, 0x1000):
            with self.subTest(successor=successor):
                status, _ = self.execute({2: successor}, {6: 1})
                self.assertEqual(status, 0)


if __name__ == "__main__":
    unittest.main()
