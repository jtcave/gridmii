// eventloop.c - event loop for gridmii

// TODO: Currently we call poll() multiple times per event loop.
//       This is not good.

#include <mosquitto.h>
#include <poll.h>
#include <errno.h>
#include <err.h>
#include "gridmii.h"

void do_mqtt_events();

void gm_do_events() {
    do_mqtt_events();
    do_job_events();
}

void do_mqtt_events() {
    int fd = mosquitto_socket(gm_mosq);
    if (fd == -1) {
        err(1, "could not get socket from mosquitto object");
    }

    struct pollfd pfd;
    pfd.fd = fd;
    pfd.events = POLLIN;

    // only poll for write if there's something that needs written
    if (mosquitto_want_write(gm_mosq)) {
        pfd.events = POLLIN | POLLOUT;
    }
    else {
        pfd.events = POLLIN;
    }
    int rv = poll(&pfd, 1, 4);
    if (rv == -1) {
        if (errno == EINTR || errno == EAGAIN) {
            // just try again later
            return;
        }
        else {
            err(1, "could not poll()");
        }
    }
    gm_process_mqtt(pfd.revents);
}