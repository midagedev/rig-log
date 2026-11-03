// NVMe O_DIRECT probe, 2026-11-03. Built to put the DGX Spark's drive beside the workstation's 10-11 queue-depth
// sweep (log/2026-10-11.md, bloomery probe_nvread) with the same request shape: blocking 4 MiB preads, one per
// worker, so worker count = queue depth. It is not the same tool: probe_nvread reads a model's expert ranges,
// this reads contiguous slices of one file.
//   nvread write <file> <GiB>                 one thread, O_DIRECT 4 MiB writes of non-repeating data, then fsync
//   nvread read  <file> <threads> [MiB=4]     file split into <threads> contiguous slices, each read front to back
// Reads go to a file this probe wrote, never to unwritten LBAs: an SSD answers those without touching NAND, so a
// raw-device read of an empty region reads fast and means nothing (the failure mode this probe exists to avoid).
#define _GNU_SOURCE
#include <fcntl.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

static double now(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec + t.tv_nsec * 1e-9; }
typedef struct { int fd; off_t start, end; size_t req; int err; } job_t;

static void *reader(void *p) {
    job_t *j = p; void *buf;
    if (posix_memalign(&buf, 4096, j->req)) { j->err = 1; return NULL; }
    for (off_t o = j->start; o < j->end; o += j->req) {
        size_t n = (size_t) (j->end - o) < j->req ? (size_t) (j->end - o) : j->req;
        if (pread(j->fd, buf, n, o) != (ssize_t) n) { j->err = 1; break; }
    }
    free(buf); return NULL;
}

int main(int argc, char **argv) {
    if (argc < 4) { fprintf(stderr, "usage: nvread write <file> <GiB> | nvread read <file> <threads> [MiB]\n"); return 2; }
    const size_t MiB = 1 << 20;
    if (!strcmp(argv[1], "write")) {
        size_t total = (size_t) atoi(argv[3]) << 30, req = 4 * MiB;
        int fd = open(argv[2], O_WRONLY | O_CREAT | O_TRUNC | O_DIRECT, 0644);
        if (fd < 0) { perror("open"); return 1; }
        uint64_t *buf; if (posix_memalign((void **) &buf, 4096, req)) return 1;
        uint64_t x = 0x9e3779b97f4a7c15ull;
        double t0 = now();
        for (size_t o = 0; o < total; o += req) {
            for (size_t i = 0; i < req / 8; i++) { x ^= x << 13; x ^= x >> 7; x ^= x << 17; buf[i] = x; }
            if (write(fd, buf, req) != (ssize_t) req) { perror("write"); return 1; }
        }
        double tw = now() - t0; fsync(fd); double tf = now() - t0; close(fd);
        printf("write %zu GiB  %.2f GB/s (to last write)  %.2f GB/s (incl. fsync)  [4 MiB, 1 thread, O_DIRECT]\n",
               total >> 30, total / tw / 1e9, total / tf / 1e9);
        return 0;
    }
    int nt = atoi(argv[3]); size_t req = (argc > 4 ? (size_t) atoi(argv[4]) : 4) * MiB;
    int fd = open(argv[2], O_RDONLY | O_DIRECT);
    if (fd < 0) { perror("open"); return 1; }
    off_t size = lseek(fd, 0, SEEK_END), per = (size / nt) / req * req;
    job_t *jobs = calloc(nt, sizeof *jobs); pthread_t *th = calloc(nt, sizeof *th);
    for (int i = 0; i < nt; i++) jobs[i] = (job_t) { fd, per * i, per * (i + 1), req, 0 };
    double t0 = now();
    for (int i = 0; i < nt; i++) pthread_create(&th[i], NULL, reader, &jobs[i]);
    int err = 0; for (int i = 0; i < nt; i++) { pthread_join(th[i], NULL); err |= jobs[i].err; }
    double dt = now() - t0;
    if (err) { fprintf(stderr, "short read\n"); return 1; }
    printf("read qd %2d  %.3f GB/s  (%.1f GiB in %.2f s, %zu MiB requests, O_DIRECT)\n", nt, (double) per * nt / dt / 1e9,
           (double) per * nt / (1 << 30), dt, req / MiB);
    return 0;
}
