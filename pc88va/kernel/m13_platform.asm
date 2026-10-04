; SPDX-License-Identifier: GPL-2.0-or-later
; PC-88VA adapter for the common FreeDOS block and clock interfaces.
;
; The adapter owns no filesystem policy.  It translates the common driver
; request to the resident bounded sector ABI.  Filesystem policy, caching,
; and DOS error presentation remain in the common kernel.
bits 16
cpu 8086
%include "kernel/disk_buffer.inc"

%include "../hdr/stacks.inc"
%include "boot/loader_abi.inc"

; The common arg macro starts at BP+4 for a near return frame.  These
; platform entry points are called FAR by the medium-model C caller, so their
; first argument starts at BP+6 (the extra word is the return CS).
%macro pc88va_arg_far 1-*
        %assign .argloc 6
        %rep %0
                %ifdef PASCAL
                        %rotate -1
                %endif
                        definearg %1
                %ifdef STDCALL
                        %rotate 1
                %endif
        %endrep
%endmacro

%ifndef PC88VA
%error PC88VA selector is required
%endif
%ifdef NEC98
%error Mixed machine selectors
%endif
%ifdef IBMPC
%error Mixed machine selectors
%endif

extern pc88va_kernel_disk_read_
extern pc88va_kernel_disk_write_
extern pc88va_kernel_firmware_read_one_
extern pc88va_kernel_firmware_write_one_
extern pc88va_m12_request_
extern pc88va_m12_buffer_
extern pc88va_m12_drive_context_
extern _int21_service
extern entry

%include "kernel/m13_segments.inc"
segment M13_PLATFORM_TEXT

; HMA_TEXT invokes the common INT 21 service through a FAR transfer after
; relocation.  The Open Watcom medium-model C body is a FAR CDECL function.
; Entry has the user register-frame words (BP then SS) below the synthetic
; FAR return frame; rebuild that one far argument explicitly before calling
; the C body and remove it after the CDECL return.  This keeps the outer
; entry/IRET frame byte-for-byte intact.
global _pc88va_int21_service_far
global pc88va_int21_service_far_
_pc88va_int21_service_far:
pc88va_int21_service_far_:
        push bp
        mov bp, sp
        ; wrapper entry: [bp+2] outer IP, [bp+4] outer CS,
        ; [bp+6] user BP (pointer offset), [bp+8] user SS (segment).
        push word [bp+8]
        push word [bp+6]
        call far _int21_service
        add sp, 4
        pop bp
        retf

; Measure conventional RAM without trusting a retained BIOS selection.
; The active low-staging profile fits below 256 KiB. Check its upper boundary,
; then sample one byte at the start of each KiB from 256 KiB through 639 KiB.
; Restore every sample after complementary 00h/FFh writes, including failures.
; AX returns the contiguous writable capacity in KiB, or zero if the minimum
; capacity is unavailable. Interrupts are masked during the temporary writes;
; all other registers, flags, and memory-bank settings are preserved.
global PC88VA_MEMORY_KB
%include "kernel/m16_memory_probe.inc"
PC88VA_MEMORY_KB:
        PC88VA_MEASURE_RAM
        retf

; Return the segment where the MZ loader placed the initial kernel image.
; `entry` is the zero-offset PSP/MZ entry, so its relocated segment is the
; image base even though the common resident text is later copied elsewhere.
global PC88VA_IMAGE_SEGMENT
PC88VA_IMAGE_SEGMENT:
        mov ax, seg entry
        retf

