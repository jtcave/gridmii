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
    if (readsize > 0) {
        // figure out the appropriate topic
        char topic_buf[512];
        const char *topic_leaf = (source_fd == jobspec->job_stderr) ? "stderr" : "stdout";
        snprintf(topic_buf, sizeof(topic_buf), "job/%d/%s", jobspec->job_id, topic_leaf);
        // publish the contents of the buffer to the topic
        mosquitto_publish(gm_mosq, NULL, topic_buf, readsize, buffer, 2, false);
    }
}

void publish_job_response(int jid, const char *verb, const char *payload) {
    char topic_buf[512];
    snprintf(topic_buf, sizeof(topic_buf), "job/%d/%s", jid, verb);
    mosquitto_publish(gm_mosq, NULL, topic_buf, strlen(payload), payload, 2, true);
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

    // otherwise just spawn a process and publish the response message
    else {
        // TODO: extract jid from topic instead of static counter
        static uint32_t jid = 0;
        int rv = submit_job(++jid, on_stdout_mqtt, payload);
        if (rv == 0) {
            publish_job_response(jid, "startup", "");
        }
        else {
            fprintf(stderr, "couldn't start job: %s\n", strerror(rv));
            publish_job_response(jid, "reject", strerror(rv));
        }
    }
}