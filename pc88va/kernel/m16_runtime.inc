; SPDX-License-Identifier: GPL-2.0-or-later
; Runtime placement for the matched M16 loader and split external-ring carrier.
%include "m16_memory_probe.inc"
%macro M13_MOV_IMAGE 2
    mov %1, %2
%ifdef M16_BOOT_RECORD_OFFSET
    add %1, [cs:m16_image_delta]
%endif
%endmacro
%macro M13_MOV_FILE 1
%ifdef M16_BOOT_RECORD_OFFSET
    mov %1, [cs:m16_work_file]
%else
    mov %1, M13_FILE_SEG
%endif
%endmacro
%macro M13_MOV_RING 1
%ifdef M16_BOOT_RECORD_OFFSET
    mov %1, [cs:m16_work_ring]
%else
    mov %1, M13_RING_SEG
%endif
%endmacro
%macro M13_MOV_STACK 1
%ifdef M16_BOOT_RECORD_OFFSET
    mov %1, [cs:m16_work_stack]
%else
    mov %1, M13_BRIDGE_STACK_SEG
%endif
%endmacro
%macro M16_RUNTIME_CODE 0
m16_prepare:
    mov [cs:m13_saved_dx], dx
    mov [cs:m16_saved_file_segment], cx
    ; AX is the loader's measured KiB; CX and CS identify the in-place
    ; carrier. Validate this handoff without using the four-byte MZ stack.
    cmp ax, 256
    jb .invalid
    cmp ax, 640
    ja .invalid
    mov si, cx
    mov cl, 6
    shl ax, cl
    mov dx, ax
    sub ax, 1900h
    cmp ax, si
    jne .invalid
    mov cx, cs
    cmp ax, cx
    jne .invalid
    mov [cs:m16_work_file], ax
    add ax, 1100h
    mov [cs:m16_work_ring], ax
    sub ax, 100h
    mov [cs:m16_work_stack], ax
    mov ss, ax
    mov sp, M13_BRIDGE_STACK_SP
    or bx, bx
    jnz .selected
    mov bx, M13_IMAGE_SEG
.selected:
    cmp bx, 1000h
    jb .invalid
    mov ax, bx
    sub ax, M13_IMAGE_SEG
    mov [cs:m16_image_delta], ax
    ; Final resident code/data start at BX and grow upward. The initial
    ; expanded image (including its bootstrap stack) must end before the
    ; compressed carrier. INIT is temporary and follows the RAM-top-relative
    ; workspace plan, independently of the resident base.
    mov ax, bx
    add ax, M16_LOW_IMAGE_END_PARAS
    jc .invalid
    cmp ax, [cs:m16_work_file]
    ja .invalid
    ; The builder qualifies INIT and its stack against the 256 KiB workspace.
    ; Translate that complete temporary plan by measured RAM minus 256 KiB.
    mov ax, dx
    sub ax, 4000h
    sub ax, [cs:m16_image_delta]
    mov [cs:m16_init_delta], ax
.ready:
    mov dx, [cs:m13_saved_dx]
    jmp m13_unpack_start_ready
.invalid:
    push cs
    pop ds
    mov si, m16_placement_error
    mov dx, 8000h
    mov ah, 02h
    int 83h
    ; Leave a distinct status for bounded emulator diagnostics. No target
    ; image has been written when a placement request is rejected.
    mov ax, 01601h
.halt:
    cli
    hlt
    jmp .halt
m16_fill_layout:
    mov bx, [cs:m16_image_delta]
    add word [es:M16_LAYOUT_RECORD_OFFSET+8], bx
    add word [es:M16_LAYOUT_RECORD_OFFSET+10], bx
    add word [es:M16_LAYOUT_RECORD_OFFSET+12], bx
    add word [es:M16_LAYOUT_RECORD_OFFSET+16], bx
    mov bx, [cs:m16_init_delta]
    add word [es:M16_LAYOUT_RECORD_OFFSET+12], bx
    add word [es:M16_LAYOUT_RECORD_OFFSET+16], bx
    mov ax, [cs:m16_saved_file_segment]
    mov [es:M16_BOOT_RECORD_OFFSET+8], ax
    mov ax, [cs:m16_work_file]
    mov [es:M16_BOOT_RECORD_OFFSET+10], ax
    mov ax, [cs:m16_work_stack]
    mov [es:M16_BOOT_RECORD_OFFSET+12], ax
    mov [es:M16_BOOT_RECORD_OFFSET+16], ax
    mov ax, [cs:m16_work_ring]
    mov [es:M16_BOOT_RECORD_OFFSET+14], ax
    ret
m16_image_delta: dw 0
m16_init_delta: dw 0
m16_work_file: dw M13_FILE_SEG
m16_work_ring: dw M13_RING_SEG
m16_work_stack: dw M13_BRIDGE_STACK_SEG
m16_placement_error: db 'PC88VA_LOADSEG: invalid or overlapping RAM layout', 13, 10, 0
%endmacro
