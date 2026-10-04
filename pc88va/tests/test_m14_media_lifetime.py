#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Execute actual common C policy with synthetic media, not firmware or ABI."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(os.environ.get("M14_KERNEL_SOURCE_ROOT", Path(__file__).resolve().parents[2]))


def function(source, signature):
    start = re.search(re.escape(signature) + r'[^;{}]*\{', source).start()
    level = 0
    for token in re.finditer(r'/\*[\s\S]*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|[{}]', source[start:]):
        if token[0] == '{':
            level += 1
        elif token[0] == '}':
            level -= 1
            if level == 0:
                return source[start:start + token.end()] + '\n'
    raise AssertionError(signature)


HARNESS = r'''
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define STATIC static
#define REG
#define FAR
#define VOID void
#define FOREVER for (;;)
#define TRUE 1
#define FALSE 0
#define SUCCESS 0
#define DE_INVLDHNDL -6
#define DE_INVLDDRV -15
#define DE_ACCESS -5
#define ABORT 0
#define RETRY 1
#define CONTINUE 2
#define FAIL 3
#define XFR_READ 0
#define XFR_WRITE 1
#define XFR_FORCE_WRITE 2
#define DSKREAD 0
#define DSKWRITE 1
#define DSKWRITEINT26 2
#define DSKREADINT25 3
#define O_WRONLY 1
#define O_ACCMODE 3
#define O_RDONLY 0
#define REM_READ 0
#define REM_WRITE 1
#define REM_FLUSH 2
#define REM_CLOSE 3
#define CTL_Z 26
#define LOC_CONV 0
#define MAXSHORT 65535
#define HUGECOUNT 65535
#define FP_OFF(p) ((size_t)(p))
#define FP_SEG(p) 0x1000
#define MK_FP(s,o) ((void *)(size_t)(o))
#define fmemcpy memcpy
typedef int COUNT, BOOL;
typedef uint8_t UBYTE;
typedef char BYTE;
typedef uint16_t UWORD;
typedef uint32_t ULONG;
typedef struct { int dummy; } bpb, boot;
struct dhdr { unsigned dh_attr; };
struct dpb { int dpb_unit, dpb_subunit; UBYTE dpb_flags; int dpb_mdb, dpb_secsize; struct dhdr *dpb_device; };
typedef struct { unsigned sft_count, sft_mode, sft_flags; int sft_shroff;
    ULONG sft_posit; struct dpb *sft_dcb; struct dhdr *sft_dev; } sft;
typedef struct sfttbl { struct sfttbl *sftt_next; int sftt_count; sft sftt_table[8]; } sfttbl;
struct buffer { unsigned b_flag, b_unit, b_copies, b_offset; ULONG b_blkno; char b_buffer[1024]; struct buffer *next; };
#define b_next(p) ((p)->next)
typedef struct { unsigned r_length,r_unit,r_command,r_status,r_mcmdesc,r_meddesc,r_count;
    int r_mcretcode; unsigned r_start; ULONG r_huge; void *r_trans,*r_bpfat; bpb *r_bpptr; } request;
static struct dhdr device;
static struct dpb disks[2] = {{0,0,0,0,1024,&device},{1,1,0,0,1024,&device}};
static sfttbl table, *sfthead = &table;
static struct buffer buffer, other_buffer, *firstbuf = &buffer;
static request MediaReqHdr, IoReqHdr;
static char DiskTransferBuffer[1024], deblock_buf[1024];
static unsigned verify_ena, bufloc, cu_psp;
static void *dta;
static sft *lpCurSft;
static ULONG current_filepos;
static int signal_code = 1, media_error, media_calls, builds, io_calls, rw_calls, close_calls;
static int inject_io_error, recovery, critical_reply = RETRY, critical_calls;
static struct dpb *get_dpb(int d) { return d >= 0 && d < 2 ? &disks[d] : NULL; }
static sft *idx_to_sft(int i) { return i >= 0 && i < 8 ? &table.sftt_table[i] : (sft *)-1; }
static int IsShareInstalled(int x) { (void)x; return 0; }
static int share_access_check(unsigned a,int b,ULONG c,ULONG d,int e) { abort(); }
static void share_close_file(int x) { abort(); }
static long remote_rw(int a,sft*b,unsigned c) { abort(); }
static int network_redirector_fp(int a,sft*b) { abort(); }
static long BinaryCharIO(struct dhdr **a,unsigned b,void*c,int d) { abort(); }
static void update_scr_pos(char c,int n) { abort(); }
static long read_line_handle(int a,unsigned b,void*c) { abort(); }
static long cooked_read(struct dhdr **a,unsigned b,void*c) { abort(); }
static long cooked_write(struct dhdr **a,unsigned b,void*c) { abort(); }
static void bpb_to_dpb(bpb *b, struct dpb *d) { (void)b; d->dpb_flags=0; }
COUNT media_check(struct dpb *d);
VOID setinvld(COUNT d);
BOOL dirty_buffers(COUNT d);
BOOL flush1(struct buffer *b);
UWORD dskxfer(COUNT d,ULONG l,void *b,UWORD n,COUNT m);
static int block_error(request *r,int d,struct dhdr *dev,int mode) {
    (void)r; (void)dev; (void)mode;
    if (++critical_calls > 3) abort();
    if (recovery == 1) signal_code = -1;
    if (recovery == 2) { signal_code = -1; media_check(&disks[d]); signal_code = 1; }
    return critical_reply;
}
static void execrh(request *r,struct dhdr *dev) {
    (void)dev;
    if (r->r_command == C_MEDIACHK) {
        ++media_calls;
        r->r_status = media_error ? S_ERROR|S_DONE|E_NOTRDY : S_DONE;
        r->r_mcretcode = signal_code;
    } else if (r->r_command == C_BLDBPB) {
        ++builds; r->r_status = S_DONE;
    } else {
        ++io_calls;
        r->r_status = inject_io_error && io_calls == 1 ? S_ERROR|S_DONE|E_WRITE : S_DONE;
    }
}
static long rwblock(int fd,void *b,unsigned n,int mode) {
    (void)fd; (void)b; (void)mode; ++rw_calls; return n;
}
static COUNT dos_close(int fd) { (void)fd; ++close_calls; return SUCCESS; }
'''

