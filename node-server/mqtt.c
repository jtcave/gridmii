// mqtt.c - gridmii mqtt routines

#include <stdlib.h>
#include <string.h>
#include <err.h>
#include <errno.h>
#include <sys/utsname.h>
#include <poll.h>
#include <unistd.h>

#include <stdio.h>

#include <mosquitto.h>

#include "gm-node.h"

// global mosquitto object
struct mosquitto *gm_mosq = NULL;

void subscribe_topics(void);

bool mqtt_initialized(void);
void assert_mqtt_initialized(void);
void attempt_reconnect(void);


void has_connected(struct mosquitto *mosq, void *obj, int rc);
void has_published(struct mosquitto *mosq, void *obj, int mid);
void has_message(struct mosquitto *mosq, void *obj, const struct mosquitto_message *message);
void has_subscribed(struct mosquitto *mosq, void *obj, int mid, int qos_count, const int *granted_qos);
void has_disconnected(struct mosquitto *mosq, void *obj, int reason);

// returhs false if MQTT hasn't been initialized - that is, if `gm_mosq` is still NULL;
bool mqtt_initialized() {
    return gm_mosq != NULL;
}

// sanity check for initialized MQTT
void assert_mqtt_initialized(void) {
    if (!mqtt_initialized()) {
        errx(1, "internal error - MQTT not initialized");
    }
}

struct mosquitto *gm_init_mqtt(void) {
    int rv;

    // get the MQTT client ID
    const char *client_name = gm_config.node_name;

    // set up library
    if (mosquitto_lib_init() != MOSQ_ERR_SUCCESS) {
        errx(1, "could not initialize mosquitto library");
    }
    // set up mosquitto struct
    // We want to clear messages and subscriptions on disconnect, because we
    // don't want a torrent of jobs coming in from users who submitted them
    // without knowing the node was down. We also want to start with a clean
    // slate with subscriptions. Hence, set clean_session.
    gm_mosq = mosquitto_new(client_name, true, NULL);
    if (gm_mosq == NULL) {
        err(1, "could not create mosquitto client object");
    }

    // wire up callbacks
    mosquitto_connect_callback_set(gm_mosq, has_connected);
    mosquitto_publish_callback_set(gm_mosq, has_published);
    mosquitto_subscribe_callback_set(gm_mosq, has_subscribed);
    mosquitto_message_callback_set(gm_mosq, has_message);
    mosquitto_disconnect_callback_set(gm_mosq, has_disconnected);

    
    // declare last will of client
    // TODO: currently it just writes the client name to the `disconnect` topic - is that ideal? 
    rv = mosquitto_will_set(gm_mosq, "node/disconnect", strlen(client_name), client_name, 1, false);
    if (rv != MOSQ_ERR_SUCCESS) {
        errx(1, "could not set last will, mosq_err_t = %d (%s)", rv, mosquitto_strerror(rv));
    }

    // TODO: let user specify TLS cert name
    if (gm_config.use_tls) {
        rv = mosquitto_tls_set(gm_mosq, "gridmii.crt", NULL, NULL, NULL, NULL);
        if (rv != MOSQ_ERR_SUCCESS) {
            errx(1, "could not set up TLS, mosq_err_t = %d (%s)", rv, mosquitto_strerror(rv));
        }
    }

    if (gm_config.grid_username != NULL && gm_config.grid_password != NULL) {
        mosquitto_username_pw_set(gm_mosq, gm_config.grid_username, gm_config.grid_password);
    }

    return gm_mosq;
}

void gm_connect_mqtt() {
    assert_mqtt_initialized();

    // connect
    const char *host = gm_config.grid_host;
    int port = gm_config.grid_port;
    printf("Connecting to broker %s:%d\n", host, port);
    int rv = mosquitto_connect(gm_mosq, host, port, GRID_KEEPALIVE);
    if (rv == MOSQ_ERR_ERRNO) {
        err(1, "could not connect to broker");
    }
    else if (rv != MOSQ_ERR_SUCCESS) {
        errx(1, "could not connect to broker, mosq_err_t = %d (%s)", rv, mosquitto_strerror(rv));
    }

    subscribe_topics();
}

// Subscribe to all topics relevant to a node.
void subscribe_topics() {
    // buffer for topic string
    char topic_buf[512];

    // subscribe to node topics
    int rv;
    snprintf(topic_buf, sizeof(topic_buf), "%s/#", gm_config.node_name);
    rv = mosquitto_subscribe(gm_mosq, NULL, topic_buf, 2);
    if (rv != MOSQ_ERR_SUCCESS) {
        errx(1, "could not subscribe to node topics, mosq_err_t = %d (%s)", rv, mosquitto_strerror(rv));
    }

    // subscribe to grid topics
    rv = mosquitto_subscribe(gm_mosq, NULL, "grid/#", 2);
    if (rv != MOSQ_ERR_SUCCESS) {
        errx(1, "could not subscribe to grid topics, mosq_err_t = %d (%s)", rv, mosquitto_strerror(rv));
    }
}


