#ifndef BARROBOT_MOTION_H
#define BARROBOT_MOTION_H

#include <stdbool.h>
#include <stdint.h>

/** Identifies the four output lines owned by the motion service. */
enum motion_line {
    MOTION_LINE_DIRECTION = 0,
    MOTION_LINE_STEP = 1,
    MOTION_LINE_ENABLE = 2,
    MOTION_LINE_ACTUATOR = 3,
};

/** Defines stable results returned by the motion core. */
enum motion_result {
    MOTION_OK = 0,
    MOTION_INVALID = 1,
    MOTION_DISARMED = 2,
    MOTION_POSITION_UNKNOWN = 3,
    MOTION_BUSY = 4,
    MOTION_STOPPED = 5,
    MOTION_GPIO_ERROR = 6,
    MOTION_FAULT = 7,
};

/** Configures turret geometry, polarity, and the operator-tunable motion envelope. */
struct motion_config {
    int slot_count;
    int steps_per_revolution;
    int microsteps;
    int ramp_steps;
    uint32_t minimum_half_period_us;
    uint32_t maximum_half_period_us;
    uint32_t settle_ms;
    bool hold_position;
    bool clockwise_high;
    bool enable_active_low;
    bool actuator_active_high;
};

/** Abstracts GPIO and monotonic timing so the motion core is hardware-testable. */
struct motion_backend {
    void *context;
    int (*set_line)(void *context, enum motion_line line, bool high);
    uint64_t (*now_ns)(void *context);
    int (*sleep_until_ns)(void *context, uint64_t deadline_ns);
};

/** Exposes a stable snapshot of daemon-owned safety and position state. */
struct motion_status {
    bool armed;
    bool busy;
    bool fault;
    bool realtime;
    int position;
};

struct motion;

/** Creates a motion core in disarmed, unknown-position state. */
struct motion *motion_create(const struct motion_config *config, const struct motion_backend *backend);

/** Places outputs into their safe states and releases the motion core. */
void motion_destroy(struct motion *instance);

/** Returns a lock-free snapshot suitable for status reporting. */
struct motion_status motion_get_status(const struct motion *instance);

/** Records whether the active worker obtained real-time scheduling. */
void motion_set_realtime(struct motion *instance, bool enabled);

/** Safely updates the motion envelope while disarmed and idle. */
enum motion_result motion_configure(
    struct motion *instance,
    int ramp_steps,
    uint32_t minimum_half_period_us,
    uint32_t maximum_half_period_us,
    uint32_t settle_ms,
    bool hold_position
);

/** Establishes an operator-confirmed zero-based slot while disarmed. */
enum motion_result motion_set_position(struct motion *instance, int slot);

/** Arms movement only when position is known and no fault is latched. */
enum motion_result motion_arm(struct motion *instance);

/** Disables outputs and rejects further live commands. */
enum motion_result motion_disarm(struct motion *instance);

/** Clears a fault while leaving the machine disarmed with unknown position. */
enum motion_result motion_reset(struct motion *instance);

/** Executes one shortest-path ramped move to a zero-based slot. */
enum motion_result motion_move(struct motion *instance, int slot);

/** Executes calibrated actuator presses while the machine is armed. */
enum motion_result motion_dispense(
    struct motion *instance,
    int press_count,
    uint32_t press_duration_ms,
    uint32_t release_duration_ms
);

/** Latches a fault, disarms, invalidates position, and interrupts active work. */
enum motion_result motion_stop(struct motion *instance);

/** Returns a stable protocol name for one motion result. */
const char *motion_result_name(enum motion_result result);

#endif
