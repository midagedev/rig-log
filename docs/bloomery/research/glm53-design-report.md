# GLM-5.3 full (`glm-dsa`, 753B) 설계 보고서

bloomery 이슈 #60. 2026-10-22에 읽기 전용 설계 라운드 두 개(A: 구조 비교·재사용 표·다운로드, B: 티어 계획·오라클·라운드 사다리, 둘 다 Opus 5.5, AI 에이전트)가 썼고 리드가 합쳤다. 박스 실행 없이 헤더 range 읽기와 엔진 planner의 Mac 하네스로 닫았다. 스크래치 경로(바이트 표 TSV, 하네스)는 그 세션에만 있다.

## GLM-5.3 (`glm-dsa`, 753B) 설계 A부: 1·2·3절과 바이트 표

라운드 glm53d-A는 읽기 전용으로 진행했고, 모델은 Opus 5.5입니다. 트리는 `main` 8d74220bb입니다. 레포 파일 편집, git 조작, ssh와 box 사용은 모두 0건입니다. 헤더는 range 요청(206 응답만)으로 31개 shard에서 66 MB를 읽었고 텐서 바이트는 받지 않았습니다.

**산출물** (스크래치 경로 `/private/tmp/claude-501/-Users-hckim-repo-bloomery/eb5ee462-15fe-4069-9c51-0b1f37bdc193/scratchpad/glm53d/`)
- `/private/tmp/claude-501/-Users-hckim-repo-bloomery/eb5ee462-15fe-4069-9c51-0b1f37bdc193/scratchpad/glm53d/glm53-UD-Q2_K_XL-bytes.tsv`: 텐서별 바이트 표. 1,809행이며 열은 shard, name, layer, layer_kind, class, type, dims, bytes, offset입니다.
- `/private/tmp/claude-501/-Users-hckim-repo-bloomery/eb5ee462-15fe-4069-9c51-0b1f37bdc193/scratchpad/glm53d/glm53-UD-Q2_K_XL-layers.tsv`: 층별 요약. top 1행과 층 0–78입니다.
- 원시 비교 표: `/private/tmp/claude-501/-Users-hckim-repo-bloomery/eb5ee462-15fe-4069-9c51-0b1f37bdc193/scratchpad/glm53d/UD-IQ2_M.tsv`, `/private/tmp/claude-501/-Users-hckim-repo-bloomery/eb5ee462-15fe-4069-9c51-0b1f37bdc193/scratchpad/glm53d/UD-Q3_K_XL.tsv`, `/private/tmp/claude-501/-Users-hckim-repo-bloomery/eb5ee462-15fe-4069-9c51-0b1f37bdc193/scratchpad/glm53d/UD-IQ4_XS.tsv`.
- 리더 스크립트 `/private/tmp/claude-501/-Users-hckim-repo-bloomery/eb5ee462-15fe-4069-9c51-0b1f37bdc193/scratchpad/glm53d/hdr.py`. `tools/bloomery/hf.py`의 `Hub.range`와 `read_header`를 그대로 씁니다.
- 첫 shard 메타 `/private/tmp/claude-501/-Users-hckim-repo-bloomery/eb5ee462-15fe-4069-9c51-0b1f37bdc193/scratchpad/glm53d/UD-Q2_K_XL.meta.json`.
- 채팅 템플릿 두 벌: `/private/tmp/claude-501/-Users-hckim-repo-bloomery/eb5ee462-15fe-4069-9c51-0b1f37bdc193/scratchpad/glm53d/tmpl-glm53.jinja`, `/private/tmp/claude-501/-Users-hckim-repo-bloomery/eb5ee462-15fe-4069-9c51-0b1f37bdc193/scratchpad/glm53d/tmpl-flash.jinja`.
- 오라클 원문: `/private/tmp/claude-501/-Users-hckim-repo-bloomery/eb5ee462-15fe-4069-9c51-0b1f37bdc193/scratchpad/glm53d/glm-dsa.cpp`(mainline 7be2c65, 806줄), `/private/tmp/claude-501/-Users-hckim-repo-bloomery/eb5ee462-15fe-4069-9c51-0b1f37bdc193/scratchpad/glm53d/pr25980.diff`.

## 0. 분해와 자원 타임라인

- **분해.** 질문은 세 항으로 나뉩니다. (a) 아키텍처 사실(config 두 개, 헤더, llama.cpp와 ik 그래프), (b) 텐서별 바이트(헤더의 type과 dims), (c) 디스크(HF API 크기).
  - 세 항 모두 읽기로 닫힙니다. 그래서 box 실행은 0건이고 예측 카드도 필요 없습니다.
  - 파생 수는 KV 바이트/토큰, 활성 파라미터, 디코드 바이트/토큰, 다운로드 wall이며, 모두 `[derived]`로 표시했습니다.
- **타임라인 입력** (B가 그립니다).
  - 디코드 1토큰이 읽는 가중치는 21.52 GB이고, 이 중 routed가 7.33 GB입니다 [derived, §1].
  - routed가 전부 호스트 DRAM에서 나오면 호스트 항은 7.33 GB / 147.7 GB/s = 49.6 ms/토큰입니다 [derived, 147.7은 spec 값]. 카드 상주 비율만큼 줄어듭니다.
  - 카드 항과 비교해 어느 쪽이 max인지, 그림자에 들어가는지는 B가 정합니다.

## 1. 아키텍처 차이: GLM-5.3 vs V4.1 vs GLM-5.3-Flash

**출처**
- 두 config를 받아 확인했습니다.
  - https://huggingface.co/zai-org/GLM-5.3/raw/main/config.json → `"model_type": "glm_moe_dsa"`
  - …/GLM-5.3-Flash/raw/main/config.json → `"hc_mult": 4`
- PR 25980 제목: "model: add NextN/MTP speculative decoding support for GLM_DSA (GLM-5.2)". 2026-07-29에 머지됐고 커밋은 7be2c65입니다.
  - 이 PR은 MTP 그래프를 추가한 것입니다. trunk와 DSA는 그보다 앞서 들어와 있었습니다.
  - 오라클로는 머지 시점의 `src/models/glm-dsa.cpp` 전체를 읽었습니다.
- exllamav3 `exllamav3/architecture/glm_moe_dsa.py`(b00082a8)를 받아 확인했습니다. 14행: "Interleaved (GPT-J) rope pairing in both the main attention and the indexer, plain rope".
- mistral.rs는 읽지 않았습니다. Mac에 트리가 없습니다.

