/****************************************************************/
/*                                                              */
/*                            dsk.c                             */
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
#include "globals.h"
#include "dyndata.h"

#ifdef VERSION_STRINGS
static BYTE *dskRcsId =
    "$Id: dsk.c 1702 2012-02-04 08:46:16Z perditionc $";
#endif

#if defined(DEBUG)
#define DebugPrintf(x) printf x
#else
#define DebugPrintf(x)
#endif

/* #define STATIC  */

BOOL ASMPASCAL fl_reset(WORD);
COUNT ASMPASCAL fl_diskchanged(WORD);
#if defined(PC88VA)
extern COUNT ASMPASCAL pc88va_m16_probe_read(WORD, WORD, UBYTE FAR *);
extern COUNT ASMPASCAL pc88va_m16_set_profile(WORD, WORD, WORD, WORD, WORD);
#endif

COUNT ASMPASCAL fl_format(WORD, WORD, WORD, WORD, WORD, UBYTE FAR *);
COUNT ASMPASCAL fl_read(WORD, WORD, WORD, WORD, WORD, UBYTE FAR *);
COUNT ASMPASCAL fl_write(WORD, WORD, WORD, WORD, WORD, UBYTE FAR *);
COUNT ASMPASCAL fl_verify(WORD, WORD, WORD, WORD, WORD, UBYTE FAR *);
COUNT ASMPASCAL fl_setdisktype(WORD, WORD);
COUNT ASMPASCAL fl_setmediatype(WORD, WORD, WORD);
VOID ASMPASCAL fl_readkey(VOID);
extern COUNT ASMPASCAL fl_lba_ReadWrite(BYTE drive, WORD mode,
                                       struct _bios_LBA_address_packet FAR
                                       * dap_p);
UWORD ASMPASCAL floppy_change(UWORD);
#ifdef __WATCOMC__
#pragma aux (pascal) fl_reset modify exact [ax dx]
#pragma aux (pascal) fl_diskchanged modify exact [ax dx]
#pragma aux (pascal) fl_setdisktype modify exact [ax bx dx]
#pragma aux (pascal) fl_readkey modify exact [ax]
#pragma aux (pascal) fl_lba_ReadWrite modify exact [ax dx]
#pragma aux (pascal) floppy_change modify exact [ax cx dx]
#if defined(PC88VA)
#pragma aux (pascal) pc88va_m16_probe_read modify exact [ax]
#pragma aux (pascal) pc88va_m16_set_profile modify exact [ax]
#endif
#endif

STATIC int LBA_Transfer(ddt * pddt, UWORD mode, VOID FAR * buffer,
                 ULONG LBA_address, unsigned total, UWORD * transferred);

#define NENTRY          26      /* total size of dispatch table */

#define LBA_READ         0x4200
#define LBA_WRITE        0x4300
UWORD LBA_WRITE_VERIFY = 0x4302;
#define LBA_VERIFY       0x4400
#define LBA_FORMAT       0xffff /* fake number for FORMAT track
                                   (only for NON-LBA floppies now!) */

                /* this buffer must not overlap a 64K boundary
                   due to DMA transfers
                   this is certainly true, if located somewhere
                   at 0xf+1000 and must hold already during BOOT time
                 */
UBYTE DiskTransferBuffer[MAX_SEC_SIZE];

struct FS_info {
  ULONG serialno;
  BYTE volume[11];
  BYTE fstype[8];
};

extern struct DynS ASM Dyn;

/*TE - array access functions */
ddt *getddt(int dev)
{
  return &(((ddt *) Dyn.Buffer)[dev]);
}

STATIC VOID tmark(ddt *pddt)
{
  pddt->ddt_fh.ddt_lasttime = ReadPCClock();
}

STATIC BOOL tdelay(ddt *pddt, ULONG ticks)
{
  return ReadPCClock() - pddt->ddt_fh.ddt_lasttime >= ticks;
}

#define N_PART 4                /* number of partitions per
                                   table partition              */

#define PARTOFF 0x1be

#ifdef PROTO
typedef WORD dsk_proc(rqptr rq, ddt * pddt);
#else
typedef WORD dsk_proc();
#endif

STATIC dsk_proc mediachk, bldbpb, blockio, IoctlQueblk,
    Genblkdev, Getlogdev, Setlogdev, blk_Open, blk_Close,
    blk_Media, blk_noerr, blk_nondr, blk_error;

STATIC WORD getbpb(ddt * pddt);
#ifdef PROTO
STATIC WORD dskerr(COUNT);
#else
STATIC WORD dskerr();
#endif

/*                                                                      */
/* the function dispatch table                                          */
/*                                                                      */

static dsk_proc * const dispatch[NENTRY] =
{
      /* disk init is done in diskinit.c, so this should never be called */
      blk_error,                /* Initialize                   */
      mediachk,                 /* Media Check                  */
      bldbpb,                   /* Build BPB                    */
      blk_error,                /* Ioctl In                     */
      blockio,                  /* Input (Read)                 */
      blk_nondr,                /* Non-destructive Read         */
      blk_noerr,                /* Input Status                 */
      blk_noerr,                /* Input Flush                  */
      blockio,                  /* Output (Write)               */
      blockio,                  /* Output with verify           */
      blk_noerr,                /* Output Status                */
      blk_noerr,                /* Output Flush                 */
      blk_error,                /* Ioctl Out                    */
      blk_Open,                 /* Device Open                  */
      blk_Close,                /* Device Close                 */
      blk_Media,                /* Removable Media              */
      blk_noerr,                /* Output till busy             */
      blk_error,                /* undefined                    */
      blk_error,                /* undefined                    */
      Genblkdev,                /* Generic Ioctl Call           */
      blk_error,                /* undefined                    */
      blk_error,                /* undefined                    */
      blk_error,                /* undefined                    */
      Getlogdev,                /* Get Logical Device           */
      Setlogdev,                /* Set Logical Device           */
      IoctlQueblk               /* Ioctl Query                  */
};

#define hd(x)   ((x) & DF_FIXED)

/* ----------------------------------------------------------------------- */
/*  F U N C T I O N S  --------------------------------------------------- */
/* ----------------------------------------------------------------------- */

COUNT ASMCFUNC FAR blk_driver(rqptr rp)
{
  if (rp->r_unit >= blk_dev.dh_name[0] && rp->r_command != C_INIT)
#if defined(PC88VA)
  {
    if (rp->r_command == C_INPUT || rp->r_command == C_OUTPUT ||
        rp->r_command == C_OUTVFY)
      rp->r_count = 0;
#endif
    return failure(E_UNIT);
#if defined(PC88VA)
  }
  if (rp->r_command >= NENTRY)
#else
  if (rp->r_command > NENTRY)
#endif
  {
    return failure(E_FAILURE);  /* general failure */
  }
  else
    return ((*dispatch[rp->r_command]) (rp, getddt(rp->r_unit)));
}

