# SPDX-License-Identifier: GPL-2.0-or-later
"""Synthetic profile validation and complete assembled stage-2 execution QA."""
import copy
import pathlib
import struct
import subprocess
import sys
import tempfile
import unittest

import unicorn
from unicorn import Uc, UC_ARCH_X86, UC_MODE_16, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.x86_const import (
    UC_X86_REG_AX, UC_X86_REG_BX, UC_X86_REG_CX, UC_X86_REG_DX,
    UC_X86_REG_SI, UC_X86_REG_DI, UC_X86_REG_BP, UC_X86_REG_SP,
    UC_X86_REG_CS, UC_X86_REG_DS, UC_X86_REG_ES, UC_X86_REG_SS,
    UC_X86_REG_EFLAGS, UC_X86_REG_IP,
)
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
from loader_profile import ProfileError, definitions, nasm_definitions, stage2_symbols
from test_m08_volume import boot_sector
from test_m08_mz import carrier
from test_m08_fat import encode
from test_m08_root import entry

BOOT = pathlib.Path(__file__).resolve().parents[1] / "boot"


def synthetic_profile():
    return {
        "schema_version": 1, "profile_class": "synthetic_rom_free",
        "regions": {"stage2": [0x12000, 0x16000], "loader_stack": [0x18000, 0x19000],
                    "scratch": [0x28000, 0x2c000], "kernel_file": [0x48000, 0x4c000],
                    "kernel_allocation": [0x68000, 0x6c000]},
        "firmware_regions": [[0, 0x10000], [0xf0000, 0x100000]],
        "stack": {"segment": 0x1800, "pointer": 0xff0, "reserve": 0xc00},
        "disk": {"sector_bytes": 512, "sectors_track": 6, "heads": 2, "total_sectors": 72},
        "cache": {"fat_bytes": 512, "root_bytes": 1024, "bitmap_bytes": 512},
    }


def low_staging_profile():
    profile = synthetic_profile()
    profile["regions"].update({
        "scratch": [0x37000, 0x3b000],
        "kernel_file": [0x27000, 0x36ff0],
        "kernel_allocation": [0x27000, 0x36ff0],
    })
    return profile


class ProfileTests(unittest.TestCase):
    def test_synthetic_layout_and_deterministic_definitions(self):
        profile = synthetic_profile()
        result = definitions(profile)
        self.assertEqual((result["S2_FAT_OFFSET"], result["S2_MIRROR_OFFSET"],
                          result["S2_ROOT_OFFSET"], result["S2_BITMAP_OFFSET"]), (512, 1024, 1536, 2560))
        self.assertEqual(result["S2_CONFIG_OFFSET"], 3072)
        self.assertEqual(result["S2_CONFIG_CAPACITY"], 4096)
        self.assertEqual(result["S2_CONFIG_SEGMENT"], 0x2800)
        self.assertEqual(result["PC88VA_LOW_STAGING_SEGMENT"], 0x4800)
        self.assertEqual(result["PC88VA_INITIAL_LOAD_SEGMENT"], 0x4800)
        self.assertEqual(result["S2_KERNEL_IN_PLACE"], 0)
        self.assertEqual(nasm_definitions(profile), nasm_definitions(copy.deepcopy(profile)))

    def test_low_staging_alias_is_explicit_and_fits_256k(self):
        profile = low_staging_profile()
        result = definitions(profile)
        self.assertEqual(result["PC88VA_LOW_STAGING_SEGMENT"], 0x2700)
        self.assertEqual(result["PC88VA_INITIAL_LOAD_SEGMENT"], 0x2700)
        self.assertEqual(result["S2_KERNEL_IN_PLACE"], 1)
        self.assertLessEqual(profile["regions"]["kernel_file"][1], 0x40000)
        self.assertEqual(profile["regions"]["kernel_file"], profile["regions"]["kernel_allocation"])

    def test_partial_kernel_alias_is_rejected(self):
        profile = low_staging_profile()
        profile["regions"]["kernel_allocation"] = [0x25ff0, 0x35ff0]
        with self.assertRaises(ProfileError):
            definitions(profile)

    def test_closed_schema_and_privacy_class(self):
        for change in ({"extra": 1}, {"schema_version": True}, {"profile_class": "unspecified"}):
            profile = synthetic_profile()
            profile.update(change)
            with self.assertRaises(ProfileError):
                definitions(profile)

    def test_region_alias_overflow_and_alignment_rejected(self):
        for bad in ([0x12000, 0x13000], [0x100000, 0x100010], [0x68001, 0x6c000],
                    [0x68000, 0x68000], [0x68000, 0x80000], [0xf0000, 0xf4000]):
            profile = synthetic_profile()
            profile["regions"]["kernel_allocation"] = bad
            with self.assertRaises(ProfileError):
                definitions(profile)

    def test_stack_bounds_and_reserve(self):
        for change in ({"reserve": 100}, {"pointer": 100}, {"segment": 0x2800}, {"pointer": 65535}):
            profile = synthetic_profile()
            profile["stack"].update(change)
            with self.assertRaises(ProfileError):
                definitions(profile)

    def test_geometry_and_cache_bounds(self):
        for key, bad in (("sector_bytes", 513), ("total_sectors", 0), ("heads", 257), ("sectors_track", 256)):
            profile = synthetic_profile()
            profile["disk"][key] = bad
            with self.assertRaises(ProfileError):
                definitions(profile)
        for key, bad in (("fat_bytes", 511), ("root_bytes", 16384), ("bitmap_bytes", 65535)):
            profile = synthetic_profile()
            profile["cache"][key] = bad
            with self.assertRaises(ProfileError):
                definitions(profile)

    def test_missing_firmware_ownership_rejected(self):
        profile = synthetic_profile()
        profile["firmware_regions"] = []
        with self.assertRaises(ProfileError):
            definitions(profile)


