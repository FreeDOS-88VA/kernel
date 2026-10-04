; SPDX-License-Identifier: GPL-2.0-or-later
; Near platform calls and CS-relative state share one explicit code frame.
; Never let automatic packing separate CON from the M10/M11/M12 services.
bits 16
cpu 8086
%include "kernel/m13_segments.inc"
%include "../kernel/segs.inc"
segment _DATA
global _m13_layout
_m13_layout:
        db 'M13PLAN1'
        times 8 dw 0
global _m16_boot_layout
_m16_boot_layout:
        db 'M16BOOT1'
        times 6 dw 0
