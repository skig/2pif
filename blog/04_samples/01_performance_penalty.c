#include <stdint.h>

typedef struct {
    uint8_t a;
    uint8_t b;
    uint8_t d;
    uint8_t c;
} struct_example_t;

uint32_t foo(const struct_example_t *a) {
    return a->a | (a->b << 8) | (a->c << 16) | (a->d << 24);
}