; File:
;                         intr.asm
; Description:
;       Assembly implementation of calling an interrupt
;
;                    Copyright (c) 2000
;                       Steffen Kaiser
;                       All Rights Reserved
;
; This file is part of FreeDOS.
;
; FreeDOS is free software; you can redistribute it and/or
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
; write to the Free Software Foundation, Inc.,
; 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA.
;

		%include "segs.inc"
		%include "stacks.inc"

%macro INTR 0
        
                push    bp                      ; Standard C entry
                mov     bp,sp
                push    si
                push    di
%ifdef WATCOM
                push    bx
                push    cx
                push    dx
                push    es
%endif
                push	ds


%ifdef PC88VA
                ; Open Watcom medium-model callers enter this helper with a
                ; FAR return frame.  The Pascal pushes in the caller are
                ; (nr, rp), so the final pushed pointer is at BP+6 and the
                ; interrupt number is at BP+8 after the BP prologue.
                mov     ax, [ss:bp+8]      ; interrupt number
                mov     [cs:%%intr_1-1], al
                jmp     short %%intr_2     ; flush the instruction cache
%%intr_2        mov     bx, [ss:bp+6]      ; REGPACK pointer
%else
arg nr, rp
                mov	ax, [.nr]		; interrupt number
                mov	[cs:%%intr_1-1], al
                jmp 	short %%intr_2		; flush the instruction cache
%%intr_2	mov	bx, [.rp]		; regpack structure
%endif
		mov	ax, [bx]
		mov	cx, [bx+4]
		mov	dx, [bx+6]
		mov	si, [bx+8]
		mov	di, [bx+10]
		mov	bp, [bx+12]
		push	word [bx+14]		; ds
		mov	es, [bx+16]
		mov	bx, [bx+2]
		pop	ds
		int	0
%%intr_1:

		pushf
		push	ds
		push	bx
		mov	bx, sp
		mov	ds, [ss:bx+6]
%ifdef WATCOM
%ifdef PC88VA
		mov	bx, [ss:bx+26]		; address of REGPACK (FAR caller frame)
%else
		mov	bx, [ss:bx+24]		; address of REGPACK
%endif
%else
		%ifdef PC88VA
		mov	bx, [ss:bx+18]		; address of REGPACK (FAR caller frame)
		%else
		mov	bx, [ss:bx+12+.rp-bp]	; address of REGPACK
		%endif
%endif
		mov	[bx], ax
		pop	word [bx+2]
		mov	[bx+4], cx
		mov	[bx+6], dx
		mov	[bx+8], si
		mov	[bx+10], di
		mov	[bx+12], bp
		pop	word [bx+14]
		mov	[bx+16], es
		pop	word [bx+22]

		pop	ds
%ifdef WATCOM
                pop     es
                pop     dx
                pop     cx
                pop     bx
%endif
		pop	di
		pop	si
		pop	bp
%ifdef PC88VA
		retf    4
%else
		ret     4
%endif
%endmacro

segment	HMA_TEXT

%ifdef M13_VISIBLE_DIAGNOSTICS
        extern _pc88va_m13_exec_raw_ax
        extern _pc88va_m13_exec_raw_flags
        extern _pc88va_m13_input_raw_ax
        extern _pc88va_m13_input_raw_flags
%endif

;; COUNT ASMPASCAL res_DosExec(COUNT mode, exec_blk FAR * ep, BYTE * lp)
    global RES_DOSEXEC
RES_DOSEXEC:
%ifdef PC88VA
        ; Open Watcom medium-model callers use a FAR Pascal call.  Keep the
        ; FAR return frame intact while loading the near pathname, FAR
        ; parameter block, and mode.  After the frame prologue the caller's
        ; pushes are: BP+6 lp, BP+8 ep offset, BP+10 ep segment, BP+12 mode.
        push bp
        mov bp,sp
        mov ax,[ss:bp+12]       ; mode (AL)
        mov bx,[ss:bp+8]        ; EXEC parameter block offset
        mov es,[ss:bp+10]       ; EXEC parameter block segment
        mov dx,[ss:bp+6]        ; pathname offset
        mov ah,4bh
        int 21h
%ifdef M13_VISIBLE_DIAGNOSTICS
        pushf
        pop dx
        mov [_pc88va_m13_exec_raw_ax],ax
        mov [_pc88va_m13_exec_raw_flags],dx
