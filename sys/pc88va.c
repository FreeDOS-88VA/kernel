/* SPDX-License-Identifier: GPL-2.0-or-later
 * SYS backend for an explicitly prepared, flat PC-88VA FAT12 floppy.
 * Uses DOS only: no PC BIOS, formatter, bootstrap patching or host service.
 */
#include <dos.h>
#include <fcntl.h>
#include <malloc.h>
#include <stdio.h>
#include <string.h>

#define SECTOR 1024
#define TOTAL 1280
#define ROOT_COUNT 192
#define FIRST_DATA 11
#define CLUSTERS (TOTAL - FIRST_DATA)
#define CHUNK 0xf000U
#define MAX_CHUNKS 4
#define ASSETS 9

extern unsigned __cdecl va_absolute(unsigned writing, unsigned sector,
                                    void *buffer);
extern void __interrupt __far va_critical(void);

typedef struct {
  const char *name;
  const char *dosname;
  unsigned long size;
  unsigned segments[MAX_CHUNKS];
  unsigned lengths[MAX_CHUNKS];
  unsigned count;
} asset;

static asset files[ASSETS] = {
  {"LOADER.BIN", "LOADER  BIN"}, {"KERNEL.SYS", "KERNEL  SYS"},
  {"COMMAND.COM", "COMMAND COM"}, {"COUNTRY.SYS", "COUNTRY SYS"},
  {"COMPROBE.COM", "COMPROBECOM"}, {"MZPROBE.EXE", "MZPROBE EXE"},
  {"TYPEA.TXT", "TYPEA   TXT"}, {"TYPEB.TXT", "TYPEB   TXT"},
  {"COMDATA.TXT", "COMDATA TXT"}
};
static unsigned char source_boot[SECTOR], boot[SECTOR], io[SECTOR];
static unsigned char fat[2 * SECTOR], root[6 * SECTOR], owned[CLUSTERS + 2];
static unsigned source_loader, loader_clusters, free_clusters, root_slots;
static unsigned source_loader_size;
static const char *phase = "arguments";
static unsigned dos_error;
static unsigned completed_files;
static int target_selected;

static unsigned word(const unsigned char *p)
{
  return p[0] | ((unsigned)p[1] << 8);
}

static unsigned long dword(const unsigned char *p)
{
  return (unsigned long)word(p) | ((unsigned long)word(p + 2) << 16);
}

static unsigned next_cluster(unsigned n)
{
  unsigned packed = word(fat + n + n / 2);
  return (n & 1) ? packed >> 4 : packed & 0xfff;
}

static int raw(unsigned writing, unsigned sector, void *buffer)
{
  dos_error = va_absolute(writing, sector, buffer);
  return dos_error == 0;
}

static void reset_disk(void)
{
  union REGS in, out;
  memset(&in, 0, sizeof(in));
  in.h.ah = 0x0d;
  intdos(&in, &out);
}

static int geometry(const unsigned char *p)
{
  return word(p + 11) == SECTOR && p[13] == 1 && word(p + 14) == 1 &&
    p[16] == 2 && word(p + 17) == ROOT_COUNT && word(p + 19) == TOTAL &&
    word(p + 22) == 2 && word(p + 24) == 8 && word(p + 26) == 2 &&
    !dword(p + 28) && !dword(p + 32);
}

static unsigned char *entry(const char *name)
{
  unsigned n;
  for (n = 0; n < ROOT_COUNT; ++n) {
    unsigned char *p = root + 32 * n;
    if (!p[0]) break;
    if (p[0] != 0xe5 && !(p[11] & 8) && !memcmp(p, name, 11)) return p;
  }
  return NULL;
}

