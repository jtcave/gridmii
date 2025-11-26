import human_readable as hr
import datetime as dt
import time
import discord.ext.commands as commands
import discord.ext.tasks as tasks
from discord.ext.commands import Context
from .entity import *


# noinspection SpellCheckingInspection
class GridMiiCogBase(commands.Cog):
    """Base class for GridMii cogs"""
    def __init__(self, bot: commands.Bot):
        # `bot` is actually a .gridbot.GridMiiBot, but that would be a circular import
        if not hasattr(bot, "mq_client"):
            raise TypeError("'bot' parameter is missing the 'mq_client' attribute (is it not a GridMiiBot?)")
        self.bot = bot

    async def cog_before_invoke(self, ctx: Context):
        # Automatically defer slash command interactions
        # Fail fast if the interaction expires before
        try:
            await ctx.defer()
        except discord.errors.NotFound:
            raise commands.CommandError("interaction expired before it could be deferred")

    async def cog_check(self, ctx: Context) -> bool:
        """Check for appropriate channel and user"""
        # If a channel was specified in the config, only allow commands in that channel.
        channel_ok =  ctx.channel.id == Config.CHANNEL or Config.CHANNEL is None
        # Don't let banned users use the cog
        return channel_ok and ctx.author.id not in Config.BANNED_USERS


    @property
    def mq_client(self) -> aiomqtt.Client:
        """Returns the MQTT client associated with the bot"""
        client: aiomqtt.Client = getattr(self.bot, "mq_client")
        return client


# noinspection SpellCheckingInspection
class UserCommandCog(GridMiiCogBase, name="User Commands"):
    """Cog for GridMii commands regular users can use"""
    @commands.command(name="yougood")
    async def ping(self, ctx: Context):
        """Check connectivity to broker"""
        # noinspection PyProtectedMember
        if self.mq_client is None:
            await ctx.reply(":-1: mq_client is None")
        elif self.mq_client._disconnected.done():
            # XXX: aiomqtt doesn't seem to expose this in a saner way
            await ctx.reply(":-1: mq_client._disconnected has come to pass")
        else:
            await ctx.reply(":+1:")

    @commands.command()
    async def nodes(self, ctx: Context):
        """View available nodes"""
        if node_table.has_nodes():
            message = '\n'.join(f"* {n}" for n in node_table)
        else:
            message = "No nodes are online"
        await ctx.reply(message)

    @commands.command()
    async def locus(self, ctx: Context, target: str|None=None):
        """Manually set the locus node for new jobs"""
        prefs = UserPrefs.get_prefs(ctx.author)
        content = ""

        if target is None:
            # query the current locus
            their_locus = prefs.locus
            if their_locus is None:
                content = "You don't have a locus node set."
            elif their_locus.is_present:
                content = f"Commands are being sent to `{their_locus.node_name}`."
            else:
                content = f":warning: Commands are being sent to `{their_locus.node_name}`, but that node isn't present."

        else:
            candidates = node_table.nodes_by_name(target)
            match candidates:
                case []:
                    # no match
                    content = f":x: `{target}` is not in the node table."
                case [new_locus]:
                    # one match; set new locus
                    prefs.locus = new_locus
                    content = f":+1: Your commands will now run on `{new_locus}`"
                case _:
                    content = f":question: `{target}` matches multiple nodes:\n"
                    for node in candidates:
                        content += f"- `{node.node_name}`\n"
                    content += "\nPlease specify exactly one of the above nodes."

        await ctx.reply(content)

    @commands.command()
    async def jobs(self, ctx: Context):
        """View running jobs"""
        def _line(job: Job):
            output_message = job.output_handler.output_message
            job_ctx = job.output_handler.ctx

            if job_ctx:
                author = job_ctx.author
                # not everybody has a nickname, fall back to username in that case
                name = author.nick if author.nick else author.name
            else:
                name = "None"

            # calculate and format elapsed time
            cur_time = time.monotonic()
            sec = cur_time - job.start_time
            elapsed = hr.precise_delta(dt.timedelta(seconds=sec))

            # format this information
            return f"* #{job.jid}, started by **{name}**, on `{job.target_node}`, running for **{elapsed}**, see {output_message.jump_url}"

        if job_table.has_jobs():
            table = '\n'.join(_line(j) for j in job_table)
        else:
            table = "No jobs running"
        await ctx.reply(table)

    @commands.command()
    async def term(self, ctx: Context, term_name:str|None=None, columns:int=40, lines:int=20):
        prefs = UserPrefs.get_prefs(ctx.author)
        if term_name is None:
            # getter
            tty_spec = prefs.tty
            if not tty_spec:
                content = "tty mode is currently off"
            else:
                term, columns, lines = tty_spec
                content = f"TERM={term}, {columns} x {lines}"
            await ctx.reply(content)
        else:
            # setter
            if term_name == "off":
                # turn it off
                prefs.tty = None
                await ctx.reply(":+1: tty mode has been turned off")
            else:
                # turn it on or adjust the parameters
                if term_name == "on":
                    # use the defaults if they say !term on
                    term_name = "dumb"
                prefs.tty = (term_name, columns, lines)
                content = f":+1: tty mode has been turned on\nTERM={term_name}, {columns} x {lines}"
                await ctx.reply(content)

    @commands.command()
    async def rules(self, ctx: Context):
        """Shows the bot's rules"""
        try:
            with open("data/rules.md", 'rb') as rules_file:
                await ctx.reply(file=discord.File(rules_file))
        except FileNotFoundError:
            logging.error("data/rules.md not found")
            await ctx.reply("rules file not found")


