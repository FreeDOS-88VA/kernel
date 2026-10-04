# M08 parameterized loader ABI

SPDX-License-Identifier: GPL-2.0-or-later

This draft specifies project-owned interfaces, not private firmware constants.
It must pass the complete M08 gate before being accepted for kernel handoff.

## Disk request version 1

`loader_abi.inc` is the canonical packed little-endian word layout. A near
DS:SI pointer must name all 48 bytes within its segment. The caller owns this
record until return and must keep it disjoint from all transfer destinations.
Words before `RD_COMPLETED` are input; subsequent words are output/workspace.
The whole request and its scratch state must remain live across callbacks.

The caller supplies zero-based LBA/count, a destination segment/offset and byte
capacity, media sector count, sectors per track, heads, sector bytes, opaque
boot-drive context, a qualified far adapter and retry ceiling. Geometry has
nonzero bounds; sector bytes is a power of two from 128 through 4096. Each
request has at most 65535 bytes and must remain inside one segment window.
The physical half-open destination interval cannot cross the real-mode
address-space end. The overlay/placement validator additionally proves that
all buffers and their declared capacities belong to the loader and do not
overlap firmware, live code, stacks, or the request record.

The core validates the entire request before making any callback, then splits
it into single-sector operations. Cylinder/head are zero-based and sector is
one-based; a firmware adapter maps these project units to its qualified ABI.
Track/head changes therefore occur only between operations. The opaque drive
context is unchanged. No firmware service selector or register binding is
embedded in the core, and no NEC98/IBM-PC fallback exists.

At each far callback DS:SI identifies the record, including current destination,
LBA, and physical record coordinates. Return AX=0 means success and CX reports
completed bytes; AX nonzero is an adapter error. SS:SP must be preserved across
the far call; other registers may be clobbered. The adapter may not write beyond
one sector at the current destination. Short or oversized completion is an
error, not a success or a reason to copy beyond the buffer. The caller must
discard partially loaded files after any failure.

The core preserves BX/CX/DX/SI/DI/BP/DS/ES and incoming FLAGS except CF; AX is the
public status and CF indicates failure. It does not change IF for firmware
calls. The private adapter establishes any qualified call-time requirements
and restores incoming FLAGS except its documented result. A callback error may
be retried zero through three times per sector, without a reset or alternative
service. M08 private profiles permit only the qualified default of zero retries
unless new evidence explicitly qualifies a bounded retry policy.

The same source is intended for stage 2 and the kernel OMF wrapper. The Watcom
wrapper will convert its near request argument in AX to DS:SI. Replacing the
M06 stub is not complete until that wrapper is linked and the stage-2 instance
is exercised by private VAEG acceptance. Unit fixtures are not firmware proof.

## Cached FAT12 request version 1

The `FT_*` layout in `loader_abi.inc` is a packed 26-byte request at DS:SI.
It contains the contiguous cached FAT's far address and byte extent, data
cluster count, first cluster, exact expected cluster count, visited-bitmap far
address and capacity, and current/next/validated output words. The expected
count must be computed from the validated directory file size and bytes per
cluster, not inferred from a fixed media extent. Zero or oversized counts fail.

The decoder reads the paired bytes for `cluster + floor(cluster/2)` only when
both bytes lie inside the cached FAT. This also handles pairs straddling a disk
sector boundary: the caller has read and verified the complete contiguous FAT
cache before invoking it. Odd entries shift right four bits; even entries mask
the low twelve bits. The cache remains immutable through loading.

The complete-chain validator initializes only `ceil(data_clusters/8)` bytes of
the declared visited bitmap. It rejects repeated clusters, free/reserved/bad
links, out-of-range links, early EOC and any nonterminal link after the exact
expected cluster count. All standard FAT12 EOC encodings are accepted. It never
copies file payload bytes. A subsequent bounded load pass may reuse directory
or bitmap scratch only after their metadata consumers have completed, and must
continue to use the same immutable FAT cache. Every physical region must first
pass the loader's overlap and ownership validation.

AX and CF report explicit errors; all other registers and incoming FLAGS are
preserved. The request's input words remain unchanged. `FT_VALIDATED` records
validated progress and does not claim successful file loading after an error.

## Root lookup request version 1

The packed 20-byte `RT_*` record describes a contiguous, already-read root
directory cache, its entry count and byte capacity, the validated data-cluster
count and file staging capacity. Lookup validates the complete cache span before
reading entries. The immutable input cache remains live until lookup returns;
it may then be reused only after the first-cluster and exact file-size outputs
have been copied into the loader state.

The required short name is exactly `KERNEL  SYS`. Deleted entries, volume labels,
directories and long-name records are skipped. A zero first byte terminates the
directory. Hidden, system, archive and read-only file attributes are supported;
reserved attribute bits on a matching regular file are rejected. A second
matching regular entry before the end marker is an error. There is no fallback
to a similarly named file or a preselected sector extent.

The matching entry must have a nonzero size within the staging capacity and a
valid FAT12 first cluster. The current bounded loader supports file sizes through
65535 bytes, so a nonzero high word in the directory's 32-bit size fails closed.
This is an explicit M08 carrier limit, not a claim to support arbitrary DOS
executables. Only AX/CF and the three output words may change; directory bytes,
input words, other registers and other FLAGS are preserved.

