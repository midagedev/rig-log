# Sending things upstream

Running unreleased models on mismatched hardware is a good way to find other
people's untested paths. This is how a failure on this machine becomes
something a maintainer can act on — and how it gets decided whether that is a
pull request, an issue, or nothing at all.

The pipeline is adapted from a general one; every step below is here because
skipping it cost something on this machine, and the cost is named.

## 0. Decide what the contribution is

Three outcomes, and picking the wrong one wastes the maintainer's time as
well as yours:

| You have | Send |
|---|---|
| A defect **and** its cause, small diff, measured before/after | a pull request |
| A defect, reproducible, cause unknown | an issue with the reproducer |
| A defect that turns out to be your own configuration | nothing |

A fix whose cause you inferred from reading source is not the first category.
It is a hypothesis, and it goes nowhere until step 2 turns it into an
observation.

## 1. Prior art, before writing any code

Search **issues, pull requests, and discussions**, and record the queries
verbatim so the absence is checkable by someone else.

GitHub's REST search does not see discussions; use GraphQL:

```bash
gh api graphql -f query='query{ search(query: "repo:OWNER/REPO <terms>",
  type: DISCUSSION, first: 5){ discussionCount nodes{ ... on Discussion { number title } } } }'
```

Then find the **closest merged pull requests of the same class** — not the
same subject, the same *shape*. What they looked like, how big they were, who
reviewed them, what evidence they carried. A taste argument loses; "same
class as #X, already merged" wins. For the null-deref fix below, the
precedents were an unchecked-value crash fix and a null-buffer crash fix,
both one file and under ten lines, both bodies a paragraph of mechanism plus
a measured repro. That told us the shape before we wrote a line.

Also look for the adjacent thing that is *not* the same, and say so in the
body. There was a closed issue about the same allocation failing, correctly
closed as a configuration problem; naming it and explaining the difference is
cheaper than having a maintainer find it and assume you did not look.

## 2. Measured FAIL-first

**Observe the bad behaviour on the target's current tip before drafting
anything.** Not on your build from last week — fetch and check, because a
stale assumption here invalidates everything after it.

Two things this step caught in one afternoon:

- A dossier item read "rebuild with PR #2432 included and re-test; if it
  resolves, there is nothing to report." One `gh pr view` showed #2432 was
  **closed, not merged**, and `git ls-remote` showed the local build already
  *was* `origin/main` tip. The whole item was void, and a day of rebuilding
  would have produced no information.
- A claim that a bug was `llama-server`-only, with `llama-cli` as the working
  control. It was wrong. The control had been run at `--temp 0`, which takes
  an argmax and so never reaches the code that aborts — it produced empty
  output that looked like success. At `--temp 0.7`, `llama-cli` aborts
  identically. **A control that does not exercise the failing path is not a
  control**, and a report built on it would have sent a maintainer looking in
  the wrong binary.

Get a backtrace if it crashes. `gdb -batch -ex run -ex bt --args <cmd>` on
the unpatched binary is thirty seconds and it turns "somewhere in this
function" into a frame.

## 3. Reduce the reproducer

Strip every flag that is not required, and keep stripping until removing one
more makes the failure go away. What you want to hand over is something a
maintainer can paste.

Worth the effort in both directions: dropping `--jinja`, the template flags,
the tensor overrides, the attention mode and most of the context turned a
nine-flag serving command into

```bash
llama-server -m <file> -ngl 0 -c 8192 -t 32
curl .../completion -d '{"prompt":"Hello","n_predict":64,"temperature":0.7}'
```

which needs no GPU at all — so anyone with the file and enough RAM can run
it. A reproducer that requires two specific GPUs will sit unreproduced.

Then localize. `llama-eval-callback` prints every tensor with its sum, so the
first `nan` in that log names the operation and its inputs. One flag
(`-no-fmoe`) moved the NaN from the fused kernel to a plain matmul over the
same tensor, which exonerated the fused path in a single run. Narrowing like
that is what separates an issue a maintainer can act on from a bug report
that says "it crashes".

## 4. The patch: minimal, single-purpose, local conventions

One fix per pull request. Match what the surrounding code already does,
including which error value each function returns — divergence is what gets
flagged, parity is what makes review instant.

Where a fix is wider than the one line that breaks, say why in the body,
per site. The null-deref fix touched five places: the producer, which stopped
dereferencing, and four callers, which would otherwise have received the
`nullptr` and crashed one frame later. That needed three sentences, not a
defence.

Read the target's `CONTRIBUTING.md` and follow it exactly. **Its rules do not
transfer between repositories, so read the one you are submitting to.** The
bullets below were written from ik_llama.cpp's, whose CONTRIBUTING calls out AI
slop in descriptions:

- Disclose AI assistance in the body.
- The commit **author** must be a person. No AI co-author trailer, whatever
  your local tooling appends by default.
- No AI-generated comments in the diff. If in doubt, remove all of them.
- Use the project's squashed-commit title format.