%endif
        jc short pc88va_exec_error
        xor ax,ax
pc88va_exec_error:
        pop bp
        retf 8
%else
        pop es                  ; ret address
        popargs ax,bx,dx        ; mode, exec block, filename
        push es                 ; ret address
        mov ah, 4bh
        push ds                 
        pop es                  ; es = ds
        int 21h
%ifdef M13_VISIBLE_DIAGNOSTICS
        pushf
        pop dx
        mov [_pc88va_m13_exec_raw_ax], ax
        mov [_pc88va_m13_exec_raw_flags], dx
%endif
        jc short no_exec_error
        xor ax, ax
no_exec_error:
        ret
%endif

;; UCOUNT ASMPASCAL res_read(int fd, void *buf, UCOUNT count); 
    global RES_READ
RES_READ:
%ifdef PC88VA
        ; The medium-model caller pushes fd, buf, count and performs a FAR
        ; Pascal call.  BP+6 is count, BP+8 is the near buffer offset, and
        ; BP+10 is fd; the data pointer is interpreted in caller DS.
        push bp
        mov bp,sp
        mov cx,[ss:bp+6]        ; count
        mov dx,[ss:bp+8]        ; buffer offset
        mov bx,[ss:bp+10]       ; file handle
        mov ah,3fh
        int 21h
%ifdef M13_VISIBLE_DIAGNOSTICS
        pushf
        pop dx
        mov [_pc88va_m13_input_raw_ax],ax
        mov [_pc88va_m13_input_raw_flags],dx
%endif
        jnc short pc88va_read_ok
        mov ax,-1
pc88va_read_ok:
        pop bp
        retf 6
%else
        pop ax         ; ret address
        popargs bx,dx,cx ; fd, buf, count
        push ax        ; ret address
        mov ah, 3fh
        int 21h
%ifdef M13_VISIBLE_DIAGNOSTICS
        pushf
        pop dx
        mov [_pc88va_m13_input_raw_ax], ax
        mov [_pc88va_m13_input_raw_flags], dx
%endif
        jnc no_read_error
        mov ax, -1
no_read_error:
        ret
%endif

segment	INIT_TEXT
;
;       void init_call_intr(nr, rp)
;       REG int nr
;       REG struct REGPACK *rp
;
		global	INIT_CALL_INTR
INIT_CALL_INTR:
		INTR

;
; int init_call_XMScall( (WORD FAR * driverAddress)(), WORD AX, WORD DX)
;
; this calls HIMEM.SYS 
;
                global INIT_CALL_XMSCALL
INIT_CALL_XMSCALL:
            pop  bx         ; ret address
            popargs {es,cx},ax,dx

            push cs         ; ret address
            push bx
            push es         ; driver address ("jmp es:cx")
            push cx
            retf
            
; void FAR *DetectXMSDriver(VOID)
global DETECTXMSDRIVER
DETECTXMSDRIVER:
        mov ax, 4300h
        int 2fh                 ; XMS installation check

        cmp al, 80h
        je detected
        xor ax, ax
        xor dx, dx
        ret

detected:
        push es
        push bx
        mov ax, 4310h           ; XMS get driver address
        int 2fh
        
        mov ax, bx
        mov dx, es
        pop bx
        pop es
        ret        

global KEYCHECK
KEYCHECK:
        mov ah, 1
        int 16h
        ret                

;; int open(const char *pathname, int flags); 
    global INIT_DOSOPEN
INIT_DOSOPEN:
%ifdef PC88VA
        ; Medium-model callers use a FAR Pascal call.  The near model
        ; entry below would read the return CS as the pathname offset and
        ; return with RET, leaving the FAR frame unbalanced.
        push    bp
        mov     bp,sp
        mov     dx,[ss:bp+8]       ; near pathname offset
        mov     ax,[ss:bp+6]       ; flags
        mov     ah,3dh
        int     21h
        jnc     init_dosopen_ok
        mov     ax,-1
init_dosopen_ok:
        pop     bp
        retf    4
%else
        ;; init calling DOS through ints:
        pop bx         ; ret address
        popargs dx,ax  ; pathname, flags
        push bx        ; ret address
        mov ah, 3dh
        ;; falls through to common_int21 as in the baseline
%endif

        ;; AX will have the file handle.  This near-return helper remains
        ;; shared by the non-PC88VA wrappers below.
