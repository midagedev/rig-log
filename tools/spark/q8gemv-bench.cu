// Q8_0 decode gemv variants on the GB10, 2026-11-04: the one-token (m = 1) product of every Q8_0 tensor that
// Qwen3.6-35B-A3B UD-Q4_K_M reads per token (shapes from the file: 30 GDN layers' qkv/gate/ssm_out, 10 attention
// layers' q/k/v/o, 40 shared experts' gate/up/down; 1.49 GB), run as one CUDA graph per variant, so launch gaps
// count as they do in a captured decode step. Variants:
//   A  bloomery 0.3.12's q8_0_gemv as written (crates/gpu/src/q8f32.rs): a warp per row, 8 rows a 256-thread block,
//      lane l reads code word 32s+l (4 B) and its f16 block scale, and the word's four f32 activations from global
//   B  A with 16 B code loads (4 words a lane per step) and the activations staged in shared memory as f32
//   C  llama.cpp's shape: activations quantized once to q8_1 (int8 + f32 scale per 32), 16 B code loads, dp4a
//   F  C with same-input tensors fused into one launch (qkv+gate, q+k+v, shexp gate+up), as llama.cpp fuses
//   D  A with the row split over S warps (split-K, a shared-memory sum) for tensors of at most 1,024 rows (shared-expert
//      gate/up, attention k/v: 512 rows are 64 blocks of A, a fifth of the GB10's 48 SMs' warp slots), S = 4; A elsewhere
// Weights are random codes; outputs are checked against A (largest |difference| over A's rms, printed). Usage: q8gemv-bench [iters=200]
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include <vector>
#include <cuda_fp16.h>
#define CK(x) do { cudaError_t e = (x); if (e != cudaSuccess) { printf("%s:%d %s\n", __FILE__, __LINE__, cudaGetErrorString(e)); exit(1); } } while (0)

struct T { int rows, k; const char* name; };

// A: bloomery layout, qs rows x k/4 u32, d rows x k/32 f16
__global__ void gemv_a(const uint32_t* qs, const __half* d, const float* x, int rows, int k, float* y) {
  int row = blockIdx.x * 8 + threadIdx.x / 32, lane = threadIdx.x % 32;
  if (row >= rows) return;
  int words = k / 4; const uint32_t* w = qs + (size_t)row * words; const __half* s = d + (size_t)row * (k / 32);
  float acc = 0.f;
  for (int i = lane; i < words; i += 32) {
    uint32_t c = w[i]; float sc = __half2float(s[i / 8]); float4 xv = reinterpret_cast<const float4*>(x)[i];
    acc += sc * ((float)(int8_t)(c & 255) * xv.x + (float)(int8_t)((c >> 8) & 255) * xv.y +
                 (float)(int8_t)((c >> 16) & 255) * xv.z + (float)(int8_t)(c >> 24) * xv.w);
  }
  for (int o = 16; o; o >>= 1) acc += __shfl_xor_sync(0xffffffff, acc, o);
  if (lane == 0) y[row] = acc;
}

// D: S warps a row (split-K); 8/S rows a 256-thread block
template <int S>
__global__ void gemv_d(const uint32_t* qs, const __half* d, const float* x, int rows, int k, float* y) {
  __shared__ float part[8];
  int w = threadIdx.x / 32, lane = threadIdx.x % 32, row = blockIdx.x * (8 / S) + w / S, sub = w % S;
  float acc = 0.f;
  if (row < rows) {
    int words = k / 4; const uint32_t* wq = qs + (size_t)row * words; const __half* s = d + (size_t)row * (k / 32);
    for (int i = sub * 32 + lane; i < words; i += 32 * S) {
      uint32_t c = wq[i]; float sc = __half2float(s[i / 8]); float4 xv = reinterpret_cast<const float4*>(x)[i];
      acc += sc * ((float)(int8_t)(c & 255) * xv.x + (float)(int8_t)((c >> 8) & 255) * xv.y +
                   (float)(int8_t)((c >> 16) & 255) * xv.z + (float)(int8_t)(c >> 24) * xv.w);
    }
  }
  for (int o = 16; o; o >>= 1) acc += __shfl_xor_sync(0xffffffff, acc, o);
  if (lane == 0) part[w] = acc;
  __syncthreads();
  if (row < rows && sub == 0 && lane == 0) { float t = 0.f; for (int j = 0; j < S; j++) t += part[w + j]; y[row] = t; }
}

