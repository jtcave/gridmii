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
#include <signal.h>

#include <mosquitto.h>

#include "gridmii.h"

void transfer_to_stdout(struct job *jobspec, int source_fd, char *buffer, size_t readsize) {
    if (source_fd == jobspec->job_stderr) {
        // stderr to stderr
        write(STDERR_FILENO, buffer, readsize);
    }
    else {
        write(STDOUT_FILENO, buffer, readsize);
    }
}

void exit_cleanup(void) {
    // clean up job scripts
    // TODO: this is a horrendous hack
    // at the very least, it should be done when there are no running jobs anymore
    // not at exit
    system("rm " TEMP_PREFIX "*");
}

// TODO: actually wire this up
void sigint_cleanup(int signum) {
    gm_shutdown();
}

int main(int argc, char *const *argv) {
    setbuf(stdout, NULL);
    atexit(exit_cleanup);

    init_job_table();

    printf("starting mqtt...");
    gm_init_mqtt();
    gm_connect_mqtt();

    for(;;) {
        gm_do_events();
    }
}