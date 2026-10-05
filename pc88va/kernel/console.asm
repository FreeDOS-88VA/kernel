; SPDX-License-Identifier: GPL-2.0-or-later
; One-byte adapter to the independently public PC-88VA Text BIOS service.
bits 16
%ifdef NEC98
%error PC88VA and NEC98 selectors are mutually exclusive
%endif
%ifdef IBMPC
%error PC88VA and IBMPC selectors are mutually exclusive
%endif
%ifndef PC88VA
%error PC88VA selector is required
%endif

%ifndef CONSOLE_FLAT_TEST
%include "../kernel/segs.inc"
%ifdef PC88VA_M13
%include "kernel/m13_segments.inc"
%endif
; DOS-C's generic IO dispatcher consumes this table.  The table is PC-88VA
; owned, while DOS semantics (request packets and status bits) remain in the
; common io.asm implementation.
segment _IO_FIXED_DATA
global ConTable
ConTable:       db 0Ah
                dw ConInitDispatch
                dw ConStatusDone
                dw ConStatusDone
                dw ConStatusError
                dw ConReadDispatch
                dw CommonNdRdExitDispatch
                dw CommonNdRdExitDispatch
                dw ConInpFlushDispatch
                dw ConWriteDispatch
                dw ConWriteDispatch
                dw ConStatusDone

segment _IO_TEXT
extern _IOExit, _IOCommandError, _syscon

; The common dispatcher stores near offsets in ConTable and performs an
; indirect jump through its own CS.  Keep these five table targets in LGROUP,
; then cross to the resident CODE segment explicitly; the implementation and
; its near calls remain in one segment close to the validated stack arena.
global ConInitDispatch, ConReadDispatch, CommonNdRdExitDispatch
global ConInpFlushDispatch, ConWriteDispatch
ConInitDispatch:
                jmp far ConInit
ConReadDispatch:
                jmp far ConRead
CommonNdRdExitDispatch:
                jmp far CommonNdRdExit
ConInpFlushDispatch:
                jmp far ConInpFlush
ConWriteDispatch:
                jmp far ConWrite
ConStatusDone:
                jmp far _IOExit
ConStatusError:
                jmp far _IOCommandError

segment _PC88VA_CODE class=CODE public use16
extern _IODone, _IOErrorExit, _ReqPktPtr
extern pc88va_console_getc_dos_, pc88va_console_peek_dos_, pc88va_console_read_dos_
extern pc88va_m11_character_, pc88va_m16_input_flush_

global _kbdType
_kbdType:        db 0

; Bridge the common device-driver call (DS = DOS data) to the M11 ABI (DS = CS).
global pc88va_dos_getc_
pc88va_dos_getc_:
                push ds
                push cs
                pop ds
                mov ax, pc88va_m11_character_
                call pc88va_console_read_dos_
                pop ds
                ret

; Bridge the DOS data segment to the non-destructive status side.  The
; character latch is owned by console_input.asm and is not consumed here.
global pc88va_dos_peek_
pc88va_dos_peek_:
                push ds
                push cs
                pop ds
                mov ax, pc88va_m11_character_
                call pc88va_console_peek_dos_
                pop ds
                ret

global ConInit, ConRead, ConInpFlush, ConWrite, CommonNdRdExit
ConInit:
                call pc88va_m16_input_flush_
                jmp far _IOExit

ConRead:
                jcxz ConReadDone
ConReadLoop:
                call pc88va_dos_getc_
                cmp ax, 1
                je ConReadLoop
                or ax, ax
                jz ConReadReady
                jmp far _IOErrorExit
ConReadReady:
                mov al, [cs:pc88va_m11_character_]
                stosb
                loop ConReadLoop
ConReadDone:
                jmp far _IOExit

; Non-destructive status is a single M11 poll.  The common dispatcher owns the
; request packet and maps busy/done/error status for DOS callers.
CommonNdRdExit:
                call pc88va_dos_peek_
                cmp ax, 1
                jne CommonNdCheck
                jmp far _IODone
CommonNdCheck:
                or ax, ax
                jz CommonNdReady
                jmp far _IOErrorExit
