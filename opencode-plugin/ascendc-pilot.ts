/**
 * AscendC Pilot OpenCode plugin.
 *
 * Install: copy this file to ~/.config/opencode/plugins/ascendc-pilot.ts
 * Does NOT merge or rewrite the user's opencode.json.
 *
 * Intercepts bash/write/edit/apply_patch/task/read/glob/grep before execution and asks
 * `acp authorize` with project, real agent, and action.
 * Soft control plane only — not OS-level security.
 *
 * Platform limits: OpenCode may not expose subagent identity on every hook;
 * receipts are issued only by `acp run-action <action_id> --finalize`.
 *
 * Action context propagation:
 * 1. ASCENDC_ACTION env
 * 2. tool args action / action_id / actionId
 * 3. `.ascendc-pilot/state/active_action.yaml` written by acp prepare
 * On Task dispatch, injects action into args so child writes inherit it.
 */

import { spawnSync } from "node:child_process"
import { existsSync, readFileSync } from "node:fs"
import { resolve } from "node:path"

type AuthorizeResult = {
  ok?: boolean
  decision?: string
  reason_zh?: string
  reason?: string
  reason_code?: string
  error_code?: string
  allowed_actions?: string[]
}

function projectRootFromPath(pathHint: string): string {
  const norm = String(pathHint || "").replace(/\\/g, "/")
  if (!norm) return ""
  // …/<op>/.ascendc-pilot/uo/ir/foo.yaml → <op>
  const marker = "/.ascendc-pilot/"
  const idx = norm.toLowerCase().indexOf(marker)
  if (idx > 0) {
    const root = norm.slice(0, idx)
    if (existsSync(root)) return root
  }
  // Absolute Windows path may appear without leading slash quirks
  const idx2 = norm.toLowerCase().indexOf(".ascendc-pilot/")
  if (idx2 > 0) {
    let root = norm.slice(0, idx2).replace(/\/$/, "")
    if (root.endsWith(":")) return ""
    if (existsSync(root)) return root
  }
  return ""
}

