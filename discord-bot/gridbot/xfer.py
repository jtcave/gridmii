import datetime
import io
import logging
import secrets

import discord
import discord.ext.commands as commands
from discord.ext.commands import Context
import aiohttp

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
      curl -OsS '{0}'
    else
      echo Please install curl, then download this url:
      echo '{0}'
    fi
    """

    DOWNLOAD_SCRIPT = """
    f='{0}'
    if ! command -v curl > /dev/null
    then
      echo Please install curl
      exit 1
    else
      if [ $(du -k "$f" | cut -f 1) -gt 8192 ]
      then
        echo File too large
        exit 2
      else
        echo Uploading:
        echo "$f"
        curl -sS -T "$f" '{1}'
      fi
    fi
    """

    def __init__(self, bot):
        super().__init__(bot)
        self.oci_ok = False
        self.object_storage: oci.object_storage.ObjectStorageClient|None = None
        self.object_namespace = None
        self.bucket: oci.object_storage.models.Bucket|None = None

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

    def make_par(self, object_name: str):
        now = datetime.datetime.now(datetime.timezone.utc)
        expiration_delta = datetime.timedelta(days=1)
        expiration = now + expiration_delta
        par_params = oci.object_storage.models.CreatePreauthenticatedRequestDetails(
            name="par_" + object_name,
            object_name = object_name,
            access_type="ObjectReadWrite",
            time_expires=expiration
        )
        par = self.object_storage.create_preauthenticated_request(
            self.bucket.namespace, self.bucket.name, par_params).data
        return par

    async def download_and_attach(self, ctx: Context, url: str, file_name: str):
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status != 200:
                    logging.error("HTTP problem", response)
                    await ctx.reply(f":x: Couldn't download the file from the relay: HTTP {response.status}")
                    return

                body = io.BytesIO()
                try:
                    body.write(await response.read())
                    body.seek(0)
                    attachment = discord.File(body, file_name)
                    await ctx.reply(file=attachment)
                except aiohttp.ClientError as exc:
                    logging.exception(f"Failed download for file {file_name}")
                    await ctx.reply(f":x: Couldn't download the file from the relay: {exc}")
                finally:
                    body.close()

    @commands.command()
    async def upload(self, ctx: Context):
        """Upload the attached file to your current node."""
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
        """Download the given file from your current node"""
        if not self.oci_ok:
            await ctx.reply(":x: File downloads are not currently available")
            return

        logging.info(f"Downloading file {file}")
        relay_object_name = secrets.token_urlsafe()
        par = self.make_par(relay_object_name)
        par_url =  par.full_path
        logging.info(f"Access URL for relay upload: {par_url}")

        # pass the URI to the client, then make a callback
        script = self.DOWNLOAD_SCRIPT.format(file, par_url)
        async def download_ready(job, status_code):
            if status_code == 0:
                await self.download_and_attach(ctx, par_url, file)

        await self.bot.submit_job(ctx, script, callback=download_ready)