CFLAGS=-Wall -g
LDLIBS=-lmosquitto

HEADERS = gm-node.h gm-node-config.h
MODULES = mqtt.c jobs.c eventloop.c controller.c gm-node.c

all: gm-node

gm-node: $(HEADERS) $(MODULES)

clean:
	rm -f gm-node *.o

.PHONY: clean