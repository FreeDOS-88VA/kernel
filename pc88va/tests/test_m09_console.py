#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""ROM-free instruction-level tests of the Text BIOS byte adapter.

The synthetic BIOS is an oracle for the public adapter ABI, not firmware
qualification. Actual display effects remain the private VAEG gate.
"""
from pathlib import Path
import json
import struct
import subprocess
import tempfile
import unittest

from unicorn import Uc, UC_ARCH_X86, UC_MODE_16, UC_HOOK_INTR, UC_HOOK_MEM_WRITE
from unicorn.x86_const import *

TARGET = Path(__file__).resolve().parents[1]
CODE, STACK, STOP = 0x1000, 0x7000, 0x3f00
MESSAGE = b'\rFreeDOS/PC-88VA M09\r\n' + b'0123456789' * 9 + b'\r\nCONSOLE OK\r\n'

class ConsoleTests(unittest.TestCase):
    def assemble(self, diagnostic=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, binary = root / 'test.asm', root / 'test.bin'
            entry = 'pc88va_console_diagnostic_' if diagnostic else 'pc88va_console_putc_'
            source.write_text('bits 16\ncpu 8086\norg 0\njmp ' + entry + '\n' +
                              '%define CONSOLE_FLAT_TEST 1\n%include "console.asm"\n')
            subprocess.run(['nasm', '-f', 'bin', '-DPC88VA', '-I', str(TARGET / 'kernel') + '/',
                            '-o', str(binary), str(source)], check=True, capture_output=True)
            return binary.read_bytes()

    def execute(self, characters, *, diagnostic=False, vector=True, clobber=False,
                columns=8, rows=3):
        cpu = Uc(UC_ARCH_X86, UC_MODE_16)
        cpu.mem_map(0, 0x100000)
        cpu.mem_write(CODE * 16, self.assemble(diagnostic))
        if vector:
            cpu.mem_write(0x83 * 4, struct.pack('<HH', 0x100, 0x8000))
        regs = {UC_X86_REG_BX: 0x1357, UC_X86_REG_CX: 0x2468,
                UC_X86_REG_DX: 0x4567, UC_X86_REG_SI: 0x3456,
                UC_X86_REG_DI: 0x5678, UC_X86_REG_BP: 0x6789,
                UC_X86_REG_DS: 0x3000, UC_X86_REG_ES: 0x4000,
                UC_X86_REG_SS: STACK, UC_X86_REG_EFLAGS: 0x602}
        calls, writes, checkpoints = [], [], []
        display = [bytearray(b' ' * columns) for _ in range(rows)]
        cursor = [0, 0]
        scrolls = [0]
        def interrupt(machine, number, _):
            self.assertEqual(number, 0x83)
            self.assertEqual(machine.reg_read(UC_X86_REG_AH), 2)
            self.assertEqual(machine.reg_read(UC_X86_REG_DX), 0x8000)
            self.assertEqual(machine.reg_read(UC_X86_REG_DS), STACK)
            address = machine.reg_read(UC_X86_REG_DS) * 16 + machine.reg_read(UC_X86_REG_SI)
            text = bytes(machine.mem_read(address, 2))
            self.assertEqual(text[1], 0)
            ch = text[0]
            calls.append(ch)
            if ch == 13:
                cursor[0] = 0
            elif ch == 10:
                cursor[1] += 1
            elif ch == 8:
                cursor[0] = max(0, cursor[0] - 1)
            else:
                self.assertTrue(0x20 <= ch <= 0x7e)
                display[cursor[1]][cursor[0]] = ch
                cursor[0] += 1
                if cursor[0] == columns:
                    cursor[0] = 0
                    cursor[1] += 1
            if cursor[1] == rows:
                display.pop(0)
                display.append(bytearray(b' ' * columns))
                cursor[1] -= 1
                scrolls[0] += 1
            checkpoints.append((tuple(bytes(line) for line in display), tuple(cursor)))
            if clobber:
                for reg in regs:
                    if reg not in (UC_X86_REG_SS, UC_X86_REG_EFLAGS):
                        machine.reg_write(reg, 0xaaaa)
                machine.reg_write(UC_X86_REG_AX, 0xbeef)
                machine.reg_write(UC_X86_REG_EFLAGS, 0x46)
        cpu.hook_add(UC_HOOK_INTR, interrupt)
        cpu.hook_add(UC_HOOK_MEM_WRITE, lambda uc, access, address, size, value, data:
                     writes.append((address, size)))
        results = []
        for character in characters:
            for reg, value in regs.items(): cpu.reg_write(reg, value)
            cpu.reg_write(UC_X86_REG_CS, CODE)
            cpu.reg_write(UC_X86_REG_SP, 0x1000)
            cpu.reg_write(UC_X86_REG_AX, character)
            cpu.mem_write(STACK * 16 + 0x1000, struct.pack('<H', STOP))
            cpu.emu_start(CODE * 16, CODE * 16 + STOP, count=50000)
            self.assertEqual(cpu.reg_read(UC_X86_REG_IP), STOP, 'bounded near return')
            self.assertEqual(cpu.reg_read(UC_X86_REG_SP), 0x1002)
            for reg, value in regs.items(): self.assertEqual(cpu.reg_read(reg), value)
            results.append(cpu.reg_read(UC_X86_REG_AX))
        self.assertTrue(all(STACK*16 + 0xf00 <= a and a+n <= STACK*16 + 0x1000 for a,n in writes))
        return results, bytes(calls), display, cursor, scrolls[0], checkpoints

    def test_first_printable(self):
        self.assertEqual(self.execute([0x20])[:2], ([0], b' '))

    def test_last_printable(self):
        self.assertEqual(self.execute([0x7e])[:2], ([0], b'~'))

    def test_all_printable_bytes(self):
        chars = list(range(0x20, 0x7f))
        result = self.execute(chars)
        self.assertEqual(result[0], [0] * len(chars))
        self.assertEqual(result[1], bytes(chars))

    def test_unsupported_controls_never_call_bios(self):
        # The current shared adapter includes M13's editing support; immutable
        # historical M09 acceptance must still use its own original checkout.
        chars = [c for c in range(256) if c not in (8, 10, 13) and not 0x20 <= c <= 0x7e]
        self.assertEqual(self.execute(chars)[:2], ([0xffff] * len(chars), b''))

    def test_backspace_is_forwarded_by_current_adapter(self):
        self.assertEqual(self.execute([8])[:2], ([0], b'\x08'))

    def test_wide_character_rejected(self):
        self.assertEqual(self.execute([0x120, 0xffff])[:2], ([0xffff, 0xffff], b''))

    def test_missing_vector_fails_closed(self):
        self.assertEqual(self.execute([65], vector=False)[:2], ([0xffff], b''))

    def test_bios_clobbers_are_contained(self):
        self.assertEqual(self.execute([65, 13, 10], clobber=True)[:2], ([0, 0, 0], b'A\r\n'))

    def test_cr_preserves_row(self):
        result = self.execute(b'AB\rC')
        self.assertEqual(result[2][0][:2], b'CB')
        self.assertEqual(result[3], [1, 0])

    def test_lf_preserves_column(self):
        result = self.execute(b'AB\nC')
        self.assertEqual(result[2][1][2], ord('C'))
        self.assertEqual(result[3], [3, 1])

    def test_crlf(self):
        result = self.execute(b'AB\r\nC')
        self.assertEqual(result[2][1][0], ord('C'))
        self.assertEqual(result[3], [1, 1])

    def test_wrap(self):
        result = self.execute(b'12345678X')
        self.assertEqual(result[2][0], b'12345678')
        self.assertEqual(result[2][1][0], ord('X'))
        self.assertEqual(result[3], [1, 1])

    def test_bottom_row_delegates_to_bios(self):
        result = self.execute(b'1\r\n2\r\n3\r\n4')
        self.assertEqual(result[4], 1)
        self.assertEqual(result[2][-1][0], ord('4'))

    def test_exact_guest_diagnostic(self):
        result = self.execute([0], diagnostic=True, columns=80, rows=25)
        self.assertEqual(result[0], [0])
        self.assertEqual(result[1], MESSAGE)

    def test_diagnostic_propagates_error(self):
        self.assertEqual(self.execute([0], diagnostic=True, vector=False)[:2], ([0xffff], b''))

    def test_two_assemblies_match(self):
        self.assertEqual(self.assemble(), self.assemble())

    def test_two_execution_projections_match(self):
        self.assertEqual(self.execute([0], diagnostic=True), self.execute([0], diagnostic=True))

    def test_console_services_replaced_without_fatal_regression(self):
        source = (TARGET / 'kernel/stubs.c').read_text()
        self.assertNotIn('pc88va_console_putc', source)
        self.assertNotIn('pc88va_console_getc', source)
        self.assertIn('pc88va_console_getc_:', (TARGET / 'kernel/console_input.asm').read_text())
        self.assertNotIn('pc88va_fatal_stop_request', source)
        machine = (TARGET / 'kernel/machine_services.asm').read_text()
        self.assertIn('pc88va_fatal_stop_request_:', machine)

    def test_machine_readable_contract_matches_adapter(self):
        contract = json.loads((TARGET / 'config/console-contract.json').read_text())
        self.assertEqual(contract['diagnostic_ascii'].encode('ascii'), MESSAGE)
        self.assertEqual(contract['character_policy']['printable_first'], 0x20)
        self.assertEqual(contract['character_policy']['printable_last'], 0x7e)
        self.assertEqual(contract['mechanism']['interrupt'], 0x83)
        self.assertEqual(contract['mechanism']['function_ah'], 2)
        self.assertEqual(contract['mechanism']['attribute_dx'], 0x8000)
        self.assertTrue(contract['non_reentrant'])
        result = self.execute([0], diagnostic=True, columns=80, rows=25)
        self.assertEqual(result[1], contract['diagnostic_ascii'].encode('ascii'))

if __name__ == '__main__':
    unittest.main()
