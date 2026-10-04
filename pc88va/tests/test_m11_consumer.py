#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""ROM-free status/consume contract tests for the PC-88VA console adapter."""
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

from unicorn import Uc, UC_ARCH_X86, UC_MODE_16, UC_HOOK_INSN
from unicorn.x86_const import *


TARGET = Path(__file__).resolve().parents[1]
CODE = 0x1000
STACK = 0x7000
STOP = 0x3F00


def matrix(*positions):
    rows = [0xFF] * 15
    for position in positions:
        rows[position >> 4] &= ~(1 << (position & 7))
    return rows


class ConsumerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "consumer.asm"
            binary = root / "consumer.bin"
            source.write_text(
                "bits 16\ncpu 8086\norg 0\n"
                "jmp near consumer_entry\n"
                "dw pc88va_console_peek_dos_, pc88va_console_read_dos_\n"
                "dw pc88va_m11_character_, pc88va_m11_storage_begin, pc88va_m11_storage_end\n"
                "dw pc88va_m16_storage_begin, pc88va_m16_storage_end\n"
                "dw pc88va_m16_input_flush_, pc88va_m16_queue_, pc88va_m16_count_\n"
                "dw m16_second_valid, m16_repeat_owner, m16_enqueue\n"
                "pc88va_m10_state_: db 2\n"
                "pc88va_m10_clock_record_: dw 1,0,0\n"
                "pc88va_clock_read_:\n"
                "push dx\npushf\npop dx\ntest dx,0600h\npop dx\njnz .bad_clock\n"
                "cmp ax,pc88va_m10_clock_record_\n"
                "jne .bad_clock\n"
                "mov ax,ds\n"
                "mov dx,cs\n"
                "cmp ax,dx\n"
                "jne .bad_clock\n"
                "add word [cs:pc88va_m10_clock_record_+2], 10\n"
                "adc word [cs:pc88va_m10_clock_record_+4], 0\n"
                "xor ax,ax\nret\n"
                ".bad_clock: mov ax,0ffffh\nret\n"
                "%define M11_FLAT_TEST 1\n"
                "%include \"console_input.asm\"\n"
                "consumer_entry:\n"
                "ret\n"
            )
            subprocess.run(
                ["nasm", "-f", "bin", "-DPC88VA", "-I", str(TARGET / "kernel") + "/",
                 "-o", str(binary), str(source)],
                check=True, capture_output=True,
            )
            cls.code = binary.read_bytes()
        (cls.peek, cls.read, cls.character, cls.storage_begin,
         cls.storage_end, cls.m16_storage_begin, cls.m16_storage_end,
         cls.flush, cls.queue, cls.queue_count, cls.second_valid,
         cls.repeat_owner, cls.enqueue) = struct.unpack_from("<" + "H" * 13, cls.code, 3)

    def setUp(self):
        self.cpu = Uc(UC_ARCH_X86, UC_MODE_16)
        self.cpu.mem_map(0, 0x100000)
        self.cpu.mem_write(CODE * 16, self.code)
        self.current = [matrix()]
        self.read_ports = []

        def port_in(_cpu, port, size, _user):
            self.assertEqual(size, 1)
            self.assertIn(port, range(15))
            self.read_ports.append(port)
            return self.current[0][port]

        self.cpu.hook_add(UC_HOOK_INSN, port_in, None, 1, 0, UC_X86_INS_IN)

    def invoke(self, entry, snapshot, ax=None):
        self.current[0] = snapshot
        regs = {UC_X86_REG_BX: 0x1357, UC_X86_REG_CX: 0x2468,
                UC_X86_REG_DX: 0x4567, UC_X86_REG_SI: 0x3456,
                UC_X86_REG_DI: 0x5678, UC_X86_REG_BP: 0x6789,
                UC_X86_REG_DS: CODE, UC_X86_REG_ES: 0x4000,
                UC_X86_REG_SS: STACK, UC_X86_REG_EFLAGS: 0x202}
        for reg, value in regs.items():
            self.cpu.reg_write(reg, value)
        self.cpu.reg_write(UC_X86_REG_CS, CODE)
        self.cpu.reg_write(UC_X86_REG_SP, 0x1000)
        self.cpu.reg_write(UC_X86_REG_IP, entry)
        self.cpu.reg_write(UC_X86_REG_AX, self.character if ax is None else ax)
        self.cpu.mem_write(STACK * 16 + 0x1000, struct.pack("<H", STOP))
        self.cpu.emu_start(CODE * 16 + entry, CODE * 16 + STOP, count=10000)
        self.assertEqual(self.cpu.reg_read(UC_X86_REG_IP), STOP)
        self.assertEqual(self.cpu.reg_read(UC_X86_REG_SP), 0x1002)
        if entry != self.enqueue:
            for reg, value in regs.items():
                self.assertEqual(self.cpu.reg_read(reg), value, hex(reg))
        return self.cpu.reg_read(UC_X86_REG_AX)

    def test_peek_is_repeatable_and_read_consumes_once(self):
        released = matrix()
        # VAEG's V binding is matrix row 4, bit 6 (wire coordinate 0x46);
        # the guest scanner's row*8+bit lookup key is 0x26.
        pressed = matrix(0x46)

        self.assertEqual(self.invoke(self.peek, released), 1)
        self.assertEqual(self.invoke(self.peek, pressed), 0)
        self.assertEqual(self.cpu.mem_read(CODE * 16 + self.character, 2), b"v\x00")

        ports_after_press = len(self.read_ports)
        self.assertEqual(self.invoke(self.peek, released), 0)
        self.assertEqual(len(self.read_ports), ports_after_press)
        self.assertEqual(self.invoke(self.read, released), 0)
        self.assertEqual(self.invoke(self.read, released), 1)
        self.assertEqual(self.invoke(self.read, pressed), 0)
        self.assertEqual(self.invoke(self.read, released), 1)


if __name__ == "__main__":
    unittest.main()
