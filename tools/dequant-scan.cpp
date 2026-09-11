// Dequantize one tensor from a GGUF with ggml's own reference path and scan
// for non-finite values.  usage: dq <gguf> <tensor-name> [max_experts]
#include "ggml.h"
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

int main(int argc, char ** argv) {
    if (argc < 3) { fprintf(stderr, "usage: dq <gguf> <tensor> [max_experts]\n"); return 2; }
    const char * path = argv[1];
    const char * want = argv[2];
    const int64_t first_m = argc > 3 ? atoll(argv[3]) : 0;
    const int64_t max_m   = argc > 4 ? atoll(argv[4]) : -1;

    ggml_context * meta = nullptr;
    struct gguf_init_params p;
    p.no_alloc = true;
    p.ctx      = &meta;
    gguf_context * gg = gguf_init_from_file(path, p);
    if (!gg) { fprintf(stderr, "gguf_init_from_file failed\n"); return 1; }

    const int idx = gguf_find_tensor(gg, want);
    if (idx < 0) { fprintf(stderr, "tensor not found: %s\n", want); return 1; }

    ggml_tensor * t = ggml_get_tensor(meta, want);
    const size_t data_off = gguf_get_data_offset(gg) + gguf_get_tensor_offset(gg, idx);
    const enum ggml_type type = t->type;
    const int64_t ne0 = t->ne[0], ne1 = t->ne[1], ne2 = t->ne[2];
    const size_t row_bytes = ggml_row_size(type, ne0);

    printf("%s type=%s ne=%lld,%lld,%lld row_bytes=%zu blck=%lld tsize=%zu data_off=%zu\n",
            want, ggml_type_name(type), (long long) ne0, (long long) ne1, (long long) ne2,
            row_bytes, (long long) ggml_blck_size(type), ggml_type_size(type), data_off);

    ggml_type_traits_t tr = ggml_internal_get_type_traits(type);
    if (!tr.to_float) { fprintf(stderr, "no to_float for this type\n"); return 1; }

    FILE * f = fopen(path, "rb");
    if (!f) { perror("fopen"); return 1; }

    std::vector<unsigned char> raw(row_bytes);
    std::vector<float>         out(ne0);
    long long bad_rows = 0, bad_vals = 0, checked = 0;
    int reported = 0;

    const int64_t last_m = max_m > 0 && max_m < ne2 ? max_m : ne2;
    for (int64_t m = first_m; m < last_m; ++m) {
        for (int64_t r = 0; r < ne1; ++r) {
            const size_t off = data_off + ((size_t) m * ne1 + r) * row_bytes;
            if (fseeko(f, off, SEEK_SET) != 0) { perror("fseeko"); return 1; }
            if (fread(raw.data(), 1, row_bytes, f) != row_bytes) { perror("fread"); return 1; }
            tr.to_float(raw.data(), out.data(), ne0);
            checked += ne0;
            long long n = 0;
            for (int64_t i = 0; i < ne0; ++i) if (!std::isfinite(out[i])) ++n;
            if (n) {
                ++bad_rows; bad_vals += n;
                if (reported < 2) {
                    ++reported;
                    printf("non-finite: expert=%lld row=%lld  (%lld of %lld in that row)\n",
                            (long long) m, (long long) r, n, (long long) ne0);
                    for (int64_t i = 0; i < ne0; ++i) {
                        if (!std::isfinite(out[i])) {
                            const int64_t blk = i / ggml_blck_size(type);
                            printf("  elem %lld = %g   block %lld raw:",
                                    (long long) i, out[i], (long long) blk);
                            const size_t bs = ggml_type_size(type);
                            const unsigned char * b = raw.data() + blk * bs;
                            for (size_t k = 0; k < bs; ++k) printf(" %02x", b[k]);
                            printf("\n");
                            break;
                        }
                    }
                }
            }
        }
        if (bad_rows && m == first_m) printf("  expert %lld: bad_rows so far %lld\n", (long long) m, bad_rows);
        if (m % 32 == 31) {
            printf("  .. through expert %lld: bad_rows=%lld\n", (long long) m, bad_rows);
            fflush(stdout);
        }
    }
    printf("RESULT %s: checked=%lld values, non-finite=%lld in %lld rows\n",
            want, checked, bad_vals, bad_rows);
    fclose(f);
    return 0;
}
