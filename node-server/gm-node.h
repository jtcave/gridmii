// gm-node.h - global declarations for gridmii node server

#include <sys/types.h>
#include <mosquitto.h>
#include <jansson.h>
#include <poll.h>

#ifndef _GM_NODE_H
#define _GM_NODE_H

#include "version.h"

#include "gm-node-config.h"

/// declarations - misc system ///

// configuration table struct
struct gm_config_data {
    int argc;                   // process argc
    char *const *argv;          // process argv
    const char *grid_host;      // MQTT broker hostname
    int grid_port;              // MQTT broker port
    bool use_tls;               // whether using TLS for MQTT
    const char *grid_username;  // MQTT username
    const char *grid_password;  // MQTT password
    const char *node_name;      // name of node in the grid
    const char *job_cwd;        // starting directory for jobs
    const char *job_shell;      // shell used to run job script
    const char *tmpdir;         // temporary directory
    int tmp_name_size;          // temporary filename size
};

// global configuration table
extern struct gm_config_data gm_config;

// global pollfds (for mqtt and jobs)
extern struct pollfd pollfds[1 + (MAX_JOBS * 2)];

// flag that suppresses our atexit function in the child process
extern bool gm_in_child;

/// declarations - mqtt ///

// global mosquitto object
extern struct mosquitto *gm_mosq;

// Initialize and configure a mosquitto object
// Store that object in global variable `gm_mosq`, and also return it
struct mosquitto *gm_init_mqtt(void);

// Connect to the broker and subscribe to topics
void gm_connect_mqtt(void);

// Process MQTT events. This is to be called by the main event loop after polling the socket.
void gm_process_mqtt(short revents);

// Serialize a JSON object and publish it as the payload of a given topic
// Takes ownership of the object and decrefs it.
int gm_publish_json(json_t *js, const char *topic, int qos, bool retain);

// Announce the node's existence to the grid
void gm_announce(void);

// pump one cycle of the mosquitto message loop
void do_mqtt_events(void);

// disconect from the broker, but don't exit
void gm_disconnect(void);

// disconnect from the broker and shut the server down
void gm_shutdown(void);

// reload the server from a newly installed binary
void gm_reload(void);

/// declarations - job table ///
typedef uint32_t jid_t;

// forward declare `struct job` because we need it as a paraneter for callbacks, which are
// members of the struct
struct job;

// callback type for job write
typedef void (*write_callback)(struct job *jobspec, int source_fd, char *buffer, size_t readsize);

// job table entry
struct job {
    jid_t job_id;                   // global job ID issued by grid controller
    pid_t job_pid;                  // process (group) id of the job subprocess
    int job_stdin;                  // fd for job stdin
    int job_stdout;                 // fd for job stdout
    int job_stderr;                 // fd for job stdout
    bool running;                   // is this job currently running?
    bool done;                      // is this job done?
    int exit_stat;                  // exit status as returned by waitpid
    write_callback on_write;        // called when the process writes to stdout/stderr
    size_t stdout_sent;             // bytes already sent from stdout to MQTT
    char temp_path[MAX_TEMP_NAME_SIZE]; // path to the job script
    int pollfd_idx;                 // index into pollfds[] of stdout
};

// job table
extern struct job job_table[MAX_JOBS];

// initialize the job table
void init_job_table(void);

// Submit a job by providing a shell command
int submit_job(jid_t jid, write_callback on_write, const char *command);

// True iff the jobspec refers to an active job
// If this returns false, the jobspec is meaningless
bool job_active(struct job *jobspec);

// write to job stdin
int job_stdin_write(jid_t jid, const char *data, size_t len);

// close job stdin
int job_stdin_eof(jid_t jid);

// close job stdout and stderr
void job_output_close(jid_t job);

// send signal to job
int job_signal(jid_t jid, int signum);

// returns whether jobs are running
bool jobs_running(void);

// Process events for a given job
void do_job_events(struct job *jobspec);

// Terminate all jobs
void job_scram(void);

// Job roll call
void job_roll_call(void);

/// declarations - message response controller

// incoming message router
void gm_route_message(const struct mosquitto_message *message);

// publish a job status update message for the given job
void gm_publish_job_status(int jid, const char *verb, const char *payload);

// publish a node announcement message not tied to any job in particular
void gm_publish_node_announce(const char *text);

#endif
