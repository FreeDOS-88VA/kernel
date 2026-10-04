; SPDX-License-Identifier: GPL-2.0-or-later
; Compile-only PC-88VA kernel entry. This code deliberately cannot continue.

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

segment _TEXT class=CODE public use16

extern pc88va_platform_probe_
extern pc88va_console_diagnostic_
extern pc88va_machine_init_
extern pc88va_fatal_stop_request_
extern pc88va_m10_control_
extern pc88va_m11_diagnostic_
extern pc88va_m12_diagnostic_
extern pc88va_m12_drive_context_
extern pc88va_m12_call_flags_
global pc88va_m10_i0, pc88va_m10_i9, pc88va_m10_f0, pc88va_m10_f1
global ..start
global _pc88va_compile_only_entry
global _pc88va_compile_only_fatal_stop

..start:
_pc88va_compile_only_entry:
        cli
        cld
        mov [cs:pc88va_m12_drive_context_], dx
        mov [cs:pc88va_m12_call_flags_], bx
        call pc88va_platform_probe_
        call pc88va_console_diagnostic_
        or ax, ax
        jnz _pc88va_compile_only_fatal_stop
pc88va_m10_i0:
        call pc88va_machine_init_
        or ax, ax
        jnz _pc88va_compile_only_fatal_stop
pc88va_m10_i9:
pc88va_m10_f0:
        cmp byte [cs:pc88va_m10_control_], 1
        jne pc88va_m11_entry
pc88va_m10_f1:
        xor ax, ax
        call pc88va_fatal_stop_request_

pc88va_m11_entry:
        call pc88va_m11_diagnostic_
        call pc88va_m12_diagnostic_
        or ax, ax
        jnz _pc88va_compile_only_fatal_stop

_pc88va_compile_only_fatal_stop:
        cli
        hlt
        jmp short _pc88va_compile_only_fatal_stop

segment _STACK class=STACK stack use16
        resb 256
