import asyncio
import io
import json
import logging
from typing import Self
import discord
import os
from discord.ext.commands import Context, errors
import aiomqtt
from discord.ext.commands._types import BotT

# load config file
with open("config.json", 'r') as config_file:
    config = json.load(config_file)
TOKEN = config['token']
GUILD = discord.Object(id=config['guild'])
CHANNEL = config.get("channel", None)
BROKER = config["mqtt_broker"]
PORT = config["mqtt_port"]
MQTT_TLS = config.get("mqtt_tls", False)
MQTT_USERNAME = config.get("mqtt_username", "")
MQTT_PASSWORD = config.get("mqtt_password", "")
TARGET_NODE = config.get("target_node", None)

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
            content = f"Running...\n```\n{self.buffer_contents()}\n```"
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
                content = f"\n```\n{output}\n```\n{status}"
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

    async def submit_job(self, command_string: str, output_message: discord.Message) -> Job:
        """Submit a job to the node"""
        job = Job.new_job(output_message, self.node_name)
        topic = f"{self.node_name}/submit/{job.jid}"
        logging.debug(f"publishing job {job.jid} to node...")
        await bot.mq_client.publish(topic, payload=command_string)
        logging.debug(f"job {job.jid} published")
        return job

    def __str__(self):
        return self.node_name


## discord part ##

bot_intents = discord.Intents.default()
bot_intents.message_content = True

class FlexBot(discord.ext.commands.Bot):
    """Adapts d.e.c.Bot to fit our use case better."""
    async def on_command_error(self, context: Context[BotT], exception: errors.CommandError, /) -> None:
        # Swallow exceptions that are due to user error and are not supposed to be serious issues
        if isinstance(exception, errors.CheckFailure):
            logging.debug("global command check failed")
        elif context.command is None:
            # no command object means to run the flex command
            if await self.can_run(context):
                try:
                    await self.flex_command(context)
                except Exception as flex_exc:
                    logging.exception("exception in flex command function", exc_info=flex_exc)
            else:
                logging.debug("global flex command check failed")
        else:
            await super().on_command_error(context, exception)

    async def invoke(self, ctx: Context[BotT], /) -> None:
        try:
            await super().invoke(ctx)
        except errors.CommandNotFound:
            await self.flex_command(ctx)

    async def flex_command(self, ctx: Context[BotT], /):
        """Run when a non-existent command is attempted"""
        raise NotImplementedError("flex command not specified")



