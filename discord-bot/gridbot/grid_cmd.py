import discord.ext.commands as commands
from discord.ext.commands import Context
# from .gridbot import GridMiiBot
from .entity import *

class UserCommandCog(commands.Cog, name="User Commands"):
    """Cog for GridMii commands regular users can use"""
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="yougood")
    async def ping(self, ctx: Context):
        """Check connectivity to broker"""
        if self.bot.mq_client is None:
            await ctx.reply(":-1: mq_client is None")
        elif self.bot.mq_client._disconnected.done():
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
    def __init__(self, bot: commands.Bot):
        self.bot = bot

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
            await self.bot.mq_client.publish("grid/scram")
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
            await node.reload(self.bot.mq_client)
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
            await node.eject(self.bot.mq_client)
        # no need to send an ack reply because the node should disconnect

class JobControlCog(discord.ext.commands.Cog, name="Job Control"):
    """Cog that contains commands to interact with a running job"""
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
            await job.eof(self.bot.mq_client)

    @commands.command()
    async def signal(self, ctx: Context, signal_num: int):
        """Send a signal (numeric code) to a job"""
        job = self.job_for_reply(ctx)
        if job is not None:
            await job.signal(signal_num, self.bot.mq_client)
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

DEFAULT_COGS = (UserCommandCog, AdminCommandCog, JobControlCog)