CommonNdReady:
                ; The packet pointer belongs to the common dispatcher's
                ; LGROUP, not this platform code frame.  DS is disposable
                ; here: _IOExit restores the dispatcher's saved registers.
                mov bx, seg _ReqPktPtr
                mov ds, bx
                lds bx, [_ReqPktPtr]
                cmp byte [bx+2], 6
                je CommonNdReadyDone
                mov al, [cs:pc88va_m11_character_]
                mov [bx+0Dh], al
                jmp far _IOExit
CommonNdReadyDone:
                jmp far _IOExit

ConInpFlush:
                call pc88va_m16_input_flush_
                jmp far _IOExit

ConWrite:
                or cx, cx
                jnz ConWriteLoop
                jmp far _IOExit
ConWriteLoop:
                xor ax, ax
                mov al, [es:di]
                inc di
                call pc88va_console_putc_
                or ax, ax
                jz ConWriteReady
                jmp far _IOErrorExit
ConWriteReady:
                loop ConWriteLoop
                jmp far _IOExit

; Common initialization installs INT 29h for compact kernel diagnostics.
; Route it through the accepted PC-88VA console service, never BIOS INT 10h.
global _int29_handler
_int29_handler:
                push ax
                pushf
                xor ah, ah
                call pc88va_console_putc_
                popf
                pop ax
                iret
%else
segment _TEXT
%endif
%ifdef CONSOLE_FLAT_TEST
; Standalone adapter tests do not provide DOS's LoL syscon pointer.  Keep a
; local placeholder so the private probe labels remain assembleable without
; changing the production table or dispatch path.
_syscon:        dw 0, 0
%endif
global pc88va_console_putc_
global pc88va_m13_stage_probe_
global pc88va_m13_after_initio_probe_
global pc88va_m13_after_setup_probe_
global pc88va_m13_after_psp_probe_
global pc88va_m13_after_clock_probe_
global pc88va_m13_after_pspset_probe_
global pc88va_m13_after_dta_probe_
global pc88va_m13_after_pspinit_probe_
global pc88va_m13_after_dsk_probe_
global pc88va_m13_before_dsk_print_probe_
global pc88va_m13_after_dsk_print_probe_
global pc88va_m13_after_dta_irqptr_probe_
global pc88va_m13_after_pspinit_irqptr_probe_
global pc88va_m13_after_dta_irqptr_probe_ptr_
global pc88va_m13_after_pspinit_irqptr_probe_ptr_
global pc88va_m13_int21_vector_probe_
global pc88va_m13_int21_vector_probe_done_
global pc88va_m13_before_dta_vector_probe_
global pc88va_m13_before_dta_vector_probe_done_
global pc88va_m13_before_initio_vector_probe_
global pc88va_m13_before_initio_vector_capture_
global pc88va_m13_after_initio_vector_probe_
global pc88va_m13_after_initio_vector_capture
global pc88va_m13_after_setup_vector_probe_
global pc88va_m13_after_setup_vector_capture
global pc88va_m13_after_pspset_vector_probe_
global pc88va_m13_after_pspset_vector_capture
global pc88va_m13_initio_enter_probe_
global pc88va_m13_init_device_enter_probe_
global pc88va_m13_init_device_pointer_capture_
global pc88va_m13_init_device_pre_execrh_probe_
global pc88va_m13_init_device_post_execrh_probe_
global pc88va_m13_init_device_next_probe_
%ifndef PC88VA_M13
global pc88va_console_diagnostic_
global _pc88va_m09_message
global _pc88va_m09_diagnostic_complete
global _pc88va_console_preconditions_valid
%endif
global pc88va_console_putc_.ready
global pc88va_console_putc_.firmware

; Open Watcom small-model register convention: AX = unsigned character.
; AX = 0 on firmware return, FFFFh for unsupported byte or missing vector.
; Other general registers, DS, ES, FLAGS and the caller's stack are preserved.
; Private diagnostic entry used only to bracket the InitIO boundary.
; Read the actual IVT 21h words after MoveKernel's vector refresh.  The
; post-load label is the capture point; no guest-visible output is emitted.
pc88va_m13_int21_vector_probe_:
        push ds
        xor ax, ax
        mov ds, ax
        mov bx, [0x84]
        mov cx, [0x86]