STATIC char template_string[] = "Remove diskette in drive X:\n";
#define DRIVE_POS (sizeof(template_string) - 4)

STATIC WORD play_dj(ddt * pddt)
{
  /* play the DJ ... */
  if ((pddt->ddt_descflags & (DF_MULTLOG | DF_CURLOG)) == DF_MULTLOG)
  {
    int i;
    ddt *pddt2 = getddt(0);
    for (i = 0; i < blk_dev.dh_name[0]; i++, pddt2++)
    {
      if (pddt->ddt_driveno == pddt2->ddt_driveno &&
          (pddt2->ddt_descflags & (DF_MULTLOG | DF_CURLOG)) ==
          (DF_MULTLOG | DF_CURLOG))
        break;
    }
    if (i == blk_dev.dh_name[0])
    {
      put_string("Error in the DJ mechanism!\n");   /* should not happen! */
    }
    else
    {
      xreg dx;
      dx.b.l = pddt->ddt_logdriveno;
      dx.b.h = pddt2->ddt_logdriveno;
      /* call int2f/ax=4a00 */
      if (floppy_change(dx.x) != 0xffff) {
        /* if someone else does not make a nice dialog... */
        template_string[DRIVE_POS] = 'A' + pddt2->ddt_logdriveno;
        put_string(template_string);
        put_string("Insert");
        template_string[DRIVE_POS] = 'A' + pddt->ddt_logdriveno;
        put_string(template_string + 6);
        put_string("Press any key to continue ... \n");
        fl_readkey();
      }
      pddt2->ddt_descflags &= ~DF_CURLOG;
      pddt->ddt_descflags |= DF_CURLOG;
      pokeb(0, 0x504, pddt->ddt_logdriveno);
    }
    return M_CHANGED;
  }
  return M_NOT_CHANGED;
}

STATIC WORD diskchange(ddt * pddt)
{
  COUNT result;

  /* if it's a hard drive, media never changes */
  if (hd(pddt->ddt_descflags))
    return M_NOT_CHANGED;

  if (play_dj(pddt) == M_CHANGED)
    return M_CHANGED;

  if (pddt->ddt_descflags & DF_CHANGELINE)      /* if we can detect a change ... */
  {
    if ((result = fl_diskchanged(pddt->ddt_driveno)) == 1)
      /* check if it has changed... */
      return M_CHANGED;
    else if (result == 0)
      return M_NOT_CHANGED;
#if defined(PC88VA)
    /* An uncertain VA firmware result needs a probe now, even just after I/O.
       The elapsed-time fallback must not hide a possible replacement. */
    return M_DONT_KNOW;
#endif
  }

  /* can not detect or error... */
  return tdelay(pddt, 37ul) ? M_DONT_KNOW : M_NOT_CHANGED;
}

STATIC WORD mediachk(rqptr rp, ddt * pddt)
{
  /* check floppy status */
  if (pddt->ddt_descflags & DF_REFORMAT)
  {
    pddt->ddt_descflags &= ~DF_REFORMAT;
    rp->r_mcretcode = M_CHANGED;
  }
  else if (pddt->ddt_descflags & DF_DISKCHANGE)
  {
    pddt->ddt_descflags &= ~DF_DISKCHANGE;
    rp->r_mcretcode = M_DONT_KNOW;
  }
  else
  {
    rp->r_mcretcode = diskchange(pddt);
#if !defined(PC88VA)
    if (rp->r_mcretcode == M_DONT_KNOW)
    {
      /* don't know but can check serial number ... */
      ULONG serialno = pddt->ddt_serialno;
      COUNT result = getbpb(pddt);
      if (result != 0)
        return (result);
      if (serialno != pddt->ddt_serialno)
        rp->r_mcretcode = M_CHANGED;
    }
#endif
  }
#if defined(PC88VA)
  if (rp->r_mcretcode == M_DONT_KNOW)
  {
    /* Requests are synchronous and getbpb does not call INT24. Keep this
       snapshot in DGROUP: a driver can also be entered with SS != DS.
       A matching nonzero DOS volume ID and complete BPB preserve the binding;
       absent identity stays uncertain, and errors must not become success. */
    static bpb previous_bpb;
    ULONG serialno = pddt->ddt_serialno;
    COUNT result;
    memcpy(&previous_bpb, &pddt->ddt_bpb, sizeof(bpb));
    result = getbpb(pddt);
    if (result != 0)
      return result;
    if (serialno != pddt->ddt_serialno ||
        memcmp(&previous_bpb, &pddt->ddt_bpb, sizeof(bpb)) != 0)
      rp->r_mcretcode = M_CHANGED;
    else if (serialno != 0)
    {
      rp->r_mcretcode = M_NOT_CHANGED;
      pddt->ddt_descflags &= ~DF_DISKCHANGE;
      tmark(pddt);
    }
  }
#endif
  return S_DONE;
}

/*
 *  Read Write Sector Zero or Hard Drive Dos Bpb
 */
STATIC WORD RWzero(ddt * pddt, UWORD mode)
{
  UWORD done;

  return LBA_Transfer(pddt, mode,
                      (UBYTE FAR *) & DiskTransferBuffer,
                      pddt->ddt_offset, 1, &done);
}

/*
   0 if not set, 1 = a, 2 = b, etc, assume set.
   page 424 MS Programmer's Ref.
 */
STATIC WORD Getlogdev(rqptr rp, ddt * pddt)
{
  int i;
  ddt *pddt2;

  if (!(pddt->ddt_descflags & DF_MULTLOG)) {
    rp->r_unit = 0;
    return S_DONE;
  }

  pddt2 = getddt(0);
  for (i = 0; i < blk_dev.dh_name[0]; i++, pddt2++)
  {
    if (pddt->ddt_driveno == pddt2->ddt_driveno &&
        (pddt2->ddt_descflags & (DF_MULTLOG | DF_CURLOG)) ==
        (DF_MULTLOG | DF_CURLOG))
        break;
  }

  rp->r_unit = i+1;
  return S_DONE;
}

STATIC WORD Setlogdev(rqptr rp, ddt * pddt)
{
  unsigned char unit = rp->r_unit;
  Getlogdev(rp, pddt);
  if (rp->r_unit == 0)
    return S_DONE;
  getddt(rp->r_unit - 1)->ddt_descflags &= ~DF_CURLOG;
  pddt->ddt_descflags |= DF_CURLOG;
  rp->r_unit = unit + 1;
  return S_DONE;
}

