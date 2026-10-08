#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Execute the actual DOS read adapter against an emulated VA floppy BIOS."""
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

import unicorn
from unicorn import Uc, UC_ARCH_X86, UC_MODE_16, UC_HOOK_CODE, UC_HOOK_INTR
from unicorn.x86_const import (
    UC_X86_REG_AX, UC_X86_REG_AH, UC_X86_REG_AL, UC_X86_REG_BH, UC_X86_REG_BL,
    UC_X86_REG_CH, UC_X86_REG_CL, UC_X86_REG_DH, UC_X86_REG_DL, UC_X86_REG_BP,
    UC_X86_REG_CS, UC_X86_REG_DS, UC_X86_REG_ES, UC_X86_REG_SS,
    UC_X86_REG_SP, UC_X86_REG_EFLAGS,
)

TARGET = Path(__file__).resolve().parents[1]
CODE, STACK, BUFFER, STOP = 0x1200, 0x7000, 0x5800, 0x3f00


class ReadAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if unicorn.__version__ != "2.1.4":
            raise RuntimeError("M14 execution QA requires pinned Unicorn 2.1.4")
        adapter = (TARGET / "kernel/m13_platform.asm").read_text(encoding="utf-8")
        macro = '%macro pc88va_arg_far' + adapter.split('%macro pc88va_arg_far', 1)[1].split('%endmacro', 1)[0] + '%endmacro\n'
        helpers = adapter.split('; Install a validated per-drive BIOS/FDC profile for subsequent block I/O.\n', 1)[1].split('; Common driver read', 1)[0]
        code = 'FL_READ:\n' + adapter.split('FL_READ:\n', 1)[1].split('; COUNT fl_write', 1)[0]
        source_text = ('bits 16\ncpu 8086\norg 0\n%define PASCAL 1\n%define XCPU 86\n'
                       '%include "stacks.inc"\n%include "loader_abi.inc"\n' + (TARGET / 'kernel/disk_buffer.inc').read_text() + macro +
                       'dw FL_READ, pc88va_kernel_disk_read_, pc88va_m12_request_, pc88va_m12_buffer_\n' + helpers + code +
                       '\npc88va_kernel_disk_read_: ret\n'
                       'pc88va_kernel_firmware_read_one_: retf\n'
                       'pc88va_m12_drive_context_: dw 0\n'
                       'pc88va_m12_call_flags_: dw 0202h\n'
                       'pc88va_m12_request_: times 48 db 0\n'
                       'pc88va_m12_buffer_: times PC88VA_DISK_BUFFER_BYTES db 0\n'
                       'pc88va_m16_profiles_: dw 0023h,1280,8,2,1024,0023h,1280,8,2,1024\n')
        with tempfile.TemporaryDirectory(prefix="m14-read-adapter-") as directory:
            source, binary = Path(directory) / 'adapter.asm', Path(directory) / 'adapter.bin'
            source.write_text(source_text, encoding="utf-8")
            result = subprocess.run(['nasm', '-f', 'bin', '-I', str(TARGET.parent / 'hdr')+'/',
                            '-I', str(TARGET / 'boot')+'/', '-o', str(binary), str(source)],
                           capture_output=True)
            if result.returncode:
                raise AssertionError(result.stderr.decode('utf-8', errors='replace'))
            cls.code = binary.read_bytes()
        cls.entry, cls.core, cls.request, cls.scratch = struct.unpack_from('<4H', cls.code)

    def execute(self, failures=0, status=0):
        machine = Uc(UC_ARCH_X86, UC_MODE_16)
        machine.mem_map(0, 0x100000)
        machine.mem_write(CODE*16, self.code)
        machine.mem_write(BUFFER*16, b'G'*8192)
        # FAR Pascal frame: the last (far buffer) argument is nearest return.
        # Drive 0, head 1, cylinder 0, sector 2, two sectors, BUFFER:0400.
        machine.mem_write(STACK*16+0x1000,
                          struct.pack('<9H', STOP, CODE, 0x400, BUFFER, 2, 2, 0, 1, 0))
        for register, value in ((UC_X86_REG_CS, CODE), (UC_X86_REG_DS, 0x2800),
                                (UC_X86_REG_SS, STACK), (UC_X86_REG_SP, 0x1000),
                                (UC_X86_REG_EFLAGS, 0x202)):
            machine.reg_write(register, value)
        calls = []

        def core(cpu, address, _size, _):
            self.assertNotEqual(address, CODE*16+self.core, 'read must not use the sector core')

        def interrupt(cpu, number, _):
            self.assertEqual(number, 0x80)
            ah = cpu.reg_read(UC_X86_REG_AH)
            if ah == 0x0a:
                self.assertEqual((cpu.reg_read(UC_X86_REG_AL), cpu.reg_read(UC_X86_REG_CH)), (0x23, 0))
                calls.append('mode')
                cpu.reg_write(UC_X86_REG_AH, 0)
                cpu.reg_write(UC_X86_REG_EFLAGS, cpu.reg_read(UC_X86_REG_EFLAGS) & ~1)
                return
            self.assertEqual(ah, 0x81)
            request = tuple(cpu.reg_read(r) for r in (
                UC_X86_REG_AL, UC_X86_REG_CH, UC_X86_REG_CL, UC_X86_REG_BH, UC_X86_REG_BL,
                UC_X86_REG_DH, UC_X86_REG_DL))
            self.assertEqual(request, (2, 0, 1, 0, 1, 2, 3))
            target = cpu.reg_read(UC_X86_REG_ES)*16 + cpu.reg_read(UC_X86_REG_BP)
            self.assertEqual(target, BUFFER*16+0x400)
            calls.append('read')
            if len([c for c in calls if c == 'read']) <= failures:
                cpu.reg_write(UC_X86_REG_AH, status)
                cpu.reg_write(UC_X86_REG_EFLAGS, cpu.reg_read(UC_X86_REG_EFLAGS) | 1)
                return
            cpu.mem_write(target, b'A'*1024 + b'B'*1024)
            cpu.reg_write(UC_X86_REG_AH, 0)
            cpu.reg_write(UC_X86_REG_EFLAGS, cpu.reg_read(UC_X86_REG_EFLAGS) & ~1)

        machine.hook_add(UC_HOOK_CODE, core)
        machine.hook_add(UC_HOOK_INTR, interrupt)
        machine.emu_start(CODE*16+self.entry, CODE*16+STOP, count=20000)
        self.assertEqual(machine.reg_read(UC_X86_REG_SP), 0x1012)
        return machine, machine.reg_read(UC_X86_REG_AX), calls

    def test_one_rom_call_reads_the_request_into_the_caller_buffer(self):
        machine, status, calls = self.execute()
        self.assertEqual(status, 0)
        self.assertEqual(calls, ['mode', 'read'])
        expected = b'G'*0x400 + b'A'*1024 + b'B'*1024 + b'G'*(8192-0x400-2048)
        self.assertEqual(bytes(machine.mem_read(BUFFER*16, 8192)), expected)

    def test_a_failed_attempt_is_retried(self):
        machine, status, calls = self.execute(failures=1, status=0x08)
        self.assertEqual(status, 0)
        self.assertEqual(calls, ['mode', 'read', 'mode', 'read'])

    def test_errors_after_three_attempts_map_to_dos_status(self):
        for rom, dos in ((0x07, 0x10), (0x08, 0x04), (0x04, 0x80), (0x02, 0x02)):
            with self.subTest(rom=rom):
                machine, status, calls = self.execute(failures=3, status=rom)
                self.assertEqual(status, dos)
                self.assertEqual(calls, ['mode', 'read'] * 3)
                self.assertEqual(bytes(machine.mem_read(BUFFER*16, 8192)), b'G'*8192)

    def test_a_request_beyond_the_track_end_is_rejected(self):
        machine = Uc(UC_ARCH_X86, UC_MODE_16)
        machine.mem_map(0, 0x100000)
        machine.mem_write(CODE*16, self.code)
        # Sector 8 with two sectors would cross into the next track.
        machine.mem_write(STACK*16+0x1000,
                          struct.pack('<9H', STOP, CODE, 0x400, BUFFER, 2, 8, 0, 0, 0))
        for register, value in ((UC_X86_REG_CS, CODE), (UC_X86_REG_DS, 0x2800),
                                (UC_X86_REG_SS, STACK), (UC_X86_REG_SP, 0x1000),
                                (UC_X86_REG_EFLAGS, 0x202)):
            machine.reg_write(register, value)
        machine.hook_add(UC_HOOK_INTR, lambda *a: self.fail('no device access expected'))
        machine.emu_start(CODE*16+self.entry, CODE*16+STOP, count=20000)
        self.assertEqual(machine.reg_read(UC_X86_REG_AX), 2)


if __name__ == '__main__':
    unittest.main()
