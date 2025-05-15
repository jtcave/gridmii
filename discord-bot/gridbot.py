import json
import logging
import discord
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

# TODO: handle abandoned jobs where we didn't get a termination message

class Job:
    """Represents a running job somewhere in the grid. A Job object a numeric
    JID (job ID) with an output buffer and a Discord message that displays the
    contents of that buffer. Standard output/error writes from the job will
    update the output buffer."""

    # The bot is responsible for issuing JIDs. Keep track of the last JID issued.
    last_jid: int = 0

    def __init__(self, jid: int, output_message: discord.Message):
        self.jid = jid
        self.output_buffer = b''
        self.output_message = output_message

    async def startup(self):
        """Called when the job has successfully started."""
        # don't trash the output message if we already wrote to it for some reason
        if not self.output_buffer:
            await self.output_message.edit(content="Your job has started! Stand by for output...")

    async def reject(self, error: bytes):
        """Called when the job could not start."""
        content = f"**Could not start job:** `{error.decode(errors="replace")}`"
        await self.output_message.edit(content=content)

    async def write(self, data: bytes):
        """Called when stdout/stderr has been written to and the output buffer needs updated"""
        self.output_buffer += data
        # TODO: escape the content so triple-backquotes don't wreck the output
        decoded = self.output_buffer.decode(errors="replace")
        content = f"Running...\n```\n{decoded}\n```"
        await self.output_message.edit(content=content)

    async def stopped(self, result: bytes):
        """Called when the job terminates, successfully or not"""
        # TODO: decode the result
        decoded_output = self.output_buffer.decode(errors="replace")
        result_code = int(result)
        content = f"Command exited with waitpid status {result_code}\n```\n{decoded_output}\n```"
        await self.output_message.edit(content=content)

# TODO: job table and new_job() need to be part of class Job
jobs: dict[int, Job] = {}

def new_job(output_message: discord.Message) -> Job:
    """Create fresh job object tied to an output message"""
    Job.last_jid += 1
    jid = Job.last_jid
    new_job = Job(jid, output_message)
    jobs[jid] = new_job
    return new_job

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
        async with aiomqtt.Client(BROKER, PORT,
                                  username=MQTT_USERNAME, password=MQTT_PASSWORD,
                                  tls_params=tls_params) as mq_client:
            logging.info("Connected to MQTT broker")
            self.mq_client = mq_client
            # subscribe to our topics
            # TODO: listen for shutdown messages
            for topic in ("general", "job/#"):
                await mq_client.subscribe(topic)
            # handle messages
            async for msg in mq_client.messages:
                await self.on_mqtt(msg)
        self.mq_client = None

    async def on_mqtt(self, msg: aiomqtt.Message):
        """MQTT message handler, called once per message"""
        logging.debug(f"MQTT [#{msg.topic}]: {msg.payload}")
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
                case "stdout": await job.write(msg.payload)
                case "stderr": await job.write(msg.payload)
                case "startup": await job.startup()
                case "reject":
                    # TODO: the reject and stopped methods should update the job table automatically
                    await job.reject(msg.payload)
                    del jobs[jid]
                case "stopped":
                    await job.stopped(msg.payload)
                    del jobs[jid]

bot = GridMiiBot(intents=intents)

@bot.command()
async def ping(ctx: Context):
    """send pong to the channel"""
    await ctx.send("pong")


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
    try:
        await bot.mq_client.publish(topic, payload=command_string)
    except aiomqtt.exceptions.MqttError as ex_mq:
        logging.exception("error publishing job submission")
        await reply.edit(content=f"**Couldn't submit job**: {str(ex_mq)}")

## startup ##
bot.run(TOKEN, root_logger=True)