| 항목 | GLM-5.3 (`glm-dsa`) | V4.1 | GLM-5.3-Flash | 우리 코드 현재 |
|---|---|---|---|---|
| arch 문자열 | 헤더 `glm-dsa`(ik `llama-arch.cpp:88`), HF `glm_moe_dsa` | `deepseek41` | `glm5next`/`glm5-next` | registry에 행이 없습니다. `arch::spec`이 `UnknownArchitecture`로 거부합니다(`crates/model/src/arch/mod.rs:46-55`) |
| 층 | trunk 78 + NextN 1(`block_count 79`) | — | 45 + NextN 1 | 공통 `nextn_layers`(`arch/mod.rs:664-`)가 `blk.78.nextn.eh_proj`로 past_trunk 1을 읽습니다 |
| hidden / vocab | 6144 / 154,880 | — | 4096 / 154,880 | — |
| mixer | 78층 모두 MLA+DSA. KDA와 HC 없음 | K=V latent 512, window ⧺ 압축 행, head별 sink(`gpu-deepseek41/src/attn.rs:1-3,70`) | KDA 34 + rope 없는 MLA 11 | rope가 있는 MLA는 V2-Lite 카드 체인만 돕니다(`flash.rs:152-156` 576폭, `deepseek2/dispatch.rs:284,342,473`) |
| MLA 크기 | q_lora 2048, kv_lora 512, nope 192 + rope 64, v 256, head 64. 헤더 기준 K 576, V 512, `*_mla` 256, kv head 1 | K=V head_dim, `o_groups`(`deepseek41/hparams.rs:99`) | q_lora 1536, nope 256, rope 0 | absorb는 `enqueue_q8_0_gemv_heads`(K=cols·32, `gpu/src/model/kernels.rs:350-351`)라 192도 받습니다. scale은 1/√256입니다(YaRN 키 없음, `glm-dsa.cpp:231`) |
| RoPE | NORM(interleaved), base 8e6, 64차원. ik `llama.cpp:9780-9785`, exl3:14 | head 꼬리 `rope_dims`(`hparams.rs:103`) | MLA는 rope 0 | `rope_table` NORM(`gpu/src/rope_table.rs:7`) |
| 선택기 | 토큰별 lightning indexer: q=`attn_q_b`·qr(2048→32×128, Q8_0), k=LayerNorm(w,b)(`attn_k`·x)(6144→128). head 128 중 **앞 64**에 rope(`glm-dsa.cpp:272-280`, ik `build_deepseek2.cpp:397-404`, exl3:86-88). q와 k에 Hadamard(`:326`). w=`proj`·x(F32 6144→32)×1/√4096. score=Σ relu(q·k)·w, top min(n_kv, 2048)(`:395`) | 압축 행 위의 indexer. head **뒤** n_dims에 rope, Hadamard, radix top-k(`indexer.rs:1-30`). key는 압축 latent 512→128의 RMS(`index_key.rs:1-12,21`) | k-pool: LN key에 gate, 4개 묶음(`gpu/src/latent.rs:1-15`), `kpool_score`/`qsa_topk_high`(`mla.rs:20-22`) | top-k(`ds41_indexer_topk`)는 그대로 씁니다. score의 rope 위치, key의 norm(LN vs RMS), key의 원천(토큰 vs 압축)이 다릅니다 |
| 선택기 층 패턴 | full 21(0,1,2,6,…,74) + shared 57. shared 층은 직전 full의 top-k를 재사용합니다(`glm-dsa.cpp:246`). **파일에 키가 없습니다.** ik 규칙 `(il<=1)\|\|(il%4==2)`(`llama-hparams.cpp:2293`)가 mainline 기본 배열(`glm-dsa.cpp:6-26`) 및 HF `indexer_types`와 같은지 확인했습니다 | 압축 층마다 | MLA 11층 모두 full | 없음 |
| 선택기 LN eps | 파일에 키가 없습니다. ik는 RMS eps 1e-5를 그대로 씁니다(`llama-hparams.cpp:2040-2047`). 같은 주석에 HF는 1e-6이라고 적혀 있습니다 | RMS | Flash 헤더에 `layer_norm_epsilon`이 있습니다 | 리더가 기본값을 `Read.defaults`(`arch/mod.rs:59-62`)에 이름을 붙여 남겨야 합니다 |
| dense FFN | 층 0–2, ff 12288(Q5_K/Q6_K) | — | 층 0–2, 12288 | Q5_K/Q6_K/F32 dense site(`placement/src/kernels.rs:477-483`) |
| routed | 256×2048, top 8, 층 3–77과 NextN 78 | top 6 of 384(`router.rs:1-3`) | 288×2048, top 8 | 공통 card leg가 IQ2_XS/IQ3_XXS/IQ4_XS를 돕니다(`kernels.rs:321-330,369-383`, `gpu/src/card_leg.rs:1-3`). 호스트 qdot은 Q2_K/IQ2_XS/IQ3_XXS/IQ4_XS(`qdot/src/lib.rs:2-4`) |
| shared expert | 1×2048 | 읽지 않음 | 1×2048 | gpu-deepseek41의 shared expert(`gpu-glm5next/src/lib.rs:5-7`) |
| router | sigmoid, noaux 편향 `exp_probs_b`, 그룹 1, norm, ×2.5, gate_inp F32(헤더 `expert_gating_func 2`) | √softplus, ×1.5 | sigmoid 288/8, ×2.5 | (256, 8) 인스턴스가 이미 있습니다. 다만 이름이 `mimo2`입니다(`router.rs:809-829`). 폭은 런타임 k입니다(`route_body.rs:583`) |
| residual | plain(`ffn_inp = cur + inpSA`) | hyper-connection(`hparams.rs:61`) | HC 4 stream | plain 바디는 mimo2와 solar2이고 둘 다 `TierShell` 위에 있습니다(`host/shell.rs:1-6`) |
| NextN | blk.78은 전체 블록(MLA, routed 256, shared)에 eh_proj(12288→6144 Q8_0)와 enorm/hnorm/shared_head_norm이 붙은 형태입니다. embed와 head는 공유합니다. 두 엔진 모두 MTP를 **dense MLA로, 인덱서 없이** 돌립니다(`pr25980.diff:92`, ik `build_deepseek2.cpp:338-339`) | DSpark draft 파일 | latent MTP 층 1개 | 공통 `app::mtp::MtpDraft`(`app/src/mtp.rs:1-5`). 카드 NextN은 glm5next 전용입니다(`nextn.rs`) |
| 문맥 | 1,048,576 | — | 1,048,576 | glm5next는 16,384를 넘으면 거부합니다(`place.rs:406`) |
| tokenizer | gpt2 BPE, pre `glm4`. tokens/merges/token_type이 Flash와 같습니다(sha 일치, 다른 위치 0개). pad만 154821(Flash 154820) | 읽지 않음 | 동일 | `pretok.rs:371` `glm4`. 이미 붙어 있습니다 |
| chat | `[gMASK]<sop>`, `<think>`, `<tool_call>{name}<arg_key>…`가 Flash와 같습니다. 차이: 미디어 매크로가 없고 미디어 항목은 안내 문구로 바뀌며 이때 `\| replace`를 씁니다. `_args is mapping` 가드가 있고 trim 몇 곳이 다릅니다 | — | 미디어 매크로 있음 | `GlmXml`(`models/src/lib.rs:742`)과 `chat_of`(`arch/mod.rs:743-761`)로 붙습니다. 단 우리 Jinja에 `replace` 필터가 없습니다(`crates/jinja/src/lib.rs:2453`). 그래서 미디어 항목이 있는 요청만 이름 붙은 오류로 실패하고, 텍스트 요청은 렌더링됩니다 |

**UD-Q2_K_XL 층별 요약** (MB/층, 헤더의 type×dims에서 읽음. norm 0.06 MB/층은 합계에만 넣었습니다)

| 층 | 개수 | attn | indexer | dense | router | shared | routed | 합 |
|---|---|---|---|---|---|---|---|---|
| top: embd Q5_K 654.21, head Q4_K 535.27 | – | | | | | | | 1,189.50 |
| 0–2(dense, full) | 3 | 132.87 | 10.54 | 165.74 | – | – | – | 309.20 |
| 3–77 일반(gate/up IQ2_XS, down IQ3_XXS) | 71 | 132.87 | 10.54 | – | 6.29 | 27.62 | 3,095.40 | 3,272.77 |
| 8(Q6_K q_a/out, IQ3_XXS/IQ4_XS) | 1 | 147.91 | 10.54 | – | 6.29 | 34.01 | 4,177.53 | 4,376.33 |
| 75–77(down IQ4_XS) | 3 | 132.87 | 10.54 | – | 6.29 | 27.62 | 3,573.55 | 3,750.92 |
| 78 NextN(Q2_K/Q3_K, glue 80.29) | 1 | 132.87 | 10.54 | – | 6.29 | 27.62 | 3,498.05 | 3,755.72 |

**합계** (텐서 바이트 253,868,860,416)
- trunk routed 234.67 GB, trunk 비routed 14.25 GB, NextN 3.76 GB, top 1.19 GB이고 넷의 합이 위 총계와 맞습니다.
- expert 하나는 12,091,392 B입니다(gate 3,637,248 + up 3,637,248 + down 4,816,896) [derived: dims×type].

**파생 수**
- 파라미터: 전체 753.86B, trunk 743.91B, NextN 9.95B, 토큰당 활성 40.83B(token_embd 제외)입니다 [derived: dims]. mainline도 이 크기를 `LLM_TYPE_744B_A40B`로 부릅니다(`glm-dsa.cpp:77`). 평균 2.69 bit/weight입니다 [derived].
- KV는 f16 기준 96,384 B/토큰입니다 [derived].
  - 구성: 78×576×2 + 21×128×2(full 층만 index key를 둡니다. ik `llama.cpp:1458`) + NextN 576×2.
  - 32k 문맥이면 3.16 GB, 128k면 12.63 GB입니다.
- 디코드 바이트/토큰은 22.12 GB입니다 [derived]: 비routed 14.25 + head 0.54 + routed의 8/256인 7.33.
  - shared 57층의 indexer 가중치 0.60 GB는 파일에 있지만 아무 step도 읽지 않습니다. 그래서 실제로는 21.52 GB이고, 이 0.60 GB는 plan에서 `Unused`로 둡니다.
- 다른 양자(routed / 비routed, GB): IQ2_M 219.37 / 14.25, Q3_K_XL 317.57 / 18.70, IQ4_XS 339.91 / 18.70.

## 2. 재사용과 신규: 공통 소유자 표 (new-model.md:191-225 형식)