/* Validate every allocation, not just the files we intend to replace. */
static int volume(void)
{
  unsigned n, i, c, count, labels = 0;
  unsigned long size;
  int end = 0;
  if (!raw(0, 0, boot) || !geometry(boot)) return 0;
  for (n = 0; n < 2; ++n)
    if (!raw(0, 1 + n, fat + SECTOR * n) || !raw(0, 3 + n, io) ||
        memcmp(fat + SECTOR * n, io, SECTOR)) return 0;
  if (next_cluster(0) != (0xf00 | boot[21]) || next_cluster(1) != 0xfff)
    return 0;
  /* There is no allocation beyond the last data cluster, including the
   * unused upper nibble of the final packed FAT12 byte. */
  if (fat[1906] & 0xf0) return 0;
  for (n = 1907; n < sizeof(fat); ++n) if (fat[n]) return 0;
  for (n = 0; n < 6; ++n)
    if (!raw(0, 5 + n, root + SECTOR * n)) return 0;
  memset(owned, 0, sizeof(owned));
  root_slots = 0;
  for (n = 0; n < ROOT_COUNT; ++n) {
    unsigned char *p = root + 32 * n;
    if (!p[0]) end = 1;
    if (end || p[0] == 0xe5) { ++root_slots; continue; }
    if (p[11] & 0xd0 || p[11] == 0x0f || word(p + 20)) return 0;
    c = word(p + 26);
    size = dword(p + 28);
    if (p[11] & 8) {
      if (++labels > 1 || c || size) return 0;
      continue;
    }
    for (i = 0; i < n; ++i)
      if (root[i * 32] != 0xe5 && !memcmp(root + i * 32, p, 11)) return 0;
    if (!size) { if (c) return 0; continue; }
    if (size > (unsigned long)CLUSTERS * SECTOR) return 0;
    count = 0;
    do {
      if (c < 2 || c >= CLUSTERS + 2 || owned[c]) return 0;
      owned[c] = 1;
      c = next_cluster(c);
      ++count;
    } while (c < 0xff8);
    if (count != (size + SECTOR - 1) / SECTOR) return 0;
  }
  free_clusters = 0;
  for (c = 2; c < CLUSTERS + 2; ++c) {
    if (!owned[c]) {
      if (next_cluster(c)) return 0;
      ++free_clusters;
    }
  }
  return 1;
}

static int identify(const char *expected)
{
  char value[34];
  unsigned got, length = strlen(expected);
  int h;
  dos_error = _dos_open("A:\\SYS.ID", O_RDONLY, &h);
  if (dos_error) return 0;
  dos_error = _dos_read(h, value, sizeof(value), &got);
  if (_dos_close(h) || dos_error || got != length + 2) return 0;
  return !memcmp(value, expected, length) && value[length] == '\r' &&
    value[length + 1] == '\n';
}

static void prompt(const char *which, const char *identity)
{
  unsigned got;
  char line[80];
  printf("Insert %s disk %s in A:, then press Enter.\n", which, identity);
  fflush(stdout);
  _dos_read(0, line, sizeof(line), &got);
}

static int loader_layout(int source)
{
  unsigned char *p = entry("LOADER  BIN");
  unsigned first, c, n;
  unsigned long size;
  if (!p || p[11] & 0x1f) return 0;
  first = c = word(p + 26);
  size = dword(p + 28);
  if (!size || size > 65535UL) return 0;
  n = (unsigned)((size + SECTOR - 1) / SECTOR);
  if (source) {
    source_loader = first;
    loader_clusters = n;
    source_loader_size = (unsigned)size;
  } else if (first != source_loader || n != loader_clusters ||
             size != source_loader_size) return 0;
  while (--n) {
    if (next_cluster(c) != c + 1) return 0;
    ++c;
  }
  return next_cluster(c) >= 0xff8;
}

static int cache_source(void)
{
  unsigned f, n, got;
  int h;
  char path[16];
  for (f = 0; f < ASSETS; ++f) {
    unsigned char *p = entry(files[f].dosname);
    unsigned long left;
    if (!p || p[11] & 0x18) return 0;
    left = files[f].size = dword(p + 28);
    if (!left || left > (unsigned long)CHUNK * MAX_CHUNKS) return 0;
    sprintf(path, "A:\\%s", files[f].name);
    dos_error = _dos_open(path, O_RDONLY, &h);
    if (dos_error) return 0;
    while (left) {
      unsigned idx = files[f].count;
      n = left > CHUNK ? CHUNK : (unsigned)left;
      dos_error = _dos_allocmem((n + 15U) / 16, &files[f].segments[idx]);
      if (dos_error) { _dos_close(h); return 0; }
      files[f].lengths[idx] = n;
      ++files[f].count;
      dos_error = _dos_read(h, MK_FP(files[f].segments[idx], 0), n, &got);
      if (dos_error || got != n) { _dos_close(h); return 0; }
      left -= n;
    }
    dos_error = _dos_read(h, io, 1, &got);
    if (_dos_close(h) || dos_error || got) return 0;
  }
  return 1;
}

