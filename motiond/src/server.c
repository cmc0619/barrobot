#define _GNU_SOURCE
#define _POSIX_C_SOURCE 200809L

#include "gpio_linux.h"
#include "motion.h"

#include <errno.h>
#include <pthread.h>
#include <sched.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>

/** Holds parsed process configuration without introducing a second config format. */
struct server_config {
    const char *socket_path;
    const char *chip_path;
    unsigned int offsets[4];
    struct motion_config motion;
};

/** Carries daemon-owned state into one detached client thread. */
struct client_context {
    int client_fd;
    struct motion *motion;
};

/** Carries shutdown state into the synchronous signal-waiting thread. */
struct signal_context {
    int server_fd;
    struct motion *motion;
};

static void default_config(struct server_config *config);
static int parse_arguments(int argc, char **argv, struct server_config *config);
static int create_server_socket(const char *path);
static void *handle_client(void *opaque);
static void *wait_for_signal(void *opaque);
static enum motion_result dispatch_command(struct motion *motion, const char *line, char *response, size_t size);
static int try_realtime(struct motion *motion);
static void format_result(enum motion_result result, char *response, size_t size);
static void format_status(struct motion *motion, char *response, size_t size);
static int parse_int(const char *text, int *value);
static int write_all(int fd, const char *text);
static void print_usage(const char *program);

int main(int argc, char **argv) {
    struct server_config config;
    default_config(&config);
    const int arguments = parse_arguments(argc, argv, &config);
    if (arguments != 0) {
        if (arguments > 0) {
            print_usage(argv[0]);
        }
        return arguments < 0 ? EXIT_FAILURE : EXIT_SUCCESS;
    }
    struct motion_backend backend;
    struct gpio_linux *gpio = gpio_linux_create(config.chip_path, config.offsets, &backend);
    if (gpio == NULL) {
        perror("Unable to request GPIO lines");
        return EXIT_FAILURE;
    }
    struct motion *motion = motion_create(&config.motion, &backend);
    if (motion == NULL) {
        fprintf(stderr, "Unable to initialize motion core\n");
        gpio_linux_destroy(gpio);
        return EXIT_FAILURE;
    }
    const int server_fd = create_server_socket(config.socket_path);
    if (server_fd < 0) {
        perror("Unable to create motion socket");
        motion_destroy(motion);
        gpio_linux_destroy(gpio);
        return EXIT_FAILURE;
    }
    sigset_t signals;
    sigemptyset(&signals);
    sigaddset(&signals, SIGINT);
    sigaddset(&signals, SIGTERM);
    pthread_sigmask(SIG_BLOCK, &signals, NULL);
    struct signal_context signal_context = {.server_fd = server_fd, .motion = motion};
    pthread_t signal_thread;
    if (pthread_create(&signal_thread, NULL, wait_for_signal, &signal_context) != 0) {
        perror("Unable to create signal thread");
        close(server_fd);
        unlink(config.socket_path);
        motion_destroy(motion);
        gpio_linux_destroy(gpio);
        return EXIT_FAILURE;
    }
    fprintf(stderr, "barrobot-motiond listening on %s\n", config.socket_path);
    for (;;) {
        const int client_fd = accept4(server_fd, NULL, NULL, SOCK_CLOEXEC);
        if (client_fd < 0) {
            if (errno == EINTR) {
                continue;
            }
            break;
        }
        struct client_context *context = malloc(sizeof(*context));
        if (context == NULL) {
            close(client_fd);
            continue;
        }
        context->client_fd = client_fd;
        context->motion = motion;
        pthread_t thread;
        if (pthread_create(&thread, NULL, handle_client, context) != 0) {
            close(client_fd);
            free(context);
            continue;
        }
        pthread_detach(thread);
    }
    pthread_join(signal_thread, NULL);
    unlink(config.socket_path);
    (void)motion;
    (void)gpio;
    return EXIT_SUCCESS;
}

static void default_config(struct server_config *config) {
    *config = (struct server_config){
        .socket_path = "/run/barrobot/motion.sock",
        .chip_path = "/dev/gpiochip0",
        .offsets = {20, 21, 16, 26},
        .motion = {
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
        },
    };
}

