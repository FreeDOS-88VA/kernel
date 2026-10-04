; SPDX-License-Identifier: GPL-2.0-or-later
; M10: conservative arena, read-only interrupt adoption, observed VRTC clock.
bits 16
cpu 8086
%ifndef PC88VA
%error PC88VA selector is required
%endif
%ifdef NEC98
%error Mixed machine selectors
%endif
%ifdef IBMPC
%error Mixed machine selectors
%endif

%ifndef M10_FLAT_TEST
; Keep the resident machine-service segment close to the loader-owned stack
; arena.  The M10 contract intentionally rejects a stack/code separation of
; one megabyte or more; placing this code in the dedicated CODE segment keeps
; the validated SS:CS relationship while the CON dispatch table remains in
; LGROUP.
%ifdef PC88VA_M13
%include "kernel/m13_segments.inc"
segment M13_PLATFORM_TEXT
%else
segment _TEXT class=CODE public use16
%endif
extern pc88va_console_putc_
%endif

global pc88va_machine_init_, pc88va_machine_init_far_
global pc88va_memory_query_, pc88va_interrupts_init_
global pc88va_clock_read_, pc88va_fatal_stop_request_
global pc88va_m10_memory_record_, pc88va_m10_clock_record_
global pc88va_m10_state_, pc88va_m10_control_
global pc88va_m10_i2, pc88va_m10_i3, pc88va_m10_i4
global pc88va_m10_i5, pc88va_m10_i6, pc88va_m10_i7, pc88va_m10_i8
global pc88va_m10_f2, pc88va_m10_f3, pc88va_m10_halt

; AX alone is a result. BP addresses our saved architectural caller FLAGS.
%macro ENTER 0
        pushf
        push bx
        push cx
        push dx
        push si
        push di
        push bp
        push ds
        push es
        mov bp, sp
%endmacro
%macro LEAVE 0
        pop es
        pop ds
        pop bp
        pop di
        pop si
        pop dx
        pop cx
        pop bx
        popf
        ret
%endmacro

pc88va_machine_init_:
        ENTER
        test word [ss:bp+16], 0600h
        jnz m10_init_bad
        cmp byte [cs:pc88va_m10_state_], 0
        jne m10_init_bad
        mov ax, ds
        mov dx, cs
        cmp ax, dx
        jne m10_init_bad
        mov ax, es
        cmp ax, dx
        jne m10_init_bad
        mov byte [cs:pc88va_m10_state_], 1
        ; The linker supplies 4096 bytes starting at an intra-paragraph offset.
        ; BP + 20 reconstructs SP before the near call and this saved frame.
        mov bx, bp
        add bx, 20
        jc m10_init_failed
        sub bx, 1000h
        jc m10_init_failed
        cmp bx, 15
        ja m10_init_failed
        mov ax, ss
        mov dx, cs
        cmp dx, 0040h
        jb m10_init_failed
        cmp ax, dx
        jbe m10_init_failed
        sub ax, dx
        cmp ax, 1000h
        jae m10_init_failed
        mov cl, 4
        shl ax, cl
        jc m10_init_failed
        add ax, bx
        jc m10_init_failed
        cmp ax, m10_storage_end
        jb m10_init_failed
        mov ax, ss
        add ax, 0101h
        jc m10_init_failed
        cmp ax, 0a000h
        ja m10_init_failed
        cmp bp, 0100h
        jb m10_init_failed
        cmp bp, 0ffeh
        ja m10_init_failed
        push cs
        pop ds
        mov dx, 0152h
        in al, dx
        mov [cs:m10_banks], al
        inc dx
        in al, dx
        and al, 01fh
        mov [cs:m10_banks+1], al
pc88va_m10_i2:
        mov ax, pc88va_m10_memory_record_
        call pc88va_memory_query_
        or ax, ax
        jnz m10_init_failed
pc88va_m10_i3:
        call pc88va_interrupts_init_
        or ax, ax
        jnz m10_init_failed
pc88va_m10_i4:
        mov ax, pc88va_m10_clock_record_
        call pc88va_clock_read_
        or ax, ax
        jnz m10_init_failed
pc88va_m10_i5:
        mov ax, pc88va_m10_clock_record_
        call pc88va_clock_read_
        or ax, ax
        jnz m10_init_failed
