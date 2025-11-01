import logging

import discord.ext.commands as commands
from discord.ext.commands import Context

from .grid_cmd import GridMiiCogBase
from .config import Config

try:
    import oci
except ModuleNotFoundError:
    oci = None

oci_config = dict()
RELAY_BUCKET = "relay_bucket"

def oci_setup() -> bool:
    """Load OCI config and check whether OCI is set up correctly"""
    if oci is None or Config.OCI_CONFIG_FILE is None:
        return False
    cfg = oci.config.from_file(Config.OCI_CONFIG_FILE)
    oci.config.validate_config(cfg)
    if RELAY_BUCKET not in cfg:
        logging.warning("please specify `relay_bucket` in the OCI config")
        return False
    oci_config.update(cfg)
    return True

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

    DOWNLOAD_SCRIPT = """
    if command -v curl > /dev/null
    then
      echo Uploading:
      echo '{0}'
      curl -s -T '{0}' '{1}'
    else
      echo Please install curl
      exit 1
    fi
    """

    def __init__(self, bot):
        super().__init__(bot)
        self.oci_ok = False
        self.object_storage = None
        self.object_namespace = None
        self.bucket = None

    async def cog_load(self) -> None:
        # TODO: split this into an OracleCloudCog
        try:
            self.oci_ok = oci_setup()
        except oci.exceptions.ClientError:
            logging.exception("failed to load OCI config")
            self.oci_ok = False
        if not self.oci_ok:
            logging.warning("OCI not set up; file download not available")
        else:
            try:
                logging.info("Contacting OCI...")
                self.object_storage = oci.object_storage.ObjectStorageClient(oci_config)
                self.object_namespace = self.object_storage.get_namespace().data
            except (oci.exceptions.ClientError, oci.exceptions.ServiceError):
                logging.exception("OCI threw exception during cog setup")
                self.oci_ok = False
            # While we're here, let's make sure the OCI bucket actually exists
            bucket_name = oci_config[RELAY_BUCKET]
            try:
                bucket_resp = self.object_storage.get_bucket(self.object_namespace, bucket_name)
                self.bucket = bucket_resp.data
                logging.info(f"Using OCI object bucket {bucket_name} as the file relay")
            except oci.exceptions.ServiceError as se:
                logging.exception(f"{se.code}: {se.message}")
                self.oci_ok = False

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

    @commands.command()
    async def download(self, ctx: Context, file: str):
        if not self.oci_ok:
            await ctx.reply(":x: File downloads are not currently available")
            return
        await ctx.reply("***TODO STUB***, but OCI is operational :+1:")