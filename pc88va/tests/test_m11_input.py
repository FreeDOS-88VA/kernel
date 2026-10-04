#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""ROM-free read-only matrix tests; not private runtime qualification."""
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unicorn import Uc, UC_ARCH_X86, UC_MODE_16, UC_HOOK_INTR, UC_HOOK_MEM_WRITE, UC_HOOK_INSN
from unicorn.x86_const import *

TARGET = Path(__file__).resolve().parents[1]
CODE, STACK, STOP = 0x1000, 0x7000, 0x3f00
# Independent public coordinate fixtures, not extracted from target bytes.
LETTERS = dict(zip('abcdefghijklmnopqrstuvwxyz',
    [0x21,0x22,0x23,0x24,0x25,0x26,0x27,0x30,0x31,0x32,0x33,0x34,0x35,
     0x36,0x37,0x40,0x41,0x42,0x43,0x44,0x45,0x46,0x47,0x50,0x51,0x52]))
PUNCTUATION = {0x57:('-', '='),0x56:('^',chr(96)),0x54:(chr(92),'|'),
               0x20:('@','~'),0x53:('[','{'),0x73:(';','+'),0x72:(':','*'),
               0x55:(']','}'),0x74:(',','<'),0x75:('.','>'),0x76:('/','?'),
               0x77:(chr(92),'_')}

def matrix(*positions):
    rows = [255]*15
    for pos in positions: rows[pos >> 4] &= ~(1 << (pos & 7))
    return rows

