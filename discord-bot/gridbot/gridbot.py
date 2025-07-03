import asyncio
import logging
from discord import Message
from discord.ext import commands
from discord.ext.commands import Context, errors
import aiomqtt

from .config import *
from .entity import Job, Node
from .output_filter import fastfetch_filter


## discord part ##

bot_intents = discord.Intents.default()
bot_intents.message_content = True

class FlexBot(discord.ext.commands.Bot):
    """Adapts d.e.c.Bot to fit our use case better."""

    # we want flex commands, we also want to swallow some exceptions

    async def on_command_error(self, context: Context, exception: errors.CommandError, /) -> None:
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

    async def invoke(self, ctx: Context, /) -> None:
        try:
            await super().invoke(ctx)
        except errors.CommandNotFound:
            await self.flex_command(ctx)

    async def flex_command(self, ctx: Context, /):
        """Run when a non-existent command is attempted"""
        raise NotImplementedError("flex command not specified")

    # flex replies

    async def on_message(self, message: Message, /) -> None:
        if message.author.bot:
            return
        ctx = await self.get_context(message)
        if message.type == discord.MessageType.reply and ctx.command is None:
            # flex reply!
            await self.flex_reply(ctx)
        else:
            await self.invoke(ctx)

    async def flex_reply(self, ctx: Context, /):
        raise NotImplementedError("flex reply not specified")


class GridMiiBot(FlexBot):
    """Discord client that accepts GridMii commands and processes MQTT messages"""
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
        # Install cogs
        cogs = (UserCommandCog, AdminCommandCog, JobControlCog, NeofetchCog)
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

@bot.check
def check_channel(ctx: Context) -> bool:
    """If a channel was specified in the config, check to see if the command was sent in that channel."""
    return ctx.channel.id == CHANNEL or CHANNEL is None

class UserCommandCog(commands.Cog, name="User Commands"):
    """Cog for GridMii commands regular users can use"""
    @commands.command(name="yougood")
    async def ping(self, ctx: Context):
        """Check connectivity to broker"""
        if bot.mq_client is None:
            await ctx.reply(":-1: mq_client is None")
        elif bot.mq_client._disconnected.done():
            # XXX: don't grovel into internal members like that
            await ctx.reply(":-1: mq_client._disconnected has come to pass")
        else:
            await ctx.reply(":+1:")

    @commands.command()
    async def nodes(self, ctx: Context):
        """View available nodes"""
        message = '\n'.join(f"* {n}" for n in Node.table) if Node.table else "No nodes are online"
        await ctx.message.reply(content=message)

    @commands.command()
    async def locus(self, ctx: Context, new_locus: str|None=None):
        """Manually set the locus node for new jobs"""

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

    @commands.command()
    async def jobs(self, ctx: Context):
        """View running jobs"""

        def _line(job: Job):
            return f"* #{job.jid}, on `{job.target_node}`, see {job.output_message.jump_url}"

        if Job.table:
            table = '\n'.join(_line(j) for j in Job.table.values())
        else:
            table = "No jobs running"
        await ctx.message.reply(table)

