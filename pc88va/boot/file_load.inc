; SPDX-License-Identifier: GPL-2.0-or-later
; Compose actual root lookup, FAT traversal and disk reads; no fixed file extent.
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

; DS:SI -> FL_SIZE bytes plus disjoint mutable RD/FT/RT workspace records.
; Immutable root/FAT caches and owned scratch/file/bitmap regions are required.
; AX/CF=result, all other registers/FLAGS preserved. FL_STAGE=4/5/6 on progress.
pc88va_file_load_core:
    pushf
    push bx
    push cx
    push dx
    push si
    push di
    push bp
    push ds
    push es
    cmp si, 65536-FL_SIZE
    ja .contract
    mov bp, si
    cmp word [ds:bp+FL_VERSION], 1
    jne .contract
    mov word [ds:bp+FL_STAGE], 0
    mov word [ds:bp+FL_LOADED], 0
    cld
    mov bx, [ds:bp+FL_DISK]
    cmp bx, 65536-RD_SIZE
    ja .contract
    cmp word [bx+RD_VERSION], 1
    je .disk_version_ok
    cmp word [bx+RD_VERSION], 2
    jne .contract
    cmp bx, 65536-RD_SIZE2
    ja .contract
.disk_version_ok:
    mov di, [ds:bp+FL_FAT]
    cmp di, 65536-FT_SIZE
    ja .contract
    cmp word [di+FT_VERSION], 1
    jne .contract
    mov si, [ds:bp+FL_ROOT]
    cmp si, 65536-RT_SIZE
    ja .contract
    cmp word [si+RT_VERSION], 1
    jne .contract
    mov ax, [di+FT_DATA_CLUSTERS]
    cmp ax, [si+RT_DATA_CLUSTERS]
    jne .contract
    mov ax, [ds:bp+FL_CAPACITY]
    or ax, ax
    jz .contract
    mov [si+RT_FILE_CAPACITY], ax
    mov ax, [ds:bp+FL_SECTORS_CLUSTER]
    or ax, ax
    jz .contract
    cmp ax, 128
    ja .contract
    mov cx, ax
    dec cx
    test ax, cx
    jnz .contract
    mov ax, [bx+RD_SECTOR_BYTES]
    cmp ax, 128
    jb .contract
    cmp ax, 4096
    ja .contract
    mov cx, ax
    dec cx
    test ax, cx
    jnz .contract
    cmp ax, [ds:bp+FL_SCRATCH_CAPACITY]
    ja .range
    mul word [ds:bp+FL_SECTORS_CLUSTER]
    or dx, dx
    jnz .range
    mov [ds:bp+FL_CLUSTER_BYTES], ax
    mov ax, [ds:bp+FL_DATA_START]
    or ax, ax
    jz .range
    cmp ax, [bx+RD_TOTAL_SECTORS]
    jae .range
    mov ax, [bx+RD_TOTAL_SECTORS]
    sub ax, [ds:bp+FL_DATA_START]
    xor dx, dx
    div word [ds:bp+FL_SECTORS_CLUSTER]
    ; The validated volume may use fewer whole cylinders than the disk
    ; profile (77 of 80); it must never extend beyond the disk.
    cmp ax, [di+FT_DATA_CLUSTERS]
    jb .range
    call pc88va_root_lookup_core
    jc .restore
    mov word [ds:bp+FL_STAGE], 4
    mov ax, [si+RT_FILE_SIZE]
    mov [ds:bp+FL_FILE_BYTES], ax
    mov [ds:bp+FL_REMAINING], ax
    add ax, [ds:bp+FL_OFFSET]
    jc .range
    mov cx, ax
    mov ax, [ds:bp+FL_SEGMENT]
    mov dx, ax
    push cx
    mov cl, 12
    shr dx, cl
    mov cl, 4
    shl ax, cl
    pop cx
    add ax, cx
    adc dx, 0
    cmp dx, 16
    ja .range
    jb .file_valid
    or ax, ax
    jnz .range
.file_valid:
    mov ax, [si+RT_FIRST_CLUSTER]
    mov [ds:bp+FL_CLUSTER], ax
    mov [di+FT_FIRST_CLUSTER], ax
    mov ax, [ds:bp+FL_FILE_BYTES]
    xor dx, dx
    div word [ds:bp+FL_CLUSTER_BYTES]
    or dx, dx
    jz .count_ready
    inc ax
.count_ready:
    mov [di+FT_EXPECTED_COUNT], ax
    mov si, di
    call pc88va_fat_chain_core
    jc .restore
    mov word [ds:bp+FL_STAGE], 5
    mov ax, [ds:bp+FL_OFFSET]
    mov [ds:bp+FL_FILE_POSITION], ax
.cluster:
    mov word [ds:bp+FL_SECTOR_INDEX], 0
.sector:
    mov si, [ds:bp+FL_DISK]
    mov ax, [ds:bp+FL_CLUSTER]
    sub ax, 2
    mul word [ds:bp+FL_SECTORS_CLUSTER]
    or dx, dx
    jnz .range
    add ax, [ds:bp+FL_DATA_START]
    jc .range
    add ax, [ds:bp+FL_SECTOR_INDEX]
    jc .range
    mov [si+RD_LBA], ax
    ; Whole sectors still to load go straight to the destination, in one
    ; request through consecutive clusters.  A final partial sector uses
    ; the scratch buffer and the byte check below.
    mov ax, [ds:bp+FL_REMAINING]
    xor dx, dx
    div word [si+RD_SECTOR_BYTES]
    or ax, ax
    jnz .run_start
    jmp .scratch_sector
