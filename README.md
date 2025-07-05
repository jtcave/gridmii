# GridMii

GridMii is the distributed public-access computing system meant to power the "Wii Bot 2" found in the [Wii-Linux](https://wii-linux.org/) Discord server.

## About

A (former) user of the Wii Linux Discord server created a simple Python script, called Wii Bot, that would run commands sent by users on his Wii. The script was primitive, and the Python interpreter consumed a large amount of the scarce RAM on the Wii. However, the bot was popular, and demand remained even after the operator had to shut it down.

GridMii is a more refined version of Wii Bot. The goal is to create a distributed public-access computing environment. Users can send commands to one of a set of community-operated nodes. By using the MQTT protocol, GridMii's node-end software can be small and simple, offloading system complexity to more capable modern machines and allowing prospective operators to spin up nodes easily.

There is nothing about GridMii that is specific to Wii-Linux. This code can be used to control Linux or BSD systems running on any suitable hardware; the node server is regularly tested on ARM macOS in addition to the intended PPC Linux.

## Components

### MQTT broker

GridMii uses an MQTT broker to pass messages between the nodes and the node controller. Using a broker as an intermediary allows nodes to operate even in situations where inbound connections are impossible, such as carrier-grade NAT.

### node server

A server program running on each node is responsible for starting processes, relaying standard input/output to the grid, and reporting job status to the front end.

### front end

The front end of GridMii is a Discord bot. This bot routes user commands to nodes and relays output back to users. This is a convenient user interface for the Wii-Linux community, and will also allow offloading some of the IAM tasks to Discord.

## Status

### What works

* Sending commands to a node
* Viewing command output
* Sending text to process stdin
* Sending signals to a process

### What is missing

* Shared state/files between nodes
* Per-user state
* Access control for nodes (currently everyone can access any node)
* Node sandboxing

## Warning

The nature of this software allows users to execute arbitrary commands. You may not know these users, and they may execute commands with malicious effects you did not anticipate. You are encouraged to monitor use of your systems, to keep backups, and to perform defense-in-depth security measures to protect your data, including on devices you own that are not directly using the software. 
