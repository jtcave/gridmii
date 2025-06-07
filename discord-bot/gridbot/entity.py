import os
import io
from typing import Self
import asyncio
import logging
import aiomqtt
import discord

from .config import *

## job table ##

def disposition(status:int) -> str:
    """Return a string explaining the waitpid status given"""
    # POSIX doesn't specify the exact values all the wait decoder macros use
    # This may cause portability issues if the node and bot use different OSes
    if status == 0:
        return "Command completed successfully"
    elif os.WIFEXITED(status):
        return f"Command completed with status {os.WEXITSTATUS(status)}"
    elif os.WIFSIGNALED(status):
        dump_message = " and dumped core" if os.WCOREDUMP(status) else ""
        return f"Command terminated with signal {os.WTERMSIG(status)}{dump_message}"
    else:
        # don't know what happened, let the user figure it out
        # We don't expect WIFSTOPPED or WIFCONTINUED, so they can fall through here
        return f"Command exited with waitpid status {status}"

class Job:
    """Represents a running job somewhere in the grid. A Job object a numeric
    JID (job ID) with an output buffer and a Discord message that displays the
    contents of that buffer. Standard output/error writes from the job will
    update the output buffer."""

    table: dict[int, Self] = {}

    # TODO: find out how to get this magic number from Discord or discord.py
    # TODO: check the attachment limit too
    MESSAGE_LIMIT = 2000    # assume no Nitro

    # The bot is responsible for issuing JIDs. Keep track of the last JID issued.
    last_jid: int = 0

    def __init__(self, jid: int, output_message: discord.Message, target_node_name: str):
        self.jid = jid
        self.output_buffer = io.BytesIO()
        self.output_message = output_message
        self.will_attach = False
        self.started = False
        self.target_node = target_node_name

    @classmethod
    def new_job(cls, output_message: discord.Message, target_node_name: str) -> Self:
        """Create fresh job object tied to an output message"""
        cls.last_jid += 1
        jid = cls.last_jid
        new_job_entry = cls(jid, output_message, target_node_name)
        cls.table[jid] = new_job_entry
        return new_job_entry

    def buffer_contents(self) -> str:
        """Return the contents of the output buffer."""
        return self.output_buffer.getvalue().decode(errors="replace")

    async def startup(self):
        """Called when the job has successfully started."""
        await self.output_message.edit(content="Your job has started! Stand by for output...")
        self.started = True

    async def reject(self, error: bytes):
        """Called when the job could not start."""
        content = f"**Could not start job:** `{error.decode(errors="replace")}`"
        await self.output_message.edit(content=content)
        self.started = True     # don't let the clean_if_unstarted task fire
        del self.table[self.jid]

    async def clean_if_unstarted(self, delay=20.0):
        """A task that will terminate jobs that did not start in a reasonable amount of time.
        This is meant to be scheduled as a task in the event loop."""
        # The default delay is an extremely conservative number. One of my test nodes has a horrific connection
        # to the broker (high latency Internet + buggy network driver), and even this isn't high enough sometimes.
        await asyncio.sleep(delay)
        if not self.started:
            logging.warning(f"job {self.jid} did not start on node {self.target_node}")
            await self.output_message.edit(content=":x: Your job did not start. The node might not be online.")
            del self.table[self.jid]


    async def write(self, data: bytes):
        """Called when stdout/stderr has been written to and the output buffer needs updated"""
        if not self.started:
            logging.warning(f"jid {self.jid} got write message before starting")
        self.output_buffer.write(data)
        # TODO: escape the content so triple-backquotes don't wreck the output
        if not self.will_attach:
            # format the output message
            content = f"Running...\n```ansi\n{self.buffer_contents()}\n```"
            if len(content) > Job.MESSAGE_LIMIT:
                # turns out we will attach
                self.will_attach = True
                content = "Running...\n*Output will be attached to this message when the job completes*"
            await self.output_message.edit(content=content)

    async def stopped(self, result: bytes):
        """Called when the  job terminates, successfully or not"""
        # Decode the result code
        result_code = int(result)
        status = disposition(result_code)
        if self.will_attach:
            # Upload the output buffer as an attachment
            self.output_buffer.seek(0)
            attachment = discord.File(self.output_buffer, f"gridmii-output-{self.jid}.txt")
            content = status
            try:
                await self.output_message.add_files(attachment)
            except discord.HTTPException as http_exc:
                content += f"\n**Error attaching file:**\n```{str(http_exc)}```"
        else:
            # Stuff the output buffer into the reply message
            output = self.buffer_contents()
            if output and not output.isspace():
                content = f"\n```ansi\n{output}\n```\n{status}"
            else:
                content = status + "\n*The command had no output*"
            if len(content) > Job.MESSAGE_LIMIT:
                # Edge case: the termination message would put the message over the limit
                # In this case, set will_attach and backpedal.
                self.will_attach = True
                await self.stopped(result)
                return
        await self.output_message.edit(content=content)
        self.output_buffer.close()
        del Job.table[self.jid]

## Node table ##
class Node:
    """Represents a node in the grid"""

    table: dict[str, Self] = {}
    locus: str|None = TARGET_NODE

    def __init__(self, node_name):
        self.node_name = node_name

    @classmethod
    def pick_node(cls) -> Self|None:
        """Select a node that can accept a job. If there are no available nodes, return None"""
        # Our first crude node selector logic:
        # * Prefer the last node used
        # * If that node is gone, pick a node that can accept jobs
        if cls.locus in cls.table:
            return cls.table[cls.locus]
        else:
            for node in cls.table.values():
                if node.can_accept_jobs():
                    cls.locus = node.node_name
                    return node
            return None

    @classmethod
    def node_seen(cls, node_name: str) -> Self:
        """Register the presence of the node with the given name, ensuring its presence in the table"""
        if node_name not in cls.table:
            cls.table[node_name] = cls(node_name)
        else:
            cls.table[node_name].touch()
        return cls.table[node_name]

    @classmethod
    def node_gone(cls, node_name: str):
        """Remove the node with the given name from the table."""
        if node_name in cls.table:
            del cls.table[node_name]

    def touch(self):
        """Called when a node already in the table responds to a ping"""
        pass

    def can_accept_jobs(self):
        # stub for now
        return True

    async def submit_job(self, command_string: str, output_message: discord.Message, mq_client: aiomqtt.Client) -> Job:
        """Submit a job to the node"""
        job = Job.new_job(output_message, self.node_name)
        topic = f"{self.node_name}/submit/{job.jid}"
        logging.debug(f"publishing job {job.jid} to node...")
        await mq_client.publish(topic, payload=command_string)
        logging.debug(f"job {job.jid} published")
        return job

    def __str__(self):
        return self.node_name