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
#include <sys/utsname.h>

#include <mosquitto.h>

#include "gm-node.h"

// vscode sucks
#ifndef __USE_POSIX
#define __USE_POSIX
#endif
#include <signal.h>

// global configuration table
struct gm_config_data gm_config;

// flag that suppresses our atexit function in the child process
bool gm_in_child = false;

// get the default client name for mqtt (currently the system hostname)
const char *default_node_name() {
    static char nodebuffer[MOSQ_MQTT_ID_MAX_LENGTH + 1] = {0};
    if (*nodebuffer == '\0') {
        // fill nodebuffer from uname()
        struct utsname the_uname;
        int rv = uname(&the_uname);
        if (rv != 0) {
            err(1, "could not get system uname");
        }
        strncpy(nodebuffer, the_uname.nodename, MOSQ_MQTT_ID_MAX_LENGTH);
    }
    return nodebuffer;
}

// populate gm_config according to the environment
void init_config(int argc, char *const *argv) {
    gm_config.argc = argc;
    gm_config.argv = argv;
    
    char *env_host = getenv("GRID_HOST");
    gm_config.grid_host = (env_host ? env_host : GRID_HOST_DEFAULT);
    
    char *env_port = getenv("GRID_PORT");
    gm_config.grid_port = (env_port ? atoi(env_port) : GRID_PORT_DEFAULT);

    char *env_tls = getenv("GRID_TLS");
    gm_config.use_tls = (env_tls != NULL);

    char *env_grid_username = getenv("GRID_USERNAME");
    gm_config.grid_username = env_grid_username;

    char *env_grid_password = getenv("GRID_PASSWORD");
    gm_config.grid_password = env_grid_password;

    char *env_node_name = getenv("GRID_NODE_NAME");
    gm_config.node_name = (env_node_name ? env_node_name : default_node_name());
    
    char *env_job_cwd = getenv("GRID_JOB_CWD");
    char *env_home = getenv("HOME");
    gm_config.job_cwd = (env_job_cwd ? env_job_cwd :
        (env_home ? env_home :
            "/"));

    // dump the config for debugging
    puts("Your configuration:");
    printf("GRID_HOST=%s\n", gm_config.grid_host);
    printf("GRID_PORT=%d\n", gm_config.grid_port);
    printf("GRID_TLS=%s\n", gm_config.use_tls ? "yes" : "no");
    printf("GRID_USERNAME=%s\n", gm_config.grid_username ? gm_config.grid_username : "(not set)");
    printf("GRID_PASSWORD=%s\n", gm_config.grid_password ? "(set)" : "(not set)");
    printf("NODE_NAME=%s\n", gm_config.node_name);
    printf("GRID_JOB_CWD=%s\n", gm_config.job_cwd);
    puts("");

    // do some sanity checking
    // Because we use "grid/#" topics for broadcast messages, you can't name a node `grid`
    if (strcasecmp("grid", gm_config.node_name) == 0) {
        errx(1, "NODE_NAME can't be 'grid'");
    }
}

void exit_cleanup(void) {
    // Don't do anything if this is one of the child processes
    if (gm_in_child) return;

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

void gm_reload() {
    fprintf(stderr, "gm_reload called\n");
    if (jobs_running()) {
        gm_publish_node_announce("The node server cannot be reloaded because there are active jobs");
    }
    else {
        gm_disconnect();
        fprintf(stderr, "\n");
        execvp(gm_config.argv[0], gm_config.argv);
        err(1, "could not re-execvp node server");
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
    init_config(argc, argv);
    init_job_table();
    gm_init_mqtt();
    gm_connect_mqtt();
    for(;;) {
        gm_do_events();
    }
}
