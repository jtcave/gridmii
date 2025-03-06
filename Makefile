CFLAGS=-Wall -g
LDLIBS=-lmosquitto

all: gridmii

gridmii: gridmii.h  mqtt.c jobs.c eventloop.c controller.c gridmii.c

clean:
	rm -f gridmii *.o

.PHONY: clean