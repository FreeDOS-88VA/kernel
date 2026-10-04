; SPDX-License-Identifier: GPL-2.0-or-later
; Included unchanged by stage 2, the kernel OMF wrapper, and ROM-free tests.
; DS:SI -> RD_SIZE bytes. AX=result, CF=error; other registers/flags preserved.
bits 16
cpu 8086
%ifndef PC88VA
%error PC88VA selector is required
%endif
%ifdef NEC98
%error Contradictory machine-family selection
%endif
%ifdef IBMPC
%error Contradictory machine-family selection
%endif
%include "loader_abi.inc"

pc88va_disk_read_core:
    pushf
    push bx
    push cx
    push dx
    push si
    push di
    push bp
    push ds
    push es
    cmp si, 65536-RD_SIZE
    ja .contract
    cmp word [si+RD_VERSION], 1
    jne .contract
    mov word [si+RD_COMPLETED], 0
    mov word [si+RD_ADAPTER_STATUS], 0
    mov ax, [si+RD_ADAPTER_OFFSET]
    or ax, [si+RD_ADAPTER_SEGMENT]
    jz .contract
    cmp word [si+RD_RETRIES], 3
    ja .contract
    mov ax, [si+RD_SECTOR_BYTES]
    cmp ax, 128
    jb .contract
    cmp ax, 4096
    ja .contract
    mov bx, ax
    dec bx
    test ax, bx
    jnz .contract
    mov ax, [si+RD_SECTORS_TRACK]
    or ax, ax
    jz .contract
    cmp ax, 255
    ja .contract
    mov bx, [si+RD_HEADS]
    or bx, bx
    jz .contract
    cmp bx, 256
    ja .contract
    mul bx
    or dx, dx
    jnz .contract
    cmp word [si+RD_TOTAL_SECTORS], 0
    je .contract
    cmp word [si+RD_COUNT], 0
    je .range
    mov ax, [si+RD_LBA]
    cmp ax, [si+RD_TOTAL_SECTORS]
    jae .range
    add ax, [si+RD_COUNT]
    jc .range
    cmp ax, [si+RD_TOTAL_SECTORS]
    ja .range
    mov ax, [si+RD_COUNT]
    mul word [si+RD_SECTOR_BYTES]
    or dx, dx
    jnz .capacity
    cmp ax, [si+RD_CAPACITY]
    ja .capacity
    mov bp, ax
    add ax, [si+RD_OFFSET]
    jc .capacity
    ; Construct the physical half-open end without 16-bit wraparound.
    mov ax, [si+RD_SEGMENT]
    mov dx, ax
    mov cl, 12
    shr dx, cl
    mov cl, 4
    shl ax, cl
    add ax, [si+RD_OFFSET]
    adc dx, 0
    add ax, bp
    adc dx, 0
    cmp dx, 16
    ja .range
    jb .physical_valid
    or ax, ax
    jnz .range
.physical_valid:
    mov ax, [si+RD_OFFSET]
    mov [si+RD_CURRENT_OFFSET], ax
    mov ax, [si+RD_SEGMENT]
    mov [si+RD_CURRENT_SEGMENT], ax
    mov ax, [si+RD_LBA]
    mov [si+RD_CURRENT_LBA], ax
    mov ax, [si+RD_COUNT]
    mov [si+RD_REMAINING], ax
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
    mov ax, [si+RD_RETRIES]
    mov [si+RD_RETRIES_LEFT], ax
.attempt:
    ; Adapter is a qualified far callback, never an implicit BIOS fallback.
    ; Only SS:SP must survive; recover request addressing even after clobbers.
    push ds
    push si
    call far [si+RD_ADAPTER_OFFSET]
    pop si
    pop ds
    mov [si+RD_ADAPTER_STATUS], ax
    or ax, ax
    jz .completed_sector
    cmp word [si+RD_RETRIES_LEFT], 0
    je .firmware
    dec word [si+RD_RETRIES_LEFT]
    jmp .attempt
.completed_sector:
    cmp cx, [si+RD_SECTOR_BYTES]
    jne .short
    mov ax, [si+RD_SECTOR_BYTES]
    add [si+RD_COMPLETED], ax
    add [si+RD_CURRENT_OFFSET], ax
    inc word [si+RD_CURRENT_LBA]
    dec word [si+RD_REMAINING]
    jnz .sector
    xor ax, ax
    jmp .restore
.contract:
    mov ax, DISK_CONTRACT
    jmp .restore
.range:
    mov ax, DISK_RANGE
    jmp .restore
.capacity:
    mov ax, DISK_CAPACITY
    jmp .restore
.short:
    mov ax, DISK_SHORT
    jmp .restore
.firmware:
    mov ax, DISK_FIRMWARE
.restore:
    pop es
    pop ds
    pop bp
    pop di
    pop si
    pop dx
    pop cx
    pop bx
    or ax, ax
    jnz .error_return
    popf
    clc
    ret
.error_return:
    popf
    stc
    ret
