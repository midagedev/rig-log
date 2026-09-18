# rig-log — agent context

한 워크스테이션의 빌드 로그, 측정한 것만. 이 기계 이야기는 여기서 시작한다. 기계 사실·서빙 설정·업스트림 전송 기록이 전부 이 트리에 있다.

## 이 리포의 용도

둘, 두 번째를 잊기 쉽다.

1. **이 하드웨어로 실제로 무엇을 할 수 있는지 잰다** — 대규모 언어 모델 먼저, 그 다음 영상·이미지·오디오. 모든 기록에 실행한 명령줄, 측정한 처리량, 틀렸던 점이 들어간다.
2. **업스트림 기여를 찾아 보낸다.** 미출시 모델을 맞지 않는 하드웨어에서 돌리면 남의 테스트 안 된 경로를 밟는다. 실행이 깨지면 "어떻게 비껴가는가"뿐 아니라 "남이 밟을 버그인가, 보고 가능한가"를 묻는다. 최소 재현자가 있는 크래시가 검증 불가한 우회보다 낫다. 방법은 [`docs/upstream-contributions.md`](docs/upstream-contributions.md), 기록은 그 파일의 표다.

공통 규율: **이 리포의 주장은 이 기계에서, 명시된 날짜에 측정된 것이다.** 도출값이면 도출됐다고 밝힌다. 틀리면 지우지 않고 선을 그어 정정한다. 조용히 고쳐 쓰는 로그는 가치가 없다.

## 기계

사실·접속 경로·보드 gotcha는 [`README.md`](README.md)가 정본이다. 최신으로 유지한다.

비공개 운영 상세(호스트명, systemd 유닛, BIOS 할 일, 대시보드)는 `~/repo-mid/vps-infra/hosts/ws.md`와 `hosts/ws-llm-serving.md`에 있고 **공개가 아니다.** 그 파일 내용을 verbatim으로 복사하지 않는다. 이 리포는 기계를 하드웨어로만 부르고 tailnet 이름·주소를 안 쓴다.

접속은 Tailscale 경유. OpenAI 호환 API를 loopback에서 서빙, tailnet에 공개. `llm.service`가 GPU 둘을 쥐니 VRAM 작업은 중단부터 시작하고, 끝나면 다시 켜고 속도가 돌아왔는지 확인한다.

## 추적

작업은 셀프호스트 트래커 **WKS** 프로젝트(`gadak --workspace gdk`). 이슈를 넘는 발견은 `GDK` 공간 위키 페이지에 쓰고 이슈에서 URL로 건다. `TODO.md`를 열지 않는다. **실험은 라벨 `experiment`** — 실험당 이슈 하나에 지금까지 잰 상태와 무엇을 재면 끝나는지를 적는다. 실험 큐는 [`docs/v41-experiment-plan.md`](docs/v41-experiment-plan.md)에 있고 이슈와 같은 말을 한다. Mac의 PATH `gadak`은 홈이 `~/.gadak-dev`인 dev 빌드라 `gdk` 워크스페이스는 `GADAK_HOME=$HOME/.gadak`이 필요하다.

gadak 자체 마찰은 **GDK** 보드에 별도 이슈로, 명령과 실제 출력과 함께 — 우회가 증거를 없앤다.

## Layout

```
log/        실험당 한 파일, 날짜순. 측정한 기록
docs/       긴 글: 업스트림 버그 서류, 방법, 하드웨어 노트
configs/    기계에서 실제로 돌아가는 스크립트, 그대로 복사
tools/      기록 수단: VHS 테이프와 구동 스크립트
assets/     클립과 시트
```

## 관례

