#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Execute the production CLOCK$ driver with an independent native counter.

The counter advances in native whole seconds. No IBM BIOS, private clock
register, calendar input, or firmware implementation is needed by this test.
"""
import ctypes
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]


class ClockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source=(ROOT/'kernel/sysclk.c').read_text()
        source=source.replace('#include "portab.h"','').replace('#include "globals.h"','')
        cls.directory=tempfile.TemporaryDirectory(prefix='m15-clock-')
        path=Path(cls.directory.name)
        shim=r'''
#include <stdint.h>
#include <string.h>
#define PC88VA 1
#define ASM
#define ASMCFUNC
#define FAR
#define STATIC static
typedef uint8_t BYTE;
typedef uint16_t UWORD;
typedef uint16_t WORD;
typedef uint32_t UDWORD;
#define C_INIT 0
#define C_INPUT 4
#define C_OUTPUT 8
#define C_OFLUSH 11
#define C_IFLUSH 7
#define C_OUB 12
#define C_NDREAD 5
#define C_OSTAT 10
#define C_ISTAT 6
#define S_DONE 0x100
#define E_LENGTH 5
#define E_FAILURE 12
#define failure(e) (0x8100|(e))
#define fmemcpy memcpy
struct ClockRecord { UWORD clkDays; BYTE clkMinutes,clkHours,clkHundredths,clkSeconds; };
typedef struct { WORD r_command,r_count,r_nunits; void *r_trans; } *rqptr;
static UDWORD source_ticks;
static UDWORD ReadPCClock(void) { return source_ticks; }
static void WritePCClock(UDWORD ticks) { (void)ticks; }
static void WriteATClock(BYTE *date,BYTE hours,BYTE minutes,BYTE seconds) {
    (void)date;(void)hours;(void)minutes;(void)seconds;
}
static const UWORD *is_leap_year_monthdays(UWORD year) {
    static const UWORD days[2][13] = {
      {0,31,59,90,120,151,181,212,243,273,304,334,365},
      {0,31,60,91,121,152,182,213,244,274,305,335,366}};
    return days[!(year%4) && (year%100 || !(year%400))];
}
'''
        exports=r'''
static struct ClockRecord record;
void native_time(unsigned seconds) {
    source_ticks=(UDWORD)((uint64_t)seconds*1193180/65536);
}
unsigned query(void) {
    struct { WORD r_command,r_count,r_nunits; void *r_trans; } request;
    request.r_command=C_INPUT; request.r_count=sizeof(record); request.r_trans=&record;
    if(clk_driver((rqptr)&request)!=S_DONE) return 0xffffffff;
    return ((record.clkHours*60u+record.clkMinutes)*60u+record.clkSeconds)*100u+record.clkHundredths;
}
unsigned day(void) { return record.clkDays; }
void set(unsigned days,unsigned centiseconds) {
    struct { WORD r_command,r_count,r_nunits; void *r_trans; } request;
    record.clkDays=days;
    record.clkHours=centiseconds/360000;
    record.clkMinutes=centiseconds/6000%60;
    record.clkSeconds=centiseconds/100%60;
    record.clkHundredths=centiseconds%100;
    request.r_command=C_OUTPUT; request.r_count=sizeof(record); request.r_trans=&record;
    clk_driver((rqptr)&request);
}
'''
        cls.code=shim+source+exports
        cls.path=path
        cpath=path/'clock.c';cpath.write_text(cls.code)
        compiled=subprocess.run(['gcc','-shared','-fPIC','-Wall','-Wextra','-Werror',
                                 '-Wno-unused-function',str(cpath),'-o',str(path/'clock.so')],
                                capture_output=True,text=True)
        if compiled.returncode:
            raise RuntimeError('Clock test compiler failed: '+compiled.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def setUp(self):
        # A separate shared-object path resets all production static state.
        path=self.path/(self.id().split('.')[-1]+'.so')
        shutil.copyfile(self.path/'clock.so',path)
        self.lib=ctypes.CDLL(str(path))
        self.lib.query.restype=ctypes.c_uint

    def assert_time(self,actual,expected):
        self.assertLessEqual(abs(actual-expected),6)

    def test_set_and_progression_from_independent_source(self):
        lib=self.lib
        lib.native_time(3600);self.assert_time(lib.query(),360000)
        lib.set(16130,4529600);self.assert_time(lib.query(),4529600)
        lib.native_time(3603);self.assert_time(lib.query(),4529900)
        self.assertEqual(lib.day(),16130)

    def test_logical_midnight_increments_date_once(self):
        lib=self.lib
        lib.native_time(100);lib.query();lib.set(1000,8639800)
        lib.native_time(103);self.assert_time(lib.query(),100)
        self.assertEqual(lib.day(),1001)
        self.assert_time(lib.query(),100);self.assertEqual(lib.day(),1001)

    def test_source_midnight_preserves_logical_date_offset(self):
        lib=self.lib
        lib.native_time(86399);lib.query();lib.set(2000,1000000)
        lib.native_time(1);self.assert_time(lib.query(),1000200)
        self.assertEqual(lib.day(),2000)

    def test_date_reset_and_fractional_time_are_not_lost(self):
        lib=self.lib
        lib.native_time(1000);lib.query();lib.set(0,1234567)
        self.assert_time(lib.query(),1234567);self.assertEqual(lib.day(),0)
        lib.set(43829,8639900);lib.native_time(1002)
        self.assert_time(lib.query(),100);self.assertEqual(lib.day(),43830)


if __name__=='__main__':
    unittest.main()