That file's wording is "AI usage is not encouraged but it is tolerated", and it
also says: do not submit a PR you do not understand or have never tested
sufficiently. Two consequences worth stating, because a comment is not a PR and
the rules read as if they were only about patches. The disclosure applies to
**anything you post**, so a measurement left on someone else's PR carries the
same sentence. And the "never tested" clause is what forces the verification
boundary into the text: a measurement of the *bug* a PR fixes is not a test of
that PR, so the comment has to say which of the two it is. Measured 2026-09-17
on [#2418](https://github.com/ikawrakow/ik_llama.cpp/pull/2418), where the
numbers were all taken on the unpatched tip and the branch was never built.

mistral.rs is the counter-example, measured 2026-09-17: there is no
`CONTRIBUTING.md` at all, the conventions live in a committed `AGENTS.md` and a
near-duplicate `CLAUDE.md` addressed to agents, there is no disclosure rule of
any kind, and the maintainer merges `Co-Authored-By: Claude` commits of his own
(three of the four such commits in that history are his). Carrying ik's bullets
there would have meant stripping a trailer the maintainer uses himself. What
that repo does demand instead is a house style a default agent breaks on sight:
comments default to **none**, one line each where they exist, ASCII only with no
em-dashes and no `--`, magic values hoisted to named `const`s, no defensive
handling for cases that cannot occur, and no "Test plan" section in a body.

### Whether the patch carries a test: count, do not read

The written rule points the wrong way often enough that reading it is not
enough. mistral.rs's `AGENTS.md` says "Add tests and examples for new
functionality" — and of its twenty-two most recently merged `fix` pull requests,
**two** touched a test file, one of those a website JavaScript test and the
other a twenty-five-file "address recent correctness regressions". The four
adjacent single-purpose fixes, including a dtype bug in the same crate
([#1755](https://github.com/EricLBuehler/mistral.rs/pull/1755)), were each one
file with no test. So the convention there, for a fix, is no test, and the
sentence in `AGENTS.md` is about new functionality.

Counting is one `gh` loop over `gh pr list --search "fix in:title" --state
merged` plus `pulls/<n>/files`, and it answers in a minute what a style
document cannot.

Our own four submissions, which is the same question asked from the other side:

| PR | shipped a test |
|---|---|
| ik_llama.cpp [#2444](https://github.com/ikawrakow/ik_llama.cpp/pull/2444) | no (one file, +5/−1) |
| exllamav3 [#376](https://github.com/turboderp-org/exllamav3/pull/376) | yes (+39, a guard that fails on the unpatched file) |
| llama.cpp [#29008](https://github.com/ggml-org/llama.cpp/pull/29008) | shipped one, **asked to remove it**, merged without |
| mistral.rs [#2430](https://github.com/EricLBuehler/mistral.rs/pull/2430) | no |

The llama.cpp one is the cautionary datapoint and it is worth being precise
about, because it was misread here once. A reviewer wrote "Please remove the
tests and we can get this merged in" and **gave no reason** — the tree is full
of parser tests in `tests/test-chat.cpp`, so it was not a rule about tests. A
second maintainer's remark in the same thread ("the attempt to align something
that won't align was just confusing") was read here as that reason, and it was
not: his commit was `--whitespace`, undoing column alignment in the parser file,
because the full-width `<｜User｜>` never lines up anyway. **A comment is
evidence of what it is about, not of what you need it to be about.**

So: **FAIL-first is a discipline, not necessarily an artifact.** Always measure
the failure and the fix locally; ship the test only when the count says that
repo ships tests for this class of change. Two further filters when it does:

- **Assert only what the fix promises.** The BF16 test drafted for #2430
  asserted that the BF16 path's values equalled the F32 path's exactly. It
  passed, because the fixture was all ones and both sides were exactly
  representable; with realistic values it fails, measured, `-3.859375` against
  `-3.8654757`. The fix promises dtype transparency, not bit-identical results,
  so the assertion was a trap for whoever edited the fixture next.
- **Where it goes matters as much as whether.** That test landed in
  `gguf/mod.rs`'s test module, which is entirely ISQ and UQFF plumbing. A
  forward-pass dtype test is an outlier there even in a repo that wanted one.

## 5. Pre-flight: predict the objections

Before submitting, read the final diff and body cold and ask what a tired
maintainer or an automated reviewer flags. The predictable classes: scope
wider than the title, a value returned that does not match the function's
convention, unchecked "tested" boxes with no explanation, and claims the diff
does not support.

For each: fix it, or pre-empt it in one sentence. A pre-empted objection
costs a sentence; an unanswered one costs a round trip and makes the
submission look unconsidered.

State the boundary of the testing honestly. "The project's backend op tests
do not reach this code, so I did not treat them as coverage" invites the
maintainer to run the step you could not. An overclaim they discover poisons
everything else in the body.

## 6. After submitting

Answer findings with things the reader can check themselves — file paths,
line numbers, pull request numbers — not opinions. Offer the follow-up
instead of arguing scope. Do not push a commit to answer what a sentence
answers; every push re-triggers review.

## What a refusal taught, since one happened

[#2437](https://github.com/ikawrakow/ik_llama.cpp/pull/2437) was declined and
closed. It was correct, seventeen lines, no false positives on six good files.
It failed on value, not on quality, and the failure is instructive enough to
change the steps above.

**Their code being wrong beats other people's input being wrong.** That is the
line the two submissions fell on either side of. A crash in the target's own
code is theirs to want fixed. A check that defends against a third party's
malformed output costs them permanent maintenance and pays someone else. The
maintainer's words were that it is "a very minor improvement to the user
experience", and on his side of the ledger that is right.

**No prior art of the same shape is a stop sign, not a green light.** The
crash fix had merged siblings to point at. The loader check had none, and that
absence was read as novelty. In a mature repository it more often means the
class has already been decided against.

**Ask in a paragraph before building.** For a class you are not sure is wanted,
an issue costs a paragraph and a refusal costs nothing. Here the patch, the
build, the false-positive run across six files and the body were all written
before the question was asked.

**Lead with what it saves the maintainer, not with what it fixes.** The real
argument for that check was that without it the symptom is NaN logits rather
than a bad file, so the reports arrive in his tracker — one user was already
composing exactly that report. That belonged in the first paragraph; it was in
the last line.

So step 0 gains a question: would the maintainer pay for these lines forever?
If the answer needs a paragraph of persuasion, it is an issue, not a pull
request.

## The record

| Date | Project | What | Outcome |
|---|---|---|---|
| 2026-09-21 | ik_llama.cpp | **후보(원인 확정, 대조 완료 — 제출 승인 대기)** — ~~`llama_kv_cache_clear` 뒤에도 앞 시퀀스가 생성한 토큰이 다음 프롬프트의 로짓을 바꾼다~~ **선 그음, 같은 날 밤. 캐시는 무죄다.** 실제 기제: ik는 그래프마다 `is_warming_up = n_eval == 0 && n_tokens == 1 && token[0] == BOS`(`src/llama-build-context.cpp:2735`)를 추론하고 워밍업 그래프는 `n_expert_used` 대신 전문가를 **전부** 돌린다(`:58`). `n_eval`은 **통계 카운터**로 `llama_synchronize` 안에서 `n_queued_tokens == 1`일 때만 오르고(`src/llama.cpp:12574`) `llama_reset_timings`가 0으로 되돌린다(`:13851`) — 그래서 프롬프트 전체를 밀어넣고 한 번 읽는 프로그램은 카운터가 영영 0이고 **매 시퀀스의 첫 그래프가 64전문가 그래프**가 된다. V2-Lite Q3_K_M(64 experts, top-6), 토큰 하나씩 디코드: 고립 디코드 하나 뒤의 `llama_synchronize` 한 줄을 넣고 빼는 것만으로 답이 1191(30.22) ↔ 245(29.23)로 뒤집히고, `llama_reset_timings`를 부르면 되돌아온다. CPU·CUDA 동일, 스레드 수 무관, `-mla`/`-fa` 무관, 그래프 재사용은 증폭기(끄면 편차 3.65 → 1.11)이지 원인 아님. GGUF가 말하는 `n_expert_used`는 6이므로 **넓혀진 답이 틀린 답**이다. ik 자신의 `common.cpp:4139` 워밍업 블록이 `llama_synchronize` 두 줄 뒤에 `llama_reset_timings`로 술어를 다시 무장시켜, 기본 경로와 `--no-warmup` 양쪽이 실사용에서 걸린 채 남는다. 출하 바이너리에서도 보인다: 같은 `llama-cli`에 `--temp 0`으로 `-ub 1 -b 1`을 더하면 답이 `" a variety of data"`에서 `" data and they make"`로 바뀌고 `--no-warmup`도 되돌리지 못한다(리드 재현 2026-09-21). 서버는 `GGML_KQ_MASK_PAD` 클램프가 `-b 1`을 16으로 올려 **우연히** 비껴간다. 줄번호는 빌드 `c10fbbcc` 기준이고 upstream main `9cba2e38`에서는 각각 `:2742`, `:12515`, `:13792`, `common.cpp:4174-4179`다(전부 리드가 해당 체크아웃에서 확인). 재현자: bloomery `tools/ref/kvclear_probe.cpp`(389줄, 차등 26팔 + 술어 접속사를 하나씩 뒤집는 5팔 + 노드 해시 `--trace`, 토크나이저 없음)와 mainline 이식본 [`tools/upstream/warmup-width/`](../tools/upstream/warmup-width/). ~~**막는 것**: mainline에 같은 거동이 있는지 — `llama-eval-callback` 관측이 양쪽 같아 보인다.~~ **답했다 — mainline은 넓히지 않는다.** 같아 보였던 관측은 ik를 ik에 댄 것이었다: `llama-eval-callback`을 낸 트리가 `ikawrakow/ik_llama.cpp` 체크아웃인데 로컬에서 "master"로 이름 붙어 있었고, mainline 빌드에는 그 바이너리가 아예 없다. 이식본으로 `930e2fa5`에서 기제 5팔 전부 `max_abs_diff` 0이고, eval 콜백으로 그래프 폭을 직접 읽으면 일곱 그래프 모두 6이다. `llama_set_warmup(ctx, true)`를 부르면 같은 자리가 64로 바뀌므로 도구가 눈먼 것이 아니다(양성 대조). mainline은 플래그가 서더라도 합산을 층별 `hparams.n_expert_used(il)`로 묶어(`src/llama-graph.cpp:2331`, PR #14753) 로짓이 그대로다 — ik의 `:1708`은 넓어진 쪽을 더한다. 사전조사: ik·llama.cpp 양쪽 트래커에 같은 증상 보고 없음(쿼리 9종). [기록](../log/2026-09-21.md#i-the-first-token-came-out-at-0918), [대조](../log/2026-09-21.md#l-the-tree-labelled-master-was-ik). **제출 보류(사용자 판단 2026-09-21)** — 본문은 [`ISSUE-DRAFT.md`](../tools/upstream/warmup-width/ISSUE-DRAFT.md)로 준비됐고 언제든 나갈 수 있다. ~~내기 전에 넣을 것 하나: 사정거리를 내 입으로 먼저 적는다~~ **적었다(2026-09-21 밤)** — 재현 블록 바로 뒤에 단일 토큰 배치가 있어야 한다는 것과 기본 `llama-cli`·`llama-server`는 무관하다는 것을 본문 앞쪽에 명시했다. ik 자신의 도구 중 걸리는 것은 `llama-cli -b 1`뿐이고(perplexity는 `batch_size` 청크, lookahead·lookup·speculative의 단일 토큰 디코드는 BOS가 아니라 술어가 거짓), 서버는 클램프로 비껴가므로 **메인테이너 자신의 품질 측정은 오염되지 않았다.** 남은 것은 사용자 승인 하나다. | candidate, not filed |
| 2026-09-21 | llama.cpp | **후보, 기제 미고립** — 문서화된 플래그 조합 `-ub 1 -b 1`에 본가 `llama-cli`가 어서트로 죽는다: `930e2fa5`, V2-Lite Q3_K_M, rc 134, `src/llama-context.cpp:1724: GGML_ASSERT(n_tokens_all <= cparams.n_batch) failed`(리드 재현 2026-09-21). 본가에는 ik가 가진 `GGML_KQ_MASK_PAD` 클램프가 없어(`grep GGML_KQ_MASK_PAD src/` 공집합) `n_batch`가 1로 남고, 프롬프트 일곱 토큰을 한 번에 내는 호출자가 그 단언을 깬다. 라이브러리 계약("호출자가 `n_batch`를 넘기지 말 것")을 깨는 쪽이 동봉 도구라면 고칠 자리는 도구인데, 이 HEAD의 `llama-cli`는 `llama_decode`를 직접 부르지 않고 `tools/cli/`의 클라이언트·서버 분리를 지나므로 **어느 호출자인지 아직 못 짚었다.** 코드 리딩으로 확정한 결함은 가설이다(파이프라인 ②) — 호출자 고립이 먼저고, 그 전에는 제출하지 않는다. | candidate, not filed |
| 2026-09-21 | ik_llama.cpp | **후보, 기제 미고립** — Qwen3-Coder-Next IQ4_XS에 3,216토큰 문서 번역을 시키면 ik `c10fbbcc`가 3/3 HTTP 500을 낸다. 생성은 3,844토큰·125.8 tok/s로 멀쩡히 끝난 뒤 요청이 버려지고, 로그에 `peg`·`unparsed` 줄이 없어 에러 본문을 못 잡았다. 같은 요청을 mainline은 `3d82ef62`(#29161, 2026-09-20 머지) 이후 빌드에서 3/3 200으로 답한다 — 유효하지 않은 UTF-8이 섞인 완성 생성을 PEG 파서가 통째로 버리던 것을 U+FFFD로 바꾼 패치다. ik의 파서는 다른 것이라 **같은 부류라는 것만 측정됐고 원인은 ik에서 고립되지 않았다**. FAIL-first가 먼저다(에러 본문 포착 → ik 파서 경로 지목 → 최소 재현자). [기록](../log/2026-09-21.md#j-the-blocked-command-went-around-846-times). | candidate, not filed |
| 2026-09-21 | ik_llama.cpp | **후보, 조사 전** — 메시지 구분자를 DeepSeek 파서가 발행하지 않아 서버 컨텍스트 체크포인트가 사용자 턴 경계에 놓이지 못한다. 본가에서는 우리가 낸 [#29008](https://github.com/ggml-org/llama.cpp/pull/29008)이 2026-09-19 머지돼 닫혔고(`common_chat_msg_delimiters`), ik의 `common/chat.cpp`에는 그 기제가 없다(확인: `delimiter` 검색 결과는 reasoning 구분자뿐). ik도 컨텍스트 체크포인트를 쓰므로(#2452, #2491) 같은 소비자가 있다. 재는 것: ik 서버가 체크포인트 경계를 어떻게 고르는지, 그리고 V4.1 긴 문서 대화에서 편집 시 재프리필 양(이 기계 본가 측정: 13k 접두 전체 재프리필 → 턴 경계 체크포인트). 포팅은 이미 머지된 패치가 원본이라 모양이 정해져 있다. | candidate, not filed |
| 2026-09-25 | cuda-oxide | [#1329](https://github.com/NVlabs/cuda-oxide/pull/1329) — `cargo oxide`가 새 백엔드를 공유 캐시의 `.so` 위에 `fs::copy`로 덮어써(같은 inode를 truncate 후 재작성) 그 파일을 이미 올린 rustc가 SIGBUS로 죽는다; 병렬 트랙 둘에서 실제로 겪었다. 같은 디렉터리의 임시 파일로 복사한 뒤 rename. 수정 전 소스에서 "설치 전에 연 핸들이 옛 바이트를 읽는가" 테스트가 빨강, 수정 후 호스트 테스트 242개 녹색; 버린 CARGO_HOME에서 두 번째 `setup` 동안 `.so`를 mmap한 리더가 수정 전 3/3 SIGBUS, 수정 후 0/3. +138/−1, 1파일. | open |
| 2026-09-23 | cuda-oxide | [#1321](https://github.com/NVlabs/cuda-oxide/pull/1321) — `#[unroll]`이 종료 조건에서 카운터에 상수를 더하는 루프(`while d + TILE <= WIDTH`, 타일 순회)를 "no recognized induction variable"로 거부했다. 분석이 오프셋을 기록하고 상수 bound를 정규화한다; 전체 언롤은 카운터·검사식의 랩을 거부하고, 부분 언롤은 완전한 묶음만 가드하고 나머지는 원래 루프로 보낸다; WGMMA 매처는 오프셋 가드를 계속 거부. main `1082e5e3`에서 FAIL-first(`while i + 1 <= 4`, verbose `trip=None primary_iv=None`). 메인테이너가 우리 커밋을 그대로 두고 경계 테스트 커밋을 얹었다 — 생성된 가드를 i8/u8 전 영역에서 랩 의미로 직접 평가, 내림·high-bit 전체 언롤 결과, 문서 주석에 "랩하지 않을 때" 조건. | **merged 2026-09-24**(nihalpasham) |
| 2026-09-23 | cutile-rs | [#309](https://github.com/NVlabs/cutile-rs/pull/309) — `CudaContext::mem_info() -> (free, total)` 한 메서드. `mem_get_info()`가 crate 비공개 모듈에 있어 밖에서는 `unsafe` 원시 호출뿐이었다. 누수 테스트의 원시 호출을 이 메서드로 바꿔 트리 안 소비자를 만들었고, 새 테스트는 `total == cuDeviceTotalMem`·`free <= total`. 3090에서 fmt·clippy(-D warnings)·leaks 4/4·doc 녹색. | open |
| 2026-09-21 | cuda-oxide | [#1314](https://github.com/NVlabs/cuda-oxide/pull/1314) — 시프트 양의 정수 폭이 피연산자와 다르면(`1u32 << i`, `i: usize`) 상수 폴더가 `APInt::shl: bitwidth mismatch (32 vs 64)`로 컴파일러를 죽인다; `#[unroll]`이 `usize` 카운터를 64비트 상수로 물질화한 뒤 SCCP가 그 쌍을 폴더에 넘긴다. 로워링(`convert_shift`)은 이미 폭을 맞추므로 폴더도 같은 규칙으로 — `shift_amount`가 양을 값의 폭으로 다시 표현하고 범위 검사는 원래 폭에서. 호스트 단위 테스트가 수정 전 같은 메시지로 실패; 3090에서 main 백엔드 rc 101 → 패치 백엔드 `== 1`/`== 85`; 예제 230개 compile-only 스모크가 두 백엔드에서 같은 227/3(실패 셋은 이 기계 llc의 `stmatrix` 미지원). +111/−10, 2파일. 본문·검증 기록은 bloomery `docs/upstream/`. | ~~open~~ **merged 2026-09-23**(nihalpasham) |
| 2026-09-21 | cuda-oxide / cutile-rs | [#107 코멘트](https://github.com/NVlabs/cuda-oxide/issues/107#issuecomment-5755814026) — `simt::CudaStream`에 `begin_capture`/`end_capture`/`is_capturing`을 더하는 패리티 패치를 포크 브랜치([feat/simt-stream-capture](https://github.com/NVlabs/cutile-rs/compare/main...midagedev:cutile-rs:feat/simt-stream-capture), DCO, 3090에서 GPU 테스트 3/3·FAIL-first)로 준비해 두고, PR을 내기 전에 방향을 물었다: 별도 PR인가, 같은 파일을 만지는 cutile-rs#257에 접는가, oxide 코드는 cuda-async로만 캡처하는 계획이라 불필요한가. 같은 모양의 그래프 PR이 방향 문제로 두 번 닫힌 레포라 질문이 먼저다. 데이터 포인트를 함께: 노드당 0.76 µs, 블록 0 FFN 융합 8 → 4노드에서 −19.7 µs 중 노드 갭의 몫 2.9 µs, 캡처가 스칼라를 얼려 KV 행·키 수·전문가 id를 디바이스 버퍼로 옮긴 일. | 답 대기 |
| 2026-09-15 | ik_llama.cpp | [#2455](https://github.com/ikawrakow/ik_llama.cpp/pull/2455) — DeepSeek-V4.1 (`deepseek41`): shared compressed KV streams, lagged hyper-connections, the low-rank-only query norm, and the engram tables, plus the row prefetch as its own commit. The first of the two PRs the maintainer asked for on #2438; the DSpark draft half is 5 files, +56/−14 on a branch and follows this one, because GitHub cannot base a fork PR on another fork branch. Rebased onto `19dfb71b` and both engines re-measured the same day: wikitext-2 2.2355 ± 0.0626 against the llama.cpp V4.1 branch's 2.2556 ± 0.0641, decode 20.4–20.7 against 21.2 tok/s at the same split. +794/−108 across 13 files, 2 commits. [Write-up](../log/2026-09-15.md#splitting-the-v41-port). **2026-09-21**: 메인테이너가 "머지하자, llama.cpp가 V4.1을 지원하면 그때 로더를 고치는 것으로 받아들이자"로 돌아섰다(9월 15일에 GGUF 규약이 안 정해졌다며 draft로 내린 것을 본인이 뒤집음). upstream `e057e7a2` 위로 리베이스(충돌은 `llama-model.cpp` 한 파일 — context-shift 예외 목록), 캐시 저장 경고를 1회로(리뷰 제안 그대로), 그리고 리베이스가 찾은 한 줄: #2452가 `llm_arch_is_hybrid`에 `DEEPSEEK4`를 더했는데 V4.1이 빠져 있어 같은 캐시 코드에서 두 아키텍처가 갈라질 참이었다(`cache.hybrid`·`v_trans`·상태 슬롯·`mla_attn` 가드·서버 체크포인트). CPU 전용 빌드 rc 0, draft 해제, MERGEABLE. 압축 상태 저장 질문에는 [답글](https://github.com/ikawrakow/ik_llama.cpp/pull/2455#issuecomment-5760008422) — 층별 레코드 포맷이 V4.1의 소유권(소스만 소유·읽는 층은 앨리어싱, 소유자 지도 둘이 독립, 텐서 집합 상이)을 못 적는다, 지금은 `layer_type 0`이라 복원이 0으로 돌아오므로 포맷 확장이나 저장 거부 중 선택을 물었다. **머지 2026-09-21 12:18Z**(`a7616195`, +796/−101 13파일, ikawrakow). 남은 반쪽(DSpark 드래프트, 5파일 +56/−14)이 이제 자기 PR로 올라갈 수 있다. 같은 날 #2438에 [답글](https://github.com/ikawrakow/ik_llama.cpp/issues/2438#issuecomment-5760619901) — @Skelectric의 `v41-on-vision`(19 ahead / 12 behind, 커밋 18개)이 main에 없는 것을 들고 있어서 경계를 그었다: 비전 mmproj·패킹 KV 캐시 타입·V4.1 채팅 템플릿과 DSML 파서·SWA 창 수정·MoE 정규화 가드는 그쪽이 이어 간다(중복 안 한다), 압축 상태 소유권(`ca30281a`)도 그쪽 것으로 넘기고, 우리는 드래프트 반쪽만 연다. 곁가지로 짚은 것: 그쪽 `151d8cbc`(`grid.y > 65535`일 때 `bin_bcast`를 1D 커널로)는 V4.1과 무관해 단독으로 낼 수 있다. | **merged** |
| 2026-09-15 | vcruz305/llama.cpp `runtime/deepseek41` (V4.1 port) | `llama_model_n_swa()` returns 0 for `DEEPSEEK4` so the server does not apply the 128-token SWA margin to a dsv4 memory's exact-position checkpoints; the V4.1 port added `DEEPSEEK41` without extending that case, so every follow-up turn on a long document re-prefilled ~2 600 tokens instead of ~560 (TTFT 21 → 8.8 s, 5/5 identical answers). One line. Mainline master measured unaffected on V4-Flash. Dossier: [`v41-serving.md`](v41-serving.md). [vcruz305/llama.cpp#3](https://github.com/vcruz305/llama.cpp/pull/3), +1/−1, opened 2026-09-15 against `runtime/deepseek41`. **2026-09-23 확인**: vcruz305가 [ggml-org/llama.cpp#28696](https://github.com/ggml-org/llama.cpp/pull/28696)을 09-22에 16커밋으로 다시 쌓으면서 draft를 풀었고, 우리 포크 PR 넷 중 셋을 우리 저자 커밋으로 그대로 실었다: 이 행(#3), #1(dflash), #4(DSML 태그 앞 공백 — 표에 따로 행이 없던 것, `2076412598`). #2만 빠졌다. #1·#3·#4 포크 PR은 같은 날 닫았다. | ~~open~~ **본가 PR에 합류** — `3b1179f6a3`(midagedev 저자)로 #28696에 실림, 2026-09-22. 포크 PR은 2026-09-23 닫음(#28696 커밋을 가리키는 한 줄) |
| 2026-09-11 | ik_llama.cpp | [#2436](https://github.com/ikawrakow/ik_llama.cpp/pull/2436) — `llama_build_graph()` returns `nullptr` on a DFlash K/V allocation failure and the result is dereferenced, turning a detected out-of-memory condition into a segfault. Four callers passed the value on unchecked. +18/−0. | merged 2026-09-14 |
| 2026-09-11 | ik_llama.cpp | [#2437](https://github.com/ikawrakow/ik_llama.cpp/pull/2437) — the loader checked a tensor's shape and type but never that the GGUF reserved as many bytes as the type requires, so a malformed file loaded silently and read across tensor boundaries. +17/−0. | closed, declined |
| 2026-09-13 | llama.cpp (V4.1 branch) | DeepSeek-V4.1's engram tensors take the body's quantization type, but the tables are never resident — a token reads a few dozen rows of 384 M off NVMe, so their precision costs disk and nothing else. Measured here on wikitext-2: 2.2438 at Q3_K against 2.1090 with the engram tensors at Q8_0, and the two tensor groups are additive, the 0.2 GB `engram_wkv` half worth about 160x more perplexity per byte than the 125 GB table. Upstream has no engram in `llama-quant.cpp` and no V4.1 outside draft [#28696](https://github.com/ggml-org/llama.cpp/pull/28696) (conversion only); [#19654](https://github.com/ggml-org/llama.cpp/pull/19654) closed unmerged. Recipient is the branch author, and the moment is when the C++ half goes up. **2026-09-21 재판단**: #28696은 9월 10일부터 draft에 리뷰 없음(9월 19일 "이 PR 죽었나" 질문에도 무응답)이고, 대신 ik가 #2455를 머지하려 한다. ik의 `llama-quant.cpp`에도 engram 규칙이 없으므로(확인: grep 0건) ik가 만드는 V4.1 퀀트는 같은 문제를 갖는다 — 수신자가 ik로 옮겨갈 수 있다. #2455 머지 뒤 후속 PR 후보. [Write-up](../log/2026-09-13.md#engram-q8-repack). | candidate, not filed |
| 2026-09-15 | exllamav3 | MTP drafting with CPU-offloaded experts (`-mcs`/`-mcl`) uses the drafter's `default_draft_size` 3, and on GLM-5.3-Flash at 4 bpw with 103 of 288 experts resident that loses 14 % against no draft (20.6 vs 23.3 tok/s, 47 % acceptance) where depth 1 gains 9 % (25.4, 77 %); the verify step is RAM-bandwidth-bound so only one drafted position pays. Prior-art search and a reproducer on a second placement still to do before filing; there is also no CLI knob for the depth (`model_init` has `-mtp` only; the bench sets `num_draft_tokens` on the `Generator`), so the request is a knob first and a default second. [Write-up](../log/2026-09-15.md#glm-5.3-flash-first-run). | candidate, not filed |
| 2026-09-14 | ik_llama.cpp | [#2438 comment](https://github.com/ikawrakow/ik_llama.cpp/issues/2438#issuecomment-5655462984) — the DSpark draft borrows the target's `token_embd`; a bf16 one lifts acceptance 41.1 → 45.5 % (block 5) and 54.8 → 60.1 % (block 3), the bf16 `output` adds nothing; the block mask is bidirectional in the reference and a dflash-local flag fixes the port's mask with no measurable effect. | posted |
| 2026-09-14 | Hugging Face, JigSawPT/DeepSeek-V4.1-Flash-DSpark-GGUF | [Community post #2](https://huggingface.co/JigSawPT/DeepSeek-V4.1-Flash-DSpark-GGUF/discussions/2) — keep the target's `token_embd` unquantized for this draft: +4–5 points of acceptance, 1.3 GB of RAM. | posted |
| 2026-09-14 | llama.cpp | [#28696 comment](https://github.com/ggml-org/llama.cpp/pull/28696#issuecomment-5655489873) — pointer for branch users: the V4.1 DSpark draft port and the fused-pre probe fix are PRs against `runtime/deepseek41`. | posted |
| 2026-09-14 | llama.cpp | [#26575 comment](https://github.com/ggml-org/llama.cpp/pull/26575#issuecomment-5655463160) — the request-level `speculative.n_max` is under `#if 0` in `server-schema.cpp`, so the per-request cap the PR adds cannot be tested through the request field; measured 5022/2192 both ways. | posted |
| 2026-09-14 | llama.cpp (V4.1 branch) | [vcruz305#1](https://github.com/vcruz305/llama.cpp/pull/1) — `dflash`: accept DeepSeek-V4.1 DSpark drafts (no `output_hc_*` head, lagged mixes, low-rank q norm). +52/−9, clean cherry-pick onto `runtime/deepseek41`, CPU compile there; measured on the merged tree 17.70 → 22.78 tok/s at block 3. V4 draft through the patched path untested, said so. | ~~open~~ **본가 PR에 합류** — `0758276edd`(midagedev 저자)로 #28696에 실림, 2026-09-22. 포크 PR은 2026-09-23 닫음(#28696 커밋을 가리키는 한 줄) |
| 2026-09-14 | llama.cpp (V4.1 branch) | [vcruz305#2](https://github.com/vcruz305/llama.cpp/pull/2) — `resolve_fused_ops` read a layer-boundary placement as missing support and disabled the fused HC pre op on every layer; ask the layer's device `supports_op` first. +10. The `-devd` abort with a DSpark draft noted in the body, not filed. Checked on master with DeepSeek-V4 (UD-IQ1_S, boundary at layer 22 and at 30): the probe keeps HC pre enabled there, so the defect is V4.1-specific (the pre node's inputs are the previous layer's lagged mix); nothing filed on ggml-org. | ~~open~~ **#28696에 실리지 않음**(2026-09-23 확인: 그 PR의 diff에 `resolve_fused_ops` 변경 없음, 파일 목록의 `src/llama-context.cpp`는 다른 hunk). 새 브랜치에서 결함이 남았는지는 안 쟀다 |
| 2026-09-11 | — | The all-NaN logits that started that investigation: a published IQ4_KSS file reserves 4 bytes per row too few in 127 of 129 expert tensors. ~~Not a defect in this engine — the quantizer returns the right size at HEAD and at the commit checked. Nothing filed upstream; the publisher was the right recipient.~~ The quantizer is correct, but the cause turned out to be the fork's own gguf-py (next row). [Write-up](v41-serving.md). | superseded |
| 2026-09-14 | ik_llama.cpp | [#2443](https://github.com/ikawrakow/ik_llama.cpp/pull/2443) — gguf-py sizes tensors without the per-row metadata that twenty of the fork's quant types carry, so any read-then-write script (`gguf_new_metadata.py`, which the #2437 publisher had used) writes each IQ4_KSS tensor rows × 4 bytes short. Reproduced from a clean `llama-quantize` output: nan perplexity before, byte-identical data and 1.0027 after. +34/−6, single table plus three call sites. | merged 2026-09-14 |
| 2026-09-14 | Hugging Face, KeinNiemand/DeepSeek-V4-Flash-0731-IK_GGUF | [Discussion 1, follow-up](https://huggingface.co/KeinNiemand/DeepSeek-V4-Flash-0731-IK_GGUF/discussions/1) — after the publisher traced the NaN files to a `gguf_new_metadata.py` rewrite: the defect is in every gguf-py read-then-write script (metadata scripts and the Python split tooling), files straight out of `llama-quantize` and C++ splits are fine, fix is #2443, bake the template into the source model until it lands. | posted |
| 2026-09-14 | ik_llama.cpp | engram row prefetch (fork commit 57735010, port of the V4.1-branch 86d01ece1): the table is memory-mapped and read lazily, so a new prompt's rows are synchronous major faults inside the graph; `posix_madvise(WILLNEED)` in `llama_set_engram_rows` takes the first pass from 13.6 to 18.4 tok/s (faults 41–62 → 1–11 a token), second pass unchanged. +23/−0, one function. ik has no V4.1 on master yet, so the recipient is the fork's V4.1 port; goes upstream with it or as its own PR once the arch lands. [Measurement](v41-serving.md). | filed as the second commit of #2455 |
| 2026-09-14 | ik_llama.cpp | [#2444](https://github.com/ikawrakow/ik_llama.cpp/pull/2444) — `GGML_CUDA_NO_PINNED_WEIGHTS`: `-ot` overrides to the CPU drop mmap so the weights land in pinned memory, which cannot succeed when they exceed RAM; the existing escape also unpins every staging buffer. One condition. V2-Lite hybrid tg128 65.1 / 60.1 / 66.0 (default / old escape / new); V4.1 loads where it did not. +5/−1. | merged 2026-09-15 |
| 2026-09-14 | ik_llama.cpp | [#2438 comment](https://github.com/ikawrakow/ik_llama.cpp/issues/2438#issuecomment-5656281274) — the V4.1 port branch offered as a reference with its verified and unverified scope (PPL 2.2258 vs 2.2438, decode 18.4/19.0 vs 18.6/19.8 at the same split); asks the maintainer whether to split it into PRs or leave it, since the V4 port went in as his own work after an external PR closed. | answered 2026-09-15: two PRs |
| 2026-09-15 | exllamav3 | [#376](https://github.com/turboderp-org/exllamav3/pull/376) — `BlockSparseMLP_CPU.can_defer_load` detected a static expert placement by reading `EXL3_MOE_CPU_SPLIT`, which `-mcs` never sets, so `-mcs` + `EXL3_MOE_CPU_SPLIT_STATS` let the router load after the permutation and the model generated garbage at a normal token rate. One line (read `infer_params.moe_cpu_split`, as the split registration already does) plus a unit test that fails on the unpatched 1.5.0 file. Three-arm reproducer on GLM-5.3-Flash 4.05 bpw; same fix sits inside the open #315, noted there. Base `dev`, AI-assistance disclosed in the #310 form. | ~~open~~ merged 2026-09-19 |
| 2026-09-15 | TabbyAPI | #454 (llama.cpp-style `timings` on completion responses) — patch prepared by the toktape session, not by this repo; checked here on the workstation against TabbyAPI main 53da791 with the same exllamav3 1.5.0 build: main has no `timings` on any of six requests, the patch places it on the last streamed chunk or top level and returns null for n=2, its unit tests fail to import on main and pass 23 on the patch. Measured along the way that exllamav3's `time_generate` spans n decode passes (one token = one pass), so the rate is n / time, and that TabbyAPI rounds its times to 0.01 s. [Log](../log/2026-09-15.md#exl3-serve-and-tabbyapi-timings). | candidate, not filed (the toktape session files it) |
| 2026-09-17 | ik_llama.cpp | [#2418](https://github.com/ikawrakow/ik_llama.cpp/pull/2418) comment - not our PR. Thireus had already fixed the Qwen3Next mixed-sequence prefill cliff; what this box had that the PR body did not was the size of it. Posted the `llama-batched-bench -npp 238 -ntg 256 -npl 1,2,4` table (prefill 2581.9 / 119.7 / 119.0 tok/s, decode flat at 133.8 / 137.9 / 157.2, so the 21x is confined to prefill), the warning the engine prints itself, and the server-level TTFT p50 of 248 ms / 4516 ms / 12529 ms at one, four and eight streams. Says in the text that the branch was never built, so it is the unpatched behaviour and not a verification; AI assistance disclosed in prose, no trailer, per that repo's CONTRIBUTING. | posted |
| 2026-09-17 | mistral.rs | [#2430](https://github.com/EricLBuehler/mistral.rs/pull/2430) — a GGUF MoE with any layer mapped to host memory fails every forward with `moe experts forward / dtype mismatch in matmul, lhs: BF16, rhs: F32`. `GgufMatMul::quantized_act_type` returns `None` for CPU weights so the packed 2D matmul can widen BF16 itself, which also switches off the cast `QuantMethod::gather_forward` applies; the indexed path dequantizes experts to F32 instead of widening. Five lines in `gguf/cpu.rs`, placed after the `indexed_gemv` fast path so that path keeps its dtype. One file, no test, because that is what twenty of the repo's twenty-two most recent merged `fix` PRs are; the regression test was written, used as the FAIL-first, and dropped. Scoped in three launches: `-n 0:40` clean, a dense GGUF on the same split serves, one layer is enough to break a MoE one. `fmt`, `clippy -D warnings`, 361 crate tests clean — 362 with the dropped test, and the row said 362 until this was checked. The body's first version claimed the bug was x86-only; the test failed on aarch64 too and the claim was struck before submission. Evidence upgraded the same night: the CUDA build of `d5ae0f1` finished with the box tree still clean, so the server-level pair is one commit on both sides — unpatched http 500 with two `dtype mismatch` lines, the PR commit applied verbatim http 200 with none. The body still attributes its server repro to v0.9.3 and is worth one edit. | open |
| 2026-09-17 | ik_llama.cpp | Qwen3Next concurrent prefill collapses from 2 582 to 119 tok/s because `src/llama.cpp:7051` chunks a mixed-sequence ubatch one token at a time — the 3.4 s to 10 s TTFTs measured on every four-stream take here. Already fixed by open PR [#2418](https://github.com/ikawrakow/ik_llama.cpp/pull/2418), so **nothing to file**: the contribution is the measurement as a comment there. [Log](../log/2026-09-17.md#b-where-the-four-stream-gap-actually-is). | duplicate of [#2418](https://github.com/ikawrakow/ik_llama.cpp/pull/2418); our measurement posted there 2026-09-17 |
| 2026-09-17 | ik_llama.cpp | MoE decode barely batches: `llama-batched-bench -npp 238 -ntg 256 -npl 1,2,4,8` on DeepSeek-V2-Lite Q3_K_M gives decode 202.1 / **156.1** / 229.9 / 317.0 tok/s, so two sequences are slower in total than one, while dense Qwen2.5-7B in the same harness gives 120.7 / 195.5 / 290.7 / 388.5. CUDA graphs ruled out (`GGML_CUDA_DISABLE_GRAPHS=1` costs 7 %, the collapse survives) and `-no-fmoe` is worse. Three duplicate searches found nothing. **Held, not filed** — a reproducer without a cause is a symptom report; needs per-op timing (nsys or a timing build, ik has no profiler env var). | candidate, held |
| 2026-09-17 | mistral.rs | **not filed** - the CPU GGUF MoE path dequantizes a block's entire expert stack to F32 and rebuilds an `UnquantLinear` on every forward, one line above where #2430 landed, so an offloaded layer costs a flat **442 ms per token** (measured 443.7 / 442.2 / 441.5 ms per layer at 1, 4 and 10 blocks on the host) against 0.20 ms for ik_llama.cpp, which runs the same matmul on the host across 26.7 cores (measured, `utime+stime`) and reads only the 8 of 256 routed experts in quantized form, where mistral.rs manages 1.3 cores. ik is therefore the existence proof to quote: a quantized sparse CPU expert path costs 0.20 ms per layer per token on this exact model and hardware. Nothing in the path uses the sparsity. Two candidate shapes: cache the dequantized stack, or gather the routed experts before dequantizing. Held because a rate is not a diagnosis - 442 ms is consistent with the dequantize and with other things, and the next step is a profile of one offloaded layer that attributes the milliseconds. Same rule that holds ik's batch-2 decode finding. | unfiled |
| 2026-09-19 | cuda-oxide | **candidate, held** — `#[unroll]` on a `while` loop with a `usize` counter fails device codegen with `APInt::shl: bitwidth mismatch (64 vs 32)` (cargo-oxide 0.2.1, git deps b9847e95, nightly-2026-08-28, sm_86); the same tree compiles `#[unroll]` on `u32`-counter loops, so the counter width is the working hypothesis, unverified. Needs a minimal repro in their examples layout, the counter-type intervention, and a duplicate search before filing. Found in the bloomery stage-0 muse arm; tracked as MUL-7. [Log](../log/2026-09-19.md#a-first-rust-kernel-two-arms). | unfiled |
| 2026-09-21 | ik_llama.cpp | **후보, 미확인** — 박스의 ik 빌드(`c10fbbcc`, #2455 브랜치 머리 = 그날의 master + 우리 두 커밋)가 DeepSeek-V2-Lite Q3_K_M을 `-ngl 99`로 올리면 9토큰 이상 배치 프리필에서 프롬프트와 무관한 로짓을 낸다: `llama-cli -ngl 99 -p "The first president of the United States was" --temp 0` → `emanoicisananthanth…`, 같은 명령 `-ngl 0` → ` George Washington. He was born on February`, 4토큰 프롬프트는 `-ngl 99`에서도 정상, 토큰을 하나씩 먹이면(M=1) 33개 프롬프트 전부 CPU와 같은 답. bloomery의 CUDA greedy 참조를 만들다 나왔고 리드가 재현했다. 아직 모르는 것: 깨끗한 upstream master에서도 나는가(아니면 우리 #2455가 들여왔는가), 어느 M에서 깨지는가, 어느 커널인가 — 그걸 재는 조사가 먼저다. **조사 끝(같은 날 오후, opus 조사 + 리드가 깨끗한 master에서 다시 재현)**: upstream의 버그다 — 새로 받아 지은 master `9cba2e38`(09-20, 우리 기준점보다 24커밋 앞)이 같은 쓰레기를 바이트까지 같게 낸다, 우리 V4.1 커밋은 무관. ~~9토큰 이상 배치 프리필~~ 정확히는 **ubatch 하나에 9열 이상**(`-ub 8` 정상 / `-ub 9` 쓰레기 = `MMVQ_MAX_BATCH_SIZE 8` 경계)이고 프롬프트 길이가 아니다. ~~프롬프트와 무관한 로짓~~ 프롬프트마다 다른 쓰레기가 나온다. 조건 둘이 더 붙는다: MLA 켜짐(`-mla 0`은 정상)과 `attn_kv_b`가 256원소 슈퍼블록 양자화(같은 Q3_K_M 레시피에서 그 텐서만 바꾼 GGUF 아홉 개 — Q3_K·Q4_K·Q6_K·IQ4_XS·IQ4_K 실패, Q8_0·Q5_0·Q4_0·IQ4_NL 통과). 같은 소스를 `-DGGML_CUDA_FORCE_CUBLAS=ON`으로 지으면 전부 고쳐지므로 결함은 MMQ 경로에 있다. ik 자신의 `llama-quantize`는 `attn_kv_b`를 Q8_0으로 강제해서 ik가 만든 파일은 안 걸리고 mainline이 만든 파일(이 공개 mradermacher 파일)이 걸린다. 가설로 남는 것: 유도 텐서 `attn_v_b`(3차원 `[512,128,16]`, 원본 타입을 물려받음)의 MMQ 행 패딩이나 `ne[2]` 보폭 — 토글로 분리하지 못했다. V2-Lite 밖의 MLA 모델은 재지 않았다. 중복 검색 19개 질의에서 같은 보고 없음. 재현 두 줄: `llama-cli -m DeepSeek-V2-Lite-Chat.Q3_K_M.gguf -ngl 99 -ub 512 -p "The first president of the United States was" -n 12 --temp 0`(쓰레기) 대 `-ub 8`(정상). **원인 측정(같은 날 저녁, opus 라운드 + 리드가 master·패치 빌드를 `-ub 8/16/512`와 IQ4_XS 변종으로 다시 돌려 확인)**: ~~결함은 MMQ 경로에 있다~~ ~~`attn_v_b`의 MMQ 행 패딩이나 `ne[2]` 보폭~~ 커널이 아니라 **할당**이다. `src/llama.cpp`의 `llm_prepare_mla`가 유도 MLA 가중치를 `ggml_nbytes(source)`로 할당하고 손으로 배치해서 `ggml_backend_buffer_init_tensor`가 돌지 않는다. `attn_k_b`(항상 Q8_0)는 `ne[0] = 128`인데 MMQ는 행당 256값을 읽으므로 마지막 행에서 할당 밖 메모리를 읽고, 거기 남은 half가 NaN이면 활성 패딩의 0과 곱해져 NaN이 그래프에 들어간다. 증거는 토글이다: 같은 바이너리에서 패딩을 `0xFF`로 채우면 27층 전부 `(행 511, 채널 15)`에 NaN, `0x00`이면 0개. 노드별 원소 비교(MMQ 대 cuBLAS 빌드)의 첫 실패도 `q_nope2-13`의 마지막 행이다. 앞 절의 '256블록 타입만 실패' 표는 커널 성질이 아니라 `cudaMalloc`이 남긴 바이트와의 상관이었다 — 지난 라운드에 통과한 `C-mqa-q3k.gguf`가 같은 바이너리에서 이번엔 실패했다. 패치는 `src/llama.cpp` 12줄 추가/2줄 삭제(버퍼 타입의 패딩 포함 크기로 할당 + `init_tensor` 호출, 두 분기 모두), 같은 부류의 머지된 선례는 #2292(COMPUTE 버퍼 쪽). master에서 쓰레기인 GGUF 여섯과 `-ngl 1/2/14/27` 부분 오프로드가 패치 뒤 전부 CPU 참조와 같고 그래프 전체 NaN 13842 → 0. 못 잰 것: `-sm graph/attn`의 랭크별 분기(GPU 한 장으로 돌렸다), V2-Lite 밖의 모델. 새 용어로 중복 검색 다섯 질의 더, 없음. 곁가지로 나온 별개 후보 하나: IQ4_XS의 CUDA mul_mat이 열 16 이하에서 NMSE 3e-2(32열은 정상) — 재현자만 있고 조사 전. | ~~이슈 초안 준비~~ ~~PR 초안 준비, 제출은 승인 대기~~ **PR #2493 제출**(2026-09-21, upstream `9cba2e38` 위 DCO 커밋 1개, 포크 브랜치 `mla-derived-weights-padded-alloc`) — ~~답 대기~~ **머지 2026-09-21**(`279f3019`, 제출 약 1시간 뒤, LGTM). 메인테이너는 mradermacher GGUF로 재현했고 증상은 gibberish가 아니라 illegal memory access였다(같은 NaN이 라우터 확률에 들어가 전문가 id가 범위를 벗어남 — 우리 경우는 id가 우연히 범위 안이라 gibberish로 보였다). "예전 V2-Lite 테스트에서 왜 안 걸렸나"는 질문에는 우리가 잰 경계 둘(MMQ 경로에서만 — `FORCE_CUBLAS` 빌드는 정상; ubatch 9토큰 이상에서만)과 패딩 바이트 운(`0x00` 정상 / `0xFF` 전 층 NaN)으로 답했다. |
| 2026-09-21 | ik_llama.cpp | **후보 둘, 재현 없음(코드 독해만)** — bloomery의 하이브리드 스케줄링 조사가 `ggml/src/ggml-backend.cpp`에서 읽었고 리드가 줄을 확인했다(포크 `c10fbbcc` 기준): ① 비-OpenMP 병렬 분할 실행기의 핫 루프에 `printf("Recording event %d, %d\n", …)`가 남아 있다(:2398; OpenMP 팔에는 없다) — 디버그 잔재로 보인다. ② `constexpr bool k_set_sync = false;`(:2019)라서 `needs_sync[...] = k_set_sync`가 전부 false의 죽은 대입이다 — 의도한 차단 스위치인지 필요한 동기화를 막는 버그인지 코드만으로는 모른다. 둘 다 그 경로를 실제로 타는 구성(다중 GPU graph split)에서 확인하기 전에는 보내지 않는다; ②는 패치가 아니라 질문이 맞다. | 기록만 |
| 2026-09-22 | ik_llama.cpp | **제출** [#2501](https://github.com/ikawrakow/ik_llama.cpp/pull/2501) — CUDA mma flash-attention 두 런처의 stream-k 가지가 `ggml_cuda_pool_alloc<float2>::alloc`에 원소 수 대신 바이트 수(`blocks_num.x*ncols*(2*2+DV)*sizeof(float)`)를 넘겨 임시 풀을 **8배** 예약한다. 메인라인은 같은 줄을 [ggml-org/llama.cpp#18559](https://github.com/ggml-org/llama.cpp/pull/18559)(2026-01-03 머지)로 고쳤고 ik는 안 가져왔다. FAIL-first: A6000에서 프로브 빌드가 `passed_elems=1056768 needed_elems=132096 ratio=8`(디코드)·`6488064/811008 ratio=8`(깊이 1024)을 찍었고, 고친 빌드가 같은 형상에서 돈다(tg32 202.8, 프로브 빌드 203.8). 중복 검색 9쿼리 결과 없음, 파일 커밋 15개 중 그 줄을 고친 것 없음. 같은 독해 라운드의 나머지 셋은 **보류**: U1 VKQ 재스케일 루프 상한이 레지스터 배열의 2배(UB, 관측 영향 미확인 — 메인라인은 #17505 리팩터가 부수적으로 지움), U5 `#endif` 주석 표시 누락(메인라인 #13926), U7 부분합 없을 때의 빈 fixup 런치(버그 아니라 낭비, 메인라인 #20586의 블록 상한 — nsys 런치 수를 잰 뒤에만). 패치 초안은 세션 스크래치 `ikup/`. 자동 리뷰 계정(생성 열흘, 리포 647개)의 APPROVED에 빌드·실행 사실로 [답글](https://github.com/ikawrakow/ik_llama.cpp/pull/2501#issuecomment-5768692861)(sm_86 A6000, tg32 202.8 / tg32@pp1024 195.8, 미패치와 잡음 안). ~~메인테이너 반응 대기.~~ **머지 2026-09-22 04:57Z**(ikawrakow). |
| 2026-09-23 | mlx-lm | **보내지 않음** — V4.1 PR [#1895](https://github.com/ml-explore/mlx-lm/pull/1895)(`00efcc2b46`)의 `sanitize`가 engram 텐서를 버리고 engram 모듈이 없다(테스트는 `engram_layer_ids=[]`, 저자 본인이 "실제 가중치로 시험 안 함"). ik에서 engram만 끈 측정: wikitext-2 c2048 4청크 PPL 2.2355 → 6.5954(2.95배), top-1 일치 63.4 %, KLD 1.18, 켬 대 켬 대조 0. 코멘트하지 않은 이유: 리뷰어가 붙지 않은 PR이고 mlx-lm의 V4 포트 여섯 개 이상이 리뷰 없이 닫혔으며, mlx-lm 규칙상 게시글은 사람이 직접 써야 해 들이는 품에 비해 받을 사람이 없다(사용자 판단). 측정은 맥에서 V4.1을 돌리려는 쪽이 부딪힐 문제로 남긴다. [기록](../log/2026-09-23.md#engram-off-ppl). | not sent |
| 2026-09-23 | ik_llama.cpp | [#2508](https://github.com/ikawrakow/ik_llama.cpp/pull/2508) — #2165가 fused indexer top-k를 기본값으로 바꿨는데 스위치는 켜는 `-fidx`뿐이라 명령줄에서 끌 수 없었다. `-no-fmoe`와 같은 방식으로 `-no-fidx`/`--no-fused-indexer-topk`를 더하고, 여전히 "기본 꺼짐"이라 적힌 주석과 `docs/parameters.md`를 고쳤다. +10/−4, 5파일. bloomery 세션이 냈다. | **merged 2026-09-23**(ikawrakow) |
| 2026-09-23 | ik_llama.cpp | [#2511](https://github.com/ikawrakow/ik_llama.cpp/pull/2511) — `iqk_flash_attn_noalibi`의 T=1 인덱스 가지가 스레드마다 `q`·`qkv`는 첫 헤드만큼 옮기면서 `sinks`는 옮기지 않아, 스레드의 첫 헤드 외에는 남의 sink를 읽었다. +1/−1. bloomery 세션이 냈다. [기록](../log/2026-09-23.md#iksink). | **merged 2026-09-23**(ikawrakow) |
| 2026-09-23 | ik_llama.cpp | [#2513](https://github.com/ikawrakow/ik_llama.cpp/pull/2513) — KLD 모드의 불확도가 음수 분산의 `sqrt`라, 두 실행이 거의 같으면 `± -nan`을 찍었다. 세 곳에서 분산을 `sqrt` 전에 0으로 자른다. +3/−3. 증상은 이 리포의 engram 대조 팔에서도 나왔다([기록](../log/2026-09-23.md#engram-off-ppl)의 켬 대 켬 팔 `± -nan`). bloomery 세션이 냈고, 중복 점검과 FAIL-first는 bloomery `docs/plan.md` ⑫. | **merged 2026-09-23**(ikawrakow) |

Findings that were investigated and deliberately not sent are worth a row
too, once there are any: a negative result that took a day is the same
information as a positive one, and the next session should not redo it.