pc88va_m13_int21_vector_probe_done:
        pop ds
        retf

; Private diagnostic: sample IVT 21h immediately before SET_DTA.  This is
; intentionally separate from the post-MoveKernel sample so an intervening
; vector rewrite can be distinguished without changing the INT21 path.
pc88va_m13_before_dta_vector_probe_:
        push ds
        xor ax, ax
        mov ds, ax
        mov bx, [0x84]
        mov cx, [0x86]
pc88va_m13_before_dta_vector_probe_done:
        pop ds
        retf

; Boundary-only IVT samples used to locate the first overwrite of INT 21h.
; Each capture label leaves BX=IVT offset and CX=IVT segment for the private
; observer, while restoring DS before returning to the caller.
%macro M13_VECTOR_SAMPLE 2
%1:
        pushf
        push ax
        push bx
        push cx
        push ds
        xor ax, ax
        mov ds, ax
        mov bx, [0x84]
        mov cx, [0x86]
%2:
        pop ds
        pop cx
        pop bx
        pop ax
        popf
        retf
%endmacro

M13_VECTOR_SAMPLE pc88va_m13_before_initio_vector_probe_, pc88va_m13_before_initio_vector_capture
M13_VECTOR_SAMPLE pc88va_m13_after_initio_vector_probe_, pc88va_m13_after_initio_vector_capture
M13_VECTOR_SAMPLE pc88va_m13_after_setup_vector_probe_, pc88va_m13_after_setup_vector_capture
M13_VECTOR_SAMPLE pc88va_m13_after_pspset_vector_probe_, pc88va_m13_after_pspset_vector_capture

; InitIO request-boundary probes.  These are no-op far-call targets used only
; by the private VAEG observer to distinguish loop entry from EXECRH entry and
; return.  They intentionally do not touch machine state.
pc88va_m13_initio_enter_probe_:
        retf

pc88va_m13_init_device_enter_probe_:
        ; Open Watcom passes this optimized single FAR argument in AX:DX
        ; (offset:segment) at this call site.  Inspect the device header using
        ; a temporary DS, while preserving the complete caller state.  The
        ; private observer stops at the capture label before restoration.
        pushf
        push ax
        push bx
        push cx
        push dx
        push ds
        push si
        mov si, ax
        mov ax, dx
        mov ds, ax
        mov ax, [si]
        mov bx, [si+2]
        mov cx, [si+4]
        mov dx, [si+6]
global pc88va_m13_init_device_pointer_capture_
pc88va_m13_init_device_pointer_capture_:
        pop si
        pop ds
        pop dx
        pop cx
        pop bx
        pop ax
        popf
        retf

pc88va_m13_init_device_pre_execrh_probe_:
        retf

pc88va_m13_init_device_post_execrh_probe_:
        ; Sample IVT[21h] immediately after EXECRH returns.  Preserve the
        ; complete caller state; the private observer stops before restore.
        pushf
        push ax
        push bx
        push cx
        push dx
        push ds
        xor ax, ax
        mov ds, ax
        mov bx, [0x84]
        mov cx, [0x86]
global pc88va_m13_init_device_post_execrh_vector_capture_
pc88va_m13_init_device_post_execrh_vector_capture_:
        pop ds
        pop dx
        pop cx
        pop bx
        pop ax
        popf
        retf

pc88va_m13_init_device_next_probe_:
        retf

pc88va_m13_stage_probe_:
        retf

pc88va_m13_after_initio_probe_:
        ; Capture the LoL->syscon far pointer before the first post-InitIO
        ; BIOS call.  The probe preserves the caller state; the observer
        ; samples BX:DX at the capture label and then execution continues.
        pushf
        push ax
        push bx
        push cx
        push dx
        mov bx, [_syscon]
        mov dx, [_syscon+2]
global pc88va_m13_after_initio_syscon_capture_
pc88va_m13_after_initio_syscon_capture_:
        pop dx
        pop cx
        pop bx
        pop ax
        popf
        retf

