// GPU memory-bandwidth probe for the DGX Spark (GB10, unified LPDDR5x), 2026-11-03.
// Modes:
//   gpu-bw read <GiB> [reps]        read-only: each thread streams int4 with a grid stride and sums (best of reps)
//   gpu-bw copy <GiB> [reps]        read+write kernel copy; reported GB/s counts both directions
//   gpu-bw sustain <GiB> <seconds>  read kernel back to back; prints one GB/s line per second (thermal/clock check)
// Buffers come from cudaMalloc, so this is the GPU's view of the pool, not the CPU's (tools/membw/bw.c).
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cuda_runtime.h>
#define CK(x) do { cudaError_t e = (x); if (e != cudaSuccess) { fprintf(stderr, "%s: %s\n", #x, cudaGetErrorString(e)); exit(1); } } while (0)

__global__ void rd(const int4 *__restrict__ p, size_t n, unsigned long long *out) {
    size_t i = blockIdx.x * (size_t) blockDim.x + threadIdx.x, st = (size_t) gridDim.x * blockDim.x;
    unsigned s = 0;
    for (; i < n; i += st) { int4 v = __ldcs(p + i); s += v.x ^ v.y ^ v.z ^ v.w; }
    if (s == 0x9e3779b9u) atomicAdd(out, 1ull);  // keeps the loads live without a per-thread store
}
__global__ void cp(const int4 *__restrict__ a, int4 *__restrict__ b, size_t n) {
    size_t i = blockIdx.x * (size_t) blockDim.x + threadIdx.x, st = (size_t) gridDim.x * blockDim.x;
    for (; i < n; i += st) __stcs(b + i, __ldcs(a + i));
}
static double now() { timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec + t.tv_nsec * 1e-9; }

int main(int argc, char **argv) {
    if (argc < 3) { fprintf(stderr, "usage: gpu-bw read|copy|sustain <GiB> [reps|seconds]\n"); return 2; }
    const char *mode = argv[1];
    size_t bytes = (size_t) atof(argv[2]) * (1ull << 30), n = bytes / sizeof(int4);
    int arg = argc > 3 ? atoi(argv[3]) : 10;
    cudaDeviceProp pr; CK(cudaGetDeviceProperties(&pr, 0));
    int blocks = pr.multiProcessorCount * 8, threads = 512;
    int4 *a, *b = nullptr; unsigned long long *out;
    CK(cudaMalloc(&a, bytes)); CK(cudaMemset(a, 1, bytes)); CK(cudaMalloc(&out, 8)); CK(cudaMemset(out, 0, 8));
    if (!strcmp(mode, "copy")) { CK(cudaMalloc(&b, bytes)); CK(cudaMemset(b, 0, bytes)); }
    cudaEvent_t e0, e1; CK(cudaEventCreate(&e0)); CK(cudaEventCreate(&e1));
    auto once = [&]() -> float {
        CK(cudaEventRecord(e0));
        if (b) cp<<<blocks, threads>>>(a, b, n); else rd<<<blocks, threads>>>(a, n, out);
        CK(cudaEventRecord(e1)); CK(cudaEventSynchronize(e1));
        float ms; CK(cudaEventElapsedTime(&ms, e0, e1)); return ms;
    };
    double moved = (double) bytes * (b ? 2 : 1);
    once();  // warm-up: first touch, clocks up
    if (!strcmp(mode, "sustain")) {
        double t0 = now(), mark = t0, acc = 0; int sec = 0;
        while (now() - t0 < arg) {
            acc += moved; once();
            if (now() - mark >= 1.0) { printf("t=%3d s  read %.1f GB/s\n", ++sec, acc / (now() - mark) / 1e9); fflush(stdout); acc = 0; mark = now(); }
        }
    } else {
        float best = 1e30f, sum = 0;
        for (int r = 0; r < arg; r++) { float ms = once(); sum += ms; if (ms < best) best = ms; }
        printf("%s  %.0f GiB  best %.1f GB/s  mean %.1f GB/s  (%d reps, %d SMs, %dx%d)\n", mode, (double) bytes / (1ull << 30),
               moved / (best * 1e-3) / 1e9, moved / (sum / arg * 1e-3) / 1e9, arg, pr.multiProcessorCount, blocks, threads);
    }
    return 0;
}
