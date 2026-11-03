# Spark 공유 규칙: 벤치와 빌드가 서로 비켜 가는 법

2026-11-04에 정했다(사용자 지시: Spark는 우리 것이고, 첫 일은 GB10 릴리스 아카이브를 여기서 직접 빌드하는 것이다). Spark에는 두 부류가 일한다. 밤에 llama.cpp·vLLM·Atlas 같은 벤치를 돌리는 세션(`/opt/build`에 클론과 툴체인을 둔다)과, bloomery의 GB10 아카이브를 빌드하는 리드 쪽이다. 빌드는 CPU 20코어를 몇 분 쓰고 끝에 카드로 큐빈을 한 번 링크하므로, 벤치 측정 중에 돌면 측정이 오염되고 반대도 그렇다. 규칙은 박스의 보류 파일(`/root/bloomery-<owner>-hold`)과 같은 모양이다: 파일이 있으면 올라가 있는 것이다.

## 두 파일

| 파일 | 올리는 쪽 | 뜻 |
|---|---|---|
| `/root/spark-bench.hold` | 벤치 세션 | 벤치가 도는 동안. 리드의 빌드는 이것이 있는 동안 시작하지 않는다 |
| `/root/spark-lead.hold` | 리드의 빌드(`rig-log tools/bloomery-follow/spark-box.sh`가 자동으로) | 빌드가 도는 동안. 벤치는 이것이 있으면 시작하지 않는다 |

형식은 한 줄, 공백으로 가른 `key=value`다. `owner=`, `since=<epoch 초>`, `until=<epoch 초>`가 앞에 오고 자유 문장 `reason=`이 맨 뒤다.

    owner=bench since=1793736000 until=1793743200 reason=q8gemv bench, Qwen3.8 FP4-Local

`until`은 **끝나리라고 보는 시각**이다. 세션이 죽어 파일이 남아도 `until`이 지나면 양쪽 다 낡은 것으로 보고 무시한다(리드의 스크립트는 "past its until: stale, ignored"를 찍는다). `until`이 없는 파일은 지울 때까지 선 것으로 본다. 그러니 벤치는 `until`을 예상 종료 + 여유로 쓴다.

벤치가 이미 쓰는 임대 `/root/spark-lease`(`<pid> <이유> <시작>`, 그 pid가 살아 있으면 바쁨)도 같은 뜻으로 읽는다. 벤치 쪽은 새 파일을 올리지 않아도 지금처럼 돌 수 있다. 파일을 올리는 쪽이 리드에게 더 정확히 말하는 길이다(끝나는 시각을 준다).

## 벤치가 할 일

시작 전에 자기 hold를 올리고, 그 다음 리드의 hold를 본다. 두 hold가 같이 올라가면 **늦게 올린 쪽이 양보한다**(같은 초면 이름이 앞선 쪽, 곧 bench가 이긴다). 끝나면 어떤 경로로든 내린다.

    set -C                                           # noclobber: 이미 있으면 실패
    now=$(date +%s)
    echo "owner=bench since=$now until=$((now + 7200)) reason=<무엇>" > /root/spark-bench.hold || exit 75
    trap 'rm -f /root/spark-bench.hold' EXIT
    lead=$(head -n 1 /root/spark-lead.hold 2> /dev/null)
    case " $lead" in *" owner=lead "*)
      s=$(printf '%s' " $lead" | sed -n 's/.* since=\([0-9]*\).*/\1/p'); u=$(printf '%s' " $lead" | sed -n 's/.* until=\([0-9]*\).*/\1/p')
      if [ "${u:-9999999999}" -gt "$now" ] && [ "${s:-0}" -lt "$now" ]; then rm -f /root/spark-bench.hold; echo "lead build is running: wait"; exit 75; fi ;;
    esac

빌드는 몇 분(아래 측정: 2분 8초)이므로 기다려도 손해가 작다.

## 리드 쪽(spark-box.sh)이 하는 일

