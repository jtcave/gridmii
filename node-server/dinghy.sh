#!/bin/sh

# simple script to run its first argument in a specific systemd container

# name of the container
MACHINE=gridmii-container
# shell to use
JOB_SHELL=/bin/sh

# copy the job script into the container
machinectl copy-to $MACHINE "$1" || exit 77

# run job script
systemd-run -P -q -M $MACHINE  $JOB_SHELL "$1"

# clean up job script
systemd-run -P -q -M $MACHINE  rm "$1"