STATIC WORD blk_Open(rqptr rp, ddt * pddt)
{
  UNREFERENCED_PARAMETER(rp);

  pddt->ddt_FileOC++;
  return S_DONE;
}

STATIC WORD blk_Close(rqptr rp, ddt * pddt)
{
  UNREFERENCED_PARAMETER(rp);

  pddt->ddt_FileOC--;
  return S_DONE;
}

STATIC WORD blk_nondr(rqptr rp, ddt * pddt)
{
  UNREFERENCED_PARAMETER(rp);
  UNREFERENCED_PARAMETER(pddt);

  return S_BUSY | S_DONE;
}

STATIC WORD blk_Media(rqptr rp, ddt * pddt)
{
  UNREFERENCED_PARAMETER(rp);

  if (hd(pddt->ddt_descflags))
    return S_BUSY | S_DONE;     /* Hard Drive */
  else
    return S_DONE;              /* Floppy */
}

STATIC WORD getbpb(ddt * pddt)
{
  ULONG count;
  bpb *pbpbarray = &pddt->ddt_bpb;
  unsigned secs_per_cyl;
  WORD ret;
#if defined(PC88VA)
  typedef struct {
    UWORD mode;
    UWORD cylinders;
    UWORD total;
    UWORD sectors_per_track;
    UWORD heads;
    UWORD sector_bytes;
    UBYTE media;
    UBYTE standard_signature;
  } pc88va_m16_profile;
  static const pc88va_m16_profile profiles[] = {
    {0x02, 40, 640, 8, 2, 512, 0xff, 1},   /* 2D 320 KiB */
    {0x02, 40, 720, 9, 2, 512, 0xfd, 1},   /* 2D 360 KiB */
    {0x12, 80, 1280, 8, 2, 512, 0xfb, 1},  /* 2DD 640 KiB */
    {0x12, 80, 1440, 9, 2, 512, 0xf9, 1},  /* 2DD 720 KiB */
    {0x22, 80, 2400, 15, 2, 512, 0xf9, 1}, /* 2HC 1.2 MiB */
    {0x23, 80, 1280, 8, 2, 1024, 0xfe, 0}, /* existing M15 2HD */
    {0x23, 77, 1232, 8, 2, 1024, 0xfe, 0} /* 77-cylinder 2HD */
  };
  /* Probe the profile last recognized on the unit first, and read the boot
     sector once per disk mode: each mode change and failed read costs the
     drive recalibrations and revolutions.  The accepted profiles and their
     validation are unchanged. */
  static UBYTE preferred_profile[2] = {5, 5};
  unsigned pass;
  unsigned profile_index;
  unsigned unit = pddt->ddt_driveno & 1;
  UWORD read_mode = 0xffff;
  UWORD failed_mode = 0xffff;
  UBYTE saw_read = FALSE;
  UBYTE legacy_native = FALSE;

  /* pddt->ddt_descflags |= DF_NOACCESS;
   * disabled for now - problems with FORMAT ?? */

  /* set drive to not accessible and changed */
  if (diskchange(pddt) != M_NOT_CHANGED)
    pddt->ddt_descflags |= DF_DISKCHANGE;

  pddt->ddt_descflags |= DF_NOACCESS;
  for (pass = 0; pass <= sizeof(profiles) / sizeof(profiles[0]); pass++)
  {
    const pc88va_m16_profile *profile;
    BYTE *raw_bpb = (BYTE *)&DiskTransferBuffer[BT_BPB];
    bpb observed;
    UBYTE signature;
    UBYTE short_bpb;

    if (pass == 0)
      profile_index = preferred_profile[unit];
    else
    {
      profile_index = pass - 1;
      if (profile_index == preferred_profile[unit])
        continue;
    }
    profile = &profiles[profile_index];
    if (profile->mode == failed_mode)
      continue;
    if (profile->mode != read_mode)
    {
      ret = pc88va_m16_probe_read(pddt->ddt_driveno, profile->mode,
                                  (UBYTE FAR *)DiskTransferBuffer);
      if (ret != 0)
      {
        read_mode = 0xffff;
        failed_mode = profile->mode;
        continue;
      }
      read_mode = profile->mode;
    }
    saw_read = TRUE;
    signature = DiskTransferBuffer[0x1fe] == 0x55 &&
                DiskTransferBuffer[0x1ff] == 0xaa;
    memcpy(&observed, raw_bpb, sizeof(observed));
    short_bpb = DiskTransferBuffer[0x26] != 0x28 &&
                DiskTransferBuffer[0x26] != 0x29;
    if (short_bpb)
    {
      /* The native formatter stores a DOS-era BPB with a 16-bit hidden
         sector field. Later bytes are IPL instructions, not extended fields. */
      observed.bpb_hidden &= 0xffffUL;
      observed.bpb_huge = 0;
    }
    /* A plausible BPB must pass the normal validator, never a fallback. */
    if (profile->mode == 0x23 && observed.bpb_nbyte != 512 &&
        observed.bpb_nbyte != 1024 && !signature &&
        DiskTransferBuffer[0x26] != 0x28 && DiskTransferBuffer[0x26] != 0x29)
      legacy_native = TRUE;

    if (observed.bpb_nbyte != profile->sector_bytes ||
        observed.bpb_nsize != profile->total || observed.bpb_huge != 0 ||
        observed.bpb_nsecs != profile->sectors_per_track ||
        observed.bpb_nheads != profile->heads ||
        observed.bpb_mdesc != profile->media || observed.bpb_hidden != 0 ||
        observed.bpb_nsector == 0 ||
        (observed.bpb_nsector & (observed.bpb_nsector - 1)) != 0 ||
        observed.bpb_nreserved == 0 || observed.bpb_nfat != 2 ||
        observed.bpb_ndirent == 0 || observed.bpb_nfsect == 0 ||
        profile->total != profile->cylinders * profile->heads *
                          profile->sectors_per_track)
      continue;
    if (profile->standard_signature && !signature && !short_bpb)
      continue;
    if (!profile->standard_signature && !short_bpb &&
        ((DiskTransferBuffer[0x1fe] == 0x55) !=
         (DiskTransferBuffer[0x1ff] == 0xaa)))
      continue;
    if (pc88va_m16_set_profile(pddt->ddt_driveno, profile->mode,
                               profile->total, profile->sectors_per_track,
                               profile->heads) != 0)
      continue;

    if (short_bpb && !signature)
    {
      unsigned fat_copy;
      ULONG lba;
      /* The checks below overwrite the boot sector in the buffer. */
      read_mode = 0xffff;
      for (fat_copy = 0; fat_copy < 2; fat_copy++)
      {
        lba = observed.bpb_nreserved +
              (ULONG)fat_copy * observed.bpb_nfsect;
        if (lba >= profile->total ||
            fl_read(pddt->ddt_driveno,
                    (UWORD)(lba / profile->sectors_per_track % 2),
                    (UWORD)(lba / (profile->sectors_per_track * 2)),
                    (UWORD)(lba % profile->sectors_per_track + 1), 1,
                    (UBYTE FAR *)DiskTransferBuffer) != 0 ||
            DiskTransferBuffer[0] != profile->media ||
            DiskTransferBuffer[1] != 0xff || DiskTransferBuffer[2] != 0xff)
          break;
      }
      if (fat_copy != 2 ||
          fl_read(pddt->ddt_driveno, 1, profile->cylinders - 1,
                  profile->sectors_per_track, 1,
                  (UBYTE FAR *)DiskTransferBuffer) != 0)
        continue;
      /* The buffer no longer holds the IPL; never parse data as an EBPB. */
      DiskTransferBuffer[0x26] = 0;
    }
    memcpy(pbpbarray, &observed, sizeof(observed));
    pddt->ddt_ncyl = profile->cylinders;
    pddt->ddt_descflags &= ~DF_NOACCESS;
    preferred_profile[unit] = (UBYTE)profile_index;
    goto read_extended_bpb;
  }

  /* Native legacy FAT12 has no boot BPB.  Recognition is read-only while
     DF_NOACCESS remains set: require both FAT reserved entries and the final
     sector of the explicit native profile.  Do not infer a writable layout
     from an unreadable boot sector or arbitrary unrecognized BPB fields. */
  if (legacy_native &&
      pc88va_m16_set_profile(pddt->ddt_driveno, 0x23, 1232, 8, 2) == 0)
  {
    static const bpb native_bpb = {1024, 1, 1, 2, 192, 1232,
                                   0xfe, 2, 8, 2, 0, 0};
    unsigned fat_sector;
    for (fat_sector = 2; fat_sector <= 4; fat_sector += 2)
    {
      if (fl_read(pddt->ddt_driveno, 0, 0, fat_sector, 1,
                  (UBYTE FAR *)DiskTransferBuffer) != 0 ||
          DiskTransferBuffer[0] != 0xfe || DiskTransferBuffer[1] != 0xff ||
          DiskTransferBuffer[2] != 0xff)
        break;
    }
    if (fat_sector == 6 &&
        fl_read(pddt->ddt_driveno, 1, 76, 8, 1,
                (UBYTE FAR *)DiskTransferBuffer) == 0)
    {
      memcpy(pbpbarray, &native_bpb, sizeof(native_bpb));
      pddt->ddt_descflags &= ~DF_NOACCESS;
      /* The buffer now contains data, not an extended boot record. */
      DiskTransferBuffer[0x26] = 0;
      goto read_extended_bpb;
    }
  }
  pddt->ddt_descflags |= DF_DISKCHANGE;
  return saw_read ? failure(E_FAILURE) : failure(E_NOTRDY);
#else
  /* pddt->ddt_descflags |= DF_NOACCESS; 
   * disabled for now - problems with FORMAT ?? */

  /* set drive to not accessible and changed */
  if (diskchange(pddt) != M_NOT_CHANGED)
    pddt->ddt_descflags |= DF_DISKCHANGE;

  ret = RWzero(pddt, LBA_READ);
  if (ret != 0)
    return (dskerr(ret));

  pbpbarray->bpb_nbyte = getword(&DiskTransferBuffer[BT_BPB]);

  if (DiskTransferBuffer[0x1fe] != 0x55
      || DiskTransferBuffer[0x1ff] != 0xaa || pbpbarray->bpb_nbyte % 512)
  {
    /* copy default bpb to be sure that there is no bogus data */
    memcpy(pbpbarray, &pddt->ddt_defbpb, sizeof(bpb));
    return S_DONE;
  }

  pddt->ddt_descflags &= ~DF_NOACCESS;  /* set drive to accessible */

/*TE ~ 200 bytes*/

  memcpy(pbpbarray, &DiskTransferBuffer[BT_BPB], sizeof(bpb));
#endif

#ifdef PC88VA
read_extended_bpb:
#endif
  /*?? */
  /*  2b is fat16 volume label. if memcmp, then offset 0x36.
     if (fstrncmp((BYTE *) & DiskTransferBuffer[0x36], "FAT16",5) == 0  ||
     fstrncmp((BYTE *) & DiskTransferBuffer[0x36], "FAT12",5) == 0) {
     TE: I'm not sure, what the _real_ decision point is, however MSDN
     'A_BF_BPB_SectorsPerFAT
     The number of sectors per FAT.
     Note: This member will always be zero in a FAT32 BPB.
     Use the values from A_BF_BPB_BigSectorsPerFat...
  */
  {
    struct FS_info *fs = (struct FS_info *)&DiskTransferBuffer[0x27];
    register BYTE extended_BPB_signature;
#ifdef WITHFAT32
    if (pbpbarray->bpb_nfsect == 0)
    {
      /* FAT32 boot sector */
      fs = (struct FS_info *)&DiskTransferBuffer[0x43];
      /* Extended BPB signature, offset differs for FAT32 vs FAT12/16 */
      extended_BPB_signature = DiskTransferBuffer[0x42];
    }
    else
#endif
      extended_BPB_signature = DiskTransferBuffer[0x26];

    /* 0x29 is usual signature value for serial#,vol label,& fstype; 
       0x28 older EBPB signature indicating only serial# is valid   */
    if ((extended_BPB_signature == 0x29) || (extended_BPB_signature == 0x28))
    {
      pddt->ddt_serialno = getlong(&fs->serialno);
    } else {
      /* short BPB, no serial # available */
      pddt->ddt_serialno = 0;
    }
    if (extended_BPB_signature == 0x29)
    {
      fmemcpy(pddt->ddt_volume, fs->volume, sizeof fs->volume);
      fmemcpy(pddt->ddt_fstype, fs->fstype, sizeof fs->fstype);
    } else {
      /* earlier extended BPB or short BPB, fields not available */
      fmemcpy(pddt->ddt_volume, "NO NAME    ", 11);
      fmemcpy(pddt->ddt_fstype, "FAT??   ", 8);
    }
  }

#ifdef DSK_DEBUG
  printf("BPB_NBYTE     = %04x\n", pbpbarray->bpb_nbyte);
  printf("BPB_NSECTOR   = %02x\n", pbpbarray->bpb_nsector);
  printf("BPB_NRESERVED = %04x\n", pbpbarray->bpb_nreserved);
  printf("BPB_NFAT      = %02x\n", pbpbarray->bpb_nfat);
  printf("BPB_NDIRENT   = %04x\n", pbpbarray->bpb_ndirent);
  printf("BPB_NSIZE     = %04x\n", pbpbarray->bpb_nsize);
  printf("BPB_MDESC     = %02x\n", pbpbarray->bpb_mdesc);
  printf("BPB_NFSECT    = %04x\n", pbpbarray->bpb_nfsect);
#endif

  count =
      pbpbarray->bpb_nsize == 0 ?
      pbpbarray->bpb_huge : pbpbarray->bpb_nsize;
  secs_per_cyl = pbpbarray->bpb_nheads * pbpbarray->bpb_nsecs;

  if (secs_per_cyl == 0)
  {
    tmark(pddt);
    return failure(E_FAILURE);
  }
  /* this field is problematic for partitions > 65535 cylinders,
     in general > 512 GiB. However: we are not using it ourselves. */
  pddt->ddt_ncyl = (UWORD)((count + (secs_per_cyl - 1)) / secs_per_cyl);

  tmark(pddt);

#ifdef DSK_DEBUG
  printf("BPB_NSECS     = %04x\n", pbpbarray->bpb_nsecs);
  printf("BPB_NHEADS    = %04x\n", pbpbarray->bpb_nheads);
  printf("BPB_HIDDEN    = %08lx\n", pbpbarray->bpb_hidden);
  printf("BPB_HUGE      = %08lx\n", pbpbarray->bpb_huge);
#endif

  return 0;
}

