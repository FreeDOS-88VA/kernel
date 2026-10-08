# SPDX-License-Identifier: GPL-2.0-or-later
"""Execute composed root/FAT/disk/copy code, without private media or firmware."""
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
from test_m08_fat import encode
from test_m08_root import entry

BOOT = pathlib.Path(__file__).resolve().parents[1] / "boot"
CODE, DATA, STACK = 0x1200, 0x2800, 0x3800
ROOT, FAT, SCRATCH, FILE, VISITED = 0x4800, 0x5000, 0x5800, 0x6800, 0x7800
FL, RD, FT, RT = 0x1000, 0x1100, 0x1200, 0x1300
CALLBACK, STOP = 0x4000, 0x4800


class FileLoadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if unicorn.__version__ != "2.1.4":
            raise RuntimeError("M08 execution QA requires pinned Unicorn 2.1.4")
        cls.temporary = tempfile.TemporaryDirectory(prefix="pc88va-m08-file-")
        root = pathlib.Path(cls.temporary.name)
        source, target = root / "file.asm", root / "file.bin"
        source.write_text('bits 16\ncpu 8086\norg 0\njmp pc88va_file_load_core\n' +
                          ''.join('%include "' + name + '.inc"\n' for name in
                                  ("disk_read", "fat12", "root_directory", "file_load")))
        subprocess.run(["nasm", "-f", "bin", "-DPC88VA", "-I", str(BOOT) + "/",
                        "-o", str(target), str(source)], check=True, capture_output=True)
        cls.code = target.read_bytes()
        assert len(cls.code) < CALLBACK

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def execute(self, file_size=1100, spc=1, links=None, updates=None, results=None,
                missing=False, corrupt_copy=False, disk_total=None, version=1):
        disk = [version, 0, 1, 0x300, SCRATCH, 512,
                5 + 10 * spc if disk_total is None else disk_total, 4, 2, 512,
                0x321, CALLBACK, CODE, 0] + [0] * 11
        fat = [1, 0x200, FAT, 32, 10, 2, 0, 0x500, VISITED, 512, 0, 0, 0]
        directory = [1, 0x100, ROOT, 1, 32, 10, 8192, 0, 0, 0]
        file_request = [1, RD, FT, RT, 0x400, FILE, 8192, 5, spc,
                        0x300, SCRATCH, 512] + [0] * 13
        for index, value in (updates or {}).items():
            file_request[index] = value
        table = bytearray(32)
        for cluster, successor in (links or {2: 4, 4: 3, 3: 0xfff}).items():
            encode(table, cluster, successor)
        machine = Uc(UC_ARCH_X86, UC_MODE_16)
        machine.mem_map(0, 0x110000)
        machine.mem_write(CODE * 16, self.code)
        machine.mem_write(CODE * 16 + CALLBACK, b"\xcb")
        for offset, record in ((FL, file_request), (RD, disk), (FT, fat), (RT, directory)):
            machine.mem_write(DATA * 16 + offset, struct.pack("<" + "H" * len(record), *record))
        root_bytes = bytes(32) if missing else entry(size=file_size)
        machine.mem_write(ROOT * 16 + 0x100, root_bytes)
        machine.mem_write(FAT * 16 + 0x200, bytes(table))
        machine.mem_write(FILE * 16 + 0x3ff, b"\xa5" * 8194)
        machine.mem_write(STACK * 16 + 0x3000, struct.pack("<H", STOP))
        registers = {
            UC_X86_REG_BX: 0x1234, UC_X86_REG_CX: 0x2345, UC_X86_REG_DX: 0x3456,
            UC_X86_REG_SI: FL, UC_X86_REG_DI: 0x4567, UC_X86_REG_BP: 0x5678,
            UC_X86_REG_DS: DATA, UC_X86_REG_ES: 0x8800, UC_X86_REG_SS: STACK,
        }
        for register, value in registers.items():
            machine.reg_write(register, value)
        machine.reg_write(UC_X86_REG_CS, CODE)
        machine.reg_write(UC_X86_REG_SP, 0x3000)
        machine.reg_write(UC_X86_REG_EFLAGS, 0x602)
        calls, outcomes, corrupted = [], iter(results or []), [False]

        def hook(cpu, address, size, _):
            if address == CODE * 16 + CALLBACK:
                request = struct.unpack("<25H", cpu.mem_read(DATA * 16 + RD, 50))
                self.assertEqual(request[10], 0x321, "boot drive is propagated")
                if version == 2:
                    # The callback transfers RD_RUN sectors and returns their number.
                    run = request[24]
                    calls.append((request[21], run))
                    status, count = next(outcomes, (0, run))
                    if status == 0:
                        cpu.mem_write(request[20] * 16 + request[19], b"".join(
                            bytes([request[21] + n]) * 512 for n in range(min(count, run))))
                else:
                    calls.append(request[21])
                    status, count = next(outcomes, (0, 512))
                    if status == 0:
                        cpu.mem_write(request[20] * 16 + request[19],
                                      bytes([request[21]]) * min(count, 512))
                cpu.reg_write(UC_X86_REG_AX, status)
                cpu.reg_write(UC_X86_REG_CX, count)
            elif corrupt_copy and not corrupted[0] and bytes(cpu.mem_read(address, 2)) == b"\xf3\xa6":
                # Corrupt the first byte of the region being compared.
                target = cpu.reg_read(UC_X86_REG_ES) * 16 + cpu.reg_read(UC_X86_REG_DI)
                cpu.mem_write(target, b"\xff")
                corrupted[0] = True

        machine.hook_add(UC_HOOK_CODE, hook)
        machine.emu_start(CODE * 16, CODE * 16 + STOP, count=200000)
        self.assertEqual(machine.reg_read(UC_X86_REG_SP), 0x3002, "bounded return")
        for register, value in registers.items():
            self.assertEqual(machine.reg_read(register), value)
        status = machine.reg_read(UC_X86_REG_AX)
        self.assertEqual(machine.reg_read(UC_X86_REG_EFLAGS), 0x602 | int(status != 0))
        self.assertEqual(bytes(machine.mem_read(ROOT * 16 + 0x100, 32)), root_bytes)
        self.assertEqual(bytes(machine.mem_read(FAT * 16 + 0x200, 32)), bytes(table))
        final = struct.unpack("<25H", machine.mem_read(DATA * 16 + FL, 50))
        self.assertEqual(final[:12], tuple(file_request[:12]))
        self.assertEqual(bytes(machine.mem_read(FILE * 16 + 0x3ff, 1)), b"\xa5")
        if file_size <= 8192:
            self.assertEqual(bytes(machine.mem_read(FILE * 16 + 0x400 + file_size,
                                                    8193 - file_size)), b"\xa5" * (8193 - file_size))
        return status, calls, final, bytes(machine.mem_read(FILE * 16 + 0x400, min(file_size, 8192)))

    def test_fragmented_file_and_final_partial_sector(self):
        status, calls, final, payload = self.execute()
        self.assertEqual((status, calls, final[12:15]), (0, [5, 7, 6], (6, 1100, 1100)))
        self.assertEqual(payload, bytes([5]) * 512 + bytes([7]) * 512 + bytes([6]) * 76)

    def test_multiple_sectors_per_cluster(self):
        status, calls, final, payload = self.execute(file_size=2200, spc=2)
        self.assertEqual((status, calls, final[13]), (0, [5, 6, 9, 10, 7], 2200))
        self.assertEqual(payload, b"".join(bytes([n]) * 512 for n in (5, 6, 9, 10)) + bytes([7]) * 152)

    def test_single_partial_sector(self):
        status, calls, final, payload = self.execute(file_size=1, links={2: 0xfff})
        self.assertEqual((status, calls, final[13], payload), (0, [5], 1, bytes([5])))

    def test_exact_sector(self):
        status, calls, final, payload = self.execute(file_size=512, links={2: 0xfff})
        self.assertEqual((status, calls, final[13]), (0, [5], 512))
        self.assertEqual(payload, bytes([5]) * 512)

    def test_missing_file_has_no_data_reads(self):
        status, calls, _, _ = self.execute(missing=True)
        self.assertEqual((status, calls), (21, []))

    def test_chain_validation_precedes_reads(self):
        for links, expected in (({2: 0xfff}, 15), ({2: 4, 4: 2}, 14),
                                ({2: 4, 4: 3, 3: 5}, 16), ({2: 0xff7}, 13)):
            with self.subTest(links=links):
                status, calls, final, _ = self.execute(links=links)
                self.assertEqual((status, calls, final[12]), (expected, [], 4))

    def test_failed_and_short_read(self):
        status, calls, final, _ = self.execute(results=[(7, 0)])
        self.assertEqual((status, calls, final[13]), (5, [5], 0))
        status, calls, final, _ = self.execute(results=[(0, 511)])
        self.assertEqual((status, calls, final[13]), (4, [5], 0))

    def test_later_disk_error_does_not_claim_loaded(self):
        status, calls, final, _ = self.execute(results=[(0, 512), (7, 0)])
        self.assertEqual((status, calls, final[12:14]), (5, [5, 7], (5, 512)))

    def test_invalid_layout_and_capacity(self):
        for updates, expected in (({0: 2}, 30), ({8: 0}, 30), ({8: 3}, 30),
                                  ({7: 0}, 31), ({7: 6}, 31), ({11: 511}, 31),
                                  ({6: 100}, 25), ({4: 0xff00}, 31), ({5: 0xffff}, 31)):
            with self.subTest(updates=updates):
                status, calls, _, _ = self.execute(updates=updates)
                self.assertEqual((status, calls), (expected, []))

    def test_volume_may_use_fewer_whole_cylinders_than_the_disk(self):
        status, calls, _, data = self.execute(disk_total=5 + 10 + 8)
        self.assertEqual((status, calls), (0, [5, 7, 6]))
        self.assertEqual(data[:512], b"\x05" * 512)
        status, calls, _, _ = self.execute(disk_total=5 + 9)
        self.assertEqual((status, calls), (31, []))

    def test_copy_bytecheck_detects_corruption(self):
        # Whole sectors load directly; the final partial sector is copied
        # from the scratch buffer and compared.
        status, calls, final, _ = self.execute(corrupt_copy=True)
        self.assertEqual((status, calls, final[13]), (32, [5, 7, 6], 1024))
        status, calls, final, _ = self.execute(file_size=100, links={2: 0xfff},
                                               corrupt_copy=True)
        self.assertEqual((status, calls, final[13]), (32, [5], 0))

    def test_version2_consecutive_clusters_load_in_one_request(self):
        # Clusters 2-3-4 are consecutive: two whole sectors in one run, then
        # the final partial sector through the scratch buffer.
        status, calls, final, payload = self.execute(
            links={2: 3, 3: 4, 4: 0xfff}, file_size=1100, version=2)
        self.assertEqual((status, calls, final[13]), (0, [(5, 2), (7, 1)], 1100))
        self.assertEqual(payload, bytes([5]) * 512 + bytes([6]) * 512 + bytes([7]) * 76)

    def test_version2_fragmented_file(self):
        status, calls, final, payload = self.execute(version=2)
        self.assertEqual((status, calls, final[13]), (0, [(5, 1), (7, 1), (6, 1)], 1100))
        self.assertEqual(payload, bytes([5]) * 512 + bytes([7]) * 512 + bytes([6]) * 76)


if __name__ == "__main__":
    unittest.main()
