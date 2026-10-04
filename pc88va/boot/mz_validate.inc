; SPDX-License-Identifier: GPL-2.0-or-later
; Validate a zero-relocation DOS MZ carrier before any destination write.
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

; DS:SI -> MZ_CONTEXT_SIZE. Protected intervals are little-endian dword
; start/end pairs in the same data segment, supplied by the ownership contract.
pc88va_mz_validate_core:
    pushf
    push bx
    push cx
    push dx
    push di
    push bp
    push es
    cmp si, 65536-MZ_CONTEXT_SIZE
    ja .contract
    cmp word [si+MZ_VERSION], 1
    jne .contract
    mov word [si+MZ_VALIDATED], 0
    mov word [si+MZ_TRANSFORMED], 0
    cmp word [si+MZ_STACK_RESERVE], 2
    jb .contract
    mov ax, [si+MZ_PROTECTED_COUNT]
    or ax, ax
    jz .contract
    cmp ax, 16
    ja .contract
    mov cl, 3
    shl ax, cl
    add ax, [si+MZ_PROTECTED_PTR]
    jc .contract
    cmp word [si+MZ_FILE_BYTES], 32
    jb .header
    mov ax, [si+MZ_FILE_OFFSET]
    add ax, [si+MZ_FILE_BYTES]
    jc .filesize
    mov ax, [si+MZ_FILE_SEGMENT]
    mov dx, ax
    mov cl, 12
    shr dx, cl
    mov cl, 4
    shl ax, cl
    add ax, [si+MZ_FILE_OFFSET]
    adc dx, 0
    mov [si+MZ_SOURCE_LO], ax
    mov [si+MZ_SOURCE_HI], dx
    add ax, [si+MZ_FILE_BYTES]
    adc dx, 0
    cmp dx, 16
    ja .filesize
    jb .source_valid
    or ax, ax
    jnz .filesize
.source_valid:
    mov [si+MZ_SOURCE_END_LO], ax
    mov [si+MZ_SOURCE_END_HI], dx
    mov es, [si+MZ_FILE_SEGMENT]
    mov di, [si+MZ_FILE_OFFSET]
    cmp word [es:di], 'MZ'
    jne .header
    cmp word [es:di+26], 0
    jne .header
    ; This carrier policy does not implement the optional DOS checksum.
    cmp word [es:di+18], 0
    jne .header
    cmp word [es:di+6], 0
    jne .relocation
    mov cx, [es:di+2]
    cmp cx, 511
    ja .filesize
    mov ax, [es:di+4]
    or ax, ax
    jz .filesize
    mov bx, 512
    mul bx
    or cx, cx
    jz .encoded_size
    sub ax, 512
    sbb dx, 0
    add ax, cx
    adc dx, 0
.encoded_size:
    or dx, dx
    jnz .filesize
    cmp ax, [si+MZ_FILE_BYTES]
    jne .filesize
    mov ax, [es:di+8]
    cmp ax, 2
    jb .header
    cmp ax, 4095
    ja .header
    mov cl, 4
    shl ax, cl
    cmp ax, [si+MZ_FILE_BYTES]
    jae .header
    mov [si+MZ_HEADER_BYTES], ax
    mov bx, [es:di+24]
    cmp bx, 28
    jb .header
    cmp bx, ax
    ja .header
    mov bx, [si+MZ_FILE_BYTES]
    sub bx, ax
    mov [si+MZ_BODY_BYTES], bx
    mov ax, bx
    add ax, 15
    jc .allocation
    mov cl, 4
    shr ax, cl
    mov dx, [es:di+10]
    cmp dx, [es:di+12]
    ja .allocation
    add ax, dx
    jc .allocation
    cmp ax, 4095
    ja .allocation
    shl ax, cl
    cmp ax, [si+MZ_CAPACITY]
    ja .allocation
    mov [si+MZ_ALLOC_BYTES], ax
    ; Entry relative byte offset must lie inside the initialized body.
    mov ax, [es:di+22]
    mov bx, 16
    mul bx
    add ax, [es:di+20]
    adc dx, 0
    or dx, dx
    jnz .entry
    cmp ax, [si+MZ_BODY_BYTES]
    jae .entry
    mov bp, ax
    mov ax, [es:di+22]
    add ax, [si+MZ_LOAD_SEGMENT]
    jc .entry
    mov [si+MZ_ENTRY_CS], ax
    mov ax, [es:di+20]
    mov [si+MZ_ENTRY_IP], ax
    ; Stack top is exclusive and must leave the declared reserve below it.
    mov ax, [es:di+14]
    mov bx, 16
    mul bx
    add ax, [es:di+16]
    adc dx, 0
    or dx, dx
    jnz .stack
    cmp ax, [si+MZ_ALLOC_BYTES]
    ja .stack
    mov bx, [es:di+16]
    cmp bx, [si+MZ_STACK_RESERVE]
    jb .stack
    cmp ax, [si+MZ_STACK_RESERVE]
    jb .stack
    mov bx, ax
    sub bx, [si+MZ_STACK_RESERVE]
    cmp bp, bx
    jb .entry_outside_stack
    cmp bp, ax
    jb .stack