| 개념 | 공통 소유자 | GLM-5.3 | 모델 코드를 강제하는 사실 |
|---|---|---|---|
| 리더 | `registry.rs` ROWS, 공통 리더 `positive`/`optional_usize`/`per_layer_count`/`nextn_layers`/`chat_of`/`n_vocab`(`arch/mod.rs:255,264,352,664,743,789`) | **붙음.** 새 모듈 `arch/glm_dsa/`(hparams, names, roles, spec, place)와 registry 1행. 모듈명은 `gemma_embedding` 선례를 따릅니다 | `glm-dsa.*` 키. 선택기 패턴과 LN eps가 파일에 없어서 기본값을 `defaults`에 남깁니다 |
| DSA 선택기 | `ds41_indexer_score`/`_topk`(`gpu-deepseek41/src/indexer.rs:1-30`), radix `qsa` | top-k는 **이미 붙음.** score는 rope가 head 앞에 오는 **새 인스턴스**로 만들고 V4.1 entry는 건드리지 않습니다. key append는 **새 entry**로, LN 계약(`latent.rs:30-36`)과 rope·Hadamard(`index_key.rs`)를 조합합니다 | rope 앞 64, LN, 토큰별 key. shared 57층은 런치 0 |
| attention | `mma_segment_walk`(`gpu/src/flash.rs:373-414`). 576 확장(`flash_latent_mma`)과 512 확장(ds41)이 이미 있습니다 | 키 2,048개 이하는 `flash_latent_mma`와 `flash_merge`가 **그대로** 돕니다. ik도 이 구간에서는 dense입니다(`build_deepseek2.cpp:341-343`). 2,048 초과는 **새 entry 1개**: 같은 walk에 576폭, index-list 키 원천(`flash.rs:390-395`에 이 형태가 이름으로 적혀 있습니다) | K=[rope 64 \| latent 512], V=latent 512로 K≠V. head 64는 16씩 4그룹(`flash.rs:124-126`) |
| KV append, absorb | `enqueue_kv_norm_rope_append`(`gpu/src/fused.rs:675-690`, m=1), `enqueue_q8_0_gemv_heads` | **이미 붙음.** 프롬프트는 비융합 경로(같은 doc) | — |
| router | `sigmoid_router_instance`(`route_body.rs:353`), (256,8) 인스턴스(`router.rs:809-829`) | **이미 붙음** | — |
| card expert leg | `CardLeg`(`card_leg.rs:440`), 규칙 `common_leg_card`(`placement/src/accepts.rs:288-291`) | **붙음.** 같은 arm에 새 Program을 추가합니다 | — |
| tier leg, shell | `StepLeg`/`BatchLeg`(`host/leg.rs:1-6`), `LegTier`(`leg_tier.rs:60`), `TierShell`, `TierBody`(`served.rs:43`) | **붙음.** glue는 node family와 open뿐입니다(`gpu-glm5next/src/tier.rs:15-16` 형태) | — |
| 적응형 residency | `SwapMachine`(`host/swap.rs:1-3`), `FileSwap`, `shell.residency_parts`(mimo2 `body.rs:1233-1235`) | **붙음.** stack 표 약 50줄(`gpu-glm5next/src/swap.rs:1-5` 형태) | NextN의 routed Q2_K gate/up과 Q3_K down에는 카드 행이 없어서 호스트에 둡니다 |
| NVMe 페이징 | `host/nvtier.rs:1-14`, `placement::expert_nvme_tier` | **붙음**(필요할 때만) | — |
| 배치 계산 | `plan_in_pool`, `nodes::loaded_routed`, `plan_routed(_reserving)`(`placement/src/placement.rs:2424,2452`) | **붙음.** 다만 같은 조합이 이미 두 벌 복사돼 있습니다(`deepseek41/place.rs:216-229`, `glm5next/place.rs:615-633`). 세 번째 복사 전에 lift합니다 | `KvLayout`은 모델 몫 |
| KV 크기 | `SeqTerms`/`Stores`/`SlotsOf`(`placement/src/slots.rs:125`) | **붙음** | 576폭 f16 79행/토큰, index key 128폭 f16 21행/토큰 |
| 프롬프트 walk | `runtime/src/prompt.rs:1-7` | **붙음** | — |
| 상주 슬롯 | `Slots`(`gpu/src/model/slots.rs:53`) | **붙음**(impl만) | — |
| MTP draft | `app::mtp` `MtpDraft`/`MtpBody`(`app/src/mtp.rs:192,395`), seat의 `drafted.rs`/`served.rs`, `arch/draft.rs:1-7`, 입력 pack `gpu/src/mtp.rs:7-17`(streams=1) | **붙음.** 카드 NextN 배관(`gpu-glm5next/src/nextn.rs`, 1,514줄, 행 규칙 `:7-12`)은 지금 glm5next 전용입니다. 복사하지 말고 store/full walk 골격을 먼저 lift합니다 | NextN 블록은 trunk 블록에 dense MLA를 쓰고, h=output_norm(trunk), stream 1개입니다 |
| serve seat | `serve_seats/tiered.rs:1-8`(mimo2, solar2) | **붙음.** 그런데 tiered.rs에는 NVMe와 MTP가 없습니다(grep 0/0). glm.rs(1,811줄)에는 둘 다 있습니다. glm.rs를 복사하지 말고 그 부분을 tiered.rs로 lift합니다 | — |
| tokenizer, chat | `pretok.rs:371`, `GlmXml` | **이미 붙음.** `replace` 필터만 없음 | — |
| 커널 표 | `kernels.rs` | Q2_K_XL의 카드 type 행이 모두 있습니다. 예외는 IQ2_XS의 프롬프트 GEMM 행(`kernels.rs:430-442`)과 NextN의 Q2_K/Q3_K입니다 | — |
| refset | family 표, `refset/src/arch/glm5next/mod.rs:1-8` 형태 | **새 family 행.** Flash의 DSA set은 다른 파일의 set이라 재사용할 수 없습니다. 첫 shard 경로가 identity입니다(`:15-20`). 이슈 #60의 "reuses DSA sets"는 틀렸습니다 | — |

**바디 형태**
- `gpu-mimo2`처럼 새 카드 crate를 공통 kernel의 조합으로 만들고, 자체 device 코드는 두지 않습니다(new-model.md:20-21).
- glm5next의 variant로 만들지 않습니다. KDA, HC, kpool이 없으니 variant로 만들면 모델별 분기만 늘어납니다.
- V2-Lite 바디 위에도 만들지 않습니다. 그 `crate::hybrid`는 expert `[0,n_l)`을 id로 고정 배치합니다(`gpu/src/arch/deepseek2/mod.rs:18-20`). 이는 이전 설계에서 놓쳤던 "정적 모델별 expert plan" 문제 그대로입니다. 이 설계는 공통 residency(`SwapMachine`, `TierShell`)를 씁니다.
- 새 device entry는 셋뿐이고 각각 add class입니다(`just ptx-compare`로 증명).
  - N1: 576폭 gather attention.
  - N2: LN, rope(앞), Hadamard를 거치는 index-key append.
  - N3: rope를 앞에 두는 score 인스턴스.

**설계 비교**
- ik(오라클)는 `--dsa`를 주지 않으면 dense로 돕니다. 기본값이 off입니다(`common.cpp:1934,3098`, `build_deepseek2.cpp:802-803`). 또 시퀀스의 첫 토큰을 top-k에 항상 넣습니다(DSA_SINK, `:366,574-590`).
- mainline은 DSA가 늘 켜져 있고 sink를 넣지 않습니다.
- exl3는 선택기 패턴을 config에서 읽고 n_group=1을 assert합니다(exl3:44-79).
- 우리 수치는 ik에 `--dsa`를 켠 쪽을 따릅니다. 오라클은 B가 확정합니다.

## 3. 다운로드 계획

| set | API 바이트 | routed gate/up·down | 카드 leg | /models 잔여(376 GB 기준) |
|---|---|---|---|---|
| UD-IQ1_S / IQ1_M | 216,715,365,893 / 228,492,971,557 | 읽지 않음 | ? | 159 / 148 |
| UD-IQ2_M | 238,577,585,701 | IQ2_XXS(74)·IQ3_XXS | gate·up 행이 없어서 routed 전부 호스트 | 137 |
| **UD-Q2_K_XL** | **253,878,406,789** | IQ2_XS(74)·IQ3_XXS(71)/IQ4_XS | **둘 다 있음**, 호스트도 있음 | **122** [derived] |
| UD-IQ3_XXS | 281,688,436,357 | 읽지 않음 | ? | 94 |
| UD-Q3_K_XL | 342,965,977,029 | IQ3_XXS·IQ4_XS | 있음. 다만 routed 317.6 GB가 RAM 여유 261.5를 넘으므로 NVMe가 56 GB 이상 필요 [derived] | 33 |
| UD-IQ4_XS | 365,313,228,709 | IQ3_S·IQ4_XS | `kernels.rs:327` 있음 | 11. 다른 파일을 옮겨야 합니다 |
| UD-Q4_K_XL | 467,289,116,837 | — | — | 들어가지 않음 |

**선택: UD-Q2_K_XL** (기본값을 유지합니다)
1. /models에 122 GB가 남아서 아무것도 옮기지 않아도 됩니다.
2. routed type 전부에 카드 leg 행과 호스트 qdot이 있습니다.
3. routed 238.17 GB(trunk와 NextN 합)가 RAM 여유 약 261.5 GB 안에 23 GB 남기고 들어갑니다 [derived, 다른 호스트 항은 빼기 전]. 그래서 NVMe 페이징은 필수가 아닙니다.

**pin**: rev `346b3591c7f28d1a23716f97a065ecf12ec14771`(lastModified 2026-08-29), 디렉터리 `UD-Q2_K_XL/`.

| shard | 바이트 | sha256 (lfs oid) |
|---|---|---|
| 00001(메타만) | 9,428,677 | 4f902dd0ad1458056d156cbfe226d159ef9f68786bcdbfd4fe1d04dca76fca41 |
| 00002 | 49,172,427,136 | 979122459ed09d9d895b85e340ddc9c93a7e82f525e20bf5c03e36da19a41b04 |
| 00003 | 49,091,626,976 | f7c9df5efffa2c1eb9b35e061f24f4d8b4a7edbd141e97455673e3e093e803db |
| 00004 | 49,091,626,976 | 8892cc45af116660fb0d6d568814e49b2e6bf173b10d5107a6ab0495c851dbd0 |
| 00005 | 49,091,626,976 | 99fff6a71cd659807196e9b624aff72771e79a0cd153f04efd6f8344c82ca489 |
| 00006 | 49,994,703,552 | 2e7c0cefe90a2cf54e7831331febd9c8c10beb1fa00437297f153f220aa258d3 |
| 00007 | 7,426,966,496 | 1c17315acbe0cd8e79faa81426412da58da960f85e5db3246e038a058f62339b |
| 합 | 253,878,406,789 (236.44 GiB) | |

**디스크**
- stage에서의 peak는 받아 둔 shard + 진행 중인 shard의 chunk + 그 `.assembled`입니다. 253.88 + 49.99 = 303.87 GB로, 여유 약 880 GB 안입니다 [derived: `fetch-gguf.sh:106-122`].
- /models는 253.88을 넣고 약 122 GB가 남습니다. 옮길 파일은 없습니다.

**절차** (lead가 실행합니다. 이 라운드에서는 실행하지 않았습니다)
1. `REV=346b3591… N=8 DEST=/home/user/stage/GLM-5.3-UD-Q2_K_XL tools/fetch-gguf.sh unsloth/GLM-5.3-GGUF UD-Q2_K_XL/GLM-5.3-UD-Q2_K_XL-0000{1..7}-of-00007.gguf`
   - DEST를 반드시 지정해야 합니다. 기본값이 /models라서입니다(`:34`).
2. shard마다 `sha256sum`을 돌려 위 표와 대조합니다. 도구는 크기만 확인합니다(`:118-121`).
3. `/models/GLM-5.3-UD-Q2_K_XL/`로 드라이브 간 복사를 하고 크기를 다시 확인합니다.
4. 우리 로더로 헤더를 읽는 것은 B의 R1입니다.

**Wall** [derived]
- 다운로드는 80 MB/s 기준 53분입니다. 80 MB/s는 `fetch-gguf.sh:23-24`에 2026-09-15 N=8로 측정해 적힌 값이고, 오늘의 링크 속도는 측정하지 않았습니다.
- 여기에 shard별 cat, 해시, 254 GB 복사가 더해집니다. 이 세 속도는 기록에 없습니다.
- fetch와 복사가 버퍼 I/O로 약 254 GB를 지나가므로 따뜻한 set(Flash 호스트 set 185.5 GB)을 밀어냅니다. timed sitting이나 warm sitting 중에는 하지 않습니다. O_DIRECT 복사(`dd iflag=direct oflag=direct`)는 제안만 하고 시험하지 않았습니다.

## 실행한 명령과 출력 (요지)

- `gh pr view 25980 --json title,state,mergedAt,mergeCommit`
  - 출력: `"title":"model: add NextN/MTP speculative decoding support for GLM_DSA (GLM-5.2)"`, MERGED 2026-07-29T06:02:31Z, 7be2c65dc9ad…
- `gh pr diff 25980 --name-only`
  - 출력: conversion/glm.py, src/llama-model.cpp, src/models/glm-dsa.cpp, src/models/models.h
- `python3 -I hdr.py <set> .`를 네 set에 대해 실행했습니다.
  - Q2_K_XL: `00001 size=9428677 tensors=0`, `00002 … tensors=389 slack=0`, …, `00007 … tensors=45 slack=0`, `requests=11 bytes=15720133`
  - 31개 shard 중 27개는 `slack=0`, 4개는 메타만 있는 첫 shard(`slack=-27`)입니다.
- `summ.py`: §1의 수가 이 출력입니다. 예: `trunk routed (3-77) 234671308800`, `routed bytes per layer distinct: {3095396352: 71, 4177526784: 1, 3573547008: 3}`
- `cmp_tok.py` 결과
  - `tokenizer.ggml.tokens … equal=True`, `merges … equal=True`, `token_type … equal=True`, `token positions differing 0`
  - `padding_token_id: glm53=154821 flash=154820`, `chat_template … equal=False len=10505/10648`
- indexer_types 확인: `len 78 equal_ik_rule True full_layers [0, 1, 2, 6, 10, …, 74]`
- ik
  - `git log -1` → `41b17995… 2026-09-25`(branch v41-dspark-pr). `git cat-file -t db517b69` → `fatal: Not a valid object name db517b69`
  - `-S LLM_ARCH_GLM_DSA` → `528cadb0 2026-02-15 GLM-5 support (#1268)`
  - DSA → `9da563d0 2026-07-02 … --dsa off by default (#2045)`
  - MTP → `6eff055a 2026-05-28`
  - 정리: Mac 트리와 box pin은 서로 다른 커밋이고, Mac 트리에는 db517b69가 없습니다.

## round B를 위해

1. 바이트 표는 위 두 TSV입니다. 첫 shard는 메타만 담고 있고, 블록이 shard 2–7에 걸쳐 있습니다.
2. `plan_routed`는 `crates/placement/src/placement.rs:2424`에 있습니다. spec이 적은 `crates/model/src/placement.rs:1771`에는 없습니다. `plan_host_routed`는 `:2477`입니다.
3. routed 238.17 GB와 RAM 여유 약 261.5 GB 비교에서는 NVMe가 선택 사항입니다. 카드 비routed는 14.25 + head 0.54 − shared indexer 0.60 GB이고, KV는 96,384 B/토큰입니다 [derived].
4. NextN의 routed(Q2_K/Q3_K)는 카드 행이 없어서 호스트에 둡니다. IQ2_XS에는 프롬프트 GEMM 행이 없습니다(`kernels.rs:430-442`). 카드에 상주하는 expert의 prefill 경로를 따로 정해야 합니다.
5. 오라클: ik에서는 `--dsa`가 필수입니다(기본 off). top_k가 n_kv 이상이면 ik는 indexer를 건너뜁니다(`build_deepseek2.cpp:392`). 그래서 2,048 이하의 set으로는 선택 동작을 시험할 수 없습니다.
6. ik와 mainline의 이름 붙은 차이는 sink anchor(DSA_SINK=1)입니다. LN eps는 ik 1e-5, HF 1e-6입니다.
7. box의 `/home/user/ik-idxkey`(db517b69)에 GLM_DSA와 DSA가 있는지 확인해야 합니다. Mac에서는 확인할 수 없습니다.
8. fixture를 자를 때 dense full 층(0–2), MoE shared 층(3), MoE full 층(6), NextN(78)을 포함해야 합니다. 6이 첫 MoE full 층입니다 [derived].
9. 선택기 패턴과 LN eps는 파일에 없으므로 리더가 기본값과 그 출처(ik의 해당 줄)를 `defaults`에 남깁니다.
10. seat: tiered.rs에 NVMe와 MTP를 lift하는 라운드가 먼저입니다. glm.rs, ds41.rs, qwen38.rs가 각자 들고 있습니다.
11. 카드 NextN의 lift 후보는 `gpu-glm5next/src/nextn.rs`이고, 배치 조합 lift 후보는 `deepseek41/place.rs:216-229`와 `glm5next/place.rs:615-633`입니다.
12. 이름 충돌: 문서가 Flash를 "GLM-5.3"이라고 부릅니다(`docs/models.md:48`, `tools/release/README.release.md:26`). seat와 모델 이름을 정해야 합니다.
13. 우선순위: plan-triage 15행에 "Fill existing model gaps before new models (… before #108/#60/#59/#61)"라고 적혀 있습니다.

## 범위 밖에서 개선할 수 있어 보인 곳 (보고만 함)

