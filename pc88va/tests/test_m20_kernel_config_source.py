#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""The PC-88VA INIT copies its kernel configuration from LowKernelConfig.

_LowKernelConfig is linked at 0000:0002 of the kernel image. That is an
image-relative link address: at run time the resident kernel starts at
PC88VA_LOADSEG, and physical 0000:0002 is inside the interrupt vector
table, whose firmware-dependent bytes must not become SkipConfigSeconds,
BootHarddiskSeconds or the drive-assignment and LBA options.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]


def pc88va_config_copy(text):
    start = text.index('drv = LoL->BootDrive + 1;')
    block = text[start:text.index('#else', start)]
    if '#if defined(PC88VA)' not in block:
        raise AssertionError('PC88VA configuration copy branch not found')
    return block


class KernelConfigSourceTests(unittest.TestCase):
    def test_copy_reads_the_linked_configuration_symbol(self):
        block = pc88va_config_copy((ROOT / 'kernel/main.c').read_text())
        self.assertRegex(block, r'BYTE FAR \*source = \(BYTE FAR \*\)&LowKernelConfig;')
        self.assertIsNone(re.search(r'MK_FP\(\s*0\s*,\s*(2|0x0*2)\s*\)', block))
        self.assertIn('sizeof(InitKernelConfig)', block)

    def test_configuration_area_is_the_kernel_image_start(self):
        asm = (ROOT / 'kernel/kernel.asm').read_text()
        entry = asm.index('entry:')
        self.assertLess(asm.index('jmp short realentry', entry), asm.index('_LowKernelConfig:', entry))
        area = asm[asm.index('_LowKernelConfig:'):asm.index('configend:')]
        self.assertIn("db 'CONFIG'", area)
        self.assertRegex(area, r'SkipConfigSeconds\s+db 2')


if __name__ == '__main__':
    unittest.main()
