CFLAGS=-Wall -Os
LDLIBS=-lmosquitto -ljansson

# pull in Homebrew on macOS
OSNAME := $(shell uname -s)
ifeq "$(OSNAME)" "Darwin"
	CFLAGS +=  -I/opt/homebrew/include -L/opt/homebrew/lib
endif

# pull in package libs on NetBSD
ifeq "$(OSNAME)" "NetBSD"
        CFLAGS +=  -I/usr/pkg/include -L/usr/pkg/lib
endif

HEADERS = gm-node.h gm-node-config.h
MODULES = mqtt.c jobs.c controller.c gm-node.c

all: gm-node

gm-node: $(HEADERS) $(MODULES)
	$(CC) $(CFLAGS) -o gm-node  $(MODULES) $(LDLIBS)

clean:
	rm -rf gm-node *.o *.dSYM

.PHONY: clean
