; SPDX-License-Identifier: GPL-2.0-or-later
; M13 resident unpack bridge for a large common FreeDOS kernel.
;
; The accepted M08 carrier has one 16-bit transformed allocation.  The
; normal path stores an LZSS-compressed common kernel in that allocation and
; expands the exact body into its separately owned destination.  The PC-88VA
; low-staging path instead compacts the MZ body in place, keeps the compressed
; source and history ring in one bounded segment, and expands the resident
; image below it.  The two paths share the same bounded decoder and handoff.
bits 16
cpu 8086
org 0

%ifndef M13_LOAD_SEG
%error M13_LOAD_SEG is required
%endif
%ifndef M13_IMAGE_SEG
%error M13_IMAGE_SEG is required
%endif
%ifndef M13_FILE_SEG
%error M13_FILE_SEG is required
%endif
%ifndef M13_SCRATCH_SEG
%error M13_SCRATCH_SEG is required
%endif
%ifndef M13_PAYLOAD_OFFSET
%error M13_PAYLOAD_OFFSET is required
%endif
%ifndef M13_PAYLOAD_SIZE
%error M13_PAYLOAD_SIZE is required
%endif
%ifndef M13_DATA_SIZE
%error M13_DATA_SIZE is required
%endif
%ifndef M13_RELOC_INPUT_OFFSET
%error M13_RELOC_INPUT_OFFSET is required
%endif
%ifndef M13_RELOC_SOURCE_OFFSET
%error M13_RELOC_SOURCE_OFFSET is required
%endif
%ifndef M13_RELOC_COUNT
%error M13_RELOC_COUNT is required
%endif
%ifndef M13_OUTPUT_SIZE
%error M13_OUTPUT_SIZE is required
%endif
%ifndef M13_SOURCE_OFFSET
%error M13_SOURCE_OFFSET is required
%endif
%define M13_SOURCE_END (M13_SOURCE_OFFSET + M13_PAYLOAD_SIZE)
%ifndef M13_ORIG_SS
%error M13_ORIG_SS is required
%endif
%ifndef M13_ORIG_SP
%error M13_ORIG_SP is required
%endif
%ifndef M13_ORIG_CS
%error M13_ORIG_CS is required
%endif
%ifndef M13_ORIG_IP
%error M13_ORIG_IP is required
%endif
%ifndef M13_SPLIT_INIT
%define M13_SPLIT_INIT 0
%endif
%ifndef M13_IN_PLACE
%define M13_IN_PLACE 0
%endif
%ifndef M13_COMPACT_BRIDGE
%define M13_COMPACT_BRIDGE 0
%endif
%if M13_COMPACT_BRIDGE && !M13_IN_PLACE
%error Compact bridge requires the in-place carrier
%endif
%ifndef M13_BRIDGE_IN_ALLOCATION
%define M13_BRIDGE_IN_ALLOCATION 0
%endif
%ifndef M13_BRIDGE_STACK_SEG
%error M13_BRIDGE_STACK_SEG is required
%endif
%ifndef M13_BRIDGE_STACK_SP
%error M13_BRIDGE_STACK_SP is required
%endif

; Compressed source follows the history window. Relocation records have a
; separate checked interval in the bridge segment, below its live stack.
%ifndef M13_RING_OFFSET
%define M13_RING_OFFSET 0
%endif
%ifndef M13_RING_SEG
%if M13_IN_PLACE
%define M13_RING_SEG M13_FILE_SEG
%else
%define M13_RING_SEG M13_SCRATCH_SEG
%endif
%endif
%define M13_RING_BYTES 4096
%define M13_EXTERNAL_RING (M13_IN_PLACE && (M13_RING_SEG != M13_FILE_SEG))
%if M13_IN_PLACE && (M13_RING_OFFSET + M13_RING_BYTES) > 0xFFF0
%error Low-staging history ring exceeds its owned segment extent
%endif

; The bootstrap runs at the transformed allocation base.  In low-staging mode
; that is already the immutable kernel-file segment; the ordinary path moves
; the bridge there before any output is written.
%include "m16_runtime.inc"

