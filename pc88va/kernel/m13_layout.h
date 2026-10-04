/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef PC88VA_M13_LAYOUT_H
#define PC88VA_M13_LAYOUT_H
/* Filled from the matched link map by the carrier builder. Segment fields
   are final physical segment values, not MZ-relative segment fixups. */
struct pc88va_layout {
  UBYTE signature[8];
  UWORD image_segment;
  UWORD resident_text_segment;
  UWORD init_segment;
  UWORD init_bytes;
  UWORD init_stack_segment;
  UWORD init_stack_bytes;
  UWORD memory_top_segment;
  UWORD version;
};

/* A low-staging carrier is valid on every supported VA RAM size.  In that
   profile the carrier builder fixes all live image/INIT intervals below the
   staging envelope, so the conventional-memory ceiling is supplied by the
   native adapter at boot rather than baked into the image. */
#define PC88VA_LAYOUT_RUNTIME_MEMORY_TOP 0

extern struct pc88va_layout m13_layout;
/* The builder fills fixed carrier addresses; the loader supplies the actual
   file segment selected before the carrier overwrites the loader context. */
struct pc88va_boot_layout {
  UBYTE signature[8];
  UWORD file_segment;
  UWORD carrier_segment;
  UWORD scratch_segment;
  UWORD ring_segment;
  UWORD bridge_stack_segment;
  UWORD bridge_stack_pointer;
};
extern struct pc88va_boot_layout m16_boot_layout;
typedef char pc88va_boot_layout_size_check[sizeof(struct pc88va_boot_layout) == 20 ? 1 : -1];
typedef char pc88va_layout_size_check[sizeof(struct pc88va_layout) == 24 ? 1 : -1];
#endif