class GridMiiBot(FlexBot):
    """Discord client that accepts GridMii commands and processes MQTT messages"""
    # TODO: inherit from Client instead of Bot to allow for a more flexible input language
    def __init__(self, *, intents: discord.Intents):
        super().__init__(command_prefix='$', intents=intents)
        self.mqtt_task = None
        self.after_broker_connect_task = None
        self.broker_connected = asyncio.Event()
        self.target_channel: discord.TextChannel|None = None
        self.mq_client: aiomqtt.Client|None = None
        self.mq_sent = set()
        self.can_announce = False

    async def setup_hook(self) -> None:
        # Install the MQTT task.
        self.mqtt_task = self.loop.create_task(self.do_mqtt_task())
        # Install the "after broker connection" task"
        self.after_broker_connect_task = self.loop.create_task(self.after_broker_connect())

    async def after_broker_connect(self):
        # Wait for the event to fire
        await self.broker_connected.wait()
        # Wait for Discord for good measure
        await self.wait_until_ready()
        # Attempt to resolve the target channel name.
        if CHANNEL:
            self.target_channel = self.get_channel(CHANNEL)
            if not self.target_channel:
                logging.error(f"The target channel specified wasn't found. ID = {CHANNEL}")
            else:
                # Do setup things that need the target channel
                logging.debug(f"Using #{self.target_channel} as the target channel")
                # After waiting some time, allow "node connected" messages to happen
                async def _allow_announce():
                    await asyncio.sleep(5)
                    self.can_announce = True
                self.loop.create_task(_allow_announce())
        else:
            logging.warning("No target channel has been specified. Certain status messages won't be sent.")
        await asyncio.sleep(5)

    async def do_mqtt_task(self):
        """Coroutine that sets up the MQTT client and processes inbound messages.
        This is meant to be scheduled in the bot's event loop."""
        if MQTT_TLS:
            tls_params = aiomqtt.TLSParameters()
        else:
            tls_params = None

        await self.wait_until_ready()
        logging.info("Starting MQTT task")

        self.mq_client = aiomqtt.Client(BROKER, PORT,
                                        username=MQTT_USERNAME, password=MQTT_PASSWORD,
                                        tls_params=tls_params)
        while True:
            try:
                async with self.mq_client:
                    logging.info("Connected to MQTT broker, now subscribing")
                    self.broker_connected.set()
                    # subscribe to our topics
                    for topic in ("job/#", "node/#"):
                        await self.mq_client.subscribe(topic)
                    # send out a ping to enumerate the nodes
                    await self.ping_grid()
                    # handle messages
                    logging.info("MQTT ready")
                    async for msg in self.mq_client.messages:
                        await self.on_mqtt(msg)
            except aiomqtt.MqttError:
                self.broker_connected.clear()
                reconnect_delay = 3
                logging.exception(f"Lost connection to broker. Retrying in {reconnect_delay} seconds")
                await asyncio.sleep(reconnect_delay)
            except Exception:
                logging.exception("Unhandled exception in MQTT task")
                raise

    async def ping_grid(self):
        await self.mq_client.publish("grid/ping")

    async def on_mqtt(self, msg: aiomqtt.Message):
        """MQTT message handler, called once per message"""
        logging.debug("MQTT %s: %s", str(msg.topic), msg.payload)
        topic_path = str(msg.topic).split('/')

        if not topic_path:
            return

        if topic_path[0] == "job" and len(topic_path) == 3:
            # job status update
            _, jid, event = topic_path
            jid = int(jid)
            if jid not in Job.table:
                logging.warning(f"got message for spurious job {jid}")
                return
            job = Job.table[jid]
            match event:
                case "stdout":
                    logging.debug(f"got job {jid} stdout: {msg.payload}")
                    await job.write(msg.payload)
                case "stderr":
                    logging.debug(f"got job {jid} stderr: {msg.payload}")
                    await job.write(msg.payload)
                case "startup":
                    logging.info(f"got job start message for {jid}")
                    await job.startup()
                case "reject":
                    logging.warning(f"got job rejection for {jid}")
                    await job.reject(msg.payload)
                case "stopped":
                    logging.info(f"got job stop message for {jid}")
                    await job.stopped(msg.payload)

        elif topic_path[0] == "node" and len(topic_path) == 2:
            # node status update
            node_name = msg.payload.decode()
            match topic_path[1]:
                case "connect":
                    logging.info(f"node {node_name} is present")
                    Node.node_seen(node_name)
                    await self.announce_node_seen(node_name)
                case "disconnect":
                    logging.info(f"node {node_name} has left")
                    Node.node_gone(node_name)
                    await self.announce_node_gone(node_name)
    # end async def on_mqtt

    async def announce_node_seen(self, node_name: str):
        if self.can_announce:
            await self.target_channel.send(f":inbox_tray: Node `{node_name}` is connected")

    async def announce_node_gone(self, node_name: str):
        if self.can_announce:
            await self.target_channel.send(f":outbox_tray: Node `{node_name}` has disconnected")

    async def submit_job(self, ctx: Context, command_string: str):
        if bot.mq_client is None:
            logging.error("bot.mq_client is None!")
            await ctx.send("**internal error!**")
            return

        # pick a node
        node = Node.pick_node()
        if node is None:
            await ctx.message.reply(":x: No nodes are available at the moment.")
            return

        # Post the reply that job output will go to
        reply = await ctx.message.reply("Your job is starting...")

        # Submit the job
        try:
            job = await node.submit_job(command_string, reply)
            bot.loop.create_task(job.clean_if_unstarted())
        except aiomqtt.exceptions.MqttError as ex_mq:
            logging.exception("error publishing job submission")
            await reply.edit(content=f"**Couldn't submit job**: {str(ex_mq)}")

    async def flex_command(self, ctx: Context[BotT], /):
        # chop off the command prefix
        command_string = ctx.message.content[1:]
        await self.submit_job(ctx, command_string)

bot = GridMiiBot(intents=bot_intents)

@bot.check
def check_channel(ctx: Context) -> bool:
    """If a channel was specified in the config, check to see if the command was sent in that channel."""
    return ctx.channel.id == CHANNEL or CHANNEL is None

@bot.command(name="yougood")
async def ping(ctx: Context):
    """Check connectivity to broker"""
    if bot.mq_client is None:
        await ctx.reply(":-1: mq_client is None")
    elif bot.mq_client._disconnected.done():
        # XXX: don't grovel into internal members like that
        await ctx.reply(":-1: mq_client._disconnected has come to pass")
    else:
        await ctx.reply(":+1:")

@bot.command(name="sh")
async def start_job(ctx: Context, *command):
    # TODO: rip this out
    await ctx.reply("the $sh command is no longer available")

@bot.command()
async def nodes(ctx: Context):
    """Dump the node table"""
    message = '\n'.join(f"* {n}" for n in Node.table) if Node.table else "No nodes are online"
    await ctx.message.reply(content=message)

@bot.command()
async def locus(ctx: Context, new_locus: str|None=None):
    """Manually set the locus node for the $sh command"""

    if new_locus is None:
        if Node.locus is None:
            content = "No node is currently set to run commands.\nOne will be selected when the next command is sent."
        else:
            content = f"Commands are being sent to {Node.locus}"
    elif new_locus in Node.table:
        Node.locus = new_locus
        content = f":+1: Commands will now run on {new_locus}"
    else:
        content = f":x: The node {new_locus} is not in the node table."
    await ctx.reply(content)

@bot.command()
async def scram(ctx: Context):
    """Terminate all jobs across the entire grid"""
    logging.warning("scram command called")
    try:
        await bot.mq_client.publish("grid/scram")
    except aiomqtt.MqttError as ex_mq:
        logging.exception("error publishing scram")
        await ctx.message.reply(f"**Couldn't send scram request**: {str(ex_mq)}")
    else:
        await ctx.message.reply(":+1: wait for the jobs to complete")


## startup ##
bot.run(TOKEN, root_logger=True)