m13_unpack_start:
    cli
%ifdef M16_BOOT_RECORD_OFFSET
    jmp m16_prepare
%endif
m13_unpack_start_ready:
%if M13_IN_PLACE
    ; The MZ transform has already moved the body to offset zero in the
    ; low staging segment.  Keep the bridge in place and use a separate
    ; temporary stack before expanding the resident image.
    mov [cs:m13_saved_dx], dx
    jmp m13_unpack_run
%elif M13_BRIDGE_IN_ALLOCATION
    ; The file was initially staged at 1340h, but the transformed allocation
    ; at the dead low staging interval is the bridge's execution home. Keeping
    ; the bridge there avoids overwriting the resident image at 1000h.
    mov ax, M13_LOAD_SEG
    mov ds, ax
    mov [cs:m13_saved_dx], dx
    jmp m13_unpack_run
%else
    mov ax, M13_LOAD_SEG
    mov ds, ax
    mov [cs:m13_saved_dx], dx
    M13_MOV_FILE ax
    mov es, ax
    xor si, si
    xor di, di
    mov cx, m13_unpack_end - m13_unpack_start
    rep movsb
    M13_MOV_FILE ax
    push ax
    mov ax, m13_unpack_run
    push ax
    retf
%endif

m13_unpack_run:
    ; The copied bridge owns a safe stack outside both output intervals.
    M13_MOV_STACK ax
    mov ss, ax
    mov sp, M13_BRIDGE_STACK_SP
    cld

%if !M13_IN_PLACE
    ; Copy the compressed payload out of the transformed carrier before
    ; expanding output over that carrier.
    mov ax, M13_LOAD_SEG
    mov ds, ax
    mov si, M13_PAYLOAD_OFFSET
    mov ax, M13_SCRATCH_SEG
    mov es, ax
    mov di, M13_SOURCE_OFFSET
    mov cx, M13_DATA_SIZE
    rep movsb

    ; The records need no history window. Keep them in the scratch segment
    ; after the compressed stream when the bridge remains in the allocation;
    ; otherwise they are copied to the file-segment bridge workspace.
    mov si, M13_RELOC_INPUT_OFFSET
    mov ax, M13_LOAD_SEG
    mov ds, ax
%if M13_BRIDGE_IN_ALLOCATION
    mov ax, M13_SCRATCH_SEG
%else
    M13_MOV_FILE ax
%endif
    mov es, ax
    mov di, M13_RELOC_SOURCE_OFFSET
    mov cx, M13_RELOC_COUNT * 4
    rep movsb
%endif

    ; Clear the 4 KiB history window. In the external-ring low-staging mode,
    ; CS remains the compressed source and DS becomes the separate ring.
%if M13_IN_PLACE
    M13_MOV_FILE ax
    mov ds, ax
%else
    mov ax, M13_SCRATCH_SEG
    mov ds, ax
%endif
    M13_MOV_RING ax
    mov es, ax
    mov di, M13_RING_OFFSET
    xor al, al
    mov cx, M13_RING_BYTES
    rep stosb
%if M13_EXTERNAL_RING
    M13_MOV_RING ax
    mov ds, ax
%endif
    M13_MOV_IMAGE ax, M13_IMAGE_SEG
    mov es, ax
    xor di, di
    xor si, si
    mov word [cs:m13_source], M13_SOURCE_OFFSET
    mov ax, M13_OUTPUT_LO
    mov [cs:m13_remaining_lo], ax
    mov ax, M13_OUTPUT_HI
    mov [cs:m13_remaining_hi], ax
    M13_MOV_IMAGE ax, M13_IMAGE_SEG
    mov [cs:m13_dest_segment], ax
    ; The flags begin at zero in the loaded bridge image.

.token:
    cmp word [cs:m13_remaining_hi], 0
    jne .have_output
    cmp word [cs:m13_remaining_lo], 0
    je .complete
.have_output:
    call m13_next_flag
    jc .fail
    test byte [cs:m13_flags], 1
    jnz .match
    call m13_consume_flag

    call m13_next_byte
    jc .fail
    call m13_emit
    jc .fail
    jmp .token

