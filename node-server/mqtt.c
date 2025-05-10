// mqtt.c - gridmii mqtt routines

#include <stdlib.h>
#include <string.h>
#include <err.h>
#include <errno.h>
#include <sys/utsname.h>
#include <poll.h>

#include <stdio.h>

#include <mosquitto.h>

#include "gm-node.h"

// global mosquitto object
struct mosquitto *gm_mosq = NULL;

void subscribe_topics(void);

bool mqtt_initialized(void);
void assert_mqtt_initialized(void);


// TODO: a disconnection callback that reconnects and puts all the subscriptions back
void has_connected(struct mosquitto *mosq, void *obj, int rc);
void has_published(struct mosquitto *mosq, void *obj, int mid);
void has_message(struct mosquitto *mosq, void *obj, const struct mosquitto_message *message);
void has_subscribed(struct mosquitto *mosq, void *obj, int mid, int qos_count, const int *granted_qos);

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
    const char *client_name = gm_node_name();

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

    
    // declare last will of client
    // TODO: currently it just writes the client name to the `disconnect` topic - is that ideal? 
    rv = mosquitto_will_set(gm_mosq, "disconnect", strlen(client_name), client_name, 0, false);
    if (rv != MOSQ_ERR_SUCCESS) {
        errx(1, "could not set last will, mosq_err_t = %d (%s)", rv, mosquitto_strerror(rv));
    }

    if (gm_config.grid_username != NULL && gm_config.grid_password != NULL) {
        mosquitto_username_pw_set(gm_mosq, gm_config.grid_username, gm_config.grid_password);
    }

    return gm_mosq;
}

void gm_connect_mqtt() {
    assert_mqtt_initialized();

    // connect
    char *host = gm_config.grid_host;
    int port = gm_config.grid_port;
    printf("Connecting to broker %s:%d\n", host, port);
    int rv = mosquitto_connect(gm_mosq, host, port, 60);
    if (rv == MOSQ_ERR_ERRNO) {
        err(1, "could not connect to broker");
    }
    else if (rv != MOSQ_ERR_SUCCESS) {
        errx(1, "could not connect to broker, mosq_err_t = %d (%s)", rv, mosquitto_strerror(rv));
    }

    subscribe_topics();
}

void subscribe_topics() {
    // buffer for topic string
    char topic_buf[512];

    // subscribe to job submit endpoint
    int rv;
    snprintf(topic_buf, sizeof(topic_buf), "%s/submit/+", gm_node_name());
    rv = mosquitto_subscribe(gm_mosq, NULL, topic_buf, 2);
    if (rv != MOSQ_ERR_SUCCESS) {
        errx(1, "could not subscribe, mosq_err_t = %d (%s)", rv, mosquitto_strerror(rv));
    }

    // subscribe to exit endpoint
    snprintf(topic_buf, sizeof(topic_buf), "%s/exit", gm_node_name());
    rv = mosquitto_subscribe(gm_mosq, NULL, topic_buf, 2);
    if (rv != MOSQ_ERR_SUCCESS) {
        errx(1, "could not subscribe, mosq_err_t = %d (%s)", rv, mosquitto_strerror(rv));
    }
}


void gm_process_mqtt(short revents) {
    // process events for mqtt socket
    // TODO: make the error handling more robust and less repetitive
    int rv;

    if (revents & (POLLERR | POLLHUP | POLLNVAL)) {
        warnx("mqtt socket died, revents = 0x%hx", revents);
        //running = false;
    }
    if (revents & POLLIN) {
        rv = mosquitto_loop_read(gm_mosq, 1);
        if (rv == MOSQ_ERR_ERRNO) {
            err(1, "could not perform read ops");
        }
        else if (rv != MOSQ_ERR_SUCCESS) {
            errx(1, "could not perform read ops, mosq_err_t = %d (%s)", rv, mosquitto_strerror(rv));
        }
    }
    if (revents & POLLOUT) {
        rv = mosquitto_loop_write(gm_mosq, 1);
        if (rv == MOSQ_ERR_ERRNO) {
            err(1, "could not perform read ops");
        }
        else if (rv != MOSQ_ERR_SUCCESS) {
            errx(1, "could not perform read ops, mosq_err_t = %d (%s)", rv, mosquitto_strerror(rv));
        }
    }

    rv = mosquitto_loop_misc(gm_mosq);
    if (rv == MOSQ_ERR_ERRNO) {
        err(1, "could not perform read ops");
    }
    else if (rv != MOSQ_ERR_SUCCESS) {
        errx(1, "could not perform read ops, mosq_err_t = %d (%s)", rv, mosquitto_strerror(rv));
    }
}

// callbacks

void has_connected(struct mosquitto *mosq, void *obj, int rc) {
    if (rc != MOSQ_ERR_SUCCESS) {
        printf("has_connected(%p, %p, %d)\n", mosq, obj, rc);
    }
    else {
        puts("Connected to MQTT");
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

// TODO: move this somewhere else

void gm_shutdown() {
    int rv = mosquitto_disconnect(gm_mosq);
    if (rv != MOSQ_ERR_SUCCESS) {
        errx(1, "could not disconnect from broker, mosq_err_t = %d (%s)", rv, mosquitto_strerror(rv));
    }

    mosquitto_destroy(gm_mosq);
    gm_mosq = NULL;
    mosquitto_lib_cleanup();

    exit(0);
}