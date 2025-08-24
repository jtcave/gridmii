// jobs.c - job and subprocess management

#include <errno.h>
#include <spawn.h>
#include <stdio.h>
#include <unistd.h>
#include <signal.h>
#include <poll.h>
#include <sys/wait.h>
#include <err.h>
#include <string.h>
#include <stdlib.h>
#include <fcntl.h>
#include <sys/resource.h>

#include "gm-node.h"

struct job *job_with_jid(jid_t jid);
void close_job_fd(struct job *jobspec, int fd);

// exit code for a job that failed to exec for one reason or another
#define SPAWN_FAILURE 0xEE

// environment variables that should not be set in the child
const char *envs_to_scrub[] = {
    // our proprietary configuration settings
    "GRID_HOST",
    "GRID_PORT",
    "GRID_TLS",
    "GRID_USERNAME",
    "GRID_PASSWORD",
    "GRID_NODE_NAME",
    "GRID_JOB_CWD",

    // terminal settings (these would mislead the program into)
    "TERM",
    "TERM_PROGRAM",
    "TERM_PROGRAM_VERSION",
    "TMUX_PANE",
    "COLUMNS",

    // SSH info (we don't want to leak the operator's IP!)
    "SSH_CLIENT",
    "SSH_CONNECTION",
    "SSH_TTY",
    NULL
};

// no-op write callback
void on_write_nothing(struct job *jobspec, int source_fd, char *buffer, size_t readsize) {
    // shut the hell up, clang
    (void)jobspec;
    (void)source_fd;
    (void)buffer;
    (void)readsize;
    return;
}

// job table
struct job job_table[MAX_JOBS];

// zero out the fields of jobspec
void init_job(struct job *jobspec) {
    jobspec->job_id = 0;
    jobspec->job_pid = 0;
    jobspec->job_stdin = -1;
    jobspec->job_stdout = jobspec->job_stderr = -1;
    jobspec->running = false;
    jobspec->exit_stat = 0;
    jobspec->on_write = on_write_nothing;
    jobspec->stdout_sent = 0;
    memset(jobspec->temp_path, 0, TEMP_NAME_SIZE);
}

void init_job_table() {
    for (int i = 0; i < MAX_JOBS; i++) {
        init_job(&job_table[i]);
    }
}