STATIC WORD bldbpb(rqptr rp, ddt * pddt)
{
  WORD result;

  if ((result = getbpb(pddt)) != 0)
    return result;

  rp->r_bpptr = &pddt->ddt_bpb;
  return S_DONE;
}

STATIC WORD IoctlQueblk(rqptr rp, ddt * pddt)
{
  UNREFERENCED_PARAMETER(pddt);

#ifdef WITHFAT32
  if (rp->r_cat == 8 || rp->r_cat == 0x48)
#else
  if (rp->r_cat == 8)
#endif
  {
#if defined(PC88VA)
    UBYTE fun = rp->r_fun & 0xdf;
    if ((fun >= 0x40 && fun <= 0x42) ||
        (fun >= 0x46 && fun <= 0x47))
      return S_DONE;
#else
    switch (rp->r_fun)
    {
    case 0x46:
    case 0x47:
    case 0x60:
    case 0x66:
    case 0x67:
      return S_DONE;
    }
#endif
  }
  return failure(E_CMD);
}

/* read/write block with CHS based off start of drive's partition */
STATIC COUNT Genblockio(ddt * pddt, UWORD mode, WORD head, WORD track,
                 WORD sector, WORD count, VOID FAR * buffer)
{
  UWORD transferred;

  /* apparently sector is ZERO, not ONE based !!! */
  return LBA_Transfer(pddt, mode, buffer,
                      ((ULONG) track * pddt->ddt_bpb.bpb_nheads + head) *
                      (ULONG) pddt->ddt_bpb.bpb_nsecs +
                      pddt->ddt_offset + sector, count, &transferred);
}

