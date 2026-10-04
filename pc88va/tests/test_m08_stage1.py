# SPDX-License-Identifier: GPL-2.0-or-later
"""ROM-free bootstrap extent and fail-closed execution tests."""
import pathlib
import struct
import subprocess
import tempfile
import unittest

from unicorn import Uc, UC_ARCH_X86, UC_MODE_16, UC_HOOK_CODE
from unicorn.x86_const import *

BOOT = pathlib.Path(__file__).resolve().parents[1] / "boot"
PROFILE = """
%define PC88VA_PROFILE_VERSION 1
%define S1_IMAGE_OFFSET 0
%define S1_ENTRY_SEGMENT 0x1000
%define S1_STAGE2_LBA 19
%define S1_STAGE2_COUNT 4
%define S1_DRIVE_CONTEXT 7
%define S1_CALL_FLAGS 2
%define S2_STAGE2_SEGMENT 0x2000
%define S2_STAGE2_CAPACITY 8192
%define S2_STACK_SEGMENT 0x3000
%define S2_STACK_POINTER 4096
%define S2_SECTOR_BYTES 1024
%define S2_SECTORS_TRACK 8
%define S2_HEADS 2
%define S2_TOTAL_SECTORS 1280
%macro PC88VA_FIRMWARE_READ_ONE 0
mov ax, 0x1234
retf
%endmacro
"""


class Stage1Tests(unittest.TestCase):
    def assemble(self, extra="", succeeds=True):
        with tempfile.TemporaryDirectory() as directory:
            base = pathlib.Path(directory)
            profile, output = base / "profile.inc", base / "stage1.bin"
            profile.write_text(PROFILE + extra)
            result = subprocess.run(["nasm", "-f", "bin", "-DPC88VA", "-I" + str(BOOT) + "/",
                                     "-p", str(profile), "-o", str(output), str(BOOT / "stage1.asm")],
                                    capture_output=True)
            if not succeeds:
                self.assertNotEqual(result.returncode, 0)
                return
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            return output.read_bytes()

    def test_layout_and_two_build_identity(self):
        image = self.assemble()
        self.assertEqual(image, self.assemble())
        self.assertEqual(len(image), 1024)
        self.assertEqual(image[:3], b"\xeb\x3c\x90")
        self.assertEqual(image[3:62], bytes(59))
        self.assertEqual(image[510:512], bytes(2))
        self.assertEqual(image[1022:], bytes(2))

    def test_extent_rejection(self):
        for setting in ("S1_STAGE2_COUNT 0", "S1_STAGE2_COUNT 9", "S1_STAGE2_LBA 1279"):
            self.assemble("\n%define " + setting + "\n", succeeds=False)

    def execute(self, error=False, short=False, wrong_cs=False):
        image = self.assemble()
        machine = Uc(UC_ARCH_X86, UC_MODE_16)
        machine.mem_map(0, 0x100000)
        segment = 0x1100 if wrong_cs else 0x1000
        start = segment * 16
        machine.mem_write(start, image)
        machine.reg_write(UC_X86_REG_CS, segment)
        machine.reg_write(UC_X86_REG_SS, 0)
        machine.reg_write(UC_X86_REG_SP, 0)
        adapter = start + image.index(b"\xb8\x34\x12\xcb")
        reads, entered = [], []
        payload = bytes(range(256)) * 16

        def instruction(uc, address, size, context):
            if address == 0x20000:
                entered.append((uc.reg_read(UC_X86_REG_DX), uc.reg_read(UC_X86_REG_BX)))
                uc.emu_stop()
            if address == adapter:
                request = uc.reg_read(UC_X86_REG_DS) * 16 + uc.reg_read(UC_X86_REG_SI)
                words = struct.unpack("<24H", uc.mem_read(request, 48))
                # Current LBA/offset/segment follow the public RD ABI.
                lba, offset, destination = words[21], words[19], words[20]
                reads.append(lba)
                if not error:
                    uc.mem_write(destination * 16 + offset, payload[(lba-19)*1024:(lba-18)*1024])
                uc.reg_write(UC_X86_REG_AX, 1 if error else 0)
                uc.reg_write(UC_X86_REG_CX, 512 if short else 1024)
                uc.reg_write(UC_X86_REG_IP, uc.reg_read(UC_X86_REG_IP) + 3)

        machine.hook_add(UC_HOOK_CODE, instruction)
        machine.emu_start(start, 0x100000, count=20000)
        return reads, entered, bytes(machine.mem_read(0x20000, len(payload))), payload

    def test_extent_loaded_and_opaque_context_transferred(self):
        reads, entered, actual, expected = self.execute()
        self.assertEqual(reads, [19, 20, 21, 22])
        self.assertEqual(entered, [(7, 2)])
        self.assertEqual(actual, expected)

    def test_failed_and_short_reads_never_transfer(self):
        for options in ({"error": True}, {"short": True}, {"wrong_cs": True}):
            self.assertFalse(self.execute(**options)[1])