# noinspection SpellCheckingInspection
class AdminCommandCog(GridMiiCogBase, name="Admin Commands"):
    """Cog for commands only admins can use"""
    async def cog_check(self, ctx: Context) -> bool:
        # deny if the generic check fails
        if not await super().cog_check(ctx):
            return False
        # approve if any of the user roles are in the admin role set
        user_roles = [r.id for r in ctx.author.roles]
        for admin_role in Config.ADMIN_ROLES:
            if admin_role in user_roles:
                return True
        # otherwise deny
        logging.info(f"admin command denied for user '{ctx.author.display_name}' ({ctx.author.id})")
        return False

    @commands.command()
    async def scram(self, ctx: Context):
        """Terminate all jobs across the entire grid"""
        logging.warning("scram command called")
        try:
            await self.mq_client.publish("grid/scram", qos=2)
        except aiomqtt.MqttError as ex_mq:
            logging.exception("error publishing scram")
            await ctx.reply(f"**Couldn't send scram request**: {str(ex_mq)}")
        else:
            await ctx.reply(":+1: wait for the jobs to complete")

    @commands.command()
    async def reload(self, ctx: Context, node_name:str):
        """Instruct a node to reload its server (useful for updates)"""
        candidates = node_table.nodes_by_name(node_name)
        match candidates:
            case []:
                await ctx.reply(f":x: node {node_name} is not in the node table")
            case [node]:
                await node.reload(self.mq_client)
                await ctx.reply(f":+1: Reloaded `{node.node_name}`")
            case _:
                content = f":question: `{node_name}` matches multiple nodes!  Possible options:\n"
                for node in candidates:
                    content += f"- `{node.node_name}`\n"
                content += "\nPlease specify exactly one of the above nodes."
                await ctx.reply(content)

    @commands.command()
    async def eject(self, ctx: Context, node_name:str):
        """Eject a node from the grid.
        WARNING: if jobs are running, output will be lost"""
        candidates = node_table.nodes_by_name(node_name)
        match candidates:
            case []:
                # no match
                await ctx.reply(f":x: Node {node_name} is not present")
            case [node]:
                # unambiguous match
                await node.eject(self.mq_client)
                await ctx.reply(":+1:")
            case _:
                # ambiguous
                names = ', '.join(n.node_name for n in candidates)
                await ctx.reply(f":question: Ambiguous name could be: {names}")


    @commands.command()
    async def abandon(self, ctx: Context, jid:int):
        """Immediately flush the output of the specified job and remove it from the job table"""
        # This is an admin-only command now because it could lead to data loss if misused
        if not job_table.jid_present(jid):
            await ctx.reply(f":x: job #{jid} is not in the job table")
            return
        job = job_table.by_jid(jid)
        await job.abandon(self.mq_client)
        await ctx.reply(f":+1: see {job.output_message.jump_url}")

    @commands.command()
    async def rollcall(self, ctx: Context):
        """Force a roll call"""
        await self.mq_client.publish("grid/roll_call", qos=2)
        await ctx.reply(":+1:")


# noinspection SpellCheckingInspection
class JobControlCog(GridMiiCogBase, name="Job Control"):
    """Cog that contains commands to interact with a running job.
    For all of these commands, the job is specified by sending a command as a reply to the job's status/output message"""
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @staticmethod
    def job_for_reply(ctx: Context) -> Job | None:
        """Attempt to find a job based on what message the user is replying to.
        Returns None if the job is gone or there was no job in the first place"""
        msg = ctx.message
        if msg.type != discord.MessageType.reply:
            return None
        replied_msg_id = msg.reference.message_id
        # scan for messages
        for job in job_table:
            if job.output_handler.output_message.id == replied_msg_id:
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
        """Close a job's stdin, like Ctrl-D does"""
        job = self.job_for_reply(ctx)
        if job is not None:
            await job.eof(self.mq_client)

    @commands.command()
    async def signal(self, ctx: Context, signal_num: int):
        """Send a signal (specified by numeric code) to a job"""
        job = self.job_for_reply(ctx)
        if job is not None:
            await job.signal(signal_num, self.mq_client)
            await ctx.reply(f"Sent signal {signal_num} to the job")

    @commands.command()
    async def kill(self, ctx: Context):
        """Send SIGKILL to a job (!ctrl-c is preferable)"""
        await self.signal(ctx, 9)    # SIGKILL is 9 on all platforms I can see

    @commands.command(name="ctrl-c")
    async def ctrlc(self, ctx: Context):
        """Send SIGINT (Ctrl-C) to a job"""
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

class AutoRollCallCog(GridMiiCogBase):
    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        self.auto_roll_call.start()

    def cog_unload(self) -> None:
        self.auto_roll_call.cancel()

    @tasks.loop(hours=1)
    async def auto_roll_call(self):
        if self.mq_client:
            logging.info("performing roll call")
            await self.mq_client.publish("grid/roll_call", qos=2)





