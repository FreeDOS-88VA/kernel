; SPDX-License-Identifier: GPL-2.0-or-later
; Bounded, side-effect-free PC-88VA pre-kernel CONFIG.SYS probe.
;
; This is deliberately not a second CONFIG.SYS interpreter.  Stage-2 reads
; the file only far enough to recognize the PC88VA_LOADSEG=hhhh selector.
; M16 passes the resident-kernel layout base to the carrier, preserving the
; file buffer. All ordinary CONFIG.SYS directives remain kernel-owned.
bits 16
cpu 8086
%include "loader_abi.inc"

; Called after the normal volume/FAT/root metadata read and before the first
; KERNEL.SYS file load.  AX=0 selects the profile default; nonzero is a
; fail-closed boot error.
pc88va_stage2_config_bootstrap:
    pushf
    push bx
    push cx
    push dx
    push si
    push di
    push bp
    push es

    ; Copy the volume-derived fields from the ordinary file request.  The
    ; probe has its own FL record and target buffer, so the kernel request is
    ; untouched until a validated selector is available.
    mov ax, [pc88va_stage2_file+FL_DISK]
    mov [pc88va_stage2_config_file+FL_DISK], ax
    mov ax, [pc88va_stage2_file+FL_FAT]
    mov [pc88va_stage2_config_file+FL_FAT], ax
    mov ax, [pc88va_stage2_file+FL_ROOT]
    mov [pc88va_stage2_config_file+FL_ROOT], ax
    mov ax, [pc88va_stage2_file+FL_DATA_START]
    mov [pc88va_stage2_config_file+FL_DATA_START], ax
    mov ax, [pc88va_stage2_file+FL_SECTORS_CLUSTER]
    mov [pc88va_stage2_config_file+FL_SECTORS_CLUSTER], ax
    mov word [pc88va_stage2_config_file+FL_STAGE], 0
    mov word [pc88va_stage2_config_file+FL_LOADED], 0

    mov word [pc88va_stage2_root_name_pointer], pc88va_stage2_config_name
    mov si, pc88va_stage2_config_file
    call pc88va_file_load_core
    cmp ax, ROOT_NOT_FOUND
    je .default
    or ax, ax
    jnz .error

    call pc88va_stage2_config_parse
    cmp ax, PC88VA_CFG_NONE
    je .default
    cmp ax, PC88VA_CFG_FOUND
    jne .invalid
%ifdef PC88VA_RUNTIME_LOADSEG
    ; The setting is the expanded image base. Staging remains profile-owned;
    ; the carrier checks the complete translated layout against measured RAM.
    cmp word [pc88va_cfg_value], 1000h
    jb .invalid
    cmp word [pc88va_cfg_value], 0a000h
    jae .invalid
%else
    ; Use the actual KERNEL.SYS directory size rather than the profile's
    ; conservative file-window capacity when checking an alternate segment.
    ; This preserves room for a selector inside the same owned window.
    mov word [pc88va_stage2_root_name_pointer], pc88va_stage2_kernel_name
    mov word [pc88va_stage2_root+RT_FILE_CAPACITY], S2_KERNEL_FILE_CAPACITY
    mov si, pc88va_stage2_root
    call pc88va_root_lookup_core
    or ax, ax
    jnz .error
    mov ax, [pc88va_cfg_value]
    mov dx, [pc88va_stage2_root+RT_FILE_SIZE]
    call pc88va_stage2_validate_load_target
    or ax, ax
    jnz .invalid
    mov ax, [pc88va_cfg_value]
    mov [pc88va_stage2_file+FL_SEGMENT], ax
    mov [pc88va_stage2_mz+MZ_FILE_SEGMENT], ax
%endif

.default:
    mov word [pc88va_stage2_root_name_pointer], pc88va_stage2_kernel_name
    xor ax, ax
    jmp .finish
.invalid:
    mov ax, BOOT_CONFIG
    jmp .finish
.error:
    ; Preserve the actual raw loader error for the caller.  The kernel-name
    ; pointer is restored before any return, including failure.
    jmp .finish_error
.finish_error:
    mov [pc88va_cfg_result], ax
    mov word [pc88va_stage2_root_name_pointer], pc88va_stage2_kernel_name
    mov ax, [pc88va_cfg_result]
    jmp .restore
.finish:
    mov [pc88va_cfg_result], ax
.restore:
    pop es
    pop bp
    pop di
    pop si
    pop dx
    pop cx
    pop bx
    popf
    mov ax, [pc88va_cfg_result]
    ret

; DS:stage2 config record is already loaded.  Return AX=NONE, FOUND,
; INVALID, or DUPLICATE and store the value in pc88va_cfg_value.
pc88va_stage2_config_parse:
    mov word [pc88va_cfg_status], PC88VA_CFG_NONE
    mov word [pc88va_cfg_value], 0
    mov ax, [pc88va_stage2_config_file+FL_SEGMENT]
    mov es, ax
    mov si, [pc88va_stage2_config_file+FL_OFFSET]
    mov cx, [pc88va_stage2_config_file+FL_FILE_BYTES]
.line:
    or cx, cx
    jz .done
.leading:
    mov al, [es:si]
    cmp al, 0x0d
    je .consume_leading
    cmp al, 0x0a
    je .consume_leading
    cmp al, ' '
    je .consume_leading
    cmp al, 9
    jne .candidate
