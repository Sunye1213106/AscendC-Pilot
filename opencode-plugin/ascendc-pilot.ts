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
 * 3. `acp host-context` (arch-scoped active_action.yaml) — Host must not hardcode flat paths
 * On Task dispatch, injects action into args so child writes inherit it.
 */

import { spawn, spawnSync, type ChildProcessWithoutNullStreams } from "node:child_process"
import { existsSync, mkdirSync, readdirSync, readFileSync, statSync, unlinkSync, writeFileSync } from "node:fs"
import { homedir } from "node:os"
import { resolve } from "node:path"

/** Host-side pending human interaction (mirrors ACP pending_interaction.yaml). */
type PendingHumanInteraction = {
  request_id: string
  project: string
  allowed_values: string[]
  kind: string
  recorded_at: number
}

const pendingByProject = new Map<string, PendingHumanInteraction>()

function pendingInteractionPath(project: string): string {
  // Arch-neutral control plane (works before --architecture is known).
  return resolve(project, ".ascendc-pilot", "control", "pending_interaction.yaml")
}

/** Prefer `--project` on `acp …` so pending locks bind to the operator dir, not cwd. */
function extractProjectFromAcpCommand(command: string): string {
  const m = String(command || "").match(
    /--project(?:\s+|=)(?:"([^"]+)"|'([^']+)'|(\S+))/i,
  )
  const raw = (m?.[1] || m?.[2] || m?.[3] || "").trim()
  if (!raw) return ""
  try {
    return resolve(raw)
  } catch {
    return raw
  }
}

function isAcpResumeStartCommand(command: string): boolean {
  if (!/\bacp(\.cmd|\.exe)?\s+start\b/i.test(command)) return false
  return /(?:^|\s)--(?:decision|force-new)(?:\s|=|$)/i.test(command)
}

