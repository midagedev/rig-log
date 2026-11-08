// One reserved virtual range whose first half is backed by card memory and second half by host memory, both made with
// cuMemCreate (location DEVICE vs HOST_NUMA) and mapped into the same range: whether an unchanged kernel reads both halves
// through one pointer, the rate of each half, and the cost of moving one page from card to host at the same address
// (copy out, unmap, map a host handle in its place). The term that decides whether a growing KV store can spill its tail
// pages to the host with no kernel change. Built and run on the box under the timing lease (run.sh).
// Args: pages a half (2 MiB each), row bytes, reps.
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#include <algorithm>
#include <chrono>
#include <cuda.h>
#include <cuda_runtime.h>

#define CK(x) do { cudaError_t e = (x); if (e != cudaSuccess) { fprintf(stderr, "cuda: %s at %s:%d\n", cudaGetErrorString(e), __FILE__, __LINE__); exit(2); } } while (0)
#define CU(x) do { CUresult r = (x); if (r != CUDA_SUCCESS) { const char* s = 0; cuGetErrorString(r, &s); fprintf(stderr, "cu: %s (%d) at %s:%d\n", s ? s : "?", (int)r, __FILE__, __LINE__); exit(3); } } while (0)

__global__ void seq_read(const uint4* __restrict__ src, size_t n, unsigned long long* sink) {
  uint4 acc = make_uint4(0, 0, 0, 0);
  for (size_t i = blockIdx.x * (size_t)blockDim.x + threadIdx.x; i < n; i += (size_t)gridDim.x * blockDim.x) {
    uint4 v = src[i];
    acc.x ^= v.x; acc.y ^= v.y; acc.z ^= v.z; acc.w ^= v.w;
  }
  if ((acc.x ^ acc.y ^ acc.z ^ acc.w) == 0x9e3779b9u) atomicAdd(sink, 1ull);
}

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

// Every 8-byte word of [base, base + n words) equals its pattern word; the first mismatch's index in *bad (or ~0).
__global__ void check(const unsigned long long* __restrict__ src, size_t first, size_t n, unsigned long long* bad) {
  for (size_t i = blockIdx.x * (size_t)blockDim.x + threadIdx.x; i < n; i += (size_t)gridDim.x * blockDim.x) {
    if (src[i] != (first + i) * 0x9e3779b97f4a7c15ull) atomicMin(bad, (unsigned long long)i);
  }
}

static float median(std::vector<float> v) { std::sort(v.begin(), v.end()); return v[v.size() / 2]; }

static CUmemGenericAllocationHandle make(size_t bytes, CUmemLocationType type, int id) {
  CUmemAllocationProp p; memset(&p, 0, sizeof p);
  p.type = CU_MEM_ALLOCATION_TYPE_PINNED; p.location.type = type; p.location.id = id;
  CUmemGenericAllocationHandle h; CU(cuMemCreate(&h, bytes, &p, 0)); return h;
}

static void access(CUdeviceptr at, size_t bytes, int dev) {
  CUmemAccessDesc d; memset(&d, 0, sizeof d);
  d.location.type = CU_MEM_LOCATION_TYPE_DEVICE; d.location.id = dev; d.flags = CU_MEM_ACCESS_FLAGS_PROT_READWRITE;
  CU(cuMemSetAccess(at, bytes, &d, 1));
}

