#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define SECRET_BYTE 0xE7

typedef struct {
    uint8_t  flag;
    uint32_t id;
    uint16_t code;
    uint8_t  state;
} padded_struct_t;

static void dump(const void *ptr, size_t size) {
    const uint8_t *p = ptr;
    for (size_t i = 0; i < size; ++i) {
        printf("%02x ", p[i]);
    }
    printf("\n");
}

int main(void) {
    padded_struct_t src, dst;
    memset(&src, SECRET_BYTE, sizeof(src));
    memset(&dst, 0x00, sizeof(dst));

    src.flag = 0x11;
    src.id = 0x22222222;
    src.code = 0x3333;
    src.state = 0x44;

    dst = src;

    dump(&dst, sizeof(dst));
}
