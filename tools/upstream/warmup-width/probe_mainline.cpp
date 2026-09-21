// probe_mainline -- does ggml-org/llama.cpp widen a MoE graph to all experts the way
// ik_llama.cpp does?
//
// ik_llama.cpp infers a warmup graph per graph build (line numbers at upstream main 9cba2e38):
//   src/llama-build-context.cpp:2742
//     bool is_warming_up = lctx.n_eval == 0 && (batch.n_tokens == 1 && (batch.token[0] == BOS));
//   src/llama-build-context.cpp:58
//     n_expert_used (warmup ? hparams.n_expert : hparams.n_expert_used),
// and n_eval is a statistics counter raised only inside llama_synchronize and zeroed by
// llama_reset_timings, so the answer a program gets depends on whether that counter happens
// to be non-zero. Measured on DeepSeek-V2-Lite-Chat Q3_K_M: inserting one llama_synchronize
// after a lone BOS decode flips the next sequence's argmax.
//
// This is the same probe against mainline's API. Mainline's equivalent expression
// (src/llama-graph.cpp:1472) reads cparams.warmup, an explicit caller-set flag, so the
// prediction is that every mechanism arm returns the same logits. A null result is only
// worth something with a positive control, so warm_explicit calls llama_set_warmup() and
// must move the width; --width prints the realized ffn_moe_topk width per graph.
//
// This tool does not tokenize: token ids come from a TSV, so both engines see identical ids.
// It writes no files and changes nothing on disk.
//
// Build: build-mainline.sh
// Run:   $OUT/probe_mainline -m <gguf> --prompts <tsv> --seq 24 --prior 5 -ngl 0 -c 512 -t 8
#include "llama.h"
#include "common.h"
#include "arg.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

static std::vector<llama_token> read_prompt(const char * path, int want) {
    std::vector<llama_token> out;
    std::ifstream in(path);
    if (!in) {
        fprintf(stderr, "probe_mainline: cannot read %s\n", path);
        return out;
    }
    std::string line;
    while (std::getline(in, line)) {
        if (line.empty() || line[0] == '#') continue;
        std::stringstream ss(line);
        std::string id, text, ids;
        if (!std::getline(ss, id, '\t')) continue;
        if (!std::getline(ss, text, '\t')) continue;
        if (!std::getline(ss, ids, '\t')) continue;
        if (atoi(id.c_str()) != want) continue;
        std::stringstream ts(ids);
        std::string tok;
        while (std::getline(ts, tok, ',')) out.push_back((llama_token) atoi(tok.c_str()));
        return out;
    }
    return out;
}

static int g_n_vocab = 0;

// logit descending, id ascending -- the row order the reference files use.
static std::vector<int> top5(const std::vector<float> & lg) {
    std::vector<int> idx(g_n_vocab);
    for (int i = 0; i < g_n_vocab; ++i) idx[i] = i;
    std::partial_sort(idx.begin(), idx.begin() + 5, idx.end(), [&](int a, int b) {
        if (lg[a] != lg[b]) return lg[a] > lg[b];
        return a < b;
    });
    idx.resize(5);
    return idx;
}

// --width: report the realized expert width of every graph. ffn_moe_topk's ne[0] IS
// n_expert_used as the graph was built, so this reads the widening directly instead of
// inferring it from logits. The callback makes the scheduler walk node by node, which can
// change fused kernels and therefore values -- shapes are decided at graph-build time and
// are not affected, which is why this mode reports shapes only.
static bool g_width_on   = false;
static int  g_width_graph = 0;

static bool width_cb(struct ggml_tensor * t, bool ask, void * /*user_data*/) {
    if (!g_width_on || !ask) return false;
    if (strncmp(t->name, "ffn_moe_topk", 12) == 0) {
        printf("W\tgraph=%d\t%s\tne=%lld,%lld\n", g_width_graph, t->name,
               (long long) t->ne[0], (long long) t->ne[1]);
        fflush(stdout);
    }
    return false;   // shapes only; do not ask for the computed data
}

static std::vector<float> snapshot(llama_context * ctx) {
    const float * p = llama_get_logits_ith(ctx, -1);
    return std::vector<float>(p, p + g_n_vocab);
}

// llama_get_logits_ith calls llama_synchronize internally; g_use_sync makes the read slot
// call only llama_synchronize, to separate the scheduler sync from the logits bookkeeping.
static bool g_use_sync = false;
static void read_slot(llama_context * ctx) {
    if (g_use_sync) llama_synchronize(ctx);
    else            (void) llama_get_logits_ith(ctx, -1);
}