; DOS clock hooks use the PC-88VA calendar BIOS.  INT 8Ch/AH=02 returns the
; current binary hour in CH, minute in CL, and second in DH.  The common
; CLOCK$ code expects the IBM-compatible PIT tick count in DX:AX, so convert
; seconds since midnight using the same 1,193,180-Hz scale as sysclk.c.
; Keep the FAR medium-model ABI and preserve every register outside the
; declared AX/CX/DX result set.
global READPCCLOCK
READPCCLOCK:
        push bx
        push si
        push di
        push bp
        push ds
        push es
        mov ah, 02h
        int 8ch

        ; Form seconds since midnight in DX:AX.  The BIOS fields are binary.
        xor bx, bx
        mov bl, dh
        mov si, bx
        xor dx, dx
        xor ax, ax
        mov al, ch
        mov bl, 60
        mul bl
        xor bx, bx
        mov bl, cl
        add ax, bx
        mov bx, 60
        mul bx
        add ax, si
        adc dx, 0

        ; 1,193,180 = 18*65,536 + 13,532.  Keep the 18*s term while
        ; calculating floor(s*13,532/65,536) with 16-bit MUL operations.
        mov si, ax
        mov bx, dx
        mov ax, si
        mov dx, bx
        shl ax, 1
        rcl dx, 1
        mov di, ax
        mov bp, dx
        shl ax, 1
        rcl dx, 1
        shl ax, 1
        rcl dx, 1
        shl ax, 1
        rcl dx, 1
        add ax, di
        adc dx, bp
        push dx
        push ax

        mov ax, si
        mov cx, 13532
        mul cx
        mov di, dx
        mov ax, bx
        mul cx
        add ax, di
        adc dx, 0
        pop cx
        pop bx
        add cx, ax
        adc bx, dx
        mov ax, cx
        mov dx, bx

        pop es
        pop ds
        pop bp
        pop di
        pop si
        pop bx
        ; Medium-model C callers enter through a synthetic FAR call
        ; (push CS followed by a near call).  Consume both return words;
        ; a near RET would leave the return segment on caller stack.
        retf

global WRITEPCCLOCK
WRITEPCCLOCK:
        ; VOID Pascal(ULONG): two argument words, FAR caller frame.
        retf 4

global WRITEATCLOCK
WRITEATCLOCK:
        ; VOID Pascal(BYTE *, BYTE, BYTE, BYTE): four argument words.
        ; The pointer is NEAR data even though the code call is FAR.
        retf 8

; BOOL fl_reset(WORD drive).  AH=00h resets the VA floppy subsystem and
; clears its retry/status state.  CF clear is the common driver's TRUE
; result; CF set is FALSE.  CX is outside the declared clobber set.
global FL_RESET
FL_RESET:
        push bp
        mov bp, sp
        push cx
        mov ch, byte [bp+6]
        xor ah, ah
        int 80h
        sbb ax, ax
        inc ax
        pop cx
        pop bp
        retf 2

; COUNT fl_diskchanged(WORD drive): ask the VA BIOS for its change status.
; AH=09h reports CF clear when the current medium is usable and CF set when
; the controller cannot establish that it is unchanged. Return -1 for that
; uncertainty, not 1 (confirmed change), so the block driver can revalidate.
global FL_DISKCHANGED
FL_DISKCHANGED:
        push bp
        mov bp, sp
        push cx
        mov ch, byte [bp+6]
        mov ah, 09h
        int 80h
        pop cx
        jc .changed
        xor ax, ax
        pop bp
        retf 2
.changed:
        mov ax, -1
        pop bp
        retf 2

; Read logical sector 1 using an explicit VA floppy mode.  This probe is the
; common kernel's media-recognition path; it never reads host image metadata.
; COUNT pc88va_m16_probe_read(WORD drive, WORD mode, UBYTE FAR *buffer).
global PC88VA_M16_PROBE_READ
PC88VA_M16_PROBE_READ:
        push bp
        mov bp, sp
        push bx
        push cx
        push dx
        push es
        pc88va_arg_far drive, mode, {buffer,4}
        mov ch, byte [.drive]
        mov al, byte [.mode]
        mov ah, 0ah
        int 80h
        jc .probe_error
        or ah, ah
        jnz .probe_error
        mov ch, byte [.drive]
        xor cl, cl
        mov dh, 1
        mov dl, byte [.mode]
        and dl, 0fh
        les bp, [.buffer]
        mov ax, 8101h
        int 80h
        jc .probe_error
        or ah, ah
        jnz .probe_error
        xor ax, ax
        jmp short .probe_return
