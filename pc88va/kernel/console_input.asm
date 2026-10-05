; SPDX-License-Identifier: GPL-2.0-or-later
; M11: read-only matrix polling; no firmware calls, queue or driver echo.
; Matrix coordinates: pinned VAEG io/serial.c scantomap/updatekeymap.
; ASCII/Shift mapping: pinned VAEG sdl2/kbdpaste.c map_ascii.
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

%ifndef M11_FLAT_TEST
%ifdef PC88VA_M13
%include "kernel/m13_segments.inc"
segment M13_PLATFORM_TEXT
%else
segment _TEXT class=CODE public use16
%endif
extern pc88va_m10_state_
extern pc88va_console_putc_
extern pc88va_clock_read_, pc88va_m10_clock_record_
%endif
global pc88va_console_getc_, pc88va_console_getc_dos_
global pc88va_console_peek_dos_, pc88va_console_read_dos_
global pc88va_m11_character_
global pc88va_m11_poll_matrix, pc88va_m11_return
global pc88va_m11_storage_begin, pc88va_m11_storage_end
global pc88va_m16_input_flush_
global pc88va_m16_storage_begin, pc88va_m16_storage_end
global pc88va_m16_queue_, pc88va_m16_count_

; AX=&exported word, DS=CS, M10 ready, IF=DF=TF=0 for the public raw entry.
; AX: 0 character, 1 no new input, 2 unsupported/ambiguous new input,
; ffff invalid precondition. Only status zero writes the character word.
; No queue: multiple non-modifier make edges in one poll are rejected.
; First poll adopts held keys; a subsequent release and make is required.
pc88va_console_getc_:
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
        test word [ss:bp+16], 0700h
        jnz m11_bad
        xor bp, bp
        jmp short m11_validate_common

; The common DOS device dispatcher deliberately inherits IF=1 after INT 21h.
; Keep the public raw entry strict, but expose an integration entry which
; accepts that inherited IF while retaining the same non-reentrant poll and
; preserving the caller's architectural flags.  The matrix poll itself does
; not install or suppress an interrupt; repeat clock sampling separately meets
; M10's IF=DF=0 service contract and restores the caller's flags.
pc88va_console_getc_dos_:
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
        test word [ss:bp+16], 0500h
        jnz m11_bad
        mov bp, 1
m11_validate_common:
        cmp ax, pc88va_m11_character_
        jne m11_bad
        mov bx, ds
        mov dx, cs
        cmp bx, dx
        jne m11_bad
        cmp byte [cs:pc88va_m10_state_], 2
        jne m11_bad
        mov word [cs:m11_candidate], 0ffffh
pc88va_m11_poll_matrix:
        xor dx, dx
        xor si, si
        mov cx, 15
m11_read:
        in al, dx
        mov [cs:m11_current+si], al
        inc dx
        inc si
        loop m11_read
        cmp byte [cs:m11_adopted], 0
        jne m11_edges
        xor si, si
        mov cx, 15
m11_adopt:
        mov al, [cs:m11_current+si]
        mov [cs:m11_previous+si], al
        inc si
        loop m11_adopt
        mov byte [cs:m11_adopted], 1
        jmp m11_empty
m11_edges:
        xor si, si
        xor di, di
        mov bx, 0ffffh
m11_row:
        mov al, [cs:m11_previous+si]
        mov ah, [cs:m11_current+si]
        mov [cs:m11_previous+si], ah
        not ah
        and al, ah
        ; Ignore derived Return and Shift/INSDEL aliases and physical Shift.
        cmp si, 1
        jne m11_not_return_alias
        and al, 7fh
m11_not_return_alias:
        cmp si, 8
        jne m11_not_shift_alias
        and al, 0b7h
        ; DOS interprets Ctrl with a letter; a modifier edge is not a key.
        or bp, bp
        jz m11_not_shift_alias
        and al, 7fh
m11_not_shift_alias:
        cmp si, 14
        jne m11_not_shift
        and al, 0f3h