static int parse_arguments(int argc, char **argv, struct server_config *config) {
    for (int index = 1; index < argc; index += 1) {
        const char *argument = argv[index];
        if (strcmp(argument, "--help") == 0) {
            return 1;
        }
        if (index + 1 >= argc) {
            fprintf(stderr, "Missing value for %s\n", argument);
            return -1;
        }
        const char *value = argv[++index];
        int parsed;
        if (strcmp(argument, "--socket") == 0) {
            config->socket_path = value;
        } else if (strcmp(argument, "--chip") == 0) {
            config->chip_path = value;
        } else if (strcmp(argument, "--dir") == 0 && parse_int(value, &parsed) == 0) {
            config->offsets[MOTION_LINE_DIRECTION] = (unsigned int)parsed;
        } else if (strcmp(argument, "--step") == 0 && parse_int(value, &parsed) == 0) {
            config->offsets[MOTION_LINE_STEP] = (unsigned int)parsed;
        } else if (strcmp(argument, "--enable") == 0 && parse_int(value, &parsed) == 0) {
            config->offsets[MOTION_LINE_ENABLE] = (unsigned int)parsed;
        } else if (strcmp(argument, "--actuator") == 0 && parse_int(value, &parsed) == 0) {
            config->offsets[MOTION_LINE_ACTUATOR] = (unsigned int)parsed;
        } else if (strcmp(argument, "--slots") == 0 && parse_int(value, &parsed) == 0) {
            config->motion.slot_count = parsed;
        } else if (strcmp(argument, "--steps") == 0 && parse_int(value, &parsed) == 0) {
            config->motion.steps_per_revolution = parsed;
        } else if (strcmp(argument, "--microsteps") == 0 && parse_int(value, &parsed) == 0) {
            config->motion.microsteps = parsed;
        } else if (strcmp(argument, "--ramp-steps") == 0 && parse_int(value, &parsed) == 0) {
            config->motion.ramp_steps = parsed;
        } else if (strcmp(argument, "--min-half-period-us") == 0 && parse_int(value, &parsed) == 0) {
            config->motion.minimum_half_period_us = (uint32_t)parsed;
        } else if (strcmp(argument, "--max-half-period-us") == 0 && parse_int(value, &parsed) == 0) {
            config->motion.maximum_half_period_us = (uint32_t)parsed;
        } else {
            fprintf(stderr, "Invalid option or value: %s %s\n", argument, value);
            return -1;
        }
    }
    return 0;
}

static int create_server_socket(const char *path) {
    if (strlen(path) >= sizeof(((struct sockaddr_un *)0)->sun_path)) {
        errno = ENAMETOOLONG;
        return -1;
    }
    const int fd = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (fd < 0) {
        return -1;
    }
    unlink(path);
    struct sockaddr_un address;
    memset(&address, 0, sizeof(address));
    address.sun_family = AF_UNIX;
    strncpy(address.sun_path, path, sizeof(address.sun_path) - 1);
    if (bind(fd, (const struct sockaddr *)&address, sizeof(address)) != 0 ||
        chmod(path, 0660) != 0 || listen(fd, 16) != 0) {
        const int saved_errno = errno;
        close(fd);
        unlink(path);
        errno = saved_errno;
        return -1;
    }
    return fd;
}

static void *handle_client(void *opaque) {
    struct client_context *context = opaque;
    char request[256];
    size_t used = 0;
    while (used + 1 < sizeof(request)) {
        const ssize_t count = read(context->client_fd, request + used, sizeof(request) - used - 1);
        if (count <= 0) {
            break;
        }
        used += (size_t)count;
        if (memchr(request, '\n', used) != NULL) {
            break;
        }
    }
    request[used] = '\0';
    char *newline = strchr(request, '\n');
    if (newline != NULL) {
        *newline = '\0';
    }
    char response[512];
    dispatch_command(context->motion, request, response, sizeof(response));
    write_all(context->client_fd, response);
    close(context->client_fd);
    free(context);
    return NULL;
}

