#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Exercise BPB-less native FAT12 recognition with original synthetic sectors."""
import re
import subprocess
import tempfile
import unittest
from test_m14_media_lifetime import function
from test_m15_media_id import ROOT, HEADER, HARNESS

BACKEND = r'''
static unsigned legacy_case, selected_total, calls;
static int fl_read(unsigned drive, unsigned head, unsigned cyl, unsigned sector,
                   unsigned count, void *buffer) {
    unsigned char *p = buffer;
    assert(drive == 1 && count == 1 && selected_total == 1232);
    ++calls;
    memset(p, 0, 1024);
    if (head == 1 && cyl == 76 && sector == 8)
        return legacy_case == 3;
    assert(head == 0 && cyl == 0 && (sector == 2 || sector == 4));
    p[0] = 0xfe; p[1] = 0xff; p[2] = 0xff;
    if (legacy_case == 1 && sector == 2) p[0] = 0;
    if (legacy_case == 2 && sector == 4) p[2] = 0;
    if (legacy_case == 4) return 1;
    return 0;
}
'''
MAIN = r'''
int main(int argc, char **argv) {
    ddt disk = {0}; int result;
    assert(argc == 2); legacy_case = atoi(argv[1]);
    disk.ddt_driveno = 1;
    memset(media, 0x90, sizeof(media));
    if (legacy_case == 5) { media[11] = 0; media[12] = 4; }
    disk.ddt_serialno = 0xdeadbeef;
    result = getbpb(&disk);
    if (legacy_case == 0) {
        assert(result == 0 && !(disk.ddt_descflags & DF_NOACCESS));
        assert(disk.ddt_bpb.bpb_nbyte == 1024);
        assert(disk.ddt_bpb.bpb_nsize == 1232);
        assert(disk.ddt_bpb.bpb_nsector == 1);
        assert(disk.ddt_bpb.bpb_ndirent == 192);
        assert(disk.ddt_bpb.bpb_nfsect == 2);
        assert(disk.ddt_serialno == 0 && disk.ddt_ncyl == 77);
        assert(calls >= 3);
    } else {
        assert(result != 0 && (disk.ddt_descflags & DF_NOACCESS));
        if (legacy_case == 5) assert(calls == 0);
    }
    assert(writes == 0);
    return 0;
}
'''

class LegacyMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        root = __import__('pathlib').Path(cls.tmp.name)
        src = (ROOT / 'kernel/dsk.c').read_text()
        header = (ROOT / 'hdr/device.h').read_text()
        bpb = re.search(r'typedef struct \{\s+UWORD bpb_nbyte;[\s\S]*?\} bpb;', header)[0]
        mid = re.search(r'struct Gioc_media \{[\s\S]*?\};', header)[0]
        info = re.search(r'struct FS_info \{[\s\S]*?\};', src)[0]
        harness = HARNESS.replace('drive > 1', 'drive != 1')
        start = harness.index('static int pc88va_m16_set_profile')
        harness = harness[:start]
        setter = r'''static int pc88va_m16_set_profile(unsigned drive, unsigned mode,
            unsigned total, unsigned spt, unsigned heads) {
            assert(drive == 1 && mode == 0x23 && spt == 8 && heads == 2);
            selected_total = total; return 0;
        }'''
        code = HEADER+bpb+mid+info+harness+BACKEND+setter+function(src, 'STATIC WORD getbpb')+MAIN
        source = root / 'legacy.c'; source.write_text(code)
        cls.binary = root / 'legacy'
        subprocess.run(['cc','-std=c99','-DPC88VA','-Wall','-Wextra','-Werror',
                        '-Wno-unused-function', str(source),'-o',str(cls.binary)],check=True)

    def test_native_without_bpb(self):
        self.assertEqual(subprocess.run([str(self.binary),'0']).returncode,0)

    def test_bad_fat_mirror_geometry_io_and_malformed_bpb(self):
        for case in range(1,6):
            with self.subTest(case=case):
                self.assertEqual(subprocess.run([str(self.binary),str(case)]).returncode,0)

if __name__ == '__main__':
    unittest.main()