m11_not_shift:
        cmp si, 9
        jne m11_not_function_alias
        ; VAEG mirrors row-12 F6-F10 contacts onto their row-9 F1-F5
        ; compatibility aliases. Count the physical row-12 make once.
        mov dl, [cs:m11_current+12]
        not dl
        shl dl, 1
        and dl, 03eh
        not dl
        and al, dl
m11_not_function_alias:
        mov dx, si
        shl dx, 1
        shl dx, 1
        shl dx, 1
        mov cx, 8
m11_bit:
        test al, 1
        jz m11_next_bit
        cmp bx, 0ffffh
        jne m11_multiple
        mov bx, dx
        jmp short m11_next_bit
m11_multiple:
        mov di, 1
m11_next_bit:
        shr al, 1
        inc dx
        loop m11_bit
        inc si
        cmp si, 15
        jb m11_row
        or di, di
        jnz m11_ambiguous
        cmp bx, 0ffffh
        je m11_empty
        mov [cs:m11_candidate], bx
        ; Unsupported modifier/mode combinations cannot become plain ASCII.
        mov al, [cs:m11_current+8]
        not al
        or bp, bp
        jz m11_check_modes
        and al, 7fh
m11_check_modes:
        test al, 0b0h
        jnz m11_unsupported
        test byte [cs:m11_current+10], 80h
        jz m11_unsupported
        mov al, [cs:m11_current+13]
        not al
        test al, 0fh
        jnz m11_unsupported
        ; The early raw ABI still rejects Escape and Tab. DOS needs their
        ; ASCII control values; break/EOF policy stays in the common kernel.
        or bp, bp
        jz m11_find_key
        cmp bl, 9*8+7
        mov al, 27
        je m11_store_character
        cmp bl, 10*8+0
        mov al, 9
        je m11_store_character
m11_find_key:
        mov si, m11_keys
        mov cx, (m11_keys_end-m11_keys)/3
m11_lookup:
        cmp bl, [cs:si]
        je m11_found
        add si, 3
        loop m11_lookup
        jmp short m11_unsupported
m11_found:
        test byte [cs:m11_current+8], 80h
        jnz m11_apply_shift
        mov al, [cs:si+1]
        sub al, 'a'
        cmp al, 25
        ja m11_unsupported
        inc al
        jmp short m11_store_character
m11_apply_shift:
        mov al, [cs:m11_current+14]
        not al
        and al, 0ch
        jz m11_plain
        inc si
m11_plain:
        mov al, [cs:si+1]
        or al, al
        jz m11_unsupported
m11_store_character:
        xor ah, ah
        mov [cs:pc88va_m11_character_], ax
        xor ax, ax
        jmp short pc88va_m11_return
m11_empty:
        mov ax, 1
        jmp short pc88va_m11_return
m11_unsupported:
        mov ax, 2
        jmp short pc88va_m11_return
m11_bad:
        mov ax, 0ffffh
pc88va_m11_return:
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

; The M11 raw ABI reports ambiguity as status 2.  M16 keeps no selected key in
; that case, so the DOS adapter cannot turn a partial chord into stale input.
m11_ambiguous:
        mov word [cs:m11_candidate], 0ffffh
        jmp short m11_unsupported

; DOS CON status is non-destructive.  The M16 queue stores whole DOS events;
; the second byte of an extended event is held separately after its 00h prefix
; has been consumed.
pc88va_console_peek_dos_:
        pushf
        push bx
        push cx
        push dx
        push si
        push di
        push bp
        push ds
        push es
        cmp byte [cs:m16_second_valid], 0
        jne m16_peek_second
        cmp byte [cs:m16_count], 0
        jne m16_peek_queued
        call m16_update
        cmp byte [cs:m16_second_valid], 0
        jne m16_peek_second
        cmp byte [cs:m16_count], 0
        je m16_peek_empty
