import discord.ext.commands as commands
from discord.ext.commands import Context

from .grid_cmd import GridMiiCogBase

class FileTransferCog(GridMiiCogBase):
    UPLOAD_SCRIPT = """
    if command -v curl > /dev/null
    then
      echo Downloading:
      echo '{0}'
      curl -Os '{0}'
    else
      echo Please install curl, then download this url:
      echo '{0}'
    fi
    """

    @commands.command()
    async def upload(self, ctx: Context):
        """Upload the attached file to your current node. Requires curl to be installed"""
        attachments = ctx.message.attachments
        if not attachments:
            await ctx.reply(":x: You need to attach one or more files")
            return
        elif len(attachments) > 1:
            await ctx.reply(":x: Currently only one file at a time can be uploaded")

        attachment, = attachments

        script = self.UPLOAD_SCRIPT.format(attachment.url)
        await self.bot.submit_job(ctx, script)