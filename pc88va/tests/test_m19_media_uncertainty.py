#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Exercise actual block-driver policy with synthetic media, without firmware."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

from test_m14_media_lifetime import function

ROOT = Path(os.environ.get('M19_KERNEL_SOURCE_ROOT', Path(__file__).resolve().parents[2]))
HARNESS = r'''
#include <stdint.h>
#include <string.h>
#include <assert.h>
#define STATIC static
#define M_CHANGED -1
#define M_DONT_KNOW 0
#define M_NOT_CHANGED 1
#define DF_CHANGELINE 2
#define DF_DISKCHANGE 64
#define DF_REFORMAT 256
#define S_DONE 256
#define hd(flags) ((flags)&1)
typedef int COUNT, WORD;
typedef uint32_t ULONG;
typedef struct { unsigned char bytes[31]; } bpb;
typedef struct { int ddt_descflags, ddt_driveno; ULONG ddt_serialno; bpb ddt_bpb; } ddt;
typedef struct { int r_mcretcode; } request, *rqptr;
static int signal_code, probe_error, probes, marks, elapsed;
static ULONG next_serial;
static bpb next_bpb;
static int play_dj(ddt *p) { (void)p; return M_NOT_CHANGED; }
static int fl_diskchanged(int d) { (void)d; return signal_code; }
static int tdelay(ddt *p, ULONG ticks) { (void)p; assert(ticks==37); return elapsed; }
static void tmark(ddt *p) { (void)p; ++marks; }
static int getbpb(ddt *p) {
 ++probes;
 if(probe_error) return probe_error;
 p->ddt_serialno=next_serial;
 p->ddt_bpb=next_bpb;
 p->ddt_descflags |= DF_DISKCHANGE;
 return 0;
}
'''
CASES = r'''
int main(void) {
 ddt d; request r; int i;
 memset(&d,0,sizeof d); d.ddt_descflags=DF_CHANGELINE;
 d.ddt_serialno=next_serial=1234;
 for(i=0;i<31;i++) d.ddt_bpb.bytes[i]=next_bpb.bytes[i]=(unsigned char)(i+1);
 signal_code=0; assert(diskchange(&d)==M_NOT_CHANGED);
 signal_code=1; assert(diskchange(&d)==M_CHANGED);
 signal_code=-1; elapsed=0;
#ifdef PC88VA
 assert(diskchange(&d)==M_DONT_KNOW); /* no grace interval hides uncertainty */
 assert(mediachk(&r,&d)==S_DONE && r.r_mcretcode==M_NOT_CHANGED);
 assert(probes==1 && marks==1 && !(d.ddt_descflags&DF_DISKCHANGE));
 d.ddt_descflags |= DF_DISKCHANGE;
 assert(mediachk(&r,&d)==S_DONE && r.r_mcretcode==M_NOT_CHANGED);
 assert(probes==2 && marks==2 && !(d.ddt_descflags&DF_DISKCHANGE));
 /* Every BPB byte is part of the bound layout, not just the volume ID. */
 for(i=0;i<31;i++) {
  next_bpb=d.ddt_bpb; next_bpb.bytes[i]^=1;
  assert(mediachk(&r,&d)==S_DONE && r.r_mcretcode==M_CHANGED);
  d.ddt_descflags=DF_CHANGELINE;
 }
 next_serial++;
 assert(mediachk(&r,&d)==S_DONE && r.r_mcretcode==M_CHANGED);
 d.ddt_descflags=DF_CHANGELINE; d.ddt_serialno=next_serial=0;
 assert(mediachk(&r,&d)==S_DONE && r.r_mcretcode==M_DONT_KNOW);
 probe_error=0x8102;
 assert(mediachk(&r,&d)==probe_error);
 probe_error=0; probes=0; signal_code=1; d.ddt_descflags=DF_CHANGELINE;
 assert(mediachk(&r,&d)==S_DONE && r.r_mcretcode==M_CHANGED && probes==0);
 d.ddt_descflags=DF_REFORMAT; signal_code=0;
 assert(mediachk(&r,&d)==S_DONE && r.r_mcretcode==M_CHANGED && probes==0);
#else
 /* Keep the selected upstream non-VA tri-state/timer behavior unchanged. */
 assert(diskchange(&d)==M_NOT_CHANGED);
 elapsed=1;
 assert(diskchange(&d)==M_DONT_KNOW);
 assert(mediachk(&r,&d)==S_DONE && r.r_mcretcode==M_DONT_KNOW);
 assert(probes==1 && marks==0);
 d.ddt_descflags=DF_CHANGELINE; next_serial++;
 assert(mediachk(&r,&d)==S_DONE && r.r_mcretcode==M_CHANGED);
 probes=0; d.ddt_descflags=DF_DISKCHANGE; signal_code=0;
 assert(mediachk(&r,&d)==S_DONE && r.r_mcretcode==M_DONT_KNOW && probes==0);
#endif
 return 0;
}
'''


