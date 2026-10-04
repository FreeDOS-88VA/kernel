/****************************************************************/
/*                                                              */
/*                           initclk.c                           */
/*                                                              */
/*                     System Clock Driver - initialization     */
/*                                                              */
/*                      Copyright (c) 1995                      */
/*                      Pasquale J. Villani                     */
/*                      All Rights Reserved                     */
/*                                                              */
/* This file is part of DOS-C.                                  */
/*                                                              */
/* DOS-C is free software; you can redistribute it and/or       */
/* modify it under the terms of the GNU General Public License  */
/* as published by the Free Software Foundation; either version */
/* 2, or (at your option) any later version.                    */
/*                                                              */
/* DOS-C is distributed in the hope that it will be useful, but */
/* WITHOUT ANY WARRANTY; without even the implied warranty of   */
/* MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See    */
/* the GNU General Public License for more details.             */
/*                                                              */
/* You should have received a copy of the GNU General Public    */
/* License along with DOS-C; see the file COPYING.  If not,     */
/* write to the Free Software Foundation, 675 Mass Ave,         */
/* Cambridge, MA 02139, USA.                                    */
/****************************************************************/

#include "portab.h"
#include "init-mod.h"

#ifdef VERSION_STRINGS
static char *RcsId =
    "$Id: initclk.c 1359 2008-03-09 16:11:10Z mceric $";
#endif

/*                                                                      */
/* WARNING - THIS DRIVER IS NON-PORTABLE!!!!                            */
/*                                                                      */

STATIC int InitBcdToByte(int x)
{
  return ((x >> 4) & 0xf) * 10 + (x & 0xf);
}

#if defined(PC88VA)
/* sysclk.c owns the common DOS calendar epoch state. */
extern UWORD ASM DaysSinceEpoch;
#if defined(M13_VISIBLE_DIAGNOSTICS)
#include "../pc88va/kernel/m13_diag.h"
#endif
#endif

void Init_clk_driver(void)
{
#if defined(PC88VA)
  /*
   * PC-88VA exposes its calendar clock through INT 8Ch, rather than the
   * IBM-PC INT 1Ah interface used by the other targets.  The calendar BIOS
   * returns binary civil values: AH=00h returns year/CX, month/DH, day/DL,
   * and weekday/AL; AH=02h returns hour/CH, minute/CL, and second/DH.
   *
   * Keep the platform read at this initialization boundary.  ReadPCClock()
   * remains the monotonic counter used by CLOCK$ timeouts; it is not a
   * calendar source.  The validated date is copied to the common DOS clock
   * state below without entering an early DOS service call.
   */
  static iregs regsD = {0};
  static iregs regsT = {0};

#if defined(M13_VISIBLE_DIAGNOSTICS)
  pc88va_m13_diag_clock(1, 0, 0, 0);
#endif
  regsD.a.x = 0x0000;            /* calendar BIOS: get date */
  init_call_intr(0x8c, &regsD);
#if defined(M13_VISIBLE_DIAGNOSTICS)
  pc88va_m13_diag_clock(2, regsD.c.x, regsD.d.b.h, regsD.d.b.l);
  pc88va_m13_diag_clock(3, 0, 0, 0);
#endif
  regsT.a.x = 0x0200;            /* calendar BIOS: get time */
  init_call_intr(0x8c, &regsT);
#if defined(M13_VISIBLE_DIAGNOSTICS)
  pc88va_m13_diag_clock(4, regsT.c.b.h, regsT.c.b.l, regsT.d.b.h);
#endif

  /* The documented calendar range is 1980--2079.  Refuse malformed BIOS
     data instead of writing an invalid DOS date or time. */
  if (regsD.c.x < 1980 || regsD.c.x > 2079
      || regsD.d.b.h < 1 || regsD.d.b.h > 12
      || regsD.d.b.l < 1 || regsD.d.b.l > 31
      || regsT.c.b.h > 23 || regsT.c.b.l > 59
      || regsT.d.b.h > 59)
    return;

  /* PreConfig2() has not created the first MCB at this call site.  The
   * ordinary DOS 2Bh/2Dh services enter the clock-driver I/O path and may
   * run memory-state checks, so they are not valid here.  Calculate the
   * validated BIOS date in place and publish it directly; later DOS requests
   * consume the common epoch state normally. */
  {
    UWORD epoch_days = 0;
    UWORD value;

    for (value = 1980; value < regsD.c.x; ++value)
      epoch_days += (value & 3U) ? 365U : 366U;

    for (value = 1; value < regsD.d.b.h; ++value)
    {
      switch (value)
      {
        case 2:
          epoch_days += 28U;
          if (!(regsD.c.x & 3U))
            ++epoch_days;
          break;
        case 4:
        case 6:
        case 9:
        case 11:
          epoch_days += 30U;
          break;
        default:
          epoch_days += 31U;
          break;
      }
    }
    DaysSinceEpoch = epoch_days + (UWORD)regsD.d.b.l - 1U;
#if defined(M13_VISIBLE_DIAGNOSTICS)
    pc88va_m13_diag_clock(5, DaysSinceEpoch, 0, 0);
#endif
  }
#else
  static iregs regsT = {0x200}; /* ah=0x02 */
  static iregs regsD = {0x400, 0, 0x1400, 0x101};
                      /* ah=4, ch=20^ ^cl=0, ^dh=dl=1 (2000/1/1)
                       * (above date will be set on error) */
  iregs dosregs;

  init_call_intr(0x1a, &regsT); /* get BIOS time */
  init_call_intr(0x1a, &regsD); /* get BIOS date */

  /* DosSetDate */
  dosregs.a.b.h = 0x2b;
  dosregs.c.x = 100 * InitBcdToByte(regsD.c.b.h) /* century */
                    + InitBcdToByte(regsD.c.b.l);/* year */
  /* A BIOS with y2k (year 2000) bug will always report year 19nn */
  if ((dosregs.c.x >= 1900) && (dosregs.c.x < 1980)) dosregs.c.x += 100;
  dosregs.d.b.h = InitBcdToByte(regsD.d.b.h);   /* month */
  dosregs.d.b.l = InitBcdToByte(regsD.d.b.l);   /* day   */
  init_call_intr(0x21, &dosregs);

  /* DosSetTime */
  dosregs.a.b.h = 0x2d;
  dosregs.c.b.l = InitBcdToByte(regsT.c.b.l);   /* minutes */
  dosregs.c.b.h = InitBcdToByte(regsT.c.b.h);   /* hours   */
  dosregs.d.b.h = InitBcdToByte(regsT.d.b.h);   /*seconds */
  dosregs.d.b.l = 0;
  init_call_intr(0x21, &dosregs);
#endif
}
