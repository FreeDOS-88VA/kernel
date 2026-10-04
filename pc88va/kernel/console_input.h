/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef PC88VA_CONSOLE_INPUT_H
#define PC88VA_CONSOLE_INPUT_H

/* Early ABI v1: DS=CS, M10 ready, IF=DF=TF=0; no reentrancy.
 * Pass only &pc88va_m11_character. No driver echo, queue or typematic.
 * The first poll adopts held keys. Poll through each release and press.
 * A nonzero result leaves the output word unchanged. */
#define PC88VA_INPUT_CHARACTER 0
#define PC88VA_INPUT_NONE 1
#define PC88VA_INPUT_UNSUPPORTED 2
#define PC88VA_INPUT_INVALID (-1)
extern unsigned short pc88va_m11_character;
int pc88va_console_getc(unsigned short *character);

#endif