class MediaUncertaintyTests(unittest.TestCase):
    def test_actual_driver_policy_and_non_va_control(self):
        source = (ROOT / 'kernel/dsk.c').read_text()
        code = HARNESS + function(source, 'STATIC WORD diskchange(')
        code += function(source, 'STATIC WORD mediachk(') + CASES
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / 'policy.c').write_text(code)
            for defines in ([], ['-DPC88VA']):
                with self.subTest(defines=defines):
                    subprocess.run(['cc', '-std=c99', '-Wall', '-Wextra',
                                    *defines, str(path / 'policy.c'), '-o', str(path / 'policy')], check=True)
                    subprocess.run([str(path / 'policy')], check=True)

    def test_real_firmware_adapter_uncertainty_and_far_abi(self):
        from unicorn import Uc, UC_ARCH_X86, UC_MODE_16, UC_HOOK_INTR
        from unicorn.x86_const import (UC_X86_REG_AX, UC_X86_REG_BX, UC_X86_REG_CX,
            UC_X86_REG_DX, UC_X86_REG_SI, UC_X86_REG_DI, UC_X86_REG_BP,
            UC_X86_REG_CS, UC_X86_REG_DS, UC_X86_REG_ES, UC_X86_REG_SS,
            UC_X86_REG_SP, UC_X86_REG_EFLAGS)
        import struct
        text = (ROOT / 'pc88va/kernel/m13_platform.asm').read_text()
        body = text.split('FL_DISKCHANGED:\n', 1)[1].split('; Read logical sector 1', 1)[0]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / 'probe.asm').write_text('bits 16\norg 0x100\n' + body)
            subprocess.run(['nasm', '-f', 'bin', str(path / 'probe.asm'),
                            '-o', str(path / 'probe.bin')], check=True)
            for carry in (0, 1):
                cpu = Uc(UC_ARCH_X86, UC_MODE_16)
                cpu.mem_map(0, 0x100000)
                cpu.mem_write(0x20100, (path / 'probe.bin').read_bytes())
                regs = {UC_X86_REG_CS:0x2000, UC_X86_REG_DS:0x3000,
                        UC_X86_REG_ES:0x4000, UC_X86_REG_SS:0x5000,
                        UC_X86_REG_SP:0xff0, UC_X86_REG_AX:0xaaaa,
                        UC_X86_REG_BX:0x1234, UC_X86_REG_CX:0x5678,
                        UC_X86_REG_DX:0x9abc, UC_X86_REG_SI:0x1357,
                        UC_X86_REG_DI:0x2468, UC_X86_REG_BP:0x6789}
                for reg, value in regs.items(): cpu.reg_write(reg, value)
                cpu.mem_write(0x50ff0, struct.pack('<HHH', 0x100, 0x6000, 1))
                def bios(uc, number, _):
                    self.assertEqual(number, 0x80)
                    self.assertEqual(uc.reg_read(UC_X86_REG_AX) >> 8, 9)
                    self.assertEqual(uc.reg_read(UC_X86_REG_CX) >> 8, 1)
                    uc.reg_write(UC_X86_REG_CX, 0xbeef)
                    uc.reg_write(UC_X86_REG_AX, 0)
                    uc.reg_write(UC_X86_REG_EFLAGS, (uc.reg_read(UC_X86_REG_EFLAGS) & ~1) | carry)
                cpu.hook_add(UC_HOOK_INTR, bios)
                cpu.emu_start(0x20100, 0x60100, count=100)
                self.assertEqual(cpu.reg_read(UC_X86_REG_AX), 0xffff if carry else 0)
                self.assertEqual(cpu.reg_read(UC_X86_REG_SP), 0xff6)
                for reg in (UC_X86_REG_BX, UC_X86_REG_CX, UC_X86_REG_SI,
                            UC_X86_REG_DI, UC_X86_REG_BP, UC_X86_REG_DS,
                            UC_X86_REG_ES, UC_X86_REG_SS):
                    self.assertEqual(cpu.reg_read(reg), regs[reg])


if __name__ == '__main__':
    unittest.main()
