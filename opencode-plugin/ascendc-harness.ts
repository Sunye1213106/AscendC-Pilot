/**
 * AscendC Harness OpenCode plugin.
 *
 * Install: copy this file to ~/.config/opencode/plugins/ascendc-harness.ts
 * Does NOT merge or rewrite the user's opencode.json.
 *
 * Intercepts bash/write/edit/apply_patch/task before execution and asks
 * `harness authorize` with project, real agent, and action.
 * Soft control plane only — not OS-level security.
 *
 * Platform limits: OpenCode may not expose subagent identity on every hook;
 * receipts are issued only by `harness run-action <action_id> --finalize`.
 */

import { spawnSync } from "node:child_process"
import { existsSync } from "node:fs"
import { resolve } from "node:path"

type AuthorizeResult = {
  ok?: boolean
  decision?: string
  reason_zh?: string
  reason_code?: string
}

function detectProjectRoot(): string {
  const fromEnv =
    process.env.ASCENDC_PROJECT_ROOT ||
    process.env.OPENCODE_PROJECT_ROOT ||
    process.env.PROJECT_ROOT ||
    ""
  if (fromEnv && existsSync(fromEnv)) return fromEnv
  // Walk up from cwd looking for .ascendc-agent or repo markers
  let cur = process.cwd()
  for (let i = 0; i < 8; i++) {
    if (
      existsSync(resolve(cur, ".ascendc-agent")) ||
      existsSync(resolve(cur, "harness")) ||
      existsSync(resolve(cur, ".git"))
    ) {
      return cur
    }
    const parent = resolve(cur, "..")
    if (parent === cur) break
    cur = parent
  }
  return process.cwd()
}

function resolveAgent(input: { agent?: string; sessionAgent?: string }): string {
  const fromEnv = process.env.ASCENDC_AGENT || process.env.OPENCODE_AGENT || ""
  const fromInput = input.agent || input.sessionAgent || ""
  return String(fromEnv || fromInput || "ascendc-agent").trim()
}

function resolveAction(args: Record<string, unknown>): string {
  return String(
    process.env.ASCENDC_ACTION ||
      args.action ||
      args.action_id ||
      args.actionId ||
      "",
  ).trim()
}

function runAuthorize(args: {
  tool: string
  command?: string
  path?: string
  agent?: string
  action?: string
  project?: string
}): AuthorizeResult {
  const project = args.project || detectProjectRoot()
  const argv = [
    "authorize",
    "--project",
    project,
    "--tool",
    args.tool,
    "--command",
    args.command ?? "",
    "--path",
    args.path ?? "",
    "--agent",
    args.agent ?? "ascendc-agent",
    "--action",
    args.action ?? "",
  ]
  const result = spawnSync("harness", argv, {
    encoding: "utf-8",
    shell: true,
    windowsHide: true,
    cwd: project,
  })
  if (result.error || result.status === 127) {
    return { ok: false, decision: "ask", reason_code: "HARNESS_MISSING", reason_zh: "未找到 harness CLI" }
  }
  try {
    const text = (result.stdout || "").trim()
    const jsonStart = text.indexOf("{")
    if (jsonStart < 0) {
      return { ok: result.status === 0, decision: result.status === 0 ? "allow" : "deny" }
    }
    return JSON.parse(text.slice(jsonStart)) as AuthorizeResult
  } catch {
    return { ok: false, decision: "deny", reason_code: "AUTHORIZE_PARSE", reason_zh: "authorize 输出无法解析" }
  }
}

export const AscendCHarnessPlugin = async () => {
  return {
    "tool.execute.before": async (
      input: { tool?: string; agent?: string; sessionAgent?: string },
      output: { args?: Record<string, unknown> },
    ) => {
      const tool = String(input.tool || "").toLowerCase()
      const args = output.args || {}
      const command = String(args.command || args.cmd || "")
      const path = String(
        args.filePath || args.path || args.file || args.filepath || args.target || "",
      )
      const agent = resolveAgent(input)
      const action = resolveAction(args)
      const project = detectProjectRoot()
      const taskAgent = String(args.agent || args.subagent || args.name || path || "")

      if (tool === "bash" || tool === "shell" || tool === "terminal") {
        const verdict = runAuthorize({
          tool: "bash",
          command,
          agent,
          action,
          project,
        })
        if (verdict.decision === "deny" || (verdict.ok === false && verdict.decision !== "ask")) {
          throw new Error(
            `[ascendc-harness] blocked bash: ${verdict.reason_zh || verdict.reason_code || "denied"}`,
          )
        }
        if (verdict.decision === "ask") {
          if (!/^\s*harness(\s|$)/i.test(command)) {
            throw new Error(
              `[ascendc-harness] bash 仅允许 harness *：${verdict.reason_zh || ""}`.trim(),
            )
          }
        }
      }

      if (
        tool === "write" ||
        tool === "edit" ||
        tool === "apply_patch" ||
        tool === "strreplace" ||
        tool === "patch"
      ) {
        const verdict = runAuthorize({
          tool: tool === "apply_patch" || tool === "patch" ? "apply_patch" : "write",
          path,
          agent,
          action,
          project,
        })
        if (verdict.decision === "deny" || verdict.ok === false) {
          throw new Error(`[ascendc-harness] blocked write: ${verdict.reason_zh || path}`)
        }
      }

      if (tool === "task" || tool === "subagent" || tool === "task_tool") {
        const verdict = runAuthorize({
          tool: "task",
          path: taskAgent,
          command: taskAgent,
          agent,
          action,
          project,
        })
        if (verdict.decision === "deny" || verdict.ok === false) {
          throw new Error(
            `[ascendc-harness] blocked task: ${verdict.reason_zh || taskAgent || "denied"}`,
          )
        }
      }
    },
    "tool.execute.after": async () => {},
  }
}

export default AscendCHarnessPlugin