// B: 16 B code loads, x in shared f32 (k <= 8192)
__global__ void gemv_b(const uint32_t* qs, const __half* d, const float* x, int rows, int k, float* y) {
  extern __shared__ float xs[];
  for (int i = threadIdx.x; i < k / 4; i += 256) reinterpret_cast<float4*>(xs)[i] = reinterpret_cast<const float4*>(x)[i];
  __syncthreads();
  int row = blockIdx.x * 8 + threadIdx.x / 32, lane = threadIdx.x % 32;
  if (row >= rows) return;
  const uint4* w = reinterpret_cast<const uint4*>(qs + (size_t)row * (k / 4)); const __half* s = d + (size_t)row * (k / 32);
  float acc = 0.f;
  for (int i = lane; i < k / 16; i += 32) {            // 16 values a step: half a block
    uint4 c = w[i]; float sc = __half2float(s[i / 2]); const float* xv = xs + i * 16; uint32_t cc[4] = {c.x, c.y, c.z, c.w};
    float a = 0.f;
#pragma unroll
    for (int j = 0; j < 4; j++)
#pragma unroll
      for (int b = 0; b < 4; b++) a += (float)(int8_t)((cc[j] >> (8 * b)) & 255) * xv[4 * j + b];
    acc += sc * a;
  }
  for (int o = 16; o; o >>= 1) acc += __shfl_xor_sync(0xffffffff, acc, o);
  if (lane == 0) y[row] = acc;
}

// q8_1 quantize of x: one warp per 32-value block
__global__ void quant_q81(const float* x, int k, int8_t* xq, float* xd) {
  int b = (blockIdx.x * blockDim.x + threadIdx.x) / 32, lane = threadIdx.x % 32;
  if (b >= k / 32) return;
  float v = x[b * 32 + lane], m = fabsf(v);
  for (int o = 16; o; o >>= 1) m = fmaxf(m, __shfl_xor_sync(0xffffffff, m, o));
  float dd = m / 127.f; xq[b * 32 + lane] = (int8_t)(dd > 0 ? rintf(v / dd) : 0); if (lane == 0) xd[b] = dd;
}

// C: dp4a over q8_1 activations staged in shared; 16 B code loads; rows of several tensors in one launch when fused
struct Seg { const uint32_t* qs; const __half* d; float* y; int rows; int row0; };
struct Segs { Seg s[3]; int n; };
__global__ void gemv_c(Segs g, const int8_t* xq, const float* xd, int k) {
  extern __shared__ int8_t sm[];
  int8_t* xs = sm; float* ds = reinterpret_cast<float*>(sm + k);
  for (int i = threadIdx.x; i < k / 16; i += 256) reinterpret_cast<int4*>(xs)[i] = reinterpret_cast<const int4*>(xq)[i];
  for (int i = threadIdx.x; i < k / 32; i += 256) ds[i] = xd[i];
  __syncthreads();
  int grow = blockIdx.x * 8 + threadIdx.x / 32, lane = threadIdx.x % 32;
  int si = 0; while (si + 1 < g.n && grow >= g.s[si + 1].row0) si++;
  Seg sg = g.s[si]; int row = grow - sg.row0;
  if (row >= sg.rows) return;
  const int4* w = reinterpret_cast<const int4*>(sg.qs + (size_t)row * (k / 4)); const __half* s = sg.d + (size_t)row * (k / 32);
  float acc = 0.f;
  for (int i = lane; i < k / 16; i += 32) {
    int4 c = w[i]; const int* xv = reinterpret_cast<const int*>(xs + i * 16);
    int a = __dp4a(c.x, xv[0], 0); a = __dp4a(c.y, xv[1], a); a = __dp4a(c.z, xv[2], a); a = __dp4a(c.w, xv[3], a);
    acc += __half2float(s[i / 2]) * ds[i / 2] * (float)a;
  }
  for (int o = 16; o; o >>= 1) acc += __shfl_xor_sync(0xffffffff, acc, o);
  if (lane == 0) sg.y[row] = acc;
}

