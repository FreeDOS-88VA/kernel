#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Host-execute production common transfer control flow with synthetic devices.

This tests C retry/completion policy, not 16-bit pointer arithmetic or firmware.
The target build and instruction-level adapter tests cover those boundaries.
"""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]

HARNESS = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define STATIC static
#define FAR
#define VOID void
typedef uint8_t UBYTE;
typedef uint16_t UWORD;
typedef uint32_t ULONG;
typedef struct { unsigned bpb_nbyte, bpb_nsecs; } bpb;
typedef struct { unsigned ddt_descflags; UBYTE ddt_driveno; bpb ddt_bpb; } ddt;
struct CHS { unsigned Head, Cylinder, Sector; };
struct _bios_LBA_address_packet {
    unsigned size, reserved, number_of_blocks;
    void *buffer_address;
    ULONG block_address, block_address_high;
};
static unsigned resets, calls, fail_at, injected_error;
static unsigned reads, writes, verifies;
static UBYTE DiskTransferBuffer[4096], parameter_table[16];
#define hd(x) ((x) & DF_FIXED)
#define FP_SEG(x) 0x1000
#define fmemcpy memcpy
static void *adjust_far(void *buffer) { return buffer; }
static unsigned DMA_max_transfer(void *buffer, unsigned count) { (void)buffer; return count; }
static void play_dj(ddt *disk) { (void)disk; }
static UBYTE *getvec(unsigned vector) { (void)vector; return parameter_table; }
static int fl_reset(unsigned drive) { (void)drive; ++resets; return 1; }
static int LBA_to_CHS(ULONG lba, struct CHS *chs, ddt *disk, const bpb **geometry) {
    chs->Sector = lba % disk->ddt_bpb.bpb_nsecs + 1;
    chs->Head = (lba / disk->ddt_bpb.bpb_nsecs) % 2;
    chs->Cylinder = lba / (disk->ddt_bpb.bpb_nsecs * 2);
    *geometry = &disk->ddt_bpb;
    return 0;
}
static int transfer(unsigned drive, unsigned head, unsigned cylinder,
                    unsigned sector, unsigned count, void *buffer) {
    (void)drive; (void)head; (void)cylinder; (void)sector; (void)count; (void)buffer;
    ++calls;
    return fail_at && calls >= fail_at ? injected_error : 0;
}
#define DEVICE_CALL(name,counter) \
static int name(unsigned d,unsigned h,unsigned c,unsigned s,unsigned n,void *b) { \
    ++counter; return transfer(d,h,c,s,n,b); }
DEVICE_CALL(fl_read,reads)
DEVICE_CALL(fl_write,writes)
DEVICE_CALL(fl_verify,verifies)
#define fl_format transfer
static int fl_lba_ReadWrite(unsigned drive, unsigned mode, struct _bios_LBA_address_packet *packet) {
    (void)drive; (void)mode; (void)packet;
    abort(); /* These tests deliberately exercise the CHS path. */
}
'''

MAIN = r'''
int main(int argc, char **argv) {
    UBYTE buffer[4096];
    ddt disk = {DF_DMA_TRANSPARENT, 0, {1024, 8}};
    UWORD completed = 0xFFFF;
    unsigned mode, count;
    int error;
    if (argc != 5 && argc != 6) return 2;
    mode = strtoul(argv[1], NULL, 0);
    count = strtoul(argv[2], NULL, 0);
    fail_at = strtoul(argv[3], NULL, 0);
    injected_error = strtoul(argv[4], NULL, 0);
    parameter_table[4] = disk.ddt_bpb.bpb_nsecs;
    error = LBA_Transfer(&disk, mode, buffer, 0, count, &completed);
    printf("%d %u %u %u", error, completed, calls, resets);
    if(argc==6) printf(" %u %u %u", reads, writes, verifies);
    puts("");
    return 0;
}
'''


class CommonTransferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dsk = (ROOT / "kernel/dsk.c").read_text()
        device = (ROOT / "hdr/device.h").read_text()
        function = dsk[dsk.rindex("STATIC int LBA_Transfer("):].split("/*\n * Revision", 1)[0]
        definitions = []
        for name in ("N_RETRY", "DF_FIXED", "DF_LBA", "DF_WRTVERIFY", "DF_DMA_TRANSPARENT"):
            definitions.append(re.search(r"^#define " + name + r"\s+[^\n]+", device, re.M)[0])
        for name in ("LBA_READ", "LBA_WRITE", "LBA_VERIFY", "LBA_FORMAT"):
            line = re.search(r"^#define " + name + r"\s+[^\n]+", dsk, re.M)[0]
            definitions.append(line.split("/*", 1)[0])
        definitions.append(re.search(r"^UWORD LBA_WRITE_VERIFY = .*;", dsk, re.M)[0])
        cls.temporary = tempfile.TemporaryDirectory(prefix="m14-common-transfer-")
        cls.addClassCleanup(cls.temporary.cleanup)
        directory = Path(cls.temporary.name)
        source = directory / "transfer.c"
        # UWORD is defined by the harness before the extracted mode variable.
        source.write_text(HARNESS.split("static unsigned resets", 1)[0] +
                          "\n".join(definitions) + "\nstatic unsigned resets" +
                          HARNESS.split("static unsigned resets", 1)[1] + function + MAIN)
        cls.programs = {}
        for va in (False, True):
            binary = directory / ("va" if va else "near")
            result = subprocess.run(["cc", "-std=c99", "-Wall", "-o", str(binary),
                                     *(["-DPC88VA"] if va else []), str(source)], capture_output=True)
            if result.returncode:
                raise AssertionError(result.stderr.decode(errors="replace"))
            cls.programs[va] = binary

    def execute(self, va, mode, count, fail_at=0, status=3):
        result = subprocess.run([str(self.programs[va]), str(mode), str(count),
                                 str(fail_at), str(status)], check=True, capture_output=True, timeout=5)
        return tuple(map(int, result.stdout.split()))

    def test_va_write_errors_do_not_reset_or_replay_the_completed_prefix(self):
        for mode in (0x4300, 0x4302):
            for status in (3, 0x10, 0x80):
                with self.subTest(mode=mode, status=status):
                    self.assertEqual(self.execute(True, mode, 2, 1, status), (status, 0, 1, 0))
        self.assertEqual(self.execute(True, 0x4300, 2, 2), (3, 1, 2, 0))
        # Write and verify the first sector, then fail the next write.
        self.assertEqual(self.execute(True, 0x4302, 2, 3), (3, 1, 3, 0))

    def test_va_read_errors_preserve_finite_retry_policy_without_global_reset(self):
        self.assertEqual(self.execute(True, 0x4200, 1, 1, 0x80), (0x80, 0, 5, 0))

    def test_success_counts_and_verification_are_preserved(self):
        for mode, calls in ((0x4200, 1), (0x4300, 2), (0x4302, 4)):
            with self.subTest(mode=mode):
                self.assertEqual(self.execute(True, mode, 2), (0, 2, calls, 0))

    def test_non_va_error_reset_and_retry_behavior_is_unchanged(self):
        for mode in (0x4200, 0x4300, 0x4302):
            with self.subTest(mode=mode):
                self.assertEqual(self.execute(False, mode, 2, 1), (3, 0, 5, 5))

    def test_verify_without_caller_data_checks_readability_not_byte_equality(self):
        # IOCTL Verify Track has no comparison-data pointer. The VA adapter's
        # fl_verify is reserved for write/readback comparison; standalone
        # verification must read sectors through its bounded scratch buffer.
        for va, expected in ((True, (0, 2, 2, 0, 2, 0, 0)),
                             (False, (0, 2, 1, 0, 0, 0, 1))):
            with self.subTest(va=va):
                result = subprocess.run([str(self.programs[va]), '17408', '2',
                                         '0', '3', 'metrics'], check=True,
                                        capture_output=True, timeout=5)
                self.assertEqual(tuple(map(int, result.stdout.split())), expected)


if __name__ == "__main__":
    unittest.main()
