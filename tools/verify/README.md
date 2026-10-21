# verify — bloomery 빌드 검증 스테이션 (round 2: fast · static · box)

라운드는 코드만 쓴다. 빌드·컴파일·검증은 한 곳에서, 페이즈별로 한다. 이 디렉터리는
그 기계 특수 코드다(rig-log 규율: 기계 특수 코드는 rig-log 에 있다).

    verify submit --tree DIR --base REV --phase fast|static|box [--gates "g1 g2"] [--label L]
    verify wait ID [--timeout S]     # 사건 대기(sleep 루프 아님)
    verify status                     # 큐를 한 줄씩
    verify station [--once]           # 큐를 처리한다

큐는 `~/.cache/bloomery/verify/` 아래다: `queue/<id>/{meta.json,patch.diff,untracked.tar,
claim}`, `results/<id>.md` 와 `results/<id>.rc` (.rc 가 완료 신호), `station.pid`.
`<id>` = `<YYYYMMDD>-<label>-<n>`. submit 은 git 을 읽기만 한다(모든 호출이
`git --no-optional-locks` — plain `git diff` 는 index 를 갱신한다): 패치는
`git diff --binary <base>`, 미추적(무시되지 않는) 파일은 tar. 결과는 임시 파일에
쓰고 rename 으로 올린다. 스테이션은 kqueue 로 큐 디렉터리를 지켜 새 항목을 깨운다.

## F 단계(fast, 두 번째 맥) — 요청 하나씩

스테이션의 클론 하나(`station-f`)가 원격 클론이다. base 를 `refs/verify/<id>` 로
밀고, 원격에서 base 로 되돌린 뒤 패치를 씌우고 미추적 파일을 푼다. 그 위에 check
(`cargo check --target x86_64-unknown-linux-gnu --all-targets` + touched 패키지. 루트
`Cargo.toml`/`Cargo.lock`/`rust-toolchain.toml` 이 바뀌었으면 `--workspace`. gpu-gates 를
건드리면 트리의 justfile `check:` 레시피 feature 목록)와 test(`tools/recipes.py pure-crates`
에 든 touched 패키지만 `cargo test -p <pkg>`)를 돈다. 오류는 파일:줄 그대로, 원격
부하(uload)는 앞뒤로 한 줄씩. F 는 static·box 요청에도 그대로 돈다.

## S 단계(static, 모아서) — mix 하나, 정적 단계 한 번

S 요청은 모두 한 mix 트리(bloomery base + 각 요청의 패치, 큐 순서)로 합쳐진다.
패치가 씌워지지 않는 요청은 **다음 mix 를 기다린다**: 그 이름으로 결과에 적히고
큐에 남는다(`.rc` 가 없다). 정적 단계는 mix 위에서 두 번째 맥에 **한 번** 돈다
(bloomery 자신의 `tools/mac-remote.sh --tree <mix> <base>` — 내부를 복사하지 않는다).

각 빨강 단계는 그 단계만 base + 그 요청 하나로 다시 돌려 귀속시킨다. base 만으로도
빨강이면 그건 **main 의 빨강**이다(이름으로 적는다). 입력 키(`tools/recipes.py
static-key`, bloomery 트리)가 읽는 파일을 그 요청이 하나도 건드리지 않았다면 그
단계는 그 요청의 빨강일 수 없다 → 다시 돌리지 않는다(**변하지 않은 요청은 0 비용**).
키가 없는 단계(키가 `-`)는 언제나 다시 돈다.

같은 mix(base 와 요청들의 패치가 같은 mix)는 두 번 돌지 않는다: mix 의 서명이
`logs/s-last.json` 에 남고, 같은 서명이면 정적 단계를 다시 돌리지 않는다. 다음 mix
를 기다리는 요청이 큐에 남아도 단계가 계속 돌지 않는다.

## B 단계(box, 모아서) — 게이트 합집합 한 번

요청들의 게이트 합집합(`--gates` 가 있으면 그것, 없으면 요청 트리에서
`just affected <base>`)이 **하나의** `tools/gate-batch.sh --tier fixture
--round-ledger` 로 돈다. 원격 디렉터리는 스테이션 것 하나
(`BLOOMERY_REMOTE=~/repo/bloomery-station-b`), 트리는 S 단계와 같은 mix 다.
빨강 게이트는 그 게이트만 base + 그 요청 하나로 다시 돌려 귀속시킨다.

**`gate-batch.sh --wait-hold` 는 배치의 GPU 홀드(`/root/bloomery-batch.gpuhold`)를
기다리지 않는다.** 그것은 타이밍 리스와 자리별 홀드만 본다. 그래서 스테이션이 배치를
직전에 그 홀드를 직접 본다: `BLOOMERY_BOX_READONLY=1 tools/box.sh 'test -e
/root/bloomery-batch.gpuhold'`, 60 초마다 한 번(사건 없이 폴링).

## 두 번째 맥의 디스크

`tools/mac-remote.sh` 는 트랙마다 `target/` 하나(8–14 GiB)를 두 번째 맥에 남기고
지우지 않는다. 108개가 쌓여 2026-10-21 에 디스크가 100 % 가 되었다(정적 단계가
ENOSPC 로 18 개 빨강처럼 보였다). 스테이션이 **S·F 실행 전에** 지운다: 12 시간 동안
건드려지지 않은 `target/` 중 락(`.lock-<track>`)이 없는 것. 스테이션의 클론
(`station-f`, `station-s`, `station-b`)은 절대 안 건드린다. 한 줄로 보고한다
(지운 트랙 수, 그 뒤의 빈 GiB).

## 가드

`guard-hook.py` 는 PreToolUse 훅이다. deny 는 종료 코드 0 +
`{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny",...}}`,
allow 은 출력 없음. 예외는 전부 allow 다(가드가 자기 때문에 일을 막지 않는다).
설정 `~/.config/bloomery/verify-guard`: `mode warn|deny|off` 줄 + `allow /abs/dir`
줄. 파일이 없으면 warn + 주 트리 허용. `VERIFY_GUARD_MODE` 가 mode 를 덮어쓴다.
outsource 의 claude-code 라운드는 `OUTSOURCE_BUILD_GUARD` 가 이름 붙인 명령을 git 가드
다음의 두 번째 PreToolUse 훅으로 단다(outsource 9507860): 이 기계에서는 그 값이
`guard-hook.sh` 의 경로다. opencode 라운드에는 PreToolUse 훅이 없다 → [`opencode-guard/`](opencode-guard/) 의
`tool.execute.before` 플러그인이 그 자리를 채운다(설치 방법은 그 README).

자체 시험: `verify --self-test`(큐·스테이션·제출과 S/B 단계, 가짜 저장소 + ssh
스텁, 두 번째 맥 없음), `python3 tools/verify/phases.py`(S/B 단계의 규칙들, 가짜
트리에 대한 가지치기 포함), `guard-hook.py --self-test`(52 행 표).

여기 있는 스크립트는 rig-log 공개 리포에 들어간다: 두 번째 맥의 호스트·사용자·홈
경로는 코드에 없다(`~/.config/bloomery/mac-remote` 에서 읽고 스크럽한다).
