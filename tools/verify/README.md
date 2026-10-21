# verify — bloomery 빌드 검증 스테이션 (round 1)

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

F 단계(두 번째 맥): 스테이션의 클론 하나(`station-f`)가 원격 클론이다. base 를
`refs/verify/<id>` 로 밀고, 원격에서 base 로 되돌린 뒤 패치를 씌우고 미추적 파일을
푼다. 그 위에 check(`cargo check --target x86_64-unknown-linux-gnu --all-targets` +
touched 패키지. 루트 `Cargo.toml`/`Cargo.lock`/`rust-toolchain.toml` 이 바뀌었으면
`--workspace`. gpu-gates 를 건드리면 트리의 justfile `check:` 레시피 feature 목록)와
test(`tools/recipes.py pure-crates` 에 든 touched 패키지만 `cargo test -p <pkg>`)를
돈다. 오류는 파일:줄 그대로, 원격 부하(uload)는 앞뒤로 한 줄씩. S/B 는 round 2
전까지 `phase S/B: not built yet (round 2)` 만 붙고 F 는 그대로 돈다.

가드: `guard-hook.py` 는 PreToolUse 훅이다. deny 는 종료 코드 0 +
`{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny",...}}`,
allow 은 출력 없음. 예외는 전부 allow 다(가드가 자기 때문에 일을 막지 않는다).
설정 `~/.config/bloomery/verify-guard`: `mode warn|deny|off` 줄 + `allow /abs/dir`
줄. 파일이 없으면 warn + 주 트리 허용. `VERIFY_GUARD_MODE` 가 mode 를 덮어쓴다.
opencode 라운드에는 PreToolUse 훅이 없다 → round 2 의 플러그인 전까지 가드가 없다.

자체 시험: `verify --self-test`(큐·스테이션·제출, 가짜 저장소 + ssh 스텁, 두 번째
맥 없음), `guard-hook.py --self-test`(51 행 표).

여기 있는 스크립트는 rig-log 공개 리포에 들어간다: 두 번째 맥의 호스트·사용자·홈
경로는 코드에 없다(`~/.config/bloomery/mac-remote` 에서 읽고 스크럽한다).
