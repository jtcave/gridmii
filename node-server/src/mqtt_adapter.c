// mqtt.c - gridmii mqtt routines

#include <stdlib.h>
#include <string.h>
#include <err.h>
#include <errno.h>
#include <stdio.h>
#include <sys/utsname.h>
#include <poll.h>
#include <unistd.h>
#include <netdb.h>
#include <fcntl.h>

#include <openssl/bio.h>

#include "gm-node.h"

// global mqtt object
struct mqtt_client *gm_mqtt = NULL;
static struct mqtt_client client_instance;

// params for the object
static struct gm_mqtt_params gm_mqtt_params;

void subscribe_topics(void);
void attempt_reconnect(void);
int connect_to_broker(void);

// callbacks that we set
void has_message(void **state, struct mqtt_response_publish *message);
void has_disconnected(struct mqtt_client *client, void **state);

void gm_init_mqtt(void) {
    // set up client struct
    gm_mqtt = &client_instance;
    mqtt_init_reconnect(gm_mqtt, &has_disconnected, NULL, &has_message);
    
    // clear the socket
    gm_mqtt_params.broker_bio = NULL;
}

// Subscribe to all topics relevant to a node.
void subscribe_topics() {
    // buffer for topic string
    char topic_buf[512];

    // subscribe to node topics
    enum MQTTErrors rv;
    snprintf(topic_buf, sizeof(topic_buf), "%s/#", gm_config.node_name);
    rv = mqtt_subscribe(gm_mqtt, topic_buf, 2);
    if (rv != MQTT_OK) {
        errx(1, "could not subscribe to node topics: %s", mqtt_error_str(rv));
    }

    // subscribe to grid topics
    rv = mqtt_subscribe(gm_mqtt, "grid/#", 2);
    if (rv != MQTT_OK) {
        errx(1, "could not subscribe to grid topics: %s", mqtt_error_str(rv));
    }
}

// Deferred message queue

struct deferred_message *dmq_head = NULL;
struct deferred_message *dmq_tail = NULL;

// Save the body of this message into the DMQ
void defer_message(struct mqtt_response_publish *message) {
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
    if (dmq_head == NULL || dmq_tail == NULL) {
        dmq_head = dmq_tail = node;
    }
    else {
        dmq_tail->next = node;
        dmq_tail = node;
    }
    node->next = NULL;
}

// Deallocate a DMQ entry
void free_deferred_message(struct deferred_message *node) {
    if (node->payload != NULL) {
        free(node->payload);
    }
    free(node);
}

// Process each DMQ entry. Free them afterwards.
void service_dmq(void) {
    while (dmq_head != NULL) {
        struct deferred_message *here = dmq_head;
        gm_route_message(here);
        dmq_head = here->next;
        free_deferred_message(here);
    }
    dmq_tail = NULL;
}

// callbacks

// Called when we get an MQTT message
void has_message(void **state, struct mqtt_response_publish *message) {
    int i;
    char *topic = (char*)(message->topic_name);
    // print our message for debugging
    printf("message %d @ ", (int)(message->packet_id));
    for (i = 0; i < message->topic_name_size; i++) {
        putchar(topic[i]);
    }
    putchar('\n');
    // save message for later
    defer_message(message);
}

// Called when we we need to (re)connect to the broker
void has_disconnected(struct mqtt_client *client, void **state) {
    attempt_reconnect();
}

// Reconnect to MQTT with exponential backoff
#define MIN_DELAY 1
#define MAX_DELAY 60

// Try to (re)connect
void attempt_reconnect(void) {
    enum MQTTErrors rv;
    uint8_t flags;

    const char *client_id = gm_config.node_name;
    
    // check error from client object
    if (gm_mqtt->error == MQTT_ERROR_INITIAL_RECONNECT) {
        puts("Connecting to broker...");
    }
    else {
        printf("Reconnecting to broker (%s)...\n", mqtt_error_str(gm_mqtt->error));
    }

    // don't leak old BIOs
    if (gm_mqtt_params.broker_bio != NULL) {
        BIO_free_all(gm_mqtt_params.broker_bio);
    }

    // build BIO
    int fd = connect_to_broker();
    gm_mqtt_params.broker_bio = BIO_new_socket(fd, 1);

    // mqtt_reinit

    mqtt_reinit(gm_mqtt, gm_mqtt_params.broker_bio,
        gm_mqtt_params.xmit_buffer, GM_MQTT_XMIT_BUFFER_SIZE,
        gm_mqtt_params.recv_buffer, GM_MQTT_RECV_BUFFER_SIZE);

    flags = MQTT_CONNECT_CLEAN_SESSION | MQTT_CONNECT_WILL_QOS_2;

    // mqtt_connect (LWT message set here)
    rv = mqtt_connect(gm_mqtt, client_id,
        "node/disconnect", client_id, strlen(client_id),    // last will
        gm_config.grid_username, gm_config.grid_password,
        flags, GRID_KEEPALIVE);
    if (rv != MQTT_OK) {
        errx(1, "could not establish MQTT session: %s", mqtt_error_str(rv));
    }

    // subscribe to topics
    subscribe_topics();

    gm_announce();

    puts("Connected.");
}

