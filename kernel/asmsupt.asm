; File:
;                         asmsupt.asm
; Description:
;       Assembly support routines for miscellaneous functions
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
; version 1.4 by tom.ehlert@ginko.de
; added some more functions
; changed bcopy, scopy, sncopy,...
; to      memcpy, strcpy, strncpy
; Bart Oldeman: optimized a bit: see /usr/include/bits/string.h from 
; glibc 2.2
;
; $Id: asmsupt.asm 1568 2011-04-09 02:42:51Z bartoldeman $
;

; for OW on Linux:
%ifdef owlinux
%define WATCOM
%endif

%ifdef WATCOM
%ifdef _INIT
%define WATCOM_INIT ; no seperate init segment for watcom.
%endif
%endif

%ifndef WATCOM_INIT

		%include "segs.inc"
		%include "stacks.inc"

%ifdef _INIT

  segment INIT_TEXT
  %define  FMEMCPYBACK INIT_FMEMCPYBACK
  %define   MEMCPY   INIT_MEMCPY
  %define  FMEMCPY  INIT_FMEMCPY
  %define   MEMSET   INIT_MEMSET
  %define  FMEMSET  INIT_FMEMSET
  %define   STRCPY   INIT_STRCPY
  %define  FSTRCPY  INIT_FSTRCPY
  %define   STRLEN   INIT_STRLEN
  %define  FSTRLEN  INIT_FSTRLEN
  %define  FMEMCHR  INIT_FMEMCHR
  %define  FSTRCHR  INIT_FSTRCHR
  %define   STRCHR   INIT_STRCHR
  %define  FSTRCMP  INIT_FSTRCMP
  %define   STRCMP   INIT_STRCMP
  %define FSTRNCMP INIT_FSTRNCMP
  %define  STRNCMP  INIT_STRNCMP
  %define  FMEMCMP  INIT_FMEMCMP
  %define   MEMCMP   INIT_MEMCMP

%else

  segment HMA_TEXT

%endif

;*********************************************************************
; this implements some of the common string handling functions
;
; every function has 1 entry
;
;   NEAR FUNC()
;
; currently done:
;
; fmemcpyBack(void FAR *dest, void FAR *src, int count)
;  memcpy(void     *dest, void     *src, int count)
; fmemcpy(void FAR *dest, void FAR *src, int count)
;  memset(void *dest, int ch, int count);
; fmemset(void FAR *dest, int ch, int count);
;  strcpy (void    *dest, void     *src);
; fstrcpy (void FAR*dest, void FAR *src);
;  strlen (void    *dest);
; fstrlen (void FAR*dest);
; fmemchr (BYTE FAR *src , int ch);
; fstrchr (BYTE FAR *src , int ch);
;  strchr (BYTE     *src , int ch);
; fstrcmp (BYTE FAR *s1 , BYTE FAR *s2);
;  strcmp (BYTE     *s1 , BYTE     *s2);
; fstrncmp(BYTE FAR *s1 , BYTE FAR *s2, int count);
;  strncmp(BYTE     *s1 , BYTE     *s2, int count);
; fmemcmp(BYTE FAR *s1 , BYTE FAR *s2, int count);
;  memcmp(BYTE     *s1 , BYTE     *s2, int count);

;***********************************************
; pascal_setup - set up the standard calling frame for C-functions
;                and save registers needed later
;                also preload the args for the near functions
;                di=arg1
;                si=arg2
;                cx=arg3
;
pascal_setup:
                pop     ax                      ; get return address
                
                push    bp                      ; Standard C entry
                mov     bp,sp
%ifdef WATCOM
                push    bx
                push    cx
                push    es
%endif
                push    si
                push    di
                push    ds
                ; Set both ds and es to same segment (for near copy)
                push    ds
                pop     es

                ; Set direction to autoincrement
                cld

                mov bl,6       ; majority (4) wants that
arg arg1, arg2, arg3
                mov cx,[.arg3] ; majority (8) wants that (near and far)
                mov si,[.arg2] ; majority (3) wants that (near)
                mov di,[.arg1] ; majority (3) wants that (near)
                
                jmp ax



        
