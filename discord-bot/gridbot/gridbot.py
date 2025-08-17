import asyncio
from typing import override

import aiomqtt
import logging

from discord import Message
from discord.ext.commands import errors, Context

from .config import *
from .entity import Job, Node
from .grid_cmd import DEFAULT_COGS, JobControlCog
from .neofetch import NeofetchCog
from .cmd_denylist import permit_command


## discord part ##

bot_intents = discord.Intents.default()
bot_intents.message_content = True

class FlexBot(discord.ext.commands.Bot):
    """Adapts d.e.c.Bot to fit our use case better."""

    def __init__(self, *, command_prefix: str, script_prefix: str, intents: discord.Intents, **kwargs):
        super().__init__(command_prefix, intents=intents, **kwargs)
        self.script_prefix = script_prefix

    async def on_command_error(self, context: Context, exception: errors.CommandError, /) -> None:
        # Swallow exceptions that are due to user error and are not supposed to be serious issues
        if isinstance(exception, errors.CheckFailure):
            logging.debug("global command check failed")
        else:
            await super().on_command_error(context, exception)

    @override
    async def on_message(self, message: discord.Message, /):
        if message.author.bot:
            return
        ctx = await self.get_context(message)
        if ctx.valid:
            await self.invoke(ctx)
        elif message.content.startswith(self.script_prefix):
            if await self.flex_check(ctx):
                await self.flex_command(ctx)
        elif message.type == discord.MessageType.reply:
            await self.flex_reply(ctx)

    async def flex_check(self, ctx: Context) -> bool:
        return True

    async def flex_command(self, ctx: Context, /):
        """Run when a non-existent command is attempted"""
        raise NotImplementedError("flex command not specified")

    async def flex_reply(self, ctx: Context, /):
        raise NotImplementedError("flex reply not specified")


class GridMiiBot(FlexBot):
    """Discord client that accepts GridMii commands and processes MQTT messages"""
    def __init__(self, *, intents: discord.Intents):
        super().__init__(command_prefix='!', script_prefix='$', intents=intents)
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
        # Install cogs
        cogs = DEFAULT_COGS + (NeofetchCog,)
        for cog_class in cogs:
            await self.add_cog(cog_class(self))


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
            payload = msg.payload.decode()
            match topic_path[1]:
                case "connect":
                    logging.info(f"node {payload} is present")
                    Node.node_seen(payload)
                    await self.announce_node_seen(payload)
                case "disconnect":
                    logging.info(f"node {payload} has left")
                    Node.node_gone(payload)
                    await self.announce_node_gone(payload)
                case "announce":
                    logging.info(f"node announcement: {payload}")
                    await self.announce_string(payload)

    # end async def on_mqtt

    async def announce_node_seen(self, node_name: str):
        if self.can_announce:
            await self.target_channel.send(f":inbox_tray: Node `{node_name}` is connected")

    async def announce_node_gone(self, node_name: str):
        if self.can_announce:
            await self.target_channel.send(f":outbox_tray: Node `{node_name}` has disconnected")

    async def announce_string(self, payload: str):
        # don't respect self.can_announce
        # these kinds of announcements aren't directly caused by us starting up
        await self.target_channel.send(f":mega: `{payload}`")

    async def submit_job(self, ctx: Context, command_string: str, output_filter=None):
        if self.mq_client is None:
            logging.error("GridMiiBot.mq_client is None!")
            await ctx.send("**Internal error:** Couldn't submit a job because the MQTT client is not initialized")
            return

        # denylist
        if not permit_command(command_string):
            logging.warning(f"denied command: {command_string}")
            await ctx.message.reply(":octagonal_sign: That command is not allowed")
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
            job = await node.submit_job(command_string, reply, self.mq_client, output_filter)
            bot.loop.create_task(job.clean_if_unstarted())
        except aiomqtt.exceptions.MqttError as ex_mq:
            logging.exception("error publishing job submission")
            await reply.edit(content=f"**Couldn't submit job**: {str(ex_mq)}")

    async def stdin_post(self, ctx: Context, job: Job):
        body = ctx.message.content
        body += '\n'
        try:
            payload = body.encode()
        except UnicodeEncodeError:
            # I can't see how this can even happen, but complain about it anyway
            logging.exception("user message couldn't be encoded")
            await ctx.reply(":x: Internal error encoding your stdin")
            return
        await job.stdin(payload, self.mq_client)

    async def flex_check(self, ctx: Context) -> bool:
        """If a channel was specified in the config, only allow commands in that channel."""
        return ctx.channel.id == CHANNEL or CHANNEL is None

    async def flex_command(self, ctx: Context, /):
        # chop off the command prefix
        command_string = ctx.message.content[1:]
        await self.submit_job(ctx, command_string)

    async def flex_reply(self, ctx: Context, /):
        # XXX: this method should probably be in that cog itself
        job = JobControlCog.job_for_reply(ctx)
        if job is not None:
            await self.stdin_post(ctx, job)

bot = GridMiiBot(intents=bot_intents)