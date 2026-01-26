# load config file
import tomllib

class Config:
    # These defaults are used during testing,
    # You still need to call load_config to fill these with sensible data.
    BROKER: str = ""
    PORT: int = 0
    MQTT_TLS: bool = False
    MQTT_USERNAME: str = ""
    MQTT_PASSWORD: str = ""
    KEEPALIVE: int = 60
    OCI_CONFIG_FILE: str|None = None

    @classmethod
    def load_config(cls, config_path: str):
        with open(config_path, 'rb') as config_file:
            config = tomllib.load(config_file)
            # MQTT broker info
            cls.BROKER = config["mqtt_broker"]
            cls.PORT = config["mqtt_port"]
            cls.MQTT_TLS = config.get("mqtt_tls", False)
            cls.MQTT_USERNAME = config.get("mqtt_username", "")
            cls.MQTT_PASSWORD = config.get("mqtt_password", "")
            cls.KEEPALIVE = config.get("mqtt_keepalive", 60)
            # OCI info (for file downloads)
            cls.OCI_CONFIG_FILE = config.get("oci_config_file", None)