int main(int argc, char** argv) {
  size_t half_pages = argc > 1 ? strtoull(argv[1], 0, 10) : 1024;  // 2 GiB a half at 2 MiB pages
  size_t row = argc > 2 ? strtoull(argv[2], 0, 10) : 1536;
  int reps = argc > 3 ? atoi(argv[3]) : 9;
  CK(cudaFree(0));
  int dev; CK(cudaGetDevice(&dev));
  CUdevice cd; CU(cuDeviceGet(&cd, dev));
  char name[256]; CU(cuDeviceGetName(name, sizeof name, cd));
  int vmm = 0, numa_vmm = 0, numa_id = -1, drv = 0;
  CU(cuDeviceGetAttribute(&vmm, CU_DEVICE_ATTRIBUTE_VIRTUAL_MEMORY_MANAGEMENT_SUPPORTED, cd));
  CU(cuDeviceGetAttribute(&numa_vmm, CU_DEVICE_ATTRIBUTE_HOST_NUMA_VIRTUAL_MEMORY_MANAGEMENT_SUPPORTED, cd));
  CU(cuDeviceGetAttribute(&numa_id, CU_DEVICE_ATTRIBUTE_HOST_NUMA_ID, cd));
  CU(cuDriverGetVersion(&drv));
  printf("device %s driver_api %d vmm %d host_numa_vmm %d host_numa_id %d\n", name, drv, vmm, numa_vmm, numa_id);
  if (!vmm || !numa_vmm) { printf("host-located VMM not supported: stop\n"); return 69; }
  int nid = numa_id < 0 ? 0 : numa_id;
  CUmemAllocationProp gp; memset(&gp, 0, sizeof gp);
  gp.type = CU_MEM_ALLOCATION_TYPE_PINNED; gp.location.type = CU_MEM_LOCATION_TYPE_DEVICE; gp.location.id = dev;
  size_t gdev; CU(cuMemGetAllocationGranularity(&gdev, &gp, CU_MEM_ALLOC_GRANULARITY_MINIMUM));
  gp.location.type = CU_MEM_LOCATION_TYPE_HOST_NUMA; gp.location.id = nid;
  size_t ghost; CU(cuMemGetAllocationGranularity(&ghost, &gp, CU_MEM_ALLOC_GRANULARITY_MINIMUM));
  size_t page = std::max(gdev, ghost);
  printf("granularity device %zu host_numa %zu page %zu\n", gdev, ghost, page);
  if (row % 16 || row == 0 || row > half_pages * page) { fprintf(stderr, "row must be a nonzero multiple of 16 within a half\n"); return 64; }
  size_t half = half_pages * page, total = 2 * half;
  CUdeviceptr base; CU(cuMemAddressReserve(&base, total + page, page, 0, 0));  // one spare page of VA for the move's scratch
  CUmemGenericAllocationHandle hc = make(half, CU_MEM_LOCATION_TYPE_DEVICE, dev);
  CUmemGenericAllocationHandle hh = make(half, CU_MEM_LOCATION_TYPE_HOST_NUMA, nid);
  CU(cuMemMap(base, half, 0, hc, 0));
  CU(cuMemMap(base + half, half, 0, hh, 0));
  access(base, total, dev);
  // The pattern: word i of the whole range is i * golden, written through the one pointer.
  {
    std::vector<unsigned long long> h(page / 8);
    for (size_t p = 0; p < 2 * half_pages; p++) {
      size_t first = p * (page / 8);
      for (size_t i = 0; i < h.size(); i++) h[i] = (first + i) * 0x9e3779b97f4a7c15ull;
      CU(cuMemcpyHtoD(base + p * page, h.data(), page));
    }
  }
  unsigned long long* sink; CK(cudaMalloc(&sink, 8));
  unsigned long long* bad; CK(cudaMalloc(&bad, 8));
  cudaDeviceProp prop; CK(cudaGetDeviceProperties(&prop, dev));
  int grid = prop.multiProcessorCount * 8, block = 256;
  auto verify = [&](CUdeviceptr at, size_t first_word, size_t words) {
    unsigned long long none = ~0ull; CK(cudaMemcpy(bad, &none, 8, cudaMemcpyHostToDevice));
    check<<<grid, block>>>((const unsigned long long*)at, first_word, words, bad);
    CK(cudaDeviceSynchronize());
    unsigned long long got; CK(cudaMemcpy(&got, bad, 8, cudaMemcpyDeviceToHost));
    return got == ~0ull;
  };
  printf("values card half %s host half %s\n", verify(base, 0, half / 8) ? "ok" : "BAD",
         verify(base + half, half / 8, half / 8) ? "ok" : "BAD");
  cudaEvent_t a, b; CK(cudaEventCreate(&a)); CK(cudaEventCreate(&b));
  auto time = [&](auto launch, double bytes, const char* what) {
    launch(); CK(cudaDeviceSynchronize());
    std::vector<float> ms;
    for (int r = 0; r < reps; r++) {
      CK(cudaEventRecord(a)); launch(); CK(cudaEventRecord(b)); CK(cudaEventSynchronize(b));
      float t; CK(cudaEventElapsedTime(&t, a, b)); ms.push_back(t);
    }
    float m = median(ms);
    printf("%-34s %8.3f ms %8.2f GB/s\n", what, m, bytes / m / 1e6);
  };
  size_t rows_half = half / row, nread = rows_half / 4, wpr = row / 16;
  std::vector<unsigned> idx(nread); srand(12345);
  for (size_t i = 0; i < nread; i++) idx[i] = (unsigned)(((size_t)rand() * RAND_MAX + rand()) % rows_half);
  unsigned* didx; CK(cudaMalloc(&didx, nread * 4)); CK(cudaMemcpy(didx, idx.data(), nread * 4, cudaMemcpyHostToDevice));
  // The mixed set: the same count of rows drawn over both halves.
  std::vector<unsigned> mix(nread);
  for (size_t i = 0; i < nread; i++) mix[i] = (unsigned)(((size_t)rand() * RAND_MAX + rand()) % (2 * rows_half));
  unsigned* dmix; CK(cudaMalloc(&dmix, nread * 4)); CK(cudaMemcpy(dmix, mix.data(), nread * 4, cudaMemcpyHostToDevice));
  const uint4* card = (const uint4*)base; const uint4* host = (const uint4*)(base + half);
  char what[64];
  time([&] { seq_read<<<grid, block>>>(card, half / 16, sink); }, half, "seq card half");
  time([&] { seq_read<<<grid, block>>>(host, half / 16, sink); }, half, "seq host half");
  snprintf(what, sizeof what, "rows %zu B card half", row);
  time([&] { row_read<<<grid, block>>>(card, didx, nread, wpr, sink); }, (double)nread * row, what);
  snprintf(what, sizeof what, "rows %zu B host half", row);
  time([&] { row_read<<<grid, block>>>(host, didx, nread, wpr, sink); }, (double)nread * row, what);
  snprintf(what, sizeof what, "rows %zu B both halves", row);
  time([&] { row_read<<<grid, block>>>(card, dmix, nread, wpr, sink); }, (double)nread * row, what);
  // Move the card half's last 8 pages to the host at their addresses, one page at a time: a host handle mapped at the
  // scratch page, the card page copied into it, both unmapped, the host handle mapped where the card page was.
  CU(cuMemUnmap(base, half));
  CU(cuMemRelease(hc));
  std::vector<CUmemGenericAllocationHandle> pc(half_pages);
  for (size_t p = 0; p < half_pages; p++) {  // the card half again, a handle a page, so one page can leave alone
    pc[p] = make(page, CU_MEM_LOCATION_TYPE_DEVICE, dev);
    CU(cuMemMap(base + p * page, page, 0, pc[p], 0));
  }
  access(base, half, dev);
  {
    std::vector<unsigned long long> h(page / 8);
    for (size_t p = 0; p < half_pages; p++) {
      size_t first = p * (page / 8);
      for (size_t i = 0; i < h.size(); i++) h[i] = (first + i) * 0x9e3779b97f4a7c15ull;
      CU(cuMemcpyHtoD(base + p * page, h.data(), page));
    }
  }
  CUdeviceptr scratch = base + total;
  size_t freed_before, total_mem; CU(cuMemGetInfo(&freed_before, &total_mem));
  std::vector<double> us;
  for (size_t k = 0; k < 8; k++) {
    size_t p = half_pages - 1 - k;
    auto t0 = std::chrono::steady_clock::now();
    CUmemGenericAllocationHandle hp = make(page, CU_MEM_LOCATION_TYPE_HOST_NUMA, nid);
    CU(cuMemMap(scratch, page, 0, hp, 0));
    access(scratch, page, dev);
    CU(cuMemcpyDtoD(scratch, base + p * page, page));
    CU(cuCtxSynchronize());
    CU(cuMemUnmap(scratch, page));
    CU(cuMemUnmap(base + p * page, page));
    CU(cuMemRelease(pc[p]));
    CU(cuMemMap(base + p * page, page, 0, hp, 0));
    access(base + p * page, page, dev);
    CU(cuMemRelease(hp));  // the mapping holds it
    us.push_back(std::chrono::duration<double, std::micro>(std::chrono::steady_clock::now() - t0).count());
  }
  size_t freed_after; CU(cuMemGetInfo(&freed_after, &total_mem));
  std::vector<double> s = us; std::sort(s.begin(), s.end());
  printf("move card->host a %zu B page: median %.1f us, min %.1f, max %.1f (8 pages); card free +%lld B\n", page,
         s[s.size() / 2], s.front(), s.back(), (long long)freed_after - (long long)freed_before);
  printf("values after the move: card pages %s, moved pages %s\n",
         verify(base, 0, (half_pages - 8) * page / 8) ? "ok" : "BAD",
         verify(base + (half_pages - 8) * page, (half_pages - 8) * page / 8, 8 * page / 8) ? "ok" : "BAD");
  return 0;
}
