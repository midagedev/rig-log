// Read-bandwidth probe: each thread streams its own slice of a large buffer with 256-bit loads and sums it.
// Reports GB/s for the best of N repetitions. Usage: bw <threads> <GiB total> [reps]
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <omp.h>
#include <immintrin.h>
int main(int argc, char **argv) {
    int nt = argc > 1 ? atoi(argv[1]) : 32;
    size_t gib = argc > 2 ? (size_t) atoi(argv[2]) : 8;
    int reps = argc > 3 ? atoi(argv[3]) : 5;
    size_t bytes = gib << 30;
    uint8_t *buf = aligned_alloc(64, bytes);
    if (!buf) { fprintf(stderr, "alloc failed\n"); return 1; }
    omp_set_num_threads(nt);
    #pragma omp parallel for schedule(static)
    for (size_t i = 0; i < bytes; i += 4096) memset(buf + i, (int) (i >> 12), 4096); // first-touch on the reading thread
    double best = 0; long long sink = 0;
    for (int r = 0; r < reps; r++) {
        double t0 = omp_get_wtime();
        long long total = 0;
        #pragma omp parallel reduction(+:total)
        {
            int tid = omp_get_thread_num(), n = omp_get_num_threads();
            size_t per = bytes / n, s = per * tid;
            __m256i acc = _mm256_setzero_si256();
            for (size_t i = 0; i + 128 <= per; i += 128) {
                const __m256i *p = (const __m256i *) (buf + s + i);
                acc = _mm256_add_epi64(acc, _mm256_load_si256(p));
                acc = _mm256_add_epi64(acc, _mm256_load_si256(p + 1));
                acc = _mm256_add_epi64(acc, _mm256_load_si256(p + 2));
                acc = _mm256_add_epi64(acc, _mm256_load_si256(p + 3));
            }
            long long tmp[4]; _mm256_storeu_si256((__m256i *) tmp, acc);
            total += tmp[0] + tmp[1] + tmp[2] + tmp[3];
        }
        double dt = omp_get_wtime() - t0, gbs = bytes / dt / 1e9;
        if (gbs > best) best = gbs;
        sink += total;
    }
    printf("threads %3d  read %.1f GB/s (best of %d, %zu GiB)  [%lld]\n", nt, best, reps, gib, sink & 1);
    return 0;
}
