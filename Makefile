CFLAGS=-Wall -g
LDLIBS=-lmosquitto

all: gridmii

gridmii: gridmii.h  mqtt.c jobs.c eventloop.c gridmii.c

# mqtt-hello: mqtt-hello.c mqtt.c gridmii.h

clean:
	rm -f gridmii *.o

.PHONY: clean