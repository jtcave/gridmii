# load config file
import tomllib
import discord



class Config:


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