function detectProjectRoot(pathHint?: string): string {
  const fromPath = projectRootFromPath(String(pathHint || ""))
  if (fromPath) return fromPath

  const fromEnv =
    process.env.ASCENDC_PROJECT_ROOT ||
    process.env.OPENCODE_PROJECT_ROOT ||
    process.env.PROJECT_ROOT ||
    ""
  if (fromEnv && existsSync(fromEnv)) return fromEnv

  // Prefer cwd when it looks like an operator package, even before acp start
  // creates `.ascendc-pilot`. Walking up to a parent `.ascendc-pilot` would otherwise
  // authorize against the wrong leftover run (e.g. ops-transformer vs op dir).
  const cwd = process.cwd()
  if (
    existsSync(resolve(cwd, "CMakeLists.txt")) ||
    existsSync(resolve(cwd, "op_kernel")) ||
    existsSync(resolve(cwd, "op_host"))
  ) {
    return cwd
  }

  // Walk up from cwd looking for .ascendc-pilot or repo markers
  let cur = cwd
  for (let i = 0; i < 8; i++) {
    if (
      existsSync(resolve(cur, ".ascendc-pilot")) ||
      existsSync(resolve(cur, "pilot")) ||
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
  return String(fromEnv || fromInput || "ascendc-pilot").trim()
}

/** Prefer declared producer actor when the hook mislabels the session as primary. */
function resolveEffectiveAgent(
  input: { agent?: string; sessionAgent?: string },
  active: { action_id?: string; actor_id?: string },
  tool: string,
): string {
  let agent = resolveAgent(input)
  const actor = String(active.actor_id || "").trim()
  if (!actor) return agent
  const isTask = tool === "task" || tool === "subagent" || tool === "task_tool"
  if (isTask) return agent
  if (!agent || agent === "ascendc-pilot" || agent === "ascendc_agent") {
    return actor
  }
  return agent
}

const PASS_THROUGH_AGENTS = new Set([
  "build",
  "plan",
  "general",
  "general-purpose",
  "generalpurpose",
  "ask",
  "debug",
])

const PILOT_AGENT_PREFIXES = ["uo-", "tg-", "deterministic-", "ce-"]

/** Pilot primary + declared UO/TG/CE actors. Build/Plan/unknown → pass-through. */
function isPilotFamilyAgent(agent: string): boolean {
  const a = String(agent || "")
    .trim()
    .toLowerCase()
  if (!a || a === "ascendc-pilot" || a === "ascendc_agent") return true
  if (PASS_THROUGH_AGENTS.has(a)) return false
  if (PILOT_AGENT_PREFIXES.some((p) => a.startsWith(p))) return true
  return false
}

/** Enforce harness only for Pilot-family agents (global plugin stays loaded). */
function shouldEnforceHarness(agent: string): boolean {
  return isPilotFamilyAgent(agent)
}

function readActiveAction(project: string): { action_id?: string; actor_id?: string } {
  const path = resolve(project, ".ascendc-pilot", "state", "active_action.yaml")
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

function resolveAcpBin(): string {
  const fromEnv = String(process.env.ASCENDC_HARNESS_BIN || "").trim()
  if (fromEnv && existsSync(fromEnv)) return fromEnv

  // Prefer PATH lookup without shell (Windows-safe argv).
  const probe = spawnSync(process.platform === "win32" ? "where" : "which", ["pilot"], {
    encoding: "utf-8",
    shell: false,
    windowsHide: true,
  })
  const first = String(probe.stdout || "")
    .split(/\r?\n/)
    .map((s) => s.trim())
    .find((s) => s && existsSync(s))
  if (first) return first

  // Common Windows pip user-script location
  if (process.platform === "win32") {
    const roaming = process.env.APPDATA || ""
    const local = process.env.LOCALAPPDATA || ""
    const candidates = [
      resolve(roaming, "Python", "Python313", "Scripts", "acp.exe"),
      resolve(roaming, "Python", "Python312", "Scripts", "acp.exe"),
      resolve(roaming, "Python", "Python311", "Scripts", "acp.exe"),
      resolve(local, "Programs", "Python", "Python313", "Scripts", "acp.exe"),
      resolve(local, "Programs", "Python", "Python312", "Scripts", "acp.exe"),
    ]
    for (const c of candidates) {
      if (existsSync(c)) return c
    }
  }
  return "pilot"
}

function runAuthorize(args: {
  tool: string
  command?: string
  path?: string
  agent?: string
  action?: string
  project?: string
  leaseId?: string
}): AuthorizeResult {
  const project = args.project || detectProjectRoot()
  // IMPORTANT (Windows):
  // 1) never pass empty optional flags (shell drops "" → argparse error)
  // 2) never use shell:true with argv arrays — Node concatenates unsafely and
  //    Windows cmd mangles --command values, so authorize always fails.
  const argv = ["authorize", "--project", project, "--tool", args.tool]
  const command = String(args.command ?? "").trim()
  if (command) {
    argv.push("--command", command)
  }
  const path = String(args.path ?? "").trim()
  if (path) {
    argv.push("--path", path)
  }
  const agent = String(args.agent || "ascendc-pilot").trim() || "ascendc-pilot"
  argv.push("--agent", agent)
  const action = String(args.action || "").trim()
  if (action) {
    argv.push("--action", action)
  }
  const leaseId = String(args.leaseId || "").trim()
  if (leaseId) {
    argv.push("--lease-id", leaseId)
  }

  const acpBin = resolveAcpBin()
  const result = spawnSync(acpBin, argv, {
    encoding: "utf-8",
    shell: false,
    windowsHide: true,
    cwd: project,
    env: {
      ...process.env,
      ASCENDC_ACTION: action || process.env.ASCENDC_ACTION || "",
      ASCENDC_AGENT: agent || process.env.ASCENDC_AGENT || "",
      ASCENDC_PROJECT_ROOT: project,
    },
  })
  if (result.error || result.status === 127) {
    return {
      ok: false,
      decision: "ask",
      reason_code: "HARNESS_MISSING",
      reason_zh: `未找到 acp CLI (${acpBin}): ${String(result.error || result.status)}`,
    }
  }
  try {
    const text = `${result.stdout || ""}\n${result.stderr || ""}`.trim()
    const jsonStart = text.indexOf("{")
    if (jsonStart < 0) {
      const errTail = (result.stderr || result.stdout || "").trim().slice(0, 240)
      return {
        ok: false,
        decision: "deny",
        reason_code: "AUTHORIZE_NO_JSON",
        reason_zh: errTail || `authorize exited ${result.status}`,
        error_code: "AUTHORIZE_NO_JSON",
      }
    }
    return JSON.parse(text.slice(jsonStart)) as AuthorizeResult
  } catch {
    return { ok: false, decision: "deny", reason_code: "AUTHORIZE_PARSE", reason_zh: "authorize 输出无法解析" }
  }
}

function denyMessage(verdict: AuthorizeResult, kind: string, detail: string): string {
  const code = verdict.error_code || verdict.reason_code || "HARNESS_ACTION_NOT_AUTHORIZED"
  const allowed = (verdict.allowed_actions || []).slice(0, 6).join(" | ")
  const base = `[ascendc-pilot] blocked ${kind}: ${verdict.reason_zh || verdict.reason || code || detail}`
  return allowed ? `${base} (allowed: ${allowed})` : base
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
        args.filePath ||
          args.path ||
          args.file ||
          args.filepath ||
          args.target ||
          args.pattern ||
          args.glob ||
          "",
      )
      const project = detectProjectRoot(path)
      const active = readActiveAction(project)
      let agent = resolveEffectiveAgent(input, active, tool)

      // Build / Plan / other non-Pilot tabs: behave like stock OpenCode.
      if (!shouldEnforceHarness(agent)) {
        return
      }

      const action = resolveAction(args, project)
      const taskAgent = String(
        args.agent ||
          args.subagent ||
          args.subagent_type ||
          args.subagentType ||
          args.name ||
          path ||
          "",
      )

      if (tool === "bash" || tool === "shell" || tool === "terminal") {
        // Always authorize — including acp CLI — so containment can revoke domain steps.
        const verdict = runAuthorize({
          tool: "bash",
          command,
          agent,
          action,
          project,
        })
        if (verdict.decision === "deny" || (verdict.ok === false && verdict.decision !== "ask")) {
          throw new Error(denyMessage(verdict, "bash", command))
        }
        if (verdict.decision === "ask") {
          throw new Error(
            `[ascendc-pilot] bash 仅允许 acp *：${verdict.reason_zh || ""}`.trim(),
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
          throw new Error(denyMessage(verdict, "write", path))
        }
      }

      if (tool === "read" || tool === "glob" || tool === "grep" || tool === "list" || tool === "search") {
        const verdict = runAuthorize({
          tool: tool === "list" || tool === "search" ? "glob" : tool,
          path,
          command: String(args.pattern || args.query || ""),
          agent,
          action,
          project,
        })
        if (verdict.decision === "deny" || verdict.ok === false) {
          throw new Error(denyMessage(verdict, tool, path))
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
          throw new Error(denyMessage(verdict, "task", taskAgent || "denied"))
        }
      }
    },
    "tool.execute.after": async () => {},
  }
}

export default AscendCHarnessPlugin
