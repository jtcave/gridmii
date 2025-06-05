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

void gm_publish_job_status(int jid, const char *verb, const char *payload) {
    char topic_buf[512];
    snprintf(topic_buf, sizeof(topic_buf), "job/%d/%s", jid, verb);
    mosquitto_publish(gm_mosq, NULL, topic_buf, strlen(payload), payload, 2, false);
}

// topic router

/* Adding a new node topic requires:
 *  - extending the topic_patterns array
 *  - making a new entry in the enum for the topic
 *  - adding dispatch and handling code to gm_route_message()
 *  - subscribing to the topic in mqtt.c
 * 
 * Since we don't expect to handle that many topics, this should be an
 * acceptable level of nonsense.
 */

#define N_TOPIC_HANDLERS 3
#define MAX_TOPIC_TEMPLATE 256
static char topic_patterns[N_TOPIC_HANDLERS][MAX_TOPIC_TEMPLATE];
static bool topic_patterns_initialized = false;
enum request_topics {
    TOPIC_SUBMIT_JOB = 0,
    TOPIC_SCRAM = 1,
    TOPIC_EXIT = 2
};

// Prepare topic patterns
void init_topic_templates() {
    if (topic_patterns_initialized) return;

    const char *node_name = gm_config.node_name;
    snprintf(topic_patterns[TOPIC_SUBMIT_JOB], MAX_TOPIC_TEMPLATE,
        "%s/submit/%%ud", node_name);
    snprintf(topic_patterns[TOPIC_SCRAM], MAX_TOPIC_TEMPLATE,
        "%s/scram", node_name);
    snprintf(topic_patterns[TOPIC_EXIT], MAX_TOPIC_TEMPLATE,
        "%s/exit", node_name);
    topic_patterns_initialized = true;
}

void gm_route_message(const struct mosquitto_message *message) {
    // set up patterns
    init_topic_templates();

    // slurp payload out of message
    char payload[JOB_SCRIPT_LIMIT+1] = {0};
    memset(payload, 0, JOB_SCRIPT_LIMIT+1);
    int payload_size = (message->payloadlen >= JOB_SCRIPT_LIMIT)
                            ? JOB_SCRIPT_LIMIT - 1
                            : message->payloadlen;
    memcpy(payload, message->payload, payload_size);
    
    printf("message %d @ %s: %s\n", message->mid, message->topic, payload);

    // start matching topic patterns:

    // submit job endpoint
    uint32_t jid;
    if (sscanf(message->topic, topic_patterns[TOPIC_SUBMIT_JOB], &jid) > 0) {
        if (jid == 0) {
            // sender doesn't care what the JID is, so make one up
            static uint32_t jid_counter = 777;
            jid = jid_counter++;
        }
        int rv = submit_job(jid, on_stdout_mqtt, payload);
        if (rv == 0) {
            gm_publish_job_status(jid, "startup", "");
        }
        else {
            fprintf(stderr, "couldn't start job: %s\n", strerror(rv));
            gm_publish_job_status(jid, "reject", strerror(rv));
        }
    }

    // scram endpoint
    else if (strcmp(message->topic, topic_patterns[TOPIC_SCRAM]) == 0) {
        job_scram();
    }

    // exit endpoint
    else if (strcmp(message->topic, topic_patterns[TOPIC_EXIT]) == 0) {
        gm_shutdown();
    }

    // Next come the broadcast topics
    // broadcast ping
    else if (strcmp(message->topic, "grid/ping") == 0) {
        gm_announce();
    }

    // broadcast scram
    else if (strcmp(message->topic, "grid/scram") == 0) {
        job_scram();
    }
    
    // unrecognized topic, complain
    else {
        fprintf(stderr, "don't understand topic '%s'\n", message->topic);
    }
}