.probe_error:
        mov al, ah
        xor ah, ah
        or ax, ax
        jnz .probe_return
        mov ax, 0ffffh
.probe_return:
        pop es
        pop dx
        pop cx
        pop bx
        pop bp
        retf 8

; Install a validated per-drive BIOS/FDC profile for subsequent block I/O.
; COUNT pc88va_m16_set_profile(WORD drive, WORD mode, WORD total,
;                              WORD sectors_per_track, WORD heads).
global PC88VA_M16_SET_PROFILE
PC88VA_M16_SET_PROFILE:
        push bp
        mov bp, sp
        push bx
        push cx
        push dx
        pc88va_arg_far drive, mode, total, spt, heads
        mov ax, [.drive]
        cmp ax, 1
        ja .profile_invalid
        mov ax, [.mode]
        cmp ax, 0002h
        je .profile_512
        cmp ax, 0012h
        je .profile_512
        cmp ax, 0022h
        je .profile_512
        cmp ax, 0023h
        jne .profile_invalid
        mov dx, 1024
        jmp short .profile_validate
.profile_512:
        mov dx, 512
.profile_validate:
        mov ax, [.total]
        or ax, ax
        jz .profile_invalid
        mov ax, [.spt]
        or ax, ax
        jz .profile_invalid
        cmp ax, 18
        ja .profile_invalid
        mov ax, [.heads]
        cmp ax, 2
        jne .profile_invalid

        mov cx, dx
        mov ax, [.drive]
        call pc88va_m16_profile_index
        ; All arguments have been validated before changing the active entry.
        mov ax, [.mode]
        mov [cs:pc88va_m16_profiles_+bx+0], ax
        mov ax, [.total]
        mov [cs:pc88va_m16_profiles_+bx+2], ax
        mov ax, [.spt]
        mov [cs:pc88va_m16_profiles_+bx+4], ax
        mov ax, [.heads]
        mov [cs:pc88va_m16_profiles_+bx+6], ax
        mov [cs:pc88va_m16_profiles_+bx+8], cx
        xor ax, ax
        jmp short .profile_return
.profile_invalid:
        mov ax, 1
.profile_return:
        pop dx
        pop cx
        pop bx
        pop bp
        retf 10

; AX=physical unit (0 or 1), BX=10-byte profile offset.
pc88va_m16_profile_index:
        cmp ax, 1
        ja .profile_index_invalid
        mov bx, ax
        shl bx, 1
        mov dx, ax
        shl dx, 1
        shl dx, 1
        shl dx, 1
        add bx, dx
        clc
        ret
.profile_index_invalid:
        stc
        ret

; Bind the selected unit's validated geometry to the reusable resident request.
; AX=physical unit.  Returns AX=0 on success, AX=1 for an invalid unit.
pc88va_m16_bind_request:
        call pc88va_m16_profile_index
        jc .bind_invalid
        mov [cs:pc88va_m12_request_+RD_DRIVE_CONTEXT], ax
        mov ax, [cs:pc88va_m16_profiles_+bx+2]
        mov [cs:pc88va_m12_request_+RD_TOTAL_SECTORS], ax
        mov ax, [cs:pc88va_m16_profiles_+bx+4]
        mov [cs:pc88va_m12_request_+RD_SECTORS_TRACK], ax
        mov ax, [cs:pc88va_m16_profiles_+bx+6]
        mov [cs:pc88va_m12_request_+RD_HEADS], ax
        mov ax, [cs:pc88va_m16_profiles_+bx+8]
        mov [cs:pc88va_m12_request_+RD_SECTOR_BYTES], ax
        xor ax, ax
        ret
.bind_invalid:
        mov ax, 1
        ret

