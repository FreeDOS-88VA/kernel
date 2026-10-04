; SPDX-License-Identifier: GPL-2.0-or-later
; M14: resident bounded block service after M10/M11 startup.
;
; The request record and scratch buffer are kernel-owned storage.  The
; parameterized read/write cores remain the single validator/transfer state
; machines; this file supplies resident entries and VA firmware callbacks.
bits 16
cpu 8086
%include "kernel/disk_buffer.inc"
%ifndef PC88VA
%error PC88VA selector is required
%endif
%ifdef NEC98
%error Mixed machine selectors
%endif
%ifdef IBMPC
%error Mixed machine selectors
%endif

%ifdef PC88VA_M13
%include "kernel/m13_segments.inc"
segment M13_PLATFORM_TEXT
%else
segment _TEXT class=CODE public use16
%endif

extern pc88va_m10_state_
extern pc88va_console_putc_
extern pc88va_m16_profiles_

; Keep a resident copy of the accepted M08 validator/transfer state machine.
; The loader object retains its historical copy; this copy is linked into the
; kernel resident service so the public entry is not loader-only.
%include "disk_read.inc"
%include "disk_write.inc"

global pc88va_kernel_disk_read_
global pc88va_kernel_disk_write_
global pc88va_kernel_firmware_read_one_
global pc88va_kernel_firmware_write_one_
global pc88va_m12_prepare_
global pc88va_m12_diagnostic_
global pc88va_m12_control_
global pc88va_m12_request_
global pc88va_m12_result_
global pc88va_m12_buffer_
global pc88va_m12_drive_context_
global pc88va_m12_call_flags_
global pc88va_m12_storage_begin
global pc88va_m12_storage_end

; AX points only to the exported resident request.  AX returns the M08 typed
; status.  The entry is non-reentrant and preserves the caller frame.
pc88va_kernel_disk_read_:
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
        ; DOS invokes the integration entry with IF inherited from INT 21h.
        ; Keep DF/TF strict while preserving the caller's IF state.
        test word [ss:bp+16], 0500h
        jnz .bad
        mov bx, ds
        mov dx, cs
        cmp bx, dx
        jne .bad
        cmp byte [cs:pc88va_m10_state_], 2
        jne .bad
        cmp ax, pc88va_m12_request_
        jne .bad
        cmp word [cs:pc88va_m12_request_+RD_CAPACITY], PC88VA_DISK_BUFFER_BYTES
        ja .bad
        mov si, ax
        call pc88va_disk_read_core
        jmp short .return
.bad:
        mov ax, 1
.return:
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

; Accepted M08 firmware route.  The controller owns the transfer and writes
; directly to the validated ES:BP destination supplied by the core.  The
; callback returns AX=0 and CX=sector bytes only after the firmware reports
; success; no write/format command is reachable from this entry.
pc88va_kernel_firmware_read_one_:
        mov bx, [si+20]
        cmp bx, 1
        ja .firmware_not_ready
        mov dx, bx
        shl bx, 1
        shl dx, 1
        shl dx, 1
        shl dx, 1
        add bx, dx
        push si
        mov al, [cs:pc88va_m16_profiles_+bx]
        mov ch, byte [si+20]
        mov ah, 0ah
        push word [cs:pc88va_m12_call_flags_]
        popf
        int 80h
        pop si
        jc .firmware_error
        or ah, ah
        jnz .firmware_error
        mov ax, [si+40]
        mov es, ax
        mov bp, [si+38]
        mov cx, [si+32]
        shl cx, 1
        or cx, [si+34]
        mov ax, [si+20]
        mov ch, al
        mov bx, ax
        shl bx, 1
        mov dx, bx
        shl bx, 1
        shl bx, 1
        add bx, dx
        mov dl, [cs:pc88va_m16_profiles_+bx]
        and dl, 0fh
        ; The profile index calculation uses BX and DX, which otherwise
        ; clobber the firmware's cylinder/head and sector registers.
        mov bh, [si+32]
        mov bl, [si+34]
        mov dh, [si+36]
        mov ax, 8101h
        push si
        push word [cs:pc88va_m12_call_flags_]
        popf
        int 80h
        pop si
        jc .firmware_error
        or ah, ah
        jnz .firmware_error
        xor ax, ax
        mov cx, [si+18]
        retf
.firmware_error:
        ; The core stores the callback's status separately from DISK_FIRMWARE.
        ; Preserve it for the DOS adapter instead of turning every read error
        ; into the numeric status used for write protection.
        mov al, ah
        xor ah, ah
        xor cx, cx
        or ax, ax
        jnz .firmware_error_return
        mov ax, 0ffffh             ; CF-only failure: unknown device status
.firmware_error_return:
        retf
.firmware_not_ready:
        xor cx, cx
        mov ax, 4
        retf

