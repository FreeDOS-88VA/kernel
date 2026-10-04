;
; File:
;                          execrh.asm
; Description:
;             request handler for calling device drivers
;
;                    Copyright (c) 1995, 1998
;                       Pasquale J. Villani
;                       All Rights Reserved
;
; This file is part of DOS-C.
;
; DOS-C is free software; you can redistribute it and/or
; modify it under the terms of the GNU General Public License
; as published by the Free Software Foundation; either version
; 2, or (at your option) any later version.
;
; DOS-C is distributed in the hope that it will be useful, but
; WITHOUT ANY WARRANTY; without even the implied warranty of
; MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See
; the GNU General Public License for more details.
;
; You should have received a copy of the GNU General Public
; License along with DOS-C; see the file COPYING.  If not,
; write to the Free Software Foundation, 675 Mass Ave,
; Cambridge, MA 02139, USA.
;
; $Id: execrh.asm 1184 2006-05-20 20:49:59Z mceric $
;

                %include "segs.inc"
                %include "stacks.inc"

segment	HMA_TEXT
                ; EXECRH
                ;       Execute Device Request
                ;
                ; execrh(rhp, dhp)
                ; request far *rhp;
                ; struct dhdr far *dhp;
                ;
;
; The stack is very critical in here.
;
        global  EXECRH
	global  INIT_EXECRH

%macro EXECRHM 0
                push    bp              ; perform c entry
                mov     bp,sp
                push    si
                push    ds              ; sp=bp-8

arg {rhp,4}, {dhp,4}
; Open Watcom emits a far call for this entry in the split M13 text groups;
; account for the return IP:CS before the Pascal far arguments.  The
; historical offsets remain for non-Watcom targets.
%ifdef PC88VA
%define EXECRH_DHP bp+6
%define EXECRH_RHP bp+10
%else
%define EXECRH_DHP .dhp
%define EXECRH_RHP .rhp
%endif
                lds     si,[EXECRH_DHP]       ; ds:si = device header
                les     bx,[EXECRH_RHP]       ; es:bx = request header


                mov     ax, [si+6]      ; construct strategy address
                mov     [EXECRH_DHP], ax

                push si                 ; the bloody fucking RTSND.DOS 
                push di                 ; driver destroys SI,DI (tom 14.2.03)

                call    far[EXECRH_DHP]       ; call far the strategy

                pop di 
                pop si
                                
                ; Protect386Registers	; old free-EMM386 versions destroy regs in their INIT method

                mov     ax,[si+8]       ; construct 'interrupt' address
                mov     [EXECRH_DHP],ax       ; construct interrupt address
                call    far[EXECRH_DHP]       ; call far the interrupt

%ifdef PC88VA
                ; Private return-boundary sample.  Preserve every register
                ; this helper touches so the real EXECRH epilogue is unchanged.
                pushf
                push    ax
                push    ds
                push    si
                push    di
                xor     ax,ax
                mov     ds,ax
                mov     si,[0x84]
                mov     di,[0x86]
                global  pc88va_m13_execrh_after_interrupt_capture
pc88va_m13_execrh_after_interrupt_capture:
                pop     di
                pop     si
                pop     ds
                pop     ax
                popf
%endif

                ; Restore386Registers	; less stack load and better performance...

                sti                     ; damm driver turn off ints
                cld                     ; has gone backwards
                pop     ds
                pop     si
                pop     bp
%ifdef PC88VA
                ; EXECRH is a far C entry in the split M13 text groups.
                ; Discard the two far arguments after consuming IP:CS.
                retf    8
%else
                ret     8
%endif
%endmacro

EXECRH:
	EXECRHM

%ifndef WATCOM

segment INIT_TEXT

INIT_EXECRH:
	EXECRHM

%endif