m16_peek_queued:
        xor bx, bx
        mov bl, [cs:m16_head]
        shl bx, 1
        mov ax, [cs:m16_queue+bx]
        xor ah, ah
        jmp short m16_peek_byte
m16_peek_second:
        xor ax, ax
        mov al, [cs:m16_second_byte]
m16_peek_byte:
        mov [cs:pc88va_m11_character_], ax
        xor ax, ax
        jmp short m16_peek_done
m16_peek_empty:
        mov ax, 1
m16_peek_done:
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

; C_INPUT is the consuming side of the same contract.  A character found by
; an earlier non-destructive status request is returned without requiring a
; new matrix edge; otherwise perform one ordinary poll.
pc88va_console_read_dos_:
        pushf
        push bx
        push cx
        push dx
        push si
        push di
        push bp
        push ds
        push es
        cmp byte [cs:m16_second_valid], 0
        jne m16_read_second
        cmp byte [cs:m16_count], 0
        jne m16_read_queued
        call m16_update
        cmp byte [cs:m16_second_valid], 0
        jne m16_read_second
        cmp byte [cs:m16_count], 0
        je m16_read_empty
m16_read_queued:
        xor bx, bx
        mov bl, [cs:m16_head]
        shl bx, 1
        mov dx, [cs:m16_queue+bx]
        add byte [cs:m16_head], 1
        and byte [cs:m16_head], 7
        dec byte [cs:m16_count]
        mov ax, dx
        or ah, ah
        jz m16_read_store
        mov [cs:m16_second_byte], ah
        mov byte [cs:m16_second_valid], 1
        xor ah, ah
        jmp short m16_read_store
m16_read_second:
        mov byte [cs:m16_second_valid], 0
        xor ax, ax
        mov al, [cs:m16_second_byte]
m16_read_store:
        mov [cs:pc88va_m11_character_], ax
        xor ax, ax
        jmp short m16_read_done
m16_read_empty:
        mov ax, 1
m16_read_done:
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

pc88va_m11_storage_begin:
pc88va_m11_character_: dw 0
m11_candidate: dw 0ffffh
m11_adopted: db 0
m11_previous: times 15 db 0
m11_current: times 15 db 0
pc88va_m11_storage_end:


; One row/bit coordinate, unshifted byte, shifted byte per physical key.
; Unsupported Shift+0 maps to zero internally, never to a returned NUL.
m11_keys:
        db 6*8+1, '1', '!'
        db 6*8+2, '2', '"'
        db 6*8+3, '3', '#'
        db 6*8+4, '4', '$'
        db 6*8+5, '5', '%'
        db 6*8+6, '6', '&'
        db 6*8+7, '7', 39
        db 7*8+0, '8', '('
        db 7*8+1, '9', ')'
        db 6*8+0, '0', 0
        db 5*8+7, '-', '='
        db 5*8+6, '^', 96
        db 5*8+4, 92, '|'
        db 4*8+1, 'q', 'Q'
        db 4*8+7, 'w', 'W'
        db 2*8+5, 'e', 'E'
        db 4*8+2, 'r', 'R'
        db 4*8+4, 't', 'T'
        db 5*8+1, 'y', 'Y'
        db 4*8+5, 'u', 'U'
        db 3*8+1, 'i', 'I'
        db 3*8+7, 'o', 'O'
        db 4*8+0, 'p', 'P'
        db 2*8+0, '@', '~'
        db 5*8+3, '[', '{'
        db 2*8+1, 'a', 'A'
        db 4*8+3, 's', 'S'
        db 2*8+4, 'd', 'D'
        db 2*8+6, 'f', 'F'
        db 2*8+7, 'g', 'G'
        db 3*8+0, 'h', 'H'
        db 3*8+2, 'j', 'J'
        db 3*8+3, 'k', 'K'
        db 3*8+4, 'l', 'L'
        db 7*8+3, ';', '+'
        db 7*8+2, ':', '*'
        db 5*8+5, ']', '}'
        db 5*8+2, 'z', 'Z'
        db 5*8+0, 'x', 'X'
        db 2*8+3, 'c', 'C'
        db 4*8+6, 'v', 'V'
        db 2*8+2, 'b', 'B'
        db 3*8+6, 'n', 'N'
        db 3*8+5, 'm', 'M'
        db 7*8+4, ',', '<'
        db 7*8+5, '.', '>'
        db 7*8+6, '/', '?'
        db 7*8+7, 92, '_'
        db 9*8+6, ' ', ' '
        db 12*8+5, 8, 8
        db 14*8+0, 13, 13
        db 14*8+1, 13, 13
