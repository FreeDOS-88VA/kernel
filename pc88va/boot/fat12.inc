; SPDX-License-Identifier: GPL-2.0-or-later
; Cached FAT12 decoding and complete bounded chain validation, 8086 only.
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

; DS:SI -> FT_SIZE bytes. Decode FT_CURRENT into FT_NEXT without changing FAT.
; AX=0/explicit error; CF=error. Other registers and flags preserved.
pc88va_fat_next_core:
    pushf
    push bx
    push cx
    push dx
    push di
    push es
    cmp si, 65536-FT_SIZE
    ja .contract
    cmp word [si+FT_VERSION], 1
    jne .contract
    mov bx, [si+FT_DATA_CLUSTERS]
    or bx, bx
    jz .contract
    cmp bx, 4084
    ja .contract
    inc bx
    mov ax, [si+FT_CURRENT]
    cmp ax, 2
    jb .cluster
    cmp ax, 0x0ff0
    jae .cluster
    cmp ax, bx
    ja .cluster
    mov bx, ax
    shr bx, 1
    add bx, ax
    mov cx, [si+FT_FAT_BYTES]
    cmp cx, 2
    jb .buffer
    mov di, [si+FT_FAT_OFFSET]
    add di, cx
    jc .buffer
    sub cx, 2
    cmp bx, cx
    ja .buffer
    add bx, [si+FT_FAT_OFFSET]
    mov dx, [si+FT_FAT_SEGMENT]
    mov es, dx
    ; The contiguous cached FAT permits a word crossing a sector boundary.
    mov dx, [es:bx]
    test ax, 1
    jz .even
    mov cl, 4
    shr dx, cl
.even:
    and dx, 0x0fff
    mov [si+FT_NEXT], dx
    xor ax, ax
    jmp .restore
.contract:
    mov ax, FAT_CONTRACT
    jmp .restore
.cluster:
    mov ax, FAT_CLUSTER
    jmp .restore
.buffer:
    mov ax, FAT_BUFFER
.restore:
    pop es
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

; Validate exactly FT_EXPECTED_COUNT clusters and require a final EOC.
; The caller owns disjoint immutable FAT, request, and visited-bitmap regions.
; No file bytes are copied by this validator. FT_VALIDATED reports progress.
pc88va_fat_chain_core:
    pushf
    push bx
    push cx
    push dx
    push di
    push es
    cmp si, 65536-FT_SIZE
    ja .contract
    cmp word [si+FT_VERSION], 1
    jne .contract
    mov word [si+FT_VALIDATED], 0
    mov ax, [si+FT_FIRST_CLUSTER]
    mov [si+FT_CURRENT], ax
    ; Validate FAT/cluster bounds before initializing caller-owned scratch.
    call pc88va_fat_next_core
    jc .restore
    mov ax, [si+FT_EXPECTED_COUNT]
    or ax, ax
    jz .contract
    cmp ax, [si+FT_DATA_CLUSTERS]
    ja .contract
    mov ax, [si+FT_DATA_CLUSTERS]
    add ax, 7
    mov cl, 3
    shr ax, cl
    cmp ax, [si+FT_VISITED_CAPACITY]
    ja .buffer
    mov cx, ax
    mov di, [si+FT_VISITED_OFFSET]
    add ax, di
    jc .buffer
    mov es, [si+FT_VISITED_SEGMENT]
    xor ax, ax
    cld
    rep stosb
.cluster:
    mov bx, [si+FT_CURRENT]
    sub bx, 2
    mov cx, bx
    and cx, 7
    mov al, 1
    shl al, cl
    mov cl, 3
    shr bx, cl
    add bx, [si+FT_VISITED_OFFSET]
    test [es:bx], al
    jnz .cycle
    or [es:bx], al
    call pc88va_fat_next_core
    jc .restore
    inc word [si+FT_VALIDATED]
    mov ax, [si+FT_NEXT]
    cmp ax, 0x0ff8
    jae .eoc
    cmp ax, 0x0ff0
    jae .reserved
    cmp ax, 2
    jb .reserved
    mov dx, [si+FT_DATA_CLUSTERS]
    inc dx
    cmp ax, dx
    ja .bad_cluster
    mov dx, [si+FT_VALIDATED]
    cmp dx, [si+FT_EXPECTED_COUNT]
    je .long
    mov [si+FT_CURRENT], ax
    jmp .cluster
.eoc:
    mov ax, [si+FT_VALIDATED]
    cmp ax, [si+FT_EXPECTED_COUNT]
    jne .early
    xor ax, ax
    jmp .restore
.contract:
    mov ax, FAT_CONTRACT
    jmp .restore
.buffer:
    mov ax, FAT_BUFFER
    jmp .restore
.cycle:
    mov ax, FAT_CYCLE
    jmp .restore
.reserved:
    mov ax, FAT_RESERVED
    jmp .restore
.bad_cluster:
    mov ax, FAT_CLUSTER
    jmp .restore
.long:
    mov ax, FAT_LONG_CHAIN
    jmp .restore
.early:
    mov ax, FAT_EARLY_EOC
.restore:
    pop es
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
