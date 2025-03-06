// jobs.c - job and subprocess management

#include <errno.h>
#include <spawn.h>
#include <stdio.h>
#include <unistd.h>
#include <poll.h>
#include <sys/wait.h>
#include <err.h>
#include <string.h>
#include <stdlib.h>

#include "gm-node.h"


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
    int code = 0;

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

    // initialize these for the required fields
    posix_spawn_file_actions_t file_actions;
    posix_spawn_file_actions_init(&file_actions);
    posix_spawnattr_t attr;
    posix_spawnattr_init(&attr);

    // create pipes for child stdout and stderr
    // TODO: handle errors more gracefully
    int stdout_pipe[2], stderr_pipe[2];
    if (pipe(stdout_pipe) != 0) {
        err(1, "could not create pipe for stdout");
    }
    jobspec->job_stdout = stdout_pipe[0];
    posix_spawn_file_actions_adddup2(&file_actions, stdout_pipe[1], STDOUT_FILENO);

    if (pipe(stderr_pipe) != 0) {
        err(1, "could not create pipe for stdout");
    }
    jobspec->job_stderr = stderr_pipe[0];
    posix_spawn_file_actions_adddup2(&file_actions, stderr_pipe[1], STDERR_FILENO);

    // TODO: build an environment for the subprocess instead of just slurping up the host's
    //       (this is an awful dirty hack for development purposes)
    extern char **environ;

    // do the spawn!
    int rv = posix_spawnp(&(jobspec->job_pid), argv[0], &file_actions, &attr, argv, environ);
    if (rv != 0) {
        // process spawn failed, nuke the jobspec and report failure
        // TODO: do we need to close the pipes?
        fprintf(stderr, "couldn't spawn subprocess: %s", strerror(rv));
        init_job(jobspec);
        code = rv;
    }
    else {
        jobspec->running = true;
    }

    // close the write side of the pipes in this process, so the read sides will be orphaned when the subprocess exits
    close(stdout_pipe[1]);
    close(stderr_pipe[1]);

    // clean up file actions/attr
    posix_spawnattr_destroy(&attr);
    posix_spawn_file_actions_destroy(&file_actions);

    return code;
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

// TODO: return something sensible from this
int poll_job_process_life(struct job *jobspec) {
    // This is a stub that just waits for the subprocess
    int stat = 0;
    if (jobspec->running) {
        pid_t pid = waitpid(jobspec->job_pid, &stat, WNOHANG);
        if (pid != 0) {
            // job's done
            //printf("pid %d (%d) is gone\n", pid, jobspec->job_pid);
            jobspec->running = false;
            jobspec->exit_stat = stat;
        }
    }
    return stat;
}

// returns whether a job is active
bool job_active(struct job *jobspec) {
    return jobspec->running
            || jobspec->job_stdout != -1
            || jobspec->job_stderr != -1;
}

// Process events for jobs
void do_job_events() {
    for (int i = 0; i < MAX_JOBS; i++) {
        struct job *jobspec = &job_table[i];
        if (job_active(jobspec)) {
            // TODO: what if there's output to be read after the process dies?
            poll_job_output(jobspec);
            poll_job_process_life(jobspec);
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
    int buf_len = strlen(command); // TODO: strnlen for a size cap?
    // Writing the script in one go might take too long and clog up the event loop.
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

    // clean up
    //usleep(DELAY_MS);
    //unlink(path);
    return spawn_code;
}