m11_keys_end:

; M16 DOS input adapter. Events use the common DOS convention: ASCII is one
; byte; extended keys are queued atomically as 00h followed by their code.
; Repeat is driven only by observed M10 VRTC edges (30-edge delay, 4-edge
; period). The queue holds eight complete events and drops new events at full.
%define M16_REPEAT_DELAY 30
%define M16_REPEAT_PERIOD 4
pc88va_m16_storage_begin:
pc88va_m16_queue_:
m16_queue: times 16 db 0
m16_head: db 0
pc88va_m16_count_:
m16_count: db 0
m16_second_valid: db 0
m16_second_byte: db 0
m16_repeat_owner: dw 0ffffh
m16_repeat_event: dw 0
m16_repeat_deadline: dd 0
m16_now: dd 0
m16_saved_scan: db 0
m16_saved_shift: db 0
pc88va_m16_storage_end:

; All state is private to the serialized DOS CON path. Flush does not poll
; hardware; clearing the adoption flag makes the next poll swallow held keys.
pc88va_m16_input_flush_:
        pushf
        push bx
        push cx
        push dx
        push si
        push di
        push bp
        push ds
        push es
        mov byte [cs:m16_head], 0
        mov byte [cs:m16_count], 0
        mov byte [cs:m16_second_valid], 0
        mov byte [cs:m16_second_byte], 0
        mov word [cs:m16_repeat_owner], 0ffffh
        mov word [cs:m16_repeat_event], 0
        mov word [cs:m16_repeat_deadline], 0
        mov word [cs:m16_repeat_deadline+2], 0
        mov word [cs:m11_candidate], 0ffffh
        mov byte [cs:m11_adopted], 0
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

; Poll exactly once per DOS status/read request. The low-level scanner remains
; responsible for physical make/release accounting; this adapter owns event
; translation, queueing and repeat policy.
m16_update:
        mov ax, pc88va_m11_character_
        call pc88va_console_getc_dos_
        or ax, ax
        jz m16_new_ascii
        cmp ax, 2
        je m16_new_non_ascii
        cmp ax, 1
        je m16_no_make
        jmp near m16_cancel_repeat
m16_new_ascii:
        mov ax, [cs:pc88va_m11_character_]
        call m16_enqueue
        jc m16_drop_new
        call m16_start_repeat
        ret
m16_new_non_ascii:
        call m16_translate_candidate
        jnc m16_cancel_repeat
        call m16_enqueue
        jc m16_drop_new
        call m16_start_repeat
        ret
m16_drop_new:
        mov word [cs:m16_repeat_owner], 0ffffh
        ret
m16_cancel_repeat:
        mov word [cs:m16_repeat_owner], 0ffffh
        ret
m16_no_make:
        call m16_repeat_check
        ret

; Input AX is a complete one- or two-byte DOS event. CF reports a full ring;
; AX is preserved for the caller's repeat setup.
m16_enqueue:
        cmp byte [cs:m16_count], 8
        jae m16_enqueue_full
        push bx
        push dx
        mov dx, ax
        xor bx, bx
        mov bl, [cs:m16_head]
        add bl, [cs:m16_count]
        and bl, 7
        shl bx, 1
        mov [cs:m16_queue+bx], dx
        inc byte [cs:m16_count]
        mov ax, dx
        pop dx
        pop bx
        clc
        ret
m16_enqueue_full:
        stc
        ret

