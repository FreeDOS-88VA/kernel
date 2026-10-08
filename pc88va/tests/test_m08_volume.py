# SPDX-License-Identifier: GPL-2.0-or-later
"""Execute the FAT12 BPB validator with synthetic and public M05 layout fields."""
import pathlib
import struct
import subprocess
import tempfile
import unittest

import unicorn
from unicorn import Uc, UC_ARCH_X86, UC_MODE_16
from unicorn.x86_const import (
    UC_X86_REG_AX, UC_X86_REG_BX, UC_X86_REG_CX, UC_X86_REG_DX,
    UC_X86_REG_SI, UC_X86_REG_DI, UC_X86_REG_BP, UC_X86_REG_SP,
    UC_X86_REG_CS, UC_X86_REG_DS, UC_X86_REG_ES, UC_X86_REG_SS,
    UC_X86_REG_EFLAGS,
)

BOOT = pathlib.Path(__file__).resolve().parents[1] / "boot"
CODE, DATA, STACK, SECTOR = 0x1200, 0x2800, 0x3800, 0x4800
REQUEST, DISK, STOP = 0x1400, 0x1600, 0x1f00


def boot_sector(updates=None, sector=512, total=72, spc=1, spf=1, roots=32, spt=6):
    image = bytearray(sector)
    struct.pack_into("<HBHBHHBHHHII", image, 11,
                     sector, spc, 1, 2, roots, total, 0xf0, spf, spt, 2, 0, 0)
    for (offset, width), value in (updates or {}).items():
        image[offset:offset + width] = value.to_bytes(width, "little")
    return bytes(image)


class VolumeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if unicorn.__version__ != "2.1.4":
            raise RuntimeError("M08 execution QA requires pinned Unicorn 2.1.4")
        cls.temporary = tempfile.TemporaryDirectory(prefix="pc88va-m08-volume-")
        binaries = []
        for number in (1, 2):
            target = pathlib.Path(cls.temporary.name) / (str(number) + ".bin")
            subprocess.run(["nasm", "-f", "bin", "-DPC88VA", "-I", str(BOOT) + "/",
                            "-o", str(target), str(BOOT / "volume_validate.inc")],
                           check=True, capture_output=True)
            binaries.append(target.read_bytes())
        if binaries[0] != binaries[1]:
            raise AssertionError("Two clean volume-validator builds differ")
        cls.code = binaries[0]

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def execute(self, image=None, updates=None, disk_updates=None):
        image = boot_sector() if image is None else image
        disk = [1, 0, 1, 0x300, SECTOR, 4096, 72, 6, 2, 512,
                0, 0x100, CODE, 0] + [0] * 10
        for index, value in (disk_updates or {}).items():
            disk[index] = value
        words = [1, 0x300, SECTOR, len(image), DISK, 8192, 8192, 512] + [0] * 14
        for index, value in (updates or {}).items():
            words[index] = value
        machine = Uc(UC_ARCH_X86, UC_MODE_16)
        machine.mem_map(0, 0x110000)
        machine.mem_write(CODE * 16, self.code)
        machine.mem_write(DATA * 16 + REQUEST, struct.pack("<22H", *words))
        machine.mem_write(DATA * 16 + DISK, struct.pack("<24H", *disk))
        machine.mem_write(words[2] * 16 + words[1], image)
        machine.mem_write(STACK * 16 + 0x3000, struct.pack("<H", STOP))
        registers = {
            UC_X86_REG_BX: 0x1234, UC_X86_REG_CX: 0x2345, UC_X86_REG_DX: 0x3456,
            UC_X86_REG_SI: REQUEST, UC_X86_REG_DI: 0x4567, UC_X86_REG_BP: 0x5678,
            UC_X86_REG_DS: DATA, UC_X86_REG_ES: 0x7800, UC_X86_REG_SS: STACK,
        }
        for register, value in registers.items():
            machine.reg_write(register, value)
        machine.reg_write(UC_X86_REG_CS, CODE)
        machine.reg_write(UC_X86_REG_SP, 0x3000)
        machine.reg_write(UC_X86_REG_EFLAGS, 0x602)
        machine.emu_start(CODE * 16, CODE * 16 + STOP, count=100000)
        self.assertEqual(machine.reg_read(UC_X86_REG_SP), 0x3002)
        for register, value in registers.items():
            self.assertEqual(machine.reg_read(register), value)
        status = machine.reg_read(UC_X86_REG_AX)
        self.assertEqual(machine.reg_read(UC_X86_REG_EFLAGS), 0x602 | int(status != 0))
        self.assertEqual(bytes(machine.mem_read(words[2] * 16 + words[1], len(image))), image)
        self.assertEqual(bytes(machine.mem_read(DATA * 16 + DISK, 48)), struct.pack("<24H", *disk))
        final = struct.unpack("<22H", machine.mem_read(DATA * 16 + REQUEST, 44))
        self.assertEqual(final[:8], tuple(words[:8]))
        self.assertEqual(final[20], int(status == 0))
        return status, final

    def test_synthetic_layout(self):
        status, final = self.execute()
        self.assertEqual(status, 0)
        self.assertEqual(final[8:], (512, 1, 1, 1, 512, 3, 2, 32, 1024, 5, 67, 0xf0, 1, 9))

    def test_public_m05_layout(self):
        image = boot_sector({(21, 1): 0xfe}, sector=1024, total=1280, spf=2, roots=192, spt=8)
        status, final = self.execute(image, disk_updates={6: 1280, 7: 8, 9: 1024})
        self.assertEqual(status, 0)
        self.assertEqual(final[8:], (1024, 1, 1, 2, 2048, 5, 6, 192, 6144, 11, 1269, 0xfe, 1, 159))

    def test_fewer_whole_cylinders_of_the_same_geometry(self):
        image = boot_sector({(21, 1): 0xfe}, sector=1024, total=1232, spf=2, roots=192, spt=8)
        status, final = self.execute(image, disk_updates={6: 1280, 7: 8, 9: 1024})
        self.assertEqual(status, 0)
        self.assertEqual(final[8:], (1024, 1, 1, 2, 2048, 5, 6, 192, 6144, 11, 1221, 0xfe, 1, 153))
        for total in (1250, 1296):
            with self.subTest(total=total):
                image = boot_sector({(21, 1): 0xfe}, sector=1024, total=total, spf=2,
                                    roots=192, spt=8)
                self.assertEqual(
                    self.execute(image, disk_updates={6: 1280, 7: 8, 9: 1024})[0], 54)

    def test_root_rounding_and_partial_final_cluster(self):
        status, final = self.execute(boot_sector(roots=17, spc=2))
        self.assertEqual(status, 0)
        self.assertEqual((final[14], final[16], final[18], final[21]), (2, 1024, 33, 5))

    def test_32bit_total_with_zero_high_word(self):
        self.assertEqual(self.execute(boot_sector({(19, 2): 0, (32, 4): 72}))[0], 0)

    def test_ambiguous_overflowing_or_wrong_geometry(self):
        for update in ({(19, 2): 71}, {(19, 2): 0}, {(32, 4): 72},
                       {(19, 2): 0, (32, 4): 0x10048}, {(11, 2): 1024},
                       {(24, 2): 8}, {(26, 2): 1}):
            with self.subTest(update=update):
                self.assertEqual(self.execute(boot_sector(update))[0], 54)

    def test_invalid_context_or_adapter_geometry(self):
        for update in ({0: 2}, {4: 0xfff0}):
            self.assertEqual(self.execute(updates=update)[0], 50)
        # Disk request versions 1 and 2 are valid; version 3 is not.
        for update in ({0: 3}, {6: 0}, {7: 0}, {7: 256}, {8: 0}, {8: 257},
                       {9: 64}, {9: 513}, {9: 8192}):
            self.assertEqual(self.execute(disk_updates=update)[0], 50)

    def test_non_superfloppy_or_invalid_fat12_fields(self):
        for update in ({(28, 4): 1}, {(30, 2): 1}, {(16, 1): 1}, {(16, 1): 3},
                       {(13, 1): 0}, {(13, 1): 3}, {(13, 1): 255},
                       {(21, 1): 0xf1}, {(21, 1): 0}, {(14, 2): 0},
                       {(22, 2): 0}, {(17, 2): 0}):
            with self.subTest(update=update):
                self.assertEqual(self.execute(boot_sector(update))[0], 51)

    def test_short_wrapping_or_out_of_memory_boot_sector(self):
        for update in ({3: 511}, {1: 0xff00}, {2: 0xffff}):
            self.assertEqual(self.execute(updates=update)[0], 53)

    def test_cache_and_bitmap_capacity(self):
        for update in ({5: 511}, {6: 1023}, {7: 8}):
            self.assertEqual(self.execute(updates=update)[0], 53)
        self.assertEqual(self.execute(boot_sector({(22, 2): 128}))[0], 53)
        self.assertEqual(self.execute(boot_sector({(17, 2): 2048}))[0], 53)

    def test_packed_fat_must_cover_all_clusters(self):
        self.assertEqual(self.execute(boot_sector(total=4000), disk_updates={6: 4000})[0], 53)

    def test_no_data_cluster_or_fat16_sized_volume(self):
        for total, spc in ((5, 1), (6, 2), (5000, 1)):
            with self.subTest(total=total, spc=spc):
                self.assertEqual(self.execute(boot_sector(total=total, spc=spc), disk_updates={6: total})[0], 52)

    def test_metadata_or_cluster_byte_count_overflow(self):
        self.assertEqual(self.execute(boot_sector({(14, 2): 65535}))[0], 52)
        self.assertEqual(self.execute(boot_sector(spc=128))[0], 52)


if __name__ == "__main__":
    unittest.main()
