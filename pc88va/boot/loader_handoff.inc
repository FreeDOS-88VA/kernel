; SPDX-License-Identifier: GPL-2.0-or-later
; One-way, zero-relocation MZ handoff. No firmware or machine-specific address.
bits 16
cpu 8086
    jmp pc88va_loader_handoff_core
%include "mz_transform.inc"

pc88va_loader_handoff_core:
    pushf
    push bx
    push cx
    push dx
    push si
    push di
    push bp
    push es
    cmp si, 65536-MZ_CONTEXT_SIZE
    ja .contract
    ; A far-return frame uses four bytes below the declared entry SP.
    cmp word [si+MZ_STACK_RESERVE], 4
    jb .contract
    call pc88va_mz_transform_core
    or ax, ax
    jnz .restore
    mov ax, [si+MZ_LOAD_SEGMENT]
    mov bx, [si+MZ_ENTRY_CS]
    mov cx, [si+MZ_ENTRY_IP]
    mov dx, [si+MZ_DRIVE_CONTEXT]
    mov di, [si+MZ_STACK_SP]
    mov bp, [si+MZ_STACK_SS]
    ; Establish IF=DF=0 on the old, validated loader stack. All following
    ; instructions preserve FLAGS. The new stack holds only the far frame.
    push ax
    mov ax, 2
    push ax
    popf
    pop ax
    mov ss, bp
    mov sp, di
    push bx
    push cx
%ifdef PC88VA_RUNTIME_LOADSEG
    ; BX selects the expanded image base (zero means profile default).
    ; CX reports the measured-RAM-derived file staging segment for startup diagnostics.
    mov bx, [pc88va_cfg_value]
    mov cx, [si+MZ_FILE_SEGMENT]
%endif
    mov ds, ax
    mov es, ax
%ifdef PC88VA_RUNTIME_LOADSEG
    mov ax, [cs:pc88va_stage2_measured_kb]
%else
    mov ax, 0
%endif
%ifndef PC88VA_RUNTIME_LOADSEG
    mov bx, 0
%endif
%ifndef PC88VA_RUNTIME_LOADSEG
    mov cx, 0
%endif
    mov si, 0
    mov di, 0
    mov bp, 0
    retf
.contract:
    mov ax, MZ_CONTRACT
.restore:
    pop es
    pop bp
    pop di
    pop si
    pop dx
    pop cx
    pop bx
    popf
    stc
    ret