; Start a fresh owner only for printable text, Backspace or unmodified arrows.
; A non-repeatable make deliberately cancels the previous owner's repeat.
m16_start_repeat:
        mov word [cs:m16_repeat_owner], 0ffffh
        mov word [cs:m16_repeat_event], 0
        cmp ah, 0
        jne m16_repeat_extended
        cmp al, 8
        je m16_repeat_eligible
        cmp al, 32
        jb m16_repeat_done
        cmp al, 126
        ja m16_repeat_done
        jmp short m16_repeat_eligible
m16_repeat_extended:
        cmp al, 0
        jne m16_repeat_done
        cmp ah, 48h
        je m16_repeat_eligible
        cmp ah, 50h
        je m16_repeat_eligible
        cmp ah, 4bh
        je m16_repeat_eligible
        cmp ah, 4dh
        jne m16_repeat_done
m16_repeat_eligible:
        mov bx, [cs:m11_candidate]
        cmp bx, 0ffffh
        je m16_repeat_done
        mov [cs:m16_repeat_event], ax
        mov [cs:m16_repeat_owner], bx
        call m16_sample_clock
        jc m16_repeat_clock_bad
        mov ax, [cs:m16_now]
        mov dx, [cs:m16_now+2]
        add ax, M16_REPEAT_DELAY
        adc dx, 0
        mov [cs:m16_repeat_deadline], ax
        mov [cs:m16_repeat_deadline+2], dx
m16_repeat_done:
        ret
m16_repeat_clock_bad:
        mov word [cs:m16_repeat_owner], 0ffffh
        ret

; Check the currently held matrix bit before consulting the clock. This keeps
; idle DOS polling independent of the timer and cancels repeat on release.
m16_repeat_check:
        mov bx, [cs:m16_repeat_owner]
        cmp bx, 0ffffh
        je m16_repeat_done
        mov dx, bx
        and dx, 7
        mov di, bx
        mov cl, 3
        shr di, cl
        mov cl, dl
        mov al, [cs:m11_current+di]
        shr al, cl
        test al, 1
        jnz m16_cancel_repeat
        call m16_sample_clock
        jc m16_cancel_repeat
        mov ax, [cs:m16_now]
        mov dx, [cs:m16_now+2]
        sub ax, [cs:m16_repeat_deadline]
        sbb dx, [cs:m16_repeat_deadline+2]
        test dx, 8000h
        jnz m16_repeat_done
        mov ax, [cs:m16_repeat_event]
        call m16_enqueue
        ; Advance from this observation even if full. Never emit catch-up bursts.
        mov ax, [cs:m16_now]
        mov dx, [cs:m16_now+2]
        add ax, M16_REPEAT_PERIOD
        adc dx, 0
        mov [cs:m16_repeat_deadline], ax
        mov [cs:m16_repeat_deadline+2], dx
        ret

; M10's record contains a valid word followed by a monotonically increasing
; 32-bit count of observed VRTC rising edges. Clock failure disables repeat.
m16_sample_clock:
%ifdef M16_FLAT_TEST
        ; The standalone test supplies a deterministic clock stub below this
        ; include; the production path uses the validated M10 service.
%endif
        ; DOS CON can call this adapter with IF=1. M10 clock reads require
        ; IF=DF=0 while polling the VRTC port; preserve and restore DOS flags.
        pushf
        cli
        cld
        push ds
        push cs
        pop ds
        mov ax, pc88va_m10_clock_record_
        call pc88va_clock_read_
        pop ds
        popf
        or ax, ax
        jnz m16_clock_failed
        cmp word [cs:pc88va_m10_clock_record_], 1
        jne m16_clock_failed
        mov ax, [cs:pc88va_m10_clock_record_+2]
        mov [cs:m16_now], ax
        mov ax, [cs:pc88va_m10_clock_record_+4]
        mov [cs:m16_now+2], ax
        clc
        ret
m16_clock_failed:
        stc
        ret

