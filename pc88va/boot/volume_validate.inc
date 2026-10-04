; SPDX-License-Identifier: GPL-2.0-or-later
; Validate a superfloppy FAT12 BPB before reading its metadata regions.
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

; DS:SI -> VP_SIZE, referencing a disjoint RD request and immutable boot sector.
; All registers except AX, and all FLAGS except CF, are preserved.
pc88va_volume_validate_core:
    pushf
    push bx
    push cx
    push dx
    push di
    push bp
    push es
    cmp si, 65536-VP_SIZE
    ja .contract
    cmp word [si+VP_VERSION], 1
    jne .contract
    mov word [si+VP_VALIDATED], 0
    mov bx, [si+VP_DISK]
    cmp bx, 65536-RD_SIZE
    ja .contract
    cmp word [bx+RD_VERSION], 1
    jne .contract
    mov ax, [bx+RD_SECTOR_BYTES]
    cmp ax, 128
    jb .contract
    cmp ax, 4096
    ja .contract
    mov cx, ax
    dec cx
    test ax, cx
    jnz .contract
    cmp ax, [si+VP_BYTES]
    ja .capacity
    mov [si+VP_SECTOR_BYTES], ax
    cmp word [bx+RD_TOTAL_SECTORS], 0
    je .contract
    cmp word [bx+RD_SECTORS_TRACK], 1
    jb .contract
    cmp word [bx+RD_SECTORS_TRACK], 255
    ja .contract
    cmp word [bx+RD_HEADS], 1
    jb .contract
    cmp word [bx+RD_HEADS], 256
    ja .contract
    mov ax, [si+VP_OFFSET]
    add ax, [si+VP_BYTES]
    jc .capacity
    mov ax, [si+VP_SEGMENT]
    mov dx, ax
    mov cl, 12
    shr dx, cl
    mov cl, 4
    shl ax, cl
    add ax, [si+VP_OFFSET]
    adc dx, 0
    add ax, [si+VP_BYTES]
    adc dx, 0
    cmp dx, 16
    ja .capacity
    jb .buffer_valid
    or ax, ax
    jnz .capacity
.buffer_valid:
    mov es, [si+VP_SEGMENT]
    mov di, [si+VP_OFFSET]
    mov ax, [es:di+11]
    cmp ax, [si+VP_SECTOR_BYTES]
    jne .geometry
    mov ax, [es:di+24]
    cmp ax, [bx+RD_SECTORS_TRACK]
    jne .geometry
    mov ax, [es:di+26]
    cmp ax, [bx+RD_HEADS]
    jne .geometry
    cmp word [es:di+28], 0
    jne .bpb
    cmp word [es:di+30], 0
    jne .bpb
    ; Do not accept ambiguous or overflowing alternate size encodings.
    cmp word [es:di+34], 0
    jne .geometry
    mov ax, [es:di+19]
    or ax, ax
    jz .large_size
    cmp word [es:di+32], 0
    jne .geometry
    jmp .size_ready
.large_size:
    mov ax, [es:di+32]
.size_ready:
    ; The BPB may describe fewer whole cylinders of the same track geometry
    ; (the NEC-compatible 77-cylinder 2HD form of an 80-cylinder profile).
    ; Keep the disk record unchanged; the layout below uses the BPB total.
    or ax, ax
    jz .geometry
    cmp ax, [bx+RD_TOTAL_SECTORS]
    je .size_accepted
    ja .geometry
    push ax
    mov cx, ax
    mov ax, [bx+RD_SECTORS_TRACK]
    mul word [bx+RD_HEADS]
    xchg ax, cx
    xor dx, dx
    div cx
    pop ax
    or dx, dx
    jnz .geometry
.size_accepted:
    mov [si+VP_DATA_CLUSTERS], ax       ; scratch: BPB total until computed
    cmp byte [es:di+16], 2
    jne .bpb
    xor ax, ax
    mov al, [es:di+13]
    or ax, ax
    jz .bpb
    cmp ax, 128
    ja .bpb
    mov cx, ax
    dec cx
    test ax, cx
    jnz .bpb
    mov [si+VP_SECTORS_CLUSTER], ax
    mul word [si+VP_SECTOR_BYTES]
    or dx, dx
    jnz .layout
    xor ax, ax
    mov al, [es:di+21]
    cmp al, 0xf0
    je .media_valid
    cmp al, 0xf8
    jb .bpb
.media_valid:
    mov [si+VP_MEDIA], ax
    mov ax, [es:di+14]
    or ax, ax
    jz .bpb
    mov [si+VP_FAT_START], ax
    mov ax, [es:di+22]
    or ax, ax
    jz .bpb
    mov [si+VP_FAT_SECTORS], ax
    mul word [si+VP_SECTOR_BYTES]
    or dx, dx
    jnz .capacity
    cmp ax, [si+VP_FAT_CAPACITY]
    ja .capacity
    mov [si+VP_FAT_BYTES], ax
    mov ax, [es:di+17]
    or ax, ax
    jz .bpb
    cmp ax, 2047
    ja .capacity
    mov [si+VP_ROOT_ENTRIES], ax
    mov cl, 5
    shl ax, cl
    xor dx, dx
    div word [si+VP_SECTOR_BYTES]
    or dx, dx
    jz .root_rounded
    inc ax
.root_rounded:
    mov [si+VP_ROOT_SECTORS], ax
    mul word [si+VP_SECTOR_BYTES]
    or dx, dx
    jnz .capacity
    cmp ax, [si+VP_ROOT_CAPACITY]
    ja .capacity
    mov [si+VP_ROOT_BYTES], ax
    mov ax, [si+VP_FAT_SECTORS]
    add ax, ax
    jc .layout
    add ax, [si+VP_FAT_START]
    jc .layout
    mov [si+VP_ROOT_START], ax
    add ax, [si+VP_ROOT_SECTORS]
    jc .layout
    cmp ax, [si+VP_DATA_CLUSTERS]
    jae .layout
    mov [si+VP_DATA_START], ax
    mov cx, [si+VP_DATA_CLUSTERS]
    sub cx, ax
    mov ax, cx
    xor dx, dx
    div word [si+VP_SECTORS_CLUSTER]
    or ax, ax
    jz .layout
    cmp ax, 4084
    ja .layout
    mov [si+VP_DATA_CLUSTERS], ax
    ; The packed FAT must hold both reserved entries and every data cluster.
    add ax, 2
    mov cx, 3
    mul cx
    inc ax
    shr ax, 1
    cmp ax, [si+VP_FAT_BYTES]
    ja .capacity
    mov ax, [si+VP_DATA_CLUSTERS]
    add ax, 7
    mov cl, 3
    shr ax, cl
    cmp ax, [si+VP_BITMAP_CAPACITY]
    ja .capacity
    mov [si+VP_BITMAP_BYTES], ax
    mov word [si+VP_VALIDATED], 1
    xor ax, ax
    jmp .restore
.contract:
    mov ax, VOLUME_CONTRACT
    jmp .restore
.bpb:
    mov ax, VOLUME_BPB
    jmp .restore
.layout:
    mov ax, VOLUME_LAYOUT
    jmp .restore
.capacity:
    mov ax, VOLUME_CAPACITY
    jmp .restore
.geometry:
    mov ax, VOLUME_GEOMETRY
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