// Mainline's llama_batch_get_one takes (tokens, n_tokens): positions are tracked from the
// memory module's max position for the sequence, so they restart at 0 after a clear and
// continue otherwise -- the same semantics the ik probe spelled out by hand.
static bool decode_one(llama_context * ctx, llama_token t) {
    ++g_width_graph;
    return llama_decode(ctx, llama_batch_get_one(&t, 1)) == 0;
}

static bool decode_many(llama_context * ctx, std::vector<llama_token> toks) {
    ++g_width_graph;
    return llama_decode(ctx, llama_batch_get_one(toks.data(), (int32_t) toks.size())) == 0;
}

enum Reads { RD_NONE, RD_LAST, RD_EACH, RD_BEFORE_LAST };
static const char * reads_name(int r) {
    switch (r) {
        case RD_NONE: return "none";
        case RD_LAST: return "last";
        case RD_EACH: return "each";
        default:      return "before_last";
    }
}

static bool step_decode(llama_context * ctx, const std::vector<llama_token> & toks, int reads) {
    const size_t n = toks.size();
    for (size_t i = 0; i < n; ++i) {
        if (!decode_one(ctx, toks[i])) return false;
        const bool rd = reads == RD_EACH
                     || (reads == RD_LAST        && i + 1 == n)
                     || (reads == RD_BEFORE_LAST && i + 2 == n);
        if (rd) read_slot(ctx);
    }
    return true;
}

enum Reset { R_CLEAR, R_FRESH, R_NONE, R_SKIP };

