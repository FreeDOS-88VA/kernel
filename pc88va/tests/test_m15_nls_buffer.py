#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Check NLS table-copy bounds and preserve the selected FreeDOS fallback."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_m14_media_lifetime import function

ROOT = Path(__file__).resolve().parents[2]
HEADER = r'''
#include <assert.h>
#include <stdint.h>
#define NULL ((void *)0)
#include <stdlib.h>
#include <string.h>
#define STATIC static
#define FAR
#define VOID void
#define log(x)
#define SUCCESS 0
#define DE_INVLDFUNC -1
#define DE_FILENOTFND -2
#define DE_INVLDDATA -13
#define NLS_DOS_38 256
#define NLS_FLAG_DIRECT_GETDATA 1
#define fmemcpy memcpy
#define FP_SEG(p) ((uintptr_t)(p) ? 1 : 0)
#define FP_OFF(p) ((uintptr_t)(p))
typedef int COUNT;
typedef uint16_t UWORD;
struct nlsPackage { unsigned flags,cp,cntry; };
static struct nlsPackage active={1,437,1};
static struct nlsPackage *searchPackage(unsigned cp,unsigned country) {
    return cp==437 && country==1 ? &active : NULL;
}
static int mux38(unsigned cp,unsigned country,unsigned count,void *p) {
    (void)cp; (void)country; (void)count; (void)p; return DE_INVLDFUNC;
}
static int mux65(int sub,unsigned cp,unsigned country,unsigned count,void *p) {
    (void)sub; (void)cp; (void)country; (void)count; (void)p;
    return DE_INVLDFUNC;
}
'''
TABLE = r'''
static int nlsGetData(struct nlsPackage *nls,int sub,void *p,unsigned count) {
    unsigned char packet[5]={0,0x34,0x12,0x00,0x20};
    assert(nls==&active);
    if(sub==3) return DE_INVLDFUNC;
    packet[0]=sub;
    return cpyBuf(p,count,packet,sizeof(packet));
}
'''
MAIN = r'''
int main(int argc,char **argv) {
    unsigned char guarded[10]; unsigned count; int sub,ret;
    unsigned country;
    assert(argc==4); sub=atoi(argv[1]); count=(unsigned)atoi(argv[2]);
    country=(unsigned)atoi(argv[3]);
    if(sub==98)
        return DosGetData(NLS_DOS_38,437,country,count,guarded+2)==DE_INVLDFUNC ? 0 : 1;
    if(sub==99)
        return DosGetData(2,437,1,5,0)==DE_INVLDDATA ? 0 : 1;
    memset(guarded,0xcc,sizeof(guarded));
    ret=DosGetData(sub,437,country,count,guarded+2);
    assert(guarded[0]==0xcc && guarded[1]==0xcc);
    assert(guarded[7]==0xcc && guarded[8]==0xcc && guarded[9]==0xcc);
    if(country!=1 && (sub==1 || sub==2 || (sub>=4 && sub<=7))) {
        unsigned i;
        assert(ret==DE_INVLDFUNC);
        for(i=0;i<sizeof(guarded);++i) assert(guarded[i]==0xcc);
    } else if(country!=1) {
        unsigned i;
        assert(ret==DE_INVLDFUNC);
        for(i=0;i<sizeof(guarded);++i) assert(guarded[i]==0xcc);
    } else if(sub==3) {
        unsigned i;
        assert(ret==DE_INVLDFUNC);
        for(i=0;i<sizeof(guarded);++i) assert(guarded[i]==0xcc);
    } else if(count==0) {
        unsigned i; assert(ret==DE_INVLDDATA);
        for(i=0;i<sizeof(guarded);++i) assert(guarded[i]==0xcc);
    } else if(count<5) {
        unsigned i; assert(ret==DE_INVLDFUNC);
        for(i=0;i<sizeof(guarded);++i) assert(guarded[i]==0xcc);
    } else {
        assert(ret==0 && guarded[2]==sub && guarded[3]==0x34);
        assert(guarded[4]==0x12 && guarded[5]==0 && guarded[6]==0x20);
    }
    return 0;
}
'''