; Common driver read: drive, head, cylinder, sector, count, ES:BX buffer.
; M12 receives one sector per request.  Geometry and sector bytes come from
; the profile installed by common-kernel media recognition.
global FL_READ
FL_READ:
        push bp
        mov bp, sp
        push ds
        push si
        push di
        push bx
        push cx
        push dx
        push es
        pc88va_arg_far drive, head, track, sector, count, {buffer,4}
        mov ax, [.drive]
        call pc88va_m16_bind_request
        or ax, ax
        jnz .bad
        mov word [cs:pc88va_m12_request_+RD_VERSION], 1
        mov word [cs:pc88va_m12_request_+RD_OFFSET], pc88va_m12_buffer_
        mov word [cs:pc88va_m12_request_+RD_SEGMENT], cs
        mov word [cs:pc88va_m12_request_+RD_CAPACITY], PC88VA_DISK_BUFFER_BYTES
        mov ax, [.head]
        cmp ax, [cs:pc88va_m12_request_+RD_HEADS]
        jae .bad
        mov ax, [.sector]
        cmp ax, 1
        jb .bad
        cmp ax, [cs:pc88va_m12_request_+RD_SECTORS_TRACK]
        ja .bad
        mov ax, [.count]
        or ax, ax
        jz .bad
        mov cx, ax
        mov ax, [.track]
        cmp ax, 80
        jae .bad
        ; lba = ((cylinder * heads) + head) * sectors/track + sector - 1.
        shl ax, 1
        add ax, [.head]
        mul word [cs:pc88va_m12_request_+RD_SECTORS_TRACK]
        or dx, dx
        jnz .bad
        mov dx, [.sector]
        dec dx
        add ax, dx
        jc .bad
        mov si, ax
        add ax, cx
        jc .bad
        cmp ax, [cs:pc88va_m12_request_+RD_TOTAL_SECTORS]
        ja .bad
        les di, [.buffer]
        mov dx, [cs:pc88va_m12_request_+RD_SECTOR_BYTES]
        call pc88va_validate_buffer_request
        jc .bad
.next:
        ; The full extent was validated before any sector transfer.
        mov word [cs:pc88va_m12_request_+RD_LBA], si
        mov word [cs:pc88va_m12_request_+RD_COUNT], 1
        ; The resident validator requires an explicit qualified far adapter.
        ; Keep the callback binding in the request built for each DOS read;
        ; a zero binding is a contract error, not a firmware result.
        mov word [cs:pc88va_m12_request_+RD_ADAPTER_OFFSET], pc88va_kernel_firmware_read_one_
        mov word [cs:pc88va_m12_request_+RD_ADAPTER_SEGMENT], cs
        mov word [cs:pc88va_m12_request_+RD_RETRIES], 3
        mov word [cs:pc88va_m12_request_+RD_COMPLETED], 0
        mov ax, pc88va_m12_request_
        push ds
        push cs
        pop ds
        call pc88va_kernel_disk_read_
        pop ds
        or ax, ax
        jnz .read_io_error
        push cx
        push ds
        push cs
        pop ds
        mov si, pc88va_m12_buffer_
        mov cx, [cs:pc88va_m12_request_+RD_SECTOR_BYTES]
        shr cx, 1
        cld
        rep movsw
        pop ds
        pop cx
        ; SI is the source scratch pointer; recover the next LBA from the
        ; request record rather than relying on the copied-byte count.
        mov si, [cs:pc88va_m12_request_+RD_LBA]
        inc si
        ; REP MOVSW already advanced DI by exactly one sector. Advancing it
        ; again would leave a gap and overwrite beyond the caller's buffer.
        dec cx
        jnz .next
        xor ax, ax
        jmp short .return
.read_io_error:
        cmp ax, 5
        jne .read_generic_error
        call pc88va_map_va_write_status
        jmp short .return
.read_generic_error:
        mov ax, 2                 ; DOS general I/O error
.bad:
        mov ax, 2
.return:
        pop es
        pop dx
        pop cx
        pop bx
        pop di
        pop si
        pop ds
        pop bp
        retf 14

