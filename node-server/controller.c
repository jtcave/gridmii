// controller.c - logic to process traffic from MQTT and from job subprocesses

#include <unistd.h>
#include <stdio.h>
#include <string.h>

#include "gm-node.h"

void on_stdout_mqtt(struct job *jobspec, int source_fd, char *buffer, size_t readsize) {
    if (readsize > 0) {
        // construct destination topic for write message
        char topic_buf[512];
        const char *topic_leaf = (source_fd == jobspec->job_stderr) ? "stderr" : "stdout";
        snprintf(topic_buf, sizeof(topic_buf), "job/%d/%s", jobspec->job_id, topic_leaf);

        // publish to the topic with the buffer contents as payload
        mosquitto_publish(gm_mosq, NULL, topic_buf, readsize, buffer, 2, false);

        // update write count and check write quota
        jobspec->stdout_sent += readsize;
#ifdef STDOUT_LIMIT
        if (jobspec->stdout_sent > STDOUT_LIMIT) {
            // Close the job's stdout handles.
            // This will cause SIGPIPE in the job, which will probably kill it.
            fprintf(stderr, "closing outputs for job %d: sent %ld limit %d\n",
                jobspec->job_id, (unsigned long)jobspec->stdout_sent, STDOUT_LIMIT);
            job_output_close(jobspec->job_id);
        }
#endif // STDOUT_LIMIT
    }
}

void gm_publish_job_status(int jid, const char *verb, const char *payload) {
    char topic_buf[512];
    snprintf(topic_buf, sizeof(topic_buf), "job/%d/%s", jid, verb);
    mosquitto_publish(gm_mosq, NULL, topic_buf, strlen(payload), payload, 2, false);
}

void gm_publish_node_announce(const char *text) {
    char payload[512];
    snprintf(payload, sizeof(payload), "%s: %s", gm_config.node_name, text);
    mosquitto_publish(gm_mosq, NULL, "node/announce", strlen(payload), payload, 2, false);
    fprintf(stderr, "announcement: %s\n", payload);
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

#define N_TOPIC_HANDLERS 7
#define MAX_TOPIC_TEMPLATE 256
static char topic_patterns[N_TOPIC_HANDLERS][MAX_TOPIC_TEMPLATE];
static bool topic_patterns_initialized = false;
enum request_topics {
    TOPIC_SUBMIT_JOB = 0,
    TOPIC_STDIN_JOB = 1,
    TOPIC_EOF_JOB = 2,
    TOPIC_SIGNAL_JOB = 3,
    TOPIC_SCRAM = 4,
    TOPIC_EXIT = 5,
    TOPIC_RELOAD = 6
};

// Prepare topic patterns
void init_topic_templates() {
    if (topic_patterns_initialized) return;

    const char *node_name = gm_config.node_name;
    snprintf(topic_patterns[TOPIC_SUBMIT_JOB], MAX_TOPIC_TEMPLATE,
        "%s/submit/%%u", node_name);
    snprintf(topic_patterns[TOPIC_STDIN_JOB], MAX_TOPIC_TEMPLATE,
        "%s/stdin/%%u", node_name);
    snprintf(topic_patterns[TOPIC_EOF_JOB], MAX_TOPIC_TEMPLATE,
        "%s/eof/%%u", node_name);
    snprintf(topic_patterns[TOPIC_SIGNAL_JOB], MAX_TOPIC_TEMPLATE,
        "%s/signal/%%u/%%d", node_name);
    snprintf(topic_patterns[TOPIC_SCRAM], MAX_TOPIC_TEMPLATE,
        "%s/scram", node_name);
    snprintf(topic_patterns[TOPIC_EXIT], MAX_TOPIC_TEMPLATE,
        "%s/exit", node_name);
    snprintf(topic_patterns[TOPIC_RELOAD], MAX_TOPIC_TEMPLATE,
        "%s/reload", node_name);

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

    // start matching topic patterns
    jid_t jid = 0;
    int signum = 0;

    // submit job endpoint

    if (sscanf(message->topic, topic_patterns[TOPIC_SUBMIT_JOB], &jid) > 0) {
        if (jid == 0) {
            // sender doesn't care what the JID is, so make one up
            static jid_t jid_counter = 777;
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

    // stdin endpoint
    else if (sscanf(message->topic, topic_patterns[TOPIC_STDIN_JOB], &jid) > 0) {
        int rv = job_stdin_write(jid, message->payload, message->payloadlen);
        // TODO: report stdin write error on a more appropriate channel
        if (rv != 0) {
            char err_buf[128];
            snprintf(err_buf, sizeof(err_buf), "error writing to job stdin: %s", strerror(rv));
            gm_publish_node_announce(err_buf);
        }
    }

    // stdin EOF endpoint
    else if (sscanf(message->topic, topic_patterns[TOPIC_EOF_JOB], &jid) > 0) {
        int rv = job_stdin_eof(jid);
        // TODO: report stdin errors on a more appropriate channel
        if (rv != 0) {
            char err_buf[128];
            snprintf(err_buf, sizeof(err_buf), "error closing job stdin: %s", strerror(rv));
            gm_publish_node_announce(err_buf);
        }
    }

    // signal endpoint
    else if (sscanf(message->topic, topic_patterns[TOPIC_SIGNAL_JOB], &jid, &signum) > 0) {
        int rv = job_signal(jid, signum);
        // TODO: report job manip errors on a more appropriate channel
        if (rv != 0) {
            char err_buf[128];
            snprintf(err_buf, sizeof(err_buf), "error signalling job: %s", strerror(rv));
            gm_publish_node_announce(err_buf);
        }
    }

    // scram endpoint
    else if (strcmp(message->topic, topic_patterns[TOPIC_SCRAM]) == 0) {
        job_scram();
    }

    // reload endpoint
    else if (strcmp(message->topic, topic_patterns[TOPIC_RELOAD]) == 0) {
        gm_reload();
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