MUX_HEADER = r'''
#include <assert.h>
#include <stdint.h>
#define NULL ((void *)0)
#define FAR
#define VOID void
#define ASMCFUNC
#define log(x)
#define MK_FP(seg,off) ((void *)(uintptr_t)(((unsigned)(seg)<<16)|(off)))
#define SUCCESS 0
#define DE_INVLDFUNC -1
#define DE_FILENOTFND -2
#define NLSFUNC_INSTALL_CHECK 0
#define NLSFUNC_DOS38 4
#define NLSFUNC_GETDATA 2
#define NLSFUNC_DRDOS_GETDATA 0xfe
#define NLSFUNC_LOAD_PKG 3
#define NLSFUNC_LOAD_PKG2 1
#define NLSFUNC_UPMEM 0x22
#define NLSFUNC_YESNO 0x23
#define NLSFUNC_FILE_UPMEM 0xa2
#define NLS_FREEDOS_NLSFUNC_ID 0x1234
#define NLS_DOS_38 0x101
typedef uint16_t UWORD;
struct nlsPackage { unsigned cp,cntry; };
typedef struct { UWORD AL,BX,DX,BP,ES,DI,CX,CL; } iregs;
static struct nlsPackage active={437,1};
static struct nlsPackage *searchPackage(unsigned cp,unsigned country) {
    return cp==437 && country==1 ? &active : 0;
}
static int nlsGetData(struct nlsPackage *nls,int sub,void *p,unsigned count) {
    (void)nls; (void)p; (void)count;
    return sub==3 ? DE_INVLDFUNC : SUCCESS;
}
static int nlsLoadPackage(struct nlsPackage *p) { (void)p; return SUCCESS; }
static int nlsSetPackage(struct nlsPackage *p) { (void)p; return SUCCESS; }
static int nlsYesNo(struct nlsPackage *p,unsigned count) {
    (void)p; (void)count; return SUCCESS;
}
static void nlsUpMem(struct nlsPackage *p,void *buf,unsigned count) {
    (void)p; (void)buf; (void)count;
}
static void nlsFUpMem(struct nlsPackage *p,void *buf,unsigned count) {
    (void)p; (void)buf; (void)count;
}
'''
MUX_MAIN = r'''
int main(void) {
    iregs request={0};
    request.AL=NLSFUNC_INSTALL_CHECK; request.BX=437; request.DX=65534;
    assert(syscall_MUX14(&request)==(UWORD)DE_INVLDFUNC);
    request.DX=1;
    assert(syscall_MUX14(&request)==SUCCESS);
    assert(request.BX==NLS_FREEDOS_NLSFUNC_ID);
    request.AL=NLSFUNC_GETDATA; request.BX=437; request.DX=65534;
    request.BP=2;
    assert(syscall_MUX14(&request)==(UWORD)DE_INVLDFUNC);
    request.AL=NLSFUNC_YESNO;
    assert(syscall_MUX14(&request)==(UWORD)DE_INVLDFUNC);
    request.AL=0x55;
    assert(syscall_MUX14(&request)==(UWORD)DE_INVLDFUNC);
    request.DX=1; request.AL=NLSFUNC_GETDATA; request.BP=3;
    assert(syscall_MUX14(&request)==(UWORD)DE_INVLDFUNC);
    request.BP=2;
    assert(syscall_MUX14(&request)==SUCCESS);
    request.AL=0x55;
    assert(syscall_MUX14(&request)==(UWORD)DE_INVLDFUNC);
    return 0;
}
'''


class NlsBufferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        source = (ROOT / 'kernel/nls.c').read_text()
        probe = Path(cls.tmp.name) / 'nls.c'
        probe.write_text(HEADER + function(source, 'STATIC COUNT cpyBuf') +
                         TABLE + function(source, 'COUNT DosGetData') + MAIN)
        cls.binary = probe.with_suffix('')
        result = subprocess.run(['cc', '-std=c99', '-Wall', '-Wextra', '-Werror',
                                 str(probe), '-o', str(cls.binary)],
                                capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(
                f"cc exited {result.returncode}; stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
        mux_source = (ROOT / 'kernel/nls.c').read_text()
        mux_probe = Path(cls.tmp.name) / 'mux14.c'
        mux_probe.write_text(MUX_HEADER +
                             function(mux_source, 'UWORD ASMCFUNC syscall_MUX14') +
                             MUX_MAIN)
        cls.mux_binary = mux_probe.with_name('mux14')
        result = subprocess.run(['cc', '-std=c99', '-Wall', '-Wextra', '-Werror',
                                 str(mux_probe), '-o', str(cls.mux_binary)],
                                capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(
                f"cc exited {result.returncode}; stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )

    def check(self, sizes):
        for sub in (2, 4, 5, 6, 7):
            for size in sizes:
                with self.subTest(sub=sub, size=size):
                    result = subprocess.run([str(self.binary), str(sub), str(size), '1'],
                                            capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_zero_length_uses_free_dos_small_buffer_error(self): self.check([0])
    def test_null_far_pointer_is_rejected(self):
        result = subprocess.run([str(self.binary), '99', '5', '1'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
    def test_short_packets_leave_all_caller_bytes_untouched(self): self.check(range(1, 5))
    def test_exact_and_larger_packets_copy_only_five_bytes(self): self.check([5, 6])

    def test_missing_country_preserves_free_dos_fallback_error(self):
        for sub in (1, 2, 4, 5, 6, 7):
            with self.subTest(sub=sub):
                result = subprocess.run([str(self.binary), str(sub), '5', '65534'],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_unknown_selector_without_country_remains_invalid(self):
        for sub in (3, 8, 255):
            with self.subTest(sub=sub):
                result = subprocess.run([str(self.binary), str(sub), '5', '65534'],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_unsupported_selector_with_loaded_country_remains_invalid(self):
        result = subprocess.run([str(self.binary), '3', '5', '1'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_country_data_preserves_missing_package_fallback(self):
        result = subprocess.run([str(self.binary), '98', '5', '65534'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_mux_keeps_invalid_function_for_missing_package_and_unknown_operation(self):
        result = subprocess.run([str(self.mux_binary)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