- `docs/contrib/new-model.md:51,150,215`: `placement.rs:1771/:1821`이 지금은 `:2424/:2477`입니다(XS).
- `docs/contrib/new-model.md:217`: card leg가 "family마다 각자"라고 적혀 있지만 지금은 공통 `crates/gpu/src/card_leg.rs`입니다(XS).
- `docs/contrib/new-model.md:210-211`: mimo2 residency가 "None을 반환한다"고 적혀 있지만 `crates/gpu-mimo2/src/body.rs:1233-1235`는 shell로 넘깁니다(XS).
- `docs/models.md:52-53`: "IQ3_S gate/up은 카드 kernel 없음"이라고 적혀 있지만 `kernels.rs:327,382`에 IQ3_S 행이 있습니다. 어느 쪽이 낡았는지 확인이 필요합니다(XS–S).
- `crates/gpu-deepseek41/src/router.rs:809-829`: (256,8) 인스턴스 이름이 `mimo2`입니다. 두 번째 사용자가 생기면 `sigmoid_320_8`(`:831-850`)처럼 형상 이름으로 바꾸는 게 맞습니다. rename class이고 canon-check로 증명합니다(S).
- `deepseek41/place.rs:216-229`와 `glm5next/place.rs:615-633`: 같은 plan 조합이 두 벌입니다. 공통 함수로 lift할 수 있습니다(S).
- `~/repo/rig-log/tools/fetch-gguf.sh:117-121`: lfs oid와 대조하는 sha256 검사가 없고, peak가 shard 크기의 2배입니다. 스트리밍 해시와 rename 기반 조립을 제안합니다(S, rig-log 쪽).
- `tools/type-census.py:14-17`: blk dims를 남기지 않아서 바이트 표를 만들려면 스크래치 스크립트가 필요합니다. `--dims` 옵션을 제안합니다(S).
- `tools/ref/gguf-ranges.py:150-158`: `value()`가 배열을 None으로 건너뜁니다. 그래서 짧은 배열 키(예: `indexer_types`)를 헤더 도구로 볼 수 없습니다(XS–S).
- `crates/jinja/src/lib.rs:2453`: `replace` 필터가 없습니다. GLM-5.3 템플릿의 미디어 분기가 이 필터를 씁니다(S).

**실행 모델**: Opus 5.5 (`claude-opus-5-5`). 설계 라운드라 lead가 opus를 지정했습니다.

---

## 설계 보고서 B (GLM-5.3 full, `glm-dsa`, 753B): §4 tier 계획, §5 oracle과 refset, §6 라운드 사다리

박스는 쓰지 않았습니다. 수치는 Mac에서 엔진 자신의 planner를 scratch 하네스로 돌려 얻었고, repo는 그대로입니다(아래 `git status` 출력 참고).

**파일 경로**
- 텐서별 바이트 표(A가 만든 것, 1,809행): `/private/tmp/claude-501/-Users-hckim-repo-bloomery/eb5ee462-15fe-4069-9c51-0b1f37bdc193/scratchpad/glm53d/glm53-UD-Q2_K_XL-bytes.tsv`
- 층별 바이트 표(A가 만든 것): `/private/tmp/claude-501/-Users-hckim-repo-bloomery/eb5ee462-15fe-4069-9c51-0b1f37bdc193/scratchpad/glm53d/glm53-UD-Q2_K_XL-layers.tsv`
- 하네스: `/private/tmp/claude-501/-Users-hckim-repo-bloomery/eb5ee462-15fe-4069-9c51-0b1f37bdc193/scratchpad/glm53d-b/harness/src/main.rs`. `bloomery-placement`와 `bloomery-gguf`를 path 의존으로 씁니다.
- 하네스 출력: `/private/tmp/claude-501/-Users-hckim-repo-bloomery/eb5ee462-15fe-4069-9c51-0b1f37bdc193/scratchpad/glm53d-b/plan.log`
- 초안 카드: `/private/tmp/claude-501/-Users-hckim-repo-bloomery/eb5ee462-15fe-4069-9c51-0b1f37bdc193/scratchpad/glm53d-b/glm53-slotrate.card`
- Flash 헤더 표(기준값 비교용): `/private/tmp/claude-501/-Users-hckim-repo-bloomery/eb5ee462-15fe-4069-9c51-0b1f37bdc193/scratchpad/glm53d-b/flash/UD-Q4_K_XL.tsv`

---

## 4. Tier 계획: A6000 48 GB + 3090 24 GB + 호스트 RAM + NVMe

### 4.0 분해: 항, 출처, 예측

| 항 | 출처 | 값 |
|---|---|---|
| 토큰당 routed 슬롯 | MoE 층 75개(3..77) × top-8 (A §1) | 600 [derived] |
| 슬롯 바이트 | 대표 층 3,095,396,352 B / 256 = 12.09 MB, 층 8은 16.32 MB, 층 75–77은 13.96 MB (layers.tsv) | 평균 12.22 MB [derived: 234.67 GB / 19,200] |
| 카드가 토큰마다 읽는 dense | 하네스 `dense 14.187` | 14.19 GB (A의 14.25 + 0.54 − 0.60과 같음) |
| 카드 KV | 576×2 B × 78층 + indexer key 128×2 B × full 21층 | 95,232 B/pos [derived]. NextN 1,152 B를 더하면 A의 96,384와 같음 |
| τ_slot (32스레드 호스트, 슬롯 하나) | 아래 4.4 | 0.088–0.105 ms, 중심 0.094 [derived] |
| F (호스트 쪽 고정비) | Flash 2.5–3.5 ms(`docs/cards/glmbp-ab.card`)를 42층에서 75층으로 비례 | 4.5–6.3 ms [derived] |
| C1 (카드 front) | 14.19 GB ÷ Flash 실효 575–700 GB/s + 층 수 지연. 실효 rate는 Flash 카드 dense 8,966,188,280 B(`tools/ref/models/glm5next.sh:54`)를 Flash 잔차 C1 12.8–15.6 ms로 나눈 값 | 21–27 ms [derived] |
| 카드 적중률 | 엔진 plan의 정적 f에 Flash residency 상승비 1.71을 곱함(`docs/cards/glmres-ab.card`: off 23.1 %, on 39.5 %) | 가정. 아래 4.3 |

### 4.1 층별 바이트 (layers.tsv에서 읽음, MB = 10^6 B)

| 층 종류 | 층 | attn(+indexer) | dense FFN | router + shexp | routed | 층 합계 |
|---|---|---|---|---|---|---|
| dense, full | 0–2 | 132.87 + 10.54 | 165.74 | 0 | 0 | 309.2 |
| MoE full (`il%4==2`) | 6, 10, …, 74 (18개) | 132.87 + 10.54 | 0 | 6.29 + 27.62 | 3,095.40 | 3,272.8 |
| MoE shared | 나머지 53개 | 132.87 + 10.54(읽지 않음) | 0 | 6.29 + 27.62 | 3,095.40 | 3,272.8 |
| MoE shared, 층 8 | 8 | 147.91 + 10.54 | 0 | 6.29 + 34.01 | 4,177.53 | 4,376.3 |
| MoE shared, down IQ4_XS | 75–77 | 132.87 + 10.54 | 0 | 6.29 + 27.62 | 3,573.55 | 3,750.9 |
| NextN | 78 | 132.87 + 10.54 | 0 | 6.29 + 27.62 | 3,498.05 (+ glue 80.29) | 3,755.7 |
| embed / head | — | — | — | — | — | 654.2 / 535.3 |

- **역할별 합계**(`plan.log:2`): attn 10.60 GB, 읽지 않는 shared indexer 0.60 GB, shexp 2.08 GB, router 0.47 GB, dense FFN 0.50 GB, head 0.535 GB, embed 0.654 GB, routed 234.67 GB, NextN 3.756 GB. 파일 전체는 253,868,860,416 B입니다.
- **full과 shared 구분.** full 층은 ik 규칙 `(il<=1)||(il%4==2)`으로 21개입니다(A §1). shared 층 57개는 직전 full 층의 top-k를 재사용하므로 indexer key cache가 없습니다. 그래서 KV에 128×2 B가 붙는 층은 21개뿐입니다.

### 4.2 엔진 planner 결과 (하네스, `plan.log`)

**planner 조합.** 하네스는 `glm5next/place.rs:615-633`과 같은 순서로 planner를 부릅니다.
1. `plan_in_pool` (`crates/placement/src/placement.rs:3782`)
2. `nodes::loaded_routed` (`placement/nodes.rs:46`). 규칙은 `routed_rule(Program::Glm5nextBody)`(`accepts.rs:278`), 즉 공통 leg인 `common_leg_card`(`accepts.rs:311`)입니다.
3. `plan_at` (`placement.rs:4023`)
4. `expert_nvme_tier` (`placement.rs:3576`)

**머신.** `plan_a`, `plan_bp`, `plan_gate`(`workstation.rs:289,470,630`)를 썼습니다. room은 `PLAN_ROOM` 263,376,371,712 B(`workstation.rs:129`)입니다.

**reserve.**
- prompt reserve는 glm5next 공식을 GLM-5.3 폭으로 계산했습니다. 합계 0.416 GB [derived].
- `tier_batch`(`glm5next/place.rs:126`)로 잡은 3090 reserve는 0.126 GB입니다.
- NextN은 `plan_host_routed`(`placement.rs:2477`)로 따로 계획하며 카드 0.275 GB, 호스트 3.498 GB입니다. glm5next의 NextN 계획 패턴(`place.rs:672-760`)을 따랐습니다.

| 경우 (ctx, mtp) | 카드에 두는 것 | 호스트 | f (카드 적중, 정적) | 위반 |
|---|---|---|---|---|
| a, 16k, mtp | A6000: dense 14.187, experts 32.132 GB(2,629개, 층마다 35..36), kv 1.560, 남는 공간 1.787 | experts 202.539, need 206.691, 남는 공간 56.685 | 0.1369 | 0 |
| bp, 16k, mtp | 위와 같음 + 3090 tier 22.561 GB(1,846개, 층마다 24..25), 남는 공간 1.785 | experts 179.978, need 184.332, 남는 공간 79.045 | 0.2331 | 0 |
| a / bp, 32k, mtp | experts 2,495개 / 4,339개, kv 3.121 | — | 0.130 / 0.226 | 0 |
| a / bp, 128k, mtp | experts 1,731개, kv 12.48 | — | 0.090 / 0.186 | 0 |
| gate (3090 단독), 16k | 3090: dense 14.187, experts 6.675 GB(546개) | need 228.651, 남는 공간 34.726 | 0.0284 | 0 |
| a, room 200 GB | 위 a와 같음 | nvme 13.913 GB 페이징, arena 0, churn pool 0개 | 0.1369 | 0 |
| a, room 160 GB | 위 a와 같음 | nvme 53.911 GB 페이징 | 0.1369 | 0 |

**호스트 전용 stack.**
- 공통 leg 규칙에서 trunk의 호스트 전용 routed stack은 0개입니다(`plan.log:4`). trunk 타입인 IQ2_XS, IQ3_XXS, IQ4_XS는 모두 카드 행이 있습니다.
- NextN의 q2_K/q3_K expert만 "no card expert kernel"로 호스트에 남습니다(`plan.log:5-7`).

**배치 결론.** 세 계층에 이렇게 나뉩니다.
- 카드: dense 전부, KV, 정적 expert 2,629개(+3090 1,846개)
- RAM: 나머지 expert 전부
- NVMe: 없음

**churn pool.** churn pool(`placement/churn.rs:22`, `ChurnPool::of` :39)은 카드 expert의 호스트 사본을 둡니다.
- a는 32.132 GB이고 남는 공간 56.685에 들어가므로, 남는 공간은 24.55 GB가 됩니다 [derived]. adaptive residency가 켜집니다.
- churn pool까지 두려면 room이 a에서 238.8 GB 이상, bp에서 263.6 GB 이상이어야 합니다 [derived: need + 카드 expert 사본].
- 따라서 **bp에서는 3090 쪽 churn pool이 room 263.4 안에 다 들어가지 않습니다.** 하네스는 card0과 card1의 pool을 각각 `host headroom 79.045`와 비교하므로 둘의 합 54.7 GB를 세지 않았습니다. R2 게이트가 둘의 합으로 판정해야 합니다.
- room 200 GB에서는 churn pool이 0개라서 residency가 꺼집니다.

**하네스 출력의 산술 오류.** 분할 경우의 headroom(−3.49)은 하네스가 `draft_host` 3.498을 두 번 뺀 값이라 실제로는 약 0입니다. 엔진이 아니라 하네스의 문제입니다.

### 4.3 디코드 예측과 자원 시간선 (토큰당, 깊이 ≤ 2048, A6000)

`S1 = C1 + F + h`(합)는 Flash에서 보정한 식입니다. Flash 값은 47.7 ms(20.95 tok/s) = C1 + F + h이고, h는 29.6–31.4 ms입니다(`docs/cards/glmbp-ab.card`). 층마다 카드 front → 호스트 experts → 카드 순서로 직렬 사슬이 이어지기 때문입니다.

**카드 적중 가정.** plan a의 정적 f는 0.137입니다(하네스). residency를 켜면 0.23–0.27로 봅니다 [가정: Flash residency 상승비 1.71(`docs/cards/glmres-ab.card`) × 0.137 = 0.234, 상한은 bp Flash stage 32.7 %에 비례].

| 배치 | 호스트 슬롯 | h (ms) | S1 (ms) | tok/s [derived] |
|---|---|---|---|---|
| a, residency on | 438–462(정적 516까지) | 38.5–54.2, 중심 43.4 | 64.0–87.5, 중심 72.8 | **11.4–15.6, 중심 13.7** |
| bp (stage 0.14–0.24 + tier 0.096) | 398–458 | 35.0–48.1 | 60.5–83.9 (두 카드 비용 c_two 0–2.5 포함) | 11.9–16.5, 중심 14.1 (a 대비 +0…+8 %) |
| gate (3090 단독, f 0.028) | 583 | 51–61 | 77–94 | 10.6–13.0 |
| a + MTP 쌍 패스 | V2 = (1+ρ)h + 2F + 1.5 + D. ρ 0.93–1.0, α 0.753/0.829 (`docs/cards/glmpair-probe.card`), D 2.2–3.0 | — | 87–126 | 13.9–21.0, 중심 17.9 (+30 %) |
| a, room 200 GB (페이징) | 정적 516 + NVMe 미스 슬롯 32개 | +57…155 (0.39 GB ÷ 2.51–6.77 GB/s) | 135–230 | 4–7 |

- 마지막 행의 NVMe 속도는 rig-log `log/2026-10-11.md:48`의 O_DIRECT QD1 2.51, QD16 6.77 GB/s입니다.
- 결론적으로 GLM-5.3은 다른 큰 모델과 같은 시점에 page cache를 나눠 쓰면 안 됩니다(room ≥ 238.8 GB).

**자원 시간선 (a, residency on, 중심, ms/토큰)**

| 자원 | 바쁜 시간 | 수요(같은 단위) | 근거 |
|---|---|---|---|
| 카드 SM (A6000) | C1 24 + 카드 expert 1.67 GB 약 2.8 | 15.86 GB ÷ 701 GB/s = 22.6 | VRAM 701 GB/s (rig-log log 09-30) |
| 호스트 CPU (32스레드) | h 43.4 + F 5.4 | — | τ × 462 |
| 호스트 DRAM | (h 안) | 5.59 GB ÷ 147.7 = 37.8 (÷ 135이면 41.4) | facts.md의 147.7(잠정), facts.md:108의 122.6–136.3 |
| PCIe | 활성값 3.7 MB ≈ 0.14 + residency staging ≤ 3 (비동기, SM 그늘) | — | 26.28 GB/s pinned |
| NVMe | 0 | — | nvme 0.000 (`plan.log`) |
| wall | **72.8 = 합** | 최대 수요 37.8–41.4 = step의 52–57 % | |

**판정.**
- 가장 바쁜 자원(호스트 DRAM)의 수요가 step의 절반을 조금 넘을 뿐입니다. 그래서 step은 층별 직렬 사슬의 지연입니다(AGENTS.md "busiest unit is not the bound").
- 한 자원의 항을 줄이는 레버는 0을 예측합니다. 먼저 쓸 레버는 흐름 레버입니다. MTP 쌍 패스나 `--parallel 2`로 두 행을 겹쳐 카드 front가 호스트 그늘에 들어가게 합니다. 쌍 패스에서는 2h ≈ 87이 2C1 ≈ 48을 덮어 호스트가 묶습니다.
- SIMD(호스트 GEMM)와 SIMT는 decode 1행에서 레버가 0입니다.

**prefill은 숫자를 내지 않습니다.** A의 round B 항목 4에 따르면 IQ2_XS에는 프롬프트 GEMM 행이 없습니다(`kernels.rs:430-442`, A가 인용). 카드 상주 expert의 prompt walk가 R6에서 정해진 뒤 예측합니다. 비교 기준선은 Flash pp512/4096 176/205(3090), 218/262(bp)입니다(`README.md:169,178`).

### 4.4 유도로 닫히지 않는 항 하나: τ_slot

- **항.** 32스레드에서 IQ2_XS gate/up(7.27 MB)과 IQ3_XXS down(4.82 MB)의 실효 rate입니다.
- **왜 유도로 안 닫히나.** 단일 코어 IQ2_XS rate는 4.3–4.6 GB/s(`docs/cards/q2k-iq2xs-rate.card`)이므로 32코어 CPU 항은 138–147 GB/s입니다. 이 값이 DRAM 항 122.6–136.3(facts.md:108)과 10 % 안에 있어서 max(CPU, DRAM) 이상이라는 것까지만 정해지고 정확한 값은 정해지지 않습니다.
- **기대값.** IQ2_XS@k=6144, T=32에서 118–140 GB/s, τ = 0.088–0.099 ms입니다 [derived].
- **닫는 방법.** 측정 R0b로 닫습니다. 모델 파일도 카드도 필요 없습니다.
  - `qdot-rate-mt.rs:35`의 `shapes()`에 IQ2_XS k=6144와 IQ3_XXS k=2048 행을 넣고, 초안 카드로 lease를 받습니다.
  - 카드 결정 갈래: 140 초과면 호스트 read를 재측정하고 τ = bytes / R로 내립니다. 118–140이면 band를 유지합니다. 118 미만이면 IQ2_XS 루프 커널 라운드를 엽니다.
  - `card.py check`는 ok입니다(아래 출력).
- **적중률은 별개의 가정입니다.** R3의 라우터 trace를 Mac에서 residency 시뮬레이터로 재생해 닫습니다. 박스 timed run이 필요 없습니다.

### 4.5 A 정정 (증거 포함)

1. **RAM 여유.** A가 쓴 "RAM 여유 약 261.5 GB"(A:134,190)는 엔진 기준이 아닙니다. 엔진 기준은 `PLAN_ROOM` 263,376,371,712 B입니다(`workstation.rs:129` = `HOST_USABLE` 270.07 − `OS_OTHER` 6.69, :121-122).
2. **"routed 238 GB가 RAM에 23 GB를 남기고 든다"(A:134)는 엔진 계획과 다릅니다.**
   - 엔진은 32.1 GB를 카드에 두고 호스트 need를 206.7로 잡습니다.
   - residency를 쓰면 churn pool 32.1 GB 사본이 붙어 238.8 GB가 되고, 남는 공간은 24.55 GB입니다.
   - 숫자는 비슷하지만 이유가 다르며, bp에서는 pool 둘이 room을 넘습니다(4.2).
3. **fixture 층 선택(A round B 항목 8).** A가 제안한 층(0–2, 3, 6, 78)을 그대로 이어 붙이면 번호가 바뀝니다.
   - 6번 층이 f4가 되는데, `4%4==0`이라 shared로 계산됩니다. 원본 6번은 full이므로 종류가 바뀝니다.
   - 선택기 패턴은 파일에 없고 리더가 기본값으로 계산합니다(A 항목 9). 그래서 fixture는 **번호를 다시 매겨도 종류가 보존되는 층 집합**이어야 합니다.
   - 대안은 5.3절에 있습니다.
4. KV 96,384 B/토큰과 카드 dense 14.19 GB는 맞습니다. KV는 trunk 95,232 + NextN 1,152입니다.

---

## 5. Oracle과 refset

### 5.1 덤프 엔진

