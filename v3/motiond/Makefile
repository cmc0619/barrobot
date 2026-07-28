CC ?= cc
CPPFLAGS := -Iinclude
CFLAGS := -std=c11 -O2 -Wall -Wextra -Werror -Wpedantic -Wconversion -Wshadow -pthread
LDFLAGS := -pthread
BUILD_DIR := build
DAEMON := $(BUILD_DIR)/barrobot-motiond
TEST := $(BUILD_DIR)/test-motion

.PHONY: all clean test

all: $(DAEMON)

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(DAEMON): src/server.c src/motion.c src/gpio_linux.c include/motion.h include/gpio_linux.h | $(BUILD_DIR)
	$(CC) $(CPPFLAGS) $(CFLAGS) src/server.c src/motion.c src/gpio_linux.c -o $@ $(LDFLAGS)

$(TEST): tests/test_motion.c src/motion.c include/motion.h | $(BUILD_DIR)
	$(CC) $(CPPFLAGS) $(CFLAGS) -fsanitize=address,undefined tests/test_motion.c src/motion.c -o $@ $(LDFLAGS) -fsanitize=address,undefined

test: $(TEST)
	ASAN_OPTIONS=detect_leaks=0 $(TEST)

clean:
	rm -rf $(BUILD_DIR)
