#ifndef BARROBOT_GPIO_LINUX_H
#define BARROBOT_GPIO_LINUX_H

#include "motion.h"

struct gpio_linux;

/** Requests the existing BCM output lines from a Linux GPIO v2 character device. */
struct gpio_linux *gpio_linux_create(
    const char *chip_path,
    const unsigned int offsets[4],
    struct motion_backend *backend
);

/** Restores safe output values and releases the GPIO line request. */
void gpio_linux_destroy(struct gpio_linux *gpio);

#endif
