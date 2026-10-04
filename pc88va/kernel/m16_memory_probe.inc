; SPDX-License-Identifier: GPL-2.0-or-later
; One-byte 00h/FFh sampling per KiB; AX returns measured contiguous KiB.
%ifndef PC88VA_M16_MEMORY_PROBE
%define PC88VA_M16_MEMORY_PROBE 1
%macro PC88VA_MEASURE_RAM 0
pushf
        cli
        push bx
        push cx
        push dx
        push si
        push es

        mov ax, 03fffh
        mov es, ax
        mov si, 000fh
        xor cx, cx
        call %%memory_sample
        jc %%memory_done

        mov cx, 256
        mov ax, 04000h
        mov es, ax
        xor si, si
%%memory_probe:
        call %%memory_sample
        jc %%memory_done
        inc cx
        cmp cx, 640
        jae %%memory_done
        mov ax, es
        add ax, 64
        mov es, ax
        jmp short %%memory_probe

%%memory_done:
        mov ax, cx
        pop es
        pop si
        pop dx
        pop cx
        pop bx
        popf
        jmp %%memory_end

%%memory_sample:
        mov bl, [es:si]
        mov byte [es:si], 00h
        cmp byte [es:si], 00h
        jne %%memory_sample_failed
        mov byte [es:si], 0ffh
        cmp byte [es:si], 0ffh
        jne %%memory_sample_failed
        mov [es:si], bl
        clc
        ret
%%memory_sample_failed:
        mov [es:si], bl
        stc
        ret
%%memory_end:
%endmacro
%endif