.run_start:
    mov [ds:bp+FL_WHOLE], ax
    mov cx, [ds:bp+FL_SECTORS_CLUSTER]
    sub cx, [ds:bp+FL_SECTOR_INDEX]
    mov word [ds:bp+FL_RUN_STATE], 0
    cmp cx, ax
    jbe .run_cluster
    ; Fewer whole sectors than remain in this cluster: stay inside it.
    mov [ds:bp+FL_RUN], ax
    mov word [ds:bp+FL_RUN_STATE], 2
    jmp .run_read
.run_cluster:
    mov [ds:bp+FL_RUN], cx
.run_extend:
    mov ax, [ds:bp+FL_RUN]
    add ax, [ds:bp+FL_SECTORS_CLUSTER]
    cmp ax, [ds:bp+FL_WHOLE]
    ja .run_read
    ; Another whole cluster follows, so the chain has a next cluster.
    push si
    mov si, [ds:bp+FL_FAT]
    mov ax, [ds:bp+FL_CLUSTER]
    mov [si+FT_CURRENT], ax
    call pc88va_fat_next_core
    jc .run_fat_error
    mov ax, [si+FT_NEXT]
    pop si
    mov dx, [ds:bp+FL_CLUSTER]
    inc dx
    cmp ax, dx
    jne .run_pending
    mov [ds:bp+FL_CLUSTER], ax
    mov ax, [ds:bp+FL_SECTORS_CLUSTER]
    add [ds:bp+FL_RUN], ax
    jmp .run_extend
.run_fat_error:
    pop si
    jmp .restore
.run_pending:
    ; Not consecutive: this run ends here and the next one starts there.
    mov [ds:bp+FL_PENDING], ax
    mov word [ds:bp+FL_RUN_STATE], 1
.run_read:
    mov ax, [ds:bp+FL_RUN]
    mov [si+RD_COUNT], ax
    mov ax, [ds:bp+FL_FILE_POSITION]
    mov [si+RD_OFFSET], ax
    mov ax, [ds:bp+FL_SEGMENT]
    mov [si+RD_SEGMENT], ax
    mov ax, [ds:bp+FL_CAPACITY]
    sub ax, [ds:bp+FL_LOADED]
    jae .run_capacity
    jmp .range
.run_capacity:
    mov [si+RD_CAPACITY], ax
    call pc88va_disk_read_core
    jnc .run_done
    jmp .restore
.run_done:
    mov ax, [ds:bp+FL_RUN]
    mul word [si+RD_SECTOR_BYTES]
    add [ds:bp+FL_LOADED], ax
    add [ds:bp+FL_FILE_POSITION], ax
    sub [ds:bp+FL_REMAINING], ax
    jnz .run_more
    jmp .loaded
.run_more:
    cmp word [ds:bp+FL_RUN_STATE], 2
    jne .run_next_cluster
    mov ax, [ds:bp+FL_RUN]
    add [ds:bp+FL_SECTOR_INDEX], ax
    jmp .sector
.run_next_cluster:
    cmp word [ds:bp+FL_RUN_STATE], 1
    jne .next_cluster
    mov ax, [ds:bp+FL_PENDING]
    mov [ds:bp+FL_CLUSTER], ax
    jmp .cluster
.scratch_sector:
    mov word [si+RD_COUNT], 1
    mov ax, [ds:bp+FL_SCRATCH_OFFSET]
    mov [si+RD_OFFSET], ax
    mov ax, [ds:bp+FL_SCRATCH_SEGMENT]
    mov [si+RD_SEGMENT], ax
    mov ax, [ds:bp+FL_SCRATCH_CAPACITY]
    mov [si+RD_CAPACITY], ax
    call pc88va_disk_read_core
    jc .restore
    mov dx, [si+RD_SECTOR_BYTES]
    cmp dx, [ds:bp+FL_REMAINING]
    jbe .copy_size
    mov dx, [ds:bp+FL_REMAINING]
.copy_size:
    mov [ds:bp+FL_COPY_BYTES], dx
    mov cx, dx
    mov di, [ds:bp+FL_FILE_POSITION]
    mov es, [ds:bp+FL_SEGMENT]
    mov ax, [ds:bp+FL_SCRATCH_SEGMENT]
    push ds
    push si
    mov si, [ds:bp+FL_SCRATCH_OFFSET]
    mov ds, ax
    rep movsb
    ; Compare the actual copy against the successful sector buffer before reuse.
    sub si, dx
    sub di, dx
    mov cx, dx
    repe cmpsb
    pop si
    pop ds
    jne .bytecheck
    add [ds:bp+FL_LOADED], dx
    add [ds:bp+FL_FILE_POSITION], dx
    sub [ds:bp+FL_REMAINING], dx
    jz .loaded
    inc word [ds:bp+FL_SECTOR_INDEX]
    mov ax, [ds:bp+FL_SECTOR_INDEX]
    cmp ax, [ds:bp+FL_SECTORS_CLUSTER]
    jb .sector
.next_cluster:
    mov si, [ds:bp+FL_FAT]
    mov ax, [ds:bp+FL_CLUSTER]
    mov [si+FT_CURRENT], ax
    call pc88va_fat_next_core
    jc .restore
    mov ax, [si+FT_NEXT]
    mov [ds:bp+FL_CLUSTER], ax
    jmp .cluster
.loaded:
    mov word [ds:bp+FL_STAGE], 6
    xor ax, ax
    jmp .restore
.contract:
    mov ax, FILE_CONTRACT
    jmp .restore
.range:
    mov ax, FILE_RANGE
    jmp .restore
.bytecheck:
    mov ax, FILE_BYTECHECK
.restore:
    pop es
    pop ds
    pop bp
    pop di
    pop si
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
