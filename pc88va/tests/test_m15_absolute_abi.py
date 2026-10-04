#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Execute production INT 25h/26h stack switching and C callback frames."""
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import unittest

import unicorn
from unicorn import Uc, UC_ARCH_X86, UC_MODE_16, UC_HOOK_CODE
from unicorn.x86_const import (
    UC_X86_REG_AX, UC_X86_REG_BX, UC_X86_REG_CX, UC_X86_REG_DX,
    UC_X86_REG_SI, UC_X86_REG_DI, UC_X86_REG_BP, UC_X86_REG_DS,
    UC_X86_REG_ES, UC_X86_REG_CS, UC_X86_REG_SS, UC_X86_REG_SP,
    UC_X86_REG_EFLAGS,
)

ROOT=Path(__file__).resolve().parents[2]
CODE,C_CODE,DATA,USER,CALLER=0x1200,0x2800,0x4000,0x6000,0x7200
SP,STOP,CALLBACK=0x7000,0x1000,0x2000


def assemble(source):
    with tempfile.TemporaryDirectory(prefix='m15-absolute-') as directory:
        path=Path(directory)
        (path/'test.asm').write_text(source)
        subprocess.run(['nasm','-f','bin','-I',str(ROOT/'hdr')+'/',
                        str(path/'test.asm'),'-o',str(path/'test.bin')],
                       check=True,capture_output=True)
        return (path/'test.bin').read_bytes()


class AbsoluteAbiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if unicorn.__version__!='2.1.4':
            raise RuntimeError('Execution QA requires pinned Unicorn 2.1.4')
        source=(ROOT/'kernel/entry.asm').read_text()
        body=source[source.index('reloc_call_low_int26_handler:\n'):
                    source.index('CONTINUE        equ')]
        body=re.sub(r'call\s+far\s+_int2526_handler',
                    f'call {C_CODE}:_int2526_handler',body)
        cls.images={}
        for far in (False,True):
            prefix=('bits 16\ncpu 8086\norg 0\n%define XCPU 86\n'
                    '%include "stacks.inc"\n'+('%define PC88VA 1\n' if far else '')+
                    'dw reloc_call_low_int25_handler,reloc_call_low_int26_handler\n'+
                    f'_DGROUP_: dw {DATA}\n_disk_api_tos equ 09000h\n'+
                    f'_int2526_handler equ {CALLBACK}\n')
            cls.images[far]=assemble(prefix+body)

    def execute(self,far,write,same_stack,carry):
        machine=Uc(UC_ARCH_X86,UC_MODE_16);machine.mem_map(0,0x100000)
        code=self.images[far];machine.mem_write(CODE*16,code)
        entry=struct.unpack_from('<H',code,2*write)[0]
        segment=C_CODE if far else CODE
        arg=6 if far else 4
        callback=assemble('bits 16\ncpu 8086\norg 0\npush bp\nmov bp,sp\n'+
                          f'mov bx,[ss:bp+{arg+2}]\nmov es,[ss:bp+{arg+4}]\n'+
                          'mov word [es:bx+18],0beefh\n'+
                          ('or word [es:bx+20],1\n' if carry else
                           'and word [es:bx+20],0fffeh\n')+
                          'pop bp\n'+('retf\n' if far else 'ret\n'))
        machine.mem_write(segment*16+CALLBACK,callback)
        stack=DATA if same_stack else USER
        flags=0x602|int(not carry)
        machine.mem_write(stack*16+SP,struct.pack('<3H',STOP,CALLER,flags))
        saved={UC_X86_REG_AX:0x0021,UC_X86_REG_BX:0x1234,UC_X86_REG_CX:0x0042,
               UC_X86_REG_DX:0x0031,UC_X86_REG_SI:0x5678,UC_X86_REG_DI:0x6789,
               UC_X86_REG_BP:0x789a,UC_X86_REG_DS:0x5000,UC_X86_REG_ES:0x5100}
        for reg,value in saved.items():machine.reg_write(reg,value)
        for reg,value in ((UC_X86_REG_CS,CODE),(UC_X86_REG_SS,stack),
                          (UC_X86_REG_SP,SP),(UC_X86_REG_EFLAGS,flags)):
            machine.reg_write(reg,value)
        callbacks=[];stops=[]

        def instruction(cpu,address,_size,_data):
            if address in (CODE*16+CALLBACK,C_CODE*16+CALLBACK):
                callbacks.append(address)
                self.assertEqual(cpu.reg_read(UC_X86_REG_CS),segment)
                self.assertEqual(cpu.reg_read(UC_X86_REG_SS),DATA)
                current=cpu.reg_read(UC_X86_REG_SP)+(4 if far else 2)
                mode,offset,selector=struct.unpack('<3H',cpu.mem_read(DATA*16+current,6))
                self.assertEqual(mode,0x26 if write else 0x25)
                self.assertEqual((offset,selector),(SP-22,stack))
                frame=struct.unpack('<13H',cpu.mem_read(stack*16+offset,26))
                self.assertEqual(frame[:5],tuple(saved[r] for r in
                    (UC_X86_REG_ES,UC_X86_REG_DS,UC_X86_REG_DI,UC_X86_REG_SI,UC_X86_REG_BP)))
                self.assertEqual(frame[6:10],tuple(saved[r] for r in
                    (UC_X86_REG_BX,UC_X86_REG_DX,UC_X86_REG_CX,UC_X86_REG_AX)))
                self.assertEqual(frame[11:],(STOP,CALLER))
            if address==CALLER*16+STOP:
                stops.append(address);cpu.emu_stop()

        machine.hook_add(UC_HOOK_CODE,instruction)
        machine.emu_start(CODE*16+entry,0,count=1000)
        self.assertEqual(len(callbacks),1);self.assertEqual(len(stops),1)
        self.assertEqual(machine.reg_read(UC_X86_REG_SS),stack)
        self.assertEqual(machine.reg_read(UC_X86_REG_SP),SP+4)
        self.assertEqual(struct.unpack('<H',machine.mem_read(stack*16+SP+4,2))[0],flags)
        self.assertEqual(machine.reg_read(UC_X86_REG_AX),0xbeef)
        self.assertEqual(machine.reg_read(UC_X86_REG_EFLAGS)&1,int(carry))
        for reg,value in saved.items():
            if reg!=UC_X86_REG_AX:self.assertEqual(machine.reg_read(reg),value)

    def test_far_callback_and_legacy_flags_word(self):
        for write in (False,True):
            for same_stack in (False,True):
                for carry in (False,True):
                    with self.subTest(write=write,same_stack=same_stack,carry=carry):
                        self.execute(True,write,same_stack,carry)

    def test_non_va_near_callback_and_legacy_flags_word(self):
        for write in (False,True):
            for same_stack in (False,True):
                for carry in (False,True):
                    with self.subTest(write=write,same_stack=same_stack,carry=carry):
                        self.execute(False,write,same_stack,carry)


if __name__=='__main__':
    unittest.main()