int main(int argc, char** argv) {
  int iters = argc > 1 ? atoi(argv[1]) : 200;
  // per-token Q8_0 tensors in layer order; group id marks same-input sets that F fuses
  struct L { T t; int group; };
  std::vector<L> seq; int g = 0;
  for (int l = 0; l < 40; l++) {
    bool full = (l % 4 == 3);                      // 10 full-attention layers, 30 GDN
    if (full) { seq.push_back({{8192, 2048, "attn_q"}, g}); seq.push_back({{512, 2048, "attn_k"}, g}); seq.push_back({{512, 2048, "attn_v"}, g}); g++;
                seq.push_back({{2048, 4096, "attn_output"}, g++}); }
    else      { seq.push_back({{8192, 2048, "attn_qkv"}, g}); seq.push_back({{4096, 2048, "attn_gate"}, g}); g++;
                seq.push_back({{2048, 4096, "ssm_out"}, g++}); }
    seq.push_back({{512, 2048, "shexp_gate"}, g}); seq.push_back({{512, 2048, "shexp_up"}, g}); g++;
    seq.push_back({{2048, 512, "shexp_down"}, g++});
  }
  size_t bytes = 0; for (auto& e : seq) bytes += (size_t)e.t.rows * e.t.k / 32 * 34;
  printf("tensors %zu, groups %d, Q8_0 bytes per token %.1f MB\n", seq.size(), g, bytes / 1e6);
  std::vector<uint32_t*> qs(seq.size()); std::vector<__half*> dd(seq.size()); std::vector<float*> ya(seq.size()), yc(seq.size());
  float* x; int8_t* xq; float* xd; CK(cudaMalloc(&x, 8192 * 4)); CK(cudaMalloc(&xq, 8192)); CK(cudaMalloc(&xd, 256 * 4));
  { std::vector<float> h(8192); for (auto& v : h) v = (rand() / (float)RAND_MAX - 0.5f); CK(cudaMemcpy(x, h.data(), 8192 * 4, cudaMemcpyHostToDevice)); }
  for (size_t i = 0; i < seq.size(); i++) {
    size_t r = seq[i].t.rows, k = seq[i].t.k;
    CK(cudaMalloc(&qs[i], r * k)); CK(cudaMalloc(&dd[i], r * k / 32 * 2)); CK(cudaMalloc(&ya[i], r * 4)); CK(cudaMalloc(&yc[i], r * 4));
    std::vector<uint32_t> hq(r * k / 4); for (auto& v : hq) v = (uint32_t)rand() * 2654435761u; CK(cudaMemcpy(qs[i], hq.data(), r * k, cudaMemcpyHostToDevice));
    std::vector<__half> hd(r * k / 32); for (auto& v : hd) v = __float2half(0.001f + (rand() % 100) * 1e-5f); CK(cudaMemcpy(dd[i], hd.data(), r * k / 32 * 2, cudaMemcpyHostToDevice));
  }
  cudaStream_t st; CK(cudaStreamCreate(&st));
  CK(cudaFuncSetAttribute(gemv_b, cudaFuncAttributeMaxDynamicSharedMemorySize, 32768));
  auto run = [&](char v) {
    if (v == 'A') for (size_t i = 0; i < seq.size(); i++) gemv_a<<<(seq[i].t.rows + 7) / 8, 256, 0, st>>>(qs[i], dd[i], x, seq[i].t.rows, seq[i].t.k, ya[i]);
    if (v == 'D') for (size_t i = 0; i < seq.size(); i++) {
      if (seq[i].t.rows <= 1024) gemv_d<4><<<(seq[i].t.rows + 1) / 2, 256, 0, st>>>(qs[i], dd[i], x, seq[i].t.rows, seq[i].t.k, yc[i]);
      else gemv_a<<<(seq[i].t.rows + 7) / 8, 256, 0, st>>>(qs[i], dd[i], x, seq[i].t.rows, seq[i].t.k, yc[i]);
    }
    if (v == 'B') for (size_t i = 0; i < seq.size(); i++) gemv_b<<<(seq[i].t.rows + 7) / 8, 256, seq[i].t.k * 4, st>>>(qs[i], dd[i], x, seq[i].t.rows, seq[i].t.k, yc[i]);
    if (v == 'C' || v == 'F') {
      // one quantize per distinct input (per group in F, per tensor-input in C: llama.cpp quantizes once per input too)
      int lastg = -1;
      for (size_t i = 0; i < seq.size();) {
        int k = seq[i].t.k;
        if (seq[i].group != lastg) { quant_q81<<<(k / 32 * 32 + 255) / 256, 256, 0, st>>>(x, k, xq, xd); lastg = seq[i].group; }
        Segs sg{}; sg.n = 0; int rows = 0; size_t j = i;
        do { sg.s[sg.n++] = {qs[j], dd[j], yc[j], seq[j].t.rows, rows}; rows += seq[j].t.rows; j++; }
        while (v == 'F' && j < seq.size() && seq[j].group == seq[i].group && sg.n < 3);
        gemv_c<<<(rows + 7) / 8, 256, k + k / 32 * 4, st>>>(sg, xq, xd, k);
        i = j;
      }
    }
  };
  int launches[256] = {0};
  for (char v : {'A', 'D', 'B', 'C', 'F'}) {
    cudaGraph_t gr; cudaGraphExec_t ge;
    CK(cudaStreamBeginCapture(st, cudaStreamCaptureModeGlobal)); run(v); CK(cudaStreamEndCapture(st, &gr));
    size_t nn; CK(cudaGraphGetNodes(gr, nullptr, &nn)); launches[(int)v] = (int)nn;
    CK(cudaGraphInstantiate(&ge, gr, 0));
    for (int i = 0; i < 5; i++) CK(cudaGraphLaunch(ge, st));
    cudaEvent_t e0, e1; CK(cudaEventCreate(&e0)); CK(cudaEventCreate(&e1));
    CK(cudaEventRecord(e0, st)); for (int i = 0; i < iters; i++) CK(cudaGraphLaunch(ge, st)); CK(cudaEventRecord(e1, st));
    CK(cudaStreamSynchronize(st)); float ms; CK(cudaEventElapsedTime(&ms, e0, e1)); ms /= iters;
    double diff = 0;
    if (v != 'A') for (size_t i = 0; i < seq.size(); i += 7) {
      std::vector<float> a(seq[i].t.rows), c(seq[i].t.rows);
      CK(cudaMemcpy(a.data(), ya[i], a.size() * 4, cudaMemcpyDeviceToHost)); CK(cudaMemcpy(c.data(), yc[i], c.size() * 4, cudaMemcpyDeviceToHost));
      double rms = 0; for (float q : a) rms += (double)q * q; rms = sqrt(rms / a.size()) + 1e-12;
      for (size_t r = 0; r < a.size(); r++) { double dlt = fabs(a[r] - c[r]) / rms; if (dlt > diff) diff = dlt; }
    }
    printf("{\"variant\":\"%c\",\"ms_per_token\":%.4f,\"gbs\":%.1f,\"nodes\":%d,\"max_rel_diff_vs_A\":%.3g}\n", v, ms, bytes / ms / 1e6, launches[(int)v], diff);
  }
  return 0;
}