;***********************************************
;
;       VOID memcpy(REG BYTE *s, REG BYTE *d, REG COUNT n);
;
                global  MEMCPY
%ifdef PC88VA
; Medium-model C calls are FAR even when both data pointers are NEAR.  The
; historical pascal_setup helper is a NEAR-frame trampoline and would read
; the outer return CS as the count when entered through a FAR call.  Keep the
; PC-88VA entry frame explicit and consume the six argument bytes here.
MEMCPY:
                push    bp
                mov     bp, sp
                push    bx
                push    cx
                push    es
                push    si
                push    di
                push    ds

                ; FAR Pascal frame: +6 count, +8 source, +10 destination.
                mov     cx, [bp+6]
                mov     si, [bp+8]
                mov     di, [bp+10]
                push    ds
                pop     es
                cld
                shr     cx, 1
                rep     movsw
                jnc     .memcpy_done
                movsb
.memcpy_done:
                pop     ds
                pop     di
                pop     si
                pop     es
                pop     cx
                pop     bx
                pop     bp
                retf    6
%else
MEMCPY:
                call pascal_setup

                ;mov cx,[4+bp] - preset above
                ;mov si,[6+bp] - preset above
                ;mov di,[8+bp] - preset above

                ;mov bl,6 - preset above


domemcpy:
                ; And do the built-in byte copy, but do a 16-bit transfer
                ; whenever possible.
                shr     cx,1
                rep     movsw
                jnc     memcpy_return
                movsb
memcpy_return:
%if 0                           ; only needed for fmemcpyback
                cld
%endif        

;
; pascal_return - pop saved registers and do return
;
        
                jmp pascal_return
%endif



;************************************************************
;
;       VOID fmemcpy(REG BYTE FAR *d, REG BYTE FAR *s,REG COUNT n);
;       VOID fmemcpyBack(REG BYTE FAR *d, REG BYTE FAR *s,REG COUNT n);
;
                global  FMEMCPY
%if 0
                global  FMEMCPYBACK
FMEMCPYBACK:
                std             ; force to copy the string in reverse order
%endif
%ifdef PC88VA
; The PC-88VA target uses the medium Open Watcom model, so this symbol is
; entered by a FAR Pascal call.  The historical helper below is a NEAR-only
; trampoline (pascal_setup consumes one return word); calling it FAR leaves
; the return CS in the count/pointer slots.  Keep the common helper unchanged
; for other targets and use a small frame-correct FAR implementation here.
FMEMCPY:
global pc88va_fmemcpy_entry_probe
pc88va_fmemcpy_entry_probe:
                push    bp
                mov     bp, sp
                push    bx
                push    cx
                push    es
                push    si
                push    di
                push    ds

                ; FAR Pascal frame after the saved BP as emitted by the
                ; Open Watcom PC-88VA caller:
                ; +2 return IP, +4 return CS, +6 count,
                ; +8 source offset, +10 source segment,
                ; +12 destination offset, +14 destination segment.
                ;
                ; The C declaration is (dest, src, count), while this
                ; target's Pascal ABI emits the pointer pairs in source-then-
                ; destination order at the callee.  The generated caller and
                ; runtime trace are the authority for this frame.
                mov     cx, [bp+6]
                mov     si, [bp+8]
                mov     ax, [bp+10]
                mov     ds, ax
                mov     di, [bp+12]
                mov     ax, [bp+14]
                mov     es, ax
                cld
global pc88va_fmemcpy_before_copy_probe
pc88va_fmemcpy_before_copy_probe:
                rep     movsb
global pc88va_fmemcpy_after_copy_probe
pc88va_fmemcpy_after_copy_probe:

                pop     ds
                pop     di
                pop     si
                pop     es
                pop     cx
                pop     bx
                pop     bp
global pc88va_fmemcpy_before_return_probe
pc88va_fmemcpy_before_return_probe:
                retf    10
%else
FMEMCPY:
                call pascal_setup

arg {d,4}, {s,4}, n
                ; Get the repetition count, n preset above
%ifdef STDCALL
                mov     cx,[.n]
%endif

                ; Get the far source pointer, s
                lds     si,[.s]

                ; Get the far destination pointer d
                les     di,[.d]
		mov	bl,10

                jmp short domemcpy
