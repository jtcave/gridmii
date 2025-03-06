// gridmii.h - global declarations
// TODO: consistent prefix and naming for the global interfaces

#include <sys/types.h>
#include <mosquitto.h>

/// configuration ///

// MQTT broker host name
#define GRID_HOST "iris.local"
// MQTT broker port
#define GRID_PORT 1883

// buffer size for subprocess stdout/stderr reads
#define BUFFER_SIZE 64

// used as a millisecond delay value in poll(), etc.
#define DELAY_MS 100

// shell used to run job scripts
#define SHELL_PATH "/bin/sh"

// max number of concurrent jobs
#define MAX_JOBS 1

// temp file prefix
#define TEMP_PREFIX "/tmp/gridmii-"
#define TEMP_PATTERN TEMP_PREFIX "XXXXXX"

/// declarations - mqtt ///

// global mosquitto object
// TODO: if we have this, then do we need all these `struct mosquitto *` params everywhere?
extern struct mosquitto *gm_mosq;

// Initialize and configure a mosquitto object
// Store that object in global variable `gm_mosq`, and also return it
struct mosquitto *gm_init_mqtt(void);

// Connect to the broker and subscribe to topics
void gm_connect_mqtt(void);

// Process MQTT events. This is to be called by the main event loop after polling the socket.
// mosq - a mosquitto object
// revents - the `revents` field from the poll(2) call pertaining to the socket
void gm_process_mqtt(short revents);

// disconnect from the broker and shut the server down
void gm_shutdown(void);

/// declarations - job table ///

// forward declare `struct job` because we need it as a paraneter for callbacks, which are
// members of the struct
struct job;

// callback type for job write
typedef void (*write_callback)(struct job *jobspec, int source_fd, char *buffer, size_t readsize);

// job table entry
struct job {
    uint32_t job_id;    // global job identifier, issued by cluster manager
    pid_t job_pid;      // local pid, used to address actual child process
    int job_stdin;
    int job_stdout;
    int job_stderr;
    bool running;
    int exit_stat;
    write_callback on_write;
};

// initialize the job table
void init_job_table(void);

// Submit a job by providing a shell command
int submit_job(uint32_t job_id, write_callback on_write, const char *command);

// returns whether jobs are running
bool jobs_running(void);

// Process events for jobs
void do_job_events(void);

/// declarations - event loop ///

// body of event loop
void gm_do_events(void);

/// declarations - message response controller

// incoming message router
void gm_route_message(const struct mosquitto_message *message);