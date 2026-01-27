import asyncio
import json
import aiomqtt
import logging

from .config import Config
from .entity import Job, Node, job_table, node_table
from .cmd_denylist import permit_command
from .get_version import GIT_VERSION


class GridMiiHost():
    """TCP server that accepts GridMii commands and processes MQTT messages"""
    def __init__(self):
        self.mqtt_task = None
        self.after_broker_connect_task = None
        self.broker_connected = asyncio.Event()
        self.mq_client: aiomqtt.Client|None = None
        self.mq_sent = set()
        self.can_announce = False

    async def setup_hook(self) -> None:
        logging.info(f"GridMii host version {GIT_VERSION}")
        # Install the MQTT task.
        self.mqtt_task = self.loop.create_task(self.do_mqtt_task())
        # Install the "after broker connection" task"
        self.after_broker_connect_task = self.loop.create_task(self.after_broker_connect())

    async def after_broker_connect(self):
        # Wait for the event to fire
        await self.broker_connected.wait()
        await asyncio.sleep(5)

    async def do_mqtt_task(self):
        """Coroutine that sets up the MQTT client and processes inbound messages.
        This is meant to be scheduled in the host's event loop."""
        if Config.MQTT_TLS:
            tls_params = aiomqtt.TLSParameters()
        else:
            tls_params = None

        logging.info("Starting MQTT task") # helpmii

        self.mq_client = aiomqtt.Client(Config.BROKER, Config.PORT,
                                        username=Config.MQTT_USERNAME, password=Config.MQTT_PASSWORD,
                                        tls_params=tls_params, keepalive=Config.KEEPALIVE)
        while True:
            try:
                async with self.mq_client:
                    logging.info("Connected to MQTT broker, now subscribing")
                    self.broker_connected.set()
                    # subscribe to our topics
                    for topic in ("job/#", "node/#"):
                        await self.mq_client.subscribe(topic, qos=2)
                    # send out a ping to enumerate the nodes
                    await self.ping_grid()
                    # handle messages
                    logging.info("MQTT ready")
                    async for msg in self.mq_client.messages:
                        await self.on_mqtt(msg)
            except aiomqtt.MqttError:
                self.broker_connected.clear()
                reconnect_delay = 3
                logging.exception(f"Lost connection to broker. Retrying in {reconnect_delay} seconds")
                await asyncio.sleep(reconnect_delay)
            except Exception as exc:
                logging.exception("Unhandled exception in MQTT task")
                # TODO: Broadcast to clients

    async def ping_grid(self):
        await self.mq_client.publish("grid/ping", qos=2)

    async def on_mqtt(self, msg: aiomqtt.Message):
        """MQTT message handler, called once per message"""
        logging.debug("MQTT %s: %s", str(msg.topic), msg.payload)
        topic_path = str(msg.topic).split('/')

        if not topic_path:
            return

        if topic_path[0] == "job" and len(topic_path) == 3:
            # job status update
            _, jid, event = topic_path
            jid = int(jid)
            if not job_table.jid_present(jid):
                logging.warning(f"got message for spurious job {jid}")
                return
            job = job_table.by_jid(jid)
            match event:
                case "stdout":
                    logging.debug(f"got job {jid} stdout: {msg.payload}")
                    await job.write(msg.payload)
                case "stderr":
                    logging.debug(f"got job {jid} stderr: {msg.payload}")
                    await job.write(msg.payload)
                case "startup":
                    logging.info(f"got job start message for {jid}")
                    await job.startup()
                case "reject":
                    logging.warning(f"got job rejection for {jid}")
                    await job.reject(msg.payload)
                case "stopped":
                    logging.info(f"got job stop message for {jid}")
                    await job.stopped(msg.payload)

        elif topic_path[0] == "node" and len(topic_path) == 2:
            # node status update
            payload = msg.payload.decode()
            match topic_path[1]:
                case "connect":
                    await self.on_node_present(payload)
                case "disconnect":
                    logging.info(f"node {payload} has left")
                    node_table.node_gone(payload)
                    await self.announce_node_gone(payload)
                case "announce":
                    logging.info(f"node announcement: {payload}")
                    await self.announce_string(payload)
                case "roll_call":
                    # decode response
                    try:
                        decoded = json.loads(payload)
                    except json.JSONDecodeError:
                        logging.exception(f"bad JSON in roll_call: {payload}")
                        return
                    # unpack response
                    if not ("node" in decoded and "jobs" in decoded):
                        logging.error(f"missing field(s) in JSON: {payload}")
                        return
                    node_name: str = decoded["node"]
                    job_list: list[int] = decoded["jobs"]
                    await self.on_roll_call_reply(node_name, job_list)

    # end async def on_mqtt

    async def on_node_present(self, payload: str):
        try:
            message = json.loads(payload)
            node_name = message["node"]
            node_version = message["version"]
        except json.JSONDecodeError:
            # legacy non-JSON
            node_name = payload
            node_version = None

        logging.info(f"node present: {node_name} version {node_version}")
        node_table.node_seen(node_name, node_version)
        # TODO: Broadcast to clients

    async def announce_node_gone(self, node_name: str):
        if self.can_announce:
            # TODO: Broadcast to clients
            pass

    async def announce_string(self, payload: str):
        # don't respect self.can_announce
        # these kinds of announcements aren't directly caused by us starting up
        # TODO: Broadcast to clients
        pass

    async def on_roll_call_reply(self, node_name: str, job_list: list[int]):
        # set of jobs that belong to the node
        node_jobs = {j for j in job_table if j.target_node == node_name}
        # known good jobs
        job_set = {job_table.by_jid(jid) for jid in job_list if job_table.jid_present(jid)}
        # jobs that belong to the node, but are not known good and hence should be abandoned
        bad_jobs = node_jobs - job_set
        for j in bad_jobs:
            logging.warning(f"job {j.jid} is lost")
            await j.abandon(self.mq_client)



    async def submit_job(self, node: Node, command_string: str, output_filter=None, callback=None):
        if self.mq_client is None:
            logging.error("GridMiiHost.mq_client is None!")
            # TODO: Broadcast to clients
            return

        # denylist
        if not permit_command(command_string):
            logging.warning(f"denied command: {command_string}")
            # TODO: Broadcast to clients
            return

        # Post the reply that job output will go to
        # TODO: Broadcast to clients that job is starting

        # Submit the job
        try:
            job = await node.submit_job(command_string, self.mq_client, output_filter, callback)
            host.loop.create_task(job.clean_if_unstarted())
        except aiomqtt.exceptions.MqttError as ex_mq:
            logging.exception("error publishing job submission")
            # TODO: Broadcast to clients that it failed

    async def stdin_post(self, payload: bytes, job: Job):
        await job.stdin(payload, self.mq_client)

host = GridMiiHost()