%endif

;***************************************************************
;
;       VOID fmemset(REG VOID FAR *d, REG BYTE ch, REG COUNT n);
;
                global  FMEMSET
%ifdef PC88VA
; PC-88VA medium-model callers use a FAR Pascal frame.  Open Watcom emits
; the destination pointer followed by the fill word and count, so after the
; FAR return frame the callee sees count at +6, fill at +8 and dest at +10/+12.
FMEMSET:
                push    bp
                mov     bp, sp
                push    bx
                push    cx
                push    es
                push    di

                mov     cx, [bp+6]
                mov     ax, [bp+8]
                les     di, [bp+10]
                mov     al, al
                mov     ah, al
                cld
                shr     cx, 1
                rep     stosw
                jnc     .fmemset_done
                stosb
.fmemset_done:
                pop     di
                pop     es
                pop     cx
                pop     bx
                pop     bp
                retf    8
%else
FMEMSET:
                call pascal_setup

arg {d,4}, ch, n
                ; Get the repetition count, n - preset above
%ifdef STDCALL
                mov     cx,[.n]
%endif

                ; Get the fill byte ch
                mov     ax,[.ch]
                
                ; Get the far source pointer, s
                les     di,[.d]
		mov	bl,8

domemset:                
                mov	ah, al

                shr	cx,1
                rep     stosw
                jnc     pascal_return
                stosb
                
                jmp  short pascal_return
%endif

;***************************************************************
;
;       VOID memset(REG VOID *d, REG BYTE ch, REG COUNT n);
;
                global  MEMSET
%ifdef PC88VA
; Medium-model C calls are FAR even when the destination data pointer is
; NEAR.  Use DS as the segment for that pointer and consume the six bytes
; (pointer, fill word, count) left by the caller.
MEMSET:
                push    bp
                mov     bp, sp
                push    bx
                push    cx
                push    es
                push    di

                mov     cx, [bp+6]
                mov     ax, [bp+8]
                mov     di, [bp+10]
                push    ds
                pop     es
                mov     ah, al
                cld
                shr     cx, 1
                rep     stosw
                jnc     .memset_done
                stosb
.memset_done:
                pop     di
                pop     es
                pop     cx
                pop     bx
                pop     bp
                retf    6
%else
MEMSET:
                call pascal_setup
                
arg d, ch, n
                ; Get the repitition count, n - preset above
                ; mov     cx,[bp+4]

                ; Get the char ch
                mov     ax, [.ch]

                ; Get the far source pointer, d - preset above
                ; mov      di,[bp+8]

		;mov	bl, 6   ; preset above

                jmp short domemset
%endif

;*****
pascal_return:
                lds     di, [bp]    ; return address in ds, saved bp in di
                mov     bh, 0
                add     bp, bx      ; point bp to "as if there were 0 args"
                mov     [bp+2], ds  ; put return address at first arg
                mov     [bp], di    ; saved bp below that one

                pop     ds
                pop     di
                pop     si
%ifdef WATCOM
                pop     es
                pop     cx
                pop     bx
%endif
                mov     sp,bp
                pop     bp
                ret

;*****************************************************************
                
; fstrcpy (void FAR*dest, void FAR *src);

%ifndef _INIT
                global  FSTRCPY
%ifdef PC88VA
; Medium-model callers use a FAR CALL even when the data pointers are FAR.
; Keep this entry independent from the shared NEAR trampoline.  Pascal
; argument order is (dest, src), so after the FAR prologue the source is at
; +6/+8 and the destination is at +10/+12.
FSTRCPY:
                push    bp
                mov     bp, sp
                push    bx
                push    cx
                push    dx
                push    si
                push    di
                push    es
                push    ds

                mov     si, [bp+6]
                mov     ax, [bp+8]
                mov     ds, ax
                mov     di, [bp+10]
                mov     ax, [bp+12]
                mov     es, ax
                cld

pc88va_fstrcpy_loop:
                lodsb
                stosb
                test    al, al
                jne     pc88va_fstrcpy_loop

                pop     ds
                pop     es
                pop     di
                pop     si
                pop     dx
                pop     cx
                pop     bx
                pop     bp
                retf    8
