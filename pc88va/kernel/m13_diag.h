/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef PC88VA_M13_DIAG_H
#define PC88VA_M13_DIAG_H

#define M13_DIAG_PRECONFIG_BEGIN 1
#define M13_DIAG_ARENA_CHECK_OK 2
#define M13_DIAG_POSTCONFIG_BEGIN 3
#define M13_DIAG_BUFFER_ALLOC_BEGIN 4
#define M13_DIAG_BUFFER_CLEAR_DONE 5
#define M13_DIAG_POSTCONFIG_DONE 6

void pc88va_m13_diag_stage(unsigned short stage);
void pc88va_m13_diag_clock(unsigned short stage,
                           unsigned short value1,
                           unsigned short value2,
                           unsigned short value3);
void pc88va_m13_diag_buffers(unsigned short requested,
                             unsigned short limit,
                             unsigned short actual);
void pc88va_m13_diag_shell_exec_begin(unsigned short mode);
void pc88va_m13_diag_shell_exec_attempt(unsigned short attempt,
                                        unsigned short origin,
                                        const unsigned char *path,
                                        unsigned short path_length);
void pc88va_m13_diag_config_mode(unsigned short mode);
void pc88va_m13_diag_exec_param_match(unsigned short match);
void pc88va_m13_diag_exec_service_return(unsigned short ax,
                                         unsigned short flags);
void pc88va_m13_diag_shell_exec_return(int rc);
void pc88va_m13_diag_shell_input_begin(void);
void pc88va_m13_diag_input_service_return(unsigned short ax,
                                          unsigned short flags);
void pc88va_m13_diag_input_wrapper_return(unsigned short rc);
void pc88va_m13_diag_input_bytes(const unsigned char *bytes,
                                 unsigned short length);
void pc88va_m13_diag_input_length_valid(unsigned short valid);
void pc88va_m13_diag_input_rejected(void);
void pc88va_m13_diag_shell_input_end(unsigned short length);
void pc88va_m13_diag_memalloc_failure(unsigned short request,
                                      unsigned short mode,
                                      unsigned short largest,
                                      unsigned short first_mcb,
                                      unsigned short owner_psp);
void pc88va_m13_diag_arena(unsigned short base,
                           unsigned short top,
                           unsigned short kernel_segment,
                           unsigned short ram_kb);
void pc88va_m13_diag_mcb(unsigned short index,
                         unsigned short segment,
                         unsigned short type,
                         unsigned short owner,
                         unsigned short size);

extern unsigned short pc88va_m13_exec_raw_ax;
extern unsigned short pc88va_m13_exec_raw_flags;
extern unsigned short pc88va_m13_input_raw_ax;
extern unsigned short pc88va_m13_input_raw_flags;

#endif
