#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""ROM-free DOS CON queue, extended-key and guest-timer repeat tests."""
import struct
import unittest
from unicorn.x86_const import UC_X86_REG_EFLAGS

from test_m11_consumer import CODE, ConsumerTests, matrix


class M16InputTests(ConsumerTests):
    def character_word(self):
        return struct.unpack('<H', self.cpu.mem_read(
            CODE * 16 + self.character, 2))[0]

    def start_from_released(self):
        self.assertEqual(self.invoke(self.read, matrix()), 1)

    def read_extended(self, positions, expected):
        pressed = matrix(*positions)
        self.assertEqual(self.invoke(self.read, pressed), 0)
        self.assertEqual(self.character_word(), 0)
        self.assertEqual(self.invoke(self.read, pressed), 0)
        self.assertEqual(self.character_word(), expected)

    def test_all_function_keys_use_dos_extended_pairs(self):
        keys = [(0x91 + i, 0x3b + i) for i in range(5)]
        keys += [(0xc0 + i, 0x40 + i) for i in range(5)]
        for position, code in keys:
            with self.subTest(position=hex(position)):
                self.setUp()
                self.start_from_released()
                self.read_extended((position,), code)
                self.assertEqual(self.invoke(self.read, matrix(position)), 1)

    def test_vaeg_f6_f10_compatibility_aliases_are_one_function_key(self):
        # VAEG mirrors each row-12 F6-F10 contact onto row-9 F1-F5.
        for index in range(5):
            position = 0xc0 + index
            alias = 0x91 + index
            with self.subTest(position=hex(position), alias=hex(alias)):
                self.setUp()
                self.start_from_released()
                self.read_extended((position, alias), 0x40 + index)
                self.assertEqual(self.invoke(self.read, matrix(position, alias)), 1)

    def test_shifted_f10_with_vaeg_alias_and_unrelated_chord(self):
        self.start_from_released()
        self.read_extended((0xe2, 0x95, 0xc4), 0x89)

        self.setUp()
        self.start_from_released()
        self.assertEqual(self.invoke(self.read, matrix(0x46, 0x95, 0xc4)), 1)

    def test_editing_keys_and_cursor_keys(self):
        cases = [(0x81, 0x48), (0xa1, 0x50), (0xa2, 0x4b), (0x82, 0x4d),
                 (0x80, 0x47), (0xa3, 0x4f), (0xc6, 0x52), (0xc7, 0x53)]
        for position, code in cases:
            with self.subTest(position=hex(position)):
                self.setUp()
                self.start_from_released()
                self.read_extended((position,), code)

    def test_control_arrows_and_project_shift_extensions(self):
        cases = [((0x87, 0xa2), 0x73), ((0x87, 0x82), 0x74),
                 ((0xe2, 0x81), 0x8a), ((0xe2, 0xa1), 0x8b),
                 ((0xe2, 0xa2), 0x8c), ((0xe2, 0x82), 0x8d),
                 ((0xe2, 0x91), 0x80), ((0xe3, 0xc4), 0x89)]
        for positions, code in cases:
            with self.subTest(positions=tuple(hex(p) for p in positions)):
                self.setUp()
                self.start_from_released()
                self.read_extended(positions, code)

    def test_extended_peek_is_non_destructive_and_flush_discards_second_byte(self):
        self.start_from_released()
        f1 = matrix(0x91)
        self.assertEqual(self.invoke(self.peek, f1), 0)
        self.assertEqual(self.character_word(), 0)
        self.assertEqual(self.invoke(self.peek, matrix()), 0)
        self.assertEqual(self.character_word(), 0)
        self.assertEqual(self.invoke(self.read, matrix()), 0)
        self.assertEqual(self.cpu.mem_read(
            CODE * 16 + self.second_valid, 1), b'\x01')
        self.assertEqual(self.invoke(self.flush, f1), self.character)
        self.assertEqual(self.cpu.mem_read(
            CODE * 16 + self.second_valid, 1), b'\x00')
        self.assertEqual(self.invoke(self.read, f1), 1,
                         'flush adopts the currently held key as the new baseline')

    def test_repeat_uses_clock_deadlines_and_stops_on_release(self):
        self.start_from_released()
        up = matrix(0x81)
        self.assertEqual(self.invoke(self.read, up), 0)
        self.assertEqual(self.character_word(), 0)
        self.assertEqual(self.invoke(self.read, up), 0)
        self.assertEqual(self.character_word(), 0x48)
        self.assertEqual(self.invoke(self.read, up), 1)
        self.assertEqual(self.invoke(self.read, up), 1)
        self.assertEqual(self.invoke(self.read, up), 0,
                         'first repeat appears after the configured guest-clock delay')
        self.assertEqual(self.character_word(), 0)
        self.assertEqual(self.invoke(self.read, up), 0)
        self.assertEqual(self.character_word(), 0x48)
        self.assertEqual(self.invoke(self.read, matrix()), 1)
        for _ in range(4):
            self.assertEqual(self.invoke(self.read, matrix()), 1)

    def test_queue_is_event_atomic_and_drops_new_event_when_full(self):
        for byte in range(1, 9):
            self.assertEqual(self.invoke(self.enqueue, matrix(), ax=byte), byte)
            self.assertEqual(self.cpu.reg_read(UC_X86_REG_EFLAGS) & 1, 0)
        self.assertEqual(self.cpu.mem_read(
            CODE * 16 + self.queue_count, 1), b'\x08')
        self.assertEqual(self.invoke(self.enqueue, matrix(), ax=0x3b00), 0x3b00)
        self.assertEqual(self.cpu.reg_read(UC_X86_REG_EFLAGS) & 1, 1)
        words = struct.unpack('<8H', self.cpu.mem_read(
            CODE * 16 + self.queue, 16))
        self.assertEqual(words, tuple(range(1, 9)))

    def test_unsupported_modes_and_ambiguous_chords_are_ignored(self):
        self.start_from_released()
        for positions in ((0x84,), (0x85,), (0xa7,), (0x21, 0x22), (0xe2, 0x91, 0x87)):
            with self.subTest(positions=positions):
                self.assertEqual(self.invoke(self.read, matrix(*positions)), 1)


if __name__ == '__main__':
    unittest.main()
