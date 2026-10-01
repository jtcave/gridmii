// event.c - event queue

#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <pthread.h>
#include <stdatomic.h>

#include "gm-node.h"

static struct deferred_message *events_head = NULL;
static struct deferred_message *events_tail = NULL;
static pthread_mutex_t events_lock = PTHREAD_MUTEX_INITIALIZER;

// Set by gm_request_shutdown() (possibly from a signal handler) and polled
// by gm_service_events(), which runs the actual shutdown in normal thread
// context once it notices the flag.
static atomic_bool shutdown_requested = false;

void gm_request_shutdown(void) {
    atomic_store(&shutdown_requested, true);
}

bool gm_shutdown_pending(void) {
    return atomic_load(&shutdown_requested);
}

// Deallocate a DMQ entry
static void free_deferred_message(struct deferred_message *node) {
    if (node->payload != NULL) {
        free(node->payload);
    }
    free(node);
}

void gm_defer_message(struct mqtt_response_publish *message) {
    int topic_len, payload_len;
    struct deferred_message *node;

    // copy topic
    node = malloc(sizeof(struct deferred_message));
    topic_len = message->topic_name_size;
    if (topic_len > MQTT_ID_MAX_LENGTH) {
        topic_len = MQTT_ID_MAX_LENGTH;
    }
    memset(node->topic, 0, MQTT_ID_MAX_LENGTH + 1);
    memcpy(node->topic, message->topic_name, topic_len);

    // copy payload
    payload_len = node->payload_len = message->application_message_size;
    if (payload_len > 0 && message->application_message != NULL) {
        node->payload = malloc(payload_len);
        memcpy(node->payload, message->application_message, payload_len);
    }
    else {
        node->payload = NULL;
    }

    // enqueue node
    pthread_mutex_lock(&events_lock);
    if (events_head == NULL || events_tail == NULL) {
        events_head = events_tail = node;
    }
    else {
        events_tail->next = node;
        events_tail = node;
    }
    node->next = NULL;
    pthread_mutex_unlock(&events_lock);
}

void gm_service_events(void) {
    if (atomic_load(&shutdown_requested)) {
        fprintf(stderr, "\nshutting down due to SIGINT...\n");
        gm_shutdown();
    }

    for (;;) {
        struct deferred_message *here = NULL;

        // Pop message off the queue
        pthread_mutex_lock(&events_lock);
        if (events_head != NULL) {
            here = events_head;
            events_head = events_head->next;
            if (events_head == NULL) {
                // the queue is now empty, so clear the tail
                events_tail = NULL;
            }
        }
        pthread_mutex_unlock(&events_lock);

        if (here == NULL) break;

        gm_route_message(here);
        free_deferred_message(here);
    }
}
