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

#include "gm-node.h"

// exit code for a job that failed to exec for one reason or another
#define SPAWN_FAILURE 0xEE

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
}

void init_job_table() {
    for (int i = 0; i < MAX_JOBS; i++) {
        init_job(&job_table[i]);
    }
}

// Start a job, including the process it monitors
int spawn_job(struct job *jobspec, uint32_t job_id, write_callback on_write, char *const *argv) {
    // initialize the jobspec
    init_job(jobspec);
    jobspec->job_id = job_id;
    if (on_write == NULL) {
        // won't take NULL as a callback
        return EFAULT;
    }
    jobspec->on_write = on_write;

    // no null argv
    if (argv == NULL || *argv == NULL) {
        return EFAULT;
    }

    // create pipes for child stdio
    // TODO: handle errors more gracefully
    int stdin_pipe[2], stdout_pipe[2], stderr_pipe[2];
    if (pipe(stdout_pipe) != 0) {
        err(1, "could not create pipe for stdout");
    }
    jobspec->job_stdout = stdout_pipe[0];

    if (pipe(stderr_pipe) != 0) {
        err(1, "could not create pipe for stdout");
    }
    jobspec->job_stderr = stderr_pipe[0];

    if (pipe(stdin_pipe) != 0) {
        err(1, "could not create pipe for stdin");
    }
    //jobspec->job_stdin = stdin_pipe[1];
    
    // TODO: hook the write side of stdin pipe to the jobspec/event loop
    // for now we just widow the pipe so the subprocess sees EOF
    close(stdin_pipe[1]);

    // TODO: build an environment for the subprocess instead of just slurping up the host's
    //       (this is an awful dirty hack for development purposes)
    extern char **environ;

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

        // Next, we enter a new session, detaching from the terminal.
        if (setsid() == -1) {
            err(SPAWN_FAILURE, "could not create session (process group) for job");
        }

        // chdir to our new working directory
        if (chdir(gm_config.job_cwd) == -1) {
            // TODO: should this be an error?
            // Shouldn't we also at least stat() the putative job_cwd first?
            // The node operator needs a chance to fix it before putting a
            // busted node in the grid.
            err(SPAWN_FAILURE, "could not chdir to node's GRID_JOB_CWD");
        }

        // exec the new process
        execve(argv[0], argv, environ);
        
        // exec failed, break the bad news
        err(SPAWN_FAILURE, "could not exeve new process");
    }
    else {
        // in parent process
        jobspec->job_pid = child_pid;
        jobspec->running = true;
        // Orphan the pipes in the parent parent process
        // This ensures the pipes will deliver EOF when the subprocess exits
        close(stdout_pipe[1]);
        close(stderr_pipe[1]);
        close(stdin_pipe[0]);
        return 0;
    }
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
        errx(1, "tried to close bogus fd %d (stdout = %d; stderr = %d)",
            fd, jobspec->job_stdout, jobspec->job_stderr);
    }
    *job_fdp = -1;
    close(fd);
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
        // TODO: do we need to do non-blocking reads with pipes?
        // TODO: less draconian read error handling

        for (int i = 0; i <= 1; i++) {
            if (polls[i].revents & (POLLIN|POLLHUP)) {
                read_count = read(polls[i].fd, buffer, BUFFER_SIZE);
                if (read_count == -1) {
                    err(1, "error reading from job pipe");
                }
                jobspec->on_write(jobspec, polls[i].fd, buffer, read_count);
                if (read_count == 0) {
                    // EOF
                    //printf("\nclosing fd %d\n", polls[i].fd);
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
    // Killing the pgroup would be sufficient to clean the job table
    // as the processes dying would eventually close stdio and trigger waitpid
    fprintf(stderr, "scram invoked");
    for (int i = 0; i < MAX_JOBS; i++) {
        struct job *jobspec = &job_table[i];
        if (job_active(jobspec)) {
            kill_job(jobspec);
        }
    }
    return;
}

// Submit a job by providing a shell command
int submit_job(uint32_t job_id, write_callback on_write, const char *command) {
    // First, put the command in a temporary file to be used as a shell script.
    char path[20];
    memcpy(path, TEMP_PATTERN, 20);
    int scriptfd = mkstemp(path);
    if (scriptfd == -1) {
        // TODO: less draconian action on transient failures
        err(1, "could not create temp file for job script");
    }
    int buf_len = strlen(command); // TODO: use strnlen to enforce a size cap?
    // Writing a large script in one go might take too long and clog up the event loop.
    // For now we just say this interface is for "a command."
    write(scriptfd, command, buf_len);
    write(scriptfd, "\n", 1);
    close(scriptfd);

    // build argv and start the job
    char *argv[] = {SHELL_PATH, path, NULL};
    struct job *jobspec = empty_job_slot();
    if (jobspec == NULL) {
        // TODO: sensible error return for "no job slots available"
        return EUSERS;
    }
    int spawn_code = spawn_job(jobspec, job_id, on_write, argv);
    fprintf(stderr, "spawn_job() for jid %d returned %d\n", job_id, spawn_code);

    // clean up
    //usleep(DELAY_MS);
    //unlink(path);
    return spawn_code;
}
