// The verify guard as an opencode plugin: the `tool.execute.before` hook.
//
// opencode has no PreToolUse hook, so a round that runs on opencode had no guard.
// This plugin is that hook: it hands the command to the same guard-hook.py the
// claude-code harness uses, so there is one policy and not two.
//
// The hook denies by throwing: opencode reports the error and the tool call does
// not run. The guard's own failure (a missing python3, a broken guard) never
// blocks a round: the plugin returns and lets the tool through.
//
// Install (this round did NOT install it):
//   1) copy this file into opencode's plugin folder
//        cp <rig-log>/tools/verify/opencode-guard/verify-guard.js \
//           ~/.config/opencode/plugin/verify-guard.js
//      (opencode reads every *.js and *.ts in the plugin folder of its config
//      dir; a round's own dir can hold one too: <tree>/.opencode/plugin/)
//   2) point it at the guard, if the copy is not beside guard-hook.py
//        export VERIFY_GUARD_HOOK=<rig-log>/tools/verify/guard-hook.py
//      Without the variable the plugin looks for ../guard-hook.py next to
//      itself, so a copy that stays in tools/verify/ needs no environment.
//
// Caveat for the outsource opencode harness: it runs opencode with `--pure`,
// which skips the user's external plugins. Until that flag is dropped (or the
// plugin is put inside the harness's own config dir), an outsource opencode
// round has no guard either.

import { spawnSync } from "node:child_process"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"

const HERE = dirname(fileURLToPath(import.meta.url))

function guardPath() {
  return process.env.VERIFY_GUARD_HOOK || join(HERE, "..", "guard-hook.py")
}

function ask(command, cwd) {
  const payload = JSON.stringify({
    session_id: "opencode",
    cwd: cwd,
    hook_event_name: "PreToolUse",
    tool_name: "Bash",
    tool_input: { command },
    agent_type: "round",
  })
  const r = spawnSync("python3", [guardPath()], {
    input: payload,
    encoding: "utf8",
    timeout: 10000,
  })
  if (r.status !== 0 || !r.stdout) return null
  try {
    return JSON.parse(r.stdout)
  } catch {
    return null
  }
}

export const VerifyGuard = async ({ directory, worktree }) => {
  const cwd = directory || worktree || process.cwd()
  return {
    "tool.execute.before": async (input, output) => {
      if (input.tool !== "bash") return
      const command = output?.args?.command
      if (typeof command !== "string" || command.trim() === "") return
      const decision = ask(command, cwd)
      const hook = decision?.hookSpecificOutput
      if (!hook || hook.permissionDecision !== "deny") return
      throw new Error(hook.permissionDecisionReason || "verify 가드가 이 명령을 막았습니다")
    },
  }
}

export default VerifyGuard
