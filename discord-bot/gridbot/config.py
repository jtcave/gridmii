# load config file
import json
import discord

with open("data/config.json", 'r') as config_file:
    config = json.load(config_file)
TOKEN = config['token']
GUILD = discord.Object(id=config['guild'])
CHANNEL = config.get("channel", None)
ADMIN_ROLES = config.get("admin_roles", [])
BROKER = config["mqtt_broker"]
PORT = config["mqtt_port"]
MQTT_TLS = config.get("mqtt_tls", False)
MQTT_USERNAME = config.get("mqtt_username", "")
MQTT_PASSWORD = config.get("mqtt_password", "")
TARGET_NODE = config.get("target_node", None)