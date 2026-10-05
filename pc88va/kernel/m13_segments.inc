; SPDX-License-Identifier: GPL-2.0-or-later
; Every participating object must declare this group so its offset fixups,
; not just the linker's placement, use the same CS-relative frame.
%ifndef PC88VA_M13_SEGMENTS_DECLARED
%define PC88VA_M13_SEGMENTS_DECLARED 1
segment _PC88VA_CODE class=CODE align=16 public use16
segment M13_PLATFORM_TEXT class=CODE public use16
; Machine initialization runs once, in place, from the expanded image before
; INIT. Its own class places it after the INIT source (kernel/segs.inc); the
; shared group keeps its near calls and CS-relative state in the platform frame.
segment M10_BOOT_TEXT class=M10BOOT public use16
group PC88VA_PLATFORM _PC88VA_CODE M13_PLATFORM_TEXT M10_BOOT_TEXT
%endif
