import asyncio
import io
import json
import logging
import discord
import os
from discord.ext.commands import Bot, Context
import aiomqtt

# load config file
with open("config.json", 'r') as config_file:
    config = json.load(config_file)
TOKEN = config['token']
GUILD = discord.Object(id=config['guild'])
BROKER = config["mqtt_broker"]
PORT = config["mqtt_port"]
MQTT_TLS = config.get("mqtt_tls", False)
MQTT_USERNAME = config.get("mqtt_username", "")
MQTT_PASSWORD = config.get("mqtt_password", "")
TARGET_NODE = config["target_node"]

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


# TODO: handle abandoned jobs where we didn't get a termination message

class Job:
    """Represents a running job somewhere in the grid. A Job object a numeric
    JID (job ID) with an output buffer and a Discord message that displays the
    contents of that buffer. Standard output/error writes from the job will
    update the output buffer."""

    # TODO: find out how to get this magic number from Discord or discord.py
    # TODO: check the attachment limit too
    MESSAGE_LIMIT = 2000    # assume no Nitro

    # The bot is responsible for issuing JIDs. Keep track of the last JID issued.
    last_jid: int = 0

    def __init__(self, jid: int, output_message: discord.Message):
        self.jid = jid
        self.output_buffer = io.BytesIO()
        self.output_message = output_message
        self.will_attach = False

    def buffer_contents(self) -> str:
        """Return the contents of the output buffer."""
        return self.output_buffer.getvalue().decode(errors="replace")

    async def startup(self):
        """Called when the job has successfully started."""
        await self.output_message.edit(content="Your job has started! Stand by for output...")

    async def reject(self, error: bytes):
        """Called when the job could not start."""
        content = f"**Could not start job:** `{error.decode(errors="replace")}`"
        await self.output_message.edit(content=content)

    async def write(self, data: bytes):
        """Called when stdout/stderr has been written to and the output buffer needs updated"""
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
        # TODO: decode the result code
        result_code = int(result)
        content = disposition(result_code)
        if self.will_attach:
            self.output_buffer.seek(0)
            attachment = discord.File(self.output_buffer, f"gridmii-output-{self.jid}.txt")
            try:
                await self.output_message.add_files(attachment)
            except discord.HTTPException as http_exc:
                content += f"\n**Error attaching file:**\n```{str(http_exc)}```"
        else:
            output = self.buffer_contents()
            if output and not output.isspace():
                content += f"\n```\n{output}\n```"
            else:
                content += "\n*The command had no output*"
            if len(content) > Job.MESSAGE_LIMIT:
                # Edge case: the termination message would put the message over the limit
                # In this case, set will_attach and backpedal.
                self.will_attach = True
                await self.stopped(result)
                return
        await self.output_message.edit(content=content)
        self.output_buffer.close()

# TODO: job table and new_job() need to be part of class Job
jobs: dict[int, Job] = {}

def new_job(output_message: discord.Message) -> Job:
    """Create fresh job object tied to an output message"""
    Job.last_jid += 1
    jid = Job.last_jid
    new_job_entry = Job(jid, output_message)
    jobs[jid] = new_job_entry
    return new_job_entry

## discord part ##

intents = discord.Intents.default()
intents.message_content = True

class GridMiiBot(Bot):
    """Discord client that accepts GridMii commands and processes MQTT messages"""
    # TODO: inherit from Client instead of Bot to allow for a more flexible input language
    def __init__(self, *, intents: discord.Intents):
        super().__init__(command_prefix='$', intents=intents)
        self.mqtt_task = None
        self.mq_client: aiomqtt.Client|None = None
        self.mq_sent = set()

    async def setup_hook(self) -> None:
        # Install the MQTT task.
        self.mqtt_task = self.loop.create_task(self.do_mqtt_task())

    async def do_mqtt_task(self):
        # This is the MQTT task.
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
                    # subscribe to our topics
                    # TODO: listen for shutdown messages
                    for topic in ("general", "job/#"):
                        await self.mq_client.subscribe(topic)
                    # handle messages
                    logging.info("MQTT ready")
                    async for msg in self.mq_client.messages:
                        await self.on_mqtt(msg)
            except aiomqtt.MqttError:
                reconnect_delay = 3
                logging.exception(f"Lost connection to broker. Retrying in {reconnect_delay} seconds")
                await asyncio.sleep(reconnect_delay)
            except Exception:
                logging.exception("Unhandled exception in MQTT task")
                raise

    async def on_mqtt(self, msg: aiomqtt.Message):
        """MQTT message handler, called once per message"""
        topic_path = str(msg.topic).split('/')

        if not topic_path:
            return

        if topic_path[0] == "job" and len(topic_path) == 3:
            # job status update
            _, jid, event = topic_path
            jid = int(jid)
            if jid not in jobs:
                logging.warning(f"got message for spurious job {jid}")
                return
            job = jobs[jid]
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
                    # TODO: the reject and stopped methods should update the job table automatically
                    logging.warning(f"got job rejection for {jid}")
                    await job.reject(msg.payload)
                    del jobs[jid]
                case "stopped":
                    logging.info(f"got job stop message for {jid}")
                    await job.stopped(msg.payload)
                    del jobs[jid]

bot = GridMiiBot(intents=intents)

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
    """Start a job, using the given text as the command"""
    if bot.mq_client is None:
        logging.error("bot.mq_client is None!")
        await ctx.send("**internal error!**")
        return

    command_string = ' '.join(command)

    reply = await ctx.message.reply("Your job is starting...")
    job = new_job(reply)
    topic = f"{TARGET_NODE}/submit/{job.jid}"
    logging.debug(f"publishing job {job.jid} to node...")
    try:
        await bot.mq_client.publish(topic, payload=command_string)
        logging.debug(f"job {job.jid} published")
    except aiomqtt.exceptions.MqttError as ex_mq:
        logging.exception("error publishing job submission")
        await reply.edit(content=f"**Couldn't submit job**: {str(ex_mq)}")

@bot.command()
async def scram(ctx: Context):
    """Terminate all jobs across the entire grid"""
    logging.warning("scram command called")
    topic = f"{TARGET_NODE}/scram"
    try:
        await bot.mq_client.publish(topic)
    except aiomqtt.MqttError as ex_mq:
        logging.exception("error publishing scram")
        await ctx.message.reply(f"**Couldn't send scram request**: {str(ex_mq)}")
    else:
        await ctx.message.reply(":+1: wait for the jobs to complete")


## startup ##
bot.run(TOKEN, root_logger=True)