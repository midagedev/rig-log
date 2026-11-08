// Kernel reads of pinned, device-mapped host memory (zero-copy) over PCIe: the rate a decode step would see if KV rows
// lived on the host. Two patterns over a buffer of BUF bytes: sequential (every warp reads consecutive 16-byte words) and
// random rows of ROW bytes (each block reads whole rows at random row indices). Prints GB/s per pattern, the median of
// REPS timed launches after one warm-up. Built and run on the box under the timing lease (run.sh).
#include <cstdio>
#include <cstdlib>
#include <vector>
#include <algorithm>
#include <cuda_runtime.h>

#define CK(x) do { cudaError_t e = (x); if (e != cudaSuccess) { fprintf(stderr, "cuda: %s at %s:%d\n", cudaGetErrorString(e), __FILE__, __LINE__); exit(2); } } while (0)

__global__ void seq_read(const uint4* __restrict__ src, size_t n, unsigned long long* sink) {
  uint4 acc = make_uint4(0, 0, 0, 0);
  for (size_t i = blockIdx.x * (size_t)blockDim.x + threadIdx.x; i < n; i += (size_t)gridDim.x * blockDim.x) {
    uint4 v = src[i];
    acc.x ^= v.x; acc.y ^= v.y; acc.z ^= v.z; acc.w ^= v.w;
  }
  if ((acc.x ^ acc.y ^ acc.z ^ acc.w) == 0x9e3779b9u) atomicAdd(sink, 1ull);
}

// One block a row at a time: the block's threads read the row's 16-byte words.
__global__ void row_read(const uint4* __restrict__ src, const unsigned* __restrict__ rows, size_t nrows_read,
                         size_t words_per_row, unsigned long long* sink) {
  uint4 acc = make_uint4(0, 0, 0, 0);
  for (size_t r = blockIdx.x; r < nrows_read; r += gridDim.x) {
    const uint4* row = src + (size_t)rows[r] * words_per_row;
    for (size_t w = threadIdx.x; w < words_per_row; w += blockDim.x) {
      uint4 v = row[w];
      acc.x ^= v.x; acc.y ^= v.y; acc.z ^= v.z; acc.w ^= v.w;
    }
  }
  if ((acc.x ^ acc.y ^ acc.z ^ acc.w) == 0x9e3779b9u) atomicAdd(sink, 1ull);
}

static float median(std::vector<float> v) { std::sort(v.begin(), v.end()); return v[v.size() / 2]; }

int main(int argc, char** argv) {
  size_t buf = (argc > 1 ? strtoull(argv[1], 0, 10) : 4096ull) << 20;  // MiB
  size_t row = argc > 2 ? strtoull(argv[2], 0, 10) : 1536;              // bytes a row
  int reps = argc > 3 ? atoi(argv[3]) : 9;
  if (row % 16 || row == 0 || row > buf) { fprintf(stderr, "row must be a nonzero multiple of 16 within the buffer\n"); return 64; }
  buf -= buf % row;  // whole rows: the buffer rounds down to a multiple of the row
  CK(cudaSetDeviceFlags(cudaDeviceMapHost));
  cudaDeviceProp p; int dev; CK(cudaGetDevice(&dev)); CK(cudaGetDeviceProperties(&p, dev));
  void* host; CK(cudaHostAlloc(&host, buf, cudaHostAllocMapped));
  for (size_t i = 0; i < buf / 8; i++) ((unsigned long long*)host)[i] = i * 0x9e3779b97f4a7c15ull;
  void* dptr; CK(cudaHostGetDevicePointer(&dptr, host, 0));
  unsigned long long* sink; CK(cudaMalloc(&sink, 8));
  size_t nrows = buf / row, nread = nrows / 4;
  std::vector<unsigned> idx(nread); srand(12345);
  for (size_t i = 0; i < nread; i++) idx[i] = (unsigned)(((size_t)rand() * RAND_MAX + rand()) % nrows);
  unsigned* didx; CK(cudaMalloc(&didx, nread * 4)); CK(cudaMemcpy(didx, idx.data(), nread * 4, cudaMemcpyHostToDevice));
  cudaEvent_t a, b; CK(cudaEventCreate(&a)); CK(cudaEventCreate(&b));
  int grid = p.multiProcessorCount * 8, block = 256;
  auto time = [&](auto launch, double bytes, const char* name) {
    launch(); CK(cudaDeviceSynchronize());
    std::vector<float> ms;
    for (int r = 0; r < reps; r++) {
      CK(cudaEventRecord(a)); launch(); CK(cudaEventRecord(b)); CK(cudaEventSynchronize(b));
      float t; CK(cudaEventElapsedTime(&t, a, b)); ms.push_back(t);
    }
    float m = median(ms);
    printf("%s card=\"%s\" buf_mib=%zu row_b=%zu bytes=%.0f median_ms=%.3f gbps=%.2f reps=%d\n", name, p.name, buf >> 20,
           row, bytes, m, bytes / (m * 1e6), reps);
  };
  time([&] { seq_read<<<grid, block>>>((const uint4*)dptr, buf / 16, sink); }, (double)buf, "seq");
  time([&] { row_read<<<grid, 128>>>((const uint4*)dptr, didx, nread, row / 16, sink); }, (double)nread * row, "rows");
  CK(cudaGetLastError());
  return 0;
}
