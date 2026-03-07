// main.c
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <stdio.h>

#define N 50000000

typedef struct {
    uint64_t a;
    uint8_t  b;
    uint64_t c;
    uint8_t  d;
} BadType;

typedef struct {
    uint64_t a;
    uint64_t c;
    uint8_t  b;
    uint8_t  d;
    uint64_t notused;
} GoodType;

/* IDENTICAL IMPLEMENTATION */
void __attribute__((noinline)) test_bad(BadType *p, size_t n) {
    for (size_t i = 0; i < n; i++)
        if (p[i].b)
            p[i].c += p[i].a;
}

/* IDENTICAL IMPLEMENTATION */
void __attribute__((noinline)) test_good(GoodType *p, size_t n) {
    for (size_t i = 0; i < n; i++)
        if (p[i].b)
            p[i].c += p[i].a;
}

int main(int argc, char **argv) {
    printf("sizes: BadType=%zu GoodType=%zu\n", sizeof(BadType), sizeof(GoodType));
    if (argc != 2) {
        return 1;
    }

    double start, end;

    if (strcmp(argv[1], "--bad-type") == 0) {

        BadType *p = aligned_alloc(64, N * sizeof(BadType));

        for (size_t i = 0; i < N; i++) {
            p[i].a = i;
            p[i].b = i & 1;
            p[i].c = i;
        }

        test_bad(p, N);

        free(p);

    } else if (strcmp(argv[1], "--good-type") == 0) {

        GoodType *p = aligned_alloc(64, N * sizeof(GoodType));

        for (size_t i = 0; i < N; i++) {
            p[i].a = i;
            p[i].b = i & 1;
            p[i].c = i;
        }

        test_good(p, N);

        free(p);

    } else {
        return 1;
    }

    return 0;
}