#define _POSIX_C_SOURCE 200809L

#include "motion.h"

#include <pthread.h>
#include <stdatomic.h>
#include <limits.h>
#include <stdlib.h>

/** Owns all mutable hardware state for one daemon process. */
struct motion {
    struct motion_config config;
    struct motion_backend backend;
    pthread_mutex_t hardware_lock;
    atomic_bool armed;
    atomic_bool busy;
    atomic_bool fault;
    atomic_bool realtime;
    atomic_bool stop_requested;
    atomic_int position;
};

static int safe_outputs(struct motion *instance);
static enum motion_result fail_motion(struct motion *instance, enum motion_result result);
static bool valid_slot(const struct motion *instance, int slot);
static int boundary_step(const struct motion *instance, int slot);
static int movement_steps(const struct motion *instance, int current, int target, bool clockwise);
static uint32_t half_period_us(const struct motion *instance, int step, int total_steps);
static int set_logical_line(struct motion *instance, enum motion_line line, bool active);
static int sleep_half_period(struct motion *instance, uint64_t *deadline_ns, uint32_t microseconds);

struct motion *motion_create(const struct motion_config *config, const struct motion_backend *backend) {
    if (config == NULL || backend == NULL || backend->set_line == NULL || backend->now_ns == NULL ||
        backend->sleep_until_ns == NULL || config->slot_count < 2 ||
        config->steps_per_revolution < 1 || config->microsteps < 1 || config->ramp_steps < 0 ||
        config->minimum_half_period_us < 1 ||
        config->maximum_half_period_us < config->minimum_half_period_us ||
        config->steps_per_revolution > INT_MAX / config->microsteps) {
        return NULL;
    }
    struct motion *instance = calloc(1, sizeof(*instance));
    if (instance == NULL) {
        return NULL;
    }
    instance->config = *config;
    instance->backend = *backend;
    if (pthread_mutex_init(&instance->hardware_lock, NULL) != 0) {
        free(instance);
        return NULL;
    }
    atomic_init(&instance->armed, false);
    atomic_init(&instance->busy, false);
    atomic_init(&instance->fault, false);
    atomic_init(&instance->realtime, false);
    atomic_init(&instance->stop_requested, false);
    atomic_init(&instance->position, -1);
    if (safe_outputs(instance) != 0) {
        pthread_mutex_destroy(&instance->hardware_lock);
        free(instance);
        return NULL;
    }
    return instance;
}

void motion_destroy(struct motion *instance) {
    if (instance == NULL) {
        return;
    }
    motion_stop(instance);
    pthread_mutex_destroy(&instance->hardware_lock);
    free(instance);
}

struct motion_status motion_get_status(const struct motion *instance) {
    struct motion_status status = {0};
    if (instance == NULL) {
        status.fault = true;
        status.position = -1;
        return status;
    }
    status.armed = atomic_load(&instance->armed);
    status.busy = atomic_load(&instance->busy);
    status.fault = atomic_load(&instance->fault);
    status.realtime = atomic_load(&instance->realtime);
    status.position = atomic_load(&instance->position);
    return status;
}

void motion_set_realtime(struct motion *instance, bool enabled) {
    if (instance != NULL) {
        atomic_store(&instance->realtime, enabled);
    }
}

enum motion_result motion_set_position(struct motion *instance, int slot) {
    if (instance == NULL || !valid_slot(instance, slot)) {
        return MOTION_INVALID;
    }
    if (atomic_load(&instance->busy)) {
        return MOTION_BUSY;
    }
    if (atomic_load(&instance->armed)) {
        return MOTION_DISARMED;
    }
    atomic_store(&instance->position, slot);
    atomic_store(&instance->stop_requested, false);
    return MOTION_OK;
}

enum motion_result motion_arm(struct motion *instance) {
    if (instance == NULL) {
        return MOTION_INVALID;
    }
    if (atomic_load(&instance->busy)) {
        return MOTION_BUSY;
    }
    if (atomic_load(&instance->fault)) {
        return MOTION_FAULT;
    }
    if (atomic_load(&instance->position) < 0) {
        return MOTION_POSITION_UNKNOWN;
    }
    atomic_store(&instance->stop_requested, false);
    atomic_store(&instance->armed, true);
    return MOTION_OK;
}

enum motion_result motion_disarm(struct motion *instance) {
    if (instance == NULL) {
        return MOTION_INVALID;
    }
    atomic_store(&instance->armed, false);
    atomic_store(&instance->stop_requested, true);
    return safe_outputs(instance) == 0 ? MOTION_OK : fail_motion(instance, MOTION_GPIO_ERROR);
}

