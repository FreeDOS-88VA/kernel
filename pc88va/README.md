# PC-88VA kernel entry carrier

This directory is the independent PC-88VA machine boundary.  M06 deliberately
builds only a linked kernel scaffold: it establishes the target selector,
binary interface, deterministic link order, and fail-closed service boundary.
M08 adds parameterized disk-read and zero-relocation MZ handoff cores. The
historical `makefile.wc` target remains the M06-M12 compile-only carrier and
is intentionally unchanged. M13 adds `makefile.m13.wc`, which links the
FreeDOS common kernel core with the PC-88VA resident M12 block adapter and the
M09/M11 console adapters. The M13 target is read-only and ASCII-only.

The build must run in the accepted Linux/amd64 Open Watcom 1.9 environment:

```sh
cd pc88va
wmake -ms -h -f makefile.wc clean all
python3 tools/collect_build.py --repo-root .. --output build/evidence \
  --component-commit "$COMPONENT_COMMIT" --source-archive-sha256 "$SOURCE_ARCHIVE_SHA256"
```

The caller must supply the actual exported component commit and source-archive
identity; do not label an uncommitted diagnostic build as a committed export.
Use the accepted fixed container-internal source path for both clean builds;
Watcom debug objects retain that path. No host source mount is permitted.

`bin/KERNEL.SYS` is a DOS MZ entry carrier, not the flat FreeDOS kernel format
used by existing boot loaders. M08 uses the zero-relocation policy documented
in [boot/loader-abi.md](boot/loader-abi.md): header validation and removal,
body copy/byte comparison, allocation initialization, and one-way entry.
The entry point remains unchanged and always reaches a local fatal
stop after probing the fail-closed interface object.  It performs no firmware
interrupt or I/O-port access.

The historical target defines `PC88VA`, `JAPAN`, and `DBCS`. The M13 target
defines only `PC88VA` (plus common-core large-sector switches); it rejects
`NEC98` and `IBMPC`, and no source below `nec98/` or `ibmpc/` is a link input.

For the M13 common-core build use the pinned Linux/amd64 Open Watcom
environment and the explicit target:

```sh
cd pc88va
wmake -ms -h -f makefile.m13.wc clean all
```

This target links `kernel/main.c`, `inthndlr.c`, FAT12, memory/process, EXEC,
and console objects from the common tree. `kernel/m13_platform.asm` is a
read-only adapter: every block mutation operation returns the documented DOS
write-protect error before reaching the M12 firmware callback. The adapter
chunks DOS reads into validated resident requests and never exposes its
kernel-owned 4 KiB scratch region to an application.

The two M08 C-call adapters are in `kernel/loader_services.asm`; they link the
same assembly cores used by the loader. Their packed near-pointer contracts
are documented in `boot/loader-abi.md`, with C declarations in
`kernel/loader_services.h`. They contain no firmware vector, private address
or fallback implementation. A validated caller supplies the firmware adapter
and ownership configuration.

The eight remaining temporary interfaces are listed in `config/stubs.json`. Their return
value is the signed error `-1`, except the probe which returns `0xffff`; none
reports hardware success.

ROM-free execution QA is documented in `boot/loader-abi.md`. After a linked
build, `python3 tests/check_m08_linked.py --build-dir build` exercises the
actual MZ body and both Watcom-call adapters with synthetic memory and disk
callbacks. This does not substitute for the private VAEG acceptance gate.

The flat stages have one explicit parameter source:

```sh
python3 tools/build_loader.py --overlay "$LOADER_OVERLAY" --output "$LOADER_OUTPUT" --stage 2
python3 tools/build_loader.py --overlay "$LOADER_OVERLAY" --output "$LOADER_OUTPUT" --stage 1 \
  --extent "$STAGE2_EXTENT"
```

Run these commands in the same accepted offline build container. The parent
media builder derives `STAGE2_EXTENT` from the allocated `LOADER.BIN` file;
it is never the kernel extent. Each stage refuses to overwrite old products.
The bootstrap preserves the public M05 BPB interval and the two separately
declared experimental signature slots. No firmware signature is selected by
this source tree.

The closed overlay has `schema_version`, `layout`, `bootstrap`, and
`firmware_callback` fields. `layout` uses the validated half-open ownership,
stack, geometry and cache contract. `bootstrap` supplies the qualified incoming
image segment/offset/extent, opaque drive context and firmware-call FLAGS.
`firmware_callback` defines only the bounded `PC88VA_FIRMWARE_READ_ONE` macro:
no file inclusion, binary embedding or ambient preprocessor metadata is
allowed. This is the explicit binding boundary for the independently qualified
firmware ABI; a ROM-free fixture instead returns a closed error. No firmware
binding, vector, address or private observation is inferred by the builder.

Private overlays must be regular, non-symlink, owner-only files. Their outputs
must use owner-only, non-temporary, Git-excluded storage (or an offline exported
build tree with no Git metadata, copied into persistent evidence before use).
Neither overlay definitions nor output identities from a private profile may
be copied into public goldens or CI. Public CI uses only a project-authored
synthetic profile and does not start an emulator.
