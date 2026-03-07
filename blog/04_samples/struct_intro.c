#include <stdint.h>
#include <stdio.h>
#include <stddef.h>

typedef struct {
    uint16_t c;
    uint8_t d;
    uint32_t b;
    uint64_t a;
} foo_t;

void main(void) {
    foo_t struct_example;
}