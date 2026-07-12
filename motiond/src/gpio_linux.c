#define _POSIX_C_SOURCE 200809L

#include "gpio_linux.h"

#include <errno.h>
#include <fcntl.h>
#include <linux/gpio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>

/** Retains the GPIO chip and anonymous line-request file descriptors. */
struct gpio_linux {
    int chip_fd;
    int request_fd;
};

static int linux_set_line(void *context, enum motion_line line, bool high);
static uint64_t linux_now_ns(void *context);
static int linux_sleep_until_ns(void *context, uint64_t deadline_ns);

struct gpio_linux *gpio_linux_create(
    const char *chip_path,
    const unsigned int offsets[4],
    struct motion_backend *backend
) {
    if (chip_path == NULL || offsets == NULL || backend == NULL) {
        return NULL;
    }
    struct gpio_linux *gpio = calloc(1, sizeof(*gpio));
    if (gpio == NULL) {
        return NULL;
    }
    gpio->chip_fd = -1;
    gpio->request_fd = -1;
    gpio->chip_fd = open(chip_path, O_RDONLY | O_CLOEXEC);
    if (gpio->chip_fd < 0) {
        gpio_linux_destroy(gpio);
        return NULL;
    }
    struct gpio_v2_line_request request;
    memset(&request, 0, sizeof(request));
    for (unsigned int index = 0; index < 4; index += 1) {
        request.offsets[index] = offsets[index];
    }
    request.num_lines = 4;
    strncpy(request.consumer, "barrobot-motiond", sizeof(request.consumer) - 1);
    request.config.flags = GPIO_V2_LINE_FLAG_OUTPUT;
    request.config.num_attrs = 1;
    request.config.attrs[0].attr.id = GPIO_V2_LINE_ATTR_ID_OUTPUT_VALUES;
    request.config.attrs[0].attr.values = 1ULL << MOTION_LINE_ENABLE;
    request.config.attrs[0].mask = 0x0FULL;
    if (ioctl(gpio->chip_fd, GPIO_V2_GET_LINE_IOCTL, &request) < 0) {
        gpio_linux_destroy(gpio);
        return NULL;
    }
    gpio->request_fd = request.fd;
    backend->context = gpio;
    backend->set_line = linux_set_line;
    backend->now_ns = linux_now_ns;
    backend->sleep_until_ns = linux_sleep_until_ns;
    return gpio;
}

void gpio_linux_destroy(struct gpio_linux *gpio) {
    if (gpio == NULL) {
        return;
    }
    if (gpio->request_fd >= 0) {
        struct gpio_v2_line_values values = {
            .bits = 1ULL << MOTION_LINE_ENABLE,
            .mask = 0x0FULL,
        };
        ioctl(gpio->request_fd, GPIO_V2_LINE_SET_VALUES_IOCTL, &values);
        close(gpio->request_fd);
    }
    if (gpio->chip_fd >= 0) {
        close(gpio->chip_fd);
    }
    free(gpio);
}

static int linux_set_line(void *context, enum motion_line line, bool high) {
    struct gpio_linux *gpio = context;
    struct gpio_v2_line_values values = {
        .bits = high ? 1ULL << (unsigned int)line : 0,
        .mask = 1ULL << (unsigned int)line,
    };
    return ioctl(gpio->request_fd, GPIO_V2_LINE_SET_VALUES_IOCTL, &values);
}

static uint64_t linux_now_ns(void *context) {
    (void)context;
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now) != 0) {
        return 0;
    }
    return (uint64_t)now.tv_sec * 1000000000ULL + (uint64_t)now.tv_nsec;
}

static int linux_sleep_until_ns(void *context, uint64_t deadline_ns) {
    (void)context;
    const struct timespec deadline = {
        .tv_sec = (time_t)(deadline_ns / 1000000000ULL),
        .tv_nsec = (long)(deadline_ns % 1000000000ULL),
    };
    int result;
    do {
        result = clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &deadline, NULL);
    } while (result == EINTR);
    return result == 0 ? 0 : -1;
}
