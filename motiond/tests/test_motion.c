#include "motion.h"

#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

/** Records output transitions and monotonic deadlines without sleeping. */
struct fake_gpio {
    bool values[4];
    int step_rising_edges;
    int actuator_rising_edges;
    uint64_t now_ns;
    uint64_t last_deadline_ns;
    uint64_t intervals_us[8];
    int sleep_count;
};

static struct motion *new_motion(struct fake_gpio *gpio);

static int fake_set_line(void *context, enum motion_line line, bool high) {
    struct fake_gpio *gpio = context;
    if (line == MOTION_LINE_STEP && high && !gpio->values[line]) {
        gpio->step_rising_edges += 1;
    }
    if (line == MOTION_LINE_ACTUATOR && high && !gpio->values[line]) {
        gpio->actuator_rising_edges += 1;
    }
    gpio->values[line] = high;
    return 0;
}

static uint64_t fake_now_ns(void *context) {
    return ((struct fake_gpio *)context)->now_ns;
}

static int fake_sleep_until_ns(void *context, uint64_t deadline_ns) {
    struct fake_gpio *gpio = context;
    assert(deadline_ns >= gpio->last_deadline_ns);
    if (gpio->sleep_count < (int)(sizeof(gpio->intervals_us) / sizeof(gpio->intervals_us[0]))) {
        gpio->intervals_us[gpio->sleep_count] = (deadline_ns - gpio->last_deadline_ns) / 1000U;
    }
    gpio->sleep_count += 1;
    gpio->last_deadline_ns = deadline_ns;
    gpio->now_ns = deadline_ns;
    return 0;
}

static void test_s_curve_starts_without_a_speed_jump(void) {
    struct fake_gpio gpio;
    memset(&gpio, 0, sizeof(gpio));
    struct motion *motion = new_motion(&gpio);
    assert(motion_configure(motion, 100, 900, 5000, 0, true) == MOTION_OK);
    assert(motion_set_position(motion, 0) == MOTION_OK);
    assert(motion_arm(motion) == MOTION_OK);
    assert(motion_move(motion, 1) == MOTION_OK);
    assert(gpio.intervals_us[0] == 5000);
    assert(gpio.intervals_us[1] == 5000);
    assert(gpio.intervals_us[2] >= 4995);
    motion_destroy(motion);
}

static void test_conservative_timing_scale_slows_a_move(void) {
    struct fake_gpio baseline_gpio;
    struct fake_gpio slowed_gpio;
    memset(&baseline_gpio, 0, sizeof(baseline_gpio));
    memset(&slowed_gpio, 0, sizeof(slowed_gpio));
    struct motion *baseline = new_motion(&baseline_gpio);
    struct motion *slowed = new_motion(&slowed_gpio);
    assert(motion_set_position(baseline, 0) == MOTION_OK);
    assert(motion_set_position(slowed, 0) == MOTION_OK);
    assert(motion_arm(baseline) == MOTION_OK);
    assert(motion_arm(slowed) == MOTION_OK);
    assert(motion_move(baseline, 1) == MOTION_OK);
    assert(motion_move_scaled(slowed, 1, 150) == MOTION_OK);
    assert(slowed_gpio.intervals_us[0] == baseline_gpio.intervals_us[0] * 3U / 2U);
    assert(motion_move_scaled(slowed, 2, 99) == MOTION_INVALID);
    motion_destroy(baseline);
    motion_destroy(slowed);
}

static struct motion *new_motion(struct fake_gpio *gpio) {
    const struct motion_config config = {
        .slot_count = 12,
        .steps_per_revolution = 200,
        .microsteps = 8,
        .ramp_steps = 25,
        .minimum_half_period_us = 1200,
        .maximum_half_period_us = 6000,
        .settle_ms = 250,
        .hold_position = true,
        .clockwise_high = true,
        .enable_active_low = true,
        .actuator_active_high = true,
    };
    const struct motion_backend backend = {
        .context = gpio,
        .set_line = fake_set_line,
        .now_ns = fake_now_ns,
        .sleep_until_ns = fake_sleep_until_ns,
    };
    return motion_create(&config, &backend);
}

static void test_startup_and_arm_require_position(void) {
    struct fake_gpio gpio;
    memset(&gpio, 0, sizeof(gpio));
    struct motion *motion = new_motion(&gpio);
    assert(motion != NULL);
    const struct motion_status initial = motion_get_status(motion);
    assert(!initial.armed);
    assert(initial.position == -1);
    assert(motion_arm(motion) == MOTION_POSITION_UNKNOWN);
    assert(motion_set_position(motion, 0) == MOTION_OK);
    assert(motion_arm(motion) == MOTION_OK);
    motion_destroy(motion);
}

