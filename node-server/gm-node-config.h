// gm-node-config.h - static configuration for gridmii node server

#ifndef _GM_NODE_CONFIG_H
#define _GM_NODE_CONFIG_H

/// configuration ///

// MQTT broker host name
#define GRID_HOST_DEFAULT "localhost"
// MQTT broker port
#define GRID_PORT_DEFAULT 1883

// MQTT keepalive
#define GRID_KEEPALIVE 10

// buffer size for subprocess stdout/stderr reads
#define BUFFER_SIZE 1024

// used as a millisecond delay value in poll(), etc.
#define DELAY_MS 100

// max number of concurrent jobs
#define MAX_JOBS 4

// largest allowable job script
// (n.b. 4000 characters is the Discord character cap if you have Nitro)
#define JOB_SCRIPT_LIMIT 4000

// temp file names
#define TEMP_PREFIX "/tmp/gridmii-"
#define TEMP_PATTERN TEMP_PREFIX "XXXXXX"
#define TEMP_NAME_SIZE sizeof(TEMP_PATTERN)

#endif
