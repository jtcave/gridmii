CFLAGS=-Wall -Os
LDLIBS=-lmosquitto -ljansson

# pull in Homebrew includes/libs on macOS
OSNAME := $(shell uname -s)
ifeq "$(OSNAME)" "Darwin"
	CPPFLAGS +=  -I/opt/homebrew/include
	LDFLAGS  +=  -L/opt/homebrew/lib
endif

# pull in package libs on NetBSD
ifeq "$(OSNAME)" "NetBSD"
	CPPFLAGS +=  -I/usr/pkg/include
	LDFLAGS  +=  -L/usr/pkg/lib
endif

# source directory
SOURCE = src

HEADERS = $(SOURCE)/gm-node.h $(SOURCE)/gm-node-config.h $(SOURCE)/version.h

MODULES = mqtt.c jobs.c controller.c gm-node.c

OUT = bin/gm-node
OBJ = $(patsubst %.c,build/%.o,$(MODULES))

GIT_VERSION := "$(shell git describe --dirty --always --tags)"

all: $(OUT)

$(SOURCE)/version.h: ../.git/index
	printf '#ifndef GIT_VERSION\n#define GIT_VERSION "%s"\n#endif\n' "$(GIT_VERSION)" > $@

$(SOURCE)/gm-node.h: $(SOURCE)/version.h

$(OUT): $(HEADERS) $(OBJ)
	@mkdir -p $(@D)
	$(CC) $(CFLAGS) $(LDFLAGS) -o $(OUT) $(OBJ) $(LDLIBS)

build/%.o: $(SOURCE)/%.c
	@mkdir -p $(@D)
	$(CC) $(CFLAGS) $(CPPFLAGS) -o $@ -c $<


# TODO: drop the first line of this task
# It cleans up builds made with an older version of the Makefile
clean:
	rm -rf gm-node *.o *.dSYM version.h
	rm -rf bin build $(SOURCE)/version.h


.PHONY: clean