%else
FSTRCPY:
                call pascal_setup

arg {dest,4}, {src,4}
                ; Get the source pointer, ss
                lds   si,[.src]

                ; and the destination pointer, d
                les   di,[.dest]

		mov   bl,8

                jmp short dostrcpy
%endif
%endif

;******
                global  STRCPY
%ifdef PC88VA
; Near data pointers remain one word each.  The code call is nevertheless FAR
; under the medium model, so use the FAR frame (+6 source, +8 destination).
STRCPY:
                push    bp
                mov     bp, sp
                push    bx
                push    cx
                push    dx
                push    si
                push    di
                push    es
                push    ds

                mov     si, [bp+6]
                mov     di, [bp+8]
                push    ds
                pop     es
                cld

pc88va_strcpy_loop:
                lodsb
                stosb
                test    al, al
                jne     pc88va_strcpy_loop

                mov     ax, [bp+8]
                pop     ds
                pop     es
                pop     di
                pop     si
                pop     dx
                pop     cx
                pop     bx
                pop     bp
                retf    4
%else
STRCPY:
                call pascal_setup


%ifdef PASCAL
                ; Get the source pointer, ss
                mov   si,[bp+4]

                ; and the destination pointer, d
                mov   di,[bp+6]
%endif
		mov   bl,4

dostrcpy:

strcpy_loop:                
                lodsb
                stosb
                test al,al
                jne  strcpy_loop

                jmp  short pascal_return
%endif

;******************************************************************                
%ifndef _INIT                
                global  FSTRLEN
%ifdef PC88VA
; Medium-model C callers enter the FAR string helper through a FAR CALL.
; Keep the historical NEAR trampoline for other targets, but use an explicit
; FAR frame here so the return CS is consumed and the FAR argument is read
; from the correct offsets.  The public pragma promises AX as the only
; clobbered register.
FSTRLEN:
                push    bp
                mov     bp, sp
                push    bx
                push    cx
                push    es
                push    di

                les     di, [bp+6]
                xor     ax, ax
                mov     cx, 0ffffh
                repne   scasb
                mov     ax, cx
                not     ax
                dec     ax

                pop     di
                pop     es
                pop     cx
                pop     bx
                pop     bp
                retf    4
%else
FSTRLEN:
                call pascal_setup

                ; Get the source pointer, ss
                les   di,[bp+4]
		mov   bl,4

                jmp short dostrlen
%endif
%endif

;**********************************************
                global  STRLEN
%ifdef PC88VA
; Open Watcom medium-model callers use a FAR Pascal call even when the
; character pointer is a NEAR data pointer.  The shared pascal_setup and
; pascal_return path is a NEAR-call trampoline: entering it through FAR CALL
; leaves the caller's CS on the stack and its final RET transfers to the
; caller continuation in the HMA segment.  Keep this target-specific entry
; separate so other targets and the shared return path remain unchanged.
STRLEN:
                push    bp
                mov     bp, sp
                push    bx
                push    cx
                push    dx
                push    si
                push    di
                push    es
                push    ds

                ; FAR Pascal frame after the saved BP:
                ; +2 return IP, +4 return CS, +6 one-word NEAR pointer.
                ; The pointer is relative to the caller's DS; use that same
                ; segment as ES for SCASB without changing the saved DS.
                mov     di, [bp+6]
                push    ds
                pop     es
                xor     ax, ax
                mov     cx, 0ffffh
                cld
                repne   scasb

                mov     ax, cx
                not     ax
                dec     ax

                pop     ds
                pop     es
                pop     di
                pop     si
                pop     dx
                pop     cx
                pop     bx
                pop     bp
                ; ASMPASCAL owns the single 16-bit argument.
                retf    2
%else
STRLEN:
                call pascal_setup
                ; Get the source pointer, ss
%ifdef PASCAL
                mov   di,[bp+4]
%endif
		mov   bl,2

dostrlen:
                mov al,0
                mov cx,0xffff
                repne scasb

                mov ax,cx
                not ax
                dec ax

                jmp short pascal_return
%endif

;************************************************************
; strchr (BYTE *src , int ch);

                global  STRCHR
