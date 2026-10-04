; SPDX-License-Identifier: GPL-2.0-or-later
; Read the BPB, both FAT copies and root directory through the shared disk core.
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

; DS:SI -> VM_SIZE. The complete memory ownership map must be validated first.
; The caller's RD/VP/FT/RT/FL records are owned mutable initialization workspace.
pc88va_volume_read_core:
    pushf
    push bx
    push cx
    push dx
    push si
    push di
    push bp
    push ds
    push es
    cmp si, 65536-VM_SIZE
    ja .contract
    mov bp, si
    cmp word [ds:bp+VM_VERSION], 1
    jne .contract
    mov word [ds:bp+VM_STAGE], 0
    cld
    mov bx, [ds:bp+VM_DISK]
    cmp bx, 65536-RD_SIZE
    ja .contract
    cmp word [bx+RD_VERSION], 1
    jne .contract
    mov si, [ds:bp+VM_VOLUME]
    cmp si, 65536-VP_SIZE
    ja .contract
    cmp word [si+VP_VERSION], 1
    jne .contract
    cmp [si+VP_DISK], bx
    jne .contract
    mov di, [ds:bp+VM_FAT]
    cmp di, 65536-FT_SIZE
    ja .contract
    cmp word [di+FT_VERSION], 1
    jne .contract
    mov ax, [di+FT_FAT_BYTES]
    mov [si+VP_FAT_CAPACITY], ax
    mov ax, [di+FT_VISITED_CAPACITY]
    mov [si+VP_BITMAP_CAPACITY], ax
    mov di, [ds:bp+VM_ROOT]
    cmp di, 65536-RT_SIZE
    ja .contract
    cmp word [di+RT_VERSION], 1
    jne .contract
    mov ax, [di+RT_BYTES]
    mov [si+VP_ROOT_CAPACITY], ax
    mov di, [ds:bp+VM_FILE]
    cmp di, 65536-FL_SIZE
    ja .contract
    cmp word [di+FL_VERSION], 1
    jne .contract
    cmp [di+FL_DISK], bx
    jne .contract
    mov ax, [ds:bp+VM_FAT]
    cmp [di+FL_FAT], ax
    jne .contract
    mov ax, [ds:bp+VM_ROOT]
    cmp [di+FL_ROOT], ax
    jne .contract
    ; The BPB is obtained from the actual disk, not supplied as host metadata.
    xor ax, ax
    mov cx, 1
    mov dx, [si+VP_OFFSET]
    mov es, [si+VP_SEGMENT]
    mov di, [si+VP_BYTES]
    call .read
    or ax, ax
    jnz .restore
    call pc88va_volume_validate_core
    or ax, ax
    jnz .restore
    mov ax, [si+VP_FAT_BYTES]
    cmp ax, [ds:bp+VM_MIRROR_CAPACITY]
    ja .capacity
    mov word [ds:bp+VM_STAGE], 1
    mov bx, [ds:bp+VM_FAT]
    mov ax, [si+VP_FAT_START]
    mov cx, [si+VP_FAT_SECTORS]
    mov dx, [bx+FT_FAT_OFFSET]
    mov es, [bx+FT_FAT_SEGMENT]
    mov di, [bx+FT_FAT_BYTES]
    call .read
    or ax, ax
    jnz .restore
    mov ax, [si+VP_FAT_START]
    add ax, [si+VP_FAT_SECTORS]
    mov cx, [si+VP_FAT_SECTORS]
    mov dx, [ds:bp+VM_MIRROR_OFFSET]
    mov es, [ds:bp+VM_MIRROR_SEGMENT]
    mov di, [ds:bp+VM_MIRROR_CAPACITY]
    call .read
    or ax, ax
    jnz .restore
    mov cx, [si+VP_FAT_BYTES]
    mov bx, [ds:bp+VM_FAT]
    mov ax, [bx+FT_FAT_SEGMENT]
    mov dx, [bx+FT_FAT_OFFSET]
    mov di, [ds:bp+VM_MIRROR_OFFSET]
    push ds
    push si
    mov ds, ax
    mov si, dx
    repe cmpsb
    pop si
    pop ds
    jne .mismatch
    mov es, [bx+FT_FAT_SEGMENT]
    mov di, [bx+FT_FAT_OFFSET]
    mov ax, [si+VP_MEDIA]
    cmp [es:di], al
    jne .reserved
    cmp word [es:di+1], 0xffff
    jne .reserved
    mov word [ds:bp+VM_STAGE], 2
    mov bx, [ds:bp+VM_ROOT]
    mov ax, [si+VP_ROOT_START]
    mov cx, [si+VP_ROOT_SECTORS]
    mov dx, [bx+RT_OFFSET]
    mov es, [bx+RT_SEGMENT]
    mov di, [bx+RT_BYTES]
    call .read
    or ax, ax
    jnz .restore
    ; Populate exact layout fields only after all metadata reads complete.
    mov bx, [ds:bp+VM_FAT]
    mov ax, [si+VP_FAT_BYTES]
    mov [bx+FT_FAT_BYTES], ax
    mov ax, [si+VP_DATA_CLUSTERS]
    mov [bx+FT_DATA_CLUSTERS], ax
    mov bx, [ds:bp+VM_ROOT]
    mov [bx+RT_DATA_CLUSTERS], ax
    mov ax, [si+VP_ROOT_ENTRIES]
    mov [bx+RT_ENTRIES], ax
    mov ax, [si+VP_ROOT_BYTES]
    mov [bx+RT_BYTES], ax
    mov di, [ds:bp+VM_FILE]
    mov ax, [di+FL_CAPACITY]
    mov [bx+RT_FILE_CAPACITY], ax
    mov ax, [si+VP_DATA_START]
    mov [di+FL_DATA_START], ax
    mov ax, [si+VP_SECTORS_CLUSTER]
    mov [di+FL_SECTORS_CLUSTER], ax
    mov word [ds:bp+VM_STAGE], 3
    xor ax, ax
    jmp .restore
.contract:
    mov ax, VOLUME_READ_CONTRACT
    jmp .restore
.capacity:
    mov ax, VOLUME_CAPACITY
    jmp .restore
.mismatch:
    mov ax, VOLUME_FAT_MISMATCH
    jmp .restore
.reserved:
    mov ax, VOLUME_RESERVED
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
    jnz .error
    popf
    clc
    ret
.error:
    popf
    stc
    ret

; Input AX=LBA, CX=count, ES:DX=destination, DI=capacity. Preserve VP pointer.
.read:
    push si
    mov si, [ds:bp+VM_DISK]
    mov [si+RD_LBA], ax
    mov [si+RD_COUNT], cx
    mov [si+RD_OFFSET], dx
    mov ax, es
    mov [si+RD_SEGMENT], ax
    mov [si+RD_CAPACITY], di
    call pc88va_disk_read_core
    pop si
    ret
