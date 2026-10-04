#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Execute the actual DOS read adapter with a synthetic resident sector core."""
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

    def test_two_sectors_are_contiguous_and_preserve_surrounding_bytes(self):
        machine = Uc(UC_ARCH_X86, UC_MODE_16)
        machine.mem_map(0, 0x100000)
        machine.mem_write(CODE*16, self.code)
        machine.mem_write(BUFFER*16, b'G'*8192)
        # FAR Pascal frame: the last (far buffer) argument is nearest return.
        machine.mem_write(STACK*16+0x1000,
                          struct.pack('<9H', STOP, CODE, 0x400, BUFFER, 2, 1, 0, 0, 0))
        for register, value in ((UC_X86_REG_CS, CODE), (UC_X86_REG_DS, 0x2800),
                                (UC_X86_REG_SS, STACK), (UC_X86_REG_SP, 0x1000),
                                (UC_X86_REG_EFLAGS, 0x202)):
            machine.reg_write(register, value)
        sectors = []

        def resident(cpu, address, _size, _):
            if address != CODE*16+self.core:
                return
            words = struct.unpack('<24H', cpu.mem_read(CODE*16+self.request, 48))
            self.assertEqual((words[2], words[9]), (1, 1024))
            self.assertEqual(words[1], len(sectors))
            sectors.append(bytes([0x41+len(sectors)])*1024)
            cpu.mem_write(CODE*16+self.scratch, sectors[-1])
            cpu.reg_write(UC_X86_REG_AX, 0)

        machine.hook_add(UC_HOOK_CODE, resident)
        machine.emu_start(CODE*16+self.entry, CODE*16+STOP, count=10000)
        self.assertEqual(machine.reg_read(UC_X86_REG_AX), 0)
        self.assertEqual(machine.reg_read(UC_X86_REG_SP), 0x1012)
        self.assertEqual(len(sectors), 2)
        expected = b'G'*0x400 + b''.join(sectors) + b'G'*(8192-0x400-2048)
        self.assertEqual(bytes(machine.mem_read(BUFFER*16, 8192)), expected)


if __name__ == '__main__':
    unittest.main()
