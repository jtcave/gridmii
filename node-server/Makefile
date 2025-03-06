CFLAGS=-Wall -g
LDLIBS=-lmosquitto

all: gm-node

gm-node: gm-node.h  mqtt.c jobs.c eventloop.c controller.c gm-node.c

clean:
	rm -f gm-node *.o

.PHONY: clean