# 오프로딩 대역폭 영상

2026-09-30에 만든 35.5초 설명 영상(1080×1080, 60 fps)의 소스다. 이 기계에서 데이터가 오가는 통로 넷의 대역폭을 공 경주로 보이고, DeepSeek-V4.1-Flash 디코드 토큰 하나가 GPU·PCIe·CPU·RAM·NVMe를 어떻게 지나며 어디에서 시간이 드는지를 보인다. 완성본은 [`assets/offload-bandwidth-v3.mp4`](../../../assets/offload-bandwidth-v3.mp4), 경위는 [log 09-30](../../../log/2026-09-30.md#offload-clip).

영상 문구는 영어다(리포 밖으로 나가는 것). 이 문서는 한국어다.

## 다시 찍기

```
cd tools/clip/offload-bandwidth
python3 -m venv .venv && .venv/bin/pip install playwright numpy && .venv/bin/python -m playwright install chromium
python3 -m http.server 8765 --bind 127.0.0.1 &      # film.html을 서빙한다
.venv/bin/python render.py probe 0 11 20 32.5       # 스틸 몇 장 → probe/sheet.png
SUB=16 .venv/bin/python render.py full              # 한 프로세스로 전부: M-시리즈 Mac에서 약 36분
.venv/bin/python render.py pops                     # 한 프레임짜리 튐 검사, 0건이어야 한다
```

병렬로 찍으면 약 7분이다. 프레임 2,130개를 구간으로 나눠 청크마다 `SUB=16 F0=<시작> F1=<끝> NO_ENCODE=1 render.py full`을 띄우고, pid를 파일에 한 줄씩 적어 `while read p; do while kill -0 $p; do sleep 5; done; done < pids.txt`로 기다린 뒤 `render.py encode`를 돈다. zsh에서 `for p in $pids`는 낱말로 나뉘지 않아 기다림이 곧바로 끝난다(이 영상을 만들며 한 번 밟았다).

`film.html`은 모든 프레임을 시간의 순수 함수 `window.seek(t)` 하나로 그린다. 타이머와 프레임 사이 상태가 없어서 같은 t는 같은 프레임이다. `render.py`는 프레임마다 서브프레임 16장을 찍어 `tmix`로 섞는다(빠른 공의 모션 블러). 주소에 `?l3=<GB/s>`를 붙이면 1막에 L3 줄이 생긴다. 최종본은 이 줄을 뺐다(아래 「고친 것」).

## 화면의 숫자와 출처

1막 — 공 하나가 한 번 건널 때 1 GB, 시간 100배 느리게.

| 줄 | GB/s | 종류 | 출처 |
|---|---:|---|---|
| VRAM → GPU 코어 (RTX A6000) | 701 | 측정, 한 런치의 최고값 | [09-23#v41-dense-reads-a6000](../../../log/2026-09-23.md#v41-dense-reads-a6000) |
| RAM → CPU 코어 (DDR4-3600 ×8) | 147.7 | 측정, 32스레드 읽기 | [09-14](../../../log/2026-09-14.md) |
| RAM → VRAM (PCIe 4.0 ×16) | 26.28 | 측정, pinned 호스트 → A6000 | [09-25#m2-h2d-a6000](../../../log/2026-09-25.md#m2-h2d-a6000) |
| NVMe → RAM | 6.12 | 측정, O_DIRECT 한 스레드 | [09-29#odmax](../../../log/2026-09-29.md#odmax) |

2막 — 토큰 하나가 읽는 라우팅 expert 4,043,243,520 B(층마다 384개 중 6개 × 40층)를 위 대역폭으로 나눈 시간이다[유도]: 5.8 / 27.4 / 154 / 661 ms.

3막 바이트 — 공개 `DeepSeek-V4.1-Flash-Q3_K_M`(9샤드, 347,271,481,305 B)을 [`tools/gguf-roles.py`](../../gguf-roles.py)로 역할별로 셌다.

| 역할 | B | 화면 |
|---|---:|---|
| 라우팅 expert | 258,767,585,280 | 층당 109 MB(0·1층, q5_K) / 101 MB |
| engram 테이블 | 84,482,513,536 | NVMe 상자 |
| attention + hc + ffn_norm | 2,221,639,680 | ① 층당 ~55 MB |
| shared expert | 673,873,920 | ⑤ 층당 ~17 MB |
| head | 542,996,480 | ⑥ 토큰당 한 번 |
| router | 157,409,280 | ② 층당 ~4 MB |
| engram dense | 135,203,200 | blk.1·blk.14에서 attention 앞 |

PCIe로 건너는 것은 ik_llama.cpp 소스를 읽어 셌다[유도]. 층마다 나가는 hidden 20,480 B(f32 5,120개, hc가 섞은 한 줄기)와 expert id 24 B, 돌아오는 것은 합치기 전 expert 출력 6개 122,880 B다(가중 합은 GPU의 `MUL_MULTI_ADD`). 여기에 토큰 임베딩 행 20,480 B와 engram 행 두 번(49,152 B씩)을 더해 토큰당 5,854,144 B, RAM에서 읽는 양의 약 1/690이다. 확정하려면 `GGML_SCHED_DEBUG=1`로 스플릿 입력 목록을 한 번 뜬다.

3막 시간 — 바이트를 측정한 속도로 나눠 한 단계씩 더한 직렬 추정이다. 겹침이나 유휴는 주장하지 않는다. GPU는 [09-23](../../../log/2026-09-23.md#v41-dense-reads-a6000) 토큰 그래프 전체의 실측률 503 GB/s(701은 한 런치의 최고값이라 쓰지 않았다), CPU는 147.7 GB/s, PCIe 한 번은 약 3 µs([09-18](../../../log/2026-09-18.md), 82 KB에 3.0·3.2 µs)다. page fault는 토큰당 4–23회([09-14](../../../log/2026-09-14.md), [09-16](../../../log/2026-09-16.md)) × 회당 92–384 µs([09-22](../../../log/2026-09-22.md))로 0.4–9 ms 범위다. 합계는 토큰당 약 35–44 ms이고, 그중 CPU가 RAM을 읽는 27.4 ms가 가장 크다. KV 캐시는 세지 않았다.

## 고친 것

- ~~토큰당 expert 3.41 GB~~ → 4.04 GB. 3.41은 일부 층을 카드에 둔 배치의 호스트 몫이었다. 3막이 그리는 경우(expert 전부 호스트)와 맞췄다.
- ~~VRAM 토큰당 7.99 GB, attention 층당 136 MB~~ → 3.73 GB, 55 MB. 로컬 477 GB 빌드(attention·shared Q8_0) 인벤토리를 화면에 적힌 347 GB 공개 파일에 붙여 썼다. 기술 검토가 잡았다.
- ~~PCIe 토큰당 1.6 MB, RAM 대비 2,468×~~ → 5.85 MB, 약 690×. 돌아오는 쪽을 hidden 한 줄로 셌는데, 실제로는 합치기 전 expert 출력 6개가 돌아온다.
- ~~"ik: ~27 cores busy"~~ 뺐다. 09-17의 26.7코어는 Qwen3.6-35B 10층 오프로드의 값이다. ~~"~4 page faults (ik)"~~ → 이 박스에서 잰 범위 "4–23".
- ~~"The weights never move."~~ → "Expert weights stay in RAM." page fault가 NVMe에서 가중치 바이트를 옮기고, 임베딩과 engram 행도 버스를 건넌다.
- ~~L3 → CPU 2,207 GB/s 줄~~ 뺐다. 토큰의 가중치 4 GB는 L3 128 MB에 머물지 못해 오프로딩 경로의 병목이 아니다([09-30#l3-read-bw](../../../log/2026-09-30.md#l3-read-bw)).

## 만든 방법

[howseen-ai/claude-motion-design](https://github.com/howseen-ai/claude-motion-design)의 방식(시간의 함수 하나로 그리는 HTML + Playwright + ffmpeg)을 따랐고, `render.py`는 그 템플릿(MIT, 저작권 고지는 파일 머리말)을 고친 것이다. 스틸의 레이아웃·가독성 판정은 매번 새 opus 서브에이전트가 했고, 이론과 구조의 정확성은 Fable 서브에이전트가 ik_llama.cpp 소스와 이 리포 로그로 검토했다. 코드와 문구는 Claude Code(Opus 5.5)가 썼다.