pc88va_m10_i6:
%ifdef M10_VISIBLE_DIAGNOSTICS
        ; M10 verification text is diagnostic-only.  Keep the machine,
        ; interrupt, clock, and arena checks active in the normal candidate,
        ; but do not emit their private milestone banner on the console.
        mov si, m10_message
m10_init_print:
        mov al, [cs:si]
        inc si
        or al, al
        jz pc88va_m10_i7
        xor ah, ah
        call pc88va_console_putc_
        or ax, ax
        jnz m10_init_failed
        jmp short m10_init_print
%endif
pc88va_m10_i7:
        call m10_interrupts_compare
        or ax, ax
        jnz m10_init_failed
        mov dx, 0152h
        in al, dx
        cmp al, [cs:m10_banks]
        jne m10_init_failed
        inc dx
        in al, dx
        and al, 01fh
        cmp al, [cs:m10_banks+1]
        jne m10_init_failed
pc88va_m10_i8:
        mov byte [cs:pc88va_m10_state_], 2
        xor ax, ax
        LEAVE
m10_init_failed:
        mov byte [cs:pc88va_m10_state_], 3
        mov byte [cs:m10_interrupts_valid], 0
        mov word [cs:m10_ticks], 0
        mov word [cs:m10_ticks+2], 0
        mov byte [cs:m10_clock_origin], 0
        ; Public result records are invalidated after a failed transaction.
        mov word [cs:pc88va_m10_memory_record_], 0
        mov word [cs:pc88va_m10_clock_record_], 0
m10_init_bad:
        mov ax, -1
        LEAVE

; INIT_TEXT invokes this far trampoline so the service's CS-relative state
; resolves in the resident _TEXT segment rather than the transient startup
; segment.  The implementation itself remains a near, register-preserving
; service for all resident callers.
pc88va_machine_init_far_:
        ; Remove the far-return frame while entering the near service.  The
        ; stack-arena contract measures the caller SP immediately before its
        ; near call; restoring the frame after the service preserves that
        ; exact measurement and returns to INIT_TEXT normally.
        pop bx
        pop dx
        mov ax, cs
        mov ds, ax
        mov es, ax
        call pc88va_machine_init_
        push dx
        push bx
        retf

pc88va_memory_query_:
        ENTER
        test word [ss:bp+16], 0600h
        jnz .bad
        cmp ax, pc88va_m10_memory_record_
        jne .bad
        mov ax, ds
        mov dx, cs
        cmp ax, dx
        jne .bad
        mov ax, cs
        mov bx, 16
        mul bx
        add ax, m10_arena
        adc dx, 0
        cmp dx, 000ah
        jae .bad
        mov bx, ax
        mov cx, dx
        add bx, m10_arena_end-m10_arena
        adc cx, 0
        cmp cx, 000ah
        jae .bad
        ; Prefix [0, arena), arena [arena, end), suffix [end, 1 MiB).
        mov word [cs:pc88va_m10_memory_record_+2], 3
        mov word [cs:pc88va_m10_memory_record_+4], 0
        mov word [cs:pc88va_m10_memory_record_+6], 0
        mov [cs:pc88va_m10_memory_record_+8], ax
        mov [cs:pc88va_m10_memory_record_+10], dx
        mov word [cs:pc88va_m10_memory_record_+12], 0
        mov [cs:pc88va_m10_memory_record_+14], ax
        mov [cs:pc88va_m10_memory_record_+16], dx
        mov [cs:pc88va_m10_memory_record_+18], bx
        mov [cs:pc88va_m10_memory_record_+20], cx
        mov word [cs:pc88va_m10_memory_record_+22], 1
        mov [cs:pc88va_m10_memory_record_+24], bx
        mov [cs:pc88va_m10_memory_record_+26], cx
        mov word [cs:pc88va_m10_memory_record_+28], 0
        mov word [cs:pc88va_m10_memory_record_+30], 0010h
        mov word [cs:pc88va_m10_memory_record_+32], 0
        mov word [cs:pc88va_m10_memory_record_], 1
        xor ax, ax
        LEAVE
.bad:
        mov ax, -1
        LEAVE

pc88va_interrupts_init_:
        ENTER
        test word [ss:bp+16], 0600h
        jnz .bad
        cmp byte [cs:m10_interrupts_valid], 0
        jne .compare
        xor ax, ax
        mov es, ax
        mov ax, [es:0083h*4]
        or ax, [es:0083h*4+2]
        jz .bad
        xor si, si
        mov di, m10_ivt
        mov cx, 512