.match:
    call m13_consume_flag
    call m13_next_byte
    jc .fail
    mov dl, al
    call m13_next_byte
    jc .fail
    mov bl, al
    mov ah, bl
    and ah, 0xf0
    mov cl, 4
    shr ah, cl
    mov al, dl
    inc ax
    mov dx, ax
    mov al, bl
    and al, 0x0f
    xor ah, ah
    add ax, 3
    mov cx, ax
    ; The token stores a backwards distance.  Convert it to the current
    ; ring index before emitting an overlapping match.
    mov ax, si
    sub ax, dx
    and ax, M13_RING_BYTES - 1
    mov [cs:m13_match_offset], ax
.match_byte:
    cmp cx, 0
    je .token
    cmp word [cs:m13_remaining_hi], 0
    jne .match_output_ok
    cmp word [cs:m13_remaining_lo], 0
    ; A final LZSS match may be longer than the exact body tail.  The
    ; bounded MZ output length is authoritative; stop at it and validate the
    ; relocations rather than rejecting an otherwise complete body.
    je .complete
.match_output_ok:
    mov bx, [cs:m13_match_offset]
    add bx, M13_RING_OFFSET
    mov al, [ds:bx]
    call m13_emit
    jc .fail
    inc word [cs:m13_match_offset]
    cmp word [cs:m13_match_offset], M13_RING_BYTES
    jb .match_next
    sub word [cs:m13_match_offset], M13_RING_BYTES
.match_next:
    loop .match_byte
    jmp .token

.complete:
    ; Initialize all non-file-backed storage, including the exact linked
    ; stack. The host layout validator bounds this one-segment clear.
    M13_MOV_IMAGE ax, M13_ZERO_SEG
    mov es, ax
    mov di, M13_ZERO_OFF
    mov cx, M13_ZERO_BYTES
    xor ax, ax
    rep stosb
    ; Apply the original MZ relocation words after the exact body has been
    ; expanded. The records are retained below the bridge stack.
%if M13_BRIDGE_IN_ALLOCATION
    mov ax, M13_SCRATCH_SEG
%else
    M13_MOV_FILE ax
%endif
    mov ds, ax
    mov si, M13_RELOC_SOURCE_OFFSET
    mov cx, M13_RELOC_COUNT
.relocate:
    jcxz .relocated
    mov di, [ds:si]
    mov bx, [ds:si+2]
    M13_MOV_IMAGE ax, M13_IMAGE_SEG
    add ax, bx
    mov es, ax
%ifdef M16_BOOT_RECORD_OFFSET
    ; Split INIT references have one builder-qualified relative segment.
    ; Rebase them separately when INIT is compacted below its legacy slot.
    cmp word [es:di], M13_INIT_DEST_SEG - M13_IMAGE_SEG
    jne .resident_fixup
    mov bx, [cs:m16_init_delta]
    add word [es:di], bx
.resident_fixup:
%endif
    M13_MOV_IMAGE bx, M13_IMAGE_SEG
    add word [es:di], bx
    add si, 4
    dec cx
    jmp .relocate
.relocated:
%if M13_SPLIT_INIT
    ; The original image is now fully relocated. Copy INIT first, while its
    ; low source is intact, then seed the final assembly-text slot over that
    ; dead source. The original bootstrap stack remains separate until M10.
    M13_MOV_IMAGE ax, M13_INIT_SOURCE_SEG
    mov ds, ax
    xor si, si
    M13_MOV_IMAGE ax, M13_INIT_DEST_SEG
%ifdef M16_BOOT_RECORD_OFFSET
    add ax, [cs:m16_init_delta]
%endif
    mov es, ax
    xor di, di
    mov cx, M13_INIT_BYTES
    rep movsb
    xor ax, ax
    mov cx, M13_INIT_ZERO_BYTES
    rep stosb
    M13_MOV_IMAGE ax, M13_HMA_SOURCE_SEG
    mov ds, ax
    xor si, si
    M13_MOV_IMAGE ax, M13_HMA_DEST_SEG
    mov es, ax
    xor di, di
    mov cx, M13_HMA_BYTES
    rep movsb