static void test_full_revolution_is_exact(void) {
    struct fake_gpio gpio;
    memset(&gpio, 0, sizeof(gpio));
    struct motion *motion = new_motion(&gpio);
    assert(motion_set_position(motion, 0) == MOTION_OK);
    assert(motion_arm(motion) == MOTION_OK);
    for (int slot = 1; slot < 12; slot += 1) {
        assert(motion_move(motion, slot) == MOTION_OK);
    }
    assert(motion_move(motion, 0) == MOTION_OK);
    assert(gpio.step_rising_edges == 1600);
    motion_destroy(motion);
}

static void test_tie_moves_clockwise_and_dispenses_exact_count(void) {
    struct fake_gpio gpio;
    memset(&gpio, 0, sizeof(gpio));
    struct motion *motion = new_motion(&gpio);
    assert(motion_set_position(motion, 0) == MOTION_OK);
    assert(motion_arm(motion) == MOTION_OK);
    assert(motion_move(motion, 6) == MOTION_OK);
    assert(gpio.values[MOTION_LINE_DIRECTION]);
    assert(gpio.values[MOTION_LINE_ENABLE]);
    assert(motion_dispense(motion, 3, 600, 200) == MOTION_OK);
    assert(gpio.actuator_rising_edges == 3);
    assert(gpio.values[MOTION_LINE_ENABLE]);
    motion_destroy(motion);
}

static void test_job_scope_holds_then_releases_motor(void) {
    struct fake_gpio gpio;
    memset(&gpio, 0, sizeof(gpio));
    struct motion *motion = new_motion(&gpio);
    assert(motion_set_position(motion, 0) == MOTION_OK);
    assert(motion_arm(motion) == MOTION_OK);
    assert(motion_begin_job(motion) == MOTION_OK);
    assert(!gpio.values[MOTION_LINE_ENABLE]);
    assert(motion_move(motion, 1) == MOTION_OK);
    assert(!gpio.values[MOTION_LINE_ENABLE]);
    assert(motion_dispense(motion, 1, 100, 100) == MOTION_OK);
    assert(!gpio.values[MOTION_LINE_ENABLE]);
    assert(motion_end_job(motion) == MOTION_OK);
    assert(gpio.values[MOTION_LINE_ENABLE]);
    motion_destroy(motion);
}

static void test_tuning_requires_disarm_and_preserves_safe_limits(void) {
    struct fake_gpio gpio;
    memset(&gpio, 0, sizeof(gpio));
    struct motion *motion = new_motion(&gpio);
    assert(motion_configure(motion, 100, 900, 5000, 200, true) == MOTION_OK);
    assert(motion_set_position(motion, 0) == MOTION_OK);
    assert(motion_arm(motion) == MOTION_OK);
    assert(motion_configure(motion, 100, 900, 5000, 200, true) == MOTION_BUSY);
    assert(motion_disarm(motion) == MOTION_OK);
    assert(motion_configure(motion, 100, 500, 5000, 200, true) == MOTION_INVALID);
    motion_destroy(motion);
}

static void test_stop_latches_fault_and_invalidates_position(void) {
    struct fake_gpio gpio;
    memset(&gpio, 0, sizeof(gpio));
    struct motion *motion = new_motion(&gpio);
    assert(motion_set_position(motion, 4) == MOTION_OK);
    assert(motion_arm(motion) == MOTION_OK);
    assert(motion_stop(motion) == MOTION_OK);
    const struct motion_status stopped = motion_get_status(motion);
    assert(stopped.fault);
    assert(!stopped.armed);
    assert(stopped.position == -1);
    assert(motion_move(motion, 5) == MOTION_DISARMED);
    assert(motion_reset(motion) == MOTION_OK);
    assert(motion_get_status(motion).position == -1);
    motion_destroy(motion);
}

int main(void) {
    test_startup_and_arm_require_position();
    test_s_curve_starts_without_a_speed_jump();
    test_conservative_timing_scale_slows_a_move();
    test_full_revolution_is_exact();
    test_tie_moves_clockwise_and_dispenses_exact_count();
    test_job_scope_holds_then_releases_motor();
    test_tuning_requires_disarm_and_preserves_safe_limits();
    test_stop_latches_fault_and_invalidates_position();
    puts("motion tests passed");
    return 0;
}
