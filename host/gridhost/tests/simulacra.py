# simulacra for unit testing
# these are mock objects for discord.py and aiomqtt objects

import unittest.mock as mock

def mock_mqtt():
    mqttoid = mock.AsyncMock()
    # emulate the innards we reach into
    mqttoid._disconnected.done = lambda: False
    return mqttoid

def mock_bot():
    botoid = mock.Mock()
    botoid.mq_client = mock_mqtt()
    return botoid

def mock_context():
    return mock.AsyncMock()

def mock_message():
    return mock.AsyncMock()

def mock_config():
    class FakeConfig: pass
    FakeConfig.NOTIFY_LIMIT = 600
    FakeConfig.MIN_REPORT_SEC = 600
    return FakeConfig