#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Execute the production multiplex entry against explicit C ABI callbacks.

Flat fixtures resolve external FAR relocations to a separate synthetic code
segment. The production near/far choice, stack switching, saved register frame
and return instructions remain executable. No ROM or private address is used.
"""
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import unittest

import unicorn
from unicorn import Uc, UC_ARCH_X86, UC_MODE_16, UC_HOOK_CODE, UC_HOOK_INTR
from unicorn.x86_const import (
    UC_X86_REG_AX, UC_X86_REG_BX, UC_X86_REG_CX, UC_X86_REG_DX,
    UC_X86_REG_SI, UC_X86_REG_DI, UC_X86_REG_BP, UC_X86_REG_DS,
    UC_X86_REG_ES, UC_X86_REG_CS, UC_X86_REG_SS, UC_X86_REG_SP,
    UC_X86_REG_IP, UC_X86_REG_EFLAGS,
)

ROOT = Path(__file__).resolve().parents[2]
CODE, C_CODE, DATA, USER, CALLER = 0x1200, 0x2800, 0x4000, 0x6000, 0x7200
SP, STOP = 0x7000, 0x1000
MUX14, MUX12 = 0x2000, 0x2100


def assemble(text):
    with tempfile.TemporaryDirectory(prefix="m15-multiplex-") as directory:
        source, binary = Path(directory) / "qa.asm", Path(directory) / "qa.bin"
        source.write_text(text)
        subprocess.run(["nasm", "-f", "bin", "-I", str(ROOT / "hdr") + "/",
                        "-o", str(binary), str(source)], check=True, capture_output=True)
        return binary.read_bytes()


class MultiplexAbiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if unicorn.__version__ != "2.1.4":
            raise RuntimeError("Execution QA requires pinned Unicorn 2.1.4")
        source = (ROOT / "kernel/int2f.asm").read_text()
        body = source[source.index("%macro SwitchToInt2fStack"):source.index("SHARE_CHECK:")]
        body = re.sub(r"(?m)^\s*(extern|global|segment)\s+[^\n]+", "", body)
        # Resolve only an explicit production FAR call. A near call remains
        # near and therefore fails the relocated medium-model execution test.
        body = re.sub(r"call\s+far\s+(_syscall_MUX14|_int2F_12_handler)",
                      rf"call {C_CODE}:\1", body)
        cls.images = {}
        for far in (False, True):
            prefix = ("bits 16\ncpu 8086\norg 0\n%define XCPU 86\n"
                      '%include "stacks.inc"\n' +
                      ("%define PC88VA 1\n" if far else "") +
                      "dw reloc_call_int2f_handler\n"
                      f"_DGROUP_: dw {DATA}\n"
                      "_HaltCpuWhileIdle equ 0100h\n_cu_psp equ 0102h\n"
                      "_Dyn equ 0200h\nint2f_stk_top equ 09000h\n"
                      f"_syscall_MUX14 equ {MUX14}\n_int2F_12_handler equ {MUX12}\n")
            cls.images[far] = assemble(prefix + body)

    def execute(self, far, nls, own_stack, returned=0, carry=False):
        machine = Uc(UC_ARCH_X86, UC_MODE_16)
        machine.mem_map(0, 0x100000)
        image = self.images[far]
        machine.mem_write(CODE * 16, image)
        entry = struct.unpack_from("<H", image)[0]
        segment = C_CODE if far else CODE
        callback = MUX14 if nls else MUX12
        argument = 6 if far else 4
        output = 2 if nls else 16
        stub = assemble("bits 16\ncpu 8086\norg 0\npush bp\nmov bp,sp\n"
                        f"mov bx,[ss:bp+{argument}]\nmov es,[ss:bp+{argument + 2}]\n"
                        f"mov word [es:bx+{output}],0beefh\nmov ax,{returned}\n"
                        "pop bp\n" + ("retf\n" if far else "ret\n"))
        machine.mem_write(segment * 16 + callback, stub)
        stack = DATA if own_stack else USER
        flags = 0x602 | int(carry)
        machine.mem_write(stack * 16 + SP, struct.pack("<3H", STOP, CALLER, flags))
        saved = {UC_X86_REG_AX: 0x1404 if nls else 0x1200,
                 UC_X86_REG_BX: 0xA012, UC_X86_REG_CX: 0xB023,
                 UC_X86_REG_DX: 0xC034, UC_X86_REG_SI: 0xD045,
                 UC_X86_REG_DI: 0xE056, UC_X86_REG_BP: 0xF067,
                 UC_X86_REG_DS: 0x5100, UC_X86_REG_ES: 0x5200}
        for register, value in saved.items():
            machine.reg_write(register, value)
        for register, value in ((UC_X86_REG_CS, CODE), (UC_X86_REG_SS, stack),
                                (UC_X86_REG_SP, SP), (UC_X86_REG_EFLAGS, flags)):
            machine.reg_write(register, value)
        callbacks, stops = [], []

        def instruction(cpu, address, _size, _):
            if address in (CODE * 16 + callback, C_CODE * 16 + callback):
                actual_segment = cpu.reg_read(UC_X86_REG_CS)
                callbacks.append(actual_segment)
                self.assertEqual(actual_segment, segment, "C callback entered through wrong code segment")
                current_sp = cpu.reg_read(UC_X86_REG_SP)
                current_ss = cpu.reg_read(UC_X86_REG_SS)
                self.assertEqual(current_ss, DATA)
                pointer = struct.unpack("<2H", cpu.mem_read(DATA * 16 + current_sp + (4 if far else 2), 4))
                self.assertEqual(pointer, (SP - (20 if nls else 18), stack))
                expected = ([saved[r] for r in (UC_X86_REG_AX, UC_X86_REG_BX, UC_X86_REG_CX,
                             UC_X86_REG_DX, UC_X86_REG_SI, UC_X86_REG_DI, UC_X86_REG_BP,
                             UC_X86_REG_DS, UC_X86_REG_ES)] if nls else
                            [saved[r] for r in (UC_X86_REG_ES, UC_X86_REG_DS, UC_X86_REG_DI,
                             UC_X86_REG_SI, UC_X86_REG_BP, UC_X86_REG_BX, UC_X86_REG_DX,
                             UC_X86_REG_CX, UC_X86_REG_AX)])
                self.assertEqual(bytes(cpu.mem_read(pointer[1] * 16 + pointer[0], 18)),
                                 struct.pack("<9H", *expected))
            if address == CALLER * 16 + STOP:
                stops.append(address)
                cpu.emu_stop()

        machine.hook_add(UC_HOOK_CODE, instruction)
        machine.emu_start(CODE * 16 + entry, 0xFFFFF, count=2000)
        self.assertEqual(callbacks, [segment])
        self.assertEqual(stops, [CALLER * 16 + STOP])
        self.assertEqual((machine.reg_read(UC_X86_REG_SS), machine.reg_read(UC_X86_REG_SP)),
                         (stack, SP + 6))
        saved[UC_X86_REG_AX] = returned if nls else 0xBEEF
        if nls:
            saved[UC_X86_REG_BX] = 0xBEEF
        self.assertEqual({r: machine.reg_read(r) for r in saved}, saved)
        return machine.reg_read(UC_X86_REG_EFLAGS)

    def test_far_nls_frame_and_return_across_stack_switch(self):
        for own_stack in (False, True):
            with self.subTest(own_stack=own_stack):
                self.execute(True, True, own_stack)

    def test_far_internal_frame_and_return_across_stack_switch(self):
        for own_stack in (False, True):
            with self.subTest(own_stack=own_stack):
                self.execute(True, False, own_stack)

    def test_non_va_near_c_callback_frames_remain_valid(self):
        for nls in (False, True):
            for own_stack in (False, True):
                with self.subTest(nls=nls, own_stack=own_stack):
                    self.execute(False, nls, own_stack)

class NlsCallerAbiTests(unittest.TestCase):
    def execute(self, far):
        source = (ROOT / "kernel/int2f.asm").read_text()
        body = source.split("CALL_NLS:\n", 1)[1].split("; extern UWORD ASMPASCAL floppy_change", 1)[0]
        image = assemble("bits 16\ncpu 8086\norg 0\n_nlsInfo equ 0500h\n" +
                         ("%define PC88VA 1\n" if far else "") + body)
        machine = Uc(UC_ARCH_X86, UC_MODE_16)
        machine.mem_map(0, 0x100000)
        machine.mem_write(CODE * 16, image)
        return_segment = C_CODE if far else CODE
        # Pascal order: final scalar argument nearest the return address.
        args = [0x0022, 0xA001, 0xB002, 0x0004, 0x1234, 0x5000, 0xC003]
        frame = [STOP] + ([return_segment] if far else []) + args
        machine.mem_write(DATA * 16 + SP, struct.pack('<' + 'H' * len(frame), *frame))
        initial = {UC_X86_REG_CS: CODE, UC_X86_REG_SS: DATA, UC_X86_REG_DS: DATA,
                   UC_X86_REG_SP: SP, UC_X86_REG_BP: 0x7654,
                   UC_X86_REG_SI: 0x8765, UC_X86_REG_DI: 0x9876}
        for register, value in initial.items():
            machine.reg_write(register, value)
        calls = []

        def interrupt(cpu, number, _):
            self.assertEqual(number, 0x2F)
            actual = [cpu.reg_read(r) for r in (UC_X86_REG_AX, UC_X86_REG_BX,
                      UC_X86_REG_CX, UC_X86_REG_DX, UC_X86_REG_BP, UC_X86_REG_ES,
                      UC_X86_REG_DI, UC_X86_REG_DS, UC_X86_REG_SI)]
            self.assertEqual(actual, [0x1404, 0xB002, 0x22, 0xA001, 0xC003,
                                      0x5000, 0x1234, DATA, 0x500])
            calls.append(number)
            cpu.reg_write(UC_X86_REG_AX, 0xFFFF)
            cpu.reg_write(UC_X86_REG_BX, 0x534B)

        machine.hook_add(UC_HOOK_INTR, interrupt)
        machine.emu_start(CODE * 16, return_segment * 16 + STOP, count=2000)
        self.assertEqual(calls, [0x2F])
        self.assertEqual(machine.reg_read(UC_X86_REG_CS), return_segment)
        self.assertEqual(machine.reg_read(UC_X86_REG_IP), STOP)
        self.assertEqual(machine.reg_read(UC_X86_REG_SP), SP + 14 + (4 if far else 2))
        self.assertEqual((machine.reg_read(UC_X86_REG_AX), machine.reg_read(UC_X86_REG_DX)),
                         (0xFFFF, 0x534B))
        for register in (UC_X86_REG_DS, UC_X86_REG_BP, UC_X86_REG_SI, UC_X86_REG_DI):
            self.assertEqual(machine.reg_read(register), initial[register])

    def test_medium_pascal_arguments_result_and_cleanup(self):
        self.execute(True)

    def test_existing_near_pascal_arguments_result_and_cleanup(self):
        self.execute(False)


if __name__ == "__main__":
    unittest.main()
