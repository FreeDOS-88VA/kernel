#include <errno.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <utime.h>

static int set_reproducible_mtime(const char *path)
{
  const char *value = getenv("SOURCE_DATE_EPOCH");
  const char *cursor;
  char *end;
  uintmax_t parsed;
  time_t timestamp;
  struct utimbuf times;

  if (value == NULL)
  {
    return 0;
  }
  if (value[0] == '\0' || value[0] == '-')
  {
    fprintf(stderr, "Invalid SOURCE_DATE_EPOCH: %s\n", value);
    return 1;
  }
  for (cursor = value; *cursor != '\0'; cursor++)
  {
    if (*cursor < '0' || *cursor > '9')
    {
      fprintf(stderr, "Invalid SOURCE_DATE_EPOCH: %s\n", value);
      return 1;
    }
  }

  errno = 0;
  end = NULL;
  parsed = strtoumax(value, &end, 10);
  if (errno != 0 || end == value || *end != '\0')
  {
    fprintf(stderr, "Invalid SOURCE_DATE_EPOCH: %s\n", value);
    return 1;
  }
  timestamp = (time_t)parsed;
  if (timestamp < (time_t)0 || (uintmax_t)timestamp != parsed)
  {
    fprintf(stderr, "SOURCE_DATE_EPOCH is outside the host time_t range: %s\n", value);
    return 1;
  }

  times.actime = timestamp;
  times.modtime = timestamp;
  if (utime(path, &times) != 0)
  {
    fprintf(stderr, "Cannot set reproducible mtime for %s: %s\n", path, strerror(errno));
    return 1;
  }
  return 0;
}

int main(int argc, char **argv)
{
  FILE *in, *out;
  int col;
  int c;

  if (argc < 4)
  {
    fprintf(stderr,
            "Usage: bin2c <output bin file> <output h file> <array name>\n");
    return 1;
  }

  if ((in = fopen(argv[1], "rb")) == NULL)
  {
    fprintf(stderr, "Cannot open input file (%s).\n", argv[1]);
    return 1;
  }

  if ((out = fopen(argv[2], "wt")) == NULL)
  {
    fprintf(stderr, "Cannot open output file (%s).\n", argv[2]);
    return 1;
  }

  col = 0;

  fprintf(out, "unsigned char %s[] = {\n  ", argv[3]);

  while ((c = fgetc(in)) != EOF)
  {
    if (col)
    {
      fprintf(out, ", ");
    }
    if (col >= 8)
    {
      fprintf(out, "\n  ");
      col = 0;
    }
    fprintf(out, "0x%02X", c);
    col++;
  }

  fprintf(out, "\n};\n");
  fclose(in);
  fclose(out);

  if (set_reproducible_mtime(argv[2]) != 0)
  {
    return 1;
  }

  return 0;
}