function readPendingFromDisk(project: string): PendingHumanInteraction | null {
  if (!project) return null
  const path = pendingInteractionPath(project)
  if (!existsSync(path)) return null
  try {
    const text = readFileSync(path, "utf8")
    const id = text.match(/request_id:\s*["']?([A-Za-z0-9_-]+)/)?.[1] || ""
    if (!id) return null
    const status = text.match(/^\s*status:\s*["']?([A-Za-z0-9_-]+)/m)?.[1] || "pending"
    if (status && status !== "pending") return null
    const kind = text.match(/kind:\s*["']?([A-Za-z0-9_-]+)/)?.[1] || ""
    const values: string[] = []
    const block = text.match(/allowed_values:\s*\n((?:\s*-\s*.+\n?)*)/)
    if (block?.[1]) {
      for (const line of block[1].split("\n")) {
        const m = line.match(/^\s*-\s*["']?([^"'\n]+)/)
        if (m?.[1]) values.push(m[1].trim())
      }
    }
    return {
      request_id: id,
      project,
      allowed_values: values,
      kind,
      recorded_at: Date.now(),
    }
  } catch {
    return null
  }
}

function getPending(project: string): PendingHumanInteraction | null {
  if (!project) return null
  // Disk is source of truth. After `acp answer` the yaml is status=answered (or
  // unlinked on consume). Stale in-memory pending must not keep blocking start.
  const disk = readPendingFromDisk(project)
  if (!disk) {
    pendingByProject.delete(project)
    return null
  }
  pendingByProject.set(project, disk)
  return disk
}

function clearPending(project: string): void {
  if (!project) return
  pendingByProject.delete(project)
}

function extractJsonObjects(text: string): Record<string, unknown>[] {
  const out: Record<string, unknown>[] = []
  const src = String(text || "")
  for (let i = 0; i < src.length; i++) {
    if (src[i] !== "{") continue
    let depth = 0
    for (let j = i; j < src.length; j++) {
      const ch = src[j]
      if (ch === "{") depth++
      else if (ch === "}") {
        depth--
        if (depth === 0) {
          const slice = src.slice(i, j + 1)
          try {
            const obj = JSON.parse(slice) as Record<string, unknown>
            if (obj && typeof obj === "object") out.push(obj)
          } catch {
            /* not json */
          }
          i = j
          break
        }
      }
    }
  }
  return out
}

function captureHumanInteractionFromOutput(project: string, outputText: string): void {
  if (!project) return
  for (const obj of extractJsonObjects(outputText)) {
    const req = obj.human_interaction_request
    if (!req || typeof req !== "object") continue
    const r = req as Record<string, unknown>
    const requestId = String(r.request_id || "").trim()
    if (!requestId) continue
    const allowed = Array.isArray(r.allowed_values)
      ? r.allowed_values.map((v) => String(v))
      : []
    pendingByProject.set(project, {
      request_id: requestId,
      project,
      allowed_values: allowed,
      kind: String(r.kind || ""),
      recorded_at: Date.now(),
    })
    return
  }
}

function toolOutputText(output: Record<string, unknown> | undefined): string {
  if (!output) return ""
  const chunks: string[] = []
  for (const k of ["output", "content", "message", "text", "result", "stdout"] as const) {
    const v = output[k]
    if (typeof v === "string" && v.trim()) chunks.push(v)
  }
  const meta = output.metadata
  if (meta && typeof meta === "object") {
    for (const k of ["output", "content", "stdout"] as const) {
      const v = (meta as Record<string, unknown>)[k]
      if (typeof v === "string" && v.trim()) chunks.push(v)
    }
  }
  return chunks.join("\n")
}

function extractQuestionAnswer(args: Record<string, unknown>, output: Record<string, unknown> | undefined): string {
  const fromArgs = [
    args.answer,
    args.value,
    args.selection,
    args.selected,
    args.choice,
    args.response,
  ]
  for (const v of fromArgs) {
    if (typeof v === "string" && v.trim()) return v.trim()
    if (Array.isArray(v) && v.length) return String(v[0]).trim()
  }
  const text = toolOutputText(output)
  // Prefer last non-empty line as the selection.
  const lines = text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean)
  if (lines.length) return lines[lines.length - 1]
  return text.trim()
}

function runAcpAnswer(project: string, requestId: string, value: string): { ok: boolean; detail: string } {
  const bin = resolveAcpBin()
  const r = spawnSync(
    bin,
    ["answer", "--project", project, "--request-id", requestId, "--value", value],
    { encoding: "utf8", timeout: 60_000 },
  )
  const stdout = String(r.stdout || "")
  const stderr = String(r.stderr || "")
  try {
    const obj = JSON.parse(stdout) as Record<string, unknown>
    if (obj.ok) return { ok: true, detail: stdout.slice(0, 500) }
    return { ok: false, detail: String(obj.message_zh || obj.error || stdout || stderr).slice(0, 800) }
  } catch {
    if (r.status === 0) return { ok: true, detail: stdout.slice(0, 500) }
    return { ok: false, detail: (stderr || stdout || `exit ${r.status}`).slice(0, 800) }
  }
}

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
  // …/<op>/.ascendc-pilot/<arch>/uo/ir/foo.yaml → <op>
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

/**
 * Sole Host helper that knows Pilot state directory layout.
 * Prefer ``control/active_run.yaml`` → arch-scoped state; then sole arch;
 * then legacy flat ``.ascendc-pilot/state/workflow.yaml``.
 * Do not call this for control/pending_interaction (arch-neutral by design).
 */
function findPilotStateFile(root: string): string {
  const r = String(root || "").trim()
  if (!r) return ""
  const pilot = resolve(r, ".ascendc-pilot")
  if (!existsSync(pilot)) return ""

  // Durable active-run pointer (written by ACP; Host must not invent arch).
  const activeRun = resolve(pilot, "control", "active_run.yaml")
  if (existsSync(activeRun)) {
    try {
      const text = readFileSync(activeRun, "utf-8")
      const m = text.match(/^\s*architecture:\s*["']?([A-Za-z0-9_.-]+)["']?\s*$/m)
      const arch = m ? String(m[1] || "").trim() : ""
      if (arch) {
        const candidate = resolve(pilot, arch, "state", "workflow.yaml")
        if (existsSync(candidate)) return candidate
      }
    } catch {
      // fall through
    }
  }

  // Legacy flat layout (migrated by Python migrate_legacy_agent_dir via host-context).
  const flat = resolve(pilot, "state", "workflow.yaml")
  if (existsSync(flat)) return flat

  try {
    const hits: string[] = []
    for (const name of readdirSync(pilot)) {
      if (!name || name === "control" || name === "uo") continue
      const candidate = resolve(pilot, name, "state", "workflow.yaml")
      if (existsSync(candidate)) hits.push(candidate)
    }
    if (hits.length === 1) return hits[0]
  } catch {
    // ignore
  }
  return ""
}

function isPilotProjectRoot(root: string): boolean {
  return Boolean(findPilotStateFile(root))
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
  // prepare stub (…/<op>/.ascendc-pilot/runs/.../actions/<action_id>/...).
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
  active: { action_id?: string; actor_id?: string; status?: string },
  tool: string,
  _command = "",
): string {
  let agent = resolveAgent(input)
  const actor = String(active.actor_id || "").trim()
  if (!actor) return agent
  // Task + all bash stay Primary. Authorize remaps write tools only.
  const isTask = tool === "task" || tool === "subagent" || tool === "task_tool"
  if (isTask) return agent
  if (tool === "bash" || tool === "shell" || tool === "terminal") return agent
  const status = String(active.status || "")
    .trim()
    .toLowerCase()
  // Lease finished: never remap Primary onto a stale producer.
  if (status === "finalized" || status === "revoked") return agent
  if (status && status !== "prepared" && status !== "running" && status !== "actor_running") {
    return agent
  }
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

type HostContext = {
  ok?: boolean
  project_root?: string
  architecture?: string
  architectures?: string[]
  workflow_state_path?: string
  active_action_path?: string
  pending_interaction_path?: string
  run_id?: string
  workflow_id?: string
  phase?: string
  status?: string
  action_id?: string
  actor_id?: string
  active_action_status?: string
  error?: string
}

type HostContextCache = { mtimeNs: string; payload: HostContext }

const hostContextCache = new Map<string, HostContextCache>()

function hostContextMemoKey(project: string, stateFile: string): string {
  let mtime = "0"
  try {
    if (stateFile && existsSync(stateFile)) {
      mtime = String(statSync(stateFile).mtimeMs)
    }
  } catch {
    mtime = "0"
  }
  const activeHint = stateFile ? resolve(stateFile, "..", "active_action.yaml") : ""
  let activeM = "0"
  try {
    if (activeHint && existsSync(activeHint)) {
      activeM = String(statSync(activeHint).mtimeMs)
    }
  } catch {
    activeM = "0"
  }
  return `${project}|${stateFile}|${mtime}|${activeM}`
}

function fetchHostContext(project: string): HostContext {
  const root = String(project || "").trim()
  if (!root) return { ok: false, error: "missing_project" }
  const stateFile = findPilotStateFile(root)
  const key = hostContextMemoKey(root, stateFile)
  const hit = hostContextCache.get(key)
  if (hit) return hit.payload

  const acpBin = resolveAcpBin()
  const argv = ["host-context", "--project", root]
  const res = spawnSync(acpBin, argv, {
    encoding: "utf-8",
    shell: false,
    windowsHide: true,
    cwd: root,
    env: { ...process.env, ASCENDC_PROJECT_ROOT: root },
    timeout: 15_000,
  })
  const text = `${res.stdout || ""}\n${res.stderr || ""}`.trim()
  const jsonStart = text.indexOf("{")
  let payload: HostContext = { ok: false, error: "host_context_parse_failed" }
  if (jsonStart >= 0) {
    try {
      payload = JSON.parse(text.slice(jsonStart)) as HostContext
    } catch {
      payload = { ok: false, error: "host_context_json_invalid", project_root: root }
    }
  } else if (res.error || res.status === 127) {
    payload = {
      ok: false,
      error: "HARNESS_MISSING",
      project_root: root,
    }
  }
  hostContextCache.set(key, { mtimeNs: key, payload })
  // Bound cache size.
  if (hostContextCache.size > 32) {
    const first = hostContextCache.keys().next().value
    if (first) hostContextCache.delete(first)
  }
  return payload
}

function readActiveAction(project: string): {
  action_id?: string
  actor_id?: string
  status?: string
} {
  // Authority is ACP host-context — Host must not open active_action.yaml itself.
  const ctx = fetchHostContext(project)
  return {
    action_id: String(ctx.action_id || "").trim(),
    actor_id: String(ctx.actor_id || "").trim(),
    status: String(ctx.active_action_status || "").trim(),
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
  // Install scripts write the cache; Host adapter must not re-implement install discovery.
  const fromEnv = String(process.env.ASCENDC_HARNESS_BIN || "").trim()
  if (fromEnv && existsSync(fromEnv)) return fromEnv

  try {
    const cached = readFileSync(harnessBinCachePath(), "utf-8").trim()
    if (cached && existsSync(cached)) return cached
  } catch {
    // ignore
  }

  // Bare name: rely on PATH at spawn time (agent-facing bash stays `acp *`).
  return "acp"
}

type AuthorizeDaemon = {
  proc: ChildProcessWithoutNullStreams
  ready: boolean
}

let _authDaemon: AuthorizeDaemon | null = null
let _authReqSeq = 0

function authIpcDir(): string {
  return resolve(homedir(), ".config", "opencode", "ascendc-auth-ipc")
}

function ensureAuthorizeDaemon(): boolean {
  if (_authDaemon && _authDaemon.ready && !_authDaemon.proc.killed) return true
  if (process.env.ASCENDC_AUTHORIZE_SPAWN === "1") return false
  const acpBin = resolveAcpBin()
  try {
    mkdirSync(authIpcDir(), { recursive: true })
    const proc = spawn(acpBin, ["serve-authorize", "--ipc-dir", authIpcDir()], {
      shell: false,
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
      env: { ...process.env },
      detached: false,
    }) as ChildProcessWithoutNullStreams
    const daemon: AuthorizeDaemon = { proc, ready: false }
    proc.stdout.setEncoding("utf-8")
    let buf = ""
    proc.stdout.on("data", (chunk: string) => {
      buf += chunk
      if (buf.includes('"event": "ready"') || buf.includes('"event":"ready"')) {
        daemon.ready = true
      }
    })
    proc.on("exit", () => {
      if (_authDaemon === daemon) _authDaemon = null
    })
    proc.on("error", () => {
      if (_authDaemon === daemon) _authDaemon = null
    })
    _authDaemon = daemon
    const deadline = Date.now() + 2000
    while (!daemon.ready && Date.now() < deadline && !proc.killed) {
      spawnSync(process.execPath, ["-e", ""], { timeout: 15 })
    }
    return daemon.ready
  } catch {
    return false
  }
}

function runAuthorizeViaIpc(req: Record<string, unknown>): AuthorizeResult | null {
  if (!ensureAuthorizeDaemon()) return null
  const dir = authIpcDir()
  const id = `r${Date.now().toString(36)}_${(++_authReqSeq).toString(36)}`
  const reqPath = resolve(dir, `${id}.req.json`)
  const respPath = resolve(dir, `${id}.resp.json`)
  try {
    writeFileSync(reqPath, JSON.stringify({ id, method: "authorize", ...req }), "utf-8")
    const deadline = Date.now() + 8000
    while (Date.now() < deadline) {
      if (existsSync(respPath)) {
        try {
          const text = readFileSync(respPath, "utf-8")
          unlinkSync(respPath)
          try {
            unlinkSync(reqPath)
          } catch {
            /* ignore */
          }
          return JSON.parse(text) as AuthorizeResult
        } catch {
          return null
        }
      }
      spawnSync(process.execPath, ["-e", ""], { timeout: 10 })
    }
  } catch {
    return null
  }
  return null
}

function runAuthorize(args: {
  tool: string
  command?: string
  path?: string
  agent?: string
  action?: string
  project?: string
  leaseId?: string
  sessionId?: string
}): AuthorizeResult {
  const project = args.project || detectProjectRoot()
  const agent = String(args.agent || "ascendc-pilot").trim() || "ascendc-pilot"
  const action = String(args.action || "").trim()
  const command = String(args.command ?? "").trim()
  const path = String(args.path ?? "").trim()
  const leaseId = String(args.leaseId || "").trim()
  const sessionId = String(args.sessionId || "").trim()

  const ipcReq: Record<string, unknown> = {
    project,
    tool: args.tool,
    command,
    path,
    agent,
    action,
    lease_id: leaseId,
    session_id: sessionId,
  }
  const viaIpc = runAuthorizeViaIpc(ipcReq)
  if (viaIpc) {
    rememberProjectRoot(project)
    return viaIpc
  }

  // Fallback: one-shot spawnSync (cold start). Always correct.
  const argv = ["authorize", "--project", project, "--tool", args.tool]
  if (command) argv.push("--command", command)
  if (path) argv.push("--path", path)
  argv.push("--agent", agent)
  if (action) argv.push("--action", action)
  if (leaseId) argv.push("--lease-id", leaseId)
  if (sessionId) argv.push("--session-id", sessionId)

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

/** Persist child session identity for ticket-based authorize (cross-process). */
function registerAuthorizeSession(args: {
  project: string
  sessionId: string
  actorId: string
  actionId: string
  leaseId?: string
  runId?: string
}): void {
  try {
    const dir = resolve(homedir(), ".config", "opencode", "ascendc-sessions")
    mkdirSync(dir, { recursive: true })
    writeFileSync(
      resolve(dir, `${args.sessionId.replace(/[^\w.-]/g, "_")}.json`),
      JSON.stringify({
        project: args.project,
        session_id: args.sessionId,
        actor_id: args.actorId,
        action_id: args.actionId,
        lease_id: args.leaseId || "",
        run_id: args.runId || "",
        ts: Date.now(),
      }),
      "utf-8",
    )
  } catch {
    /* ignore */
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
  projectRoot?: string,
): void {
  if (!action && !projectRoot) return
  // Ensure subsequent authorize/resolvers see action without relying on LLM memory.
  if (action && !args.action && !args.action_id && !args.actionId) {
    args.action = action
    args.action_id = action
  }
  // Pin child working directory to the operator package when Host supports it.
  if (projectRoot) {
    if (!args.cwd && !args.workdir && !args.working_directory && !args.directory) {
      args.cwd = projectRoot
      args.workdir = projectRoot
      args.directory = projectRoot
    }
    // OpenCode session.create location (Host Driver / Task bridges).
    if (!args.location || typeof args.location !== "object") {
      args.location = { directory: projectRoot }
    } else {
      const loc = args.location as Record<string, unknown>
      if (!loc.directory) loc.directory = projectRoot
    }
  }
  // Identity travels via env/metadata only — do NOT mutate Task prompt body
  // (ses_0622: prefix + FIX ONLY identity churn). Finalize trusts artifact_identity.
  const envBag = (args.env || args.environment || args.envVars) as Record<string, string> | undefined
  const envPatch: Record<string, string> = {}
  if (action) envPatch.ASCENDC_ACTION = action
  if (actor) envPatch.ASCENDC_AGENT = actor
  if (projectRoot) envPatch.ASCENDC_PROJECT_ROOT = projectRoot
  if (envBag && typeof envBag === "object") {
    Object.assign(envBag, envPatch)
  } else {
    args.env = { ...envPatch }
  }
}

export const AscendCHarnessPlugin = async (ctx?: {
  client?: unknown
  directory?: string
  project?: unknown
  $?: unknown
}) => {
  const client = ctx && typeof ctx === "object" ? (ctx as any).client : undefined
  let pilotTools: Record<string, unknown> = {}
  try {
    // Dynamic import keeps older OpenCode hosts working if this file is absent.
    const mod = await import("./pilot-driver")
    pilotTools = mod.createPilotRunTool(client, ctx) || {}
  } catch {
    pilotTools = {}
  }

  return {
    tool: pilotTools,
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
      const fromCmd = extractProjectFromAcpCommand(command)
      const fromArgs = String(
        args.project || args.project_root || args.projectRoot || "",
      ).trim()
      const project = isTaskTool
        ? detectProjectRootForTask(taskPromptHint)
        : detectProjectRoot(fromCmd || fromArgs || path)
      if (project) rememberProjectRoot(project)
      const active = readActiveAction(project)
      let agent = resolveEffectiveAgent(input, active, tool, command)

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

      // Human Interaction Broker: while ACP has a pending interaction, only
      // the question UI (and acp answer / inspect helpers) may proceed.
      const pending = getPending(project)
      if (pending) {
        const isQuestion =
          tool === "question" ||
          tool === "askquestion" ||
          tool === "ask_question" ||
          tool.includes("question")
        const isAnswerBash =
          (tool === "bash" || tool === "shell" || tool === "terminal") &&
          /\bacp(\.cmd|\.exe)?\s+answer\b/i.test(command)
        const isInspectBash =
          (tool === "bash" || tool === "shell" || tool === "terminal") &&
          /\bacp(\.cmd|\.exe)?\s+(inspect-failure|next|status|run-summary)\b/i.test(command)
        const isResumeStartBash =
          (tool === "bash" || tool === "shell" || tool === "terminal") &&
          isAcpResumeStartCommand(command)
        // Host Driver owns AskQuestion + start --decision; do not deadlock
        // a second pilot_run after EXISTING_RUN left pending yaml on disk.
        const isPilotDriver = tool === "pilot_run" || tool === "pilotrun"
        if (!isQuestion && !isAnswerBash && !isInspectBash && !isResumeStartBash && !isPilotDriver) {
          throw new Error(
            `[ascendc-pilot] human interaction pending (request_id=${pending.request_id}). ` +
              `Only the question UI, acp answer, acp start --decision continue|reinit, or pilot_run is allowed until the user answers.`,
          )
        }
      }

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
        injectActionContext(args, dispatchAction, dispatchActor, project)
        const hostSession = extractHostSessionId(input as Record<string, unknown>)
        const taskInvocationId = extractTaskInvocationId(input as Record<string, unknown>)
        // Ticket identity for child authorize (even before child session id is known).
        registerAuthorizeSession({
          project,
          sessionId: taskInvocationId || `task_${dispatchAction}_${Date.now().toString(36)}`,
          actorId: dispatchActor,
          actionId: dispatchAction,
          leaseId: "",
          runId: "",
        })
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
              "ARTIFACT_SESSION_MISMATCH 须 resume 原 stub 或完整 re-prepare 后整份重写产物。",
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
        const command = String(args.command || args.cmd || "")
        const isTaskTool = tool === "task" || tool === "subagent" || tool === "task_tool"
        const taskPromptHint = String(args.prompt || args.description || args.task || "")
        const fromCmd = extractProjectFromAcpCommand(command)
        const fromArgs = String(
          args.project || args.project_root || args.projectRoot || "",
        ).trim()
        const project = isTaskTool
          ? detectProjectRootForTask(taskPromptHint)
          : detectProjectRoot(fromCmd || fromArgs || path)
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

        // Capture human_interaction_request from acp stdout and record answers.
        if (tool === "bash" || tool === "shell" || tool === "terminal") {
          const text = toolOutputText(output)
          if (project && text) {
            if (/\bacp(\.cmd|\.exe)?\s+answer\b/i.test(command) && /"ok"\s*:\s*true/.test(text)) {
              clearPending(project)
            } else {
              captureHumanInteractionFromOutput(project, text)
            }
          }
        }
        const isQuestionTool =
          tool === "question" ||
          tool === "askquestion" ||
          tool === "ask_question" ||
          tool.includes("question")
        if (isQuestionTool && project) {
          const pending = getPending(project)
          if (pending) {
            const value = extractQuestionAnswer(args, output)
            if (value) {
              const answered = runAcpAnswer(project, pending.request_id, value)
              if (answered.ok) {
                clearPending(project)
              } else {
                runDebug(
                  [
                    "record-tool-failure",
                    "--tool",
                    "question",
                    "--error",
                    `acp answer failed: ${answered.detail}`.slice(0, 1500),
                  ],
                  project,
                )
              }
            }
          }
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