; PC-88VA data-write callback.  AH=82h is the VA write-sector service.
; The transfer core has already bounded ES:BP to the resident scratch area
; and supplies one 1024-byte sector for this callback.
pc88va_kernel_firmware_write_one_:
        mov bx, [si+20]
        cmp bx, 1
        ja .write_not_ready
        mov dx, bx
        shl bx, 1
        shl dx, 1
        shl dx, 1
        shl dx, 1
        add bx, dx
        push si
        mov al, [cs:pc88va_m16_profiles_+bx]
        mov ch, byte [si+20]
        mov ah, 0ah
        push word [cs:pc88va_m12_call_flags_]
        popf
        int 80h
        pop si
        jc .write_firmware_error
        or ah, ah
        jnz .write_firmware_error
        mov ax, [si+40]
        mov es, ax
        mov bp, [si+38]
        mov cx, [si+32]
        shl cx, 1
        or cx, [si+34]
        mov ax, [si+20]
        mov ch, al
        mov bx, ax
        shl bx, 1
        mov dx, bx
        shl bx, 1
        shl bx, 1
        add bx, dx
        mov dl, [cs:pc88va_m16_profiles_+bx]
        and dl, 0fh
        ; Keep the firmware's CHS registers out of the profile-index scratch.
        mov bh, [si+32]
        mov bl, [si+34]
        mov dh, [si+36]
        mov ax, 8201h
        push si
        push word [cs:pc88va_m12_call_flags_]
        popf
        int 80h
        pop si
        jc .write_firmware_error
        mov al, ah
        or al, al
        jnz .write_firmware_error_status
        xor ax, ax
        mov cx, [si+18]
        retf
.write_firmware_error:
        mov al, ah
.write_firmware_error_status:
        xor ah, ah
        xor cx, cx
        or ax, ax
        jnz .write_firmware_error_return
        mov ax, 0dh
.write_firmware_error_return:
        retf
.write_not_ready:
        xor cx, cx
        mov ax, 4
        retf

; Resident write entry mirrors the accepted read entry's ownership and
; non-reentrancy checks, but invokes the write transfer core.
pc88va_kernel_disk_write_:
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
        jnz .write_bad
        mov bx, ds
        mov dx, cs
        cmp bx, dx
        jne .write_bad
        cmp byte [cs:pc88va_m10_state_], 2
        jne .write_bad
        cmp ax, pc88va_m12_request_
        jne .write_bad
        cmp word [cs:pc88va_m12_request_+RD_CAPACITY], PC88VA_DISK_BUFFER_BYTES
        ja .write_bad
        mov si, ax
        call pc88va_disk_write_core
        jmp short .write_return
.write_bad:
        mov ax, DISK_CONTRACT
.write_return:
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

; Initialize the reusable record for one bounded resident request.  The
; caller may replace LBA/COUNT before invoking pc88va_kernel_disk_read_.
pc88va_m12_prepare_:
        mov word [cs:pc88va_m12_request_+0], 1
        ; The deterministic M12 fixture occupies sectors 200 and 201.
        mov word [cs:pc88va_m12_request_+2], 200
        mov word [cs:pc88va_m12_request_+4], 2
        mov word [cs:pc88va_m12_request_+6], pc88va_m12_buffer_
        mov word [cs:pc88va_m12_request_+8], cs
        mov word [cs:pc88va_m12_request_+10], pc88va_m12_buffer_end-pc88va_m12_buffer_
        mov word [cs:pc88va_m12_request_+12], 1280
        mov word [cs:pc88va_m12_request_+14], 8
        mov word [cs:pc88va_m12_request_+16], 2
        mov word [cs:pc88va_m12_request_+18], 1024
        mov ax, [cs:pc88va_m12_drive_context_]
        mov [cs:pc88va_m12_request_+20], ax
        mov word [cs:pc88va_m12_request_+22], pc88va_kernel_firmware_read_one_
        mov word [cs:pc88va_m12_request_+24], cs
        mov word [cs:pc88va_m12_request_+26], 3
        mov word [cs:pc88va_m12_request_+28], 0
        mov word [cs:pc88va_m12_request_+30], 0
        ret

; Qualification caller.  It is selected by an explicit control byte and is
; reached only after the normal M11 diagnostic has returned.  It records the
; status and completed bytes but never fabricates a successful result.
pc88va_m12_diagnostic_:
        cmp byte [cs:pc88va_m12_control_], 0
        je .disabled
        cmp byte [cs:pc88va_m12_control_], 3
        ja .disabled
        call pc88va_m12_prepare_
        cmp byte [cs:pc88va_m12_control_], 2
        jne .invoke
        ; Control 2 is a deliberately invalid post-boot range.  It must be
        ; rejected by the shared validator before the firmware callback.
        mov word [cs:pc88va_m12_request_+2], 1279
        mov word [cs:pc88va_m12_request_+4], 2
.invoke:
        mov ax, pc88va_m12_request_
        call pc88va_kernel_disk_read_
        mov [cs:pc88va_m12_result_+0], ax
        mov ax, [cs:pc88va_m12_request_+28]
        mov [cs:pc88va_m12_result_+2], ax
        cmp word [cs:pc88va_m12_result_+0], 0
        jne .done
        mov si, pc88va_m12_ok_message
.print:
        xor ax, ax
        mov al, [cs:si]
        inc si
        or al, al
        jz .done
        call pc88va_console_putc_
        or ax, ax
        jz .print
        mov word [cs:pc88va_m12_result_+0], 1
.done:
        mov ax, [cs:pc88va_m12_result_+0]
        ret
.disabled:
        xor ax, ax
        ret

pc88va_m12_ok_message: db 'M12 READ OK', 13, 10, 0
pc88va_m12_service_marker: db 'M12SERVICE:DISK_READ:RESIDENT', 0
pc88va_m12_control_: db 0
pc88va_m12_drive_context_: dw 0
pc88va_m12_call_flags_: dw 0
pc88va_m12_request_: times 48 db 0
pc88va_m12_result_: times 4 db 0
align 16, db 0
pc88va_m12_storage_begin:
pc88va_m12_buffer_: times PC88VA_DISK_BUFFER_BYTES db 0
pc88va_m12_buffer_end:
pc88va_m12_storage_end:
