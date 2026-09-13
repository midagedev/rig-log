#!/usr/bin/env python3
"""Teach ik_llama.cpp's DSV4 DFlash draft path the two V4.1 rules the body already has.

1. hparams: a DSV4 draft without output_hc_base.weight is a V4.1 draft (dflash_dsv41).
2. loader: the three output_hc_* tensors are optional for a V4.1 draft.
3. graph: no per-head q rms_norm after the up projection; hyper-connection mixes lag by one
   sublayer; the output collapse uses the last FFN's mix instead of the learned head.
Exact-string replacements; every anchor must be found exactly once.
"""
import sys

ROOT = "/home/user/ik_llama.cpp/src/"


def patch(path, pairs):
    s = open(ROOT + path).read()
    for old, new in pairs:
        n = s.count(old)
        assert n == 1, (path, n, old[:60])
        s = s.replace(old, new)
    open(ROOT + path, "w").write(s)
    print("patched", path, len(pairs))


patch("llama-hparams.h", [
    ("    bool     dflash_dsv4 = false;\n",
     "    bool     dflash_dsv4 = false;\n"
     "    bool     dflash_dsv41 = false;  // DSV4 draft with V4.1 rules: lagged hyper-connections, no output head\n"),
    ("        if (this->dflash_dsv4   != other.dflash_dsv4)   return true;\n",
     "        if (this->dflash_dsv4   != other.dflash_dsv4)   return true;\n"
     "        if (this->dflash_dsv41  != other.dflash_dsv41)  return true;\n"),
])

patch("llama-hparams.cpp", [
    ("""                    hparams.dflash_dsv4 = hparams.dsv4_hc_mult > 0;
                    if (!hparams.dflash_dsv4) {
                        throw std::runtime_error("dflash: hyper_connection.count is required for the official DSV4 schema");
                    }
""",
     """                    hparams.dflash_dsv4 = hparams.dsv4_hc_mult > 0;
                    if (!hparams.dflash_dsv4) {
                        throw std::runtime_error("dflash: hyper_connection.count is required for the official DSV4 schema");
                    }
                    // A V4.1 draft has no learned output head: its hyper-connection mixes lag by one
                    // sublayer and the last FFN's mix does the output collapse, exactly as in the
                    // V4.1 body. The absence of output_hc_base.weight is the signature.
                    hparams.dflash_dsv41 = ml.get_tensor_meta("output_hc_base.weight") == nullptr;
                    LLAMA_LOG_INFO("%s: DSV4 draft flavor = %s\\n", __func__,
                            hparams.dflash_dsv41 ? "V4.1 (lagged hyper-connections, no output head)" : "V4");
"""),
])

patch("llama-load-tensors.cpp", [
    ("""    model.hc_head_base = create_tensor(ctx_output, tn(LLM_TENSOR_HC_HEAD_BASE, "weight"), {(int64_t) hparams.dsv4_hc_mult}, 0);
    model.hc_head_fn = create_tensor(ctx_output, tn(LLM_TENSOR_HC_HEAD_FN, "weight"),
            {(int64_t) n_embd * hparams.dsv4_hc_mult, (int64_t) hparams.dsv4_hc_mult}, 0);
    model.hc_head_scale = create_tensor(ctx_output, tn(LLM_TENSOR_HC_HEAD_SCALE, "weight"), {1}, 0);
    model.dspark_markov_w1""",
     """    // V4.1 drafts carry no output hyper-connection head (the last FFN's mix collapses the copies)
    const int hc_head_flags = hparams.dflash_dsv41 ? llama_model_loader::TENSOR_NOT_REQUIRED : 0;
    model.hc_head_base = create_tensor(ctx_output, tn(LLM_TENSOR_HC_HEAD_BASE, "weight"), {(int64_t) hparams.dsv4_hc_mult}, hc_head_flags);
    model.hc_head_fn = create_tensor(ctx_output, tn(LLM_TENSOR_HC_HEAD_FN, "weight"),
            {(int64_t) n_embd * hparams.dsv4_hc_mult, (int64_t) hparams.dsv4_hc_mult}, hc_head_flags);
    model.hc_head_scale = create_tensor(ctx_output, tn(LLM_TENSOR_HC_HEAD_SCALE, "weight"), {1}, hc_head_flags);
    model.dspark_markov_w1"""),
])

patch("graphs/build_deepseek4.cpp", [
    # 3a. the assert
    ("""    GGML_ASSERT(model.dflash_hidden_norm != nullptr);
    GGML_ASSERT(model.hc_head_fn != nullptr && model.hc_head_base != nullptr && model.hc_head_scale != nullptr);

    ggml_cgraph * gf = ggml_new_graph_custom(ctx0, model.max_nodes((int) std::max<int64_t>(n_tokens, ctx_len)) + 48 * n_layer, false);
""",
     """    GGML_ASSERT(model.dflash_hidden_norm != nullptr);
    // V4.1 draft: no learned output head, hyper-connection mixes lag by one sublayer (see the body graph)
    const bool hc_lag = hparams.dflash_dsv41;
    GGML_ASSERT(hc_lag || (model.hc_head_fn != nullptr && model.hc_head_base != nullptr && model.hc_head_scale != nullptr));

    ggml_cgraph * gf = ggml_new_graph_custom(ctx0, model.max_nodes((int) std::max<int64_t>(n_tokens, ctx_len)) + 48 * n_layer, false);
"""),
    # 3b. no per-head q norm for V4.1
    ("""        q = ggml_reshape_2d(ctx0, q, n_embd_head, n_head * n_tokens);
        q = ggml_rms_norm(ctx0, q, hparams.f_norm_rms_eps);
        q = ggml_reshape_3d(ctx0, q, n_embd_head, n_head, n_tokens);
        q = ggml_rope_ext_inplace(ctx0, q, inp_pos, nullptr, n_embd_head_rope, rope_type, 0,
                freq_base, 1.0f, 0.0f, 1.0f, 0.0f, 0.0f);
        q->op_params[15] = 1;
        cb(q, "dsv4_dflash_q", il);
""",
     """        if (!hc_lag) {
            // V4 normalizes each head again after the up projection; V4.1 normalizes only the low-rank part
            q = ggml_reshape_2d(ctx0, q, n_embd_head, n_head * n_tokens);
            q = ggml_rms_norm(ctx0, q, hparams.f_norm_rms_eps);
        }
        q = ggml_reshape_3d(ctx0, q, n_embd_head, n_head, n_tokens);
        q = ggml_rope_ext_inplace(ctx0, q, inp_pos, nullptr, n_embd_head_rope, rope_type, 0,
                freq_base, 1.0f, 0.0f, 1.0f, 0.0f, 0.0f);
        q->op_params[15] = 1;
        cb(q, "dsv4_dflash_q", il);
"""),
    # 3c. the layer loop with the lag carry
    ("""    ggml_tensor * inp_pos = build_inp_pos();
    for (int il = 0; il < n_layer; ++il) {
        const auto & layer = model.layers[il];
        ggml_tensor * residual = inpL;
        ggml_tensor * post = nullptr;
        ggml_tensor * comb = nullptr;
        ggml_tensor * cur = build_hc_pre(ctx0, *this, hparams, n_embd, hparams.f_norm_rms_eps, inpL,
                layer.hc_attn_fn, layer.hc_attn_scale, layer.hc_attn_base, &post, &comb, cb, il);
        cur = llm_build_norm(ctx0, cur, hparams, layer.attn_norm, nullptr, LLM_NORM_RMS, cb, il);
        cur = build_attention(il, cur, inp_pos);
        inpL = build_mhc_post(cur, post, residual, comb, n_embd, hparams.dsv4_hc_mult, true);

        residual = inpL;
        cur = build_hc_pre(ctx0, *this, hparams, n_embd, hparams.f_norm_rms_eps, inpL,
                layer.hc_ffn_fn, layer.hc_ffn_scale, layer.hc_ffn_base, &post, &comb, cb, il);
""",
     """    ggml_tensor * inp_pos = build_inp_pos();
    ggml_tensor * hc_pre_mix = nullptr;
    if (hc_lag) {
        // layer 0 collapses with a one-hot that selects the first copy, as in the body
        hc_pre_mix = ggml_concat(ctx0,
                ggml_fill(ctx0, ggml_new_tensor_2d(ctx0, GGML_TYPE_F32, 1, n_tokens), 1.0f),
                ggml_fill(ctx0, ggml_new_tensor_2d(ctx0, GGML_TYPE_F32, hparams.dsv4_hc_mult - 1, n_tokens), 0.0f), 0);
        cb(hc_pre_mix, "dsv4_dflash_hc_pre_init", -1);
    }
    for (int il = 0; il < n_layer; ++il) {
        const auto & layer = model.layers[il];
        ggml_tensor * residual = inpL;
        ggml_tensor * post = nullptr;
        ggml_tensor * comb = nullptr;
        ggml_tensor * hc_attn_pre = nullptr;
        ggml_tensor * cur = build_hc_pre(ctx0, *this, hparams, n_embd, hparams.f_norm_rms_eps, inpL,
                layer.hc_attn_fn, layer.hc_attn_scale, layer.hc_attn_base, &post, &comb, cb, il,
                hc_pre_mix, hc_lag ? &hc_attn_pre : nullptr);
        cur = llm_build_norm(ctx0, cur, hparams, layer.attn_norm, nullptr, LLM_NORM_RMS, cb, il);
        cur = build_attention(il, cur, inp_pos);
        inpL = build_mhc_post(cur, post, residual, comb, n_embd, hparams.dsv4_hc_mult, true);

        residual = inpL;
        cur = build_hc_pre(ctx0, *this, hparams, n_embd, hparams.f_norm_rms_eps, inpL,
                layer.hc_ffn_fn, layer.hc_ffn_scale, layer.hc_ffn_base, &post, &comb, cb, il,
                hc_attn_pre, hc_lag ? &hc_pre_mix : nullptr);
"""),
    # 3d. the output collapse
    ("""    ggml_tensor * out = build_hc_head(ctx0, *this, hparams, n_embd, hparams.f_norm_rms_eps,
            inpL, model.hc_head_fn, model.hc_head_scale, model.hc_head_base);
    out = llm_build_norm(ctx0, out, hparams, model.output_norm, nullptr, LLM_NORM_RMS, cb, -1);
    out = build_output(lctx, ctx0, out, model.output, nullptr, cb);
    if (lctx.dflash.dspark) {
""",
     """    ggml_tensor * out = nullptr;
    if (hc_lag) {
        // the last FFN's mix is the one nothing consumed; it does what V4's learned head does
        out = build_mhc_weighted_sum(inpL, hc_pre_mix, n_embd, hparams.dsv4_hc_mult);
        cb(out, "dsv4_dflash_hc_out", -1);
    } else {
        out = build_hc_head(ctx0, *this, hparams, n_embd, hparams.f_norm_rms_eps,
                inpL, model.hc_head_fn, model.hc_head_scale, model.hc_head_base);
    }
    out = llm_build_norm(ctx0, out, hparams, model.output_norm, nullptr, LLM_NORM_RMS, cb, -1);
    out = build_output(lctx, ctx0, out, model.output, nullptr, cb);
    if (lctx.dflash.dspark) {
"""),
])
print("OK")
