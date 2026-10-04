#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Execute the common INT 24 bridge with synthetic near and VA far C callers."""
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

import unicorn
from unicorn import Uc, UC_ARCH_X86, UC_MODE_16, UC_HOOK_CODE, UC_HOOK_INTR
from unicorn.x86_const import (
    UC_X86_REG_AX, UC_X86_REG_BP, UC_X86_REG_CS, UC_X86_REG_DI,
    UC_X86_REG_DS, UC_X86_REG_ES, UC_X86_REG_IP, UC_X86_REG_SI,
    UC_X86_REG_SP, UC_X86_REG_SS, UC_X86_REG_EFLAGS,
)

ROOT = Path(__file__).resolve().parents[2]
CODE, DATA, CALLER, PSP, USER = 0x1100, 0x4000, 0x2300, 0x5800, 0x6000
STOP, KSP, USP = 0x1000, 0x8000, 0x9000
GLOBALS = ("_ErrorMode", "_InDOS", "_cu_psp", "_MachineId",
           "int21regs_seg", "int21regs_off", "_user_r", "critical_sp")
OFFSETS = dict(zip(GLOBALS, range(0x200, 0x220, 4)))


class CriticalErrorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if unicorn.__version__ != "2.1.4":
            raise RuntimeError("M14 execution QA requires pinned Unicorn 2.1.4")
        source = (ROOT / "kernel/entry.asm").read_text()
        # This is the entire production function, including the abort path.
        body = source[source.index("CONTINUE        equ"):]
        cls.images = {}
        for far in (False, True):
            text = ("bits 16\ncpu 8086\norg 0\n%define XCPU 86\n"
                    '%include "stacks.inc"\n' +
                    ("%define PC88VA 1\n" if far else "") +
                    "dw _CriticalError, int21_reentry\n_DGROUP_: dw " + str(DATA) + "\n" +
                    "\n".join(f"{name} equ {offset}" for name, offset in OFFSETS.items()) +
                    "\n" + body + "\nint21_reentry: hlt\n")
            with tempfile.TemporaryDirectory(prefix="m14-critical-error-") as directory:
                assembly, binary = Path(directory) / "test.asm", Path(directory) / "test.bin"
                assembly.write_text(text)
                result = subprocess.run(["nasm", "-f", "bin", "-I", str(ROOT / "hdr") + "/",
                                         "-o", str(binary), str(assembly)], capture_output=True)
                if result.returncode:
                    raise AssertionError(result.stderr.decode(errors="replace"))
                cls.images[far] = binary.read_bytes()

    def execute(self, far, flags=0x39, drive=0, error=0, response=3,
                busy=False, parent_is_self=True):
        machine = Uc(UC_ARCH_X86, UC_MODE_16)
        machine.mem_map(0, 0x110000)
        image = self.images[far]
        entry, abort = struct.unpack_from("<2H", image)
        self.assertLess(len(image), STOP)
        machine.mem_write(CODE * 16, image)
        return_segment = CALLER if far else CODE
        frame = [STOP] + ([return_segment] if far else []) + [flags, drive, error, 0x1234, 0x5678]
        machine.mem_write(DATA * 16 + KSP, struct.pack("<" + "H" * len(frame), *frame))
        saved = {"_ErrorMode": int(busy), "_InDOS": 1, "_cu_psp": PSP,
                 "_MachineId": 0xCAFE, "int21regs_seg": USER,
                 "int21regs_off": 0x7000, "_user_r": 0x7100 | (USER << 16),
                 "critical_sp": 0}
        for name, value in saved.items():
            machine.mem_write(DATA * 16 + OFFSETS[name], struct.pack("<I", value))
        machine.mem_write(PSP * 16 + 0x16, struct.pack("<H", PSP if parent_is_self else PSP - 0x100))
        machine.mem_write(PSP * 16 + 0x2E, struct.pack("<2H", USP, USER))
        for register, value in ((UC_X86_REG_CS, CODE), (UC_X86_REG_DS, DATA),
                                (UC_X86_REG_SS, DATA), (UC_X86_REG_SP, KSP),
                                (UC_X86_REG_BP, 0xABCD), (UC_X86_REG_SI, 0xBCDE),
                                (UC_X86_REG_DI, 0xCDEF), (UC_X86_REG_EFLAGS, 0x202)):
            machine.reg_write(register, value)
        calls, stops = [], []

        def interrupt(cpu, number, _):
            self.assertEqual(number, 0x24)
            calls.append(tuple(cpu.reg_read(register) for register in
                               (UC_X86_REG_AX, UC_X86_REG_DI, UC_X86_REG_BP, UC_X86_REG_SI)))
            self.assertEqual(calls[-1], ((flags << 8) | drive, error, 0x5678, 0x1234))
            self.assertEqual((cpu.reg_read(UC_X86_REG_SS), cpu.reg_read(UC_X86_REG_SP)), (USER, USP))
            self.assertEqual(bytes(cpu.mem_read(DATA * 16 + OFFSETS["_ErrorMode"], 1)), b"\1")
            self.assertEqual(bytes(cpu.mem_read(DATA * 16 + OFFSETS["_InDOS"], 1)), b"\0")
            # Nested DOS use may replace these saved pointers and working registers.
            for name in ("_MachineId", "int21regs_seg", "int21regs_off", "_user_r"):
                width = 4 if name == "_user_r" else 2
                cpu.mem_write(DATA * 16 + OFFSETS[name], b"\xAA" * width)
            cpu.mem_write(PSP * 16 + 0x2E, b"\xAA" * 4)
            for register in (UC_X86_REG_BP, UC_X86_REG_SI, UC_X86_REG_DI,
                             UC_X86_REG_DS, UC_X86_REG_ES):
                cpu.reg_write(register, 0xAAAA)
            cpu.reg_write(UC_X86_REG_AX, 0xFF00 | response)

        def stop(cpu, address, _size, _):
            if address in (CODE * 16 + abort, CODE * 16 + STOP, CALLER * 16 + STOP):
                stops.append(address)
                cpu.emu_stop()

        machine.hook_add(UC_HOOK_INTR, interrupt)
        machine.hook_add(UC_HOOK_CODE, stop)
        machine.emu_start(CODE * 16 + entry, 0x10FFFF, count=20000)
        aborting = not busy and not parent_is_self and (response == 2 or not (flags & 8) and response == 3)
        self.assertEqual(stops, [CODE * 16 + abort if aborting else return_segment * 16 + STOP])
        self.assertEqual(len(calls), 0 if busy else 1)
        for name in ("_MachineId", "int21regs_seg", "int21regs_off", "_user_r"):
            width = 4 if name == "_user_r" else 2
            actual = int.from_bytes(machine.mem_read(DATA * 16 + OFFSETS[name], width), "little")
            self.assertEqual(actual, saved[name])
        self.assertEqual(bytes(machine.mem_read(PSP * 16 + 0x2E, 4)), struct.pack("<2H", USP, USER))
        self.assertEqual(bytes(machine.mem_read(DATA * 16 + OFFSETS["_InDOS"], 1)), b"\1")
        if aborting:
            self.assertEqual(bytes(machine.mem_read(DATA * 16 + OFFSETS["_ErrorMode"], 1)), b"\1")
            self.assertEqual((machine.reg_read(UC_X86_REG_SS), machine.reg_read(UC_X86_REG_SP)), (USER, 0x7100))
            self.assertEqual(bytes(machine.mem_read(USER * 16 + 0x7100, 2)), b"\0L")
            return None
        self.assertEqual(machine.reg_read(UC_X86_REG_CS), return_segment)
        self.assertEqual(machine.reg_read(UC_X86_REG_IP), STOP)
        self.assertEqual(machine.reg_read(UC_X86_REG_SS), DATA)
        self.assertEqual(machine.reg_read(UC_X86_REG_SP), KSP + (4 if far else 2))
        self.assertEqual([machine.reg_read(r) for r in (UC_X86_REG_BP, UC_X86_REG_SI, UC_X86_REG_DI)],
                         [0xABCD, 0xBCDE, 0xCDEF])
        self.assertEqual(bytes(machine.mem_read(DATA * 16 + OFFSETS["_ErrorMode"], 1)), bytes([int(busy)]))
        return machine.reg_read(UC_X86_REG_AX)

    def test_medium_model_far_arguments_and_return(self):
        for drive, error in ((0, 0), (1, 2), (3, 12)):
            with self.subTest(drive=drive, error=error):
                self.assertEqual(self.execute(True, drive=drive, error=error), 3)

    def test_recursive_handler_fails_without_callback(self):
        for far in (False, True):
            with self.subTest(far=far):
                self.assertEqual(self.execute(far, busy=True), 3)

    def test_reply_policy_restores_the_original_flags(self):
        for far in (False, True):
            for flags, reply, expected in ((0x39, 0, 0), (0x39, 1, 1), (0x39, 3, 3),
                                           (0x09, 0, 3), (0x09, 1, 3), (0x30, 3, 3), (0x39, 2, 3)):
                with self.subTest(far=far, flags=flags, reply=reply):
                    self.assertEqual(self.execute(far, flags=flags, response=reply), expected)

    def test_abort_reenters_termination_with_restored_user_frame(self):
        for far in (False, True):
            for flags, response in ((0x39, 2), (0x30, 3)):
                with self.subTest(far=far, flags=flags, response=response):
                    self.assertIsNone(self.execute(far, flags=flags, response=response, parent_is_self=False))


if __name__ == "__main__":
    unittest.main()
