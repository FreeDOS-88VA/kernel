/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Near pointers reference the packed records documented in boot/loader-abi.md. */
#ifndef PC88VA_LOADER_SERVICES_H
#define PC88VA_LOADER_SERVICES_H
#if !defined(PC88VA) || defined(NEC98) || defined(IBMPC)
#error Exactly the PC88VA machine-family selector is required
#endif

/* Open Watcom 1.9 small model, default register calling convention: AX pointer.
 * Zero is success; positive values identify a fail-closed loader error.
 * Handoff does not return on success. Other hardware services remain stubs.
 */
int pc88va_disk_read(void *request);
int pc88va_loader_handoff(void *record);
#endif
