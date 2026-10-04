; SPDX-License-Identifier: GPL-2.0-or-later
; Every participating object must declare this group so its offset fixups,
; not just the linker's placement, use the same CS-relative frame.
%ifndef PC88VA_M13_SEGMENTS_DECLARED
%define PC88VA_M13_SEGMENTS_DECLARED 1
segment _PC88VA_CODE class=CODE align=16 public use16
segment M13_PLATFORM_TEXT class=CODE public use16
group PC88VA_PLATFORM _PC88VA_CODE M13_PLATFORM_TEXT
%endif