/* read/write block with CHS based off start of disk drive is on */
STATIC COUNT GenblockioAbs(ddt * pddt, UWORD mode, WORD head, WORD track,
                 WORD sector, WORD count, VOID FAR * buffer)
{
  UWORD transferred;

  /* apparently sector is ZERO, not ONE based !!! */
  return LBA_Transfer(pddt, mode, buffer,
                      ((ULONG) track * pddt->ddt_bpb.bpb_nheads + head) *
                      (ULONG) pddt->ddt_bpb.bpb_nsecs +
                      sector, count, &transferred);
}

STATIC WORD Genblkdev(rqptr rp, ddt * pddt)
{
  int ret;
  unsigned descflags = pddt->ddt_descflags;
#ifdef WITHFAT32
  int extended = 0;

  if (rp->r_cat == 0x48)
    extended = 1;
  else
#endif
  if (rp->r_cat != 8)
    return failure(E_CMD);

  switch (rp->r_fun)
  {
    case 0x40:                 /* set device parameters */
      {
        struct gblkio FAR *gblp = rp->r_io;
        bpb *pbpb;

        pddt->ddt_type = gblp->gbio_devtype;
        pddt->ddt_descflags = (descflags & ~3) | (gblp->gbio_devattrib & 3)
            | (DF_DPCHANGED | DF_REFORMAT);
        pddt->ddt_ncyl = gblp->gbio_ncyl;
        /* use default dpb or current bpb? */
        pbpb =
            (gblp->gbio_spcfunbit & 0x01) ==
            0 ? &pddt->ddt_defbpb : &pddt->ddt_bpb;
#ifdef WITHFAT32
        fmemcpy(pbpb, &gblp->gbio_bpb,
                extended ? sizeof(gblp->gbio_bpb) : BPB_SIZEOF);
#else
        fmemcpy(pbpb, &gblp->gbio_bpb, sizeof(gblp->gbio_bpb));
#endif
        /*pbpb->bpb_nsector = gblp->gbio_nsecs; */
        break;
      }
    case 0x41:                 /* write track - CHS is absolute not relative to partition start */
      {
        struct gblkrw FAR *rw = rp->r_rw;
        ret = GenblockioAbs(pddt, LBA_WRITE, rw->gbrw_head, rw->gbrw_cyl,
                         rw->gbrw_sector, rw->gbrw_nsecs, rw->gbrw_buffer);
        if (ret != 0)
          return dskerr(ret);
      }
      break;
    case 0x42:                 /* format/verify track */
      {
        struct gblkfv FAR *fv = rp->r_fv;
        COUNT tracks;
        struct thst {
          UBYTE track, head, sector, type;
        } *addrfield, afentry;

        pddt->ddt_descflags &= ~DF_DPCHANGED;
        if (hd(descflags))
        {
          /* XXX no low-level formatting for hard disks implemented */
          fv->gbfv_spcfunbit = 1;       /* "not supported by bios" */
          return S_DONE;
        }
        if (descflags & DF_DPCHANGED)
        {
          /* first try newer setmediatype function */
          ret = fl_setmediatype(pddt->ddt_driveno, pddt->ddt_ncyl,
                                pddt->ddt_bpb.bpb_nsecs);
          if (ret == 0xc)
          {
            /* specified tracks, sectors/track not allowed for drive */
            fv->gbfv_spcfunbit = 2;
            return dskerr(ret);
          }
          else if (ret == 0x80)
          {
            fv->gbfv_spcfunbit = 3;     /* no disk in drive */
            return dskerr(ret);
          }
          else if (ret != 0)
            /* otherwise, setdisktype */
          {
            unsigned char type;
            unsigned tracks, secs;
            if ((fv->gbfv_spcfunbit & 1) &&
                (ret =
                 fl_read(pddt->ddt_driveno, 0, 0, 1, 1,
                         DiskTransferBuffer)) != 0)
            {
              fv->gbfv_spcfunbit = 3;   /* no disk in drive */
              return dskerr(ret);
            }
            /* type 1: 320/360K disk in 360K drive */
            /* type 2: 320/360K disk in 1.2M drive */
            tracks = pddt->ddt_ncyl;
            secs = pddt->ddt_bpb.bpb_nsecs;
            type = pddt->ddt_type + 1;
            if (!(tracks == 40 && (secs == 9 || secs == 8) && type < 3))
            {
              /* type 3: 1.2M disk in 1.2M drive */
              /* type 4: 720kb disk in 1.44M or 720kb drive */
              type++;
              if (type == 9) /* 1.44M drive */
                type = 4;
              if (!(tracks == 80 && ((secs == 15 && type == 3) ||
                                     (secs == 9 && type == 4))))
              {
                /* specified tracks, sectors/track not allowed for drive */
                fv->gbfv_spcfunbit = 2;
                return dskerr(0xc);
              }
            }
            fl_setdisktype(pddt->ddt_driveno, type);
          }
        }
        if (fv->gbfv_spcfunbit & 1)
          return S_DONE;

        afentry.type = 2;       /* 512 byte sectors */
        afentry.track = fv->gbfv_cyl;
        afentry.head = fv->gbfv_head;

        for (tracks = fv->gbfv_spcfunbit & 2 ? fv->gbfv_ntracks : 1;
             tracks > 0; tracks--)
        {
          addrfield = (struct thst *)DiskTransferBuffer;

          if (afentry.track > pddt->ddt_ncyl)
            return failure(E_FAILURE);

          for (afentry.sector = 1;
               afentry.sector <= pddt->ddt_bpb.bpb_nsecs; afentry.sector++)
            memcpy(addrfield++, &afentry, sizeof(afentry));

          ret =
              Genblockio(pddt, LBA_FORMAT, afentry.head, afentry.track, 0,
                         pddt->ddt_bpb.bpb_nsecs, DiskTransferBuffer);
          if (ret != 0)
            return dskerr(ret);
        }
        afentry.head++;
        if (afentry.head >= pddt->ddt_bpb.bpb_nheads)
        {
          afentry.head = 0;
          afentry.track++;
        }
      }

      /* fall through to verify */

    case 0x62:                 /* verify track */
      {
        struct gblkfv FAR *fv = rp->r_fv;

        ret = Genblockio(pddt, LBA_VERIFY, fv->gbfv_head, fv->gbfv_cyl, 0,
                         (fv->gbfv_spcfunbit ?
                          fv->gbfv_ntracks * pddt->ddt_defbpb.bpb_nsecs :
                          pddt->ddt_defbpb.bpb_nsecs), DiskTransferBuffer);
        if (ret != 0)
          return dskerr(ret);
        fv->gbfv_spcfunbit = 0; /* success */
      }
      break;
    case 0x46:                 /* set volume serial number */
      {
        struct Gioc_media FAR *gioc = rp->r_gioc;
        struct FS_info *fs;

        ret = getbpb(pddt);
        if (ret != 0)
          return (ret);

        /* return error if media lacks extended BPB with serial # */
        {
          register BYTE extended_BPB_signature = 
            DiskTransferBuffer[(pddt->ddt_bpb.bpb_nfsect != 0 ? 0x26 : 0x42)];
#if defined(PC88VA)
          if ((extended_BPB_signature != 0x29) && (extended_BPB_signature != 0x28))
#else
          if ((extended_BPB_signature != 0x29) || (extended_BPB_signature != 0x28))
#endif
            return failure(E_MEDIA);
        }

        /* otherwise, store serial # in extended BPB */
        fs = (struct FS_info *)&DiskTransferBuffer
            [(pddt->ddt_bpb.bpb_nfsect != 0 ? 0x27 : 0x43)];
        fs->serialno = gioc->ioc_serialno;
        pddt->ddt_serialno = fs->serialno;

        ret = RWzero(pddt, LBA_WRITE);
        if (ret != 0)
          return (dskerr(ret));
      }
      break;
    case 0x47:                 /* set access flag */
      {
        struct Access_info FAR *ai = rp->r_ai;
        pddt->ddt_descflags = (descflags & ~DF_NOACCESS) |
          (ai->AI_Flag ? 0 : DF_NOACCESS);
      }
      break;
    case 0x60:                 /* get device parameters */
      {
        struct gblkio FAR *gblp = rp->r_io;
        bpb *pbpb;

        gblp->gbio_devtype = pddt->ddt_type;
        gblp->gbio_devattrib = descflags & 3;
        /* 360 kb disk in 1.2 MB drive */
        gblp->gbio_media = (pddt->ddt_type == 1) && (pddt->ddt_ncyl == 40);
        gblp->gbio_ncyl = pddt->ddt_ncyl;
        /* use default dpb or current bpb? */
        pbpb =
            (gblp->gbio_spcfunbit & 0x01) ==
            0 ? &pddt->ddt_defbpb : &pddt->ddt_bpb;
#ifdef WITHFAT32
        fmemcpy(&gblp->gbio_bpb, pbpb,
                extended ? sizeof(gblp->gbio_bpb) : BPB_SIZEOF);
#else
        fmemcpy(&gblp->gbio_bpb, pbpb, sizeof(gblp->gbio_bpb));
#endif
        /*gblp->gbio_nsecs = pbpb->bpb_nsector; */
        break;
      }
    case 0x61:                 /* read track - CHS is absolute on disk not relative to start of partition */
      {
        struct gblkrw FAR *rw = rp->r_rw;
        ret = GenblockioAbs(pddt, LBA_READ, rw->gbrw_head, rw->gbrw_cyl,
                         rw->gbrw_sector, rw->gbrw_nsecs, rw->gbrw_buffer);
        if (ret != 0)
          return dskerr(ret);
      }
      break;
    case 0x66:                 /* get volume serial number */
      {
        struct Gioc_media FAR *gioc = rp->r_gioc;

        ret = getbpb(pddt);
        if (ret != 0)
          return (ret);

        /* Note: getbpb() will initialize extended BPB fields with default values */
        gioc->ioc_serialno = pddt->ddt_serialno;
        fmemcpy(gioc->ioc_volume, pddt->ddt_volume, 11);
        fmemcpy(gioc->ioc_fstype, pddt->ddt_fstype, 8);
      }
      break;
    case 0x67:                 /* get access flag */
      {
        struct Access_info FAR *ai = rp->r_ai;
        ai->AI_Flag = descflags & DF_NOACCESS ? 0 : 1;        /* bit 9 */
      }
      break;
    default:
      return failure(E_CMD);
  }
  return S_DONE;
}

