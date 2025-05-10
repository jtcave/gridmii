#!/bin/sh

NODE_BIN="gm-node"
CONFIG_FILE="gm-node.conf"
CERT_FILE="gridmii.crt"

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
    . ./$CONFIG_FILE
    # demand a cert only if TLS is set 
    if [ ! -r "$CERT_FILE" -a -n "$GRID_TLS" ]
    then
        echo "You requested TLS, but the certificate seems to be missing."
        echo "Please place your certificate, named \`$CERT_FILE\`, in the current directory."
        echo "Alternatively, remove the GRID_TLS variable from your config file."
        exit 1
    fi
    exec ./$NODE_BIN
fi