%ifdef PC88VA
; Open Watcom medium-model callers use a FAR Pascal call even when the
; character pointer is a NEAR data pointer.  The shared pascal_setup and
; pascal_return path is a NEAR-call trampoline and cannot consume the FAR
; return frame.  Keep this PC-88VA entry explicit; other targets retain the
; historical implementation below.
STRCHR:
                push    bp
                mov     bp, sp
                push    bx
                push    cx
                push    dx
                push    si
                push    di
                push    es
                push    ds

                ; FAR Pascal frame: +6 character, +8 NEAR source offset.
                ; The source offset is relative to the caller's DS.
                mov     cx, [bp+6]
                mov     si, [bp+8]
                cld

pc88va_strchr_loop:
                lodsb
                cmp     al, cl
                je      pc88va_strchr_found
                test    al, al
                jne     pc88va_strchr_loop

                ; A NUL search matches the terminator above; reaching this
                ; path means the requested character was absent.
                xor     ax, ax
                xor     dx, dx
                jmp     short pc88va_strchr_done

pc88va_strchr_found:
                mov     ax, si
                dec     ax
                mov     dx, ds

pc88va_strchr_done:
                pop     ds
                pop     es
                pop     di
                pop     si
                pop     dx
                pop     cx
                pop     bx
                pop     bp
                ; ASMPASCAL owns the character and pointer words.
                retf    4
%else
STRCHR:
                call pascal_setup

                ; Get the source pointer, ss
arg src, ch
%ifdef STDCALL	; preset above for PASCAL
                mov             cx,[.ch]
                mov             si,[.src]
%endif
		mov bl,4

strchr_loop:                
                lodsb
                cmp  al,cl
                je   strchr_found
                test al,al
                jne  strchr_loop
                
strchr_retzero:
                xor ax, ax               ; return NULL if not found
                mov dx, ax               ; for fstrchr()
                jmp pascal_return
                
strchr_found:
                mov ax, si
                mov dx, ds               ; for fstrchr()
strchr_found1:
		dec ax

                jmp pascal_return
%endif

%ifndef _INIT

;*****
;  fstrchr (BYTE     far *src , int ch);
                global  FSTRCHR
%ifdef PC88VA
; Open Watcom medium-model calls are FAR even for this helper.  The shared
; strchr_loop tail uses pascal_return, whose near RET is correct for STRCHR
; and FMEMCHR but leaves a FAR caller's return CS on the stack.  Keep those
; historical entries unchanged and give the PC-88VA FAR entry its own frame
; and return path.
FSTRCHR:
                push    bp
                mov     bp, sp
                push    bx
                push    cx
                push    es
                push    si
                push    di
                push    ds

                ; FAR Pascal frame: +6 character, +8 source offset,
                ; +10 source segment.  Return DX:AX (segment:offset).
                mov     cx, [bp+6]
                mov     si, [bp+8]
                mov     ax, [bp+10]
                mov     ds, ax
                cld

pc88va_fstrchr_loop:
                lodsb
                cmp     al, cl
                je      pc88va_fstrchr_found
                test    al, al
                jne     pc88va_fstrchr_loop

                xor     ax, ax
                xor     dx, dx
                jmp     short pc88va_fstrchr_done

pc88va_fstrchr_found:
                mov     ax, si
                dec     ax
                mov     dx, ds

pc88va_fstrchr_done:
                pop     ds
                pop     di
                pop     si
                pop     es
                pop     cx
                pop     bx
                pop     bp
                retf    6
%else
FSTRCHR:
                call pascal_setup

arg {src,4}, ch
                ; Get ch (preset above)
                ;mov cx, [bp+4]
                
                ;and the source pointer, src
                lds si, [.src]

		;mov	bl, 6 - preset above

                jmp short strchr_loop
%endif

;******
                global  FMEMCHR