; Translate the VA AH=82 status byte into the common fl_* status contract.
; The common dskerr() path distinguishes write protection (3), not-ready
; (80h), CRC (10h), and not-found (04h); returning the raw VA status would
; misclassify those failures as a generic command error.
pc88va_map_va_write_status:
        cmp ax, 5
        jne .generic
        mov ax, [cs:pc88va_m12_request_+RD_ADAPTER_STATUS]
        cmp ax, 5
        je .write_protect
        cmp ax, 4
        je .not_ready
        cmp ax, 0dh
        je .not_ready
        cmp ax, 6
        je .crc
        cmp ax, 7
        je .crc
        cmp ax, 8
        jb .generic
        cmp ax, 0ch
        ja .generic
        mov ax, 04h
        ret
.write_protect:
        mov ax, 3
        ret
.not_ready:
        mov ax, 80h
        ret
.crc:
        mov ax, 10h
        ret
.generic:
        mov ax, 2
        ret

; Validate the complete CX-sector caller extent before the first transfer.
; DX is the active bytes-per-sector value from the selected drive profile.
pc88va_validate_buffer_request:
        push ax
        push bx
        push dx
        push di
        mov bx, dx
        mov ax, cx
        or ax, ax
        jz .request_buffer_invalid
        dec ax
        mul bx
        or dx, dx
        jnz .request_buffer_invalid
        add di, ax
        jc .request_buffer_invalid
        ; The last sector has the highest offset and physical end. Neither
        ; the offset arithmetic nor the physical address may wrap.
        call pc88va_validate_buffer_size
        jmp short .request_buffer_restore
.request_buffer_invalid:
        stc
.request_buffer_restore:
        pop di
        pop dx
        pop bx
        pop ax
        ret

; Validate one profile-sized ES:DI sector without changing adapter registers.
; BX is bytes per sector. The VA BIOS requires a contiguous transfer that
; does not cross FFFFFh or wrap the caller's 16-bit offset.
pc88va_validate_buffer_size:
        push ax
        push dx
        push cx
        mov ax, di
        add ax, bx
        jnc .buffer_offset_valid
        ; A carry is valid only when the half-open end is exactly 10000h.
        or ax, ax
        jnz .buffer_invalid
.buffer_offset_valid:
        mov ax, es
        mov dx, ax
        mov cl, 12
        shr dx, cl
        mov cl, 4
        shl ax, cl
        add ax, di
        adc dx, 0
        add ax, bx
        adc dx, 0
        cmp dx, 16
        ja .buffer_invalid
        jb .buffer_valid
        or ax, ax
        jnz .buffer_invalid
.buffer_valid:
        clc
        jmp short .buffer_restore
.buffer_invalid:
        stc
.buffer_restore:
        pop cx
        pop dx
        pop ax
        ret

; COUNT fl_write(WORD drive, WORD head, WORD cylinder, WORD sector,
;                WORD count, UBYTE FAR *buffer).
; The resident transfer core performs all range, capacity, physical-end,
; retry, and completed-byte accounting.  The adapter copies one sector at a
; time into its resident scratch buffer so the VA AH=82h callback never sees
; an unvalidated DOS buffer or a segment-wrapping transfer.
global FL_WRITE
FL_WRITE:
        push bp
        mov bp, sp
        push ds
        push si
        push di
        push bx
        push cx
        push dx
        push es
        pc88va_arg_far drive, head, track, sector, count, {buffer,4}
        mov ax, [.drive]
        call pc88va_m16_bind_request
        or ax, ax
        jnz .write_bad
        mov word [cs:pc88va_m12_request_+RD_VERSION], 1
        mov word [cs:pc88va_m12_request_+RD_OFFSET], pc88va_m12_buffer_
        mov word [cs:pc88va_m12_request_+RD_SEGMENT], cs
        mov word [cs:pc88va_m12_request_+RD_CAPACITY], PC88VA_DISK_BUFFER_BYTES
        mov ax, [.head]
        cmp ax, [cs:pc88va_m12_request_+RD_HEADS]
        jae .write_bad
        mov ax, [.sector]
        cmp ax, 1
        jb .write_bad
        cmp ax, [cs:pc88va_m12_request_+RD_SECTORS_TRACK]
        ja .write_bad
        mov ax, [.count]
        or ax, ax
        jz .write_bad
        mov cx, ax
        mov ax, [.track]
        cmp ax, 80
        jae .write_bad
        shl ax, 1
        add ax, [.head]
        mul word [cs:pc88va_m12_request_+RD_SECTORS_TRACK]
        or dx, dx
        jnz .write_bad
        mov dx, [.sector]
        dec dx
        add ax, dx
        jc .write_bad
        mov si, ax
        add ax, cx
        jc .write_bad
        cmp ax, [cs:pc88va_m12_request_+RD_TOTAL_SECTORS]
        ja .write_bad
        les di, [.buffer]
        mov dx, [cs:pc88va_m12_request_+RD_SECTOR_BYTES]
        call pc88va_validate_buffer_request
        jc .write_bad