pc88va_m13_after_setup_probe_:
        retf

pc88va_m13_after_psp_probe_:
        retf

pc88va_m13_after_clock_probe_:
        retf

pc88va_m13_after_pspset_probe_:
        retf

pc88va_m13_after_dta_probe_:
        push    ds
        mov     ax, 040h
        mov     ds, ax
        mov     bx, [0228h]
        mov     dx, [022ah]
        pop     ds
pc88va_m13_after_dta_probe_ptr_:
        retf

pc88va_m13_after_dta_irqptr_probe_:
        push ds
        mov ax, 040h
        mov ds, ax
        mov bx, [0cb0h]
        mov dx, [0cb2h]
        pop ds
pc88va_m13_after_dta_irqptr_probe_ptr_:
        retf

pc88va_m13_after_pspinit_probe_:
        push    ds
        mov     ax, 040h
        mov     ds, ax
        mov     bx, [0228h]
        mov     dx, [022ah]
        pop     ds
pc88va_m13_after_pspinit_probe_ptr_:
        retf

pc88va_m13_after_pspinit_irqptr_probe_:
        push ds
        mov ax, 040h
        mov ds, ax
        mov bx, [0cb0h]
        mov dx, [0cb2h]
        pop ds
pc88va_m13_after_pspinit_irqptr_probe_ptr_:
        retf

pc88va_m13_after_dsk_probe_:
        retf

pc88va_m13_before_dsk_print_probe_:
        retf

pc88va_m13_after_dsk_print_probe_:
        retf

pc88va_console_putc_:
        pushf
        push bx
        push cx
        push dx
        push si
        push di
        push bp
        push ds
        push es
        cmp ax, 13
        je .accepted
        cmp ax, 10
        je .accepted
        cmp ax, 08h
        je .accepted
        cmp ax, 020h
        jb .unavailable
        cmp ax, 07eh
        ja .unavailable
.accepted:
        xor bx, bx
        mov es, bx
        mov bx, [es:083h * 4]
        or bx, [es:083h * 4 + 2]
        jz .unavailable
.ready:
        ; The word is the byte followed by a NUL; no global scratch buffer.
        push ax
        push ss
        pop ds
        mov si, sp
        mov dx, 08000h
        mov ah, 02h
.firmware:
        int 083h
        add sp, 2
        xor ax, ax
        jmp short .restore
.unavailable:
        mov ax, 0ffffh
.restore:
        pop es
        pop ds
        pop bp
        pop di
        pop si
        pop dx
        pop cx
        pop bx
        popf
        ret

; Medium-model C diagnostics call through a FAR entry, while the established
; console adapter remains a near-return routine for its assembly callers.
global pc88va_diag_putc_
pc88va_diag_putc_:
        call pc88va_console_putc_
        retf

; Milestone diagnostics are entered only from the compile-only startup.asm
; entry; the linked M13 kernel does not keep them resident.
%ifndef PC88VA_M13
pc88va_console_diagnostic_:
        pushf
        push si
        ; Establish the diagnostic precondition before its first putc call.
        ; Each standalone putc still validates its own inherited vector.
        push bx
        push es
        xor bx, bx
        mov es, bx
        mov bx, [es:083h * 4]
        or bx, [es:083h * 4 + 2]
        pop es
        pop bx
        jnz _pc88va_console_preconditions_valid
        mov ax, 0ffffh
        jmp _pc88va_m09_diagnostic_complete
_pc88va_console_preconditions_valid:
        mov si, _pc88va_m09_message
.next:
        xor ax, ax
        mov al, [cs:si]
        inc si
        test al, al
        jz _pc88va_m09_diagnostic_complete
        call pc88va_console_putc_
        test ax, ax
        jz .next
_pc88va_m09_diagnostic_complete:
        pop si
        popf
        ret

_pc88va_m09_message:
        db 13, 'FreeDOS/PC-88VA M09', 13, 10
        db '012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789'
        db 13, 10, 'CONSOLE OK', 13, 10, 0
        db 'M09SERVICE:CONSOLE_PUTC:TEXT_BIOS', 0
%endif
