; SPDX-License-Identifier: GPL-2.0-or-later
; Connect actual metadata acquisition and file traversal to the MZ handoff.
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

; DS:SI -> BL_SIZE; a validated ownership map covers all referenced workspace.
; Return only on error, restoring registers other than AX and FLAGS except CF.
pc88va_boot_load_core:
    pushf
    push bx
    push cx
    push dx
    push si
    push di
    push bp
    push es
    cmp si, 65536-BL_SIZE
    ja .bad_pointer
    mov bp, si
    mov word [ds:bp+BL_STAGE], 0
    mov word [ds:bp+BL_STATUS], 0
    cmp word [ds:bp+BL_VERSION], 1
    jne .contract
    mov bx, [ds:bp+BL_METADATA]
    cmp bx, 65536-VM_SIZE
    ja .contract
    cmp word [bx+VM_VERSION], 1
    jne .contract
    mov di, [ds:bp+BL_MZ]
    cmp di, 65536-MZ_CONTEXT_SIZE
    ja .contract
    cmp word [di+MZ_VERSION], 1
    jne .contract
    mov si, [bx+VM_FILE]
    cmp si, 65536-FL_SIZE
    ja .contract
    cmp word [si+FL_VERSION], 1
    jne .contract
    cmp word [si+FL_CAPACITY], 0
    je .contract
    mov ax, [si+FL_OFFSET]
    cmp ax, [di+MZ_FILE_OFFSET]
    jne .contract
    mov ax, [si+FL_SEGMENT]
    cmp ax, [di+MZ_FILE_SEGMENT]
    jne .contract
    mov si, bx
    call pc88va_volume_read_core
    or ax, ax
    jnz .error
    mov word [ds:bp+BL_STAGE], 3
    ; The pre-kernel selector is intentionally smaller than CONFIG.SYS
    ; processing. M16 passes the requested resident-kernel base to the
    ; carrier; ordinary CONFIG.SYS directives remain kernel-owned.
    call pc88va_stage2_config_bootstrap
    or ax, ax
    jnz .error
    mov bx, [ds:bp+BL_METADATA]
    mov si, [bx+VM_FILE]
    call pc88va_file_load_core
    or ax, ax
    jnz .error
    mov word [ds:bp+BL_STAGE], 6
    mov di, [ds:bp+BL_MZ]
    mov ax, [si+FL_FILE_BYTES]
    mov [di+MZ_FILE_BYTES], ax
    mov bx, [ds:bp+BL_METADATA]
    mov bx, [bx+VM_DISK]
    mov ax, [bx+RD_DRIVE_CONTEXT]
    mov [di+MZ_DRIVE_CONTEXT], ax
    mov si, di
    call pc88va_loader_handoff_core
    or ax, ax
    jnz .error
    ; A successful handoff has no returning continuation.
    mov ax, BOOT_RETURNED
    jmp .error
.contract:
    mov ax, BOOT_CONTRACT
.error:
    mov [ds:bp+BL_STATUS], ax
    jmp .restore
.bad_pointer:
    mov ax, BOOT_CONTRACT
.restore:
    pop es
    pop bp
    pop di
    pop si
    pop dx
    pop cx
    pop bx
    popf
    stc
    ret