// Start a job, including the process it monitors
int spawn_job(struct job *jobspec, jid_t job_id, write_callback on_write, char *const *argv) {
    int rv;

    // reject null callback
    if (on_write == NULL) {
        return EFAULT;
    }

    // reject null argv and empty argv
    if (argv == NULL || *argv == NULL) {
        return EFAULT;
    }

    jobspec->job_id = job_id;
    jobspec->on_write = on_write;

    // create pipes for child stdio
    int stdin_pipe[2], stdout_pipe[2], stderr_pipe[2];
    if (pipe(stdout_pipe) != 0) {
        rv = errno;
        warn("could not create pipe for stdout");
        return rv;
    }
    jobspec->job_stdout = stdout_pipe[0];

    if (pipe(stderr_pipe) != 0) {
        rv = errno;
        warn("could not create pipe for stdout");
        return rv;
    }
    jobspec->job_stderr = stderr_pipe[0];

    if (pipe(stdin_pipe) != 0) {
        rv = errno;
        warn("could not create pipe for stdin");
        return rv;
    }
    jobspec->job_stdin = stdin_pipe[1];
    
    // we do NOT want to block when writing to the job's stdin
    rv = fcntl(stdin_pipe[1], F_SETFL, O_NONBLOCK);
    if (rv == -1) {
        rv = errno;
        warn("could not fcntl F_SETFL");
        return rv;
    }

    // flush stdio before forking
    fflush(stdout);
    fflush(stderr);

    // fork a subprocess
    int child_pid = fork();
    if (child_pid == -1) {
        // fork failed, break the bad news
        int problem_code = errno;
        warn("couldn't spawn subprocess");
        // clean up
        init_job(jobspec);
        close(stdin_pipe[0]); close(stdin_pipe[1]);
        close(stdout_pipe[0]); close(stdout_pipe[1]);
        close(stderr_pipe[0]); close(stderr_pipe[1]);
        return problem_code;
    }
    else if (child_pid == 0) {
        // In child process. Initialize the job.

        // First we disarm atexit
        gm_in_child = true;

        // Wire up stdio descriptors to the parent.
        // XXX: These error messages are going to go to the node server console,
        //      not to the user. It'll just look like the job quit with a weird
        //      error code.
        if (dup2(stdin_pipe[0], STDIN_FILENO) == -1) {
            err(SPAWN_FAILURE, "could not dup2 stdin while bringing up job");
        }
        if (dup2(stdout_pipe[1], STDOUT_FILENO) == -1) {
            err(SPAWN_FAILURE, "could not dup2 stdout while bringing up job");
        }
        if (dup2(stderr_pipe[1], STDERR_FILENO) == -1) {
            err(SPAWN_FAILURE, "could not dup2 stderr while bringing up job");
        }
        // From now on, stderr goes to the parent and the user will see our
        // error messages.

        // Close the other ends of the pipe.
        close(stdin_pipe[1]);
        close(stdout_pipe[0]);
        close(stderr_pipe[0]);

        // Next, we enter a new session, detaching from the terminal.
        if (setsid() == -1) {
            err(SPAWN_FAILURE, "could not create session (process group) for job");
        }

        // chdir to our new working directory
        if (chdir(gm_config.job_cwd) == -1) {
            err(SPAWN_FAILURE, "could not chdir to node's GRID_JOB_CWD %s", gm_config.job_cwd);
        }

        // the new process will inherit a scrubbed version of our environment
        // TODO: this really should be an allowlist instead of a denylist
        const char *env_key = envs_to_scrub[0];
        int i = 0;
        while (env_key != NULL) {
            int rv = unsetenv(env_key);
            if (rv == -1) {
                err(SPAWN_FAILURE, "could not scrub environment from key %s", env_key);
            }
            env_key = envs_to_scrub[++i];
        }

        // Set process limit
#ifdef PROC_LIMIT
        struct rlimit rl;
        rv = getrlimit(RLIMIT_NPROC, &rl);
        if (rv == -1) {
            err(SPAWN_FAILURE, "could not fetch process limit");
        }
        if (rl.rlim_max > PROC_LIMIT) {
            rl.rlim_cur = rl.rlim_max = PROC_LIMIT;
            rv = setrlimit(RLIMIT_NPROC, &rl);
            if (rv == -1) {
                err(SPAWN_FAILURE, "could not set process limit");
            }
        }
#endif // PROC_LIMIT

        // exec the new process
        extern char **environ;
        execve(argv[0], argv, environ);
        
        // exec failed, break the bad news
        err(SPAWN_FAILURE, "could not exeve new process");
    }
    else {
        // in parent process
        jobspec->job_pid = child_pid;
        jobspec->running = true;
        // Orphan the pipes in the parent process
        // This ensures the pipes will deliver EOF when the subprocess exits
        close(stdout_pipe[1]);
        close(stderr_pipe[1]);
        close(stdin_pipe[0]);
        return 0;
    }
}

// Close stdout and stderr descriptors in the job
void job_output_close(jid_t jid) {
    struct job *jobspec = job_with_jid(jid);
    close_job_fd(jobspec, jobspec->job_stdout);
    close_job_fd(jobspec, jobspec->job_stderr);
}

// Close the given file descriptor in the job.
// This is called when the event loop sees an EOF condition.
void close_job_fd(struct job *jobspec, int fd) {
    int *job_fdp = NULL;
    if (fd == jobspec->job_stdout) {
        job_fdp = &(jobspec->job_stdout);
    }
    else if (fd == jobspec->job_stderr) {
        job_fdp = &(jobspec->job_stderr);
    }
    else {
        warnx("tried to close bogus fd %d (stdout = %d; stderr = %d)",
            fd, jobspec->job_stdout, jobspec->job_stderr);
    }
    *job_fdp = -1;
    close(fd);
}

// clean up a job's temp file
void job_rm_temp(struct job *jobspec) {
    if (jobspec->temp_path[0] != '\0') {
        fprintf(stderr, "unlinking %s\n", jobspec->temp_path);
        int rv = unlink(jobspec->temp_path);
        if (rv == -1) {
            warn("could not unlink %s", jobspec->temp_path);
        }
    }
}