`tools/bloomery-follow/spark-box.sh -- <명령>`이 한 번의 실행이다. (1) 벤치가 올라가 있으면 30초마다 보며 기다린다. 기다린 뒤에는 두 번 연속 조용해야 시작한다. 기본 한도 1800초, follower는 기다리지 않고(`--wait 0`) 75로 끝나 "deferred"로 적고 다음 call에 다시 한다. (2) 트리를 `/root/bloomery-gb10`으로 rsync한다. (3) 한 번의 ssh로: 디렉터리 락(`/root/bloomery-locks/spark-box.lock`), `/root/spark-lead.hold` 올리기, 벤치를 한 번 더 보기(먼저 올라간 벤치가 있으면 자기 hold를 내리고 75로 물러남), `timeout` 아래서 `tools/box.sh`의 로컬 모드로 명령 실행, 모든 종료 경로에서 hold 내리기. 호출이 TERM을 받으면 Spark 쪽 실행을 그 hold에 적힌 pid로 멈춘다.

box.sh를 `BLOOMERY_BOX=spark`로 직접 쓰지 않는 이유: 그 원격 경로는 박스의 것이다(`/root/bloomery-cpu.lock`을 만들어 Spark를 "박스"로 표시하고, 3090·A6000을 이름으로 고른다). 로컬 모드는 한 카드와 자기 락 디렉터리라는 Spark의 모양이지만 ssh·rsync가 없다. 그래서 rsync를 앞에 붙인 얇은 래퍼다. box.sh는 바뀌지 않았다.

## 이 기계에 깔린 것(2026-11-04)

`spark-box.sh --setup`이 만든다. 전부 우리 디렉터리이고 `/opt/build`에는 쓰지 않는다.

| 무엇 | 어디 | 근거 |
|---|---|---|
| 환경 파일 | `/root/bloomery-env.sh`(`configs/spark/bloomery-env.sh`) | box.sh 로컬 모드가 읽는다 |
| Rust 1.99.1 | `~/.rustup`(트리의 `rust-toolchain.toml`) | 기계에 이미 있었다 |
| CUDA 13.3.1 툴킷 | `/root/bloomery-cuda/cuda-13.3.1` | `nvidia/cuda:13.3.1-devel-ubuntu24.04` 이미지에서 복사. 호스트의 13.0 헤더로는 bindgen이 `cuGraphNodeGetParams`에서 E0425로 끝난다 |
| LLVM 21.1.8 | `/opt/build/llvm-21.1.8`(벤치 세션이 푼 것, 읽기만) | `llc` sha256 `7c7bdaa6…5039`, `LLVM version 21.1.8` |
| cargo-oxide 0.2.1, 패치된 백엔드 | `~/.cargo/cuda-oxide-bloomery/9df9e7cef561…/` | 핀 rev `9df9e7ce`, 패치 sha256 `31ab6a1d…`(벤치의 `/opt/build/cargo-home` 백엔드와 같은 rev·같은 패치) |
| 트리와 아카이브 | `/root/bloomery-gb10`(`target/release-dist`) | |
| 락 | `/root/bloomery-locks` | 로컬 모드의 `BLOOMERY_LOCK_DIR`. `/root`는 박스의 표식이라 쓰지 않는다 |

## 측정(11-04, 한 번)

`build.sh --stage w 0.3.13 0190b04b63e6`을 `spark-box.sh`로: 06:11:51 시작, 아카이브 파일 06:13:59, 2분 8초 — cargo 1분 36초, 큐빈 링크(`oxart_jit`, 카드) 24초, 나머지 검사와 패킹. 의존성은 직전 실패 시도(툴킷 13.0 헤더에서 bindgen 오류, 45초)가 이미 컴파일해 둔 상태라 완전한 콜드는 그 45초를 더한다. 아카이브 24,247,174 바이트. 예측은 5분(3–10분)이었고 틀린 항은 큐빈 링크다(교차 빌드의 JIT 첫 로드 118.7초에서 60–180초로 짚었으나 24초). 같은 아카이브의 `bloomery-serve`가 Qwen3.6-35B-A3B UD-Q4_K_M을 `load … in 8.2 s`로 읽고 시작 10초 만에 `/health`가 열렸다(교차 빌드의 JIT 첫 시작 118.7초와 다르다).