static int target_preflight(void)
{
  unsigned f, n, needed = 0;
  if (!volume() || memcmp(boot + 11, source_boot + 11, 25) ||
      !loader_layout(0)) return 0;
  if (!memcmp(boot, source_boot, SECTOR)) return 0;
  for (f = 1; f < ASSETS; ++f) {
    if (entry(files[f].dosname)) return 0;
    needed += (unsigned)((files[f].size + SECTOR - 1) / SECTOR);
  }
  if (free_clusters < needed || root_slots < ASSETS) return 0;
  for (n = 0; n < loader_clusters; ++n) {
    unsigned i;
    if (!raw(0, FIRST_DATA + source_loader - 2 + n, io)) return 0;
    for (i = 0; i < SECTOR; ++i) if (io[i]) return 0;
  }
  return 1;
}

static int transfer_file(unsigned f)
{
  int h;
  unsigned n, got, offset, amount;
  char path[16];
  sprintf(path, "A:\\%s", files[f].name);
  /* Keep the reserved loader allocation: never truncate or recreate it. */
  dos_error = f ? _dos_creatnew(path, _A_NORMAL, &h) :
    _dos_open(path, O_WRONLY, &h);
  if (dos_error) return 0;
  for (n = 0; n < files[f].count; ++n) {
    dos_error = _dos_write(h, MK_FP(files[f].segments[n], 0),
                           files[f].lengths[n], &got);
    if (dos_error || got != files[f].lengths[n]) {
      _dos_close(h); return 0;
    }
  }
  dos_error = _dos_commit(h);
  if (_dos_close(h) || dos_error) return 0;
  dos_error = _dos_open(path, O_RDONLY, &h);
  if (dos_error) return 0;
  for (n = 0; n < files[f].count; ++n) {
    offset = 0;
    while (offset < files[f].lengths[n]) {
      amount = files[f].lengths[n] - offset;
      if (amount > SECTOR) amount = SECTOR;
      dos_error = _dos_read(h, io, amount, &got);
      if (dos_error || got != amount ||
          _fmemcmp(io, MK_FP(files[f].segments[n], offset), amount)) {
        _dos_close(h); return 0;
      }
      offset += amount;
    }
  }
  dos_error = _dos_read(h, io, 1, &got);
  if (_dos_close(h) || dos_error || got) return 0;
  ++completed_files;
  return 1;
}

static void release_cache(void)
{
  unsigned f, n;
  for (f = 0; f < ASSETS; ++f)
    for (n = 0; n < files[f].count; ++n)
      _dos_freemem(files[f].segments[n]);
}

int main(int argc, char **argv)
{
  unsigned f;
  int good = 0;
  void (__interrupt __far *old24)(void);
  if (argc != 4 || strcmp(argv[1], "A:") || !argv[2][0] || !argv[3][0] ||
      strlen(argv[2]) > 30 || strlen(argv[3]) > 30 || !strcmp(argv[2], argv[3])) {
    puts("SYSVA A: source-token target-token (distinct SYS.ID tokens)");
    return 1;
  }
  old24 = _dos_getvect(0x24);
  _dos_setvect(0x24, va_critical);
  phase = "source identity/volume";
  if (!identify(argv[2]) || !volume() || !loader_layout(1)) goto done;
  memcpy(source_boot, boot, SECTOR);
  phase = "source cache";
  _nheapshrink();
  if (!cache_source()) goto done;
  reset_disk();
  target_selected = 1;
  prompt("target", argv[3]);
  phase = "target identity";
  if (!identify(argv[3])) goto done;
  phase = "target preflight";
  if (!target_preflight()) goto done;
  phase = "file transfer/readback";
  for (f = 0; f < ASSETS; ++f)
    if (!transfer_file(f)) goto done;
  reset_disk();
  phase = "post-transfer filesystem";
  if (!volume() || !loader_layout(0) || !identify(argv[3])) goto done;
  /* The preserved BPB/extended identity is not executable bootstrap data.
   * The loader extent was checked against the unmodified source stage one.
   */
  memcpy(source_boot + 11, boot + 11, 51);
  phase = "boot record write/readback";
  if (!raw(1, 0, source_boot) || !raw(0, 0, io) ||
      memcmp(source_boot, io, SECTOR)) goto done;
  reset_disk();
  good = 1;
done:
  if (good) puts("SYSVA transfer complete; boot and verify target separately.");
  else printf("SYSVA failed: %s; error=%u; completed-files=%u.\n",
              phase, dos_error, completed_files);
  if (target_selected) {
    reset_disk();
    do { prompt("source", argv[2]); } while (!identify(argv[2]));
  }
  release_cache();
  _dos_setvect(0x24, old24);
  return good ? 0 : 1;
}
