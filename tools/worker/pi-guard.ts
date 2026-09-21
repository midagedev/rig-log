// pi-guard.ts — the `-e` extension a `pi` delegate round is launched with: a git write guard,
// a work-tree guard for file edits, and a loop brake. Pinned to @earendil-works/pi-coding-agent
// 0.86.1 (the `tool_call` return shape and `terminate` are from that line's docs/extensions.md).
//
// Written for round WORKER (2026-09-21) after both of its failure modes were measured against
// Qwen3-Coder-Next served locally:
//
//  1. A path guard that tests the raw `path` argument rejects every relative path. pi's write
//     tool is called with `path: "hello.py"`, not an absolute path, so a guard written as
//     `p.startsWith(root)` blocks the agent's own work tree. Resolve against cwd first.
//
//  2. **pi has no turn cap, and a blocked tool is not a stop signal to a weak model.** With the
//     git guard armed and a spec step that asked for `git status`, the model reissued the
//     identical blocked command **846 times** in one round without ever changing approach or
//     concluding — 851 tool executions, 848 of them bash, 849 blocked. The round only ended
//     because the launcher's watchdog killed it. A reason string the model can ignore is not a
//     brake, so after `REPEAT_LIMIT` identical blocks this returns `terminate: true`, which is
//     the documented way to stop the agent early, and it also caps total tool calls.
//
// The launcher still needs its own wall-clock watchdog: `terminate` ends the agent loop, not a
// model call that never returns.

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const REPEAT_LIMIT = 3; // identical blocked calls before the round is terminated
const TOOL_BUDGET = 60; // total tool calls in one round
const WORK_ROOT = process.env.PI_GUARD_WORK_ROOT ?? process.cwd();

const GIT_WRITE = /(^|[;&|(\s])git\s+(commit|push|add|checkout|stash|restore|reset|merge|rebase|tag|remote)\b/;
const GIT_ANY = /(^|[;&|(\s])git\b/;

export default function (pi: ExtensionAPI) {
  const blockCounts = new Map<string, number>();
  let toolCalls = 0;

  pi.on("tool_call", async (event) => {
    toolCalls++;
    if (toolCalls > TOOL_BUDGET) {
      return {
        block: true,
        terminate: true,
        reason: `outsource guard: tool-call budget of ${TOOL_BUDGET} exhausted; the round is over. Report what you completed.`,
      };
    }

    const deny = (key: string, reason: string) => {
      const n = (blockCounts.get(key) ?? 0) + 1;
      blockCounts.set(key, n);
      if (n >= REPEAT_LIMIT) {
        return {
          block: true,
          terminate: true,
          reason: `${reason} — you have now attempted this ${n} times. Stop retrying; the round ends here. Report what you completed and what you could not.`,
        };
      }
      return { block: true, reason: `${reason} (attempt ${n} of ${REPEAT_LIMIT})` };
    };

    if (event.toolName === "bash") {
      const cmd: string = (event.input as { command?: string }).command ?? "";
      if (GIT_WRITE.test(cmd)) {
        return deny(`git-write:${cmd}`, "outsource git guard: git write subcommands are forbidden in a delegate round");
      }
      if (GIT_ANY.test(cmd)) {
        return deny(`git-any:${cmd}`, "outsource git guard: this round may not run git at all");
      }
    }

    if (event.toolName === "write" || event.toolName === "edit") {
      const raw: string = (event.input as { path?: string }).path ?? "";
      // Relative paths are the common case from pi's own tools; resolve before testing.
      const abs = raw.startsWith("/") ? raw : `${WORK_ROOT.replace(/\/$/, "")}/${raw}`;
      const norm = abs.replace(/\/\.\//g, "/");
      if (norm.includes("/../") || !norm.startsWith(WORK_ROOT.replace(/\/$/, "") + "/")) {
        return deny(
          `path:${raw}`,
          `outsource file guard: edits are confined to ${WORK_ROOT} (asked for ${raw})`,
        );
      }
    }

    return undefined;
  });
}
