; SPDX-License-Identifier: GPL-2.0-or-later
; Original bounded firmware-adapter qualification probe.
; Supply a generated profile with NASM -p. Never commit a private profile.

bits 16

%ifndef PC88VA
    %error "PC88VA must be selected"
%endif
%ifdef NEC98
    %error "Conflicting machine family"
%endif
%ifdef IBMPC
    %error "Conflicting machine family"
%endif
%ifndef PROBE_ENTRY
    %error "Profile must define PROBE_ENTRY"
%endif
%ifndef FIRMWARE_VECTOR
    %error "Profile must define FIRMWARE_VECTOR"
%endif
%ifnmacro FIRMWARE_PROBE_STACK_SETUP 0
%macro FIRMWARE_PROBE_STACK_SETUP 0
%endmacro
%endif
%ifnmacro FIRMWARE_ERROR_BRANCH 1
    %error "Profile must define FIRMWARE_ERROR_BRANCH"
%endif

org PROBE_ENTRY

probe_entry:
    nop
    FIRMWARE_PROBE_STACK_SETUP
    FIRMWARE_REQUEST_SETUP
    int FIRMWARE_VECTOR
    FIRMWARE_ERROR_BRANCH probe_failure

probe_success:
    nop
    jmp short probe_success

probe_failure:
    nop
    jmp short probe_failure

; Build-time layout record; never executed.
probe_layout:
    dw probe_entry, probe_success, probe_failure