STATIC WORD blockio(rqptr rp, ddt * pddt)
{
  ULONG start, size;
  WORD ret;
  UWORD done;

  int action;
  bpb *pbpb;

  switch (rp->r_command)
  {
    case C_INPUT:
      action = LBA_READ;
      break;
    case C_OUTPUT:
      action = LBA_WRITE;
      break;
    case C_OUTVFY:
      action = LBA_WRITE_VERIFY;
      break;
    default:
#if defined(PC88VA)
      rp->r_count = 0;
#endif
      return failure(E_FAILURE);
  }

  if (pddt->ddt_descflags & DF_NOACCESS)      /* drive inaccessible */
#if defined(PC88VA)
  {
    rp->r_count = 0;
#endif
    return failure(E_FAILURE);
#if defined(PC88VA)
  }

#else

#endif
  tmark(pddt);
  start = (rp->r_start != HUGECOUNT ? rp->r_start : rp->r_huge);
  pbpb = hd(pddt->ddt_descflags) ? &pddt->ddt_defbpb : &pddt->ddt_bpb;
  size = (pbpb->bpb_nsize ? pbpb->bpb_nsize : pbpb->bpb_huge);
#if defined(PC88VA)

  if (start >= size || rp->r_count > size - start)
#else

  if (start >= size || start + rp->r_count > size)
#endif
  {
#if defined(PC88VA)
    rp->r_count = 0;
    return failure(E_NOTFND);
#else
    return 0x0408;
#endif
  }
  start += pddt->ddt_offset;

  ret = LBA_Transfer(pddt, action,
                     rp->r_trans,
                     start, rp->r_count, &done);
  rp->r_count = done;

  if (ret != 0)
  {
    return dskerr(ret);
  }
  return S_DONE;
}