%ifdef PC88VA
; The medium-model FAR entry has the same outer frame as FSTRCHR, with a
; length word added: +6 length, +8 character, +10 source offset, +12 source
; segment.  The historical entry below reaches pascal_return (NEAR RET),
; which cannot consume a FAR return frame.  Keep it for other targets and
; give PC-88VA a frame-correct implementation.
FMEMCHR:
                push    bp
                mov     bp, sp
                push    bx
                push    cx
                push    es
                push    si
                push    di
                push    ds

                ; FAR Pascal frame: +6 length, +8 character,
                ; +10 source offset, +12 source segment.
                mov     cx, [bp+6]
                mov     bx, [bp+8]
                mov     di, [bp+10]
                mov     dx, [bp+12]
                mov     es, dx
                cld
                jcxz     pc88va_fmemchr_notfound
                mov      al, bl
                repne    scasb
                jne      pc88va_fmemchr_notfound
                mov      ax, di
                dec      ax
                mov      dx, es
                jmp      short pc88va_fmemchr_done

pc88va_fmemchr_notfound:
                xor      ax, ax
                xor      dx, dx

pc88va_fmemchr_done:
                pop      ds
                pop      di
                pop      si
                pop      es
                pop      cx
                pop      bx
                pop      bp
                retf     8
%else
FMEMCHR:
                call pascal_setup

arg {src,4}, ch, n
                ; Get the length - preset above
%ifdef STDCALL
                mov cx, [.n]
%endif

                ; and the search value
                mov ax, [.ch]

                ; and the source pointer, ss
                les di, [.src]

		mov bl, 8

		jcxz strchr_retzero
                repne scasb
                jne strchr_retzero
                mov dx, es
                mov ax, di
                jmp short strchr_found1
%endif

;**********************************************************************
                global  FSTRCMP
%ifdef PC88VA
; FAR code calls this entry in the medium model.  The C contract is
; fstrcmp(dest, src): compare unsigned bytes and return dest - src.
FSTRCMP:
                push    bp
                mov     bp, sp
                push    bx
                push    cx
                push    dx
                push    si
                push    di
                push    es
                push    ds

                ; FAR Pascal frame: source +6/+8, destination +10/+12.
                mov     si, [bp+6]
                mov     ax, [bp+8]
                mov     ds, ax
                mov     di, [bp+10]
                mov     ax, [bp+12]
                mov     es, ax
                cld

pc88va_fstrcmp_loop:
                xor     cx, cx
                mov     cl, [ds:si]
                xor     ax, ax
                mov     al, [es:di]
                test    cl, cl
                jz      pc88va_fstrcmp_result
                test    al, al
                jz      pc88va_fstrcmp_result
                cmp     al, cl
                jne     pc88va_fstrcmp_result
                inc     si
                inc     di
                jmp     short pc88va_fstrcmp_loop

pc88va_fstrcmp_result:
                sub     ax, cx
                pop     ds
                pop     es
                pop     di
                pop     si
                pop     dx
                pop     cx
                pop     bx
                pop     bp
                retf    8
%else
FSTRCMP:
                call pascal_setup

arg {dest,4}, {src,4}
                ; Get the source pointer, ss
                lds             si,[.src]

                ; and the destination pointer, d
                les             di,[.dest]
                
                mov bl,8

%if 0
                jmp short dostrcmp

;******
                global STRCMP
STRCMP:
                call pascal_setup

                mov bl,4

                ; Get the source pointer, ss
                ; mov             si,[bp+4]

                ; and the destination pointer, d
                ; mov             di,[bp+6]
                xchg si,di

dostrcmp:                       
%endif
                                    ; replace strncmp(s1,s2)-->
                                    ;         strncmp(s1,s2,0xffff)
                mov cx,0xffff
%if 0
                jmp short dostrncmp

                
;**********************************************************************
                global  FSTRNCMP
FSTRNCMP:
                call pascal_setup

                ; Get the source pointer, ss
                lds             si,[bp+4]

                ; and the destination pointer, d
                les             di,[bp+8]
                mov             cx,[bp+12]
                mov             bl,10
                
                jmp short dostrncmp

;******
                global  _strncmp
_strncmp:
                call pascal_setup

                ; Get the source pointer, ss
                ;mov             si,[bp+4]

                ; and the destination pointer, d
                ;mov             di,[bp+6]
                ;mov             cx,[bp+8]
                xchg si,di

dostrncmp:
%endif
                jcxz strncmp_retzero