common_int21:
        int 21h
        jnc common_no_error
        mov ax, -1
common_no_error:
        ret

;; int close(int fd);
    global CLOSE
%ifdef PC88VA
CLOSE:
        ; Open Watcom medium-model callers use a FAR Pascal call.  The
        ; one-word handle is at BP+6 after the FAR return frame and the
        ; callee removes that argument with RETF 2.
        push    bp
        mov     bp,sp
        push    cx
        push    dx
        push    si
        push    di
        push    es
        push    ds
        mov     bx,[ss:bp+6]       ; fd
        mov     ah,3eh
        int     21h
        jnc     close_pc88va_ok
        mov     ax,-1
close_pc88va_ok:
        pop     ds
        pop     es
        pop     di
        pop     si
        pop     dx
        pop     cx
        pop     bp
        retf    2
%else
CLOSE:         
        pop ax         ; ret address
        pop bx         ; fd
        push ax        ; ret address
        mov ah, 3eh
        jmp short common_int21
%endif

;; UCOUNT read(int fd, void *buf, UCOUNT count); 
    global READ
READ: 
%ifdef PC88VA
        ; FAR Pascal: count, buffer offset:segment, fd.
        push bp
        mov bp,sp
        push ds
        push si
        push di
        push es
        mov cx,[ss:bp+6]
        lds dx,[ss:bp+8]
        mov bx,[ss:bp+12]
        mov ah,3fh
        int 21h
        jnc .read_ok
        mov ax,-1
.read_ok:
        pop es
        pop di
        pop si
        pop ds
        pop bp
        retf 8
%else
        pop ax         ; ret address
        popargs bx,dx,cx ; fd,buf,count
        push ax        ; ret address
        mov ah, 3fh
        jmp short common_int21

%endif
;; int dup2(int oldfd, int newfd); 
    global DUP2
DUP2:
%ifdef PC88VA
        ; Open Watcom medium-model callers use a FAR Pascal call.  The
        ; caller pushes oldfd then newfd, so the FAR frame is:
        ;   BP+2 return IP, BP+4 return CS, BP+6 newfd, BP+8 oldfd.
        ; Keep the historical near entry below for other targets and do not
        ; send this path through common_int21's near RET.
        push    bp
        mov     bp,sp
        push    dx
        push    si
        push    di
        push    es
        push    ds
        mov     bx,[ss:bp+8]       ; oldfd
        mov     cx,[ss:bp+6]       ; newfd
        mov     ah,46h
        int     21h
        jnc     dup2_pc88va_ok
        mov     ax,-1
dup2_pc88va_ok:
        pop     ds
        pop     es
        pop     di
        pop     si
        pop     dx
        pop     bp
        retf    4
%else
        pop ax         ; ret address
        popargs bx,cx  ; oldfd,newfd
        push ax        ; ret address
        mov ah, 46h
        jmp short common_int21
%endif
        
;
; ULONG ASMPASCAL lseek(int fd, long position);
;
    global LSEEK
LSEEK:
%ifdef PC88VA
        push bp
        mov bp,sp
        push bx
        push cx
        mov dx,[ss:bp+6]
        mov cx,[ss:bp+8]
        mov bx,[ss:bp+10]
        mov ax,4200h
        int 21h
        jnc .seek_ok
        mov ax,-1
        mov dx,ax
.seek_ok:
        pop cx
        pop bx
        pop bp
        retf 6
%else
        pop ax         ; ret address
        popargs bx,{cx,dx} ; fd, position high:low
        push ax        ; ret address
        mov ax,4200h   ; origin: start of file
        int 21h
        jnc     seek_ret        ; CF=1?
        sbb     ax,ax           ;  then dx:ax = -1, else unchanged
        sbb     dx,dx
seek_ret:
        ret
        
%endif
;; VOID init_PSPSet(seg psp_seg)
    global INIT_PSPSET
INIT_PSPSET:
%ifdef PC88VA
        pop ax         ; far return IP
        pop dx         ; far return CS
        pop bx         ; psp_seg
        push dx
        push ax
        extern _cu_psp
        mov [_cu_psp], bx
        xor ax, ax
        retf
%else
        pop ax         ; ret address
        pop bx         ; psp_seg
        push ax        ; ret_address
	mov ah, 50h
        int 21h
        ret
%endif