.consume_leading:
    inc si
    dec cx
    jmp .line
.candidate:
    cmp al, ';'
    je .skip_line
    cmp cx, 15
    jb .skip_line
    push si
    push cx
    mov di, pc88va_cfg_keyword
    mov bx, 15
.keyword:
    mov al, [es:si]
    mov dl, [ds:di]
    and al, 0xdf
    and dl, 0xdf
    cmp al, dl
    jne .not_keyword
    inc si
    inc di
    dec cx
    dec bx
    jnz .keyword
    pop cx
    pop si
    add si, 15
    sub cx, 15

    ; Parse one to four hexadecimal digits, with an optional trailing H.
    xor dx, dx
    xor bp, bp
.digits:
    or cx, cx
    jz .digits_done
    mov al, [es:si]
    ; Preserve the original byte for decimal digits.  Clearing bit 5
    ; unconditionally turns ASCII '0'..'9' into control bytes (for example
    ; '1' 31h becomes 11h), so case folding is only valid for A..F.
    cmp al, '0'
    jb .digits_done
    cmp al, '9'
    jbe .decimal_digit
    mov ah, al
    and ah, 0xdf
    cmp ah, 'A'
    jb .digits_done
    cmp ah, 'F'
    ja .digits_done
    mov bl, ah
    sub bl, 'A' - 10
    jmp .have_digit
.decimal_digit:
    mov bl, al
    sub bl, '0'
.have_digit:
    cmp bp, 4
    jae .invalid
    xor bh, bh
    shl dx, 1
    shl dx, 1
    shl dx, 1
    shl dx, 1
    add dx, bx
    inc bp
    inc si
    dec cx
    jmp .digits
.digits_done:
    cmp bp, 0
    je .invalid
    or cx, cx
    jz .line_value_done
    mov al, [es:si]
    and al, 0xdf
    cmp al, 'H'
    jne .line_value_done
    inc si
    dec cx
.line_value_done:
    ; Only horizontal whitespace and the line terminator may follow a value.
.value_tail:
    or cx, cx
    jz .accept_value
    mov al, [es:si]
    cmp al, ' '
    je .consume_value_tail
    cmp al, 9
    je .consume_value_tail
    cmp al, 0x0d
    je .accept_value
    cmp al, 0x0a
    je .accept_value
    jmp .invalid
.consume_value_tail:
    inc si
    dec cx
    jmp .value_tail
.accept_value:
    cmp word [pc88va_cfg_status], PC88VA_CFG_FOUND
    je .duplicate
    mov [pc88va_cfg_value], dx
    mov word [pc88va_cfg_status], PC88VA_CFG_FOUND
    jmp .skip_line
.not_keyword:
    pop cx
    pop si
.skip_line:
    or cx, cx
    jz .done
.skip_byte:
    mov al, [es:si]
    inc si
    dec cx
    cmp al, 0x0a
    jne .skip_byte
    jmp .line
.duplicate:
    mov word [pc88va_cfg_status], PC88VA_CFG_DUPLICATE
    jmp .done
.invalid:
    mov word [pc88va_cfg_status], PC88VA_CFG_INVALID
.done:
    mov ax, [pc88va_cfg_status]
    ret

; Validate [segment*16, segment*16+DX) against the profile-owned kernel-file
; window.  The profile validator proves that this whole window is disjoint
; from stage-2, scratch, stack, firmware, and the final allocation.  AX=0 is
; safe; AX=1 is rejected.
pc88va_stage2_validate_load_target:
    push bx
    push cx
    push dx
    push si
    push di
    push bp
    mov bx, ax
    mov cx, ax
    mov cl, 12
    shr cx, cl
    mov [pc88va_cfg_target_start_hi], cx
    mov bx, ax
    mov cl, 4
    shl bx, cl
    mov [pc88va_cfg_target_start_lo], bx
    mov bx, dx
    add bx, [pc88va_cfg_target_start_lo]
    mov [pc88va_cfg_target_end_lo], bx
    mov cx, [pc88va_cfg_target_start_hi]
    adc cx, 0
    mov [pc88va_cfg_target_end_hi], cx
    cmp cx, S2_KERNEL_FILE_END_HI
    ja .target_bad
    jb .target_start_ok
    cmp bx, S2_KERNEL_FILE_END_LO
    ja .target_bad
.target_start_ok:
    mov ax, S2_KERNEL_FILE_START_HI
    cmp ax, [pc88va_cfg_target_start_hi]
    ja .target_bad
    jb .target_valid
    mov ax, S2_KERNEL_FILE_START_LO
    cmp ax, [pc88va_cfg_target_start_lo]
    ja .target_bad
.target_valid:
    xor ax, ax
    jmp .target_restore
.target_bad:
    mov ax, 1
.target_done:
.target_restore:
    pop bp
    pop di
    pop si
    pop dx
    pop cx
    pop bx
    ret

pc88va_cfg_keyword:
    db 'PC88VA_LOADSEG='
pc88va_cfg_status: dw 0
pc88va_cfg_value: dw 0
pc88va_cfg_result: dw 0
pc88va_cfg_target_start_lo: dw 0
pc88va_cfg_target_start_hi: dw 0
pc88va_cfg_target_end_lo: dw 0
pc88va_cfg_target_end_hi: dw 0
