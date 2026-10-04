#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Execute production adapter buffer bounds before any synthetic device call."""
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

import unicorn
from unicorn import Uc, UC_ARCH_X86, UC_MODE_16, UC_HOOK_CODE
from unicorn.x86_const import (
    UC_X86_REG_AX, UC_X86_REG_CS, UC_X86_REG_DS, UC_X86_REG_SS,
    UC_X86_REG_SP, UC_X86_REG_EFLAGS,
)

TARGET = Path(__file__).resolve().parents[1]
CODE, STACK, BUFFER, STOP = 0x1200, 0x7000, 0x5800, 0x3F00


class BufferAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if unicorn.__version__ != "2.1.4":
            raise RuntimeError("M14 execution QA requires pinned Unicorn 2.1.4")
        adapter = (TARGET / "kernel/m13_platform.asm").read_text()
        macro = '%macro pc88va_arg_far' + adapter.split('%macro pc88va_arg_far', 1)[1].split('%endmacro', 1)[0] + '%endmacro\n'
        helpers = adapter.split('; Install a validated per-drive BIOS/FDC profile for subsequent block I/O.\n', 1)[1].split('; Common driver read', 1)[0]
        code = 'FL_READ:\n' + adapter.split('FL_READ:\n', 1)[1].split('; Format and the legacy', 1)[0]
        text = ('bits 16\ncpu 8086\norg 0\n%define PASCAL 1\n%define XCPU 86\n'
                '%include "stacks.inc"\n%include "loader_abi.inc"\n' + (TARGET / 'kernel/disk_buffer.inc').read_text() + macro +
                'dw FL_READ, FL_WRITE, FL_VERIFY, pc88va_kernel_disk_read_, '
                'pc88va_kernel_disk_write_, pc88va_m12_request_, pc88va_m12_buffer_\n' + helpers + code +
                '\npc88va_kernel_disk_read_: ret\npc88va_kernel_disk_write_: ret\n'
                'pc88va_kernel_firmware_read_one_: retf\npc88va_kernel_firmware_write_one_: retf\n'
                'pc88va_m12_drive_context_: dw 0\npc88va_m12_request_: times 48 db 0\n'
                'pc88va_m12_buffer_: times PC88VA_DISK_BUFFER_BYTES db 0\n'
                'pc88va_m16_profiles_: dw 0023h,1280,8,2,1024,0023h,1280,8,2,1024\n')
        with tempfile.TemporaryDirectory(prefix="m14-buffer-adapter-") as directory:
            source, binary = Path(directory) / 'adapter.asm', Path(directory) / 'adapter.bin'
            source.write_text(text)
            result = subprocess.run(['nasm', '-f', 'bin', '-I', str(TARGET.parent / 'hdr')+'/',
                                     '-I', str(TARGET / 'boot')+'/', '-o', str(binary), str(source)],
                                    capture_output=True)
            if result.returncode:
                raise AssertionError(result.stderr.decode(errors='replace'))
            cls.code = binary.read_bytes()
        (*cls.entries, cls.read_core, cls.write_core, cls.request, cls.scratch) = struct.unpack_from('<7H', cls.code)
        assert len(cls.code) < STOP

    def execute(self, function, offset, count, segment=BUFFER):
        machine = Uc(UC_ARCH_X86, UC_MODE_16)
        machine.mem_map(0, 0x110000)
        machine.mem_write(CODE*16, self.code)
        machine.mem_write(BUFFER*16, b'G'*65536)
        machine.mem_write(STACK*16+0x1000,
                          struct.pack('<9H', STOP, CODE, offset, segment, count, 1, 0, 0, 0))
        for register, value in ((UC_X86_REG_CS, CODE), (UC_X86_REG_DS, 0x2800),
                                (UC_X86_REG_SS, STACK), (UC_X86_REG_SP, 0x1000),
                                (UC_X86_REG_EFLAGS, 0x202)):
            machine.reg_write(register, value)
        calls = []

        def resident(cpu, address, _size, _):
            if address not in (CODE*16+self.read_core, CODE*16+self.write_core):
                return
            request = struct.unpack('<24H', cpu.mem_read(CODE*16+self.request, 48))
            self.assertEqual((request[2], request[9]), (1, 1024))
            self.assertEqual(request[1], len(calls))
            calls.append(request[1])
            if address == CODE*16+self.read_core:
                cpu.mem_write(CODE*16+self.scratch, b'G'*1024)
            else:
                self.assertEqual(bytes(cpu.mem_read(CODE*16+self.scratch, 1024)), b'G'*1024)
            cpu.reg_write(UC_X86_REG_AX, 0)

        machine.hook_add(UC_HOOK_CODE, resident)
        machine.emu_start(CODE*16+self.entries[function], CODE*16+STOP, count=500000)
        self.assertEqual(machine.reg_read(UC_X86_REG_SP), 0x1012)
        self.assertEqual(bytes(machine.mem_read(BUFFER*16, 65536)), b'G'*65536)
        return machine.reg_read(UC_X86_REG_AX), calls

    def test_last_word_of_segment_is_a_valid_exclusive_end(self):
        for function in range(3):
            for offset, count in ((0xFC00, 1), (0xF800, 2), (0, 64)):
                with self.subTest(function=function, offset=offset, count=count):
                    status, calls = self.execute(function, offset, count)
                    self.assertEqual(status, 0)
                    self.assertEqual(calls, list(range(count)))

    def test_invalid_full_extent_is_rejected_before_first_device_access(self):
        for function in range(3):
            for offset, count, segment in ((0xFC01, 1, BUFFER), (0xF801, 2, BUFFER),
                                           (0, 65, BUFFER), (0, 2, 0xFFC0),
                                           (0, 0, BUFFER), (0, 0xFFFF, BUFFER)):
                with self.subTest(function=function, offset=offset, count=count, segment=segment):
                    self.assertEqual(self.execute(function, offset, count, segment), (2, []))


if __name__ == '__main__':
    unittest.main()