.copy:
        mov ax, [es:si]
        mov [cs:di], ax
        add si, 2
        add di, 2
        loop .copy
        mov dx, 0186h
        in al, dx
        mov [cs:m10_masks], al
        mov dx, 018ah
        in al, dx
        mov [cs:m10_masks+1], al
        mov byte [cs:m10_interrupts_valid], 1
.compare:
        call m10_interrupts_compare
        LEAVE
.bad:
        mov ax, -1
        LEAVE

m10_interrupts_compare:
        xor ax, ax
        mov es, ax
        xor si, si
        mov di, m10_ivt
        mov cx, 512
.loop:
        mov ax, [es:si]
        cmp ax, [cs:di]
        jne .bad
        add si, 2
        add di, 2
        loop .loop
        mov dx, 0186h
        in al, dx
        cmp al, [cs:m10_masks]
        jne .bad
        mov dx, 018ah
        in al, dx
        cmp al, [cs:m10_masks+1]
        jne .bad
        xor ax, ax
        ret
.bad:
        mov ax, -1
        ret

pc88va_clock_read_:
        ENTER
        test word [ss:bp+16], 0600h
        jnz .bad
        cmp ax, pc88va_m10_clock_record_
        jne .bad
        mov ax, ds
        mov dx, cs
        cmp ax, dx
        jne .bad
        cmp byte [cs:m10_clock_busy], 0
        jne .bad
        mov byte [cs:m10_clock_busy], 1
        ; A valid source sample establishes origin zero; it does not claim
        ; elapsed progress. A subsequent read must observe a real rising edge.
        in al, 040h
        and al, 0cch
        cmp al, 0c0h
        jne .timeout
        cmp byte [cs:m10_clock_origin], 0
        jne .next_edge
        cmp word [cs:m10_ticks], 0
        jne .timeout
        cmp word [cs:m10_ticks+2], 0
        jne .timeout
        mov byte [cs:m10_clock_origin], 1
        jmp short .record
.next_edge:
        ; Each half has an instruction-count bound independent of host time.
        mov cx, 0ffffh
.low:
        in al, 040h
        test al, 020h
        jz .wait_high
        loop .low
        jmp short .timeout
.wait_high:
        mov cx, 0ffffh
.high:
        in al, 040h
        test al, 020h
        jnz .edge
        loop .high
.timeout:
        mov byte [cs:m10_clock_busy], 0
.bad:
        mov ax, -1
        LEAVE
.edge:
        add word [cs:m10_ticks], 1
        adc word [cs:m10_ticks+2], 0
.record:
        mov ax, [cs:m10_ticks]
        mov [cs:pc88va_m10_clock_record_+2], ax
        mov ax, [cs:m10_ticks+2]
        mov [cs:pc88va_m10_clock_record_+4], ax
        mov word [cs:pc88va_m10_clock_record_], 1
        mov byte [cs:m10_clock_busy], 0
        xor ax, ax
        LEAVE

pc88va_fatal_stop_request_:
        ; Deliberately do not borrow the firmware or print the supplied reason.
pc88va_m10_f2:
        cli
pc88va_m10_f3:
pc88va_m10_halt:
        hlt
        jmp short pc88va_m10_halt

%ifdef M10_VISIBLE_DIAGNOSTICS
m10_message: db 'M10 INIT OK',13,10,0
        db 'M10SERVICE:MACHINE_INIT:SINGLE_SHOT',0
        db 'M10SERVICE:MEMORY:OWNED_ARENA',0
        db 'M10SERVICE:INTERRUPTS:VALIDATED_ADOPTION',0
        db 'M10SERVICE:CLOCK:OBSERVED_VRTC_EDGE',0
        db 'M10SERVICE:FATAL_STOP:CLI_HLT',0
%endif
pc88va_m10_state_: db 0
pc88va_m10_control_: db 0
m10_interrupts_valid: db 0
m10_clock_busy: db 0
m10_clock_origin: db 0
m10_masks: dw 0
m10_banks: dw 0
m10_ticks: dd 0
pc88va_m10_memory_record_: times 34 db 0
pc88va_m10_clock_record_: times 6 db 0
m10_ivt: times 1024 db 0
m10_arena: times 256 db 0
m10_arena_end:
m10_storage_end:
