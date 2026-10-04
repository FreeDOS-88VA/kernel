; SPDX-License-Identifier: GPL-2.0-or-later
; Superfloppy bootstrap. Only stage 2 has a builder-declared contiguous extent.
; The media builder overlays the original BPB and declared signature slots.
bits 16
cpu 8086
org S1_IMAGE_OFFSET
%include "loader_abi.inc"
%ifndef PC88VA_PROFILE_VERSION
%error Validated loader profile required
%endif
%ifnmacro PC88VA_FIRMWARE_READ_ONE 0
%error Qualified firmware adapter required
%endif
%if S1_STAGE2_COUNT < 1 || S1_STAGE2_COUNT * S2_SECTOR_BYTES > S2_STAGE2_CAPACITY
%error Stage-2 extent exceeds owned memory
%endif
%if S1_STAGE2_LBA < 1 || S1_STAGE2_LBA + S1_STAGE2_COUNT > S2_TOTAL_SECTORS
%error Stage-2 extent exceeds media
%endif
    jmp short pc88va_stage1_entry
    nop
    times 62-($-$$) db 0
pc88va_stage1_entry:
    ; Capture no state by reading firmware memory. The qualified overlay
    ; supplies the opaque boot-source context and call FLAGS explicitly.
    cli
    mov ax, cs
    cmp ax, S1_ENTRY_SEGMENT
    jne pc88va_stage1_fail
    mov ds, ax
    mov ax, S2_STACK_SEGMENT
    mov ss, ax
    mov sp, S2_STACK_POINTER
    cld
    mov si, pc88va_stage1_disk
%if S2_SECTOR_BYTES = 512
    call pc88va_stage1_read_extent
%else
    call pc88va_disk_read_core
%endif
    jc pc88va_stage1_fail
    mov dx, S1_DRIVE_CONTEXT
    mov bx, S1_CALL_FLAGS
    jmp S2_STAGE2_SEGMENT:0
pc88va_stage1_fail:
    cli
    jmp short pc88va_stage1_fail
pc88va_stage1_adapter:
%define PC88VA_CALL_FLAGS pc88va_stage1_call_flags
    PC88VA_FIRMWARE_READ_ONE
align 2, db 0
pc88va_stage1_call_flags: dw S1_CALL_FLAGS
pc88va_stage1_disk:
    dw 1, S1_STAGE2_LBA, S1_STAGE2_COUNT, 0, S2_STAGE2_SEGMENT
    dw S2_STAGE2_CAPACITY, S2_TOTAL_SECTORS, S2_SECTORS_TRACK
    dw S2_HEADS, S2_SECTOR_BYTES, S1_DRIVE_CONTEXT
    dw pc88va_stage1_adapter, S1_ENTRY_SEGMENT, 0
    times 10 dw 0
%if S2_SECTOR_BYTES = 512
; This immutable extent is checked by the builder and the assembly assertions.
; Stage 2 retains the full shared request validator for filesystem reads.
; Keep the complete first-stage reader within the single ROM-loaded sector.
pc88va_stage1_read_extent:
    mov word [si+RD_CURRENT_LBA], S1_STAGE2_LBA
    mov word [si+RD_REMAINING], S1_STAGE2_COUNT
    mov word [si+RD_CURRENT_OFFSET], 0
    mov word [si+RD_CURRENT_SEGMENT], S2_STAGE2_SEGMENT
.sector:
    mov ax, [si+RD_CURRENT_LBA]
    xor dx, dx
    div word [si+RD_SECTORS_TRACK]
    inc dx
    mov [si+RD_SECTOR], dx
    xor dx, dx
    div word [si+RD_HEADS]
    mov [si+RD_CYLINDER], ax
    mov [si+RD_HEAD], dx
    push ds
    push si
    call far [si+RD_ADAPTER_OFFSET]
    pop si
    pop ds
    or ax, ax
    jnz .error
    cmp cx, S2_SECTOR_BYTES
    jne .error
    add word [si+RD_CURRENT_OFFSET], S2_SECTOR_BYTES
    inc word [si+RD_CURRENT_LBA]
    dec word [si+RD_REMAINING]
    jnz .sector
    clc
    ret
.error:
    stc
    ret
%endif
    times 510-($-$$) db 0
    dw 0
%if S2_SECTOR_BYTES != 512
%include "disk_read.inc"
    times 1022-($-$$) db 0
    dw 0
%endif
