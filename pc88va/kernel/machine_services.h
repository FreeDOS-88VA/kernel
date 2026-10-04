/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef PC88VA_MACHINE_SERVICES_H
#define PC88VA_MACHINE_SERVICES_H

/* Near Watcom register ABI, AX argument/status. Other registers and FLAGS
 * preserved, except fatal_stop_request never returns and clears IF.
 * Call with IF=DF=0. Record pointers must designate the exported storage
 * in DS=CS. All integers are little endian. Version zero is invalid.
 * Initialization is single shot; state 2 alone means initialized.
 */
#pragma pack(push, 1)
struct pc88va_memory_interval {
  unsigned long begin, end; /* Half-open physical byte interval. */
  unsigned short usable;  /* Zero reserved, one usable. */
};
struct pc88va_memory_record {
  unsigned short version, count;
  struct pc88va_memory_interval intervals[3];
};
struct pc88va_clock_record {
  unsigned short version;
  unsigned long observed_edges; /* Origin zero at first source sample, then
                                * observed edges modulo 2^32; not elapsed time. */
};
#pragma pack(pop)
int pc88va_machine_init(void);
int pc88va_memory_query(void *record);
int pc88va_interrupts_init(void);
int pc88va_clock_read(void *record);
int pc88va_fatal_stop_request(unsigned short reason);
extern struct pc88va_memory_record pc88va_m10_memory_record;
extern struct pc88va_clock_record pc88va_m10_clock_record;
#endif
