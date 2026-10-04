# SPDX-License-Identifier: GPL-2.0-or-later
"""Execute the production SYS absolute-I/O wrapper against the DOS stack ABI."""
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import unittest

import unicorn
from unicorn import Uc, UC_ARCH_X86, UC_MODE_16, UC_HOOK_INTR
from unicorn.x86_const import (UC_X86_REG_AX, UC_X86_REG_BX, UC_X86_REG_CX,
    UC_X86_REG_DX, UC_X86_REG_SI, UC_X86_REG_DI, UC_X86_REG_BP,
    UC_X86_REG_DS, UC_X86_REG_ES, UC_X86_REG_CS, UC_X86_REG_SS,
    UC_X86_REG_SP, UC_X86_REG_IP, UC_X86_REG_EFLAGS)

ROOT = Path(__file__).resolve().parents[2]


class SysAbsoluteAbiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if unicorn.__version__ != '2.1.4':
            raise RuntimeError('Execution QA requires pinned Unicorn 2.1.4')
        source = (ROOT / 'sys/pc88va_io.asm').read_text()
        source = re.sub(r'^segment.*$', 'org 0', source, flags=re.M)
        source = re.sub(r'^global.*$', '', source, flags=re.M)
        with tempfile.TemporaryDirectory(prefix='m15-sys-abi-') as tmp:
            p = Path(tmp)
            (p / 'test.asm').write_text(source)
            subprocess.run(['nasm', '-f', 'bin', str(p / 'test.asm'),
                            '-o', str(p / 'test.bin')], check=True, capture_output=True)
            cls.code = (p / 'test.bin').read_bytes()

    def test_read_write_success_and_error_keep_cdecl_stack_and_registers(self):
        for writing in (0, 1):
            for error in (0, 0x0201, 0x8108):
                with self.subTest(writing=writing, error=error):
                    cpu = Uc(UC_ARCH_X86, UC_MODE_16)
                    cpu.mem_map(0, 0x100000)
                    cpu.mem_write(0x10000, self.code)
                    cpu.mem_write(0x30000 + 0x8000,
                                  struct.pack('<4H', 0x1000, writing, 1279, 0x4567))
                    saved = {UC_X86_REG_BX:0x1234, UC_X86_REG_CX:0x2345,
                             UC_X86_REG_DX:0x3456, UC_X86_REG_SI:0x4567,
                             UC_X86_REG_DI:0x5678, UC_X86_REG_BP:0x6789,
                             UC_X86_REG_DS:0x4000, UC_X86_REG_ES:0x5000}
                    for reg, value in {**saved, UC_X86_REG_CS:0x1000,
                                       UC_X86_REG_SS:0x3000, UC_X86_REG_SP:0x8000,
                                       UC_X86_REG_EFLAGS:0x202}.items():
                        cpu.reg_write(reg, value)
                    calls = []

                    def dos(machine, number, _):
                        calls.append(number)
                        self.assertEqual(number, 0x26 if writing else 0x25)
                        self.assertEqual(machine.reg_read(UC_X86_REG_AX), 0)
                        self.assertEqual(machine.reg_read(UC_X86_REG_BX), 0x4567)
                        self.assertEqual(machine.reg_read(UC_X86_REG_CX), 1)
                        self.assertEqual(machine.reg_read(UC_X86_REG_DX), 1279)
                        self.assertEqual(machine.reg_read(UC_X86_REG_DS), 0x4000)
                        sp = machine.reg_read(UC_X86_REG_SP) - 2
                        machine.reg_write(UC_X86_REG_SP, sp)
                        machine.mem_write(0x30000 + sp, struct.pack('<H', 0x246))
                        machine.reg_write(UC_X86_REG_AX, error if error else 0xbeef)
                        machine.reg_write(UC_X86_REG_EFLAGS, 0x202 | bool(error))

                    cpu.hook_add(UC_HOOK_INTR, dos)
                    cpu.emu_start(0x10000, 0x11000, count=1000)
                    self.assertEqual(calls, [0x26 if writing else 0x25])
                    self.assertEqual(cpu.reg_read(UC_X86_REG_IP), 0x1000)
                    self.assertEqual(cpu.reg_read(UC_X86_REG_SP), 0x8002)
                    self.assertEqual(cpu.reg_read(UC_X86_REG_AX), error)
                    for reg, value in saved.items():
                        self.assertEqual(cpu.reg_read(reg), value)


if __name__ == '__main__':
    unittest.main()
