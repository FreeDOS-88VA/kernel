/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "portab.h"
#include "console.h"
#include "m13_diag.h"

#if defined(PC88VA) && defined(M13_VISIBLE_DIAGNOSTICS)

static unsigned short shell_events;
static unsigned char shell_event_visible;

#define M13_DIAG_BYTES_MAX 64U

/* Written by the assembly service wrappers before they translate errors. */
unsigned short pc88va_m13_exec_raw_ax;
unsigned short pc88va_m13_exec_raw_flags;
unsigned short pc88va_m13_input_raw_ax;
unsigned short pc88va_m13_input_raw_flags;

static void diag_putc(unsigned short character)
{
  (void)pc88va_diag_putc(character);
}

static void diag_text(const char *text)
{
  while (*text != '\0')
    diag_putc((unsigned short)(unsigned char)*text++);
}

static void diag_hex4(unsigned short value)
{
  static const char digits[] = "0123456789ABCDEF";
  diag_putc((unsigned short)digits[(value >> 12) & 0x0f]);
  diag_putc((unsigned short)digits[(value >> 8) & 0x0f]);
  diag_putc((unsigned short)digits[(value >> 4) & 0x0f]);
  diag_putc((unsigned short)digits[value & 0x0f]);
}

static void diag_hex2(unsigned short value)
{
  static const char digits[] = "0123456789ABCDEF";
  diag_putc((unsigned short)digits[(value >> 4) & 0x0f]);
  diag_putc((unsigned short)digits[value & 0x0f]);
}

static void diag_bytes(const unsigned char *bytes, unsigned short length)
{
  unsigned short index;
  unsigned short shown = length;

  if (bytes == (const unsigned char *)0)
  {
    diag_text("UNAVAILABLE");
    return;
  }
  if (shown > M13_DIAG_BYTES_MAX)
    shown = M13_DIAG_BYTES_MAX;
  if (shown == 0)
  {
    diag_text("EMPTY");
    return;
  }
  for (index = 0; index < shown; ++index)
  {
    if (index != 0)
      diag_putc((unsigned short)' ');
    diag_hex2(bytes[index]);
  }
  if (shown != length)
    diag_text(" ...");
}

static void diag_line(const char *text)
{
  diag_text(text);
  diag_text("\r\n");
}

void pc88va_m13_diag_stage(unsigned short stage)
{
  switch (stage)
  {
  case M13_DIAG_PRECONFIG_BEGIN:
    diag_line("[M13] PRECONFIG BEGIN");
    break;
  case M13_DIAG_ARENA_CHECK_OK:
    diag_line("[M13] ARENA CHECK OK");
    break;
  case M13_DIAG_POSTCONFIG_BEGIN:
    diag_line("[M13] POSTCONFIG BEGIN");
    break;
  case M13_DIAG_BUFFER_ALLOC_BEGIN:
    diag_line("[M13] BUFFER ALLOC BEGIN");
    break;
  case M13_DIAG_BUFFER_CLEAR_DONE:
    diag_line("[M13] BUFFER CLEAR DONE");
    break;
  case M13_DIAG_POSTCONFIG_DONE:
    diag_line("[M13] POSTCONFIG DONE");
    break;
  default:
    break;
  }
}

void pc88va_m13_diag_clock(unsigned short stage,
                           unsigned short value1,
                           unsigned short value2,
                           unsigned short value3)
{
  switch (stage)
  {
  case 1:
    diag_line("[M13] CLOCK DATE BEGIN");
    break;
  case 2:
    diag_text("[M13] CLOCK DATE RETURN Y=");
    diag_hex4(value1);
    diag_text(" M=");
    diag_hex2(value2);
    diag_text(" D=");
    diag_hex2(value3);
    diag_text("\r\n");
    break;
  case 3:
    diag_line("[M13] CLOCK TIME BEGIN");
    break;
  case 4:
    diag_text("[M13] CLOCK TIME RETURN H=");
    diag_hex2(value1);
    diag_text(" M=");
    diag_hex2(value2);
    diag_text(" S=");
    diag_hex2(value3);
    diag_text("\r\n");
    break;
  case 5:
    diag_text("[M13] CLOCK DATE APPLIED DAYS=");
    diag_hex4(value1);
    diag_text("\r\n");
    break;
  default:
    break;
  }
}

void pc88va_m13_diag_buffers(unsigned short requested,
                             unsigned short limit,
                             unsigned short actual)
{
  diag_text("[M13] BUFFERS REQUEST=");
  diag_hex4(requested);
  diag_text(" LIMIT=");
  diag_hex4(limit);
  diag_text(" ACTUAL=");
  diag_hex4(actual);
  diag_text("\r\n");
}

void pc88va_m13_diag_shell_exec_begin(unsigned short mode)
{
  shell_event_visible = (shell_events < 3);
  if (shell_event_visible)
  {
    diag_line("[M13] SHELL EXEC BEGIN");
    diag_line("[M13] EXEC SERVICE BEGIN");
    diag_text("[M13] EXEC MODE=");
    diag_hex4(mode);
    diag_text("\r\n");
  }
  ++shell_events;
}

