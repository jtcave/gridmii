# GridMii

GridMii is a distributed public-access computing system, meant to power the "Wii Bot" found in the [Wii Linux](https://wii-linux.org/) Discord server.

## About

The first Wii Bot was a Python script running on a Wii owned by a (former) user on the Wii Linux Discord server. This bot would run commands sent by users on the Wii, creating a simple public-access computing environment. However, the script was primitive, and the Python interpreter consumed a prohibitive amount of memory. (The Wii only has 88 MB of RAM, of which only 72 MB can be used by Linux.) 

GridMii is a more refined version of this idea. The goal is to create a public-access computing environment. Users will be able to send commands to one of a set of community-operated nodes.  By using the MQTT protocol, GridMii's node-end software can be small and simple, offloading system complexity to more capable modern machines.

There is nothing Wii-specific about GridMii, 

## Components

### MQTT broker

GridMii relies on an MQTT broker to pass messages between the nodes and the node controller.

### node server (WIP)

A small server program is responsible for starting processes, controlling standard input/output, and 

### grid controller (TODO)

The grid controller will collect node telemetry, route user commands to nodes, and provide a view of the system to users and administrators.

### Discord bot (TODO)

The user interface to GridMii will be a Discord bot. This is convenient for the Wii Linux community, and will also allow offloading some of the IAM tasks to Discord.