void gm_process_mqtt(short revents) {
    // process events for mqtt socket
    // TODO: make the error handling more robust and less repetitive
    int rv;

    if (revents & (POLLERR | POLLHUP | POLLNVAL)) {
        warnx("mqtt socket died, revents = 0x%hx", revents);
        attempt_reconnect();
    }
    if (revents & POLLIN) {
        rv = mosquitto_loop_read(gm_mosq, 1);
        if (rv == MOSQ_ERR_ERRNO) {
            err(1, "could not perform read ops");
        }
        else if (rv == MOSQ_ERR_KEEPALIVE) {
            // don't die, let the disconnect callback fire
            warnx("keepalive exceeded");
        }
        else if (rv != MOSQ_ERR_SUCCESS) {
            errx(1, "read ops failed, mosq_err_t = %d (%s)", rv, mosquitto_strerror(rv));
        }
    }
    if (revents & POLLOUT) {
        rv = mosquitto_loop_write(gm_mosq, 1);
        if (rv == MOSQ_ERR_ERRNO) {
            err(1, "could not perform write ops");
        }
        else if (rv == MOSQ_ERR_KEEPALIVE) {
            warnx("keepalive exceeded");
        }
        else if (rv != MOSQ_ERR_SUCCESS) {
            errx(1, "write ops failed, mosq_err_t = %d (%s)", rv, mosquitto_strerror(rv));
        }
    }

    rv = mosquitto_loop_misc(gm_mosq);
    if (rv == MOSQ_ERR_ERRNO) {
        err(1, "could not perform misc ops");
    }
    else if (rv == MOSQ_ERR_KEEPALIVE) {
        warnx("keepalive exceeded");
    }
    else if (rv != MOSQ_ERR_SUCCESS) {
        errx(1, "misc ops failed, mosq_err_t = %d (%s)", rv, mosquitto_strerror(rv));
    }
}

// callbacks

void has_connected(struct mosquitto *mosq, void *obj, int rc) {
    if (rc != MOSQ_ERR_SUCCESS) {
        printf("has_connected(%p, %p, %d)\n", mosq, obj, rc);
    }
    else {
        puts("Connected to MQTT");
        gm_announce();
    }
}

void has_published(struct mosquitto *mosq, void *obj, int mid) {
    // printf("has_published(%p, %p, %d)\n", mosq, obj, mid);
}

void has_subscribed(struct mosquitto *mosq, void *obj, int mid, int qos_count, const int *granted_qos) {
    //printf("has_subscribed(%p, %p, %d, %d, %p)\n", mosq, obj, mid, qos_count, granted_qos);
    printf("Subscribed, mid = %d\n", mid);
}

void has_message(struct mosquitto *mosq, void *obj, const struct mosquitto_message *message) {
    // punt to controller
    gm_route_message(message);
}

void has_disconnected(struct mosquitto *mosq, void *obj, int reason) {
    printf("in reconnect callback, reason = %d\n", reason);
    if (reason != 0) {
        attempt_reconnect();
    }
    
}

// Reconnect to MQTT with exponential backoff
#define MIN_DELAY 1
#define MAX_DELAY 60

// Try to reconnect
void attempt_reconnect(void) {
    int delay = MIN_DELAY;
    int rv;
    puts("Reconnecting to broker...");
    while ((rv = mosquitto_reconnect(gm_mosq) != MOSQ_ERR_SUCCESS)) {
        if (rv == MOSQ_ERR_ERRNO || rv == MOSQ_ERR_NOMEM) {
            // TODO: actually look at errno
            if (rv == MOSQ_ERR_ERRNO){
                warn("could not reconnect");
            }
            else {
                warnx("could not reconnect, mosq_err_t = %d (%s)", rv, mosquitto_strerror(rv));
            }
            printf("sleeping for %d secs and trying again\n", delay);
            sleep(delay);
            delay *= 2;
            delay = delay > MAX_DELAY ? MAX_DELAY : delay;
        }
        else {
            errx(1, "could not reconnect, mosq_err_t = %d (%s)", rv, mosquitto_strerror(rv));
        }
    }

    subscribe_topics();
}

// TODO: move these somewhere else

// Announce the node's existence to the grid
void gm_announce(void) {
    int rv = mosquitto_publish(gm_mosq, NULL, "node/connect", strlen(gm_config.node_name), gm_config.node_name, 1, false);
    if (rv != MOSQ_ERR_SUCCESS) {
        errx(1, "could not announce, mosq_err_t = %d (%s)", rv, mosquitto_strerror(rv));
    }
}

// Disconnect from the broker and free resources
void gm_shutdown() {
    // Send disconect message 
    int rv = mosquitto_publish(gm_mosq, NULL, "node/disconnect", strlen(gm_config.node_name), gm_config.node_name, 1, false);
    if (rv != MOSQ_ERR_SUCCESS) {
        // we're shutting down anyway, may as well warn instead of err
        warnx("could not send farewell, mosq_err_t = %d (%s)", rv, mosquitto_strerror(rv));
    }
    rv = mosquitto_disconnect(gm_mosq);
    if (rv != MOSQ_ERR_SUCCESS) {
        warnx("could not disconnect from broker, mosq_err_t = %d (%s)", rv, mosquitto_strerror(rv));
    }

    mosquitto_destroy(gm_mosq);
    gm_mosq = NULL;
    mosquitto_lib_cleanup();

    exit(0);
}