void pc88va_m13_diag_shell_exec_attempt(unsigned short attempt,
                                        unsigned short origin,
                                        const unsigned char *path,
                                        unsigned short path_length)
{
  if (!shell_event_visible)
    return;
  diag_text("[M13] EXEC ATTEMPT=");
  diag_hex4(attempt);
  diag_text(" ORIGIN=");
  if (origin == 1)
    diag_text("BOOT");
  else
    diag_text("RECOVERY");
  diag_text("\r\n");
  diag_text("[M13] EXEC PATH LEN=");
  diag_hex4(path_length);
  diag_text(" BYTES=");
  diag_bytes(path, path_length);
  diag_text("\r\n");
}

void pc88va_m13_diag_config_mode(unsigned short mode)
{
  diag_text("[M13] CONFIG MODE=");
  diag_hex4(mode);
  diag_text("\r\n");
}

void pc88va_m13_diag_exec_param_match(unsigned short match)
{
  if (!shell_event_visible)
    return;
  diag_text("[M13] EXEC PARAM MATCH=");
  diag_putc((unsigned short)(match ? '1' : '0'));
  diag_text("\r\n");
}

void pc88va_m13_diag_exec_service_return(unsigned short ax,
                                         unsigned short flags)
{
  if (!shell_event_visible)
    return;
  diag_text("[M13] EXEC SERVICE RETURN AX=");
  diag_hex4(ax);
  diag_text(" CF=");
  diag_putc((unsigned short)((flags & 1U) ? '1' : '0'));
  diag_text("\r\n");
}

void pc88va_m13_diag_shell_exec_return(int rc)
{
  if (!shell_event_visible)
    return;
  diag_text("[M13] SHELL EXEC RETURN RC=");
  diag_hex4((unsigned short)rc);
  diag_text("\r\n");
  diag_line("[M13] SHELL EXEC FAIL");
}

void pc88va_m13_diag_shell_input_begin(void)
{
  if (shell_event_visible)
  {
    diag_line("[M13] SHELL INPUT BEGIN");
  }
}

void pc88va_m13_diag_input_service_return(unsigned short ax,
                                          unsigned short flags)
{
  if (!shell_event_visible)
    return;
  diag_text("[M13] INPUT SERVICE RETURN AX=");
  diag_hex4(ax);
  diag_text(" CF=");
  diag_putc((unsigned short)((flags & 1U) ? '1' : '0'));
  diag_text("\r\n");
}

void pc88va_m13_diag_input_wrapper_return(unsigned short rc)
{
  if (!shell_event_visible)
    return;
  diag_text("[M13] INPUT WRAPPER RETURN RC=");
  diag_hex4(rc);
  diag_text("\r\n");
}

void pc88va_m13_diag_input_bytes(const unsigned char *bytes,
                                 unsigned short length)
{
  if (!shell_event_visible)
    return;
  diag_text("[M13] INPUT BYTES LEN=");
  diag_hex4(length);
  diag_text(" BYTES=");
  diag_bytes(bytes, length);
  diag_text("\r\n");
}

void pc88va_m13_diag_input_length_valid(unsigned short valid)
{
  if (!shell_event_visible)
    return;
  diag_text("[M13] INPUT LENGTH VALID=");
  diag_putc((unsigned short)(valid ? '1' : '0'));
  diag_text("\r\n");
}

void pc88va_m13_diag_input_rejected(void)
{
  if (shell_event_visible)
    diag_line("[M13] INPUT REJECTED");
}

void pc88va_m13_diag_shell_input_end(unsigned short length)
{
  if (!shell_event_visible)
    return;
  diag_text("[M13] SHELL INPUT END LEN=");
  diag_hex4(length);
  diag_text("\r\n");
}

void pc88va_m13_diag_memalloc_failure(unsigned short request,
                                      unsigned short mode,
                                      unsigned short largest,
                                      unsigned short first_mcb,
                                      unsigned short owner_psp)
{
  diag_text("[M13] MEMALLOC FAIL REQ=");
  diag_hex4(request);
  diag_text(" MODE=");
  diag_hex4(mode);
  diag_text(" LARGEST=");
  diag_hex4(largest);
  diag_text(" FIRST=");
  diag_hex4(first_mcb);
  diag_text(" PSP=");
  diag_hex4(owner_psp);
  diag_text("\r\n");
}

void pc88va_m13_diag_arena(unsigned short base,
                           unsigned short top,
                           unsigned short kernel_segment,
                           unsigned short ram_kb)
{
  diag_text("[M13] ARENA BASE=");
  diag_hex4(base);
  diag_text(" TOP=");
  diag_hex4(top);
  diag_text(" KERNEL=");
  diag_hex4(kernel_segment);
  diag_text(" RAMKB=");
  diag_hex4(ram_kb);
  diag_text("\r\n");
}

void pc88va_m13_diag_mcb(unsigned short index,
                         unsigned short segment,
                         unsigned short type,
                         unsigned short owner,
                         unsigned short size)
{
  diag_text("[M13] MCB");
  diag_hex2(index);
  diag_text(" SEG=");
  diag_hex4(segment);
  diag_text(" TYPE=");
  diag_hex2(type);
  diag_text(" PSP=");
  diag_hex4(owner);
  diag_text(" SIZE=");
  diag_hex4(size);
  diag_text("\r\n");
}

#endif
