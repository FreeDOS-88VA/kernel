/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "portab.h"
#include "init-mod.h"

/*
 * init_printf is discardable: it is used only while INIT_TEXT is live.
 * These fatal paths remain callable from resident P_0/task code after the
 * INIT release barrier, so they must use the resident, non-varargs output
 * primitive instead of retaining the init formatter in the resident image.
 */
#undef printf
extern VOID put_string(const char *message);

/* These error paths remain callable after INIT has been released. */
VOID init_fatal(BYTE *message)
{
  put_string("\nInternal kernel error - ");
  put_string((const char *)message);
  put_string("\nSystem halted\n");
  for (;;) ;
}

VOID ASMCFUNC pc88va_p0_returned(void)
{
  init_fatal("Unexpected process-zero return");
}