%endif
    M13_MOV_IMAGE ax, M13_IMAGE_SEG
    mov es, ax
%ifdef M16_BOOT_RECORD_OFFSET
    call m16_fill_layout
%endif
    M13_MOV_IMAGE ax, M13_IMAGE_SEG + M13_ORIG_SS
    mov ss, ax
    mov sp, M13_ORIG_SP
    M13_MOV_IMAGE ax, M13_IMAGE_SEG
    mov ds, ax
    mov es, ax
    mov dx, [cs:m13_saved_dx]
%if M13_IN_PLACE || M13_BRIDGE_IN_ALLOCATION
    M13_MOV_IMAGE ax, M13_IMAGE_SEG + M13_ORIG_CS
    push ax
    mov ax, M13_ORIG_IP
    push ax
    retf
%else
    ; Cross a resident trampoline to flush the CPU fetch stream after the
    ; expanded image has replaced the carrier bytes.
    M13_MOV_FILE ax
    push ax
    mov ax, m13_flush_code
    push ax
    retf
%endif

.fail:
    cli
    hlt
    jmp .fail

; The in-place handoff returns directly above. Its legacy fetch trampoline
; is unreachable and can be omitted by an explicitly compact carrier build.
%if !M13_COMPACT_BRIDGE
m13_flush_code:
    times 16 nop
    M13_MOV_IMAGE ax, M13_IMAGE_SEG + M13_ORIG_CS
    push ax
    mov ax, M13_ORIG_IP
    push ax
    retf
%endif

; Load the next flag bit.  Carry means that the bounded source is exhausted.
m13_next_flag:
    cmp byte [cs:m13_flag_bits], 0
    jne .ready
    cmp word [cs:m13_source], M13_SOURCE_END
    jae .bad
    mov bx, [cs:m13_source]
%if M13_EXTERNAL_RING
    mov al, [cs:bx]
%else
    mov al, [ds:bx]
%endif
    mov [cs:m13_flags], al
    inc word [cs:m13_source]
    mov byte [cs:m13_flag_bits], 8
.ready:
    clc
    ret
.bad:
    stc
    ret

m13_consume_flag:
    mov al, [cs:m13_flags]
    shr al, 1
    mov [cs:m13_flags], al
    dec byte [cs:m13_flag_bits]
    ret

; Return one bounded source byte in AL, with carry on exhaustion.
m13_next_byte:
    cmp word [cs:m13_source], M13_SOURCE_END
    jae .bad
    mov bx, [cs:m13_source]
%if M13_EXTERNAL_RING
    mov al, [cs:bx]
%else
    mov al, [ds:bx]
%endif
    inc word [cs:m13_source]
    clc
    ret
.bad:
    stc
    ret

; Emit AL to the contiguous real-mode output and to the history ring.
m13_emit:
    cmp word [cs:m13_remaining_hi], 0
    jne .emit_allowed
    cmp word [cs:m13_remaining_lo], 0
    je .bad
.emit_allowed:
    push ax
    mov [es:di], al
    inc di
    jnz .destination_ok
    mov ax, [cs:m13_dest_segment]
    add ax, 0x1000
    mov [cs:m13_dest_segment], ax
    mov es, ax
.destination_ok:
    pop ax
    mov [ds:si+M13_RING_OFFSET], al
    inc si
    and si, M13_RING_BYTES - 1
    sub word [cs:m13_remaining_lo], 1
    jnc .remaining_ok
    dec word [cs:m13_remaining_hi]
.remaining_ok:
    clc
    ret
.bad:
    stc
    ret

m13_saved_dx:       dw 0
%ifdef M16_BOOT_RECORD_OFFSET
m16_saved_file_segment: dw 0
%endif
m13_source:         dw 0
m13_remaining_lo:   dw 0
m13_remaining_hi:   dw 0
m13_dest_segment:   dw 0
m13_match_offset:   dw 0
m13_flags:          db 0
m13_flag_bits:      db 0
%ifdef M16_BOOT_RECORD_OFFSET
    M16_RUNTIME_CODE
%endif
m13_unpack_end:
