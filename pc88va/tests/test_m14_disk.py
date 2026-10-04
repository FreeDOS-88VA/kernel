#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""ROM-free execution tests for the M14 resident write transfer core."""

from __future__ import annotations

import pathlib
import struct
import subprocess
import tempfile
import unittest

import unicorn
from unicorn import Uc, UC_ARCH_X86, UC_MODE_16, UC_HOOK_CODE
from unicorn.x86_const import (
    UC_X86_REG_AX, UC_X86_REG_BX, UC_X86_REG_CX, UC_X86_REG_DX,
    UC_X86_REG_SI, UC_X86_REG_DI, UC_X86_REG_BP, UC_X86_REG_SP,
    UC_X86_REG_CS, UC_X86_REG_DS, UC_X86_REG_ES, UC_X86_REG_SS,
    UC_X86_REG_EFLAGS,
)


BOOT = pathlib.Path(__file__).resolve().parents[1] / "boot"
CODE_SEG, DATA_SEG, STACK_SEG, BUFFER_SEG = 0x1200, 0x2800, 0x3800, 0x5800
REQUEST, CALLBACK, STOP = 0x1400, 0x1800, 0x1f00
SECTOR_BYTES = 512


class DiskWriteCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if unicorn.__version__ != "2.1.4":
            raise RuntimeError("M14 execution QA requires pinned Unicorn 2.1.4")
        cls.temporary = tempfile.TemporaryDirectory(prefix="pc88va-m14-unit-")
        cls.directory = pathlib.Path(cls.temporary.name)
        cls.binary = cls.directory / "disk-write.bin"
        command = ["nasm", "-f", "bin", "-DPC88VA", "-I", str(BOOT) + "/",
                   "-o", str(cls.binary), str(BOOT / "disk_write.inc")]
        subprocess.run(command, check=True, capture_output=True)
        cls.code = cls.binary.read_bytes()
        assert len(cls.code) < CALLBACK

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def execute(self, updates=None, results=None, clobber=False):
        # This synthetic 72-sector geometry is deliberately independent of
        # private media.  The callback models one accepted sector write.
        words = [1, 0, 1, 0x300, BUFFER_SEG, 0x4000, 72, 6, 2, SECTOR_BYTES,
                 0x321, CALLBACK, CODE_SEG, 0] + [0] * 10
        for index, value in (updates or {}).items():
            words[index] = value
        machine = Uc(UC_ARCH_X86, UC_MODE_16)
        machine.mem_map(0, 0x110000)
        machine.mem_write(CODE_SEG * 16, self.code)
        machine.mem_write(CODE_SEG * 16 + CALLBACK, b"\xcb")
        machine.mem_write(DATA_SEG * 16 + REQUEST, struct.pack("<24H", *words))
        machine.mem_write(BUFFER_SEG * 16 + 0x300, bytes(range(256)) * 16)
        stack = 0x3000
        machine.mem_write(STACK_SEG * 16 + stack, struct.pack("<H", STOP))
        preserved = {
            UC_X86_REG_BX: 0x1234, UC_X86_REG_CX: 0x2345,
            UC_X86_REG_DX: 0x3456, UC_X86_REG_SI: REQUEST,
            UC_X86_REG_DI: 0x4567, UC_X86_REG_BP: 0x5678,
            UC_X86_REG_DS: DATA_SEG, UC_X86_REG_ES: 0x6800,
            UC_X86_REG_SS: STACK_SEG,
        }
        for register, value in preserved.items():
            machine.reg_write(register, value)
        machine.reg_write(UC_X86_REG_SI, REQUEST)
        machine.reg_write(UC_X86_REG_CS, CODE_SEG)
        machine.reg_write(UC_X86_REG_SP, stack)
        machine.reg_write(UC_X86_REG_EFLAGS, 0x602)
        calls = []
        media = bytearray(72 * SECTOR_BYTES)
        outcomes = iter(results or [])

        def callback(cpu, address, _size, _):
            if address != CODE_SEG * 16 + CALLBACK:
                return
            request = struct.unpack("<24H", cpu.mem_read(DATA_SEG * 16 + REQUEST, 48))
            lba = request[21]
            source = request[20] * 16 + request[19]
            calls.append((lba, request[16], request[17], request[18],
                          request[19], request[20], request[10]))
            status, count = next(outcomes, (0, request[9]))
            if status == 0:
                payload = bytes(cpu.mem_read(source, min(count, request[9])))
                start = lba * SECTOR_BYTES
                media[start:start + len(payload)] = payload
            if clobber:
                for register in preserved:
                    if register != UC_X86_REG_SS:
                        cpu.reg_write(register, 0x7654)
            cpu.reg_write(UC_X86_REG_AX, status)
            cpu.reg_write(UC_X86_REG_CX, count)

        machine.hook_add(UC_HOOK_CODE, callback)
        machine.emu_start(CODE_SEG * 16, CODE_SEG * 16 + STOP, count=50000)
        self.assertEqual(machine.reg_read(UC_X86_REG_SP), stack + 2)
        for register, value in preserved.items():
            self.assertEqual(machine.reg_read(register), value,
                             "caller register preserved")
        flags = machine.reg_read(UC_X86_REG_EFLAGS)
        result = machine.reg_read(UC_X86_REG_AX)
        self.assertEqual(flags & ~1, 0x602)
        self.assertEqual(flags & 1, int(result != 0))
        final = struct.unpack("<24H", machine.mem_read(DATA_SEG * 16 + REQUEST, 48))
        return result, calls, final, media, machine

    def test_first_last_and_track_head_crossing(self):
        result, calls, final, media, _ = self.execute({1: 5, 2: 8})
        self.assertEqual(result, 0)
        self.assertEqual([entry[0] for entry in calls], list(range(5, 13)))
        self.assertEqual(final[14], 8 * SECTOR_BYTES)
        expected = bytes(range(256)) * 16
        self.assertEqual(media[5 * SECTOR_BYTES:6 * SECTOR_BYTES], expected[:SECTOR_BYTES])
        self.assertEqual(media[12 * SECTOR_BYTES:13 * SECTOR_BYTES], expected[:SECTOR_BYTES])
        result, calls, final, media, _ = self.execute({1: 71})
        self.assertEqual((result, calls[0][0], final[14]), (0, 71, SECTOR_BYTES))
        self.assertEqual(media[71 * SECTOR_BYTES:72 * SECTOR_BYTES], expected[:SECTOR_BYTES])

    def test_invalid_contract_range_and_capacity_do_not_call_device(self):
        for update, expected in (
            ({0: 2}, 1), ({7: 0}, 1), ({8: 0}, 1), ({9: 513}, 1),
            ({2: 0}, 2), ({1: 72}, 2), ({1: 71, 2: 2}, 2),
            ({1: 0xfffe, 2: 2, 6: 0xffff}, 2),
            ({5: 511}, 3), ({2: 128, 6: 512}, 3), ({3: 0xff00}, 3),
            ({4: 0xffff}, 2),
        ):
            with self.subTest(update=update):
                result, calls, final, media, _ = self.execute(update)
                self.assertEqual((result, calls), (expected, []))
        self.assertEqual(final[14], 0)
        self.assertEqual(media, bytes(len(media)))

    def test_not_ready_and_timeout_do_not_retry_a_removable_request(self):
        for firmware_status in (4, 0x0d):
            with self.subTest(firmware_status=firmware_status):
                result, calls, final, media, _ = self.execute(
                    results=[(firmware_status, 0)]
                )
                self.assertEqual((result, len(calls), final[14]), (5, 1, 0))
                self.assertEqual(media, bytes(len(media)))

    def test_short_transfer_and_bounded_retry(self):
        result, calls, final, media, _ = self.execute(results=[(0, 511)])
        self.assertEqual((result, len(calls), final[14]), (4, 1, 0))
        # A short completion is reported as an error after the adapter has
        # supplied its declared prefix; it must not be reported as success.
        expected = bytes(range(256)) * 16
        self.assertEqual(media[:511], expected[:511])
        self.assertEqual(media[511], 0)
        result, calls, final, media, _ = self.execute({13: 1}, [(7, 0), (0, 512)])
        self.assertEqual((result, len(calls), final[14]), (0, 2, 512))
        self.assertNotEqual(media[:SECTOR_BYTES], bytes(SECTOR_BYTES))
        result, calls, final, media, _ = self.execute({13: 2}, [(7, 0)] * 3)
        self.assertEqual((result, len(calls), final[14]), (5, 3, 0))
        self.assertEqual(media, bytes(len(media)))

    def test_callback_register_clobbers_are_contained(self):
        result, calls, final, _, _ = self.execute({2: 3}, clobber=True)
        self.assertEqual((result, len(calls), final[14]), (0, 3, 3 * SECTOR_BYTES))

    def test_binary_is_reproducible(self):
        second = self.directory / "disk-write-second.bin"
        subprocess.run(["nasm", "-f", "bin", "-DPC88VA", "-I", str(BOOT) + "/",
                        "-o", str(second), str(BOOT / "disk_write.inc")],
                       check=True, capture_output=True)
        self.assertEqual(second.read_bytes(), self.code)


if __name__ == "__main__":
    unittest.main()