// Monitor job output
void poll_job_output(struct job *jobspec) {
    // buffer for reads
    char buffer[BUFFER_SIZE];
    int read_count;

    // assemble poll array for job stdout and stderr
    // TODO: shouldn't this just be done once and stored in the job table?
    struct pollfd polls[2];
    polls[0].fd = jobspec->job_stdout;
    polls[1].fd = jobspec->job_stderr;
    polls[0].events = polls[1].events = POLLIN;

    // poll for input
    int ready = poll(polls, 2, DELAY_MS);
    if (ready == -1) {
        // we can just swallow EINTR and EAGAIN
        if (errno == EFAULT || errno == EINVAL) {
            err(1, "could not poll for job output");
        }
    }
    else if (ready > 0) {
        // we might be able to do some reads, check our fds

        for (int i = 0; i <= 1; i++) {
            if (polls[i].revents & (POLLIN|POLLHUP)) {
                read_count = read(polls[i].fd, buffer, BUFFER_SIZE);
                if (read_count == -1) {
                    warn("error reading from job pipe");
                }
                jobspec->on_write(jobspec, polls[i].fd, buffer, read_count);
                if (read_count == 0) {
                    // EOF
                    close_job_fd(jobspec, polls[i].fd);
                }
            }
        }
    }
}

// Check whether the subprocess is still alive
void check_job_subprocess(struct job *jobspec) {
    if (jobspec->job_pid != 0) {
        int stat = 0;
        pid_t pid = waitpid(jobspec->job_pid, &stat, WNOHANG);
        if (pid != 0) {
            fprintf(stderr, "job %d subprocess existed with code %d\n", jobspec->job_id, stat);
            // clear job pid to mark as defunct (stdout/stderr may still need drained)
            jobspec->job_pid = 0;
            // store wait status
            jobspec->exit_stat = stat;
            // close stdin
            if (jobspec->job_stdin != -1) {
                close(jobspec->job_stdin);
                jobspec->job_stdin = -1;
            }
        }
    }
}

// True iff the subprocess has terminated and output pipes have been closed
bool job_dead(struct job *jobspec) {
    return jobspec->job_pid == 0
            && jobspec->job_stdout == -1
            && jobspec->job_stderr == -1;
}

// Check for completed jobs (subprocess quit + stdout/stderr clean) and report to broker
void collect_job(struct job *jobspec) {
    if (job_dead(jobspec)) {
        fprintf(stderr, "job %d done\n", jobspec->job_id);
        // mark job as done
        jobspec->running = false;
        // report termination to broker
        char payload[16];
        snprintf(payload, sizeof(payload), "%d", jobspec->exit_stat);
        gm_publish_job_status(jobspec->job_id, "stopped", payload);
        job_rm_temp(jobspec);
    }
}

// True iff the jobspec refers to an active job
// If this returns false, the jobspec is meaningless
bool job_active(struct job *jobspec) {
    return jobspec->running;
}


// Process events for all entries in the job table
void do_job_events() {
    for (int i = 0; i < MAX_JOBS; i++) {
        struct job *jobspec = &job_table[i];
        if (job_active(jobspec)) {
            poll_job_output(jobspec);
            check_job_subprocess(jobspec);
            collect_job(jobspec);
        }
    }
}


// find empty job slot, or NULL if job table is full
struct job *empty_job_slot() {
    for (int i = 0; i < MAX_JOBS; i++) {
        struct job *jobspec = &job_table[i];
        if (!job_active(jobspec)) {
            init_job(jobspec);
            return jobspec;
        }
    }
    return NULL;
}

// find job with given jid
struct job *job_with_jid(jid_t jid) {
    for (int i = 0; i < MAX_JOBS; i++) {
        struct job *jobspec = &job_table[i];
        if (jobspec->job_id == jid && job_active(jobspec)) {
            return jobspec;
        }
    }
    return NULL;
}

// returns whether jobs are running
bool jobs_running() {
    for (int i = 0; i < MAX_JOBS; i++) {
        if (job_active(&job_table[i])) {
            return true;
        }
    }
    return false;
}

// Kill process group at the given jobspec
void kill_job(struct job *jobspec) {
    if (jobspec->job_pid == 0) {
        // empty job
        return;
    }
    // get the process group to blow away the entirety of the job subprocesses
    pid_t job_pgroup = getpgid(jobspec->job_pid);
    if (job_pgroup == -1) {
        warn("couldn't get process group of pid %d", jobspec->job_pid);
        return;
    }
    // make sure we don't nuke ourselves
    pid_t my_pgroup = getpgid(getpid());
    if (my_pgroup == job_pgroup) {
        warnx("node server and job share process group %d; not killing", my_pgroup);
        return;
    }
    // this is for emergency use, so we may as well SIGKILL
    killpg(job_pgroup, SIGKILL);
}

