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

function isPilotProjectRoot(root: string): boolean {
  const r = String(root || "").trim()
  if (!r) return false
  return existsSync(resolve(r, ".ascendc-pilot", "state", "workflow.yaml"))
}

function lastProjectCachePath(): string {
  return resolve(homedir(), ".config", "opencode", "ascendc-last-project")
}

function rememberProjectRoot(project: string): void {
  const root = String(project || "").trim()
  // Never cache workspace/git parents that are not a live Pilot project — that
  // poisons Task dispatch when OpenCode cwd is D:\TEST (or similar).
  if (!root || !isPilotProjectRoot(root)) return
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
    if (root && isPilotProjectRoot(root)) {
      return root
    }
  } catch {
    // ignore
  }
  return ""
}

function detectProjectRoot(pathHint?: string): string {
  const fromPath = projectRootFromPath(String(pathHint || ""))
  if (fromPath && isPilotProjectRoot(fromPath)) return fromPath
  // Operator package path before acp start (has op_kernel etc., no workflow yet).
  if (fromPath && existsSync(fromPath)) return fromPath

  const fromEnv =
    process.env.ASCENDC_PROJECT_ROOT ||
    process.env.OPENCODE_PROJECT_ROOT ||
    process.env.PROJECT_ROOT ||
    ""
  if (fromEnv && existsSync(fromEnv)) {
    if (isPilotProjectRoot(fromEnv)) return fromEnv
  }

  // Prefer cwd when it looks like an operator package, even before acp start
  // creates `.ascendc-pilot`. Walking up to a parent `.ascendc-pilot` would otherwise
  // authorize against the wrong leftover run (e.g. ops-transformer vs op dir).
  const cwd = process.cwd()
  if (isPilotProjectRoot(cwd)) {
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
  for (let i = 0; i < 8; i++) {
    if (isPilotProjectRoot(cur)) {
      return cur
    }
    const parent = resolve(cur, "..")
    if (parent === cur) break
    cur = parent
  }

  const remembered = readRememberedProjectRoot()
  if (remembered) return remembered

  // Do NOT fall back to bare .git / AscendC-Pilot repo — those authorize as a
  // fake project with empty phase actors and block Task (ses_062d).
  return fromEnv && existsSync(fromEnv) ? fromEnv : process.cwd()
}

function detectProjectRootForTask(promptHint?: string): string {
  // Task args carry subagent names, not file paths. Prefer paths embedded in the
  // prepare stub (…/<op>/.ascendc-pilot/runs/.../actions/extract_plan/...).
  const fromPrompt = projectRootFromPath(String(promptHint || ""))
  if (fromPrompt && isPilotProjectRoot(fromPrompt)) {
    return fromPrompt
  }

  const fromEnv =
    process.env.ASCENDC_PROJECT_ROOT ||
    process.env.OPENCODE_PROJECT_ROOT ||
    process.env.PROJECT_ROOT ||
    ""
  if (fromEnv && isPilotProjectRoot(fromEnv)) {
    return fromEnv
  }
  const cwd = process.cwd()
  if (isPilotProjectRoot(cwd)) {
    return cwd
  }
  const remembered = readRememberedProjectRoot()
  if (remembered) return remembered
  // Last resort: still try prompt even without workflow (pre-start edge).
  if (fromPrompt && existsSync(fromPrompt)) return fromPrompt
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

function harnessBinCachePath(): string {
  return resolve(homedir(), ".config", "opencode", "ascendc-harness-bin")
}

function resolveAcpBin(): string {
  const fromEnv = String(process.env.ASCENDC_HARNESS_BIN || "").trim()
  if (fromEnv && existsSync(fromEnv)) return fromEnv

  // Written by install.ps1 / install.sh after pip installs the console script.
  try {
    const cached = readFileSync(harnessBinCachePath(), "utf-8").trim()
    if (cached && existsSync(cached)) return cached
  } catch {
    // ignore
  }

  const exeName = process.platform === "win32" ? "acp.exe" : "acp"

  // Prefer PATH lookup without shell (Windows-safe argv).
  // Note: OpenCode's Node process may have a thinner PATH than the user shell.
  const probe = spawnSync(process.platform === "win32" ? "where" : "which", ["acp"], {
    encoding: "utf-8",
    shell: false,
    windowsHide: true,
  })
  const first = String(probe.stdout || "")
    .split(/\r?\n/)
    .map((s) => s.trim())
    .find((s) => s && existsSync(s))
  if (first) return first

  // Scan PATH directories directly (covers cases where `where` is unavailable).
  const pathEnv = process.env.PATH || process.env.Path || ""
  const pathSep = process.platform === "win32" ? ";" : ":"
  for (const dir of pathEnv.split(pathSep)) {
    const trimmed = dir.trim()
    if (!trimmed) continue
    const candidate = resolve(trimmed, exeName)
    if (existsSync(candidate)) return candidate
  }

  // Common Windows install locations (pip --user, conda/miniconda, store Python).
  if (process.platform === "win32") {
    const roaming = process.env.APPDATA || ""
    const local = process.env.LOCALAPPDATA || ""
    const home = process.env.USERPROFILE || ""
    const conda = process.env.CONDA_PREFIX || ""
    const candidates = [
      conda ? resolve(conda, "Scripts", "acp.exe") : "",
      resolve(roaming, "Python", "Python313", "Scripts", "acp.exe"),
      resolve(roaming, "Python", "Python312", "Scripts", "acp.exe"),
      resolve(roaming, "Python", "Python311", "Scripts", "acp.exe"),
      resolve(local, "Programs", "Python", "Python313", "Scripts", "acp.exe"),
      resolve(local, "Programs", "Python", "Python312", "Scripts", "acp.exe"),
      resolve(local, "miniconda3", "Scripts", "acp.exe"),
      resolve(local, "anaconda3", "Scripts", "acp.exe"),
      resolve(home, "miniconda3", "Scripts", "acp.exe"),
      resolve(home, "anaconda3", "Scripts", "acp.exe"),
      "C:\\ProgramData\\miniconda3\\Scripts\\acp.exe",
      "C:\\ProgramData\\anaconda3\\Scripts\\acp.exe",
    ]
    for (const c of candidates) {
      if (c && existsSync(c)) return c
    }
  }
  return "acp"
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

/** Pending Task registrations keyed by stable invocation id or dispatch_nonce. */
const pendingTaskRegs = new Map<
  string,
  { registration_id: string; dispatch_nonce: string; action_id: string; parent_session_id: string }
>()

/** Local child→parent relationship registry (mirrors Python children registry). */
const childSessionRegistry = new Map<
  string,
  {
    parent_session_id: string
    registration_id: string
    dispatch_nonce: string
    run_id: string
    action_id: string
  }
>()

type DebugRunResult = {
  ok: boolean
  skipped?: boolean
  payload?: Record<string, unknown>
  exit_code: number
  stdout: string
  stderr: string
}

/** Best-effort debug capture via `acp debug`. Checks exit/JSON; records anomaly on failure. */
function runDebug(argvExtra: string[], project?: string): DebugRunResult {
  const root = project || detectProjectRoot() || readRememberedProjectRoot() || process.cwd()
  try {
    const acpBin = resolveAcpBin()
    const res = spawnSync(acpBin, ["debug", ...argvExtra, "--project", root], {
      encoding: "utf-8",
      shell: false,
      windowsHide: true,
      cwd: root,
      env: { ...process.env, ASCENDC_PROJECT_ROOT: root },
      timeout: 45_000,
    })
    const exitCode = typeof res.status === "number" ? res.status : 1
    const stdout = String(res.stdout || "")
    const stderr = String(res.stderr || "")
    let payload: Record<string, unknown> | undefined
    let jsonOk: boolean | null = null
    try {
      const trimmed = stdout.trim()
      if (trimmed.startsWith("{")) {
        payload = JSON.parse(trimmed) as Record<string, unknown>
        if (typeof payload.ok === "boolean") jsonOk = payload.ok
      }
    } catch {
      jsonOk = null
    }
    const failed =
      exitCode !== 0 ||
      jsonOk === false ||
      /traceback|error:/i.test(stderr)
    if (failed && !payload?.skipped) {
      try {
        spawnSync(
          acpBin,
          [
            "debug",
            "record-anomaly",
            "--kind",
            "debug_export_failure",
            "--summary",
            `runDebug failed: ${argvExtra[0] || "unknown"} exit=${exitCode}`,
            "--project",
            root,
          ],
          {
            encoding: "utf-8",
            shell: false,
            windowsHide: true,
            cwd: root,
            env: { ...process.env, ASCENDC_PROJECT_ROOT: root },
            timeout: 15_000,
          },
        )
      } catch {
        // ignore nested failure
      }
    }
    return {
      ok: !failed,
      skipped: Boolean(payload?.skipped),
      payload,
      exit_code: exitCode,
      stdout,
      stderr,
    }
  } catch (err) {
    return {
      ok: false,
      exit_code: 1,
      stdout: "",
      stderr: String(err),
    }
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

/** Stable Task invocation id from OpenCode hook input (before/after must match). */
function extractTaskInvocationId(input: Record<string, unknown>): string {
  for (const k of ["tool_call_id", "call_id", "message_id", "task_invocation_id"] as const) {
    const v = input[k]
    if (typeof v === "string" && v.trim()) return v.trim()
  }
  // Nested under common OpenCode envelopes.
  for (const nest of ["call", "toolCall", "tool_call", "message"] as const) {
    const obj = input[nest]
    if (obj && typeof obj === "object") {
      const nested = extractTaskInvocationId(obj as Record<string, unknown>)
      if (nested) return nested
    }
  }
  return ""
}

/** Inject dispatch_nonce / registration_id into Task args so after-hook can recover without latest-pending. */
function injectTaskCorrelationMeta(
  args: Record<string, unknown>,
  meta: { dispatch_nonce: string; registration_id: string; task_invocation_id?: string },
): void {
  const bag =
    args.metadata && typeof args.metadata === "object"
      ? ({ ...(args.metadata as Record<string, unknown>) } as Record<string, unknown>)
      : ({} as Record<string, unknown>)
  bag.ascendc_dispatch_nonce = meta.dispatch_nonce
  bag.ascendc_registration_id = meta.registration_id
  if (meta.task_invocation_id) bag.ascendc_task_invocation_id = meta.task_invocation_id
  args.metadata = bag
  args.ascendc_dispatch_nonce = meta.dispatch_nonce
  args.ascendc_registration_id = meta.registration_id
  if (meta.task_invocation_id) args.ascendc_task_invocation_id = meta.task_invocation_id
}

function extractTaskCorrelationFromArgs(args: Record<string, unknown>): {
  dispatch_nonce: string
  registration_id: string
  task_invocation_id: string
} {
  const meta =
    args.metadata && typeof args.metadata === "object"
      ? (args.metadata as Record<string, unknown>)
      : {}
  const pick = (obj: Record<string, unknown>, key: string): string => {
    const v = obj[key]
    return typeof v === "string" && v.trim() ? v.trim() : ""
  }
  return {
    dispatch_nonce:
      pick(args, "ascendc_dispatch_nonce") ||
      pick(meta, "ascendc_dispatch_nonce") ||
      pick(args, "dispatch_nonce") ||
      pick(meta, "dispatch_nonce"),
    registration_id:
      pick(args, "ascendc_registration_id") ||
      pick(meta, "ascendc_registration_id") ||
      pick(args, "registration_id") ||
      pick(meta, "registration_id"),
    task_invocation_id:
      pick(args, "ascendc_task_invocation_id") ||
      pick(meta, "ascendc_task_invocation_id") ||
      pick(args, "task_invocation_id") ||
      pick(meta, "task_invocation_id"),
  }
}

function lookupPendingTaskReg(
  invocationId: string,
  fromArgs: { dispatch_nonce: string; registration_id: string; task_invocation_id: string },
):
  | {
      key: string
      reg: {
        registration_id: string
        dispatch_nonce: string
        action_id: string
        parent_session_id: string
      }
    }
  | undefined {
  const keys = [
    invocationId,
    fromArgs.task_invocation_id,
    fromArgs.dispatch_nonce,
    fromArgs.registration_id,
  ].filter(Boolean)
  for (const k of keys) {
    const reg = pendingTaskRegs.get(k)
    if (reg) return { key: k, reg }
  }
  if (fromArgs.registration_id) {
    for (const [key, reg] of pendingTaskRegs.entries()) {
      if (reg.registration_id === fromArgs.registration_id) return { key, reg }
    }
  }
  if (fromArgs.dispatch_nonce) {
    for (const [key, reg] of pendingTaskRegs.entries()) {
      if (reg.dispatch_nonce === fromArgs.dispatch_nonce) return { key, reg }
    }
  }
  return undefined
}

/** Resolve parent/child for the session that is executing this tool hook. */
function resolveToolEventSessions(eventSessionId: string): {
  parent_session_id: string
  child_session_id: string
} {
  if (!eventSessionId) return { parent_session_id: "", child_session_id: "" }
  const rel = childSessionRegistry.get(eventSessionId)
  if (rel) {
    return {
      parent_session_id: rel.parent_session_id,
      child_session_id: eventSessionId,
    }
  }
  return { parent_session_id: eventSessionId, child_session_id: "" }
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
  // Identity travels via env/metadata only — do NOT mutate Task prompt body
  // (ses_0622: prefix + FIX ONLY identity churn). Finalize trusts artifact_identity.
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
      const taskPromptHint = String(args.prompt || args.description || args.task || "")
      const project = isTaskTool
        ? detectProjectRootForTask(taskPromptHint)
        : detectProjectRoot(path)
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
        // Do NOT rewrite agent bash to an absolute acp.exe path.
        // OpenCode frontmatter only allows `acp *`; rewriting to
        // `C:\...\Scripts\acp.exe --help` turns green allow into red deny (ses_00c4 follow-up).
        // resolveAcpBin() is only for this plugin's internal spawnSync(authorize).
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
        const taskInvocationId = extractTaskInvocationId(input as Record<string, unknown>)
        const promptText = String(args.prompt || args.description || args.task || "")
        const promptTrim = promptText.trim()
        // Empty / placeholder Task bodies poison producer sessions (ses_0627).
        if (
          !promptTrim ||
          promptTrim === "{}" ||
          promptTrim === "null" ||
          promptTrim === "undefined"
        ) {
          throw new Error(
            "[ascendc-pilot] Task prompt 为空或无效（禁止 {} / 空串）；必须原样粘贴 prepare 返回的 task_prompt_stub",
          )
        }
        // ses_0622: Host burned retries with "FIX ONLY change action_session_id".
        if (
          /FIX\s*ONLY/i.test(promptTrim) &&
          /action_session_id/i.test(promptTrim) &&
          !/^action_id\s*=/m.test(promptTrim)
        ) {
          throw new Error(
            "[ascendc-pilot] 禁止 FIX ONLY 只改 action_session_id；" +
              "ARTIFACT_SESSION_MISMATCH 须 resume 原 stub 或完整 re-prepare 后整份重写产物。" +
              "semantic_patches 权威字段是 candidate_set_hash（勿写 patch_candidate_set_hash）。",
          )
        }
        if (hostSession) {
          const nonce = `nonce_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
          // Control-plane session identity always registers (not debug-gated).
          const resumeFrom = String(
            (args as any).sessionId ||
              (args as any).sessionID ||
              (args as any).resume ||
              (args as any).resumeSessionId ||
              "",
          )
          const regArgs = [
            "register-child",
            "--parent-session-id",
            hostSession,
            "--action-id",
            dispatchAction,
            "--actor-id",
            dispatchActor,
            "--dispatch-nonce",
            nonce,
            "--task-prompt",
            promptText.slice(0, 4000),
          ]
          if (resumeFrom) {
            regArgs.push("--resumed-from", resumeFrom)
          }
          const reg = runDebug(regArgs, project)
          const regId = String(
            (reg.payload && (reg.payload.registration_id || (reg.payload.registration as any)?.registration_id)) ||
              "",
          )
          const resolvedNonce = String(
            (reg.payload && (reg.payload.dispatch_nonce || (reg.payload.registration as any)?.dispatch_nonce)) ||
              nonce,
          )
          if (regId) {
            const entry = {
              registration_id: regId,
              dispatch_nonce: resolvedNonce,
              action_id: dispatchAction,
              parent_session_id: hostSession,
            }
            // Prefer Hook-provided stable call id; always also index by dispatch_nonce.
            // NEVER key by parent+action "latest pending" (concurrent overwrite).
            if (taskInvocationId) {
              pendingTaskRegs.set(taskInvocationId, entry)
            }
            pendingTaskRegs.set(resolvedNonce, entry)
            pendingTaskRegs.set(regId, entry)
            injectTaskCorrelationMeta(args, {
              dispatch_nonce: resolvedNonce,
              registration_id: regId,
              task_invocation_id: taskInvocationId || undefined,
            })
          }
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
        const taskPromptHint = String(args.prompt || args.description || args.task || "")
        const project = isTaskTool
          ? detectProjectRootForTask(taskPromptHint)
          : detectProjectRoot(path)
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

        const eventSession = extractHostSessionId(input as Record<string, unknown>)
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
          // Ownership from relationship registry: registered child → child=current;
          // else parent=current, child="". event_session_id enables exact-id backfill.
          const owned = resolveToolEventSessions(eventSession)
          runDebug(
            [
              "record-tool-event",
              "--if-enabled",
              "--tool",
              tool,
              "--event-session-id",
              eventSession,
              "--parent-session-id",
              owned.parent_session_id,
              "--child-session-id",
              owned.child_session_id,
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

        // Subagent (Task) finished → exact invocation correlation + export child bundle.
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
          const parentSession = eventSession
          const taskInvocationId = extractTaskInvocationId(input as Record<string, unknown>)
          // Recover correlation from args (injected in before) and output/input envelopes.
          const fromArgs = extractTaskCorrelationFromArgs({
            ...args,
            ...((output && typeof output === "object" ? output : {}) as Record<string, unknown>),
            ...((input as Record<string, unknown>) || {}),
          })
          const hit = lookupPendingTaskReg(taskInvocationId, fromArgs)
          const resultText = (() => {
            const chunks: string[] = []
            if (!output) return ""
            for (const k of ["output", "content", "message", "text", "result"] as const) {
              const v = output[k]
              if (typeof v === "string" && v.trim()) chunks.push(v)
            }
            return chunks.join("\n").slice(0, 8000)
          })()

          if (!hit) {
            // Correlation miss: never wrong-bind via parent+action latest-pending.
            runDebug(
              [
                "record-anomaly",
                "--kind",
                "DEBUG_TASK_CORRELATION_MISSING",
                "--summary",
                `Task after-hook missing pending reg parent=${parentSession} action=${actionId} inv=${taskInvocationId || fromArgs.task_invocation_id || "-"} child=${childSession || "-"}`,
              ],
              project,
            )
          } else if (childSession) {
            const pending = hit.reg
            const patchArgs = [
              "patch-child-session",
              "--child-session-id",
              childSession,
              "--parent-session-id",
              pending.parent_session_id || parentSession,
              "--action-id",
              pending.action_id || actionId,
              "--registration-id",
              pending.registration_id,
              "--dispatch-nonce",
              pending.dispatch_nonce,
            ]
            const hostResume = String(
              (args as any).sessionId ||
                (args as any).sessionID ||
                (args as any).resume ||
                (args as any).resumeSessionId ||
                "",
            )
            if (hostResume) {
              patchArgs.push("--resumed-from", hostResume)
            }
            if (resultText) {
              patchArgs.push("--task-result", resultText)
            }
            const patched = runDebug(patchArgs, project)
            // Update local relationship registry so subsequent child tools attribute correctly.
            childSessionRegistry.set(childSession, {
              parent_session_id: pending.parent_session_id || parentSession,
              registration_id: pending.registration_id,
              dispatch_nonce: pending.dispatch_nonce,
              run_id: String((patched.payload as any)?.registration?.run_id || ""),
              action_id: pending.action_id || actionId,
            })
            // Clear all index keys for this pending entry.
            pendingTaskRegs.delete(hit.key)
            if (pending.dispatch_nonce) pendingTaskRegs.delete(pending.dispatch_nonce)
            if (pending.registration_id) pendingTaskRegs.delete(pending.registration_id)
            if (taskInvocationId) pendingTaskRegs.delete(taskInvocationId)
            if (fromArgs.task_invocation_id) pendingTaskRegs.delete(fromArgs.task_invocation_id)

            const exp = runDebug(
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
            if (!exp.ok && !exp.skipped) {
              // already anomaly-recorded inside runDebug
            }
          } else if (hit) {
            // Task finished but child session id not extractable — clear pending to avoid leak,
            // still record correlation anomaly for observability.
            runDebug(
              [
                "record-anomaly",
                "--kind",
                "DEBUG_TASK_CORRELATION_MISSING",
                "--summary",
                `Task after-hook has pending reg but no child session id inv=${taskInvocationId || hit.reg.dispatch_nonce}`,
              ],
              project,
            )
            pendingTaskRegs.delete(hit.key)
            if (hit.reg.dispatch_nonce) pendingTaskRegs.delete(hit.reg.dispatch_nonce)
            if (hit.reg.registration_id) pendingTaskRegs.delete(hit.reg.registration_id)
          }
        }
      } catch {
        // fail-open
      }
    },
  }
}

export default AscendCHarnessPlugin