; Translate the one unique make edge the raw scanner retained. The project
; contract uses FreeDOS extended-key pairs for ordinary editing keys and a
; small documented PC-88VA extension range for shifted arrows/function keys.
m16_translate_candidate:
        mov bx, [cs:m11_candidate]
        cmp bx, 0ffffh
        je m16_translate_bad
        call m16_modes_clear
        jc m16_translate_bad

        ; F1-F10 are the physical matrix contacts identified by the VA key map.
        cmp bx, 9*8+1
        jb m16_try_f6
        cmp bx, 9*8+5
        ja m16_try_f6
        mov ax, bx
        sub ax, 9*8+1
        add al, 3bh
        jmp short m16_function_key
m16_try_f6:
        cmp bx, 12*8+0
        jb m16_try_cursor
        cmp bx, 12*8+4
        ja m16_try_cursor
        mov ax, bx
        sub ax, 12*8+0
        add al, 40h
m16_function_key:
        mov dl, al
        call m16_control_down
        or al, al
        jnz m16_translate_bad
        call m16_shift_down
        or al, al
        jz m16_function_plain
        mov al, dl
        sub al, 3bh
        add al, 80h
        jmp short m16_function_store
m16_function_plain:
        mov al, dl
m16_function_store:
        mov ah, al
        xor al, al
        stc
        ret

m16_try_cursor:
        ; AL is the ordinary DOS scan code; AH is this target's Shift extension.
        cmp bx, 8*8+1
        jne m16_cursor_down
        mov ax, 8a48h
        jmp short m16_cursor_modifiers
m16_cursor_down:
        cmp bx, 10*8+1
        jne m16_cursor_left
        mov ax, 8b50h
        jmp short m16_cursor_modifiers
m16_cursor_left:
        cmp bx, 10*8+2
        jne m16_cursor_right
        mov ax, 8c4bh
        jmp short m16_cursor_modifiers
m16_cursor_right:
        cmp bx, 8*8+2
        jne m16_cursor_home
        mov ax, 8d4dh
        jmp short m16_cursor_modifiers
m16_cursor_home:
        cmp bx, 8*8+0
        jne m16_cursor_end
        mov ax, 4747h
        jmp short m16_nonarrow_modifiers
m16_cursor_end:
        cmp bx, 10*8+3
        jne m16_cursor_insert
        mov ax, 4f4fh
        jmp short m16_nonarrow_modifiers
m16_cursor_insert:
        cmp bx, 12*8+6
        jne m16_cursor_delete
        mov ax, 5252h
        jmp short m16_nonarrow_modifiers
m16_cursor_delete:
        cmp bx, 12*8+7
        jne m16_control_letter
        mov ax, 5353h
m16_nonarrow_modifiers:
        mov [cs:m16_saved_scan], al
        call m16_control_down
        or al, al
        jnz m16_translate_bad
        call m16_shift_down
        or al, al
        jnz m16_translate_bad
        mov ah, [cs:m16_saved_scan]
        xor al, al
        stc
        ret

m16_cursor_modifiers:
        mov [cs:m16_saved_scan], al
        mov [cs:m16_saved_shift], ah
        call m16_control_down
        or al, al
        jz m16_cursor_not_control
        call m16_shift_down
        or al, al
        jnz m16_translate_bad
        cmp bx, 10*8+2
        jne m16_cursor_control_right
        mov ax, 7300h
        stc
        ret
m16_cursor_control_right:
        cmp bx, 8*8+2
        jne m16_translate_bad
        mov ax, 7400h
        stc
        ret
m16_cursor_not_control:
        call m16_shift_down
        or al, al
        jz m16_cursor_plain
        mov ah, [cs:m16_saved_shift]
        xor al, al
        stc
        ret
m16_cursor_plain:
        mov al, [cs:m16_saved_scan]
        mov ah, al
        xor al, al
        stc
        ret

m16_control_letter:
        call m16_control_down
        or al, al
        jz m16_translate_bad
        mov si, m11_keys
        mov cx, (m11_keys_end-m11_keys)/3