.entry_outside_stack:
    mov ax, [es:di+14]
    add ax, [si+MZ_LOAD_SEGMENT]
    jc .stack
    mov [si+MZ_STACK_SS], ax
    mov ax, [es:di+16]
    mov [si+MZ_STACK_SP], ax
    mov ax, [si+MZ_LOAD_SEGMENT]
    mov dx, ax
    mov cl, 12
    shr dx, cl
    mov cl, 4
    shl ax, cl
    mov [si+MZ_DEST_LO], ax
    mov [si+MZ_DEST_HI], dx
    add ax, [si+MZ_ALLOC_BYTES]
    adc dx, 0
    cmp dx, 16
    ja .allocation
    jb .destination_valid
    or ax, ax
    jnz .allocation
.destination_valid:
    mov [si+MZ_END_LO], ax
    mov [si+MZ_END_HI], dx
    ; The ordinary carrier has disjoint source and destination intervals.
    ; The low-staging carrier is a deliberate in-place exception: the file
    ; and load segments are equal, the file starts at offset zero, and the
    ; transform compacts the body before the bridge executes.
    mov ax, [si+MZ_SOURCE_LO]
    mov dx, [si+MZ_SOURCE_HI]
    mov bx, [si+MZ_SOURCE_END_LO]
    mov cx, [si+MZ_SOURCE_END_HI]
    mov bp, [si+MZ_FILE_SEGMENT]
    cmp bp, [si+MZ_LOAD_SEGMENT]
    jne .check_source_overlap
    cmp word [si+MZ_FILE_OFFSET], 0
    jne .overlap
    mov ax, [si+MZ_FILE_BYTES]
    cmp ax, [si+MZ_CAPACITY]
    ja .allocation
    jmp .source_overlap_done
.check_source_overlap:
    call pc88va_mz_interval_check
    jc .overlap
.source_overlap_done:
    mov di, [si+MZ_PROTECTED_PTR]
    mov bp, [si+MZ_PROTECTED_COUNT]
.protected:
    mov ax, [di]
    mov dx, [di+2]
    mov bx, [di+4]
    mov cx, [di+6]
    call pc88va_mz_interval_check
    jc .overlap
    add di, 8
    dec bp
    jnz .protected
    mov word [si+MZ_VALIDATED], 1
    xor ax, ax
    jmp .restore
.contract:
    mov ax, MZ_CONTRACT
    jmp .restore
.header:
    mov ax, MZ_HEADER
    jmp .restore
.filesize:
    mov ax, MZ_FILESIZE
    jmp .restore
.relocation:
    mov ax, MZ_RELOCATION
    jmp .restore
.allocation:
    mov ax, MZ_ALLOCATION
    jmp .restore
.entry:
    mov ax, MZ_ENTRY
    jmp .restore
.stack:
    mov ax, MZ_STACK
    jmp .restore
.overlap:
    mov ax, MZ_OVERLAP
.restore:
    pop es
    pop bp
    pop di
    pop dx
    pop cx
    pop bx
    or ax, ax
    jnz .error
    popf
    clc
    ret
.error:
    popf
    stc
    ret

; Check nonempty [DX:AX,CX:BX) against the destination using unsigned arithmetic.
pc88va_mz_interval_check:
    cmp cx, 16
    ja .bad
    jb .bound_valid
    or bx, bx
    jnz .bad
.bound_valid:
    cmp dx, cx
    ja .bad
    jb .ordered
    cmp ax, bx
    jae .bad
.ordered:
    cmp dx, [si+MZ_END_HI]
    ja .good
    jb .test_end
    cmp ax, [si+MZ_END_LO]
    jae .good
.test_end:
    cmp cx, [si+MZ_DEST_HI]
    jb .good
    ja .bad
    cmp bx, [si+MZ_DEST_LO]
    jbe .good
.bad:
    stc
    ret
.good:
    clc
    ret
