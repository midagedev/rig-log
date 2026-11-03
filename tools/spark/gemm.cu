// Dense GEMM throughput probe (cuBLAS), 2026-11-03. Usage: gemm <bf16|fp16|fp32|tf32> <M=N=K> [reps]
// Reports best and mean TFLOP/s (2*M*N*K per call). Inputs are filled with small values so nothing overflows.
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cuda_runtime.h>
#include <cuda_bf16.h>
#include <cuda_fp16.h>
#include <cublas_v2.h>
#define CK(x) do { cudaError_t e = (x); if (e != cudaSuccess) { fprintf(stderr, "%s: %s\n", #x, cudaGetErrorString(e)); exit(1); } } while (0)
#define CB(x) do { cublasStatus_t s = (x); if (s != CUBLAS_STATUS_SUCCESS) { fprintf(stderr, "%s: cublas %d\n", #x, (int) s); exit(1); } } while (0)

int main(int argc, char **argv) {
    const char *t = argc > 1 ? argv[1] : "bf16";
    int n = argc > 2 ? atoi(argv[2]) : 8192, reps = argc > 3 ? atoi(argv[3]) : 20;
    cudaDataType ab; cublasComputeType_t ct = CUBLAS_COMPUTE_32F; size_t es;
    if (!strcmp(t, "bf16")) { ab = CUDA_R_16BF; es = 2; }
    else if (!strcmp(t, "fp16")) { ab = CUDA_R_16F; es = 2; }
    else if (!strcmp(t, "tf32")) { ab = CUDA_R_32F; es = 4; ct = CUBLAS_COMPUTE_32F_FAST_TF32; }
    else { ab = CUDA_R_32F; es = 4; }
    cudaDataType cty = es == 2 ? ab : CUDA_R_32F;
    size_t sz = (size_t) n * n;
    void *A, *B, *C; CK(cudaMalloc(&A, sz * es)); CK(cudaMalloc(&B, sz * es)); CK(cudaMalloc(&C, sz * es));
    CK(cudaMemset(A, 0x3c, sz * es)); CK(cudaMemset(B, 0x3c, sz * es)); CK(cudaMemset(C, 0, sz * es));  // ~1.0 in fp16/bf16 high byte
    cublasHandle_t h; CB(cublasCreate(&h));
    float al = 1e-4f, be = 0.f;
    cudaEvent_t e0, e1; CK(cudaEventCreate(&e0)); CK(cudaEventCreate(&e1));
    auto call = [&]() { CB(cublasGemmEx(h, CUBLAS_OP_N, CUBLAS_OP_N, n, n, n, &al, A, ab, n, B, ab, n, &be, C, cty, n, ct, CUBLAS_GEMM_DEFAULT)); };
    for (int i = 0; i < 3; i++) call();
    CK(cudaDeviceSynchronize());
    float best = 1e30f, sum = 0;
    for (int r = 0; r < reps; r++) {
        CK(cudaEventRecord(e0)); call(); CK(cudaEventRecord(e1)); CK(cudaEventSynchronize(e1));
        float ms; CK(cudaEventElapsedTime(&ms, e0, e1)); sum += ms; if (ms < best) best = ms;
    }
    double fl = 2.0 * n * (double) n * n;
    printf("gemm %s  n=%d  best %.1f TFLOP/s  mean %.1f TFLOP/s  (%d reps)\n", t, n, fl / (best * 1e-3) / 1e12, fl / (sum / reps * 1e-3) / 1e12, reps);
    return 0;
}