m16_control_lookup:
        cmp bl, [cs:si]
        je m16_control_found
        add si, 3
        loop m16_control_lookup
        jmp short m16_translate_bad
m16_control_found:
        mov al, [cs:si+1]
        cmp al, 'a'
        jb m16_translate_bad
        cmp al, 'z'
        ja m16_translate_bad
        sub al, 'a'-1
        xor ah, ah
        stc
        ret

m16_translate_bad:
        clc
        ret

; Validate non-Control mode keys while permitting Ctrl and either Shift.
m16_modes_clear:
        mov al, [cs:m11_current+8]
        and al, 30h
        cmp al, 30h
        jne m16_modes_bad
        test byte [cs:m11_current+10], 80h
        jz m16_modes_bad
        mov al, [cs:m11_current+13]
        not al
        and al, 0fh
        jnz m16_modes_bad
        clc
        ret
m16_modes_bad:
        stc
        ret

m16_control_down:
        mov al, [cs:m11_current+8]
        not al
        and al, 80h
        ret

m16_shift_down:
        mov al, [cs:m11_current+14]
        not al
        and al, 0ch
        ret

; Milestone diagnostics are entered only from the compile-only startup.asm
; entry; the linked M13 kernel does not keep them resident.
%ifndef M11_FLAT_TEST
%ifndef PC88VA_M13
global pc88va_m11_diagnostic_, pc88va_m11_control_, pc88va_m11_count_
global pc88va_m11_empty_count_, pc88va_m11_history_
global pc88va_m11_k1, pc88va_m11_k4, pc88va_m11_k5, pc88va_m11_k8, pc88va_m11_k9
; Qualification caller owns echo. It stops on a count, never on a fixed text.
pc88va_m11_diagnostic_:
pc88va_m11_k1:
        mov cx, 8
        cmp byte [cs:pc88va_m11_control_], 0
        je m11_next
        cmp byte [cs:pc88va_m11_control_], 1
        jne m11_diagnostic_bad
        mov cx, 1
m11_next:
        mov ax, pc88va_m11_character_
pc88va_m11_k4:
        call pc88va_console_getc_
pc88va_m11_k5:
        cmp ax, 1
        je m11_no_input
        or ax, ax
        jnz m11_diagnostic_bad
        mov bx, [cs:pc88va_m11_count_]
        cmp bx, 8
        jae m11_diagnostic_bad
        shl bx, 1
        mov ax, [cs:pc88va_m11_character_]
        mov [cs:pc88va_m11_history_+bx], ax
        inc word [cs:pc88va_m11_count_]
        ; The delayed no-input control observes getc alone, without echo.
        cmp byte [cs:pc88va_m11_control_], 1
        je m11_after_echo
        cmp al, 8
        je m11_after_echo
        call pc88va_console_putc_
        or ax, ax
        jnz m11_diagnostic_bad
        cmp word [cs:pc88va_m11_character_], 13
        jne m11_after_echo
        mov ax, 10
        call pc88va_console_putc_
        or ax, ax
        jnz m11_diagnostic_bad
pc88va_m11_k8:
m11_after_echo:
        loop m11_next
        ; A completed sample must not return the held/released last key twice.
        mov ax, pc88va_m11_character_
        call pc88va_console_getc_
        cmp ax, 1
        jne m11_diagnostic_bad
pc88va_m11_k9:
        xor ax, ax
        ret
m11_no_input:
        cmp word [cs:pc88va_m11_empty_count_], 0ffffh
        je m11_next
        inc word [cs:pc88va_m11_empty_count_]
        jmp m11_next
m11_diagnostic_bad:
        mov ax, 0ffffh
        ret
pc88va_m11_control_: db 0
pc88va_m11_count_: dw 0
pc88va_m11_empty_count_: dw 0
pc88va_m11_history_: times 8 dw 0
db 'M11SERVICE:CONSOLE_GETC:MATRIX_POLL', 0
%endif
%endif
