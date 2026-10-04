#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""DOS control-key mapping over the public VAEG keyboard matrix contract.

The early M11 raw entry retains its narrower unsupported-modifier contract.
The DOS entry must deliver character codes; the common DOS kernel owns break
and EOF policy. Coordinates come from VAEG io/serial.c scantomap, not ROM data.
"""
import struct
import unittest
from test_m11_consumer import ConsumerTests, CODE, matrix
from test_m11_input import LETTERS


class DosControlTests(ConsumerTests):
    def character_word(self):
        return struct.unpack('<H', self.cpu.mem_read(CODE * 16 + self.character, 2))[0]

    def test_control_letters_are_characters_without_repeat(self):
        for letter, position in LETTERS.items():
            with self.subTest(letter=letter):
                self.setUp()
                self.assertEqual(self.invoke(self.read, matrix()), 1)
                self.assertEqual(self.invoke(self.read, matrix(0x87)), 1)
                self.assertEqual(self.invoke(self.peek, matrix(0x87, position)), 0)
                self.assertEqual(self.character_word(), ord(letter) - ord('a') + 1)
                self.assertEqual(self.invoke(self.peek, matrix()), 0)
                self.assertEqual(self.invoke(self.read, matrix()), 0)
                self.assertEqual(self.invoke(self.read, matrix(0x87, position)), 1)
                self.assertEqual(self.invoke(self.read, matrix()), 1)

    def test_control_shift_letter_and_simultaneous_modifier(self):
        self.assertEqual(self.invoke(self.read, matrix()), 1)
        self.assertEqual(self.invoke(self.read, matrix(0x87, 0xe2, 0x86, 0x23)), 0)
        self.assertEqual(self.character_word(), 3)

    def test_escape_and_tab_in_dos_entry(self):
        for position, expected in ((0x97, 27), (0xa0, 9)):
            with self.subTest(position=position):
                self.setUp()
                self.assertEqual(self.invoke(self.read, matrix()), 1)
                self.assertEqual(self.invoke(self.read, matrix(position)), 0)
                self.assertEqual(self.character_word(), expected)

    def test_other_modes_and_multiple_letters_are_ignored_by_dos(self):
        for positions in ((0x84, 0x23), (0x85, 0x23), (0xa7, 0x23),
                          (0x87, 0x21, 0x22), (0x87, 0x60)):
            with self.subTest(positions=positions):
                self.setUp()
                self.assertEqual(self.invoke(self.read, matrix()), 1)
                self.assertEqual(self.invoke(self.read, matrix(*positions)), 1)


if __name__ == '__main__':
    unittest.main()
