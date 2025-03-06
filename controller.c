// controller.c - logic to process traffic from MQTT and from job subprocesses

#include <unistd.h>
#include <stdio.h>
#include <string.h>

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

void gm_route_message(const struct mosquitto_message *message) {
    // TODO: read topic and dispatch the appropriate function
    static char payload[256];
    memset(payload, '\0', 256);
    int payload_size = (message->payloadlen > 255) ? 255 : message->payloadlen;
    memcpy(payload, message->payload, payload_size);
    printf("message %d @ %s: %s\n", message->mid, message->topic, payload);

    // exit on magic word
    if (strcmp(payload, "exit") == 0) {
        gm_shutdown();
    }

    // otherwise just spawn a process
    // TODO: this should be in a "controller class" module
    //       it also needs some sort of error handling
    else {
        static uint32_t jid = 2;
        int rv = submit_job(jid++, transfer_to_stdout, payload);
        if (rv != 0) {
            fprintf(stderr, "couldn't start job: %s\n", strerror(rv));
        }
    }
}