enum motion_result motion_reset(struct motion *instance) {
    if (instance == NULL) {
        return MOTION_INVALID;
    }
    if (atomic_load(&instance->busy)) {
        return MOTION_BUSY;
    }
    atomic_store(&instance->armed, false);
    atomic_store(&instance->fault, false);
    atomic_store(&instance->stop_requested, false);
    atomic_store(&instance->position, -1);
    return safe_outputs(instance) == 0 ? MOTION_OK : fail_motion(instance, MOTION_GPIO_ERROR);
}

enum motion_result motion_move(struct motion *instance, int slot) {
    if (instance == NULL || !valid_slot(instance, slot)) {
        return MOTION_INVALID;
    }
    if (pthread_mutex_trylock(&instance->hardware_lock) != 0) {
        return MOTION_BUSY;
    }
    atomic_store(&instance->busy, true);
    enum motion_result result = MOTION_OK;
    const int current = atomic_load(&instance->position);
    if (!atomic_load(&instance->armed)) {
        result = MOTION_DISARMED;
        goto done;
    }
    if (atomic_load(&instance->fault)) {
        result = MOTION_FAULT;
        goto done;
    }
    if (current < 0) {
        result = MOTION_POSITION_UNKNOWN;
        goto done;
    }
    if (current == slot) {
        goto done;
    }
    atomic_store(&instance->stop_requested, false);
    const int clockwise_slots = (slot - current + instance->config.slot_count) %
                                instance->config.slot_count;
    const int counterclockwise_slots = (current - slot + instance->config.slot_count) %
                                       instance->config.slot_count;
    const bool clockwise = clockwise_slots <= counterclockwise_slots;
    const int total_steps = movement_steps(instance, current, slot, clockwise);
    if (set_logical_line(instance, MOTION_LINE_DIRECTION, clockwise) != 0 ||
        set_logical_line(instance, MOTION_LINE_ENABLE, true) != 0) {
        result = fail_motion(instance, MOTION_GPIO_ERROR);
        goto done;
    }
    uint64_t deadline_ns = instance->backend.now_ns(instance->backend.context);
    for (int step = 0; step < total_steps; step += 1) {
        if (atomic_load(&instance->stop_requested) || !atomic_load(&instance->armed)) {
            result = fail_motion(instance, MOTION_STOPPED);
            goto done;
        }
        const uint32_t period = half_period_us(instance, step, total_steps);
        if (set_logical_line(instance, MOTION_LINE_STEP, true) != 0 ||
            sleep_half_period(instance, &deadline_ns, period) != 0 ||
            set_logical_line(instance, MOTION_LINE_STEP, false) != 0 ||
            sleep_half_period(instance, &deadline_ns, period) != 0) {
            result = fail_motion(instance, MOTION_GPIO_ERROR);
            goto done;
        }
    }
    atomic_store(&instance->position, slot);

done:
    if (set_logical_line(instance, MOTION_LINE_STEP, false) != 0 ||
        set_logical_line(instance, MOTION_LINE_ENABLE, false) != 0) {
        result = fail_motion(instance, MOTION_GPIO_ERROR);
    }
    atomic_store(&instance->busy, false);
    pthread_mutex_unlock(&instance->hardware_lock);
    return result;
}

enum motion_result motion_dispense(
    struct motion *instance,
    int press_count,
    uint32_t press_duration_ms,
    uint32_t release_duration_ms
) {
    if (instance == NULL || press_count < 0 || press_count > 100 || press_duration_ms < 1 ||
        press_duration_ms > 60000 || release_duration_ms > 60000) {
        return MOTION_INVALID;
    }
    if (pthread_mutex_trylock(&instance->hardware_lock) != 0) {
        return MOTION_BUSY;
    }
    atomic_store(&instance->busy, true);
    enum motion_result result = MOTION_OK;
    if (!atomic_load(&instance->armed)) {
        result = MOTION_DISARMED;
        goto done;
    }
    if (atomic_load(&instance->fault)) {
        result = MOTION_FAULT;
        goto done;
    }
    atomic_store(&instance->stop_requested, false);
    uint64_t deadline_ns = instance->backend.now_ns(instance->backend.context);
    for (int press = 0; press < press_count; press += 1) {
        if (atomic_load(&instance->stop_requested) || !atomic_load(&instance->armed)) {
            result = fail_motion(instance, MOTION_STOPPED);
            goto done;
        }
        if (set_logical_line(instance, MOTION_LINE_ACTUATOR, true) != 0 ||
            sleep_half_period(instance, &deadline_ns, press_duration_ms * 1000U) != 0 ||
            set_logical_line(instance, MOTION_LINE_ACTUATOR, false) != 0 ||
            sleep_half_period(instance, &deadline_ns, release_duration_ms * 1000U) != 0) {
            result = fail_motion(instance, MOTION_GPIO_ERROR);
            goto done;
        }
    }

done:
    if (set_logical_line(instance, MOTION_LINE_ACTUATOR, false) != 0) {
        result = fail_motion(instance, MOTION_GPIO_ERROR);
    }
    atomic_store(&instance->busy, false);
    pthread_mutex_unlock(&instance->hardware_lock);
    return result;
}

