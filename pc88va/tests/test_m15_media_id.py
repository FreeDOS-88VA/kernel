#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Execute production BPB/media-ID logic against synthetic FAT12 sectors.

The selected FreeDOS implementation supplies the DOS-side behavior; guest
tests cover the real PC-88VA adapter and runtime ABI.
"""
from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest
from test_m14_media_lifetime import function

ROOT = Path(__file__).resolve().parents[2]
HEADER = r'''
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#ifdef __clang__
#pragma clang diagnostic ignored "-Wtautological-overlap-compare"
#endif
#define STATIC static
#define FAR
#define BT_BPB 11
#define M_NOT_CHANGED 1
#define FALSE 0
#define TRUE 1
#define DF_DISKCHANGE 2
#define DF_NOACCESS 512
#define S_DONE 256
#define E_MEDIA 7
#define E_FAILURE 12
#define E_NOTRDY 15
#define LBA_READ 0
#define LBA_WRITE 1
#define hd(x) 0
#define fmemcpy memcpy
typedef uint8_t UBYTE;
typedef char BYTE;
typedef uint16_t UWORD;
typedef uint32_t ULONG;
typedef int WORD;
#pragma pack(push,1)
'''
HARNESS = r'''
#pragma pack(pop)
typedef struct { bpb ddt_bpb,ddt_defbpb; unsigned ddt_descflags,ddt_ncyl;
    ULONG ddt_serialno; char ddt_volume[11],ddt_fstype[8]; unsigned ddt_driveno; } ddt;
typedef struct { struct Gioc_media *r_gioc; } *rqptr;
static UBYTE DiskTransferBuffer[1024], media[1024];
static unsigned writes, read_error, write_error;
static int diskchange(ddt *d) { (void)d; return M_NOT_CHANGED; }
static void tmark(ddt *d) { (void)d; }
static unsigned getword(const void *p) { uint16_t n; memcpy(&n,p,2); return n; }
static ULONG getlong(const void *p) { ULONG n; memcpy(&n,p,4); return n; }
static int dskerr(unsigned n) { return 0x8100 | n; }
static int failure(unsigned n) { return 0x8100 | n; }
static int RWzero(ddt *d, unsigned mode) {
    (void)d;
    if (mode==LBA_READ) {
        if(read_error) return read_error;
        memcpy(DiskTransferBuffer,media,sizeof(media));
    } else {
        ++writes;
        if(write_error) return write_error;
        memcpy(media,DiskTransferBuffer,sizeof(media));
    }
    return 0;
}
static int pc88va_m16_probe_read(unsigned drive, unsigned mode, void *buffer) {
    if (drive > 1 || mode != 0x23 || read_error) return 1;
    memcpy(buffer, media, sizeof(media));
    return 0;
}
static int pc88va_m16_set_profile(unsigned drive, unsigned mode, unsigned total,
                                  unsigned spt, unsigned heads) {
    return drive == 0 && mode == 0x23 && total == 1280 && spt == 8 && heads == 2
        ? 0 : 1;
}
'''
HARNESS += r'''
static int fl_read(unsigned drive, unsigned head, unsigned cyl, unsigned sector,
                   unsigned count, void *buffer) {
    (void)drive; (void)head; (void)cyl; (void)sector; (void)count; (void)buffer;
    memset(buffer,0,1024); ((UBYTE *)buffer)[0]=0xfe;
    ((UBYTE *)buffer)[1]=0xff; ((UBYTE *)buffer)[2]=0xff;
    return read_error;
}
'''
MAIN = r'''
int main(int argc, char **argv) {
    ddt disk={0};
    struct Gioc_media id={0};
    struct { struct Gioc_media *r_gioc; } request={&id};
    UBYTE original[1024];
    unsigned signature, setting, badmarker, inject;
    int ret;
    assert(argc==5);
    signature=(unsigned)atoi(argv[1]); setting=(unsigned)atoi(argv[2]);
    badmarker=(unsigned)atoi(argv[3]); inject=(unsigned)atoi(argv[4]);
    disk.ddt_defbpb=(bpb){1024,1,1,2,192,1280,254,2,8,2,0,0};
    disk.ddt_bpb=disk.ddt_defbpb;
    disk.ddt_ncyl=80;
    disk.ddt_serialno=0xcccccccc;
    memset(disk.ddt_volume,0xcc,11); memset(disk.ddt_fstype,0xcc,8);
    memcpy(media+11,&disk.ddt_defbpb,sizeof(bpb));
    media[38]=signature;
    media[39]=0x78; media[40]=0x56; media[41]=0x34; media[42]=0x12;
    memcpy(media+43,"M15 VOLUME ",11); memcpy(media+54,"FAT12   ",8);
    if(!badmarker) { media[510]=0x55; media[511]=0xaa; }
    memcpy(original,media,sizeof(media));
    if(inject==1) read_error=0x80;
    if(inject==2) write_error=3;
    if(setting) {
        id.ioc_serialno=0x87654321;
        ret=set_media((rqptr)&request,&disk);
#ifndef PC88VA
        if(signature==0x28 || signature==0x29) {
            /* Preserve the selected common FreeDOS behavior on other targets. */
            assert(ret!=S_DONE && writes==0);
            assert(!memcmp(media,original,sizeof(media)));
            return 0;
        }
#endif
        if(inject || (signature!=0x28 && signature!=0x29)) {
            assert(ret!=S_DONE);
            assert(writes==(inject==2 ? 1u : 0u));
            assert(!memcmp(media,original,sizeof(media)));
        } else {
            assert(ret==S_DONE && writes==1);
            assert(getlong(media+39)==id.ioc_serialno);
            memcpy(original+39,media+39,4);
            assert(!memcmp(media,original,sizeof(media)));
        }
    } else {
        ret=getbpb(&disk);
        if(inject) { assert(ret!=0); return 0; }
#ifndef PC88VA
        if(badmarker) { assert(ret==S_DONE); return 0; }
#endif
        assert(ret==0 && writes==0);
        assert(!memcmp(&disk.ddt_bpb,&disk.ddt_defbpb,sizeof(bpb)));
        assert(disk.ddt_ncyl==80);
        assert(disk.ddt_serialno==((signature==0x28 || signature==0x29) ? 0x12345678u : 0));
        assert(!memcmp(disk.ddt_volume,signature==0x29 ? "M15 VOLUME " : "NO NAME    ",11));
        assert(!memcmp(disk.ddt_fstype,signature==0x29 ? "FAT12   " : "FAT??   ",8));
        assert(!memcmp(media,original,sizeof(media)));
    }
    return 0;
}
'''


class MediaIdTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        root = Path(cls.tmp.name)
        source = (ROOT / 'kernel/dsk.c').read_text()
        header = (ROOT / 'hdr/device.h').read_text()
        bpb = re.search(r'typedef struct \{\s+UWORD bpb_nbyte;[\s\S]*?\} bpb;', header)[0]
        mid = re.search(r'struct Gioc_media \{[\s\S]*?\};', header)[0]
        info = re.search(r'struct FS_info \{[\s\S]*?\};', source)[0]
        setter = function(source, 'STATIC WORD Genblkdev').split(
            'case 0x46:', 1)[1].split('case 0x47:', 1)[0]
        # Execute the unmodified production switch arm in its original context.
        setter = 'static int set_media(rqptr rp, ddt *pddt) { int ret; switch(0x46) { case 0x46:' + setter + '} return S_DONE; }\n'
        probe = root / 'probe.c'
        probe.write_text(HEADER+bpb+mid+info+HARNESS+
                         function(source, 'STATIC WORD getbpb')+setter+MAIN)
        cls.binaries = {}
        for va in (False, True):
            binary = root / ('va' if va else 'pc')
            built = subprocess.run([os.environ.get('CC', 'cc'), '-std=c99',
                                    '-Wall', '-Wextra', '-Werror', '-Wno-unused-label',
                                    '-Wno-unused-function',
                                    *(['-DPC88VA'] if va else []),
                                    str(probe), '-o', str(binary)],
                                   capture_output=True, text=True)
            if built.returncode:
                raise RuntimeError(built.stdout+built.stderr)
            cls.binaries[va] = binary

    def check(self, va, signature=0x29, setting=0, badmarker=0, inject=0):
        result = subprocess.run([str(self.binaries[va]), str(signature),
                                 str(setting), str(badmarker), str(inject)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_va_native_sector_refreshes_current_serial_and_label(self):
        self.check(True, badmarker=1)

    def test_va_older_signature_has_serial_only(self):
        self.check(True, signature=0x28, badmarker=1)

    def test_va_short_bpb_clears_stale_extended_fields(self):
        self.check(True, signature=0, badmarker=1)

    def test_pc_signature_and_fallback_contract_remain(self):
        self.check(False)
        self.check(False, badmarker=1)

    def test_va_accepts_signatures_while_other_target_keeps_free_dos_behavior(self):
        for va in (False, True):
            for signature in (0x28, 0x29):
                with self.subTest(va=va, signature=signature):
                    self.check(va, signature, setting=1, badmarker=va)

    def test_set_rejects_missing_serial_field_without_writes(self):
        for va in (False, True):
            for signature in (0, 0x27, 0x30, 0xff):
                self.check(va, signature, setting=1, badmarker=va)

    def test_read_and_write_failures_remain_errors_without_media_mutation(self):
        for va in (False, True):
            for inject in (1, 2):
                self.check(va, setting=1, badmarker=va, inject=inject)
            self.check(va, badmarker=va, inject=1)


if __name__ == '__main__':
    unittest.main()
