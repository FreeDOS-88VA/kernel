; SPDX-License-Identifier: GPL-2.0-or-later
; Open Watcom small-model register-call adapters for the shared M08 cores.
bits 16
cpu 8086
%ifdef PC88VA_M13
%include "kernel/m13_segments.inc"
segment M13_PLATFORM_TEXT
%else
segment _TEXT class=CODE public use16
%endif
global pc88va_disk_read_
global pc88va_loader_handoff_
global pc88va_disk_read_marker
global pc88va_loader_handoff_marker

; A single near pointer is passed in AX under the accepted Watcom convention.
; Returning errors/success use AX; all other registers remain unchanged.
pc88va_disk_read_:
    push si
    mov si, ax
    call pc88va_disk_read_core
    pop si
    ret

pc88va_loader_handoff_:
    push si
    mov si, ax
    call pc88va_loader_handoff_core
    pop si
    ret

pc88va_disk_read_marker:
    db 'M08SERVICE:DISK_READ:PARAMETERIZED', 0
pc88va_loader_handoff_marker:
    db 'M08SERVICE:LOADER_HANDOFF:ZERO_RELOCATION_MZ', 0

%include "disk_read.inc"
%include "loader_handoff.inc"