class AdminCommandCog(commands.Cog, name="Admin Commands"):
    """Cog for commands only admins can use"""

    async def cog_check(self, ctx: Context) -> bool:
        user_roles = [r.id for r in ctx.author.roles]
        for admin_role in ADMIN_ROLES:
            if admin_role in user_roles:
                return True
        logging.info(f"admin command denied for user '{ctx.author.display_name}' ({ctx.author.id})")
        return False

    @commands.command()
    async def scram(self, ctx: Context):
        """Terminate all jobs across the entire grid"""
        logging.warning("scram command called")
        try:
            await bot.mq_client.publish("grid/scram")
        except aiomqtt.MqttError as ex_mq:
            logging.exception("error publishing scram")
            await ctx.message.reply(f"**Couldn't send scram request**: {str(ex_mq)}")
        else:
            await ctx.message.reply(":+1: wait for the jobs to complete")

    @commands.command()
    async def reload(self, ctx: Context, node_name:str|None=None):
        """Instruct a node to reload its server (useful for updates)"""
        if node_name is None:
            await ctx.reply(f"`node_name` parameter required\nfor example: `$reload {Node.locus}`?")
            return
        node = Node.table.get(node_name, None)
        if node is None:
            await ctx.reply(f"node {node_name} is not in the node table")
        else:
            await node.reload(bot.mq_client)
        # no need to send an ack reply because the node should disconnect and reconnect

    @commands.command()
    async def eject(self, ctx: Context, node_name:str|None=None):
        """Eject a node from the grid.
        WARNING: if jobs are running, output will be lost"""
        if node_name is None:
            await ctx.reply(f"`node_name` parameter required")
            return
        node = Node.table.get(node_name, None)
        if node is None:
            await ctx.reply(f"node {node_name} is not in the node table")
        else:
            await node.eject(bot.mq_client)
        # no need to send an ack reply because the node should disconnect

FETCH_SCRIPT = """
fastfetch --pipe false -s none
echo '===snip==='
fastfetch --pipe false -l none -s 'Title:Separator:OS:Host:Kernel:Uptime:Packages:CPU:Memory:Swap:Disk:LocalIp:Locale:Break'
"""
assert len(FETCH_SCRIPT) < 2000     # discord message size
class NeofetchCog(commands.Cog):
    """Cog for the $neofetch override"""
    @commands.command()
    async def neofetch(self, ctx: Context):
        """Run fastfetch, then rearrange the output to look correct"""
        await bot.submit_job(ctx, FETCH_SCRIPT, fastfetch_filter)

class JobControlCog(discord.ext.commands.Cog, name="Job Control"):
    """Cog that contains commands to interact with a running job"""

    @staticmethod
    def job_for_reply(ctx: Context) -> Job | None:
        """Attempt to find a job based on what message the user is replying to.
        Returns None if the job is gone or there was no job in the first place"""
        msg = ctx.message
        if msg.type != discord.MessageType.reply:
            return None
        replied_msg_id = msg.reference.message_id
        # scan for messages
        for job in Job.table.values():
            if job.output_message.id == replied_msg_id:
                return job
        # no message
        return None

    @commands.command()
    async def jobinfo(self, ctx: Context):
        """Report information about a job"""
        job = self.job_for_reply(ctx)
        if job is not None:
            await ctx.reply(repr(job))

    @commands.command()
    async def eof(self, ctx: Context):
        """Send end-of-file to a job's stdin"""
        job = self.job_for_reply(ctx)
        if job is not None:
            await job.eof(bot.mq_client)

    @commands.command()
    async def signal(self, ctx: Context, signal_num: int):
        """Send a signal (numeric code) to a job"""
        job = self.job_for_reply(ctx)
        if job is not None:
            await job.signal(signal_num, bot.mq_client)
            await ctx.reply(f"Sent signal {signal_num} to the job")

    @commands.command()
    async def kill(self, ctx: Context):
        """Send SIGKILL to a job"""
        await self.signal(ctx, 9)    # SIGKILL is 9 on all platforms I can see

    @commands.command(name="ctrl-c")
    async def ctrlc(self, ctx: Context):
        """Send SIGINT to a job, like pressing Ctrl-C"""
        await self.signal(ctx, 2)    # SIGINT is 2 on all platforms I can see

    @commands.command()
    async def jobtail(self, ctx: Context, lines:int=5):
        """Show the last few lines of a job's output"""
        job = self.job_for_reply(ctx)
        if job is not None:
            # add 1 to `lines` because there's probably a blank line at the end, and the user won't be counting that
            buffer_tail = '\n'.join(job.tail(lines+1))
            output = f"```ansi\n{buffer_tail}\n```"
            if len(output) > 2000:
                # Ideally we'd lower the parameter until it fits...
                output = f"***Output too large***\nThe message would have been {len(output)} characters long, but only 2000 are allowed"
            await ctx.reply(output)