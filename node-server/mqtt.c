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

const char *node_name(void);
bool mqtt_initialized(void);
void assert_mqtt_initialized(void);

void has_connected(struct mosquitto *mosq, void *obj, int rc);
void has_published(struct mosquitto *mosq, void *obj, int mid);
void has_message(struct mosquitto *mosq, void *obj, const struct mosquitto_message *message);
void has_subscribed(struct mosquitto *mosq, void *obj, int mid, int qos_count, const int *granted_qos);

// get the client name for mqtt (currently the system hostname)
// TODO: truncate to MOSQ_MQTT_ID_MAX_LENGTH
const char *node_name() {
    // host names are up to 255 characters on macOS/NetBSD, 64 on Linux
    static char nodebuffer[256] = {0};
    if (*nodebuffer == '\0') {
        // fill nodebuffer from uname()
        struct utsname the_uname;
        int rv = uname(&the_uname);
        if (rv != 0) {
            err(1, "could not get system uname");
        }
        strncpy(nodebuffer, the_uname.nodename, 255);
    }
    return nodebuffer;
}

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

    // set up library and struct
    if (mosquitto_lib_init() != MOSQ_ERR_SUCCESS) {
        errx(1, "could not initialize mosquitto library");
    }
    gm_mosq = mosquitto_new("gridmii-demo", false, NULL);
    if (gm_mosq == NULL) {
        err(1, "could not create mosquitto client object");
    }

    // wire up callbacks
    mosquitto_connect_callback_set(gm_mosq, has_connected);
    mosquitto_publish_callback_set(gm_mosq, has_published);
    mosquitto_subscribe_callback_set(gm_mosq, has_subscribed);
    mosquitto_message_callback_set(gm_mosq, has_message);

    
    // declare last will of client
    // TODO: what level of QoS for the will? What topic?
    const char *client_name = node_name();
    rv = mosquitto_will_set(gm_mosq, "disconnect", strlen(client_name), client_name, 0, false);
    if (rv != MOSQ_ERR_SUCCESS) {
        errx(1, "could not set last will, mosq_err_t = %d", rv);
    }

    // mosquitto_username_pw_set(gm_mosq, "username", "password");

    return gm_mosq;
}

void gm_connect_mqtt() {
    assert_mqtt_initialized();

    // connect
    int rv = mosquitto_connect(gm_mosq, GRID_HOST, GRID_PORT, 60);
    if (rv == MOSQ_ERR_ERRNO) {
        err(1, "could not connect to broker");
    }
    else if (rv != MOSQ_ERR_SUCCESS) {
        errx(1, "could not connect to broker, mosq_err_t = %d", rv);
    }

    // subscribe to topics
    // TODO: topic hierarchy

    rv = mosquitto_subscribe(gm_mosq, NULL, "test/gridmii", 2);
    if (rv != MOSQ_ERR_SUCCESS) {
        errx(1, "could not subscribe, mosq_err_t = %d", rv);
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
            errx(1, "could not perform read ops, mosq_err_t = %d", rv);
        }
    }
    if (revents & POLLOUT) {
        rv = mosquitto_loop_write(gm_mosq, 1);
        if (rv == MOSQ_ERR_ERRNO) {
            err(1, "could not perform read ops");
        }
        else if (rv != MOSQ_ERR_SUCCESS) {
            errx(1, "could not perform read ops, mosq_err_t = %d", rv);
        }
    }

    rv = mosquitto_loop_misc(gm_mosq);
    if (rv == MOSQ_ERR_ERRNO) {
        err(1, "could not perform read ops");
    }
    else if (rv != MOSQ_ERR_SUCCESS) {
        errx(1, "could not perform read ops, mosq_err_t = %d", rv);
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
        errx(1, "could not disconnect from broker, mosq_err_t = %dß", rv);
    }

    mosquitto_destroy(gm_mosq);
    gm_mosq = NULL;
    mosquitto_lib_cleanup();

    exit(0);
}