; SPDX-License-Identifier: GPL-2.0-or-later
; Resident DOS adapter transfers one sector per firmware request. Supported
; media use at most 1024 bytes per sector; this is not the loader history ring.
%ifndef PC88VA_DISK_BUFFER_BYTES
%define PC88VA_DISK_BUFFER_BYTES 1024
%endif
