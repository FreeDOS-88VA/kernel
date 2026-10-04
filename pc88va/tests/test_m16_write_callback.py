#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Exercise the M16 resident write callback's firmware register contract."""

from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

import unicorn
from unicorn import Uc, UC_ARCH_X86, UC_MODE_16, UC_HOOK_INTR
from unicorn.x86_const import (
    UC_X86_REG_AX, UC_X86_REG_BX, UC_X86_REG_CX, UC_X86_REG_DX,
    UC_X86_REG_SI, UC_X86_REG_SP, UC_X86_REG_CS, UC_X86_REG_DS,
    UC_X86_REG_SS, UC_X86_REG_EFLAGS,
)

TARGET = Path(__file__).resolve().parents[1]
CODE, STACK, REQUEST, STOP = 0x1200, 0x7000, 0x1000, 0x3f00


class WriteCallbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if unicorn.__version__ != "2.1.4":
            raise RuntimeError("M16 execution QA requires pinned Unicorn 2.1.4")
        resident = (TARGET / "kernel/resident_disk.asm").read_text(encoding="utf-8")
        callback = resident.split("pc88va_kernel_firmware_write_one_:\n", 1)[1]
        callback = callback.split("; Resident write entry", 1)[0]
        with tempfile.TemporaryDirectory(prefix="m16-write-callback-") as directory:
            source = Path(directory) / "callback.asm"
            binary = Path(directory) / "callback.bin"
            source.write_text(
                "bits 16\ncpu 8086\norg 0\nentry:\n" + callback +
                "\npc88va_m16_profiles_:\n"
                "dw 0023h,1280,8,2,1024\n"
                "dw 0012h,1280,8,2,512\n"
                "pc88va_m12_call_flags_: dw 0\n",
                encoding="utf-8",
            )
            subprocess.run(["nasm", "-f", "bin", "-o", str(binary), str(source)],
                           check=True, capture_output=True)
            cls.code = binary.read_bytes()

    def execute(self, drive, cylinder, head, sector, sector_bytes):
        machine = Uc(UC_ARCH_X86, UC_MODE_16)
        machine.mem_map(0, 0x100000)
        machine.mem_write(CODE * 16, self.code)
        words = [0] * 24
        words[9], words[10] = sector_bytes, drive
        words[16], words[17], words[18] = cylinder, head, sector
        words[19], words[20] = 0x2000, CODE
        machine.mem_write(CODE * 16 + REQUEST, struct.pack("<24H", *words))
        machine.mem_write(STACK * 16 + 0x1000, struct.pack("<HH", STOP, CODE))
        for register, value in ((UC_X86_REG_CS, CODE), (UC_X86_REG_DS, CODE),
                                (UC_X86_REG_SS, STACK), (UC_X86_REG_SP, 0x1000),
                                (UC_X86_REG_SI, REQUEST)):
            machine.reg_write(register, value)
        mode = 0x23 if drive == 0 else 0x12
        seen = []

        def interrupt(cpu, number, _):
            self.assertEqual(number, 0x80)
            flags = cpu.reg_read(UC_X86_REG_EFLAGS)
            ax = cpu.reg_read(UC_X86_REG_AX)
            if ax >> 8 == 0x0a:
                self.assertEqual(ax & 0xff, mode)
                self.assertEqual((cpu.reg_read(UC_X86_REG_CX) >> 8) & 0xff,
                                 drive)
                seen.append("mode")
                cpu.reg_write(UC_X86_REG_AX, 0)
                cpu.reg_write(UC_X86_REG_EFLAGS, flags & ~1)
                return
            self.assertEqual(ax, 0x8201)
            bx = cpu.reg_read(UC_X86_REG_BX)
            cx = cpu.reg_read(UC_X86_REG_CX)
            dx = cpu.reg_read(UC_X86_REG_DX)
            self.assertEqual(bx, (cylinder << 8) | head)
            self.assertEqual(cx, (drive << 8) | ((cylinder * 2 + head) & 0xff))
            self.assertEqual(dx, (sector << 8) | (mode & 0x0f))
            seen.append("write")
            cpu.reg_write(UC_X86_REG_AX, 0)
            cpu.reg_write(UC_X86_REG_EFLAGS, flags & ~1)

        machine.hook_add(UC_HOOK_INTR, interrupt)
        machine.emu_start(CODE * 16, CODE * 16 + STOP, count=200)
        self.assertEqual(seen, ["mode", "write"])
        self.assertEqual(machine.reg_read(UC_X86_REG_SP), 0x1004)
        self.assertEqual(machine.reg_read(UC_X86_REG_AX), 0)
        self.assertEqual(machine.reg_read(UC_X86_REG_CX), sector_bytes)

    def test_2hd_drive_a_keeps_sector_after_profile_index_calculation(self):
        self.execute(drive=0, cylinder=0, head=0, sector=6, sector_bytes=1024)

    def test_2dd_drive_b_keeps_full_chs_after_profile_index_calculation(self):
        self.execute(drive=1, cylinder=2, head=1, sector=9, sector_bytes=512)


if __name__ == "__main__":
    unittest.main()
