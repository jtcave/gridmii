## startup procedure ##
from .gridbot import *

Config.load_config("data/config.toml")
bot.run(Config.TOKEN, root_logger=True)