## Composed file-loading request version 1

The 42-byte `FL_*` record points to disjoint RD/FT/RT workspace records in the
caller's data segment. It supplies the file staging address/capacity, first data
sector, sectors per cluster, and single-sector scratch address/capacity. The
loader's initialization must first validate the complete memory ownership map,
the BPB layout and the successful acquisition of immutable root/FAT caches.
These are not substitute inputs for private firmware evidence.

The core verifies agreement of the cached metadata's cluster counts and the
disk extent, validates cluster size, looks up the root entry, derives the exact
required cluster count from its file size, and validates the entire FAT chain
before issuing any file-data read. It then walks that chain, mapping each
cluster to its data-sector range. One complete sector is read into scratch at
a time; only the remaining file bytes are copied to staging for the final read.
The copy is compared byte-for-byte against scratch before that scratch is reused.
No error advances the request to the file-loaded state.

The file core owns its workspace pointees and may update their request/output
fields between helper calls; its own input words remain unchanged. The stage
word reports 4 after root lookup, 5 after chain validation, and 6 only after all
declared file bytes have been copied and checked. A nonzero AX/CF error makes
any partially loaded payload unusable. All caller registers except AX, and all
FLAGS except CF, are restored. Internal string operations use DF=0. BP-relative
workspace accesses explicitly select DS, permitting a separate stack segment.

## Volume validation and metadata acquisition version 1

The 44-byte `VP_*` record supplies an immutable boot-sector far address and
capacity, a near RD request, and the FAT/root/bitmap capacities. Its outputs
describe checked sector and cluster sizes, first FAT and root sectors, FAT/root
extents, first data sector, data-cluster count, media descriptor and bitmap size.
They are usable only when `VP_VALIDATED` is one and the call succeeds.

`pc88va_volume_validate_core` accepts a superfloppy with two FAT copies, no
hidden sectors, and an unambiguous total-sector encoding matching the disk
contract. Sector size and CHS geometry must agree with that contract. Cluster
size must be a bounded power of two; all metadata arithmetic, rounded root
extent and cache capacities are checked. The packed FAT must cover both
reserved entries and every declared cluster. The cluster count must fit FAT12.
Boot-code signatures are not interpreted here: firmware acceptance remains a
separate private M07 input, not a guessed FAT-loader rule.

The 20-byte `VM_*` record refers to disjoint RD/VP/FT/RT/FL records plus a
separate mirror buffer. The caller first validates their complete ownership
map. `pc88va_volume_read_core` then reads logical sector zero through the actual
disk adapter, validates the BPB against the supplied disk geometry and cache
capacities, reads both full FAT extents, requires byte-identical copies and
valid reserved entries, and reads the complete rounded root extent. It never
repairs a FAT, selects a preferred divergent copy, or continues after a short
read. No filesystem write is performed.

The metadata core owns and initializes its pointee workspace records, replacing
capacity fields with exact validated extents on success. The VM input words
remain unchanged. `VM_STAGE` becomes one after BPB/capacity validation, two
after FAT agreement/reserved-entry validation, and three only after all root
reads and layout-field publication. A failed operation makes any partial cache
unusable. The volume cores preserve caller registers other than AX and FLAGS
other than CF. Initial sector storage may become file-sector scratch only after
metadata acquisition succeeds; the immutable FAT/root caches remain live through
complete file-chain traversal.

## MZ validation, transformation and handoff version 1

The 54-byte `MZ_*` record supplies the immutable file's far address and exact
byte count, paragraph-aligned destination segment and capacity, stack reserve,
opaque boot-drive context, and a near pointer/count for protected physical
intervals. Intervals are nonempty, little-endian 32-bit start/end pairs with
exclusive ends, bounded by the real-mode address space. The ownership contract
must enumerate all live loader code, data, workspace, stack and firmware regions;
the core separately rejects any overlap with its input file. Record and interval
storage must be disjoint from the immutable file and from the destination.
This is a trusted loader-internal interface, not a guest-supplied memory map.

`pc88va_mz_validate_core` performs no destination write. It requires an MZ magic,
zero overlay, zero optional checksum, zero relocations, a complete paragraph
header and a relocation-table offset between the fixed header and header end.
The encoded DOS page/last-page size must equal the actual FAT file size. The
initialized body must be nonempty. Its rounded paragraph size plus minimum
extra paragraphs must fit the supplied capacity and the supported 65,520-byte
allocation bound; maximum extra paragraphs may not be less than the minimum.
The loader allocates exactly the rounded body plus the minimum, not the maximum.
All arithmetic is checked before use, including physical ends and segment sums.

The entry must lie in the initialized body. SS:SP must lie in the allocation and
leave the declared reserve below SP without segment wrap. The entry byte may not
lie in that reserved stack interval. A stack located inside the initialized body
is permitted, matching the accepted carrier layout; unused body bytes are not
assumed to be executable code. Derived header/body/allocation/entry/stack outputs
are valid only when `MZ_VALIDATED` is one and AX/CF indicate success.

