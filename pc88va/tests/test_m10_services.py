#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""ROM-free instruction tests of the real assembled M10 service source."""
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from unicorn import Uc, UC_ARCH_X86, UC_MODE_16, UC_HOOK_INTR, UC_HOOK_INSN, UC_HOOK_MEM_WRITE
from unicorn.x86_const import *

TARGET = Path(__file__).resolve().parents[1]
NAMES = ['pc88va_machine_init_', 'pc88va_memory_query_', 'pc88va_interrupts_init_',
         'pc88va_clock_read_', 'pc88va_fatal_stop_request_', 'pc88va_m10_memory_record_',
         'pc88va_m10_clock_record_', 'pc88va_m10_state_', 'm10_ticks', 'm10_clock_busy',
         'm10_arena', 'm10_arena_end', 'pc88va_m10_halt', 'm10_storage_end', 'm10_clock_origin']
CODE, STACK, STOP = 0x1000, 0x1800, 0xff00


class ServicesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        scratch = TARGET/'build/m10-tests'
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as name:
            root = Path(name)
            source = root/'test.asm'
            source.write_text('bits 16\ncpu 8086\norg 0\n' +
                '\n'.join('dw '+symbol for symbol in NAMES)+'\n'+
                '%define M10_FLAT_TEST 1\n%define CONSOLE_FLAT_TEST 1\n'
                '%define M10_VISIBLE_DIAGNOSTICS 1\n'+
                '%include "console.asm"\n%include "machine_services.asm"\n')
            subprocess.run(['nasm','-f','bin','-DPC88VA','-I',str(TARGET/'kernel')+'/',
                            '-o',str(root/'test.bin'),str(source)],check=True,capture_output=True)
            cls.binary = (root/'test.bin').read_bytes()
        cls.symbols = dict(zip(NAMES,struct.unpack_from('<'+'H'*len(NAMES),cls.binary)))

    def setUp(self):
        self.cpu = Uc(UC_ARCH_X86,UC_MODE_16)
        self.cpu.mem_map(0,0x100000)
        self.cpu.mem_write(CODE*16,self.binary)
        self.cpu.mem_write(0x83*4,struct.pack('<HH',0x100,0x8000))
        self.status = None
        self.reads, self.outputs, self.writes, self.printed = [], [], [], []
        self.masks = {0x186:0x57,0x18a:0xad,0x152:0x12,0x153:0x41}
        self.change_vector = False
        def port_in(cpu,port,size,data):
            self.assertEqual(size,1)
            self.reads.append(port)
            if port in self.masks:return self.masks[port]
            self.assertEqual(port,0x40)
            if self.status is not None:return self.status
            return 0xe0 if self.reads.count(0x40)%2==0 else 0xc0
        def port_out(cpu,port,size,value,data):self.outputs.append((port,size,value))
        def interrupt(cpu,number,data):
            self.assertEqual(number,0x83)
            self.assertEqual(cpu.reg_read(UC_X86_REG_AH),2)
            self.assertEqual(cpu.reg_read(UC_X86_REG_DX),0x8000)
            address=cpu.reg_read(UC_X86_REG_DS)*16+cpu.reg_read(UC_X86_REG_SI)
            self.printed.append(cpu.mem_read(address,1)[0])
            if self.change_vector:cpu.mem_write(0x83*4,b'\x01\x02\x03\x04')
        self.cpu.hook_add(UC_HOOK_INSN,port_in,None,1,0,UC_X86_INS_IN)
        self.cpu.hook_add(UC_HOOK_INSN,port_out,None,1,0,UC_X86_INS_OUT)
        self.cpu.hook_add(UC_HOOK_INTR,interrupt)
        self.cpu.hook_add(UC_HOOK_MEM_WRITE,lambda cpu,access,address,size,value,data:
                          self.writes.append((address,size)))

    def data(self,symbol,size):return bytes(self.cpu.mem_read(CODE*16+self.symbols[symbol],size))
    def put(self,symbol,value):self.cpu.mem_write(CODE*16+self.symbols[symbol],value)

    def call(self,name,arg=0,flags=2,ds=CODE,stack=STACK,fatal=False,sp=0x0ffe):
        regs={UC_X86_REG_BX:0x1234,UC_X86_REG_CX:0x2345,UC_X86_REG_DX:0x3456,
              UC_X86_REG_SI:0x4567,UC_X86_REG_DI:0x5678,UC_X86_REG_BP:0x6789,
              UC_X86_REG_DS:ds,UC_X86_REG_ES:CODE,UC_X86_REG_SS:stack,
              UC_X86_REG_EFLAGS:flags}
        for reg,value in regs.items():self.cpu.reg_write(reg,value)
        self.cpu.reg_write(UC_X86_REG_CS,CODE)
        self.cpu.reg_write(UC_X86_REG_SP,sp)
        self.cpu.reg_write(UC_X86_REG_AX,arg)
        self.cpu.mem_write(stack*16+sp,struct.pack('<H',STOP))
        self.cpu.emu_start(CODE*16+self.symbols[name],CODE*16+STOP,count=2000000)
        self.assertEqual(self.outputs,[],'no controller, disk or keyboard output')
        if not fatal:
            self.assertEqual(self.cpu.reg_read(UC_X86_REG_IP),STOP,'bounded near return')
            self.assertEqual(self.cpu.reg_read(UC_X86_REG_SP),sp+2)
            for reg,value in regs.items():self.assertEqual(self.cpu.reg_read(reg),value)
        return self.cpu.reg_read(UC_X86_REG_AX)

    def test_init_success_and_single_shot(self):
        self.assertEqual(self.call(NAMES[0]),0)
        self.assertEqual(self.data('pc88va_m10_state_',1),b'\x02')
        self.assertEqual(bytes(self.printed),b'M10 INIT OK\r\n')
        self.assertEqual(self.data('m10_ticks',4),struct.pack('<I',1))
        previous=bytes(self.cpu.mem_read(CODE*16,len(self.binary)))
        self.assertEqual(self.call(NAMES[0]),0xffff)
        self.assertEqual(bytes(self.cpu.mem_read(CODE*16,len(self.binary))),previous)
        for address,size in self.writes:
            self.assertTrue(CODE*16<=address and address+size<=CODE*16+len(self.binary)
                            or STACK*16<=address and address+size<=STACK*16+4096)

    def test_entry_if_df_and_stack_failure(self):
        for flags in (0x202,0x402,0x602):
            self.assertEqual(self.call(NAMES[0],flags=flags),0xffff)
        self.assertEqual(self.call(NAMES[0],stack=0xa000),0xffff)
        self.assertEqual(self.printed,[])

    def test_linker_intra_paragraph_stack_boundary(self):
        end=self.symbols['m10_storage_end']
        self.assertEqual(self.call(NAMES[0],stack=CODE+end//16,sp=0x0ffe+end%16),0)
        self.assertEqual(self.data(NAMES[7],1),b'\x02')

    def test_stack_top_overflow_is_not_accepted(self):
        self.assertEqual(self.call(NAMES[0],sp=0xfffc),0xffff)
        self.assertEqual(self.data(NAMES[7],1),b'\x03')

    def test_memory_partition(self):
        self.assertEqual(self.call(NAMES[1],self.symbols[NAMES[5]]),0)
        record=self.data(NAMES[5],34)
        self.assertEqual(struct.unpack_from('<HH',record),(1,3))
        rows=[struct.unpack_from('<IIH',record,4+10*i) for i in range(3)]
        self.assertEqual(rows[0][0],0)
        self.assertEqual(rows[-1][1],0x100000)
        self.assertEqual([r[2] for r in rows],[0,1,0])
        self.assertEqual(rows[0][1],rows[1][0])
        self.assertEqual(rows[1][1],rows[2][0])
        self.assertEqual(rows[1][1]-rows[1][0],256)
        self.assertTrue(all(start<end for start,end,_ in rows))

    def test_invalid_records_and_segments_are_unchanged(self):
        for service,record in ((NAMES[1],NAMES[5]),(NAMES[3],NAMES[6])):
            for pointer,ds in ((0,CODE),(0xffff,CODE),(self.symbols[record],CODE+1)):
                before=bytes(self.cpu.mem_read(CODE*16,len(self.binary)))
                self.assertEqual(self.call(service,pointer,ds=ds),0xffff)
                self.assertEqual(bytes(self.cpu.mem_read(CODE*16,len(self.binary))),before)

    def test_interrupt_adoption_and_drift(self):
        ivt=bytes(self.cpu.mem_read(0,1024))
        self.assertEqual(self.call(NAMES[2]),0)
        self.assertEqual(bytes(self.cpu.mem_read(0,1024)),ivt)
        self.assertEqual(self.call(NAMES[2]),0)
        self.masks[0x186]^=1
        self.assertEqual(self.call(NAMES[2]),0xffff)

    def test_missing_firmware_vector(self):
        self.cpu.mem_write(0x83*4,b'\0'*4)
        self.assertEqual(self.call(NAMES[2]),0xffff)
        self.assertEqual(self.call(NAMES[0]),0xffff)
        self.assertEqual(self.data(NAMES[7],1),b'\x03')
        self.assertEqual(self.data(NAMES[5],2),b'\0\0')

    def test_post_console_vector_drift_prevents_commit(self):
        self.change_vector=True
        self.assertEqual(self.call(NAMES[0]),0xffff)
        self.assertEqual(self.data(NAMES[7],1),b'\x03')
        self.assertEqual(self.data(NAMES[5],2),b'\0\0')
        self.assertEqual(self.data(NAMES[6],2),b'\0\0')

    def test_clock_order_carry_and_wrap(self):
        self.put('m10_clock_origin',b'\x01')
        for initial in (0,0xffff,0xffffffff):
            self.put('m10_ticks',struct.pack('<I',initial))
            self.assertEqual(self.call(NAMES[3],self.symbols[NAMES[6]]),0)
            self.assertEqual(struct.unpack('<HI',self.data(NAMES[6],6)),(1,(initial+1)&0xffffffff))

    def test_clock_source_failure_no_fabricated_progress(self):
        self.put('m10_clock_origin',b'\x01')
        for status in (0,0xff,0xc0,0xe0):
            self.status=status
            before=self.data('m10_ticks',4),self.data(NAMES[6],6)
            self.assertEqual(self.call(NAMES[3],self.symbols[NAMES[6]]),0xffff)
            self.assertEqual((self.data('m10_ticks',4),self.data(NAMES[6],6)),before)

    def test_initial_source_sample_is_origin_not_fabricated_progress(self):
        self.assertEqual(self.call(NAMES[3],self.symbols[NAMES[6]]),0)
        self.assertEqual(struct.unpack('<HI',self.data(NAMES[6],6)),(1,0))
        self.assertEqual(self.call(NAMES[3],self.symbols[NAMES[6]]),0)
        self.assertEqual(struct.unpack('<HI',self.data(NAMES[6],6)),(1,1))

    def test_clock_reentrancy(self):
        self.put('m10_clock_busy',b'\x01')
        self.assertEqual(self.call(NAMES[3],self.symbols[NAMES[6]]),0xffff)
        self.assertEqual(self.reads,[])

    def test_clock_failure_rolls_back_initialization(self):
        self.status=0
        self.assertEqual(self.call(NAMES[0]),0xffff)
        self.assertEqual(self.data(NAMES[7],1),b'\x03')
        self.assertEqual(self.printed,[])
        self.assertEqual(self.data(NAMES[5],2),b'\0\0')

    def test_fatal_nonreturn_cli_hlt_no_diagnostic(self):
        self.call(NAMES[4],0xbeef,flags=0x202,fatal=True)
        self.assertEqual(self.cpu.reg_read(UC_X86_REG_EFLAGS)&0x200,0)
        self.assertEqual(self.cpu.reg_read(UC_X86_REG_IP),self.symbols['pc88va_m10_halt']+1)
        self.assertEqual(self.cpu.reg_read(UC_X86_REG_SP),0x0ffe)
        self.assertEqual(self.printed,[])
        self.assertEqual(self.reads,[])


if __name__=='__main__':unittest.main()