// establish a TCP connection to the broker, returning the socket
// TODO: auto-retry
int connect_to_broker(void) {
    // int delay = MIN_DELAY;
    int rv;
    int fd = -1;
    struct addrinfo hint;
    struct addrinfo *ai;
    char portbuf[8];

    // address lookup
    memset(&hint, 0, sizeof hint);
    hint.ai_family = AF_INET; // TODO: change this to AF_UNSPEC
    hint.ai_socktype = SOCK_STREAM;
    snprintf(portbuf, 8, "%d", gm_config.grid_port);
    rv = getaddrinfo(gm_config.grid_host, portbuf, &hint, &ai);
    if (rv != 0 || ai == NULL) {
        errx(1, "could not look up address for GRID_HOST: %s", gai_strerror(rv));
    }

    fd = socket(ai->ai_family, ai->ai_socktype, ai->ai_protocol);
    if (fd == -1) {
        err(1, "could not create socket");
    }

    rv = connect(fd, ai->ai_addr, ai->ai_addrlen);
    if (rv == -1) {
        err(1, "could not connect to broker");
    }

    rv = fcntl(fd, F_SETFL, O_NONBLOCK);
    if (rv == -1) {
        err(1, "fcntl(fd, F_SETFL, O_NONBLOCK)");
    }

    return fd;
}

// Pump the mqtt event loop
void do_mqtt_events() {
    enum MQTTErrors rv;

    // Pump the client library
    rv = mqtt_sync(gm_mqtt);
    if (rv != MQTT_OK) {
        warnx("mqtt sync failed: %s", mqtt_error_str(rv));
    }

    // Actually handle messages
    service_dmq();
}

// Announce the node's existence to the grid
void gm_announce(void) {
    /*
    {
        "node": gm_config.node_name
        "version": GIT_VERSION
    }
    */
    json_t *message = json_object();
    json_t *message_node = json_string(gm_config.node_name);
    json_t *message_version = json_string(GIT_VERSION);
    json_object_set_new(message, "node", message_node);
    json_object_set_new(message, "version", message_version);

    enum MQTTErrors rv = gm_publish_json(message, "node/connect", 1, false);
    if (rv != MQTT_OK) {
        errx(1, "could not announce: %s", mqtt_error_str(rv));
    }
}

// Convert a QoS level into an MQTT-C flags field
uint8_t flags_for_qos(int qos) {
    switch (qos) {
        case 0: return MQTT_PUBLISH_QOS_0;
        case 1: return MQTT_PUBLISH_QOS_1;
        case 2: return MQTT_PUBLISH_QOS_2;
        default: return MQTT_PUBLISH_QOS_2;
    }
}

// Serialize a JSON object and publish it as the payload of a given topic
// Takes ownership of the object and decrefs it.
enum MQTTErrors gm_publish_json(json_t *js, const char *topic, int qos, bool retain) {
    char *ser;
    enum MQTTErrors rv;
    uint8_t flags = flags_for_qos(qos);
    if (retain) {
        flags |= MQTT_PUBLISH_RETAIN;
    }
    ser = json_dumps(js, JSON_COMPACT);
    if (ser) {
        rv = mqtt_publish(gm_mqtt, topic, ser, strlen(ser), flags);
        free(ser);
    }
    else {
        // can't do anything about an error, just publish a message and hope for the best
        rv = mqtt_publish(gm_mqtt, topic, "", 0, flags);
    }
    json_decref(js);
    return rv;
}


// Disconnect from the broker and free resources
void gm_disconnect() {
    enum MQTTErrors rv;

    rv = mqtt_disconnect(gm_mqtt);
    if (rv != MQTT_OK) {
        warnx("could not disconnect from broker: %s", mqtt_error_str(rv));
    }
    else {
        puts("Disconnected.");
    }

    // Manually close the socket to make sure the disconnect message made it out before we leave
    BIO_free_all(gm_mqtt_params.broker_bio);
    gm_mqtt_params.broker_bio = NULL;
}

// Disconnect from the broker immediately without calling into the MQTT library.
// (This avoids deadlocking in a signal handler.)
void gm_shutdown() {
    BIO_free_all(gm_mqtt_params.broker_bio);
    exit(0);
}
