# GridMii node server

This is the part of GridMii that runs on the nodes and accepts commands from the bot.

The node server should build on most POSIX-ish systems (I've tested on Linux/powerpc, Linux/aarch64, NetBSD/evbppc, and macOS/arm64.) The only build-time dependency is libmosquitto.

## Arch Linux setup instructions

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