int main(int argc, char ** argv) {
    const char *        prompts_path = nullptr;
    int                 seq_id = 24, prior_id = 5;
    bool                width = false, width_warmup = false;
    std::vector<char *> passthrough;
    passthrough.push_back(argv[0]);
    for (int i = 1; i < argc; ++i) {
        if      (strcmp(argv[i], "--prompts") == 0 && i + 1 < argc) prompts_path = argv[++i];
        else if (strcmp(argv[i], "--seq")     == 0 && i + 1 < argc) seq_id   = atoi(argv[++i]);
        else if (strcmp(argv[i], "--prior")   == 0 && i + 1 < argc) prior_id = atoi(argv[++i]);
        else if (strcmp(argv[i], "--width")   == 0) width = true;
        else if (strcmp(argv[i], "--width-warmup") == 0) { width = true; width_warmup = true; }
        else passthrough.push_back(argv[i]);
    }
    if (!prompts_path) {
        fprintf(stderr, "probe_mainline: --prompts <tsv> is required; this tool does not tokenize\n");
        return 2;
    }
    std::vector<llama_token> A = read_prompt(prompts_path, seq_id);
    std::vector<llama_token> B = read_prompt(prompts_path, prior_id);
    if (A.empty() || B.empty()) {
        fprintf(stderr, "probe_mainline: prompt %d or %d not in %s\n", seq_id, prior_id, prompts_path);
        return 2;
    }

    common_params params;
    if (!common_params_parse((int) passthrough.size(), passthrough.data(), params, LLAMA_EXAMPLE_COMMON)) return 2;
    params.warmup = false;                 // this tool drives every warmup decision itself
    if (width) { params.cb_eval = width_cb; params.cb_eval_user_data = nullptr; }

    llama_backend_init();
    llama_numa_init(params.numa);
    common_init_result_ptr init = common_init_from_params(params);
    if (!init || !init->model() || !init->context()) {
        fprintf(stderr, "probe_mainline: failed to load the model\n");
        return 1;
    }
    llama_model * model = init->model();
    g_n_vocab = llama_vocab_n_tokens(llama_model_get_vocab(model));
    llama_context_params cparams = common_context_params_to_llama(params);

    printf("# probe_mainline\tmodel=%s\tseq=%d(n=%zu)\tprior=%d(n=%zu)\n",
           params.model.path.c_str(), seq_id, A.size(), prior_id, B.size());
    printf("# params\tn_ctx=%u\tn_batch=%u\tn_ubatch=%u\tn_gpu_layers=%d\tn_threads=%d\ttype_k=%d\ttype_v=%d\n",
           cparams.n_ctx, cparams.n_batch, cparams.n_ubatch,
           params.n_gpu_layers, cparams.n_threads, (int) cparams.type_k, (int) cparams.type_v);

    // --width: the positive control. One fresh context, the sequence fed one token per
    // decode, with cparams.warmup left false or forced true by the caller. If the flag moves
    // the printed width, this tool can see the widening on this tree; if no arm below moves
    // it, that is a measurement and not a blind spot.
    if (width) {
        llama_context * c = llama_init_from_model(model, cparams);
        if (!c) { fprintf(stderr, "probe_mainline: width context alloc failed\n"); return 1; }
        if (width_warmup) llama_set_warmup(c, true);
        printf("# width mode\tllama_set_warmup=%d\thparams n_expert_used is what an honest graph must print\n",
               (int) width_warmup);
        g_width_on = true; g_width_graph = 0;
        if (!step_decode(c, A, RD_NONE)) { fprintf(stderr, "probe_mainline: width decode failed\n"); return 1; }
        g_width_on = false;
        std::vector<float> L = snapshot(c);
        std::vector<int> t = top5(L);
        printf("# width mode argmax=%d\ttop1=%.6f\n", t[0], L[t[0]]);
        fflush(stdout);
        llama_free(c);
        init.reset();          // owns the model and its own context; free before the backend
        llama_backend_free();
        return 0;
    }

    // L0: the sequence in a context that has seen nothing else. Every arm is judged against
    // this, not against the arm before it.
    std::vector<float> L0;
    {
        llama_context * c = llama_init_from_model(model, cparams);
        if (!c || !step_decode(c, A, RD_NONE)) { fprintf(stderr, "probe_mainline: L0 failed\n"); return 1; }
        L0 = snapshot(c);
        llama_free(c);
    }
    std::vector<int> t0 = top5(L0);
    printf("# L0 (fresh context, step prefill)\targmax=%d\ttop5=", t0[0]);
    for (int i = 0; i < 5; ++i) printf("%s%d", i ? "," : "", t0[i]);
    printf("\t");
    for (int i = 0; i < 5; ++i) printf("%s%.6f", i ? "," : "", L0[t0[i]]);
    printf("\n\narm\tprior\treads\textra\treset\ttarget\targmax\tmax_abs_diff\tn_diff\ttop5_ids\ttop5_logits\n");

    auto report = [&](const char * name, const char * prior, const char * reads, const char * extra,
                      const char * reset, const char * target, const std::vector<float> & L1) {
        double mx = 0.0;
        long   nd = 0;
        for (int i = 0; i < g_n_vocab; ++i) {
            double d = std::fabs((double) L1[i] - (double) L0[i]);
            if (d > mx) mx = d;
            if (L1[i] != L0[i]) ++nd;
        }
        std::vector<int> t1 = top5(L1);
        printf("%s\t%s\t%s\t%s\t%s\t%s\t%d\t%.6g\t%ld\t",
               name, prior, reads, extra, reset, target, t1[0], mx, nd);
        for (int i = 0; i < 5; ++i) printf("%s%d", i ? "," : "", t1[i]);
        printf("\t");
        for (int i = 0; i < 5; ++i) printf("%s%.6f", i ? "," : "", L1[t1[i]]);
        printf("\n");
        fflush(stdout);
    };

    // One arm: do the prior work in its own context, reset it, decode A, compare with L0.
    // `prior`: 0 none, 1 A, 2 B. `extra` tokens are fed after the prior sequence the way a
    // generation loop feeds them. R_SKIP stops before the reset and reports the prior's own
    // next-token row.
    auto arm = [&](const char * name, int prior, int reads, int extra, bool extra_read,
                   bool feed_argmax, Reset reset, bool tgt_batch, bool prior_batch,
                   bool use_sync = false) {
        g_use_sync = use_sync;
        llama_context * c = llama_init_from_model(model, cparams);
        if (!c) { fprintf(stderr, "probe_mainline: context alloc failed for %s\n", name); return; }
        const std::vector<llama_token> & P = (prior == 2) ? B : A;
        bool ok = true;
        if (prior != 0) {
            ok = prior_batch ? decode_many(c, P) : step_decode(c, P, reads);
            for (int s = 0; s < extra && ok; ++s) {
                llama_token feed = feed_argmax ? (llama_token) top5(snapshot(c))[0] : A[0];
                ok = decode_one(c, feed);
                if (ok && extra_read) read_slot(c);
            }
        }
        if (!ok) { fprintf(stderr, "probe_mainline: prior decode failed for %s\n", name); llama_free(c); return; }

        std::vector<float> L1;
        const char * reset_label = "clear";
        const char * tgt_label   = tgt_batch ? "batch" : "step";
        if (reset == R_SKIP) {
            reset_label = "-";
            tgt_label   = "-";
            L1 = snapshot(c);
            llama_free(c);
        } else {
            switch (reset) {
                case R_CLEAR: llama_memory_clear(llama_get_memory(c), true); break;
                case R_FRESH: llama_free(c); c = llama_init_from_model(model, cparams);
                              reset_label = "fresh_ctx"; break;
                default:      reset_label = "none"; break;   // the contrast, not a fix
            }
            if (!c) { fprintf(stderr, "probe_mainline: fresh context failed for %s\n", name); return; }
            ok = tgt_batch ? decode_many(c, A) : step_decode(c, A, RD_NONE);
            if (!ok) { fprintf(stderr, "probe_mainline: target decode failed for %s\n", name); llama_free(c); return; }
            L1 = snapshot(c);
            llama_free(c);
        }
        g_use_sync = false;

        char extra_buf[16];
        snprintf(extra_buf, sizeof(extra_buf), "%d%s", extra, extra ? (extra_read ? "r" : "-") : "");
        char reads_buf[32];
        snprintf(reads_buf, sizeof(reads_buf), "%s%s", reads_name(reads), use_sync ? "(sync)" : "");
        report(name, prior == 0 ? "none" : (prior == 2 ? "B" : "A"), reads_buf, extra_buf,
               reset_label, tgt_label, L1);
    };

    //   name                    prior reads          extra rd     argmax reset    tgtB  priorB
    arm("self_noread",              1, RD_NONE,        0, false, false, R_SKIP,  false, false);
    arm("ctl_fresh",                0, RD_NONE,        0, false, false, R_CLEAR, false, false);
    arm("gen0_shape",               1, RD_LAST,        0, false, false, R_CLEAR, false, false);
    arm("gen1_shape",               1, RD_LAST,        1, true,  true,  R_CLEAR, false, false);
    arm("gen1_noread_after_extra",  1, RD_LAST,        1, false, false, R_CLEAR, false, false);
    arm("prior_read_each",          1, RD_EACH,        0, false, false, R_CLEAR, false, false);
    arm("priorB_gen1_shape",        2, RD_LAST,        1, true,  false, R_CLEAR, false, false);
    arm("gen1_freshctx",            1, RD_LAST,        1, true,  true,  R_FRESH, false, false);
    arm("gen1_noreset",             1, RD_LAST,        1, true,  true,  R_NONE,  false, false);
    arm("fresh_batch",              0, RD_NONE,        0, false, false, R_CLEAR, true,  false);
    arm("gen1_shape_sync",          1, RD_LAST,        1, true,  false, R_CLEAR, false, false, true);

    // The mechanism arms. On ik each of these flips exactly one conjunct of the inferred
    // predicate and warm1_sync alone changes the answer. Mainline has no such predicate, so
    // the prediction is that all five agree; warm_explicit is the positive control that says
    // this tool would have seen a widening if one had happened.
    printf("\n# mechanism arms (each flips one conjunct of ik's is_warming_up)\narm\tflipped\targmax\tmax_abs_diff\ttop5_logits\n");
    auto mech = [&](const char * name, const char * what, int lead_tokens, bool sync_after,
                    bool reset_perf, int batch_prefix, bool explicit_warmup) {
        llama_context * c = llama_init_from_model(model, cparams);
        if (!c) return;
        if (explicit_warmup) llama_set_warmup(c, true);
        for (int i = 0; i < lead_tokens; ++i) {
            if (!decode_one(c, A[0])) { llama_free(c); return; }   // BOS, one token per decode
        }
        if (sync_after) llama_synchronize(c);            // ik: n_queued_tokens == 1 -> n_eval++
        if (reset_perf) llama_perf_context_reset(c);     // ik's llama_reset_timings: n_eval = 0
        if (lead_tokens) llama_memory_clear(llama_get_memory(c), true);
        bool ok = true;
        if (batch_prefix > 1) {
            std::vector<llama_token> head(A.begin(), A.begin() + batch_prefix);
            std::vector<llama_token> rest(A.begin() + batch_prefix, A.end());
            ok = decode_many(c, head) && step_decode(c, rest, RD_NONE);
        } else {
            ok = step_decode(c, A, RD_NONE);
        }
        if (!ok) { llama_free(c); return; }
        std::vector<float> L1 = snapshot(c);
        llama_free(c);
        double mx = 0.0;
        for (int i = 0; i < g_n_vocab; ++i) mx = std::max(mx, std::fabs((double) L1[i] - (double) L0[i]));
        std::vector<int> t1 = top5(L1);
        printf("%s\t%s\t%d\t%.6g\t", name, what, t1[0], mx);
        for (int i = 0; i < 5; ++i) printf("%s%.6f", i ? "," : "", L1[t1[i]]);
        printf("\n");
        fflush(stdout);
    };
    //                          what is flipped                       lead sync reset bpfx expl
    mech("warm0_baseline",     "nothing (== L0)",                        0, false, false, 0, false);
    mech("warm1_nosync",       "1 lone decode, NO sync",                 1, false, false, 0, false);
    mech("warm1_sync",         "1 lone decode + llama_synchronize",      1, true,  false, 0, false);
    mech("warm1_sync_reset",   "+ llama_perf_context_reset",             1, true,  true,  0, false);
    mech("prefix2_batch",      "first ubatch holds 2 tokens",            0, false, false, 2, false);
    mech("warm_explicit",      "llama_set_warmup(ctx, true) [control]",  0, false, false, 0, true);

    fflush(stdout);
    init.reset();              // owns the model and its own context; free before the backend
    llama_backend_free();
    return 0;
}
