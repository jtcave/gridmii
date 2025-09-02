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

HEADERS = gm-node.h gm-node-config.h version.h
MODULES = mqtt.c jobs.c controller.c gm-node.c

GIT_VERSION := "$(shell git describe --dirty --always --tags)"

all: gm-node

version.h: ../.git/index
	printf '#ifndef GIT_VERSION\n#define GIT_VERSION "%s"\n#endif\n' "$(GIT_VERSION)" > version.h

gm-node.h: version.h

gm-node: $(HEADERS) $(MODULES)
	$(CC) $(CFLAGS) -o gm-node  $(MODULES) $(LDLIBS)

clean:
	rm -rf gm-node *.o *.dSYM version.h

.PHONY: clean
