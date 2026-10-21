# opencode-guard — opencode 라운드의 빌드 가드

opencode 에는 PreToolUse 훅이 없다. `verify-guard.js` 가 그 자리를 채운다:
`tool.execute.before` 훅이 명령을 rig-log 의 `tools/verify/guard-hook.py` 에 물어보고,
거부가 돌아오면 예외를 던져 그 도구 호출이 실행되지 않게 한다. 정책은 하나다
(claude-code 하네스가 쓰는 것과 같은 `guard-hook.py`).

## 설치 (이 라운드는 설치하지 않았다)

    cp <rig-log>/tools/verify/opencode-guard/verify-guard.js \
       ~/.config/opencode/plugin/verify-guard.js
    export VERIFY_GUARD_HOOK=<rig-log>/tools/verify/guard-hook.py

- opencode 는 설정 디렉터리의 `plugin/` 안의 `*.js`, `*.ts` 를 모두 읽는다. 라운드
  트리 안의 `<tree>/.opencode/plugin/` 에 두어도 된다.
- `VERIFY_GUARD_HOOK` 을 안 두면 플러그인은 자기 옆의 `../guard-hook.py` 를 찾는다.
  `tools/verify/` 안에 그대로 두는 복사본이라면 환경 변수가 필요 없다.
- 가드가 못 읽거나 죽으면 플러그인은 아무것도 막지 않는다(라운드를 자기 때문에
  막지 않는다).

## outsource 의 opencode 하네스에 관해 (리드가 고를 일)

outsource 의 opencode 러너는 `opencode run … --pure` 로 돈다. `--pure` 는 사용자의
외부 플러그인을 건너뛴다. 그래서 위 설치만으로는 outsource 의 opencode 라운드에
가드가 붙지 않는다. 선택지: `--pure` 를 떼거나(그 러너의 로그·플러그인 정책이
함께 느슨해진다), 하네스가 만드는 설정 디렉터리 안의 `plugin/` 에 플러그인을
복사하도록 launch 코드를 고친다(launch 코드는 outsource 저장소에 있다).