**ik를 oracle로 씁니다.**
- Mac ik 트리(41b17995)의 git log에서 GLM_DSA는 528cadb0, `--dsa`는 9da563d0(#2045, 기본 off, `common.cpp:1934`), MTP는 6eff055a에 들어왔습니다.
- 박스 pin db517b69는 Mac 트리에 없습니다(A:180-184).

**R0의 첫 작업.** 박스 `/home/user/ik-idxkey`에서 세 커밋이 HEAD의 조상인지 확인합니다. `git merge-base --is-ancestor`로 하면 되고, `BLOOMERY_BOX_READONLY=1`로 됩니다. 그래서 cargo는 돌지 않습니다.
- 조상이 아니면 mimo2 선례처럼 새 빌드 디렉터리와 pin을 만들고, `IK_BUILD`/`MTP_BUILD`를 family에 따로 적습니다. Flash도 두 빌드를 씁니다(`crates/refset/src/arch/glm5next/mod.rs:1-8`).

**DSA 세트의 조건.**
- ik는 `n_top_k < n_kv`일 때만 indexer를 돕니다(`src/graphs/build_deepseek2.cpp:392`).
- decode 빠른 경로는 `n_tokens == 1`, `n_top_k%256 == 0`, flash_attn, mla_attn이 1 또는 3일 때만 탑니다(`:343`).
- 그래서 DSA 세트는 깊이가 2048을 넘어야 합니다(D3K 이상).

**sink anchor.** ik는 각 시퀀스의 첫 토큰을 top-k에 항상 넣습니다. `DSA_SINK`는 디버그 전용 env이고 기본값은 1입니다(`build_deepseek2.cpp:589`, `src/llama.cpp:5545`).
- 덤프 규칙은 엔진의 indexer 규칙과 같아야 합니다. bug hunting이 `--act ours`처럼 엔진을 자신의 규칙과 비교하기 때문입니다.
- GLM-5.3이 붙는 공통 indexer가 sink를 넣는지는 R3 카드에서 코드를 읽어 정합니다. 넣지 않으면 `DSA_SINK=0`으로 덤프합니다.
- 이 라운드는 이 선택을 추정하지 않습니다.

**mainline(PR 25980, A §1)** 은 교차 확인과 공개 비교 기준(AGENTS "public comparison baseline is llama.cpp")으로만 씁니다.

**덤프 자원.**
- ik를 dense는 카드, experts는 CPU로 돌리면 호스트가 routed 234.7 GB를 들고 있어야 합니다. room 263.4 GB에서 남는 공간은 28.7 GB이고, mmap으로 파일 전체가 page cache에 남으면 9.5 GB입니다 [derived].
- 따라서 덤프 sitting에는 다른 큰 모델의 page cache가 없어야 합니다. Flash 185.5 + V4.1 214.0의 선례가 있습니다(spec).
- 토큰당 계산량은 Flash의 1.53배입니다 [derived: (14.19 + 600×0.01222) / (8.97 + 336×0.0152) GB].
- 첫 적재는 254 GB ÷ 2.51–6.77 GB/s = 38–101 s입니다 [derived].

### 5.2 refset family 행 (`crates/refset/src/arch/glm_dsa/mod.rs`, 새 파일)

- **식별자.** `MODEL = /models/GLM-5.3-UD-Q2_K_XL/GLM-5.3-UD-Q2_K_XL-00001-of-00007.gguf`(첫 shard의 전체 경로가 식별자, AGENTS "Reference sets have one reader"), `ARCH = "glm-dsa"`.
- **세트.**
  - `IK`: batch, step4, step4-every-node, D1K
  - `IK_DSA`: D3K. D16K는 weekly
  - `MTP`
  - 이들의 fixture 거울 `fx_*`
  - `BY_ARCH` 행
- **Flash 세트는 재사용할 수 없습니다.** Flash의 DSA 세트는 k-pool indexer를 켜고 덤프했습니다(`glm5next/mod.rs:4-6`). GLM-5.3에는 kpool이 없습니다(A:106).

### 5.3 fixture tier (cut-layer, 753B를 requant하지 않음)

- **층 선택(제안).** `LAYER_MAP = [0, 1, 6, 7, 8, 75, 78]`, `FIXTURE_FF = 512`. Flash의 512(`glm5next/fixture.rs:52,56`)와 같습니다.
- **번호를 다시 매긴 뒤의 종류.**

  | fixture 층 | 원본 | 종류 |
  |---|---|---|
  | f0 | L0 | full dense |
  | f1 | L1 | full dense |
  | f2 | L6 | full MoE (`2%4==2`) |
  | f3 | L7 | shared |
  | f4 | L8 | shared, 층 8 전용 타입 |
  | f5 | L75 | shared, down IQ4_XS |
  | f6 | L78 | NextN |

  선택기 규칙이 원본과 같은 종류를 내므로 4.5의 3번 문제가 없습니다. `leading_dense_block_count`는 2, `block_count`는 7로 다시 씁니다. 크기는 7.156 GB입니다 [derived].
- **등록할 곳.**
  - `crates/model/src/arch/glm_dsa/fixture.rs`: FixtureSpec, 카드 예산은 계획식
  - `crates/refset/src/arch/glm_dsa/fixture.rs`
  - `crates/model-hf/src/bin/fixture.rs:44`의 SPECS
  - `tools/fixture-dirs.tsv` 행 `glm-dsa<TAB>glm-dsa`. 디렉터리 이름 규칙(소문자, 숫자, `-`)에 맞습니다(:6).
  - `tools/arch-registry.tsv`, `tools/families.tsv`(F 행), `tools/gate-class.tsv`
- **이름 충돌.** Flash의 fixture STEM이 이미 `"glm53-fixture"`입니다(`glm5next/fixture.rs:77`). 새 STEM은 `"glm-dsa-fixture"`로 둡니다.

### 5.4 rung별 게이트

| rung | 게이트 | tier |
|---|---|---|
| 리더 | `gate-glmdsa-meta`(실파일 헤더 sparse set, 카드 없음) | real 헤더만 |
| plan | 같은 recipe 안의 plan clause. 4.2 표의 수와 두 churn pool 합의 판정 | 순수 |
| refset | `refset-check`, family check의 거부 clause(다른 파일, 빌드, arch) | — |
| 카드 body | `gate-gpu-glmdsa-e2e`(IK와 IK_DSA 비교, forced_exact count pin), `-sel`, `-mla`, `-router` | fixture, D16K는 real 전용 |
| MTP | `gate-gpu-glmdsa-mtp` | fixture |
| seat | `gate-glmdsa-serve`, `-residency`, `-twocard` | fixture, 두 카드는 real |

---

## 6. 라운드 사다리

예측 wall은 `~/.cache/bloomery/gate-times.tsv`의 최근 Flash 중앙값을 기준으로 잡았습니다: meta 2 s, sel 7, mla 3, router 3, e2e 778, mtp 115, serve 490, residency 113, twocard 291. 배율은 [derived]입니다.

**R0 (리드, 박스, lease 없음)**
- 할 일:
  - ik 조상 확인(5.1)
  - rig-log `tools/fetch-gguf.sh`로 다운로드
  - sha256을 lfs oid와 대조
  - stage에서 `/models`로 이동
  - 헤더 sparse set 확보
- 파일: rig-log(다운로드 로그), bloomery `tools/ref/models/glm-dsa.sh`(profile, glm5next.sh 선례)
- wall: 80 MB/s 기준 53분(A:161, `fetch-gguf.sh:23-24`) + 해시·복사 수 분
- 증명: 파일이 /models에 있고 해시가 맞음

**R0b (리드의 go, lease)**
- 파일: bloomery `crates/qdot/src/bin/qdot-rate-mt.rs`(`shapes()` 두 행), `docs/cards/glm53-slotrate.card`(초안을 옮김)
- 게이트: `gate-qdot`
- wall: 수 분 [추정, 기록 없음]. 모델 파일은 필요 없습니다.
- 증명: τ_slot(4.4). **이것이 이 설계의 유일한 timed run입니다.**

**R1 (리더, 첫 라운드: 받아야 할 것은 하나도 거부하지 않음)**
- 파일(모두 bloomery):
  - `crates/model/src/arch/glm_dsa/{mod.rs, roles.rs}`
  - registry 행, `Arch` variant
  - `program_of`는 `None`
  - `defaults`에 선택기 규칙과 LN eps를 출처(ik 줄)와 함께 기록(A 항목 9)
  - `crates/model/tests/glm_dsa_meta.rs`
  - justfile `gate-glmdsa-meta`, gate-class와 families 행
- 박스: 카드 없음, lease 없음. 게이트 약 2 s + 빌드
- 증명:
  - 1,809개 텐서가 모두 역할을 받음
  - hparam 키를 모두 읽음
  - plan에서는 "no card program for glm-dsa"라는 이름 있는 오류로 멈춤
- FAIL-first: 모르는 stem 하나, 빠진 텐서 하나 → 각각 이름 있는 거부

**R2a (lift, move class)**
- 할 일: 반복되는 `plan_in_pool → loaded_routed → plan_at → expert_nvme_tier` 조합(5곳, 아래 개선 1)을 `crates/placement`의 공통 함수 하나로 올림
- 게이트: `just canon-check BASE`, 각 모델의 plan 게이트(값 동일)
- 박스: no-JIT 스캔만
- 증명: 동작 불변

**R2b (plan)**
- 파일: `crates/model/src/arch/glm_dsa/place.rs`. R2a의 공통 함수, `Program::GlmDsaBody` → `common_leg_card`, NextN 계획
- 게이트: R1 recipe의 plan clause. 4.2 표의 수를 pin하고 bp의 두 churn pool 합을 판정
- 박스: 카드 없음, 수 초
- 증명: plan이 엔진에서 나오며 하네스와 같음

**R3 (refset)**
- 파일: bloomery `crates/refset/src/arch/glm_dsa/mod.rs`, `tools/ref/models/glm-dsa.sh`(덤프 recipe). rig-log 로그
- 박스: 덤프 sitting(page cache에 다른 큰 모델 없음). wall은 Flash 덤프 wall × 1.53 + 첫 적재 38–101 s [derived]. Flash 덤프 wall은 기록에서 읽지 않았습니다.
- 라우터 trace 덤프 하나도 같이 받음 → Mac에서 적중률 가정(4.3)을 재생
- 증명: 세트가 있고 family check가 남의 세트를 거부함

**R4 (fixture)**
- 파일: 5.3의 등록 파일들
- 박스: fixture 생성(7.2 GB 쓰기) + `fx_*` 덤프. 수 분에서 십여 분 [추정]
- 증명: fixture가 `Tier::check_file`을 통과하고 층 종류가 보존됨

**R5 (공통 커널 추가, add class)**
- 대상: A §2의 N1(576폭 gather attention), N2(index-key append), N3(rope를 앞에 두는 score 인스턴스), IQ2_XS 프롬프트 GEMM 행(A 항목 4)
- 게이트: `just ptx-compare BASE BIN`(기존 엔트리는 그대로, 새 엔트리만 추가), `gate-ptx-spill`이 새 행에서 먼저 red, family 게이트 FAIL-first
- 박스: 카드, gate lock
- 증명: 커널이 기존 것을 움직이지 않음

**R6 (카드 body)**
- 파일: 새 `crates/gpu-glm-dsa`. 자체 device 코드 없이 공통 커널을 조합(`gpu-mimo2` 선례, A:105)
- 게이트: e2e, sel, mla, router. fixture tier wall은 Flash 합계(약 13.5분)를 기준으로 비슷하게 봅니다. real D16K는 778 s × 1.53 ≈ 20분 [derived].
- 증명: ik와 band 안에서 일치. 여기서 prefill 예측(4.3)을 냅니다.

**R7 (MTP)**
- 할 일: 카드 NextN을 `gpu-glm5next/src/nextn.rs`에서 공통으로 lift한 뒤 붙임(A 항목 11)
- 게이트: mtp, fixture 약 2분
- 증명: α가 Flash band 0.75–0.83 안에 드는지 R9에서 측정

**R8 (seat)**
- 할 일: NVMe와 MTP를 `serve_seats/tiered.rs`로 lift한 뒤 seat를 붙임. glm.rs를 복사하지 않습니다(A:99, 항목 10).
- 게이트: serve, residency, twocard
- 증명: residency가 켜지고 bp churn pool 판정을 통과

**R9 (공개 수치, 리드의 go)**
- 측정: pp512/4096, 디코드 깊이 6/1024/4096, A6000 표와 bp 표를 따로. 같은 lease에서 mainline을 비교 기준으로 함께 측정
- 증명: 4.3의 band. 빗나가면 어느 항이 틀렸는지가 결과입니다.

**리드나 사용자가 정할 것.** 문서가 Flash를 "GLM-5.3"이라 부릅니다(`README.md:58`, A 항목 12). R1 전에 모델 이름과 seat 이름을 정해야 합니다. 그리고 plan-triage 15행에 "기존 모델의 빈 곳을 새 모델보다 먼저 채운다"는 우선순위가 있습니다(A 항목 13).

---

## 실행한 검증 명령과 출력

- 하네스 빌드: `RUSTUP_TOOLCHAIN=nightly-2026-08-28 CARGO_TARGET_DIR=<scratch>/target cargo build --release` → rc=0
- `plan.log`(139줄) 핵심 줄:
  - `tensors 1809 total 253868860416 B`
  - `host-only routed stacks under the common leg rule: 0`
  - `card0 A6000: usable 50.952 dense 14.187 experts 32.132 (2629 experts) … headroom 1.787 GB`
  - `experts on cards 4475 of 19200 = f 0.2331`
  - 모든 경우 `violations_beside(reserve+draft): 0`
- `python3 tools/ref/card.py check <scratch>/glm53-slotrate.card` → `card: ok kind=calibration (no ruler: not an ab card)`, rc=0
- `git -C ~/repo/bloomery status --short` → 출력 없음(clean)

## 범위 밖 개선 지점 (보고만 함)

1. **plan 조합 중복.** `crates/model/src/arch/deepseek41/place.rs:215-229`, `glm5next/place.rs:615-633`과 `:994`, `qwen35moe/place.rs:484`과 `:666`, `place_hybrid.rs:286`이 같은 순서(plan_in_pool, loaded_routed, plan_at, expert_nvme_tier)를 각자 들고 있습니다. GLM-5.3이 붙으면 일곱 번째 사본이 됩니다. 공통 함수 하나로 올리면 약 80줄이 줄어듭니다(M).
2. **churn pool 합계를 보지 않음.** `crates/placement/src/placement/churn.rs:86-100`의 `headroom_after`/`check_beside`는 카드별 pool을 하나씩 판정합니다. 하네스가 그대로 부른 결과 bp의 두 pool 합(54.7 GB)이 room을 넘는 것을 놓쳤습니다. 엔진 호출처도 같은지 확인할 가치가 있습니다(S–M).
3. **32스레드 rate 측정 수단이 없음.** `crates/qdot/src/bin/qdot-rate-mt.rs:35`의 `shapes()`에 IQ2_XS와 IQ3_XXS 행이 없어서 IQ 계열 routed 타입의 32스레드 rate를 잴 수 없습니다(S, 약 10줄. R0b가 채움).
4. **README의 "GLM-5.3"이 Flash를 가리킴.** `README.md:58`이 Flash를 "GLM-5.3"이라 부르므로 full 모델이 들어오면 뜻이 겹칩니다(XS, 문서).
5. **fixture STEM 이름 충돌.** `crates/model/src/arch/glm5next/fixture.rs:77`의 STEM `"glm53-fixture"`가 full 모델 이름과 겹칩니다. 바꿀지는 리드가 정합니다(XS).

## 실행 모델

Opus 5.5(`claude-opus-5-5`). 리드가 "(Opus: design round.)"로 지정한 설계 라운드입니다.