class InputTests(unittest.TestCase):
    def execute(self, snapshots, *, ready=2, pointer=True, ds=CODE, flags=0x93):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); source=root/'test.asm'; binary=root/'test.bin'
            source.write_text('bits 16\ncpu 8086\norg 0\njmp near pc88va_console_getc_\n'
                              'dw pc88va_m11_character_, pc88va_m11_storage_begin, pc88va_m11_storage_end\n'
                              f'pc88va_m10_state_: db {ready}\n'
                              'pc88va_m10_clock_record_: dw 1,0,0\n'
                              'pc88va_clock_read_: xor ax,ax\nret\n'
                              '%define M11_FLAT_TEST 1\n%include "console_input.asm"\n')
            subprocess.run(['nasm','-f','bin','-DPC88VA','-I',str(TARGET/'kernel')+'/',
                            '-o',str(binary),str(source)],check=True,capture_output=True)
            code=binary.read_bytes()
        output,begin,end=struct.unpack_from('<HHH',code,3)
        cpu=Uc(UC_ARCH_X86,UC_MODE_16);cpu.mem_map(0,0x100000);cpu.mem_write(CODE*16,code)
        cpu.mem_write(CODE*16+output,b'\xad\xde')
        regs={UC_X86_REG_BX:0x1357,UC_X86_REG_CX:0x2468,UC_X86_REG_DX:0x4567,
              UC_X86_REG_SI:0x3456,UC_X86_REG_DI:0x5678,UC_X86_REG_BP:0x6789,
              UC_X86_REG_DS:ds,UC_X86_REG_ES:0x4000,UC_X86_REG_SS:STACK,UC_X86_REG_EFLAGS:flags}
        reads=[];writes=[];results=[];current=[None]
        def port_in(machine,port,size,_):
            self.assertIn(port,range(15));self.assertEqual(size,1);reads.append(port)
            return current[0][port]
        def port_out(*args): self.fail('poll must never write a device')
        def interrupt(*args): self.fail('poll must never call firmware or interrupt a device')
        cpu.hook_add(UC_HOOK_INSN,port_in,None,1,0,UC_X86_INS_IN)
        cpu.hook_add(UC_HOOK_INSN,port_out,None,1,0,UC_X86_INS_OUT)
        cpu.hook_add(UC_HOOK_INTR,interrupt)
        cpu.hook_add(UC_HOOK_MEM_WRITE,lambda uc,access,address,size,value,data:writes.append((address,size)))
        for snapshot in snapshots:
            current[0]=snapshot
            for reg,value in regs.items():cpu.reg_write(reg,value)
            cpu.reg_write(UC_X86_REG_CS,CODE);cpu.reg_write(UC_X86_REG_SP,0x1000)
            cpu.reg_write(UC_X86_REG_AX,output if pointer else 0)
            cpu.mem_write(STACK*16+0x1000,struct.pack('<H',STOP))
            cpu.emu_start(CODE*16,CODE*16+STOP,count=10000)
            self.assertEqual(cpu.reg_read(UC_X86_REG_IP),STOP)
            self.assertEqual(cpu.reg_read(UC_X86_REG_SP),0x1002)
            for reg,value in regs.items():self.assertEqual(cpu.reg_read(reg),value)
            results.append((cpu.reg_read(UC_X86_REG_AX),struct.unpack('<H',cpu.mem_read(CODE*16+output,2))[0]))
        self.assertTrue(all((STACK*16+0xfee<=a and a+n<=STACK*16+0x1000) or
                            (CODE*16+begin<=a and a+n<=CODE*16+end) for a,n in writes))
        return results,reads

    def test_all_printable_ascii(self):
        fixtures=[(p,c,False) for c,p in LETTERS.items()]+[(p,c.upper(),True) for c,p in LETTERS.items()]
        fixtures += [(0x60,'0',False)]
        for i in range(1,10):
            pos=0x60+i if i<8 else 0x70+i-8
            fixtures += [(pos,str(i),False),(pos,'!"#$%&\'()'[i-1],True)]
        for pos,(plain,shift) in PUNCTUATION.items():fixtures += [(pos,plain,False),(pos,shift,True)]
        fixtures += [(0x96,' ',False)]
        self.assertEqual({ord(c) for p,c,s in fixtures},set(range(32,127)))
        for pos,ch,shift in fixtures:
            with self.subTest(ch=ch,shift=shift):
                result,reads=self.execute([matrix(),matrix(pos,*([0xe2,0x86] if shift else []))])
                self.assertEqual(result,[(1,0xdead),(0,ord(ch))])
                self.assertEqual(reads,list(range(15))*2)

    def test_released_repeated_and_delayed(self):
        result,_=self.execute([matrix(),matrix(),matrix(0x21),matrix(0x21),matrix(),matrix(0x21),matrix()])
        self.assertEqual(result,[(1,0xdead),(1,0xdead),(0,97),(1,97),(1,97),(0,97),(1,97)])

    def test_enter_backspace_aliases_and_right_shift(self):
        for positions,ch in [((0xe0,0x17),13),((0xe1,0x17),13),((0xc5,0x83),8),
                              ((0xe3,0x86,0x21),65),((0x96,),32)]:
            self.assertEqual(self.execute([matrix(),matrix(*positions)])[0],[(1,0xdead),(0,ch)])

    def test_adopt_held_key_and_shift_only(self):
        self.assertEqual(self.execute([matrix(0x21),matrix(0x21),matrix(),matrix(0x21)])[0],
                         [(1,0xdead),(1,0xdead),(1,0xdead),(0,97)])
        self.assertEqual(self.execute([matrix(),matrix(0xe2,0x86),matrix()])[0],
                         [(1,0xdead)]*3)

    def test_unsupported_and_ambiguous_make(self):
        for positions in [(0x97,),(0xa0,),(0x21,0x22),(0x87,0x21),(0x84,0x21),
                          (0x85,0x21),(0xa7,0x21),(0xd0,0x96),(0xe2,0x60)]:
            with self.subTest(positions=positions):
                self.assertEqual(self.execute([matrix(),matrix(*positions),matrix(*positions)])[0],
                                 [(1,0xdead),(2,0xdead),(1,0xdead)])

    def test_preconditions_no_device_access(self):
        for options in ({'ready':0},{'ready':1},{'ready':3},{'pointer':False},
                        {'ds':0x3000},{'flags':0x202},{'flags':0x402}):
            self.assertEqual(self.execute([matrix(0x21)],**options),([(0xffff,0xdead)],[]))

    def test_tf_is_an_explicit_entry_precondition(self):
        # Setting live TF would trap before the adapter can check its frame;
        # that CPU exception is not a firmware/device call by the adapter.
        self.assertIn('test word [ss:bp+16], 0700h',
                      (TARGET/'kernel/console_input.asm').read_text())

    def test_two_projections_identical(self):
        snapshots=[matrix(),matrix(0x21),matrix(),matrix(0xe2,0x21),matrix()]
        self.assertEqual(self.execute(snapshots),self.execute(snapshots))

if __name__=='__main__':unittest.main()
