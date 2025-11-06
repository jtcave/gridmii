# load config file
import tomllib
import discord



class Config:
    # These defaults are used during testing,
    # You still need to call load_config to fill these with sensible data.
    TOKEN: str = ""
    GUILD: discord.Object|None = None
    CHANNEL: str|None = None
    ADMIN_ROLES: list[int] = []
    BANNED_USERS: list[int] = []
    BROKER: str = ""
    PORT: int = 0
    MQTT_TLS: bool = False
    MQTT_USERNAME: str = ""
    MQTT_PASSWORD: str = ""
    NOTIFY_LIMIT: int = 60
    MIN_REPORT_SEC: int = 1
    OCI_CONFIG_FILE: str|None = None

    @classmethod
    def load_config(cls, config_path: str):
        with open(config_path, 'rb') as config_file:
            config = tomllib.load(config_file)
            # Discord info
            cls.TOKEN = config['token']
            cls.GUILD = discord.Object(id=config['guild'])
            cls.CHANNEL = config.get("channel", None)
            cls.ADMIN_ROLES = config.get("admin_roles", [])
            cls.BANNED_USERS = config.get("banned_users", [])
            # MQTT broker info
            cls.BROKER = config["mqtt_broker"]
            cls.PORT = config["mqtt_port"]
            cls.MQTT_TLS = config.get("mqtt_tls", False)
            cls.MQTT_USERNAME = config.get("mqtt_username", "")
            cls.MQTT_PASSWORD = config.get("mqtt_password", "")
            # job completion notification
            cls.NOTIFY_LIMIT = config.get("notify_limit", 60)
            cls.MIN_REPORT_SEC = config.get("min_report_sec", 1)
            # OCI info (for file downloads)
            cls.OCI_CONFIG_FILE = config.get("oci_config_file", None)