#include <spawn.h>
#include <unistd.h>
#include <poll.h>
#include <stdlib.h>
#include <err.h>
#include <stdio.h>
#include <stdbool.h>
#include <sys/errno.h>
#include <sys/wait.h>
#include <poll.h>
#include <string.h>
#include <fcntl.h>

#include <mosquitto.h>

#include "gm-node.h"

// vscode sucks
#ifndef __USE_POSIX
#define __USE_POSIX
#endif
#include <signal.h>

void exit_cleanup(void) {
    // clean up job scripts
    // TODO: this is a horrendous hack
    // at the very least, it should be done when a job exits and no jobs
    // remain, not at exit
    puts("rm -f " TEMP_PREFIX "*");     // to remind the world of my sins
    system("rm -f " TEMP_PREFIX "*");
}

// TODO: actually wire this up
void sigint_cleanup(int signum) {
    if (signum == SIGINT) {
        fprintf(stderr, "\nshutting down due to SIGINT...\n");
        gm_shutdown();
    }
    else {
        fprintf(stderr, "signal handler called on unexpected signal %d\n", signum);
        abort();
    }
}

int main(int argc, char *const *argv) {
    // install exit handler
    atexit(exit_cleanup);

    // install SIGINT handler (which ends up calling the exit handler)
    struct sigaction sa;
    sa.sa_handler = sigint_cleanup;
    sigset_t sa_set;
    sigemptyset(&sa_set);
    sa.sa_mask = sa_set;
    sa.sa_flags = 0;
    if (sigaction(SIGINT, &sa, NULL) != 0) {
        err(1, "could not set signal handler");
    }

    // start up the subsystems and do an event loop
    init_job_table();
    gm_init_mqtt();
    gm_connect_mqtt();
    for(;;) {
        gm_do_events();
    }
}