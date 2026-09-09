// SPDX-License-Identifier: BSD-2-Clause

// error handling routines that work in a signal handler context

#include <unistd.h>
#include <limits.h>
#include <string.h>
#include <errno.h>

// Are we IP32/LP64 or ILP64?
#if INT_MIN >= -2147483648
#define NUMSTR_BUFFER_SIZE 12 
#else // 128-bit ints aren't real and can't hurt you
#define NUMSTR_BUFFER_SIZE 21 // "-9223372036854775808\0"
#endif

int numstr(char *buffer, int value) {
    unsigned int uvalue;
    int is_negative = 0;
    int i = 0;
    int j;
    char tmp;
    int len;

    if (value < 0) {
        is_negative = 1;
        uvalue = (unsigned int)(-(value + 1)) + 1u; /* avoids overflow for INT_MIN */
    } else {
        uvalue = (unsigned int)value;
    }

    if (uvalue == 0) {
        buffer[i++] = '0';
    } else {
        while (uvalue > 0) {
            buffer[i++] = (char)('0' + (uvalue % 10));
            uvalue /= 10;
        }
    }

    if (is_negative) {
        buffer[i++] = '-';
    }

    len = i;

    for (j = 0; j < len / 2; j++) {
        tmp = buffer[j];
        buffer[j] = buffer[len - 1 - j];
        buffer[len - 1 - j] = tmp;
    }

    buffer[len] = '\0';

    return len;
}


void errtools_die(int exit_code, const char *message) {
    char cvt[NUMSTR_BUFFER_SIZE];
    numstr(cvt, errno);
    write(STDERR_FILENO, message, strlen(message));
    write(STDERR_FILENO, ": errno ", 8);
    write(STDERR_FILENO, cvt, strlen(cvt));
    write(STDERR_FILENO, "\n", 1);
    _exit(exit_code);
}