class Stage2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if unicorn.__version__ != "2.1.4":
            raise RuntimeError("M08 execution QA requires pinned Unicorn 2.1.4")
        cls.profile = synthetic_profile()
        cls.temporary = tempfile.TemporaryDirectory(prefix="pc88va-m08-stage2-")
        root = pathlib.Path(cls.temporary.name)
        def assemble(profile_value, stem):
            profile = root / (stem + "-profile.inc")
            # Only the ROM-free host fixture supplies disk results at this callback.
            profile.write_text(nasm_definitions(profile_value) +
                               "%macro PC88VA_FIRMWARE_READ_ONE 0\nretf\n%endmacro\n")
            blobs = []
            for number in (1, 2):
                target = root / (stem + str(number) + ".bin")
                subprocess.run(["nasm", "-f", "bin", "-DPC88VA", "-I", str(BOOT) + "/",
                                "-p", str(profile), "-o", str(target), str(BOOT / "stage2.asm")],
                               check=True, capture_output=True)
                blobs.append(target.read_bytes())
            if blobs[0] != blobs[1]:
                raise AssertionError("Two stage-2 builds differ")
            return blobs[0]

        cls.code = assemble(cls.profile, "stage2-")
        cls.symbols = stage2_symbols(cls.code)
        cls.low_profile = low_staging_profile()
        cls.low_code = assemble(cls.low_profile, "stage2-low-")
        cls.low_symbols = stage2_symbols(cls.low_code)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def execute(self, kernel=None, results=None, wrong_base=False, clobber=False,
                profile=None, code=None, symbols=None):
        profile = self.profile if profile is None else profile
        image = carrier() if kernel is None else kernel
        if profile is self.low_profile:
            # The low carrier's bootstrap far frame must live in its rounded
            # zero-filled tail, not over the compacted body at 0400h.
            image = bytearray(image)
            struct.pack_into("<H", image, 16, ((len(image) - 32 + 15) // 16) * 16)
            image = bytes(image)
        count = (len(image) + 511) // 512
        clusters = ([2, 4, 3] + list(range(5, count + 2)))[:count]
        table = bytearray(512)
        table[:3] = b"\xf0\xff\xff"
        for cluster, successor in zip(clusters, clusters[1:] + [0xfff]):
            encode(table, cluster, successor)
        directory = entry(size=len(image)) + bytes(992)
        sectors = {0: boot_sector(), 1: bytes(table), 2: bytes(table),
                   3: directory[:512], 4: directory[512:]}
        for index, cluster in enumerate(clusters):
            sectors[cluster + 3] = image[index * 512:(index + 1) * 512].ljust(512, b"\0")
        code = self.code if code is None else code
        symbols = self.symbols if symbols is None else symbols
        regions = profile["regions"]
        base = regions["stage2"][0] + (0x1000 if wrong_base else 0)
        destination = regions["kernel_allocation"][0]
        header = struct.unpack_from("<14H", image)
        entry_address = destination + header[11] * 16 + header[10]
        machine = Uc(UC_ARCH_X86, UC_MODE_16)
        machine.mem_map(0, 0x110000)
        machine.mem_write(base, code)
        machine.mem_write(destination, bytes([0xa5]) * (regions["kernel_allocation"][1] - destination))
        machine.reg_write(UC_X86_REG_CS, base // 16)
        machine.reg_write(UC_X86_REG_DS, 0xdead)
        machine.reg_write(UC_X86_REG_SS, 0)
        machine.reg_write(UC_X86_REG_SP, 0)
        machine.reg_write(UC_X86_REG_DX, 0x321)
        machine.reg_write(UC_X86_REG_BX, 0x602)
        machine.reg_write(UC_X86_REG_EFLAGS, 0x602)
        reads, writes, reached = [], [], []
        outcomes = iter(results or [])

        def owned(address, size):
            self.assertTrue(any(start <= address and address + size <= end for start, end in regions.values()),
                            "write must stay inside a predeclared owned interval")

        def memory_hook(cpu, access, address, size, value, _):
            owned(address, size)
            writes.append((address, size, value))

        def hook(cpu, address, size, _):
            if address in (entry_address, base + symbols["failure"]):
                reached.append("entry" if address == entry_address else "failure")
                cpu.emu_stop()
                return
            if address != base + symbols["adapter"]:
                return
            self.assertEqual(cpu.reg_read(UC_X86_REG_DS), base // 16)
            request = struct.unpack("<24H", cpu.mem_read(base + symbols["disk"], 48))
            self.assertEqual(request[10], 0x321)
            lba = request[21]
            reads.append(lba)
            self.assertIn(lba, sectors)
            status, completed = next(outcomes, (0, 512))
            if status == 0 and completed:
                address = request[20] * 16 + request[19]
                data = sectors[lba][:min(completed, 512)]
                owned(address, len(data))
                cpu.mem_write(address, data)
            if clobber:
                for register in (UC_X86_REG_DS, UC_X86_REG_ES, UC_X86_REG_BX,
                                 UC_X86_REG_SI, UC_X86_REG_DI, UC_X86_REG_BP, UC_X86_REG_DX):
                    cpu.reg_write(register, 0x7654)
            cpu.reg_write(UC_X86_REG_AX, status)
            cpu.reg_write(UC_X86_REG_CX, completed)

        machine.hook_add(UC_HOOK_MEM_WRITE, memory_hook)
        machine.hook_add(UC_HOOK_CODE, hook)
        machine.emu_start(base, 0x10ffff, count=300000)
        self.assertEqual(len(reached), 1)
        if reached == ["entry"]:
            expected = {
                UC_X86_REG_AX: 0, UC_X86_REG_BX: 0, UC_X86_REG_CX: 0,
                UC_X86_REG_DX: 0x321, UC_X86_REG_SI: 0, UC_X86_REG_DI: 0,
                UC_X86_REG_BP: 0, UC_X86_REG_DS: destination // 16, UC_X86_REG_ES: destination // 16,
                UC_X86_REG_CS: destination // 16 + header[11], UC_X86_REG_IP: header[10],
                UC_X86_REG_SS: destination // 16 + header[7], UC_X86_REG_SP: header[8], UC_X86_REG_EFLAGS: 2,
            }
            for register, value in expected.items():
                self.assertEqual(machine.reg_read(register), value)
            if profile is self.low_profile:
                header_bytes = header[4] * 16
                body = image[header_bytes:]
                self.assertEqual(bytes(machine.mem_read(regions["kernel_file"][0], len(body))), body)
            else:
                self.assertEqual(bytes(machine.mem_read(regions["kernel_file"][0], len(image))), image)
            body = image[header[4] * 16:]
            allocation = ((len(body) + 15) // 16 + header[5]) * 16
            transformed = bytearray(body + bytes(allocation - len(body)))
            struct.pack_into("<HH", transformed, header[7] * 16 + header[8] - 4,
                             header[10], destination // 16 + header[11])
            self.assertEqual(bytes(machine.mem_read(destination, allocation)), bytes(transformed))
        else:
            self.assertEqual(bytes(machine.mem_read(destination, 0x4000)), bytes([0xa5]) * 0x4000)
        return reached[0], reads, writes

    def test_stage2_entry_to_kernel_entry(self):
        outcome, reads, _ = self.execute()
        self.assertEqual((outcome, reads), ("entry", [0, 1, 2, 3, 4, 5, 7, 6]))

    def test_low_staging_stage2_entry_to_kernel_entry(self):
        outcome, reads, _ = self.execute(profile=self.low_profile, code=self.low_code,
                                         symbols=self.low_symbols)
        self.assertEqual((outcome, reads), ("entry", [0, 1, 2, 3, 4, 5, 7, 6]))

    def test_no_incoming_stack_or_data_segment_dependency(self):
        self.assertEqual(self.execute(clobber=True)[0], "entry")

    def test_wrong_code_base_fails_before_any_write(self):
        self.assertEqual(self.execute(wrong_base=True), ("failure", [], []))

    def test_disk_error_or_short_read_never_transfers(self):
        for result in ((1, 0), (0, 511)):
            outcome, reads, _ = self.execute(results=[result])
            self.assertEqual((outcome, reads), ("failure", [0]))

    def test_mz_relocation_failure_never_transfers(self):
        self.assertEqual(self.execute(kernel=carrier(updates={3: 1}))[0], "failure")

    def test_identical_run_observations(self):
        self.assertEqual(self.execute(), self.execute())

    def test_footer_corruption_rejected(self):
        for data in (self.code[:-1], self.code + b"\0", self.code[:-36] + bytes(36)):
            with self.assertRaises(ProfileError):
                stage2_symbols(data)


if __name__ == "__main__":
    unittest.main()
