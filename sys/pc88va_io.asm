; SPDX-License-Identifier: GPL-2.0-or-later
; Small-model cdecl helpers for the prepared-floppy SYS backend.
bits 16
cpu 8086
segment _TEXT public class=CODE use16
global _va_absolute, va_critical_
_va_absolute:
        push bp
        mov bp, sp
        push bx
        push cx
        push dx
        push si
        push di
        push ds
        push es
        xor ax, ax              ; Qualified local floppy A: only.
        mov bx, [bp+8]          ; Near buffer in DS.
        mov cx, 1              ; One logical sector, not a byte count.
        mov dx, [bp+6]
        cmp word [bp+4], 0
        jne .write
        int 25h
        jmp short .returned
.write:
        int 26h
.returned:
        pop dx                  ; DOS leaves the original FLAGS on the stack.
        jc .done
        xor ax, ax
.done:
        pop es
        pop ds
        pop di
        pop si
        pop dx
        pop cx
        pop bx
        pop bp
        ret
va_critical_:
        mov al, 3               ; Return Fail; do not recurse into DOS.
        iret