;; COUNT init_DosExec(COUNT mode, exec_blk * ep, BYTE * lp)
    global INIT_DOSEXEC
INIT_DOSEXEC:
%ifdef PC88VA
        ; FAR Pascal: near filename, FAR execution block, mode.
        push bp
        mov bp,sp
        push ds
        push si
        push di
        push cx
        mov dx,[ss:bp+6]
        les bx,[ss:bp+8]
        mov ax,[ss:bp+12]
        mov ah,4bh
        int 21h
        jc .exec_error
        xor ax,ax
.exec_error:
        pop cx
        pop di
        pop si
        pop ds
        pop bp
        retf 8
%else
        pop es                  ; ret address
        popargs ax,bx,dx        ; mode, exec block, filename
        push es                 ; ret address
        mov ah, 4bh
        push ds                 
        pop es                  ; es = ds
        int 21h
        jc short exec_no_error
        xor ax, ax
exec_no_error:
        ret

%endif
;; int init_setdrive(int drive)
   global INIT_SETDRIVE
INIT_SETDRIVE:
%ifdef PC88VA
        ; Open Watcom medium-model callers use a FAR Pascal call here.
        ; Keep the INIT_TEXT entry in its linked/retained segment; only
        ; adapt the call frame and let the INT 21h path preserve the
        ; caller's return segment.
        push    bp
        mov     bp,sp
        mov     dx,[ss:bp+6]       ; one 16-bit drive argument
        mov     ah,0x0e
        int     21h
        pop     bp
        retf    2
%else
	mov ah, 0x0e
common_dl_int21:
        pop bx                  ; ret address
        pop dx                  ; drive/char
        push bx
        int 21h
        ret
%endif

;; int init_switchar(int char)
   global INIT_SWITCHAR
INIT_SWITCHAR:
%ifdef PC88VA
        push    bp
        mov     bp,sp
        mov     dx,[ss:bp+6]       ; one 16-bit character argument
        mov     ax,0x3701
        int     21h
        pop     bp
        retf    2
%else
	mov ax, 0x3701
	jmp short common_dl_int21
%endif

;
; seg ASMPASCAL allocmem(UWORD size);
;
    global ALLOCMEM
ALLOCMEM:
%ifdef PC88VA
        ; Open Watcom medium-model callers use a FAR Pascal call here.
        ; The historical entry decoded a near-call frame and returned with
        ; RET, which leaves the caller's return CS on the stack.  Keep the
        ; non-PC88VA ABI unchanged and adapt only this boundary.
        push    bp
        mov     bp,sp
        mov     bx,[ss:bp+6]       ; one 16-bit paragraph-size argument
        mov     ah,48h
        int     21h
        sbb     bx,bx              ; carry=1 -> ax=-1
        or      ax,bx              ; segment
        pop     bp
        retf    2
%else
        pop ax           ; ret address
        pop bx           ; size
        push ax          ; ret address
        mov ah, 48h
        int 21h
        sbb bx, bx       ; carry=1 -> ax=-1
        or  ax, bx       ; segment
        ret
%endif
                        
;; void set_DTA(void far *dta)        
    global SET_DTA
SET_DTA:
%ifdef PC88VA
        ; Open Watcom medium-model callers use a FAR Pascal call here.
        ; With BP established, the far-pointer argument is offset at BP+6
        ; and segment at BP+8 (BP+2/IP, BP+4/CS are the return frame).
        ; Keep this boundary explicit instead of interpreting return CS as
        ; the DTA offset through the historical near-call pop sequence.
        push bp
        mov bp, sp
        push ds
        mov dx, [bp+6]    ; DTA offset
        mov bx, [bp+8]    ; DTA segment
        mov ah, 1ah
        mov ds, bx
global pc88va_setdta_int21_probe
pc88va_setdta_int21_probe:
        int 21h
global pc88va_setdta_int21_return_probe
pc88va_setdta_int21_return_probe:
        pop ds
global pc88va_setdta_restore_ds_probe
pc88va_setdta_restore_ds_probe:
        pop bp
global pc88va_setdta_restore_bp_probe
pc88va_setdta_restore_bp_probe:
        retf 4
%else
        pop ax           ; ret address
        popargs {bx,dx}  ; seg:off(dta)
        push ax          ; ret address
        mov ah, 1ah
        push ds
        mov ds, bx
        int 21h
        pop ds
        ret
%endif