- **발견은 산문으로, 불릿 아님.** 무엇을 시도했고 숫자가 뭐였고 비용이 뭐였는지 문장으로 쓴다. 측정은 표, 추론은 문장.
- **실패를 포함한다.** 느려진 실행이 기록의 일부다. 이긴 구성만 보이는 기록은 광고다.
- **이 리포 안은 한국어** (2026-09-18 결정). ~~영어로 쓴다 — 공개 리포이고 업스트림 독자가 읽는다. 대화만 한국어.~~ 선 그음: 이 기계 기록의 1차 독자가 작성자 자신이고, 업스트림으로 나가는 것은 리포 전체가 아니라 특정 문서라는 것이 열흘치 기록으로 분명해졌다. 나가는 것은 계속 영어다 — 업스트림 이슈·PR 본문, 버그 보고, 업스트림이 읽을 코드 주석, 넓은 타임라인용 카드의 영문 절반. 경계는 [`docs/upstream-contributions.md`](docs/upstream-contributions.md)다: 업스트림으로 나간 본문은 영어로 두고, 이 리포 안에서 그것을 가리키는 서술은 한국어로 쓴다.
- **기계번역은 리드가 읽기 전까지 초안이다.** 구조 게이트가 못 보는 의미 변경이 천 단어당 1건 넘게 나온다. `tools/check-translation.py`와 `tools/check-glossary.py`를 먼저 돌려 스크립트가 가릴 것을 가리고, 나머지는 읽는다.
- **사설 주소·호스트명·비밀번호 금지.** 커밋 전 확인. 서빙 스크립트의 호스트는 일부러 일반화돼 있다. **테이프는 호스트명을 두 군데에 담고 있다**(`summary.server.host`, `summary.host.hostname`) — `assets/` 들어가기 전 `tools/tape-sanitize.py`, 커밋 전 `tools/check-tapes-sanitized.sh`. 측정한 적 있다: 박스에서 바로 복사한 테이프가 실명으로 커밋됐고 저자가 아니라 peer 세션이 잡았다.
- **클립 파일명은 녹화기 빌드지 속도가 아니다.** `<model>-<quant>-<what>-<toktape 버전>.mp4`. 파일명의 측정 숫자는 정정 불가라 산문에 둔다. 길이도 마찬가지다. 클립 업로드는 GPU 임대·작업 트리처럼 공유 자원 — 한 번에 한 세션이 소유하고 올린 것을 말한다.
- **클립을 짧게 하려면 프레임을 자른다, `--duration` 금지.** 그 플래그는 실행을 짧은 시간에 구겨 스톨을 가린다. `gifsicle --unoptimize <file> '#<start>-' -O3 -o <out>` 순서로 — `--unoptimize` 먼저가 필수다(GIF 인덱스는 저장 이미지지 초×fps가 아니라서).
- **리포를 나가는 모든 클립에 녹화기를 링크와 함께 밝힌다.** "recorded with [toktape](https://github.com/midagedev/toktape)". 클립은 도구의 광고이기도 하다.
- 시트 원본은 `assets/placement-sheet.html`, 1280×720에 재촬영. 파비콘·제목은 재배포에 고정.
- **toktape는 요구사항을 먹이는 형제 프로젝트다.** 손으로 모으는 증인이 필요해지면 로컬 우회가 아니라 toktape 세션에 직접 보낸다.
- **모델 파일은 [`tools/fetch-gguf.sh`](tools/fetch-gguf.sh)로 받는다.** 병렬 레인지 워커 + API에서 읽은 기대 크기 + 바이트 수 맞을 때만 최종 경로에 나타난다. 손 `curl` 금지. 로더 눈에 보이는 반쪽 `.gguf`가 막는 실패다.
- **`throttled` 플래그는 질문이지 발견이 아니다.**150 W나 300 W이나 전부 yes라 binding 캡과 스친 캡을 구분 못 한다. 예산을 빼앗아 묻는다. [`tools/ik/gpu-power-sweep.sh`](tools/ik/gpu-power-sweep.sh), 기본값은 모든 종료 경로에서 복원.
- **테이프 `Sampling` 행은 요청이지 답이 아니다.** `--no-think`는 `chat_template_kwargs`를 보내고, `--jinja` 없이 뜬 llama-server는 조용히 무시한다. 러너는 `--jinja`를 넘기고 [`tools/check-take-nothink.py`](tools/check-take-nothink.py)로 답이 요청에 어긋나는 take를 떨어뜨린다. 요청 파라미터를 믿기 전에 답을 읽는다.
- **벤치는 조용한 기계에서, "조용함"은 프로토콜이다.** 단일 임대 + loadavg가 아니라 IO 압력 + 매 행 증인 기록. 위임에는 지시가 아니라 러너 스크립트를 준다. 방법과 사고 경위는 [`docs/quiet-machine.md`](docs/quiet-machine.md).
