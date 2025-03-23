// controller.c - logic to process traffic from MQTT and from job subprocesses

#include <unistd.h>
#include <stdio.h>
#include <string.h>

#include "gm-node.h"

void transfer_to_stdout(struct job *jobspec, int source_fd, char *buffer, size_t readsize) {
    if (source_fd == jobspec->job_stderr) {
        // stderr to stderr
        write(STDERR_FILENO, buffer, readsize);
    }
    else {
        write(STDOUT_FILENO, buffer, readsize);
    }
}

void on_stdout_mqtt(struct job *jobspec, int source_fd, char *buffer, size_t readsize) {
    // TODO: MQTT topic should contain job id and output channel
    //       for example: `job/42/stdout`
    if (readsize > 0) {
        const char *topic = (source_fd == jobspec->job_stderr) ? "stderr" : "stdout";
        mosquitto_publish(gm_mosq, NULL, topic, readsize, buffer, 0, false);
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
    // TODO: this needs some sort of error handling that goes to MQTT
    else {
        static uint32_t jid = 2;
        int rv = submit_job(jid++, on_stdout_mqtt, payload);
        if (rv != 0) {
            fprintf(stderr, "couldn't start job: %s\n", strerror(rv));
        }
    }
}