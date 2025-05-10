#!/bin/sh

NODE_BIN="gm-node"
CONFIG_FILE="gm-node.conf"

if [ ! -r "$CONFIG_FILE" ]
then
    echo "Can't find config file \`$CONFIG_FILE\`. Make sure it exists and can be read by this user." >&2
    exit 1
elif [ ! -x "$NODE_BIN" ]
then
    echo "Can't find executable \`$NODE_BIN\`. Make sure it exists and is executable."
    echo 'Try running `make` or `gmake`.'
    exit 1
else
    . $CONFIG_FILE
    exec ./$NODE_BIN
fi