MAIN = r'''
int main(int argc,char **argv) {
    int result = -99, op;
    if (argc != 3) return 2;
    op = atoi(argv[1]); signal_code = atoi(argv[2]);
    table.sftt_next = (sfttbl *)-1; table.sftt_count = 8;
    table.sftt_table[0] = (sft){2,2,0,-1,0,&disks[0],NULL};
    table.sftt_table[1] = (sft){1,2,0,-1,0,&disks[1],NULL};
    table.sftt_table[2] = (sft){1,2,SFT_FDEVICE,-1,0,&disks[0],&device};
    table.sftt_table[3] = (sft){1,2,SFT_FSHARED,-1,0,&disks[0],NULL};
    table.sftt_table[4] = (sft){1,2,0,-1,0,NULL,NULL}; /* unbound new open */
    buffer = (struct buffer){BFR_VALID|BFR_DIRTY,0,1,0,7,{0},&other_buffer};
    other_buffer = (struct buffer){BFR_VALID|BFR_DIRTY,1,1,0,8,{0},&buffer};
    switch (op) {
    case 0: result = media_check(&disks[0]); break;
    case 1: result = DosRWSft(0,4,DiskTransferBuffer,XFR_WRITE); break;
    case 2: result = DosRWSft(0,4,DiskTransferBuffer,XFR_READ); break;
    case 3: result = DosCloseSft(0,FALSE); break;
    case 4: result = DosCloseSft(0,TRUE); break;
    case 5: result = flush1(&buffer); break;
    case 6: case 7:
        signal_code=1; inject_io_error=1; recovery=op-5;
        result=dskxfer(0,7,DiskTransferBuffer,1,DSKWRITE); break;
    case 8: /* A successful new pathname check must not revive an old handle. */
        media_check(&disks[0]); signal_code=1;
        result=DosRWSft(0,4,DiskTransferBuffer,XFR_WRITE); break;
    case 9: /* A fresh bound slot is usable; another stale slot stays stale. */
        media_check(&disks[0]); signal_code=1;
        table.sftt_table[4].sft_dcb=&disks[0];
        result=DosRWSft(4,4,DiskTransferBuffer,XFR_WRITE); break;
    case 10: media_error=1; critical_reply=CONTINUE; result=media_check(&disks[0]); break;
    case 11: media_error=1; result=DosRWSft(0,4,DiskTransferBuffer,XFR_WRITE); break;
    default: return 2;
    }
    printf("%d %u %u %u %u %u %u %u %d %d %d %d %d\n",result,
        table.sftt_table[0].sft_flags,table.sftt_table[0].sft_count,
        table.sftt_table[1].sft_flags,table.sftt_table[2].sft_flags,
        table.sftt_table[3].sft_flags,table.sftt_table[4].sft_flags,
        buffer.b_flag,io_calls,rw_calls,close_calls,builds,critical_calls);
    return 0;
}
'''


class MediaLifetimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="m14-media-lifetime-")
        cls.addClassCleanup(cls.tmp.cleanup)
        fat = (ROOT / "kernel/fatfs.c").read_text()
        block = (ROOT / "kernel/blockio.c").read_text()
        dos = (ROOT / "kernel/dosfns.c").read_text()
        definitions = []
        for file, prefixes in (("hdr/device.h", ("S_", "E_", "C_", "M_", "ATTR_HUGE")),
                               ("hdr/sft.h", ("SFT_",)),
                               ("hdr/buffer.h", ("BFR_",))):
            header = (ROOT / file).read_text()
            definitions.extend(line for line in header.splitlines()
                               if line.startswith("#define ") and line.split()[1].startswith(prefixes))
        bodies = []
        for signature in ("STATIC void media_request(", "VOID media_invalidate(",
                          "BOOL media_check_io(", "BOOL media_check_sft("):
            if signature in fat:
                bodies.append(function(fat, signature))
        policy = ("#if defined(PC88VA)\nUWORD media_generation;\n" + ''.join(bodies[1:]) + "#endif\n") if bodies else ""
        code = '\n'.join(definitions) + HARNESS
        if bodies:
            code += bodies[0] + policy
        for src, signatures in ((fat, ("STATIC int rqblockio(", "COUNT media_check(")),
                                (block, ("VOID setinvld(", "BOOL dirty_buffers(", "BOOL flush1(", "UWORD dskxfer(")),
                                (dos, ("long DosRWSft(", "COUNT DosCloseSft("))):
            code += ''.join(function(src, signature) for signature in signatures)
        code += MAIN
        path = Path(cls.tmp.name) / "policy.c"
        path.write_text(code)
        cls.programs = {}
        for va in (False, True):
            target = path.with_name("va" if va else "original")
            result = subprocess.run(["cc", "-std=c99", "-Werror=implicit-function-declaration",
                                     *(["-DPC88VA"] if va else []), str(path), "-o", str(target)],
                                    capture_output=True)
            if result.returncode:
                raise AssertionError(result.stderr.decode())
            cls.programs[va] = target

    def run_case(self, op, signal=1, va=True):
        output = subprocess.check_output([str(self.programs[va]), str(op), str(signal)], timeout=5)
        return tuple(map(int, output.split()))

    def test_changed_and_unknown_invalidate_only_bound_local_handles(self):
        for signal in (-1, 0):
            result = self.run_case(0, signal)
            self.assertEqual(result[:8], (0, 0x2000, 2, 0, 0x80, 0x8000, 0, 0))
            self.assertEqual(result[11], 1)

    def test_unchanged_media_keeps_handles_and_pending_data(self):
        result = self.run_case(0)
        self.assertEqual(result[0:2], (0, 0))
        self.assertNotEqual(result[7], 0)
        self.assertEqual(result[11], 0)

    def test_old_reads_and_writes_are_rejected_before_filesystem_access(self):
        for op in (1, 2):
            for signal in (-1, 0):
                result = self.run_case(op, signal)
                self.assertEqual(result[0], -6)
                self.assertEqual(result[8:11], (0, 0, 0))

    def test_stale_close_releases_one_reference_without_writeback(self):
        result = self.run_case(3, -1)
        self.assertEqual(result[:3], (-6, 0x2000, 1))
        self.assertEqual(result[10], 0)
        self.assertEqual(self.run_case(4, -1)[:3], (-6, 0x2000, 2))

    def test_dirty_flush_cannot_target_replacement(self):
        for signal in (-1, 0):
            result = self.run_case(5, signal)
            self.assertEqual(result[0], 0)
            self.assertEqual(result[8], 0)

    def test_retry_cannot_rebind_even_if_error_handler_revalidated(self):
        for op in (6, 7):
            result = self.run_case(op)
            self.assertNotEqual(result[0], 0)
            self.assertEqual(result[8], 1)

    def test_explicit_new_open_does_not_revive_old_handle(self):
        result = self.run_case(8, -1)
        self.assertEqual(result[0], -6)
        self.assertEqual(result[9], 0)
        self.assertEqual(self.run_case(9, -1)[0], 4)

    def test_failed_query_cannot_be_ignored_into_a_valid_binding(self):
        result = self.run_case(10)
        self.assertEqual(result[0], -15)
        self.assertEqual(result[1], 0x2000)
        result = self.run_case(11)
        self.assertEqual(result[0], -6)
        self.assertEqual(result[8:11], (0, 0, 0))
        self.assertEqual(result[12], 0)

    def test_non_va_unknown_keeps_dirty_cache_and_original_handle_behavior(self):
        result = self.run_case(0, 0, va=False)
        self.assertEqual(result[0:2], (0, 0))
        self.assertNotEqual(result[7], 0)
        self.assertEqual(result[11], 0)
        self.assertEqual(self.run_case(1, -1, va=False)[0], 4)
        self.assertEqual(self.run_case(3, -1, va=False)[0], 0)


if __name__ == "__main__":
    unittest.main()