.write_next:
        ; The full extent was validated before any sector transfer.
        push cx
        push si
        push di
        push ds
        push es
        mov si, di
        mov ax, es
        mov ds, ax
        push cs
        pop es
        mov di, pc88va_m12_buffer_
        mov cx, [cs:pc88va_m12_request_+RD_SECTOR_BYTES]
        shr cx, 1
        cld
        rep movsw
        pop es
        pop ds
        pop di
        pop si
        pop cx
        mov word [cs:pc88va_m12_request_+RD_LBA], si
        mov word [cs:pc88va_m12_request_+RD_COUNT], 1
        mov word [cs:pc88va_m12_request_+RD_ADAPTER_OFFSET], pc88va_kernel_firmware_write_one_
        mov word [cs:pc88va_m12_request_+RD_ADAPTER_SEGMENT], cs
        mov word [cs:pc88va_m12_request_+RD_RETRIES], 3
        mov word [cs:pc88va_m12_request_+RD_COMPLETED], 0
        mov ax, pc88va_m12_request_
        push ds
        push cs
        pop ds
        call pc88va_kernel_disk_write_
        pop ds
        or ax, ax
        jz .write_sector_ok
        call pc88va_map_va_write_status
        jmp short .write_return
.write_sector_ok:
        mov si, [cs:pc88va_m12_request_+RD_LBA]
        inc si
        dec cx
        jz .write_complete
        mov ax, [cs:pc88va_m12_request_+RD_SECTOR_BYTES]
        add di, ax
        jc .write_bad
        jmp .write_next
.write_complete:
        xor ax, ax
        jmp short .write_return
.write_bad:
        mov ax, 2
.write_return:
        pop es
        pop dx
        pop cx
        pop bx
        pop di
        pop si
        pop ds
        pop bp
        retf 14

; COUNT fl_verify(...): read each requested sector through the production VA
; path and compare it with the caller buffer.  A mismatch is reported as the
; common CRC/data error; no write is implied by verification.
global FL_VERIFY
FL_VERIFY:
        push bp
        mov bp, sp
        push ds
        push si
        push di
        push bx
        push cx
        push dx
        push es
        pc88va_arg_far drive, head, track, sector, count, {buffer,4}
        mov ax, [.drive]
        call pc88va_m16_bind_request
        or ax, ax
        jnz .verify_bad
        mov word [cs:pc88va_m12_request_+RD_VERSION], 1
        mov word [cs:pc88va_m12_request_+RD_OFFSET], pc88va_m12_buffer_
        mov word [cs:pc88va_m12_request_+RD_SEGMENT], cs
        mov word [cs:pc88va_m12_request_+RD_CAPACITY], PC88VA_DISK_BUFFER_BYTES
        mov ax, [.head]
        cmp ax, [cs:pc88va_m12_request_+RD_HEADS]
        jae .verify_bad
        mov ax, [.sector]
        cmp ax, 1
        jb .verify_bad
        cmp ax, [cs:pc88va_m12_request_+RD_SECTORS_TRACK]
        ja .verify_bad
        mov ax, [.count]
        or ax, ax
        jz .verify_bad
        mov cx, ax
        mov ax, [.track]
        cmp ax, 80
        jae .verify_bad
        shl ax, 1
        add ax, [.head]
        mul word [cs:pc88va_m12_request_+RD_SECTORS_TRACK]
        or dx, dx
        jnz .verify_bad
        mov dx, [.sector]
        dec dx
        add ax, dx
        jc .verify_bad
        mov si, ax
        add ax, cx
        jc .verify_bad
        cmp ax, [cs:pc88va_m12_request_+RD_TOTAL_SECTORS]
        ja .verify_bad
        les di, [.buffer]
        mov dx, [cs:pc88va_m12_request_+RD_SECTOR_BYTES]
        call pc88va_validate_buffer_request
        jc .verify_bad