static void *wait_for_signal(void *opaque) {
    struct signal_context *context = opaque;
    sigset_t signals;
    sigemptyset(&signals);
    sigaddset(&signals, SIGINT);
    sigaddset(&signals, SIGTERM);
    int signal_number;
    sigwait(&signals, &signal_number);
    (void)signal_number;
    motion_stop(context->motion);
    shutdown(context->server_fd, SHUT_RDWR);
    close(context->server_fd);
    return NULL;
}

static enum motion_result dispatch_command(
    struct motion *motion,
    const char *line,
    char *response,
    size_t size
) {
    if (strcmp(line, "STATUS") == 0) {
        format_status(motion, response, size);
        return MOTION_OK;
    }
    enum motion_result result = MOTION_INVALID;
    int first;
    int second;
    int third;
    int fourth;
    int fifth;
    char extra;
    if (strcmp(line, "ARM") == 0) {
        result = motion_arm(motion);
    } else if (strcmp(line, "DISARM") == 0) {
        result = motion_disarm(motion);
    } else if (strcmp(line, "RESET") == 0) {
        result = motion_reset(motion);
    } else if (strcmp(line, "STOP") == 0) {
        result = motion_stop(motion);
    } else if (sscanf(line, "SET_POSITION %d %c", &first, &extra) == 1) {
        result = motion_set_position(motion, first);
    } else if (sscanf(line, "MOVE %d %c", &first, &extra) == 1) {
        try_realtime(motion);
        result = motion_move(motion, first);
    } else if (sscanf(line, "DISPENSE %d %d %d %c", &first, &second, &third, &extra) == 3 &&
               second >= 0 && third >= 0) {
        try_realtime(motion);
        result = motion_dispense(motion, first, (uint32_t)second, (uint32_t)third);
    } else if (sscanf(line, "CONFIGURE %d %d %d %d %d %c", &first, &second, &third, &fourth, &fifth, &extra) == 5 &&
               second >= 0 && third >= 0 && fourth >= 0 && (fifth == 0 || fifth == 1)) {
        result = motion_configure(motion, first, (uint32_t)second, (uint32_t)third, (uint32_t)fourth, fifth == 1);
    }
    format_result(result, response, size);
    return result;
}

static int try_realtime(struct motion *motion) {
    const struct sched_param parameters = {.sched_priority = 20};
    const int result = pthread_setschedparam(pthread_self(), SCHED_FIFO, &parameters);
    motion_set_realtime(motion, result == 0);
    return result;
}

static void format_result(enum motion_result result, char *response, size_t size) {
    if (result == MOTION_OK) {
        snprintf(response, size, "OK\n");
    } else {
        snprintf(response, size, "ERR %s command_failed\n", motion_result_name(result));
    }
}

static void format_status(struct motion *motion, char *response, size_t size) {
    const struct motion_status status = motion_get_status(motion);
    const char *state = status.fault ? "fault" : status.busy ? "busy" : status.armed ? "ready" : "disarmed";
    char position[32];
    if (status.position < 0) {
        snprintf(position, sizeof(position), "unknown");
    } else {
        snprintf(position, sizeof(position), "%d", status.position);
    }
    snprintf(
        response,
        size,
        "OK state=%s armed=%d position=%s realtime=%d\n",
        state,
        status.armed ? 1 : 0,
        position,
        status.realtime ? 1 : 0
    );
}

static int parse_int(const char *text, int *value) {
    char *end;
    errno = 0;
    const long parsed = strtol(text, &end, 10);
    if (errno != 0 || *text == '\0' || *end != '\0' || parsed < 0 || parsed > 1000000) {
        return -1;
    }
    *value = (int)parsed;
    return 0;
}

static int write_all(int fd, const char *text) {
    size_t remaining = strlen(text);
    while (remaining > 0) {
        const ssize_t written = write(fd, text, remaining);
        if (written < 0) {
            if (errno == EINTR) {
                continue;
            }
            return -1;
        }
        text += written;
        remaining -= (size_t)written;
    }
    return 0;
}

static void print_usage(const char *program) {
    fprintf(
        stderr,
        "Usage: %s [--socket PATH] [--chip PATH] [--dir N] [--step N] "
        "[--enable N] [--actuator N] [--slots N] [--steps N] [--microsteps N] "
        "[--ramp-steps N] [--min-half-period-us N] [--max-half-period-us N]\n",
        program
    );
}
