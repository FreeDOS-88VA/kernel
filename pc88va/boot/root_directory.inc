; SPDX-License-Identifier: GPL-2.0-or-later
; Exact FAT12 short-name lookup in a validated contiguous root cache.
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

; DS:SI -> RT_SIZE bytes.  The stage-2-owned pointer at
; PC88VA_ROOT_NAME_POINTER selects the 11-byte short name to match.  AX/CF
; is the result; all other registers/FLAGS are preserved.
pc88va_root_lookup_core:
    pushf
    push bx
    push cx
    push dx
    push di
    push es
    push bp
    cmp si, 65536-RT_SIZE
    ja .contract
    cmp word [si+RT_VERSION], 1
    jne .contract
    mov word [si+RT_FOUND], 0
    mov word [si+RT_FIRST_CLUSTER], 0
    mov word [si+RT_FILE_SIZE], 0
    mov ax, [si+RT_DATA_CLUSTERS]
    or ax, ax
    jz .contract
    cmp ax, 4084
    ja .contract
    cmp word [si+RT_FILE_CAPACITY], 0
    je .contract
%ifdef PC88VA_ROOT_NAME_POINTER
    mov bp, [PC88VA_ROOT_NAME_POINTER]
    cmp bp, 65536-11
    ja .contract
%endif
    mov ax, [si+RT_ENTRIES]
    or ax, ax
    jz .contract
    cmp ax, 2047
    ja .buffer
    mov cl, 5
    shl ax, cl
    cmp ax, [si+RT_BYTES]
    ja .buffer
    add ax, [si+RT_OFFSET]
    jc .buffer
    mov di, ax
    ; Validate the complete physical half-open cache extent.
    mov ax, [si+RT_SEGMENT]
    mov dx, ax
    mov cl, 12
    shr dx, cl
    mov cl, 4
    shl ax, cl
    add ax, di
    adc dx, 0
    cmp dx, 16
    ja .buffer
    jb .valid
    or ax, ax
    jnz .buffer
.valid:
    mov es, [si+RT_SEGMENT]
    mov di, [si+RT_OFFSET]
    mov cx, [si+RT_ENTRIES]
.entry:
    cmp byte [es:di], 0
    je .end
    cmp byte [es:di], 0xe5
    je .next
    ; Volume labels, directories and LFN records cannot be the kernel file.
    test byte [es:di+11], 0x18
    jnz .next
%ifdef PC88VA_ROOT_NAME_POINTER
    mov ax, [es:di]
    cmp ax, [ds:bp]
    jne .next
    mov ax, [es:di+2]
    cmp ax, [ds:bp+2]
    jne .next
    mov ax, [es:di+4]
    cmp ax, [ds:bp+4]
    jne .next
    mov ax, [es:di+6]
    cmp ax, [ds:bp+6]
    jne .next
    mov ax, [es:di+8]
    cmp ax, [ds:bp+8]
    jne .next
    mov al, [es:di+10]
    cmp al, [ds:bp+10]
    jne .next
%else
    cmp word [es:di], 'KE'
    jne .next
    cmp word [es:di+2], 'RN'
    jne .next
    cmp word [es:di+4], 'EL'
    jne .next
    cmp word [es:di+6], '  '
    jne .next
    cmp word [es:di+8], 'SY'
    jne .next
    cmp byte [es:di+10], 'S'
    jne .next
%endif
    cmp word [si+RT_FOUND], 0
    jne .duplicate
    test byte [es:di+11], 0xc0
    jnz .invalid
    cmp word [es:di+30], 0
    jne .capacity
    mov ax, [es:di+28]
    or ax, ax
    jz .invalid
    cmp ax, [si+RT_FILE_CAPACITY]
    ja .capacity
    mov bx, [es:di+26]
    cmp bx, 2
    jb .invalid
    cmp bx, 0x0ff0
    jae .invalid
    mov dx, [si+RT_DATA_CLUSTERS]
    inc dx
    cmp bx, dx
    ja .invalid
    mov [si+RT_FIRST_CLUSTER], bx
    mov [si+RT_FILE_SIZE], ax
    mov word [si+RT_FOUND], 1
.next:
    add di, 32
    dec cx
    jnz .entry
.end:
    cmp word [si+RT_FOUND], 1
    jne .missing
    xor ax, ax
    jmp .restore
.contract:
    mov ax, ROOT_CONTRACT
    jmp .restore
.buffer:
    mov ax, ROOT_BUFFER
    jmp .restore
.missing:
    mov ax, ROOT_NOT_FOUND
    jmp .restore
.invalid:
    mov ax, ROOT_ENTRY
    jmp .restore
.duplicate:
    mov ax, ROOT_DUPLICATE
    jmp .restore
.capacity:
    mov ax, ROOT_CAPACITY
.restore:
    pop bp
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
