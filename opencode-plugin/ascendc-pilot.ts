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
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs"
import { homedir } from "node:os"
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

function lastProjectCachePath(): string {
  return resolve(homedir(), ".config", "opencode", "ascendc-last-project")
}

function rememberProjectRoot(project: string): void {
  const root = String(project || "").trim()
  if (!root || !existsSync(root)) return
  try {
    const cache = lastProjectCachePath()
    mkdirSync(resolve(homedir(), ".config", "opencode"), { recursive: true })
    writeFileSync(cache, root, "utf-8")
  } catch {
    // best-effort
  }
}

function readRememberedProjectRoot(): string {
  try {
    const cache = lastProjectCachePath()
    if (!existsSync(cache)) return ""
    const root = readFileSync(cache, "utf-8").trim()
    if (root && existsSync(resolve(root, ".ascendc-pilot", "state", "workflow.yaml"))) {
      return root
    }
  } catch {
    // ignore
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
  if (existsSync(resolve(cwd, ".ascendc-pilot", "state", "workflow.yaml"))) {
    return cwd
  }
  if (
    existsSync(resolve(cwd, "CMakeLists.txt")) ||
    existsSync(resolve(cwd, "op_kernel")) ||
    existsSync(resolve(cwd, "op_host"))
  ) {
    return cwd
  }

  // Walk up: prefer active Pilot workflow over bare .git / pilot repo root.
  let cur = cwd
  let foundGit = ""
  let foundPilotRepo = ""
  for (let i = 0; i < 8; i++) {
    if (existsSync(resolve(cur, ".ascendc-pilot", "state", "workflow.yaml"))) {
      return cur
    }
    if (!foundPilotRepo && existsSync(resolve(cur, "pilot")) && existsSync(resolve(cur, "engines"))) {
      foundPilotRepo = cur
    }
    if (!foundGit && existsSync(resolve(cur, ".git"))) {
      foundGit = cur
    }
    const parent = resolve(cur, "..")
    if (parent === cur) break
    cur = parent
  }

  const remembered = readRememberedProjectRoot()
  if (remembered) return remembered

  return foundPilotRepo || foundGit || process.cwd()
}

function detectProjectRootForTask(): string {
  // Task args often carry subagent names, not file paths — ignore path hints.
  const fromEnv =
    process.env.ASCENDC_PROJECT_ROOT ||
    process.env.OPENCODE_PROJECT_ROOT ||
    process.env.PROJECT_ROOT ||
    ""
  if (fromEnv && existsSync(resolve(fromEnv, ".ascendc-pilot", "state", "workflow.yaml"))) {
    return fromEnv
  }
  const cwd = process.cwd()
  if (existsSync(resolve(cwd, ".ascendc-pilot", "state", "workflow.yaml"))) {
    return cwd
  }
  const remembered = readRememberedProjectRoot()
  if (remembered) return remembered
  return detectProjectRoot()
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
  rememberProjectRoot(project)
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

/** Best-effort debug capture via `acp debug` (never throws). */
function runDebug(argvExtra: string[], project?: string): void {
  try {
    const root = project || detectProjectRoot() || readRememberedProjectRoot() || process.cwd()
    const acpBin = resolveAcpBin()
    spawnSync(acpBin, ["debug", ...argvExtra, "--project", root], {
      encoding: "utf-8",
      shell: false,
      windowsHide: true,
      cwd: root,
      env: { ...process.env, ASCENDC_PROJECT_ROOT: root },
      timeout: 45_000,
    })
  } catch {
    // fail-open
  }
}

/** Extract OpenCode Task child session id from tool output. */
function extractTaskSessionId(output: Record<string, unknown> | undefined): string {
  if (!output || typeof output !== "object") return ""
  const direct = [
    output.sessionId,
    output.sessionID,
    output.session_id,
    output.id,
    output.taskId,
    output.task_id,
  ]
  for (const v of direct) {
    if (typeof v === "string") {
      const m = v.match(/ses_[A-Za-z0-9]+/)
      if (m) return m[0]
    }
  }
  const meta = output.metadata
  if (meta && typeof meta === "object") {
    for (const k of ["sessionId", "sessionID", "session_id", "id", "taskId"] as const) {
      const v = (meta as Record<string, unknown>)[k]
      if (typeof v === "string") {
        const m = v.match(/ses_[A-Za-z0-9]+/)
        if (m) return m[0]
      }
    }
  }
  const chunks: string[] = []
  for (const k of ["output", "content", "title", "message", "text"] as const) {
    const v = output[k]
    if (typeof v === "string" && v.trim()) chunks.push(v)
  }
  const blob = chunks.join("\n")
  const attr = blob.match(/<task\s+[^>]*\bid=["'](ses_[A-Za-z0-9]+)["']/i)
  if (attr) return attr[1]
  const any = blob.match(/\b(ses_[A-Za-z0-9]{8,})\b/)
  return any ? any[1] : ""
}

function extractHostSessionId(input: Record<string, unknown>): string {
  for (const k of ["sessionID", "sessionId", "session_id"] as const) {
    const v = input[k]
    if (typeof v === "string") {
      const m = v.match(/ses_[A-Za-z0-9]+/)
      if (m) return m[0]
    }
  }
  return ""
}

function extractToolError(
  output: Record<string, unknown> | undefined,
  tool?: string,
): string {
  if (!output || typeof output !== "object") return ""
  const toolL = String(tool || "").toLowerCase()

  const exitRaw =
    output.exit ??
    output.exitCode ??
    output.code ??
    (output.metadata && typeof output.metadata === "object"
      ? (output.metadata as Record<string, unknown>).exit ??
        (output.metadata as Record<string, unknown>).exitCode ??
        (output.metadata as Record<string, unknown>).code
      : undefined)
  const exitCode = typeof exitRaw === "number" ? exitRaw : Number.NaN

  const chunks: string[] = []
  for (const k of ["error", "message", "stderr", "output", "content", "title"] as const) {
    const v = output[k]
    if (typeof v === "string" && v.trim()) chunks.push(v)
  }
  const meta = output.metadata
  if (meta && typeof meta === "object") {
    const err = (meta as Record<string, unknown>).error
    if (typeof err === "string" && err.trim()) chunks.push(err)
  }
  const text = chunks.join("\n")

  // Successful Read dumps must never be treated as failures.
  if (
    (toolL === "read" || /<path>[\s\S]*<\/path>\s*<type>\s*file\s*<\/type>/i.test(text)) &&
    !/"ok"\s*:\s*false/i.test(text) &&
    !/SchemaError|invalid arguments/i.test(text)
  ) {
    return ""
  }

  if (!Number.isNaN(exitCode) && exitCode !== 0) {
    return (text || `exit_code=${exitCode}`).slice(0, 2000)
  }
  if (/SchemaError|invalid arguments|Missing key/i.test(text)) {
    return text.slice(0, 2000)
  }
  if (
    /\[ascendc-pilot\]\s*blocked|HARNESS_ACTION_NOT_AUTHORIZED|PRIMARY_PROTECTED_WRITE/i.test(
      text,
    )
  ) {
    return text.slice(0, 2000)
  }

  // Structured acp failure: first ok:false before any ok:true
  const falseIdx = (() => {
    const a = text.indexOf('"ok": false')
    const b = text.indexOf('"ok":false')
    if (a < 0) return b
    if (b < 0) return a
    return Math.min(a, b)
  })()
  const trueIdx = (() => {
    const a = text.indexOf('"ok": true')
    const b = text.indexOf('"ok":true')
    if (a < 0) return b
    if (b < 0) return a
    return Math.min(a, b)
  })()
  if (falseIdx >= 0 && (trueIdx < 0 || falseIdx < trueIdx)) {
    return text.slice(0, 2000)
  }

  // Bare Error:/Exception envelopes (not file content)
  if (/^(Error|ERROR|Exception|Traceback)\b/m.test(text.trim())) {
    return text.slice(0, 2000)
  }

  return ""
}

/** OpenCode todowrite requires priority; inject when Host forgot. */
function ensureTodowritePriority(args: Record<string, unknown>): void {
  const todos = args.todos
  if (!Array.isArray(todos)) return
  for (const item of todos) {
    if (!item || typeof item !== "object") continue
    const row = item as Record<string, unknown>
    if (row.priority != null && String(row.priority).trim()) continue
    const st = String(row.status || "pending").toLowerCase()
    row.priority = st === "in_progress" ? "high" : st === "completed" ? "low" : "medium"
  }
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
      const isTaskTool = tool === "task" || tool === "subagent" || tool === "task_tool"
      const project = isTaskTool ? detectProjectRootForTask() : detectProjectRoot(path)
      if (project) rememberProjectRoot(project)
      const active = readActiveAction(project)
      let agent = resolveEffectiveAgent(input, active, tool)

      // OpenCode todowrite schema requires priority — inject when Host omitted it.
      if (tool === "todowrite" || tool === "todo_write" || (tool.includes("todo") && tool.includes("write"))) {
        ensureTodowritePriority(args)
      }

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
        const hostSession = extractHostSessionId(input as Record<string, unknown>)
        const promptText = String(args.prompt || args.description || args.task || "")
        if (hostSession) {
          runDebug(
            [
              "register-child",
              "--if-enabled",
              "--parent-session-id",
              hostSession,
              "--action-id",
              dispatchAction,
              "--actor-id",
              dispatchActor,
              "--task-prompt",
              promptText.slice(0, 4000),
            ],
            project,
          )
        }
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
    "tool.execute.after": async (
      input: { tool?: string; agent?: string; sessionAgent?: string; sessionID?: string; sessionId?: string },
      output: Record<string, unknown> | undefined,
    ) => {
      try {
        const tool = String(input.tool || "").toLowerCase()
        const args = (output && typeof output.args === "object" ? output.args : {}) as Record<
          string,
          unknown
        >
        const path = String(
          args.filePath || args.path || args.file || args.filepath || args.target || "",
        )
        const isTaskTool = tool === "task" || tool === "subagent" || tool === "task_tool"
        const project = isTaskTool ? detectProjectRootForTask() : detectProjectRoot(path)
        if (project) rememberProjectRoot(project)

        const err = extractToolError(output, tool)
        if (err) {
          runDebug(
            [
              "record-tool-failure",
              "--tool",
              tool || "unknown",
              "--error",
              err.slice(0, 1500),
            ],
            project,
          )
        }

        const hostSession = extractHostSessionId(input as Record<string, unknown>)
        const active = readActiveAction(project || "")
        const actionId = String(active.action_id || "")
        const auditTools = new Set([
          "read",
          "grep",
          "glob",
          "write",
          "edit",
          "apply_patch",
          "strreplace",
          "patch",
          "search",
          "list",
        ])
        if (auditTools.has(tool)) {
          const pattern = String(args.pattern || args.query || "")
          runDebug(
            [
              "record-tool-event",
              "--if-enabled",
              "--tool",
              tool,
              "--parent-session-id",
              hostSession,
              "--action-id",
              actionId,
              "--path",
              path.slice(0, 500),
              "--pattern",
              pattern.slice(0, 500),
              ...(err ? ["--failed"] : []),
            ],
            project,
          )
        }

        // Subagent (Task) finished → patch child id + export child bundle when debug enabled.
        if (isTaskTool) {
          const sub =
            String(
              args.agent ||
                args.subagent ||
                args.subagent_type ||
                args.subagentType ||
                args.name ||
                "",
            ) || "task"
          const childSession = extractTaskSessionId(output)
          const dispatchAction = actionId
          if (childSession) {
            runDebug(
              [
                "patch-child-session",
                "--child-session-id",
                childSession,
                "--parent-session-id",
                hostSession,
                "--action-id",
                dispatchAction,
              ],
              project,
            )
            runDebug(
              [
                "export-child-session",
                "--if-enabled",
                "--reason",
                "subagent_stop",
                "--subagent",
                sub,
                "--child-session-id",
                childSession,
              ],
              project,
            )
          }
        }
      } catch {
        // fail-open
      }
    },
  }
}

export default AscendCHarnessPlugin
