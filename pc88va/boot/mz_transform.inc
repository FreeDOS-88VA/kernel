; SPDX-License-Identifier: GPL-2.0-or-later
; Copy and verify a validated zero-relocation body into its owned allocation.
bits 16
cpu 8086
    jmp pc88va_mz_transform_core
%include "mz_validate.inc"

pc88va_mz_transform_core:
    pushf
    push bx
    push cx
    push dx
    push di
    push bp
    push es
    call pc88va_mz_validate_core
    or ax, ax
    jnz .restore
    cld
    mov ax, [si+MZ_FILE_SEGMENT]
    cmp ax, [si+MZ_LOAD_SEGMENT]
    jne .copy_to_allocation
    cmp word [si+MZ_FILE_OFFSET], 0
    jne .restore_contract
    ; Low staging mode: remove the MZ header in place.  The destination starts
    ; below the source, so a forward copy is the overlap-safe direction.  The
    ; bridge then runs at the staging segment and expands the resident image
    ; elsewhere.
    ; BP addresses SS by default on 8086.  Read the context through SI while
    ; DS still names the stage-2 data segment, then retain SI in BP across the
    ; temporary file-segment switch.
    mov cx, [si+MZ_BODY_BYTES]
    mov dx, [si+MZ_HEADER_BYTES]
    mov bp, si
    push ds
    mov ds, ax
    mov es, ax
    mov si, dx
    xor di, di
    rep movsb
    ; Restore the context data segment before reading the remaining MZ
    ; fields.  BP is an offset in the caller's DS, not in the file segment
    ; that was selected for the overlapping backward copy.
    pop ds
    mov si, bp
    mov es, [si+MZ_LOAD_SEGMENT]
    mov di, [si+MZ_BODY_BYTES]
    mov cx, [si+MZ_ALLOC_BYTES]
    sub cx, di
    xor ax, ax
    rep stosb
    mov word [si+MZ_TRANSFORMED], 1
    xor ax, ax
    jmp .restore
.restore_contract:
    mov ax, MZ_CONTRACT
    jmp .restore
.copy_to_allocation:
    mov es, [si+MZ_LOAD_SEGMENT]
    xor di, di
    mov cx, [si+MZ_BODY_BYTES]
    call .source
    rep movsb
    pop si
    pop ds
    mov cx, [si+MZ_ALLOC_BYTES]
    sub cx, [si+MZ_BODY_BYTES]
    xor ax, ax
    rep stosb
    ; Compare the initialized body against the original file, not a checksum.
    xor di, di
    mov cx, [si+MZ_BODY_BYTES]
    call .source
    repe cmpsb
    pop si
    pop ds
    jne .bytecheck
    ; Verify the full rounded body padding and minimum allocation tail.
    mov cx, [si+MZ_ALLOC_BYTES]
    sub cx, [si+MZ_BODY_BYTES]
    jcxz .complete
    xor ax, ax
    repe scasb
    jne .bytecheck
.complete:
    mov word [si+MZ_TRANSFORMED], 1
    xor ax, ax
    jmp .restore
.bytecheck:
    mov ax, MZ_BYTECHECK
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

; Switch to file DS:SI while leaving the caller's DS/SI on its original stack.
; Pop the near return address before adding the two saved words.
.source:
    pop bp
    push ds
    push si
    mov ax, [si+MZ_FILE_SEGMENT]
    mov bx, [si+MZ_FILE_OFFSET]
    add bx, [si+MZ_HEADER_BYTES]
    mov si, bx
    mov ds, ax
    jmp bp