.verify_next:
        ; The full extent was validated before any sector transfer.
        mov word [cs:pc88va_m12_request_+RD_LBA], si
        mov word [cs:pc88va_m12_request_+RD_COUNT], 1
        mov word [cs:pc88va_m12_request_+RD_ADAPTER_OFFSET], pc88va_kernel_firmware_read_one_
        mov word [cs:pc88va_m12_request_+RD_ADAPTER_SEGMENT], cs
        mov word [cs:pc88va_m12_request_+RD_RETRIES], 3
        mov word [cs:pc88va_m12_request_+RD_COMPLETED], 0
        mov ax, pc88va_m12_request_
        push ds
        push cs
        pop ds
        call pc88va_kernel_disk_read_
        pop ds
        or ax, ax
        jnz .verify_io_error
        push cx
        push si
        push di
        push ds
        push es
        mov si, di
        mov ax, es
        mov ds, ax
        push cs
        pop es
        mov di, pc88va_m12_buffer_
        mov cx, [cs:pc88va_m12_request_+RD_SECTOR_BYTES]
        shr cx, 1
        cld
        repe cmpsw
        pop es
        pop ds
        pop di
        pop si
        pop cx
        jne .verify_mismatch
        mov si, [cs:pc88va_m12_request_+RD_LBA]
        inc si
        dec cx
        jz .verify_complete
        mov ax, [cs:pc88va_m12_request_+RD_SECTOR_BYTES]
        add di, ax
        jc .verify_bad
        jmp .verify_next
.verify_complete:
        xor ax, ax
        jmp short .verify_return
.verify_io_error:
        cmp ax, 5
        jne .verify_generic_error
        call pc88va_map_va_write_status
        jmp short .verify_return
.verify_generic_error:
        mov ax, 2
        jmp short .verify_return
.verify_mismatch:
        mov ax, 10h
        jmp short .verify_return
.verify_bad:
        mov ax, 2
.verify_return:
        pop es
        pop dx
        pop cx
        pop bx
        pop di
        pop si
        pop ds
        pop bp
        retf 14

; Format and the legacy/non-VA extensions remain explicitly unsupported.
%macro reject_word 2
global %1
%1:
        pop ax
        %if %2 > 0
        add sp, %2
        %endif
        push ax
        mov ax, 5
        ret
%endmacro

reject_word FL_FORMAT, 12
reject_word FL_SETDISKTYPE, 4
reject_word FL_SETMEDIATYPE, 6
reject_word FL_LBA_READWRITE, 8

global FL_READKEY
FL_READKEY:
        xor ax, ax
        ret

global FLOPPY_CHANGE
FLOPPY_CHANGE:
        mov ax, 0ffffh
        ret

; The initial A: and B: entries preserve the exact M15 1024-byte profile
; until runtime media recognition installs a validated BPB-derived profile.
align 2, db 0
global pc88va_m16_profiles_
pc88va_m16_profiles_:
        dw 0023h, 1280, 8, 2, 1024
        dw 0023h, 1280, 8, 2, 1024