STATIC WORD blk_error(rqptr rp, ddt * pddt)
{
  UNREFERENCED_PARAMETER(pddt);

  rp->r_count = 0;
  return failure(E_FAILURE);    /* general failure */
}

STATIC WORD blk_noerr(rqptr rp, ddt * pddt)
{
  UNREFERENCED_PARAMETER(rp);
  UNREFERENCED_PARAMETER(pddt);

  return S_DONE;
}

STATIC WORD dskerr(COUNT code)
{
/*      printf("diskette error:\nhead = %d\ntrack = %d\nsector = %d\ncount = %d\n",
   head, track, sector, count); */
  switch (code & 0x03)
  {
    case 1:                    /* invalid command - general failure */
      if (code & 0x08)
        return S_ERROR | E_NOTRDY;      /* failure(E_NOTRDY); at least on yhe INT25 route,
                                           0x8002 is returned */
      else
        return failure(E_CMD);

    case 2:                    /* address mark not found - general  failure */
      return failure(E_FAILURE);

    case 3:                    /* write protect */
      return failure(E_WRPRT);

    default:
      if (code & 0x80)          /* time-out */
        return failure(E_NOTRDY);
      else if (code & 0x40)     /* seek error */
        return failure(E_SEEK);
      else if (code & 0x10)     /* CRC error */
        return failure(E_CRC);
      else if (code & 0x04)
        return failure(E_NOTFND);
      else
        return failure(E_FAILURE);
  }
}

/*
    translate LBA sectors into CHS addressing
*/

STATIC int LBA_to_CHS(ULONG LBA_address, struct CHS *chs, const ddt * pddt,
    const bpb ** ppbpb)
{
  /* we need the defbpb values since those are taken from the
     BIOS, not from some random boot sector, except when
     we're dealing with a floppy */

  const bpb *pbpb = hd(pddt->ddt_descflags) ? &pddt->ddt_defbpb : &pddt->ddt_bpb;
  unsigned hs = pbpb->bpb_nsecs * pbpb->bpb_nheads;
  unsigned hsrem = (unsigned)(LBA_address % hs);

  LBA_address /= hs;

  if (LBA_address > 1023ul)
  {
#ifdef DEBUG
    printf("LBA-Transfer error : cylinder %lu > 1023\n", LBA_address);
#else
    put_string("LBA-Transfer error : cylinder > 1023\n");
#endif
    return 1;
  }

  chs->Cylinder = (UWORD)LBA_address;
  chs->Head = hsrem / pbpb->bpb_nsecs;
  chs->Sector =  hsrem % pbpb->bpb_nsecs + 1;
  *ppbpb = pbpb;
  return 0;
}

  /* Test for 64K boundary crossing and return count small        */
  /* enough not to exceed the threshold.                          */

STATIC unsigned DMA_max_transfer(void FAR * buffer, unsigned count)
{
  unsigned dma_off = (UWORD)((FP_SEG(buffer) << 4) + FP_OFF(buffer));
  unsigned sectors_to_dma_boundary = (dma_off == 0 ?
    0xffff / maxsecsize :
    (UWORD)(-dma_off) / maxsecsize);

  return min(count, sectors_to_dma_boundary);
}

/*
    int LBA_Transfer(
        ddt *pddt,                          physical characteristics of drive
        UWORD mode,                         LBA_READ/WRITE/WRITE_VERIFY/VERIFY
        VOID FAR *buffer,                   user buffer
        ULONG LBA_address,                  absolute sector address
        unsigned totaltodo,                 number of sectors to transfer
        UWORD *transferred                  sectors actually transferred

    Read/Write/Write+verify some sectors, using LBA addressing.
    
    
    This function handles all the minor details, including:
    
        retry in case of errors
        
        crossing the 64K DMA boundary
        
        translation to CHS addressing if necessary
        
        crossing track boundaries (necessary for some BIOSes
    
        High memory doesn't work very well, use internal buffer
        
        write with verify details for LBA
    
*/