enum motion_result motion_stop(struct motion *instance) {
    if (instance == NULL) {
        return MOTION_INVALID;
    }
    atomic_store(&instance->stop_requested, true);
    atomic_store(&instance->armed, false);
    atomic_store(&instance->fault, true);
    atomic_store(&instance->position, -1);
    return safe_outputs(instance) == 0 ? MOTION_OK : MOTION_GPIO_ERROR;
}

const char *motion_result_name(enum motion_result result) {
    switch (result) {
        case MOTION_OK:
            return "OK";
        case MOTION_INVALID:
            return "INVALID";
        case MOTION_DISARMED:
            return "DISARMED";
        case MOTION_POSITION_UNKNOWN:
            return "POSITION_UNKNOWN";
        case MOTION_BUSY:
            return "BUSY";
        case MOTION_STOPPED:
            return "STOPPED";
        case MOTION_GPIO_ERROR:
            return "GPIO";
        case MOTION_FAULT:
            return "FAULT";
    }
    return "INTERNAL";
}

static int safe_outputs(struct motion *instance) {
    int result = 0;
    result |= set_logical_line(instance, MOTION_LINE_ACTUATOR, false);
    result |= set_logical_line(instance, MOTION_LINE_STEP, false);
    result |= set_logical_line(instance, MOTION_LINE_ENABLE, false);
    return result;
}

static enum motion_result fail_motion(struct motion *instance, enum motion_result result) {
    atomic_store(&instance->armed, false);
    atomic_store(&instance->fault, true);
    atomic_store(&instance->position, -1);
    safe_outputs(instance);
    return result;
}

static bool valid_slot(const struct motion *instance, int slot) {
    return slot >= 0 && slot < instance->config.slot_count;
}

static int boundary_step(const struct motion *instance, int slot) {
    const int total = instance->config.steps_per_revolution * instance->config.microsteps;
    const int64_t numerator = (int64_t)slot * total + instance->config.slot_count / 2;
    return (int)(numerator / instance->config.slot_count);
}

static int movement_steps(const struct motion *instance, int current, int target, bool clockwise) {
    const int total = instance->config.steps_per_revolution * instance->config.microsteps;
    const int current_step = boundary_step(instance, current);
    const int target_step = boundary_step(instance, target);
    return clockwise ? (target_step - current_step + total) % total
                     : (current_step - target_step + total) % total;
}

static uint32_t half_period_us(const struct motion *instance, int step, int total_steps) {
    int ramp = instance->config.ramp_steps;
    if (ramp > total_steps / 2) {
        ramp = total_steps / 2;
    }
    if (ramp == 0) {
        return instance->config.minimum_half_period_us;
    }
    const uint32_t range = instance->config.maximum_half_period_us -
                           instance->config.minimum_half_period_us;
    if (step < ramp) {
        return instance->config.maximum_half_period_us - (range * (uint32_t)step) / (uint32_t)ramp;
    }
    if (step >= total_steps - ramp) {
        const int deceleration_step = step - (total_steps - ramp) + 1;
        return instance->config.minimum_half_period_us +
               (range * (uint32_t)deceleration_step) / (uint32_t)ramp;
    }
    return instance->config.minimum_half_period_us;
}

static int set_logical_line(struct motion *instance, enum motion_line line, bool active) {
    bool high = active;
    if (line == MOTION_LINE_DIRECTION && !instance->config.clockwise_high) {
        high = !high;
    } else if (line == MOTION_LINE_ENABLE && instance->config.enable_active_low) {
        high = !high;
    } else if (line == MOTION_LINE_ACTUATOR && !instance->config.actuator_active_high) {
        high = !high;
    }
    return instance->backend.set_line(instance->backend.context, line, high);
}

static int sleep_half_period(struct motion *instance, uint64_t *deadline_ns, uint32_t microseconds) {
    *deadline_ns += (uint64_t)microseconds * 1000ULL;
    return instance->backend.sleep_until_ns(instance->backend.context, *deadline_ns);
}
