; SPDX-License-Identifier: GPL-2.0-or-later
; Boot-only model display. Code and strings share the discardable INIT group.
; Public interface precedent: VAEG generic/np2info.c (ROMTPVA),
; io/memctrlva.c and io/va91.c at 62a597f0ee81e2e036af740a3e79ad3da83e3fb7.
bits 16
cpu 8086
segment M13_INIT_TEXT class=M13INIT public align=16 use16
group M13_INIT_GROUP M13_INIT_TEXT

global _pc88va_print_model
extern pc88va_diag_putc_

_pc88va_print_model:
        pushf
        push ax
        push bx
        push dx
        push si
        push es
        ; Select internal ROM1 bank zero without changing ROM0, then restore
        ; the complete bank register before interrupts or console firmware.
        pushf
        cli
        mov dx, 0152h
        in al, dx
        mov bl, al
        and al, 0fh
        out dx, al
        mov ax, 0f000h
        mov es, ax
        mov ax, [es:0fffeh]
        mov si, ax
        mov al, bl
        out dx, al
        popf
        cmp si, 0fffeh
        je .va2
        cmp si, 0ffffh
        jne .unknown
        mov dx, 0156h
        in al, dx
        test al, 80h
        jz .upgrade
        mov si, model_va
        jmp short .print
.va2:
        mov si, model_va2
        jmp short .print
.upgrade:
        mov si, model_upgrade
        jmp short .print
.unknown:
        mov si, model_unknown
.print:
        xor ax, ax
        mov al, [cs:si]
        inc si
        or al, al
        jz .done
        call seg pc88va_diag_putc_:pc88va_diag_putc_
        jmp short .print
.done:
        pop es
        pop si
        pop dx
        pop bx
        pop ax
        popf
        retf

model_va:      db 'Machine = VA',13,10,0
model_va2:     db 'Machine = VA2/3',13,10,0
model_upgrade: db 'Machine = VA + verup board (PC-88VA-91)',13,10,0
model_unknown: db 'Machine = Unknown',13,10,0
