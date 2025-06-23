# GridMii node server

This is the part of GridMii that runs on the nodes and accepts commands from the bot.

The node server should build on most POSIX-ish systems (I've tested on Linux/powerpc, Linux/aarch64, NetBSD/evbppc, and macOS/arm64.) The only build-time dependency is libmosquitto.

## Setup instructions for Arch Linux

1) Make sure you have a working C compiler toolchain. If you don't, install the `base-devel` group:
   ```
   sudo pacman -Syu
   sudo pacman -S base-devel
   ```

2) Install the `mosquitto` package:
   ```
   sudo pacman -S mosquitto
   ```
   Note: this package is not part of ArchPOWER, but it is available in the Wii-Linux `[extra]` repository

3) You do *not* need the Mosquitto message broker running on the node. Assuming you don't want to run a broker, ensure it's disabled:
   ```
   sudo systemctl disable --now mosquitto.service
   ```
   
4) Build the node server:
   ```
   make
   ```
   There's no `./configure` script to run, and at the moment, there's no `make install` target.

5) Create a `gm-node.conf` file specifying, at minimum, the MQTT broker settings. Place it in the same directory as the `gm-node` executable that was just built. Refer to `gm-node.conf.example` as a starting point.
6) If you're using TLS, place the MQTT broker certificate in the same directory as the `gm-node` executable. Name the certificate file `gridmii.crt`.
7) Start the node server:
   ```
   ./start_node.sh
   ```

The node server can be stopped by pressing Ctrl-C. If you want to run the node server in the background, run it in a `tmux` session and detach from the session.

## Notes for other platforms

### Debian and Ubuntu

You can follow the same instructions as above, except replace the pacman commands with:

```
sudo apt install build-essential libmosquitto-dev
```

This won't install the mosquitto server, so you can go to step 4

### NetBSD

```
pkgin in mosquitto gmake
```

The Makefile requires GNU Make; it will not build with the NetBSD `make` command

### macOS

```
brew install mosquitto
```

## Isolating jobs

You may wish to isolate jobs from the host in a container, a chroot, or some other isolation mechanism. You can set the `GRID_JOB_SHELL` environment variable to a script or program that forwards the job into the containment area.

As an example, the `contain.sh` script will run a job in a systemd container named `gridmii-container` by copying the job script into the container and running it.

***TODO: instructions on setting up systemd containers***

## Configuration reference

### `GRID_HOST`

Specify the host name of the MQTT broker. Defaults to `localhost`.

### `GRID_PORT`

Specify the TCP port of the MQTT broker. Defaults to `1883`

### `GRID_TLS`

If this environment variable is set, instructs the node server to use TLS to communicate with the MQTT broker. This option requires that the file `gridmii.crt` be present in the working directory.

### `GRID_USERNAME`

If set, use the specified username to authenticate with the MQTT broker.

### `GRID_PASSWORD`

If set, use the specified password to authenticate with the MQTT broker.

### `NODE_NAME`

Set the name of the node. (Node names are how users specify what node to run jobs on.) Defaults to the machine's hostname.

### `GRID_JOB_CWD`

Set the working directory of jobs. The node server will `chdir` to this directory. If not set, defaults to `$HOME`, the user's home directory, or `/` if that is not set.

(Note: setting this will only work if commands are being run directly on the node. Container relay scripts will have to set the working directory another way.)

### `GRID_JOB_SHELL`

Use the given shell or interpreter to run job scripts. Defaults to `/bin/sh`.