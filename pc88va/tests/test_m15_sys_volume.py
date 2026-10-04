# SPDX-License-Identifier: GPL-2.0-or-later
"""Exercise SYS's production volume preflight with original synthetic media.

Only sector reads are modeled. This is not DOS transfer or boot acceptance.
"""
import ctypes
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def medium():
    raw = bytearray(1280 * 1024)
    struct.pack_into('<HBHBHHBHHHII', raw, 11,
                     1024, 1, 1, 2, 192, 1280, 0xfe, 2, 8, 2, 0, 0)
    fat = bytearray(2048)
    fat[:3] = b'\xfe\xff\xff'
    # Two clusters in a contiguous loader chain, plus one unrelated sentinel.
    for n, value in ((2, 0xfff), (20, 21), (21, 0xfff)):
        offset = n * 3 // 2
        old = int.from_bytes(fat[offset:offset + 2], 'little')
        packed = (old & (0xf if n & 1 else 0xf000)) | (value << (4 if n & 1 else 0))
        fat[offset:offset + 2] = packed.to_bytes(2, 'little')
    raw[1024:3072] = raw[3072:5120] = fat
    for i, name, cluster, size in ((0, b'LOADER  BIN', 20, 1500),
                                   (1, b'KEEP    TXT', 2, 7)):
        off = 5120 + i * 32
        raw[off:off + 11] = name
        raw[off + 11] = 0x20
        struct.pack_into('<HI', raw, off + 26, cluster, size)
    raw[11 * 1024:11 * 1024 + 7] = b'keep me'
    return raw


class SysVolumeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='m15-sys-volume-')
        path = Path(cls.tmp.name)
        source = (ROOT / 'sys/pc88va.c').read_text()
        source = re.sub(r'^#include.*$', '', source, flags=re.M)
        prefix = r'''
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#define __cdecl
#define __interrupt
#define __far
#define O_RDONLY 0
#define O_WRONLY 1
#define _A_NORMAL 0
#define MK_FP(s,o) ((void *)(uintptr_t)(((unsigned long)(s)<<4)+(o)))
#define _fmemcmp memcmp
#define main unused_sys_main
union REGS { struct { unsigned char al,ah; } h; };
static void intdos(union REGS *a, union REGS *b) {(void)a;(void)b;}
static void _nheapshrink(void) {}
static unsigned _dos_open(const char *p,unsigned m,int *h) {(void)p;(void)m;(void)h;return 1;}
static unsigned _dos_creatnew(const char *p,unsigned m,int *h) {return _dos_open(p,m,h);}
static unsigned _dos_close(int h) {(void)h;return 0;}
static unsigned _dos_commit(int h) {(void)h;return 0;}
static unsigned _dos_read(int h,void *b,unsigned n,unsigned *g) {(void)h;(void)b;(void)n;*g=0;return 1;}
static unsigned _dos_write(int h,const void *b,unsigned n,unsigned *g) {(void)h;(void)b;(void)n;*g=0;return 1;}
static unsigned _dos_allocmem(unsigned n,unsigned *s) {(void)n;(void)s;return 8;}
static unsigned _dos_freemem(unsigned n) {(void)n;return 0;}
typedef void (*handler)(void);
static handler _dos_getvect(unsigned n) {(void)n;return 0;}
static void _dos_setvect(unsigned n,handler h) {(void)n;(void)h;}
'''
        suffix = r'''
static const unsigned char *test_medium;
unsigned va_absolute(unsigned writing,unsigned sector,void *buffer) {
  if(writing || sector>=TOTAL) return 0x8108;
  memcpy(buffer,test_medium+(unsigned long)sector*SECTOR,SECTOR); return 0;
}
void va_critical(void) {}
int check_volume(const unsigned char *data) {test_medium=data;return volume();}
int check_loader(const unsigned char *data) {
  test_medium=data;return volume() && loader_layout(1);
}
'''
        cfile = path / 'sys.c'
        cfile.write_text(prefix + source + suffix)
        p = subprocess.run(['gcc', '-shared', '-fPIC', '-Wall', '-Wextra',
                            '-Wno-missing-field-initializers', str(cfile),
                            '-o', str(path / 'sys.so')], capture_output=True, text=True)
        if p.returncode:
            raise RuntimeError(p.stderr)
        cls.lib = ctypes.CDLL(str(path / 'sys.so'))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def check(self, data, loader=False):
        buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        return (self.lib.check_loader if loader else self.lib.check_volume)(buf)

    def test_valid_flat_volume_and_reserved_contiguous_loader(self):
        self.assertEqual(self.check(medium(), loader=True), 1)

    def test_wrong_geometry_and_fat_copy_disagreement(self):
        for offset in (11, 13, 14, 16, 17, 19, 22, 24, 26, 28, 32, 3072):
            data = medium()
            data[offset] ^= 1
            with self.subTest(offset=offset):
                self.assertEqual(self.check(data), 0)

    def test_cross_link_or_file_length_mismatch(self):
        for offset, value in ((5120 + 32 + 26, 20), (5120 + 28, 1)):
            data = medium()
            struct.pack_into('<H', data, offset, value)
            self.assertEqual(self.check(data), 0)

    def test_orphan_and_duplicate_name_are_rejected(self):
        data = medium()
        data[5120 + 32] = 0xe5
        self.assertEqual(self.check(data), 0)
        data = medium()
        data[5120 + 32:5120 + 43] = b'LOADER  BIN'
        self.assertEqual(self.check(data), 0)

    def test_directories_are_outside_prepared_target_contract(self):
        data = medium()
        data[5120 + 32 + 11] = 0x10
        self.assertEqual(self.check(data), 0)

    def test_nonexistent_cluster_nibble_and_fat_tail_are_rejected(self):
        for offset, value in ((1906, 0xf0), (1907, 1), (2047, 1)):
            data = medium()
            data[1024 + offset] |= value
            data[3072 + offset] |= value
            self.assertEqual(self.check(data), 0)


if __name__ == '__main__':
    unittest.main()