// Terminate all jobs
void job_scram() {
    // Killing the pgroup should be sufficient to clean the job table
    // as the processes dying would eventually close stdio and trigger waitpid
    fprintf(stderr, "scram invoked\n");
    for (int i = 0; i < MAX_JOBS; i++) {
        struct job *jobspec = &job_table[i];
        if (job_active(jobspec)) {
            kill_job(jobspec);
        }
    }
    return;
}

// Publish a roll call
void job_roll_call() {
    /*
    {
        "node": name_of_node,
        "jobs": [jid_1, jid_2, jid_3...]
    }
    */
    json_t *root, *job_array, *node_name;
    root = json_object();
    node_name = json_string(gm_config.node_name);
    job_array = json_array();
    json_object_set_new(root, "node", node_name);
    json_object_set_new(root, "jobs", job_array);
    for (int i = 0; i < MAX_JOBS; i++) {
        struct job *jobspec = &job_table[i];
        if (job_active(jobspec)) {
            json_t *j_jid = json_integer(jobspec->job_id);
            json_array_append(job_array, j_jid);
        }
    }
    char *ser = json_dumps(root, JSON_COMPACT);
    if (ser == NULL) {
        warnx("could not serialize JSON for job_roll_call()");
        return;
    }
    // TODO: actually publish this to an MQTT topic
    puts(ser);
}

// Submit a job by providing a shell command
int submit_job(jid_t jid, write_callback on_write, const char *command) {
    // First, put the command in a temporary file to be used as a shell script.
    char path[TEMP_NAME_SIZE];
    memcpy(path, TEMP_PATTERN, TEMP_NAME_SIZE);
    int scriptfd = mkstemp(path);
    if (scriptfd == -1) {
        int rv = errno;
        warn("could not create temp file for job script");
        return rv;
    }
    int buf_len = strnlen(command, JOB_SCRIPT_LIMIT);
    write(scriptfd, command, buf_len);
    write(scriptfd, "\n", 1);
    close(scriptfd);

    // build argv and start the job
    char *argv[] = {(char*)gm_config.job_shell, path, NULL};
    struct job *jobspec = empty_job_slot();
    if (jobspec == NULL) {
        // this seems to be a semi-reasonable error return for "no job slots available"
        return EUSERS;
    }
    // stash path to script
    memcpy(jobspec->temp_path, path, TEMP_NAME_SIZE);
    
    // actually launch the job
    int spawn_code = spawn_job(jobspec, jid, on_write, argv);
    fprintf(stderr, "spawn_job() for jid %d returned %d\n", jid, spawn_code);
    if (spawn_code != 0) {
        job_rm_temp(jobspec);
    }
    return spawn_code;
}

int job_stdin_write(jid_t jid, const char *data, size_t len) {
    struct job *jobspec = job_with_jid(jid);
    if (jobspec == NULL) {
        return ESRCH;
    }
    int fd = jobspec->job_stdin;
    if (fd == -1) {
        return EBADF;
    }
    int rv = write(fd, data, len);
    if (rv == -1) {
        return errno;
    }
    else if (rv < len) {
        // short write, not good
        // since we don't have a write-later buffer, just pretend it was 100% blocked
        return EAGAIN;  // this is what fully blocked writes will do
    }
    else {
        return 0;
    }
}

int job_stdin_eof(jid_t jid) {
    struct job *jobspec = job_with_jid(jid);
    if (jobspec == NULL) {
        return ESRCH;
    }
    int fd = jobspec->job_stdin;
    if (fd == -1) {
        return EBADF;
    }
    int rv = close(jobspec->job_stdin);
    if (rv == -1) {
        return errno;
    }
    else {
        jobspec->job_stdin = -1;
        return 0;
    }
}

int job_signal(jid_t jid, int signum) {
    fprintf(stderr, "sending signal %d to job %u\n", signum, jid);
    struct job *jobspec = job_with_jid(jid);
    if (jobspec == NULL) {
        return ESRCH;
    }
    pid_t job_pid = jobspec->job_pid;
    if (job_pid == 0) {
        return ESRCH;
    }
    else if (job_pid == -1) {
        // we do not want to send a broadcast message
        warnx("job %ud has pid -1", jid);
        return EDOM;    // "numerical argument out of range"
                        // not a possible kill(2) error
    }
    
    // send the signal to the whole process group
    // sending SIGINT to just the shell doesn't seem to work
    int rv;
    rv = killpg(job_pid, signum);
    
    if (rv == -1) {
        return errno;
    }
    else {
        return 0;
    }
}