`pc88va_mz_transform_core` always revalidates, copies the exact body excluding
the header, zeros all rounded-body padding and minimum additional allocation,
compares the copied body against the original file, and checks the zero tail.
Only then does it set `MZ_TRANSFORMED`. An error makes any partial destination
unusable; errors return without a handoff. Both returning cores preserve all
caller registers except AX and all FLAGS except CF.

`pc88va_loader_handoff_core` requires at least four reserved stack bytes and
calls the transformation core. On success it does not return: it uses a far
return frame within the kernel's declared stack reserve to transfer to the
validated CS:IP with the declared SS:SP. The consumed frame remains as ordinary
stack bytes below SP; this is distinct from the pre-handoff body byte comparison.
DS and ES select the allocation segment, DX carries the opaque drive context,
and AX/BX/CX/SI/DI/BP are zero. FLAGS are initialized with IF and DF clear before
changing the stack; subsequent register setup does not change FLAGS. The POPF
input word is 2; reserved/fixed FLAGS bits retain the selected CPU model's
semantics. A runtime verifier must predict the complete word from that pinned
public CPU implementation, not assume an x86 QA engine's reserved-bit image
and not normalize differences out of repeated architectural observations. This
defines only a loader-to-carrier interface, not initialized DOS hardware services.

## Complete loader-core request version 1

The 10-byte `BL_*` record connects a metadata request and MZ handoff request.
Before any disk operation, `pc88va_boot_load_core` checks the record bindings
and requires the FL staging address to match the MZ input-file address. The
trusted stage setup must already have validated the complete memory ownership
map and captured the qualified boot-drive context in RD.

The core acquires real metadata, performs exact root lookup and FAT traversal,
loads and checks the file, and passes the file size obtained from the disk to
the MZ handoff. It copies the opaque RD drive context to the MZ request, not a
separately supplied kernel-drive value. The MZ validator/transformer and far
transfer are the same cores linked through the kernel's M08 service adapter.
No fixed kernel-sector extent or host-supplied file bytes enter this path.

`BL_STAGE` is three after metadata acquisition and six after successful file
loading; the referenced FL and MZ records expose their finer progress states.
Only an externally observed entry fetch proves a completed transfer. A returning
handoff is an error, even if it returns zero. On any returning failure BL_STATUS
records the error and the caller's registers/FLAGS are restored except AX/CF.
This core assumes a validated stage entry and does not replace the separate
firmware-to-stage-1 handoff checks or private execution evidence.

## ROM-free execution QA

The executable ROM-free tests run on Linux with NASM and the hash-pinned QA
wheel in `tests/m08-requirements.txt`. In an isolated Python environment:

```sh
python -m pip install --only-binary=:all: --require-hashes -r tests/m08-requirements.txt
python tests/test_m08_disk.py
python tests/test_m08_fat.py
python tests/test_m08_root.py
python tests/test_m08_file.py
python tests/test_m08_mz.py
python tests/test_m08_volume.py
python tests/test_m08_metadata.py
```

These tests execute the same assembled 8086 cores, with project-authored far
callbacks providing success, short transfers and errors. They do not use ROMs,
disk images, interrupts or private addresses. Two NASM outputs must match.
This supplemental host QA dependency does not replace the locked Open Watcom
1.9/NASM guest build or the separate two-run production VAEG gate.

## Integration requirements

FAT12 lookup must use the root directory and exact cluster chain, including
cycle and final-EOC validation. Its sector scratch, visited bitmap and file
staging have separate declared capacities. MZ handoff accepts only the validated
zero-relocation carrier, strips its header, copies its body, initializes the
required additional allocation and validates entry and stack before one-way
far transfer with interrupts disabled. Stage-2/file/kernel/stack lifetimes and
disjoint half-open intervals follow the parent M08 ADR and private overlay.

## M16 runtime kernel-layout extension

When the matched loader is assembled with `PC88VA_RUNTIME_LOADSEG`,
`PC88VA_LOADSEG=hhhh` in CONFIG.SYS selects the expanded kernel layout base,
not the temporary file buffer. The default is the carrier's compiled image base.
Stage 2 measures RAM before any disk read. It derives file/MZ staging at
measured RAM end minus 19000h, preserving the qualified 256 KiB profile's
relative transient offsets. The handoff carries measured KiB in AX, requested
base in BX (zero means default), and actual staging segment in CX; other
handoff registers retain the version-1 contract. Builds without this extension retain the historical interface.

The matched split carrier validates the measured-RAM handoff and transient
workspace, checks the full translated layout, and applies the
resident base delta to image, resident assembly and bootstrap stack. INIT
and its stack track measured RAM top independently; their descriptor fields
and all INIT segment relocations receive the corresponding temporary delta.
Final kernel work grows consecutively after the resident hull, followed by the
free DOS arena. P_0 releases temporary buffers, INIT and stack before the shell. It preserves the effective addresses in the `M16BOOT1` startup
record. It rejects an invalid layout before expanding into the requested target.
The previous M16 interpretation of LOADSEG as a file-buffer selector is superseded.