strncmp_loop:                
                lodsb
                scasb
                jne  strncmp_done
                test al,al
                loopne   strncmp_loop
                jmp  short strncmp_retzero		
%endif
%endif

;**********************************************************************
; fmemcmp(BYTE FAR *s1 , BYTE FAR *s2, int count);
                global  FMEMCMP
%ifdef PC88VA
; Compare exactly count bytes from the two FAR objects.  The first argument
; is the destination/left operand, matching the C declaration (m1, m2, n).
FMEMCMP:
                push    bp
                mov     bp, sp
                push    bx
                push    cx
                push    dx
                push    si
                push    di
                push    es
                push    ds

                ; FAR Pascal frame: count +6, source +8/+10,
                ; destination +12/+14.
                mov     cx, [bp+6]
                mov     si, [bp+8]
                mov     ax, [bp+10]
                mov     ds, ax
                mov     di, [bp+12]
                mov     ax, [bp+14]
                mov     es, ax
                cld
                jcxz    pc88va_fmemcmp_equal

pc88va_fmemcmp_loop:
                xor     ax, ax
                mov     al, [ds:si]
                xor     dx, dx
                mov     dl, [es:di]
                cmp     al, dl
                jne     pc88va_fmemcmp_difference
                inc     si
                inc     di
                dec     cx
                jnz     pc88va_fmemcmp_loop

pc88va_fmemcmp_equal:
                xor     ax, ax
                jmp     short pc88va_fmemcmp_done

pc88va_fmemcmp_difference:
                xchg    ax, dx
                sub     ax, dx

pc88va_fmemcmp_done:
                pop     ds
                pop     es
                pop     di
                pop     si
                pop     dx
                pop     cx
                pop     bx
                pop     bp
                retf    10
%else
FMEMCMP:
                call pascal_setup

arg {dest,4}, {src,4}, n
                ; the length - preset above
%ifdef STDCALL
                mov cx, [.n]
%endif
                
                ; Get the source pointer, ss
                les di,[.src]

                ; and the destination pointer, d
                lds si,[.dest]

		mov bl,10

                jmp short domemcmp
%endif

;******
;  memcmp(BYTE     *s1 , BYTE     *s2, int count);        
                global  MEMCMP
%ifdef PC88VA
; Near data pointers are still one word each, but the medium-model code call
; is FAR.  Compare exactly count bytes and return m1 - m2.
MEMCMP:
                push    bp
                mov     bp, sp
                push    bx
                push    cx
                push    dx
                push    si
                push    di
                push    es
                push    ds

                ; FAR Pascal frame: count +6, m2/source +8,
                ; m1/destination +10.
                mov     cx, [bp+6]
                mov     si, [bp+8]
                mov     di, [bp+10]
                push    ds
                pop     es
                cld
                jcxz    pc88va_memcmp_equal

pc88va_memcmp_loop:
                xor     ax, ax
                mov     al, [ds:si]
                xor     dx, dx
                mov     dl, [es:di]
                cmp     al, dl
                jne     pc88va_memcmp_difference
                inc     si
                inc     di
                dec     cx
                jnz     pc88va_memcmp_loop

pc88va_memcmp_equal:
                xor     ax, ax
                jmp     short pc88va_memcmp_done

pc88va_memcmp_difference:
                xchg    ax, dx
                sub     ax, dx

pc88va_memcmp_done:
                pop     ds
                pop     es
                pop     di
                pop     si
                pop     dx
                pop     cx
                pop     bx
                pop     bp
                retf    6
%else
MEMCMP:
                call pascal_setup

                ; all preset: Get the source pointer, ss
                ;mov             si,[bp+6]

                ; and the destination pointer, d
                ;mov             di,[bp+8]
                ;mov             cx,[bp+4]
		;mov		 bl,6
                xchg si,di

domemcmp:
                jcxz strncmp_retzero
                repe cmpsb
                jne  strncmp_done
strncmp_retzero:
                xor  ax, ax
                jmp  short strncmp_done2
strncmp_done:
                lahf
		ror  ah,1
%ifdef _INIT
strncmp_done2:  jmp  short pascal_return
%else
strncmp_done2:  jmp  pascal_return
%endif
%endif

%endif
