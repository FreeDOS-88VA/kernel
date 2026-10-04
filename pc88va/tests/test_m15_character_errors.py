#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Keep selected FreeDOS character-device error and retry behavior stable."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest
from test_m14_media_lifetime import function

ROOT = Path(__file__).resolve().parents[2]
HEADER = r'''
#include <assert.h>
#include <stddef.h>
#include <stdlib.h>
#define STATIC static
#define FAR
#define SUCCESS 0
#define S_ERROR 0x8000
#define DE_ACCESS -5
#define DE_INVLDACC -12
#define ABORT 2
#define FAIL 3
#define CONTINUE 0
#define RETRY 1
struct dhdr { int marker; };
typedef struct { unsigned r_command,r_unit,r_status,r_length,r_count;
    void *r_trans; } request;
static request CharReqHdr;
static unsigned calls, response;
static void execrh(request *r, struct dhdr *d) {
    assert(d->marker==123 && r->r_unit==0 && r->r_command==4);
    assert(r->r_length==sizeof(request));
    ++calls;
    if (calls==1) { r->r_status=S_ERROR; return; }
    assert(response==RETRY && r->r_count==1);
    r->r_status=0;
    *(unsigned char *)r->r_trans='R';
}
static int char_error(request *r, struct dhdr *d) {
    assert(r->r_status&S_ERROR); assert(d->marker==123);
    return response;
}
'''
FOOTER = r'''
int main(int argc, char **argv) {
    struct dhdr dev={123}, *p=&dev;
    unsigned char buffer[3]={0xaa,0xcc,0x55};
    long result;
    assert(argc==2); response=(unsigned)atoi(argv[1]);
    result=BinaryCharIO(&p,1,buffer+1,4);
    assert(buffer[0]==0xaa && buffer[2]==0x55);
    if (response==RETRY) {
        assert(result==1 && calls==2 && buffer[1]=='R');
    } else {
        assert(result==(response==FAIL ? DE_INVLDACC : 0));
        assert(calls==1 && buffer[1]==0xcc);
    }
    return 0;
}
'''

class CharacterErrorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        root = Path(cls.tmp.name)
        source = (ROOT / 'kernel/chario.c').read_text(encoding='latin-1')
        probe = root / 'probe.c'
        probe.write_text(HEADER + function(source, 'STATIC int CharRequest') +
                         function(source, 'long BinaryCharIO') + FOOTER)
        cls.binary = root / 'probe'
        built = subprocess.run([os.environ.get('CC','cc'), '-std=c99', '-Wall',
                                '-Wextra', '-Werror', str(probe), '-o', str(cls.binary)],
                               capture_output=True, text=True)
        if built.returncode:
            raise RuntimeError(built.stdout + built.stderr)

    def run_case(self, response):
        result = subprocess.run([str(self.binary),str(response)],
                                capture_output=True,text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_fail_returns_upstream_error_without_writing_buffer(self): self.run_case(3)
    def test_retry_reissues_the_real_request_then_returns_count(self): self.run_case(1)
    def test_allowed_ignore_reports_zero_transfer(self): self.run_case(0)

if __name__=='__main__': unittest.main()
