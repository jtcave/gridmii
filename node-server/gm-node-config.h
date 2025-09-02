// gm-node-config.h - static configuration for gridmii node server

#ifndef _GM_NODE_CONFIG_H
#define _GM_NODE_CONFIG_H

/// configuration ///

// MQTT broker host name
#define GRID_HOST_DEFAULT "localhost"
// MQTT broker port
#define GRID_PORT_DEFAULT 1883

// MQTT keepalive
#define GRID_KEEPALIVE 60

// buffer size for subprocess stdout/stderr reads
#define BUFFER_SIZE 1024

// used as a millisecond delay value in poll(), etc.
#define DELAY_MS 100

// max number of concurrent jobs
#define MAX_JOBS 4

// largest allowable job script
// (n.b. 4000 characters is the Discord character cap if you have Nitro)
#define JOB_SCRIPT_LIMIT 4000

// maximum amount a job can write to stdout+stderr
#define STDOUT_LIMIT 262114 // 256k

// process number ulimit (see setrlimit(2) RLIMIT_NPROC)
// #define PROC_LIMIT 128

// temp file names
#define TEMP_PATTERN "XXXXXX"

// should be reasonable with any TMPDIR
#define MAX_TEMP_NAME_SIZE 80

#endif
