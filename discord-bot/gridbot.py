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
TARGET_NODE = config["target_node"]

## job table ##

class Job:
    last_jid: int = 0

    def __init__(self, jid: int, output_message: discord.Message):
        self.jid = jid
        self.output_buffer = b''
        self.output_message = output_message

    async def startup(self):
        # don't trash the output message if we already wrote to it for some reason
        if not self.output_buffer:
            await self.output_message.edit(content="Your job has started! Stand by for output...")

    async def reject(self, error: bytes):
        content = f"**Could not start job:** `{error.decode(errors="replace")}`"
        await self.output_message.edit(content=content)

    async def write(self, data: bytes):
        self.output_buffer += data
        # TODO: escape the content so triple-backquotes don't wreck the output
        decoded = self.output_buffer.decode(errors="replace")
        content = f"Running...\n```\n{decoded}\n```"
        await self.output_message.edit(content=content)

    async def stopped(self, result: bytes):
        # TODO: decode the result
        decoded_output = self.output_buffer.decode(errors="replace")
        result_code = int(result)
        content = f"Command exited with waitpid status {result_code}\n```\n{decoded_output}\n```"
        await self.output_message.edit(content=content)

jobs: dict[int, Job] = {}

def new_job(output_message: discord.Message) -> Job:
    Job.last_jid += 1
    jid = Job.last_jid
    j = Job(jid, output_message)
    jobs[jid] = j
    return j

## discord part ##

intents = discord.Intents.default()
intents.message_content = True

class GridMiiBot(Bot):
    """Discord client that accepts GridMii commands"""
    def __init__(self, *, intents: discord.Intents):
        super().__init__(command_prefix='$', intents=intents)
        self.mqtt_task = None
        self.mq_client: aiomqtt.Client|None = None
        self.mq_sent = set()

    async def setup_hook(self) -> None:
        self.mqtt_task = self.loop.create_task(self.do_mqtt_task())

    async def do_mqtt_task(self):
        await self.wait_until_ready()
        async with aiomqtt.Client(BROKER, PORT) as mq_client:
            self.mq_client = mq_client
            for topic in ("general", "job/#"):
                await mq_client.subscribe(topic)
            async for msg in mq_client.messages:
                await self.on_mqtt(msg)
        self.mq_client = None

    async def on_mqtt(self, msg: aiomqtt.Message):
        print(f"MQTT [#{msg.topic}]: {msg.payload}")
        topic_path = str(msg.topic).split('/')

        if not topic_path:
            return

        if topic_path[0] == "job":
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

'''
@bot.command()
async def mq_send(ctx: Context, topic:str, *payload):
    """Send an MQTT message"""
    if bot.mq_client is None:
        logging.error("bot.mq_client is None!")
        await ctx.send("**internal error!**")
    else:
        await bot.mq_client.publish(topic, ' '.join(payload))
        await ctx.send(f"Sent message to `{topic}`")
'''

@bot.command(name="sh")
async def start_job(ctx: Context, *command):
    if bot.mq_client is None:
        logging.error("bot.mq_client is None!")
        await ctx.send("**internal error!**")
        return

    command_string = ' '.join(command)

    reply = await ctx.message.reply("Your job is starting...")
    job = new_job(reply)
    topic = f"{TARGET_NODE}/submit/{job.jid}"
    await bot.mq_client.publish(topic, payload=command_string)



## startup ##

bot.run(TOKEN)