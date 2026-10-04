# SPDX-License-Identifier: GPL-2.0-or-later
"""Read real synthetic sector records through the shared loader machine code."""
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
    UC_X86_REG_EFLAGS, UC_X86_REG_IP,
)
from test_m08_volume import boot_sector
from test_m08_fat import encode
from test_m08_root import entry
from test_m08_mz import carrier

BOOT = pathlib.Path(__file__).resolve().parents[1] / "boot"
CODE, DATA, STACK = 0x1200, 0x2800, 0x3800
ROOT, FAT, SCRATCH, FILE, VISITED, MIRROR = 0x4800, 0x5000, 0x5800, 0x6800, 0x7800, 0x8000
FL, RD, FT, RT, VP, VM = 0x1000, 0x1100, 0x1200, 0x1300, 0x1400, 0x1500
CALLBACK, STOP = 0x4000, 0x4800
BL, MZ, TABLE, LOAD = 0x1700, 0x1800, 0x1a00, 0x9000


class MetadataTests(unittest.TestCase):
    pipeline = False
    handoff = False

    @classmethod
    def setUpClass(cls):
        if unicorn.__version__ != "2.1.4":
            raise RuntimeError("M08 execution QA requires pinned Unicorn 2.1.4")
        cls.temporary = tempfile.TemporaryDirectory(prefix="pc88va-m08-metadata-")
        root = pathlib.Path(cls.temporary.name)
        source = root / "metadata.asm"
        start = 'jmp pc88va_volume_read_core\n'
        if cls.pipeline:
            start = ('pushf\npush si\ncall pc88va_volume_read_core\nor ax,ax\njnz error\n'
                     'mov si,' + str(FL) + '\ncall pc88va_file_load_core\nor ax,ax\njnz error\n'
                     'pop si\npopf\nclc\nret\nerror: pop si\npopf\nstc\nret\n')
        if cls.handoff:
            start = 'jmp pc88va_boot_load_core\n'
        includes = ["disk_read", "volume_validate", "volume_read",
                    "fat12", "root_directory", "file_load"]
        if cls.handoff:
            includes += ["loader_handoff", "boot_load"]
        # This metadata/handoff fixture has no optional CONFIG.SYS stage.
        # Bind that new stage explicitly to its absent-selector outcome;
        # selector parsing and ownership are not qualified by this fixture.
        config_stage = ('\npc88va_stage2_config_bootstrap:\n'
                        'xor ax, ax\nret\n') if cls.handoff else ''
        source.write_text('bits 16\ncpu 8086\norg 0\n' + start +
                          ''.join('%include "' + name + '.inc"\n' for name in
                                  includes) + config_stage)
        outputs = []
        for number in (1, 2):
            target = root / (str(number) + ".bin")
            subprocess.run(["nasm", "-f", "bin", "-DPC88VA", "-I", str(BOOT) + "/",
                            "-o", str(target), str(source)], check=True, capture_output=True)
            outputs.append(target.read_bytes())
        if outputs[0] != outputs[1] or len(outputs[0]) >= CALLBACK:
            raise AssertionError("Invalid or nondeterministic metadata fixture")
        cls.code = outputs[0]

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def execute(self, updates=None, bpb=None, mismatch=False, reserved=False, results=None,
                missing=False, bad_chain=False, root_capacity=1024,
                kernel=None, boot_updates=None, mz_updates=None):
        kernel = carrier() if kernel is None else kernel
        table = bytearray(512)
        table[:3] = b"\xf0\xff\xff" if not reserved else b"\xf0\xfe\xff"
        clusters = [2, 4, 3]
        if self.handoff:
            count = (len(kernel) + 511) // 512
            clusters = (clusters + list(range(5, count + 2)))[:count]
        for cluster, next_cluster in zip(clusters, clusters[1:] + [0xfff]):
            encode(table, cluster, next_cluster)
        if bad_chain:
            encode(table, 4, 2)
        mirror = bytes(table)
        if mismatch:
            mirror = mirror[:-1] + b"\x01"
        directory = (bytes(32) if missing else entry(size=len(kernel) if self.handoff else 1100)) + bytes(992)
        sectors = {0: boot_sector(bpb), 1: bytes(table), 2: mirror,
                   3: directory[:512], 4: directory[512:]}
        for lba in (5, 6, 7):
            sectors[lba] = bytes([lba]) * 512
        if self.handoff:
            for index, lba in enumerate(cluster + 3 for cluster in clusters):
                sectors[lba] = kernel[index * 512:(index + 1) * 512].ljust(512, b"\0")
        disk = [1, 0, 1, 0x300, SCRATCH, 512, 72, 6, 2, 512,
                0x321, CALLBACK, CODE, 0] + [0] * 10
        fat = [1, 0x200, FAT, 512, 0, 0, 0, 0x500, VISITED, 512, 0, 0, 0]
        directory_request = [1, 0x100, ROOT, 0, root_capacity, 0, 0, 0, 0, 0]
        file_request = [1, RD, FT, RT, 0x400, FILE, 8192, 0, 0,
                        0x300, SCRATCH, 512] + [0] * 9
        volume = [1, 0x300, SCRATCH, 512, RD, 0, 0, 0] + [0] * 14
        metadata = [1, RD, VP, FT, RT, FL, 0x100, MIRROR, 512, 0]
        for index, value in (updates or {}).items():
            metadata[index] = value
        machine = Uc(UC_ARCH_X86, UC_MODE_16)
        machine.mem_map(0, 0x110000)
        machine.mem_write(CODE * 16, self.code)
        machine.mem_write(CODE * 16 + CALLBACK, b"\xcb")
        for offset, words in ((RD, disk), (FT, fat), (RT, directory_request),
                              (FL, file_request), (VP, volume), (VM, metadata)):
            machine.mem_write(DATA * 16 + offset, struct.pack("<" + "H" * len(words), *words))
        if self.handoff:
            boot = [1, VM, MZ, 0, 0]
            mz = [1, 0x400, FILE, 0, LOAD, 0x4000, 256, 0xdead, TABLE, 2] + [0] * 17
            for index, value in (boot_updates or {}).items():
                boot[index] = value
            for index, value in (mz_updates or {}).items():
                mz[index] = value
            machine.mem_write(DATA * 16 + BL, struct.pack("<5H", *boot))
            machine.mem_write(DATA * 16 + MZ, struct.pack("<27H", *mz))
            machine.mem_write(DATA * 16 + TABLE,
                              struct.pack("<4I", 0, LOAD * 16, LOAD * 16 + 0x4000, 0x100000))
            machine.mem_write(LOAD * 16, bytes([0xa5]) * 0x4000)
        machine.mem_write(FILE * 16 + 0x400, bytes([0xa5]) * 8192)
        machine.mem_write(STACK * 16 + 0x3000, struct.pack("<H", STOP))
        registers = {
            UC_X86_REG_BX: 0x1234, UC_X86_REG_CX: 0x2345, UC_X86_REG_DX: 0x3456,
            UC_X86_REG_SI: BL if self.handoff else VM, UC_X86_REG_DI: 0x4567, UC_X86_REG_BP: 0x5678,
            UC_X86_REG_DS: DATA, UC_X86_REG_ES: 0x8800, UC_X86_REG_SS: STACK,
        }
        for register, value in registers.items():
            machine.reg_write(register, value)
        machine.reg_write(UC_X86_REG_CS, CODE)
        machine.reg_write(UC_X86_REG_SP, 0x3000)
        machine.reg_write(UC_X86_REG_EFLAGS, 0x602)
        calls, outcomes, reached = [], iter(results or []), []
        header = struct.unpack_from("<14H", kernel)
        entry_address = (LOAD + header[11]) * 16 + header[10]

        def hook(cpu, address, size, _):
            if self.handoff and address == entry_address:
                reached.append(True)
                cpu.emu_stop()
                return
            if address != CODE * 16 + CALLBACK:
                return
            request = struct.unpack("<24H", cpu.mem_read(DATA * 16 + RD, 48))
            lba = request[21]
            self.assertIn(lba, sectors, "no speculative sector reads")
            calls.append(lba)
            self.assertEqual(request[10], 0x321)
            status, count = next(outcomes, (0, 512))
            if status == 0:
                data = sectors[lba][:min(count, 512)]
                if data:
                    cpu.mem_write(request[20] * 16 + request[19], data)
            cpu.reg_write(UC_X86_REG_AX, status)
            cpu.reg_write(UC_X86_REG_CX, count)

        machine.hook_add(UC_HOOK_CODE, hook)
        machine.emu_start(CODE * 16, CODE * 16 + STOP, count=200000)
        status = machine.reg_read(UC_X86_REG_AX)
        if self.handoff and status == 0:
            self.assertEqual(reached, [True])
            expected_registers = {
                UC_X86_REG_AX: 0, UC_X86_REG_BX: 0, UC_X86_REG_CX: 0,
                UC_X86_REG_DX: 0x321, UC_X86_REG_SI: 0, UC_X86_REG_DI: 0,
                UC_X86_REG_BP: 0, UC_X86_REG_DS: LOAD, UC_X86_REG_ES: LOAD,
                UC_X86_REG_SS: LOAD + header[7], UC_X86_REG_SP: header[8],
                UC_X86_REG_CS: LOAD + header[11], UC_X86_REG_IP: header[10],
                UC_X86_REG_EFLAGS: 2,
            }
            for register, value in expected_registers.items():
                self.assertEqual(machine.reg_read(register), value)
        else:
            self.assertEqual(reached, [])
            self.assertEqual(machine.reg_read(UC_X86_REG_SP), 0x3002)
            for register, value in registers.items():
                self.assertEqual(machine.reg_read(register), value)
            self.assertEqual(machine.reg_read(UC_X86_REG_EFLAGS), 0x602 | int(status != 0))
        final = struct.unpack("<10H", machine.mem_read(DATA * 16 + VM, 20))
        self.assertEqual(final[:9], tuple(metadata[:9]))
        if status == 0:
            self.assertEqual(bytes(machine.mem_read(FAT * 16 + 0x200, 512)), bytes(table))
            self.assertEqual(bytes(machine.mem_read(MIRROR * 16 + 0x100, 512)), mirror)
            self.assertEqual(bytes(machine.mem_read(ROOT * 16 + 0x100, 1024)), directory)
        loaded = struct.unpack("<21H", machine.mem_read(DATA * 16 + FL, 42))[12] == 6
        if not self.pipeline or not loaded:
            self.assertEqual(bytes(machine.mem_read(FILE * 16 + 0x400, 8192)), bytes([0xa5]) * 8192)
        else:
            expected = kernel if self.handoff else bytes([5]) * 512 + bytes([7]) * 512 + bytes([6]) * 76
            self.assertEqual(bytes(machine.mem_read(FILE * 16 + 0x400, len(expected))), expected)
            remaining = 8192 - len(expected)
            self.assertEqual(bytes(machine.mem_read(FILE * 16 + 0x400 + len(expected), remaining)), bytes([0xa5]) * remaining)
        if self.handoff:
            boot_result = struct.unpack("<5H", machine.mem_read(DATA * 16 + BL, 10))
            self.assertEqual(boot_result[:3], tuple(boot[:3]))
            self.assertEqual(boot_result[4], status)
            transformed = struct.unpack("<27H", machine.mem_read(DATA * 16 + MZ, 54))
            if status == 0:
                self.assertEqual(boot_result[3], 6)
                self.assertEqual(transformed[3], len(kernel), "file size comes from the disk entry")
                self.assertEqual(transformed[7], 0x321, "drive context comes from the actual RD record")
                self.assertEqual(transformed[17:19], (1, 1))
                body = kernel[header[4] * 16:]
                allocation = ((len(body) + 15) // 16 + header[5]) * 16
                expected = bytearray(body + bytes(allocation - len(body)))
                struct.pack_into("<HH", expected, header[7] * 16 + header[8] - 4,
                                 header[10], LOAD + header[11])
                expected += bytes([0xa5]) * (0x4000 - allocation)
                self.assertEqual(bytes(machine.mem_read(LOAD * 16, 0x4000)), bytes(expected))
            else:
                self.assertEqual(transformed[18], 0)
                self.assertEqual(bytes(machine.mem_read(LOAD * 16, 0x4000)), bytes([0xa5]) * 0x4000)
        return status, final[9], calls

    def test_boot_fat_mirror_root_read_order(self):
        self.assertEqual(self.execute(), (0, 3, [0, 1, 2, 3, 4]))

    def test_malformed_bpb_stops_after_boot_read(self):
        self.assertEqual(self.execute(bpb={(16, 1): 1}), (51, 0, [0]))

    def test_mirror_disagreement_has_no_fallback(self):
        self.assertEqual(self.execute(mismatch=True), (55, 1, [0, 1, 2]))

    def test_reserved_fat_entries_are_validated(self):
        self.assertEqual(self.execute(reserved=True), (56, 1, [0, 1, 2]))

    def test_each_metadata_read_error_is_terminal(self):
        for index in range(5):
            stage = 0 if index == 0 else 1 if index < 3 else 2
            self.assertEqual(self.execute(results=[(0, 512)] * index + [(9, 0)]),
                             (5, stage, list(range(index + 1))))

    def test_short_read_never_marks_metadata_complete(self):
        for index in range(5):
            stage = 0 if index == 0 else 1 if index < 3 else 2
            self.assertEqual(self.execute(results=[(0, 512)] * index + [(0, 511)]),
                             (4, stage, list(range(index + 1))))

    def test_invalid_context_is_rejected_before_io(self):
        for update in ({0: 2}, {1: 0xfff0}, {2: 0xfff0}, {3: 0xfff0},
                       {4: 0xfff0}, {5: 0xfff0}, {1: FT}, {3: RT}):
            with self.subTest(update=update):
                self.assertEqual(self.execute(updates=update), (57, 0, []))

    def test_insufficient_caches_stop_after_boot_read(self):
        self.assertEqual(self.execute(updates={8: 511}), (53, 0, [0]))
        self.assertEqual(self.execute(root_capacity=1023), (53, 0, [0]))


class MetadataFilePipelineTests(MetadataTests):
    pipeline = True

    def test_boot_fat_mirror_root_read_order(self):
        self.assertEqual(self.execute(), (0, 3, [0, 1, 2, 3, 4, 5, 7, 6]))

    def test_missing_root_entry_prevents_file_reads(self):
        self.assertEqual(self.execute(missing=True), (21, 3, [0, 1, 2, 3, 4]))

    def test_bad_chain_prevents_file_reads(self):
        self.assertEqual(self.execute(bad_chain=True), (14, 3, [0, 1, 2, 3, 4]))


class BootHandoffPipelineTests(MetadataFilePipelineTests):
    handoff = True

    def test_invalid_context_is_rejected_before_io(self):
        # The boot wrapper owns its VM/FL binding checks; deeper workspace
        # validation remains the metadata core's distinct error contract.
        for update in ({0: 2}, {5: 0xfff0}):
            self.assertEqual(self.execute(updates=update), (58, 0, []))
        for update in ({1: 0xfff0}, {2: 0xfff0}, {3: 0xfff0},
                       {4: 0xfff0}, {1: FT}, {3: RT}):
            self.assertEqual(self.execute(updates=update), (57, 0, []))

    def test_nonzero_relocations_never_transfer(self):
        self.assertEqual(self.execute(kernel=carrier(updates={3: 1})),
                         (43, 3, [0, 1, 2, 3, 4, 5, 7, 6]))

    def test_invalid_kernel_entry_never_transfers(self):
        self.assertEqual(self.execute(kernel=carrier(updates={10: 1027})),
                         (45, 3, [0, 1, 2, 3, 4, 5, 7, 6]))

    def test_broken_file_binding_is_rejected_before_io(self):
        for update in ({1: 0x401}, {2: FILE + 1}, {0: 2}):
            self.assertEqual(self.execute(mz_updates=update), (58, 0, []))
        for update in ({0: 2}, {1: 0xfff0}, {2: 0xfff0}):
            self.assertEqual(self.execute(boot_updates=update), (58, 0, []))


if __name__ == "__main__":
    unittest.main()
