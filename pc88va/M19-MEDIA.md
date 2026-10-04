# M19 removable-media uncertainty

The VA firmware adapter must distinguish an uncertain media status from a
confirmed change. `FL_DISKCHANGED` returns zero for unchanged and minus one
for uncertainty. The block driver revalidates uncertainty immediately; the
ordinary elapsed-time fallback must not suppress that check.

A successful read-only profile probe, matching nonzero DOS volume serial,
and byte-identical complete BPB preserve the current DOS volume binding.
A different serial or BPB reports changed. A failed probe returns its error.
A missing/zero serial leaves the result uncertain. The existing filesystem
policy still rejects uncertain/error results, invalidates old handles and
pending requests, and prevents dirty-cache writeback to an unbound volume.
Explicit reformat/change notifications are not converted to unchanged.

This uses DOS volume identity, not a guarantee of physical-medium identity:
clones sharing a serial and BPB cannot be distinguished by those fields.
Unidentified legacy media remains conservative; an open handle can become
stale after uncertainty and must be closed/reopened by pathname. Do not infer
uninterrupted legacy-media handle lifetime from a successful identified-volume
test. Non-VA driver behavior is unchanged.

Host regressions:

```
python3 pc88va/tests/test_m19_media_uncertainty.py
python3 pc88va/tests/test_m14_media_lifetime.py
```

These require Python, Unicorn, NASM and a host C compiler. They execute the
actual policy functions with synthetic media and the assembled firmware
adapter with a synthetic BIOS. They do not qualify firmware or hardware.
The parent must clean-build the complete media, verify linked placement and
carrier layout, and independently exercise unattended startup, F5/F8 controls,
file I/O and COM/MZ execution before handing over a replacement.
