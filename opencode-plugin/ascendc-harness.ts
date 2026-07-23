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
 *
 * Action context propagation:
 * 1. ASCENDC_ACTION env
 * 2. tool args action / action_id / actionId
 * 3. `.ascendc-agent/state/active_action.yaml` written by harness prepare
 * On Task dispatch, injects action into args so child writes inherit it.
 */

import { spawnSync } from "node:child_process"
import { existsSync, readFileSync } from "node:fs"
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

function readActiveAction(project: string): { action_id?: string; actor_id?: string } {
  const path = resolve(project, ".ascendc-agent", "state", "active_action.yaml")
  if (!existsSync(path)) return {}
  try {
    const text = readFileSync(path, "utf-8")
    const actionMatch = text.match(/^\s*action_id:\s*["']?([^\s"'#]+)/m)
    const actorMatch = text.match(/^\s*actor_id:\s*["']?([^\s"'#]+)/m)
    return {
      action_id: actionMatch?.[1]?.trim() || "",
      actor_id: actorMatch?.[1]?.trim() || "",
    }
  } catch {
    return {}
  }
}

function resolveAction(args: Record<string, unknown>, project: string): string {
  const fromArgs = String(
    args.action || args.action_id || args.actionId || "",
  ).trim()
  if (fromArgs) return fromArgs
  const fromEnv = String(process.env.ASCENDC_ACTION || "").trim()
  if (fromEnv) return fromEnv
  const active = readActiveAction(project)
  return String(active.action_id || "").trim()
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
  ]
  // Windows shell drops empty args; never pass bare `--action` without a value.
  const action = String(args.action || "").trim()
  if (action) {
    argv.push("--action", action)
  }
  const result = spawnSync("harness", argv, {
    encoding: "utf-8",
    shell: true,
    windowsHide: true,
    cwd: project,
    env: {
      ...process.env,
      ASCENDC_ACTION: action || process.env.ASCENDC_ACTION || "",
      ASCENDC_AGENT: args.agent || process.env.ASCENDC_AGENT || "",
      ASCENDC_PROJECT_ROOT: project,
    },
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

function isHarnessCli(command: string): boolean {
  // Allow harness and python -m ascendc_harness; ignore trailing redirections.
  const cleaned = String(command || "")
    .replace(/[|&><].*$/, "")
    .trim()
  return /^\s*harness(\s|$)/i.test(cleaned) || /^\s*python(?:3)?\s+-m\s+ascendc_harness(\s|$)/i.test(cleaned)
}

function injectActionContext(
  args: Record<string, unknown>,
  action: string,
  actor?: string,
): void {
  if (!action) return
  // Ensure subsequent authorize/resolvers see action without relying on LLM memory.
  if (!args.action && !args.action_id && !args.actionId) {
    args.action = action
    args.action_id = action
  }
  const prompt = String(args.prompt || args.description || args.task || "")
  if (prompt && !/ASCENDC_ACTION|action_id\s*=/.test(prompt)) {
    const prefix =
      `[ASCENDC_ACTION=${action}` +
      (actor ? `; ASCENDC_AGENT=${actor}` : "") +
      `] 正式写入必须携带 action_id=${action}。\n\n`
    if (args.prompt != null) args.prompt = prefix + String(args.prompt)
    else if (args.description != null) args.description = prefix + String(args.description)
    else if (args.task != null) args.task = prefix + String(args.task)
  }
  // Common OpenCode task env bags
  const envBag = (args.env || args.environment || args.envVars) as Record<string, string> | undefined
  if (envBag && typeof envBag === "object") {
    envBag.ASCENDC_ACTION = action
    if (actor) envBag.ASCENDC_AGENT = actor
  } else {
    args.env = {
      ASCENDC_ACTION: action,
      ...(actor ? { ASCENDC_AGENT: actor } : {}),
    }
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
      const project = detectProjectRoot()
      const active = readActiveAction(project)
      let agent = resolveAgent(input)
      // When subagent hooks omit identity, fall back to prepared actor.
      if (
        (!agent || agent === "ascendc-agent") &&
        active.actor_id &&
        tool !== "task" &&
        tool !== "subagent" &&
        tool !== "task_tool"
      ) {
        agent = active.actor_id
      }
      const action = resolveAction(args, project)
      const taskAgent = String(args.agent || args.subagent || args.name || path || "")

      if (tool === "bash" || tool === "shell" || tool === "terminal") {
        // harness CLI is always allowed (control plane). Do not depend on authorize
        // succeeding first — empty --action used to break authorize on Windows.
        if (isHarnessCli(command)) {
          return
        }
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
          throw new Error(
            `[ascendc-harness] bash 仅允许 harness *：${verdict.reason_zh || ""}`.trim(),
          )
        }
      }

      if (
        tool === "write" ||
        tool === "edit" ||
        tool === "apply_patch" ||
        tool === "strreplace" ||
        tool === "patch"
      ) {
        // Propagate action onto write args for receipt/audit trail
        if (action && !args.action && !args.action_id) {
          args.action = action
          args.action_id = action
        }
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
        const dispatchAction = action || String(active.action_id || "")
        const dispatchActor = taskAgent || String(active.actor_id || "")
        injectActionContext(args, dispatchAction, dispatchActor)
        const verdict = runAuthorize({
          tool: "task",
          path: taskAgent,
          command: taskAgent,
          agent,
          action: dispatchAction,
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
