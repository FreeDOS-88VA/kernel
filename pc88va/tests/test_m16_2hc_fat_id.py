#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Distinguish the native 2HC format selector from its FAT media byte."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from test_m14_media_lifetime import function
from test_m15_media_id import ROOT, HEADER, HARNESS

MAIN = r'''
int main(int argc, char **argv) {
    ddt disk = {0}; int ret; unsigned id;
    assert(argc == 3); id = atoi(argv[1]);
    disk.ddt_driveno = 1;
    disk.ddt_defbpb = (bpb){512,1,1,2,224,2400,id,7,15,2,0,0};
    memcpy(media + 11, &disk.ddt_defbpb, sizeof(bpb));
    media[38] = 0x29;
    media[510] = 0x55; media[511] = 0xaa;
    bad_fat = atoi(argv[2]) == 2;
    if (atoi(argv[2])) {
        /* Original synthetic code after the old 19-byte BPB, no MBR marker. */
        memset(media + 30, 0x90, 482);
    }
    ret = getbpb(&disk);
    if (id == 0xf9 && !bad_fat) {
        assert(ret == 0 && !(disk.ddt_descflags & DF_NOACCESS));
        assert(disk.ddt_bpb.bpb_mdesc == 0xf9 && disk.ddt_ncyl == 80);
        assert(disk.ddt_bpb.bpb_nsize == 2400 && disk.ddt_bpb.bpb_nsecs == 15);
    } else {
        assert(ret != 0 && (disk.ddt_descflags & DF_NOACCESS));
    }
    assert(writes == 0);
    return 0;
}
'''

class TwoHcFatIdTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        root = Path(cls.tmp.name)
        src = (ROOT / 'kernel/dsk.c').read_text()
        header = (ROOT / 'hdr/device.h').read_text()
        bpb = re.search(r'typedef struct \{\s+UWORD bpb_nbyte;[\s\S]*?\} bpb;', header)[0]
        mid = re.search(r'struct Gioc_media \{[\s\S]*?\};', header)[0]
        info = re.search(r'struct FS_info \{[\s\S]*?\};', src)[0]
        harness = HARNESS.replace('mode != 0x23', 'mode != 0x22').replace(
            'drive == 0 && mode == 0x23 && total == 1280 && spt == 8',
            'drive == 1 && mode == 0x22 && total == 2400 && spt == 15')
        harness = harness[:harness.index('static int fl_read')]
        harness += r'''static int bad_fat;
        static int fl_read(unsigned drive, unsigned head,
            unsigned cyl, unsigned sector, unsigned count, void *buffer) {
            UBYTE *p = buffer;
            assert(drive == 1 && count == 1);
            assert((head == 0 && cyl == 0 && (sector == 2 || sector == 9)) ||
                   (head == 1 && cyl == 79 && sector == 15));
            memset(p,0,1024); p[0]=bad_fat ? 0 : 0xf9;p[1]=0xff;p[2]=0xff;
            return 0;
        }'''
        source = root / '2hc.c'
        source.write_text(HEADER + bpb + mid + info + harness +
                          function(src, 'STATIC WORD getbpb') + MAIN)
        cls.binary = root / '2hc'
        subprocess.run(['cc','-std=c99','-DPC88VA','-Wall','-Wextra','-Werror',
                        '-Wno-unused-function',str(source),'-o',str(cls.binary)],check=True)

    def test_2hc_uses_f9_in_the_bpb(self):
        self.assertEqual(subprocess.run([str(self.binary),'249','0']).returncode,0)

    def test_native_short_bpb_does_not_parse_following_boot_code(self):
        self.assertEqual(subprocess.run([str(self.binary),'249','1']).returncode,0)

    def test_short_bpb_requires_valid_fat_reserved_entries(self):
        self.assertEqual(subprocess.run([str(self.binary),'249','2']).returncode,0)

    def test_format_selector_is_not_a_fat_media_byte(self):
        self.assertEqual(subprocess.run([str(self.binary),'241','0']).returncode,0)

if __name__ == '__main__':
    unittest.main()
