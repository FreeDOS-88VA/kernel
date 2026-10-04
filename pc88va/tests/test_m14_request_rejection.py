#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Execute production request dispatch/rejection with an inert sector backend."""
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
#define STATIC static
#define ASMCFUNC
#define FAR
#define hd(x) ((x) & DF_FIXED)
typedef int16_t COUNT;
typedef uint16_t WORD, UWORD;
typedef uint32_t ULONG;
typedef struct { UWORD bpb_nsize; ULONG bpb_huge; } bpb;
typedef struct { UWORD ddt_descflags; ULONG ddt_offset; bpb ddt_defbpb, ddt_bpb; } ddt;
typedef struct { unsigned char r_unit, r_command; UWORD r_start, r_count; ULONG r_huge; void *r_trans; } request, *rqptr;
static struct { unsigned char dh_name[8]; } blk_dev = {{1}};
static unsigned callbacks, lookups, injected_error, completed;
static ddt disk;
static void tmark(ddt *d) { (void)d; }
static ddt *getddt(unsigned unit) { (void)unit; ++lookups; return &disk; }
static int LBA_Transfer(ddt *d, int mode, void *buffer, ULONG start, unsigned count, UWORD *done) {
    (void)d; (void)mode; (void)buffer; (void)start;
    callbacks += count != 0;
    *done = injected_error ? completed : count;
    return injected_error;
}
'''
MAIN = r'''
/* A guard slot records the original one-past-table dispatch deterministically,
   avoiding undefined host memory access. NENTRY still comes from production. */
static WORD guard(rqptr r, ddt *d) { (void)r; (void)d; return 0x1234; }
static WORD (*dispatch[NENTRY + 1])(rqptr, ddt *);
DISPATCH_FUNCTION
int main(int argc, char **argv) {
    request r = {0}; unsigned i; WORD status;
    if (argc != 8) return 2;
    r.r_unit = strtoul(argv[1], 0, 0); r.r_command = strtoul(argv[2], 0, 0);
    r.r_start = HUGECOUNT; r.r_huge = strtoul(argv[3], 0, 0);
    r.r_count = strtoul(argv[4], 0, 0);
    disk.ddt_descflags = strtoul(argv[5], 0, 0);
    injected_error = strtoul(argv[6], 0, 0); completed = strtoul(argv[7], 0, 0);
    disk.ddt_bpb.bpb_nsize = 1280;
    for (i = 0; i <= NENTRY; ++i) dispatch[i] = guard;
    dispatch[C_INPUT] = dispatch[C_OUTPUT] = dispatch[C_OUTVFY] = blockio;
    status = blk_driver(&r);
    printf("%u %u %u %u\n", status, r.r_count, callbacks, lookups);
    return 0;
}
'''


class RequestRejectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        device = (ROOT / 'hdr/device.h').read_text()
        dsk = (ROOT / 'kernel/dsk.c').read_text()
        names = ('S_ERROR', 'S_DONE', 'E_UNIT', 'E_FAILURE', 'E_NOTFND', 'DF_NOACCESS',
                 'DF_FIXED', 'HUGECOUNT', 'C_INIT', 'C_INPUT', 'C_OUTPUT', 'C_OUTVFY')
        definitions = [re.search(r'^#define ' + n + r'\s+[^\n]+', device, re.M)[0]
                       for n in names]
        definitions += [re.search(r'^#define failure\(x\)[^\n]+', device, re.M)[0]]
        for name in ('NENTRY', 'LBA_READ', 'LBA_WRITE'):
            definitions.append(re.search(r'^#define ' + name + r'\s+[^\n]+', dsk, re.M)[0])
        definitions.append(re.search(r'^UWORD LBA_WRITE_VERIFY = .*;', dsk, re.M)[0])
        function = dsk[dsk.index('STATIC WORD blockio(rqptr rp, ddt * pddt)\n{'):]
        function = function.split('\nSTATIC WORD blk_error', 1)[0]
        dispatch = dsk[dsk.index('COUNT ASMCFUNC FAR blk_driver(rqptr rp)\n{'):]
        dispatch = dispatch.split('\nSTATIC char template_string', 1)[0]
        cls.tmp = tempfile.TemporaryDirectory(prefix='m14-request-')
        cls.addClassCleanup(cls.tmp.cleanup)
        directory = Path(cls.tmp.name)
        source = directory / 'request.c'
        source.write_text(HARNESS + '\n'.join(definitions) +
                          '\nstatic WORD dskerr(unsigned error) { return failure(error); }\n' +
                          function + MAIN.replace('DISPATCH_FUNCTION', dispatch))
        cls.programs = {}
        for va in (False, True):
            binary = directory / ('va' if va else 'other')
            result = subprocess.run(['cc', '-std=c99', '-Wall', '-Werror',
                                     *(['-DPC88VA'] if va else []), str(source), '-o', str(binary)],
                                    capture_output=True, text=True)
            if result.returncode:
                raise AssertionError(result.stderr)
            cls.programs[va] = binary

    def execute(self, va=True, unit=0, command=8, start=0, count=2, flags=0, error=0, done=0):
        p = subprocess.run([str(self.programs[va]), *map(str, (unit, command, start, count, flags, error, done))],
                           capture_output=True, check=True, timeout=5)
        return tuple(map(int, p.stdout.split()))

    def test_range_errors_have_error_done_zero_completion_and_no_device_access(self):
        for va in (False, True):
            for command in (4, 8, 9):
                for start, count in ((1280, 1), (1279, 2), (1, 65535), (0xffffffff, 2)):
                    with self.subTest(va=va, command=command, start=start, count=count):
                        self.assertEqual(self.execute(va, command=command, start=start, count=count),
                                         (0x8108, 0, 0, 1))

    def test_invalid_unit_and_inaccessible_volume_complete_no_sectors(self):
        for va in (False, True):
            for command in (4, 8, 9):
                with self.subTest(va=va, command=command):
                    self.assertEqual(self.execute(va, unit=1, command=command), (0x8101, 0, 0, 0))
                    self.assertEqual(self.execute(va, flags=0x200, command=command), (0x810c, 0, 0, 1))

    def test_first_invalid_dispatch_index_is_rejected(self):
        for va in (False, True):
            for command in (26, 27, 255):
                with self.subTest(va=va, command=command):
                    status, _, calls, lookups = self.execute(va, command=command)
                    self.assertEqual((status, calls, lookups), (0x810c, 0, 0))

    def test_valid_zero_count_success_and_partial_count_are_preserved(self):
        for va in (False, True):
            for command in (4, 8, 9):
                with self.subTest(va=va, command=command):
                    self.assertEqual(self.execute(va, command=command, count=0), (0x100, 0, 0, 1))
                    self.assertEqual(self.execute(va, command=command, start=1279, count=1), (0x100, 1, 1, 1))
                    self.assertEqual(self.execute(va, command=command, error=4, done=1), (0x8104, 1, 1, 1))


if __name__ == '__main__':
    unittest.main()