STATIC int LBA_Transfer(ddt * pddt, UWORD mode, VOID FAR * buffer,
                 ULONG LBA_address, unsigned totaltodo,
                 UWORD * transferred)
{
  static struct _bios_LBA_address_packet dap = {
    16, 0, 0, 0, 0, 0, 0
  };

  unsigned count;
  unsigned error_code = 0;
  struct CHS chs;
  void FAR *transfer_address;
  unsigned char driveno = pddt->ddt_driveno;

  int num_retries;
#if defined(PC88VA)
  unsigned retry_limit;

#else

#endif
	UWORD bytes_sector = pddt->ddt_bpb.bpb_nbyte;   /* bytes per sector, usually 512 */
  *transferred = 0;
#if defined(PC88VA)
  retry_limit = N_RETRY;
  
  /* only low-level format floppies for now ! */
#else
  
  /* only low-level format floppies for now ! */
#endif
  if (mode == LBA_FORMAT && hd(pddt->ddt_descflags))
    return 0;

  /* optionally change from A: to B: or back */
  play_dj(pddt);

#if !defined(PC88VA)
  /* The INT 1Eh diskette parameter table belongs to the IBM-PC BIOS ABI.
     The VA adapter supplies its geometry in each native request and must
     neither write through that vector nor reset the native BIOS here. */
  if (!hd(pddt->ddt_descflags))
  {
    UBYTE FAR  *int1e_ptr = (UBYTE FAR *)getvec(0x1e);
    unsigned char nsecs = (unsigned char)(pddt->ddt_bpb.bpb_nsecs);

    if (int1e_ptr[4] != nsecs)
    {
      int1e_ptr[4] = nsecs;
      fl_reset(driveno);
    }
  }
#endif
        
/*    
    if (LBA_address+totaltodo > pddt->total_sectors)
        {
        printf("LBA-Transfer error : address overflow = %lu > %lu max\n",LBA_address+totaltodo,driveParam->total_sectors);
        return 1;
        }
*/

  buffer = adjust_far(buffer);
  for (; totaltodo != 0;)
  {
    /* avoid overflowing 64K DMA boundary */
    count = DMA_max_transfer(buffer, totaltodo);
#if defined(PC88VA)

#if defined(PC88VA)
    /* The legacy fl_* ABI has no completed-sector result.  Dispatching one
       VA sector per common write call keeps r_count exact on an error and
       prevents the common retry loop from replaying a dirty caller buffer on
       a newly inserted medium.  The resident VA core still owns its bounded
       firmware retries. */
    if (((mode & 0xff00) == LBA_WRITE || mode == LBA_VERIFY) && count > 1)
      count = 1;
    if ((mode & 0xfffd) == LBA_WRITE)
      retry_limit = 1;
#endif

    if (FP_SEG(buffer) >= 0xa000 || count == 0
#if defined(PC88VA)
        || mode == LBA_VERIFY
#endif
       )
#else

    if (FP_SEG(buffer) >= 0xa000 || count == 0)
#endif
    {
      transfer_address = DiskTransferBuffer;
      count = 1;

      if ((mode & 0xff00) == (LBA_WRITE & 0xff00))
      {
        fmemcpy(DiskTransferBuffer, buffer, bytes_sector);
      }
    }
    else
    {
      transfer_address = buffer;
    }
#if defined(PC88VA)

    for (num_retries = 0; num_retries < retry_limit; num_retries++)
#else

    for (num_retries = 0; num_retries < N_RETRY; num_retries++)
#endif
    {
      if ((pddt->ddt_descflags & DF_LBA) && mode != LBA_FORMAT)
      {
        dap.number_of_blocks = count;

        dap.buffer_address = transfer_address;

        dap.block_address_high = 0;     /* clear high part */
        dap.block_address = LBA_address;        /* clear high part */

        /* Load the registers and call the interrupt. */

        if ((pddt->ddt_descflags & DF_WRTVERIFY) || mode != LBA_WRITE_VERIFY)
        {
          error_code = fl_lba_ReadWrite(driveno, mode, &dap);
        }
        else
        {
          /* verify requested, but not supported */
          error_code =
              fl_lba_ReadWrite(driveno, LBA_WRITE, &dap);

          if (error_code == 0)
          {
            error_code =
                fl_lba_ReadWrite(driveno, LBA_VERIFY, &dap);
          }
        }
      }
      else
      {                         /* transfer data, using old bios functions */
        const bpb *pbpb;
        if (LBA_to_CHS(LBA_address, &chs, pddt, &pbpb))
          return 1;

        /* avoid overflow at end of track */

        if (chs.Sector + count > (unsigned)pbpb->bpb_nsecs + 1)
        {
          count = pbpb->bpb_nsecs + 1 - chs.Sector;
        }

#if defined(PC88VA)
        /* For the defined LBA modes, bit 8 marks writes; FORMAT is separate. */
        error_code = (mode == LBA_FORMAT ? fl_format :
                      (mode & 0x0100) ? fl_write : fl_read) (driveno,
                                                          chs.Head,
                                                          chs.Cylinder,
                                                          chs.Sector,
                                                          count,
                                                          transfer_address);
#else
        error_code = (mode == LBA_READ ? fl_read :
                      mode == LBA_VERIFY ? fl_verify :
                      mode ==
                      LBA_FORMAT ? fl_format : fl_write) (driveno,
                                                          chs.Head,
                                                          chs.Cylinder,
                                                          chs.Sector,
                                                          count,
                                                          transfer_address);
#endif

        if (error_code == 0 && mode == LBA_WRITE_VERIFY)
        {
          error_code = fl_verify(driveno, chs.Head, chs.Cylinder,
                                 chs.Sector, count, transfer_address);
        }
      }
      if (error_code == 0)
        break;

#if !defined(PC88VA)
      /* VA transfer recovery belongs to its resident adapter. Do not add
         a common BIOS reset after that adapter returns a final error. */
      fl_reset(driveno);
#endif

    }                           /* end of retries */

    if (error_code)
    {
      return error_code;
    }

    /* copy to user buffer if nesessary */
    if (transfer_address == DiskTransferBuffer &&
#if defined(PC88VA)
        mode == LBA_READ)
#else
        (mode & 0xff00) == (LBA_READ & 0xff00))
#endif
    {
      fmemcpy(buffer, DiskTransferBuffer, bytes_sector);
    }

    *transferred += count;
    LBA_address += count;
    totaltodo -= count;

#if defined(PC88VA)
    if (mode != LBA_VERIFY)
#endif
      buffer = adjust_far((char FAR *)buffer + count * bytes_sector);
  }

  return (error_code);
}

/*
 * Revision 1.17  2001/05/13           tomehlert
 * Added full support for LBA hard drives
 * initcode moved (mostly) to initdisk.c
 * lower interface partly redesigned
 */
