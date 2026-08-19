/**
 * AscendC Pilot OpenCode plugin.
 *
 * Install: copy this file to ~/.config/opencode/plugins/ascendc-pilot.ts
 * Does NOT merge or rewrite the user's opencode.json.
 *
 * Intercepts bash/write/edit/apply_patch/task/read/glob/grep/skill and MCP tools
 * before execution and asks `acp authorize` (MCP on Pilot children is denied).
 * Soft control plane only — not OS-level security.
 *
 * Platform limits: OpenCode may not expose subagent identity on every hook;
 * receipts are issued by Host `pilot_run` (internal transport may call run-action --finalize).
 *
 * Action context propagation:
 * 1. ASCENDC_ACTION env
 * 2. tool args action / action_id / actionId
 * 3. `acp host-context` (arch-scoped active_action.yaml) — Host must not hardcode flat paths
 * On Task dispatch, injects action into args so child writes inherit it.
 */

import { spawn, spawnSync, type ChildProcessWithoutNullStreams } from "node:child_process"
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  statSync,
  unlinkSync,
  writeFileSync,
} from "node:fs"
import { homedir } from "node:os"
import { delimiter, dirname, isAbsolute, join, relative, resolve } from "node:path"
import { pathToFileURL } from "node:url"

/** Inlined: OpenCode autoloads this file from plugins/ without sibling imports. */
function openCodeHome(): string {
  const xdg = String(process.env.XDG_CONFIG_HOME || "").trim()
  if (xdg) return resolve(xdg, "opencode")
  return resolve(homedir(), ".config", "opencode")
}

/** Host-side pending human interaction (mirrors ACP pending_interaction.yaml). */
type PendingHumanInteraction = {
  request_id: string
  project: string
  allowed_values: string[]
  kind: string
  prompt_zh: string
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

function isAcpHelpCommand(command: string): boolean {
  const cmd = String(command || "").trim()
  if (!cmd) return false
  if (/(^|\s)(--help|-h)(\s|$)/i.test(cmd)) return true
  return /^(?:acp(?:\.cmd|\.exe)?\s+)?help(?:\s|$)/i.test(cmd)
}

function isPrimaryPilotAgent(agent: string): boolean {
  const a = String(agent || "").trim().toLowerCase()
  return a === "ascendc-pilot" || a === "ascendc_agent"
}

/** Listing / cwd probes only. File contents go through Read (engine-source fence). */
function isReadonlyInspectBash(command: string): boolean {
  const cmd = String(command || "").trim()
  if (!cmd) return false
  if (/\s>>?/.test(cmd)) return false
  if (/\b(set-content|out-file|add-content|new-item|tee)\b/i.test(cmd)) return false
  return /^(ls|dir|tree|pwd|get-childitem|gci|get-item|gi|get-location|gl|test-path|resolve-path|cd|set-location|sl|push-location|pop-location)\b/i.test(
    cmd,
  )
}

function isAcpDiagnosticCommand(command: string): boolean {
  return /\b(inspect-failure|next|status|run-summary|scan-architectures|abort|answer|interpret-user-turn)\b/i.test(
    String(command || ""),
  )
}

/** Returned by plugin `pilot_cli` instead of argparse --help. */
const PILOT_CLI_HELP_USAGE_CARD = [
  "[ascendc-pilot] Do not use --help to discover protocol.",
  "argparse lists internal commands (authorize / debug / serve-authorize) and is not the Session Driver contract.",
  "",
  "Workflows (uo-init / uo-update / tg-* / ce-* / uo-investigate): Host tool pilot_run(workflow, project, architecture).",
  "If pilot_run is missing: tell the user to fully quit OpenCode and rerun refresh-opencode.ps1.",
  "",
  "Plugin `pilot_cli` command examples:",
  "  uo-query --project <operator-abs> [--architecture arch] <identifier|Dim=V>",
  "  uo-query --project <operator-abs> --status-only",
  "  scan-architectures --project <operator-abs>",
  "  status --project <operator-abs>",
  "  inspect-failure --project <operator-abs>",
  "  inspect evidence-window --project <operator-abs> --path <rel> --lines A-B",
  "  ro-search --pattern <pat> --paths <already-cited-file>",
  "  next --project <operator-abs>",
  "  retry-after-environment-fix --project <operator-abs>",
  "  interpret-user-turn --project <operator-abs> --text <latest user message>",
  "",
  "On failure: inspect-failure / status, not another --help.",
  "Pending AskQuestion: if the user typed a new message instead of clicking, interpret that turn; do not re-ask. --help does not consume the question.",
].join("\n")

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
    const prompt =
      text.match(/prompt_zh:\s*["']?([^\n"']+)/)?.[1]?.trim() ||
      text.match(/question:\s*["']?([^\n"']+)/)?.[1]?.trim() ||
      ""
    return {
      request_id: id,
      project,
      allowed_values: values,
      kind,
      prompt_zh: prompt,
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
      prompt_zh: String(
        (r.ask_question && typeof r.ask_question === "object"
          ? (r.ask_question as Record<string, unknown>).prompt_zh ||
            (r.ask_question as Record<string, unknown>).question
          : "") ||
          obj.message_zh ||
          "",
      ),
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
    if (typeof v === "string" && v.trim()) return canonicalizeQuestionValue(v.trim())
    if (Array.isArray(v) && v.length) return canonicalizeQuestionValue(String(v[0]).trim())
  }
  const text = toolOutputText(output)
  const pairs = [...text.matchAll(/"([^"]*)"\s*=\s*"([^"]+)"/g)]
  if (pairs.length) {
    return canonicalizeQuestionValue(pairs[pairs.length - 1][2].trim())
  }
  const eq = text.match(/=\s*"([^"]+)"/)
  if (eq?.[1]) return canonicalizeQuestionValue(eq[1].trim())
  const lines = text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean)
  const last = lines.length ? lines[lines.length - 1] : text.trim()
  if (/User has answered/i.test(last) || last.length > 80) {
    const m = last.match(/=\s*"([^"]+)"/)
    if (m?.[1]) return canonicalizeQuestionValue(m[1].trim())
  }
  return canonicalizeQuestionValue(last)
}

function canonicalizeQuestionValue(raw: string): string {
  const key = String(raw || "").trim()
  if (!key) return ""
  const low = key.toLowerCase()
  if (low === "continue" || low === "reinit" || low === "query") return low
  if (key.startsWith("开始") || key.includes("继续")) return "continue"
  if (key.includes("删除") || key.includes("重开")) return "reinit"
  if (key.includes("查询")) return "query"
  return key
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

function runAcpInterpretUserTurn(
  project: string,
  text: string,
  reason = "user_message",
): { ok: boolean; disposition: string; messageZh: string } {
  const bin = resolveAcpBin()
  const r = spawnSync(
    bin,
    [
      "interpret-user-turn",
      "--project",
      project,
      "--text",
      String(text || ""),
      "--reason",
      reason,
    ],
    { encoding: "utf8", timeout: 60_000 },
  )
  const stdout = String(r.stdout || "")
  const stderr = String(r.stderr || "")
  try {
    const obj = JSON.parse(stdout) as Record<string, unknown>
    return {
      ok: obj.ok !== false,
      disposition: String(obj.disposition || ""),
      messageZh: String(obj.message_zh || obj.message || "").slice(0, 400),
    }
  } catch {
    return {
      ok: r.status === 0,
      disposition: "",
      messageZh: (stderr || stdout || `exit ${r.status}`).slice(0, 400),
    }
  }
}

const lastUserTurnNote = new Map<string, string>()

function extractUserTurnText(output: { message?: unknown; parts?: unknown } | undefined): string {
  if (!output || typeof output !== "object") return ""
  const chunks: string[] = []
  const parts = Array.isArray(output.parts) ? output.parts : []
  for (const part of parts) {
    if (!part || typeof part !== "object") continue
    const row = part as Record<string, unknown>
    const t = row.text ?? row.content
    if (typeof t === "string" && t.trim()) chunks.push(t.trim())
  }
  const msg = output.message
  if (msg && typeof msg === "object") {
    const content = (msg as Record<string, unknown>).content
    if (typeof content === "string" && content.trim()) chunks.push(content.trim())
  }
  return chunks.join("\n").trim()
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
  const r = String(root || "").trim()
  if (!r) return false
  const pilot = resolve(r, ".ascendc-pilot")
  try {
    if (existsSync(pilot) && statSync(pilot).isDirectory()) return true
  } catch {
    // fall through
  }
  return Boolean(findPilotStateFile(r))
}

function isHarnessCheckout(root: string): boolean {
  const r = String(root || "").trim()
  if (!r) return false
  try {
    return existsSync(resolve(r, "pilot", "ascendc_pilot")) && existsSync(resolve(r, "engines"))
  } catch {
    return false
  }
}

function isUnderHarnessCheckout(root: string): boolean {
  const r = String(root || "").trim()
  if (!r) return false
  try {
    let cur = resolve(r)
    for (let i = 0; i < 12; i++) {
      if (isHarnessCheckout(cur)) return true
      const parent = resolve(cur, "..")
      if (parent === cur) break
      cur = parent
    }
  } catch {
    return false
  }
  return false
}

function looksLikeOperatorDir(root: string): boolean {
  const r = String(root || "").trim()
  if (!r || isHarnessCheckout(r) || isUnderHarnessCheckout(r)) return false
  return existsSync(resolve(r, "op_kernel")) || existsSync(resolve(r, "op_host"))
}

function operatorName(root: string): string {
  const norm = String(root || "").replace(/\\/g, "/").replace(/\/+$/, "")
  const parts = norm.split("/").filter(Boolean)
  return parts.length ? parts[parts.length - 1] : ""
}

function lastProjectCachePath(): string {
  return resolve(openCodeHome(), "ascendc-last-project")
}

/** OpenCode workspace (`ctx.directory`). Empty until the plugin factory runs. */
let hostOpenDirectory = ""
/** Current Host session. Empty until the first chat/tool hook. */
let liveSessionId = ""

function noteLiveSession(sessionId?: string): void {
  const sid = String(sessionId || "").trim()
  if (sid) liveSessionId = sid
}

function lastProjectSessionPath(): string {
  return `${lastProjectCachePath()}.session`
}

function pathIsInsideHost(child: string, parent: string): boolean {
  try {
    const c = resolve(child)
    const p = resolve(parent)
    if (process.platform === "win32") {
      if (c.toLowerCase() === p.toLowerCase()) return true
    } else if (c === p) {
      return true
    }
    const rel = relative(p, c)
    if (!rel) return true
    const norm = rel.replace(/\\/g, "/")
    return !norm.startsWith("../") && norm !== ".." && !isAbsolute(rel)
  } catch {
    return false
  }
}

function pathAllowedForHost(root: string): boolean {
  const remembered = String(root || "").trim()
  if (!remembered) return false
  if (!hostOpenDirectory) return true
  return pathIsInsideHost(remembered, hostOpenDirectory)
}

function writeLastProjectSession(sessionId?: string): void {
  const sid = String(sessionId || liveSessionId || "").trim()
  if (!sid) return
  try {
    writeFileSync(lastProjectSessionPath(), sid, "utf-8")
  } catch {
    // best-effort
  }
}

function readLastProjectSession(): string {
  try {
    const p = lastProjectSessionPath()
    if (!existsSync(p)) return ""
    return readFileSync(p, "utf-8").trim()
  } catch {
    return ""
  }
}

function rememberedUsable(root: string): boolean {
  if (!pathAllowedForHost(root)) return false
  if (!liveSessionId) return true
  const sid = readLastProjectSession()
  if (!sid) return false
  return sid === liveSessionId
}

function pendingDispatchCachePath(): string {
  return resolve(openCodeHome(), "ascendc-pending-dispatch.json")
}

function readPendingDispatchProject(): string {
  try {
    const cache = pendingDispatchCachePath()
    if (!existsSync(cache)) return ""
    const rec = JSON.parse(readFileSync(cache, "utf-8")) as {
      project?: string
      sessionId?: string
    }
    const root = String(rec?.project || "").trim()
    const sid = String(rec?.sessionId || "").trim()
    if (liveSessionId && sid && sid !== liveSessionId) return ""
    if (root && looksLikeOperatorDir(root) && pathAllowedForHost(root)) return root
    if (
      root &&
      isPilotProjectRoot(root) &&
      !isHarnessCheckout(root) &&
      pathAllowedForHost(root)
    ) {
      return root
    }
  } catch {
    // ignore
  }
  return ""
}

function rememberProjectRoot(project: string): void {
  const root = String(project || "").trim()
  // Cache operator dirs even before a live workflow.yaml exists.
  if (!root || !looksLikeOperatorDir(root) || isHarnessCheckout(root)) return
  if (!pathAllowedForHost(root)) return
  try {
    const cache = lastProjectCachePath()
    mkdirSync(openCodeHome(), { recursive: true })
    writeFileSync(cache, root, "utf-8")
    writeLastProjectSession(liveSessionId)
  } catch {
    // best-effort
  }
}

function readRememberedProjectRoot(): string {
  try {
    const cache = lastProjectCachePath()
    if (!existsSync(cache)) return ""
    const root = readFileSync(cache, "utf-8").trim()
    if (root && looksLikeOperatorDir(root) && !isHarnessCheckout(root) && rememberedUsable(root)) {
      return root
    }
  } catch {
    // ignore
  }
  return ""
}

function envOperatorRoot(): string {
  for (const key of [
    "ASCENDC_PROJECT_ROOT",
    "UO_OP_DIR",
    "OPENCODE_PROJECT_ROOT",
    "PROJECT_ROOT",
  ]) {
    const raw = String(process.env[key] || "").trim()
    if (!raw) continue
    try {
      const resolved = resolve(raw)
      if (
        looksLikeOperatorDir(resolved) &&
        !isHarnessCheckout(resolved) &&
        pathAllowedForHost(resolved)
      ) {
        return resolved
      }
    } catch {
      /* ignore */
    }
  }
  return ""
}

/** Conversation-pinned operator. Never the Pilot checkout or a path under it. */
function boundOperatorRoot(pathHint?: string): string {
  const hint = String(pathHint || "").trim()
  const fromPath = projectRootFromPath(hint)
  if (fromPath && looksLikeOperatorDir(fromPath)) return fromPath
  if (hint) {
    try {
      const resolved = resolve(hint)
      if (looksLikeOperatorDir(resolved) && !isUnderHarnessCheckout(resolved)) return resolved
    } catch {
      /* ignore */
    }
  }
  const pending = readPendingDispatchProject()
  if (pending && looksLikeOperatorDir(pending)) return pending
  const fromEnv = envOperatorRoot()
  if (fromEnv) return fromEnv
  const cwd = process.cwd()
  if (looksLikeOperatorDir(cwd) && !isHarnessCheckout(cwd) && pathAllowedForHost(cwd)) {
    return cwd
  }
  const remembered = readRememberedProjectRoot()
  if (remembered && looksLikeOperatorDir(remembered)) {
    if (hint) {
      const want = operatorName(hint)
      const have = operatorName(remembered)
      if (want && want.toLowerCase() === have.toLowerCase()) return remembered
    }
    return remembered
  }
  return ""
}

function detectProjectRoot(pathHint?: string): string {
  const bound = boundOperatorRoot(pathHint)
  if (bound) return bound
  const fromPath = projectRootFromPath(String(pathHint || ""))
  if (fromPath && isPilotProjectRoot(fromPath) && !isHarnessCheckout(fromPath)) return fromPath

  const cwd = process.cwd()
  if (looksLikeOperatorDir(cwd) && !isHarnessCheckout(cwd)) return cwd
  if (isPilotProjectRoot(cwd) && !isHarnessCheckout(cwd)) return cwd

  // Walk up: prefer an operator package over the Pilot checkout.
  let cur = cwd
  for (let i = 0; i < 8; i++) {
    if (isHarnessCheckout(cur)) break
    if (looksLikeOperatorDir(cur) || isPilotProjectRoot(cur)) return cur
    const parent = resolve(cur, "..")
    if (parent === cur) break
    cur = parent
  }

  const remembered = readRememberedProjectRoot()
  if (remembered) return remembered

  // Do NOT fall back to bare .git / AscendC-Pilot repo — those authorize as a
  // fake project with empty phase actors and block Task (ses_062d).
  const fromEnv = envOperatorRoot()
  return fromEnv || process.cwd()
}

function detectProjectRootForTask(promptHint?: string): string {
  // Task args carry subagent names, not file paths. Prefer paths embedded in the
  // prepare stub (…/<op>/.ascendc-pilot/runs/.../actions/<action_id>/...).
  const fromPrompt = projectRootFromPath(String(promptHint || ""))
  if (fromPrompt && looksLikeOperatorDir(fromPrompt)) {
    return fromPrompt
  }

  // pilot_run already stored the operator on dispatch_subagent. OpenCode Task
  // often only exposes the short card description here — do not re-detect cwd.
  const pending = readPendingDispatchProject()
  if (pending) return pending

  const bound = boundOperatorRoot(promptHint)
  if (bound) return bound
  if (fromPrompt && isPilotProjectRoot(fromPrompt) && !isHarnessCheckout(fromPrompt)) {
    return fromPrompt
  }
  return detectProjectRoot()
}

function resolveAgent(input: {
  agent?: string
  sessionAgent?: string
  sessionID?: string
  sessionId?: string
}): string {
  const fromInput = String(input.agent || input.sessionAgent || "").trim()
  if (fromInput) return fromInput
  const sid = String(input.sessionID || input.sessionId || "").trim()
  if (sid) {
    const cached = sessionAgentById.get(sid) || ""
    if (cached) return cached
  }
  const fromEnv = String(process.env.ASCENDC_AGENT || process.env.OPENCODE_AGENT || "").trim()
  if (fromEnv) return fromEnv
  // Never default unlabeled sessions to ascendc-pilot — that steals Build/Plan.
  return ""
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

const NATIVE_OPENCODE_AGENTS = [
  "build",
  "plan",
  "general",
  "explore",
  "scout",
  "compaction",
  "title",
  "summary",
  "ask",
  "debug",
] as const

const PASS_THROUGH_AGENTS = new Set<string>([
  ...NATIVE_OPENCODE_AGENTS,
  "general-purpose",
  "generalpurpose",
])

const PILOT_ONLY_TOOLS = new Set(["pilot_run", "pilotrun", "pilot_cli"])

/** Workflow skills live plugin-internal only. Never install into global OpenCode skills/. */
const PILOT_WORKFLOW_SKILLS = [
  "uo-init",
  "uo-update",
  "uo-query",
  "uo-investigate",
  "ce-review",
  "ce-plan",
  "ce-apply",
  "handoff",
  "tg-init",
  "tg-plan",
  "tg-solve",
  "workflow-orchestration",
  "operator",
] as const

const PILOT_COGNITIVE_SKILLS = [
  "operator-analysis",
  "testcase-generation",
  "source-proof",
  "code-review",
  "code-engineering",
] as const

const PILOT_MANAGED_SKILLS = new Set<string>([
  ...PILOT_WORKFLOW_SKILLS,
  ...PILOT_COGNITIVE_SKILLS,
])

function isPilotManagedSkill(name: string): boolean {
  const n = String(name || "")
    .trim()
    .replace(/\\/g, "/")
    .split("/")
    .filter(Boolean)
    .pop()
    ?.toLowerCase() || ""
  return PILOT_MANAGED_SKILLS.has(n)
}

/** Named deny so leftover global links cannot be invoked from Build/Plan. */
function denyPilotWorkflowSkills(perm: Record<string, unknown>): void {
  const named: Record<string, unknown> = {}
  for (const n of PILOT_MANAGED_SKILLS) named[n] = "deny"
  const cur = perm.skill
  if (typeof cur === "string") {
    perm.skill = { "*": cur, ...named }
    return
  }
  if (cur && typeof cur === "object") {
    perm.skill = { ...(cur as Record<string, unknown>), ...named }
    return
  }
  perm.skill = { "*": "allow", ...named }
}

/** sessionID → Tab / child agent. OpenCode tool hooks often omit `agent`. */
const sessionAgentById = new Map<string, string>()

function rememberSessionAgent(sessionID: string, agent: string): void {
  const id = String(sessionID || "").trim()
  const a = String(agent || "").trim()
  if (id && a) sessionAgentById.set(id, a)
}

function isPilotOnlyTool(tool: string): boolean {
  return PILOT_ONLY_TOOLS.has(String(tool || "").trim().toLowerCase())
}

const PRIMARY_AGENT_IDS = new Set(["ascendc-pilot", "ascendc_agent"])

function pluginInstallManifestPath(): string {
  return resolve(openCodeHome(), "ascendc-pilot-plugin", "install-manifest.json")
}

function pluginAgentsDir(): string {
  return resolve(openCodeHome(), "ascendc-pilot-plugin", "agents")
}

function stemAgentName(name: string): string {
  const n = String(name || "").trim()
  return n.toLowerCase().endsWith(".md") ? n.slice(0, -3) : n
}

/**
 * Owned Pilot agent ids. Source of truth is install-manifest.json written by
 * compose from generated/<host>/agents. Fallback: plugin-internal agents/.
 * Never scan ~/.config/opencode/agents and never use filename prefixes.
 */
function ownedPilotAgentIds(): Set<string> {
  const ids = new Set<string>(PRIMARY_AGENT_IDS)
  const skip = new Set(["readme", "tg-init-audit"])
  try {
    const manPath = pluginInstallManifestPath()
    if (existsSync(manPath)) {
      const raw = JSON.parse(
        readFileSync(manPath, "utf-8").replace(/^\uFEFF/, ""),
      ) as { agents?: unknown }
      const agents = Array.isArray(raw?.agents) ? raw.agents : []
      for (const item of agents) {
        const id = stemAgentName(String(item || "")).toLowerCase()
        if (id && !skip.has(id)) ids.add(id)
      }
      return ids
    }
  } catch {
    /* fall through to plugin-internal agents/ */
  }
  try {
    for (const f of readdirSync(pluginAgentsDir())) {
      if (!f.endsWith(".md")) continue
      const n = stemAgentName(f).toLowerCase()
      if (n && !skip.has(n)) ids.add(n)
    }
  } catch {
    /* ignore */
  }
  return ids
}

/** Pilot primary + owned actors from the install manifest. Build/Plan/user Tabs → pass-through. */
function isPilotFamilyAgent(agent: string): boolean {
  const a = String(agent || "")
    .trim()
    .toLowerCase()
  if (!a) return false
  if (PASS_THROUGH_AGENTS.has(a)) return false
  if (PRIMARY_AGENT_IDS.has(a)) return true
  return ownedPilotAgentIds().has(a)
}

/** Enforce harness only for Pilot-family agents (global plugin stays loaded). */
function shouldEnforceHarness(agent: string, tool = ""): boolean {
  const a = String(agent || "")
    .trim()
    .toLowerCase()
  if (PASS_THROUGH_AGENTS.has(a)) return false
  if (isPilotFamilyAgent(a)) return true
  // Plugin tools are Pilot-only; native bash/write with unknown agent stay stock OpenCode.
  if (!a && isPilotOnlyTool(tool)) return true
  return false
}

/** Installed Pilot agent ids (plugin-internal / install-manifest only). */
function listInstalledPilotAgentNames(): string[] {
  return [...ownedPilotAgentIds()].filter((n) => !PASS_THROUGH_AGENTS.has(n))
}

function isolateNativeOpenCodeAgents(agentBag: Record<string, unknown>): void {
  for (const name of NATIVE_OPENCODE_AGENTS) {
    const cur =
      agentBag[name] && typeof agentBag[name] === "object"
        ? { ...(agentBag[name] as Record<string, unknown>) }
        : {}
    const perm =
      cur.permission && typeof cur.permission === "object"
        ? { ...(cur.permission as Record<string, unknown>) }
        : {}
    perm.pilot_run = "deny"
    perm.pilotrun = "deny"
    perm.pilot_cli = "deny"
    perm.acp = "deny"
    denyPilotWorkflowSkills(perm)
    const tools =
      cur.tools && typeof cur.tools === "object"
        ? { ...(cur.tools as Record<string, unknown>) }
        : {}
    tools.pilot_run = false
    tools.pilotrun = false
    tools.pilot_cli = false
    tools.acp = false
    agentBag[name] = { ...cur, permission: perm, tools }
  }
}

function windowsPowershellPath(): string {
  const roots = [
    process.env.SystemRoot,
    process.env.SYSTEMROOT,
    process.env.windir,
    "C:\\Windows",
  ].filter((x): x is string => Boolean(x))
  for (const root of roots) {
    const p = resolve(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    if (existsSync(p)) return p
  }
  return ""
}

/**
 * OpenCode 1.18.18 on this machine switched bash from absolute powershell.EXE
 * to bare `cmd.exe`. The non-PS branch does ChildProcess.make(command, [], {shell:"cmd.exe"}).
 * Effect spawn then treats the whole `acp uo-query …` string as the executable
 * → NotFound: ChildProcess.spawn (ses_ff6fe, 2026-08-15 15:56).
 * Pin an absolute PowerShell so the PS branch (argv spawn) is used.
 *
 * Must not be applied to the global OpenCode config: that would change
 * Build/Plan bash. Pilot `acp` uses spawnSync({shell:false}) instead.
 */
function patchWindowsShell(cfg: Record<string, unknown>): Record<string, unknown> {
  if (process.platform !== "win32") return cfg
  const current = String(cfg.shell || "").trim()
  if (/powershell/i.test(current) && (!/[\\/]/.test(current) || existsSync(current))) {
    return cfg
  }
  const ps = windowsPowershellPath()
  if (ps) cfg.shell = ps
  return cfg
}

/**
 * AscendC-Pilot mode: Host Read of any directory is allow (no OpenCode ask).
 * `external_directory` is an OpenCode worktree transport workaround — not the
 * Pilot write boundary (lease + allowed paths). Does not change Build/Plan
 * Does not change Build/Plan edit/bash/skill/shell rules; those tabs only
 * get Pilot tools (`pilot_run` / `pilot_cli`) and Pilot workflow skill names denied.
 * Does not relax write/edit. Do not widen task beyond compose ceiling.
 * Mutates and returns cfg.
 */
function patchPilotReadPermissions(
  cfg: Record<string, unknown> | undefined,
): Record<string, unknown> {
  const out = cfg && typeof cfg === "object" ? cfg : {}
  const agentBag =
    out.agent && typeof out.agent === "object"
      ? (out.agent as Record<string, unknown>)
      : {}
  const mcpBag =
    out.mcp && typeof out.mcp === "object" ? (out.mcp as Record<string, unknown>) : {}
  const mcpServers = Object.keys(mcpBag)
  for (const name of listInstalledPilotAgentNames()) {
    const cur =
      agentBag[name] && typeof agentBag[name] === "object"
        ? { ...(agentBag[name] as Record<string, unknown>) }
        : {}
    const perm =
      cur.permission && typeof cur.permission === "object"
        ? { ...(cur.permission as Record<string, unknown>) }
        : {}
    perm.read = "allow"
    perm.external_directory = "allow"
    const tools =
      cur.tools && typeof cur.tools === "object"
        ? { ...(cur.tools as Record<string, unknown>) }
        : {}
    if (name === "ascendc-pilot") {
      delete perm["*"]
      perm.glob = "allow"
      perm.grep = "allow"
      perm.list = "allow"
      perm.pilot_run = "allow"
      perm.pilotrun = "allow"
      perm.pilot_cli = "allow"
      perm.acp = "deny"
      perm.skill = perm.skill || "allow"
      perm.question = perm.question || "allow"
      perm.todowrite = perm.todowrite || "allow"
      tools.pilot_run = true
      tools.pilotrun = true
      tools.pilot_cli = true
      tools.acp = false
    } else {
      cur.hidden = true
      cur.mode = cur.mode || "subagent"
      perm.webfetch = perm.webfetch || "deny"
      perm.websearch = perm.websearch || "deny"
      if (perm.task === undefined) perm.task = "deny"
      perm.skill = perm.skill || "deny"
      perm.pilot_run = "deny"
      perm.pilotrun = "deny"
      perm.acp = "deny"
      perm.pilot_cli = perm.pilot_cli || "allow"
      tools.pilot_run = false
      tools.pilotrun = false
      tools.acp = false
      tools.pilot_cli = true
      for (const server of mcpServers) {
        perm[`${server}_*`] = "deny"
      }
    }
    agentBag[name] = { ...cur, permission: perm, tools }
  }
  isolateNativeOpenCodeAgents(agentBag)
  injectHiddenChildPrompts(agentBag)
  out.agent = agentBag
  return out
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
  const session = String(process.env.ASCENDC_SESSION_ID || "").trim()
  const workflow = String(process.env.ASCENDC_WORKFLOW_ID || "").trim()
  return `${project}|${session}|${workflow}|${stateFile}|${mtime}`
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
  return resolve(openCodeHome(), "ascendc-harness-bin")
}

function cannRootCachePath(): string {
  return resolve(openCodeHome(), "ascendc-cann-root")
}

function readCachedCannRoot(): string {
  try {
    const cached = readFileSync(cannRootCachePath(), "utf-8").replace(/^\uFEFF/, "").trim()
    if (cached && existsSync(cached)) return cached
  } catch {
    /* ignore */
  }
  return ""
}

function injectHiddenChildPrompts(agentBag: Record<string, unknown>): void {
  const dir = resolve(openCodeHome(), "ascendc-pilot-plugin", "agents")
  let files: string[] = []
  try {
    files = readdirSync(dir).filter((f) => f.endsWith(".md") && f.toLowerCase() !== "readme.md")
  } catch {
    return
  }
  const owned = ownedPilotAgentIds()
  for (const f of files) {
    const name = f.slice(0, -3)
    if (!owned.has(name.toLowerCase())) continue
    if (name === "ascendc-pilot") continue
    let text = ""
    try {
      text = readFileSync(join(dir, f), "utf-8")
    } catch {
      continue
    }
    let body = text
    if (text.startsWith("---")) {
      const end = text.indexOf("\n---", 3)
      if (end >= 0) body = text.slice(end + 4).replace(/^\s*\n/, "")
    }
    const cur =
      agentBag[name] && typeof agentBag[name] === "object"
        ? { ...(agentBag[name] as Record<string, unknown>) }
        : {}
    cur.hidden = true
    cur.mode = cur.mode || "subagent"
    if (body.trim()) cur.prompt = body
    agentBag[name] = cur
  }
}

function envPathOf(env?: Record<string, string | undefined> | NodeJS.ProcessEnv): string {
  const bag = env || process.env
  return String(bag.PATH || bag.Path || process.env.PATH || process.env.Path || "")
}

function resolveAcpBin(): string {
  // Install scripts write the cache; Host adapter must not re-implement install discovery.
  const fromEnv = String(process.env.ASCENDC_HARNESS_BIN || "").trim()
  if (fromEnv && existsSync(fromEnv)) return fromEnv

  try {
    const cached = readFileSync(harnessBinCachePath(), "utf-8").replace(/^\uFEFF/, "").trim()
    if (cached && existsSync(cached)) return cached
  } catch {
    // ignore
  }

  // Windows spawn({shell:false}) does not apply PATHEXT. Never return a bare "acp"
  // name for plugin-internal ChildProcess — that is ENOENT even when acp.exe is on Path.
  if (process.platform === "win32") {
    for (const dir of envPathOf().split(delimiter)) {
      if (!dir) continue
      const p = resolve(dir, "acp.exe")
      if (existsSync(p)) return p
    }
  }

  // Bare name: Unix agent-facing bash stays `acp *`.
  return "acp"
}

type AuthorizeDaemon = {
  proc: ChildProcessWithoutNullStreams
  ready: boolean
}

let _authDaemon: AuthorizeDaemon | null = null
let _authReqSeq = 0

function authIpcDir(): string {
  return resolve(openCodeHome(), "ascendc-auth-ipc")
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
      reason_zh: `未找到 Pilot CLI (${acpBin}): ${String(result.error || result.status)}`,
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
    const dir = resolve(openCodeHome(), "ascendc-sessions")
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

function isRipgrepHostFailure(text: string): boolean {
  return /ripgrep execution failed|rg:\s*missing|cannot find.*\brg\b/i.test(text || "")
}

function resolveInstalledSkillPath(name: string): string {
  const n =
    String(name || "")
      .trim()
      .replace(/\\/g, "/")
      .split("/")
      .filter(Boolean)
      .pop() || ""
  if (!n || n.includes("..")) return ""
  const home = openCodeHome()
  // Plugin-internal only. Global ~/.config/opencode/skills/ is native OpenCode
  // discovery (Build/Plan). Do not read or recover from there.
  const candidates = [
    resolve(home, "ascendc-pilot-plugin", "skills", n, "SKILL.md"),
    resolve(home, "ascendc-pilot-plugin", "cognitive-skills", n, "SKILL.md"),
  ]
  for (const p of candidates) {
    try {
      if (existsSync(p)) return p
    } catch {
      /* ignore */
    }
  }
  return ""
}

function resolveInstalledSkillMd(name: string): string {
  const p = resolveInstalledSkillPath(name)
  if (!p) return ""
  try {
    return readFileSync(p, "utf8")
  } catch {
    return ""
  }
}

function listSkillSampleFiles(dir: string, limit = 10): string[] {
  if (!dir || !existsSync(dir)) return []
  const out: string[] = []
  const walk = (d: string) => {
    if (out.length >= limit) return
    let ents: string[] = []
    try {
      ents = readdirSync(d)
    } catch {
      return
    }
    for (const name of ents) {
      if (out.length >= limit) return
      const p = join(d, name)
      try {
        const st = statSync(p)
        if (st.isDirectory()) walk(p)
        else out.push(p)
      } catch {
        /* ignore */
      }
    }
  }
  walk(dir)
  return out
}

function formatSkillToolOutput(name: string, body: string, skillMdPath: string): string {
  const dir = skillMdPath ? dirname(skillMdPath) : ""
  const files = listSkillSampleFiles(dir)
  return [
    `<skill_content name="${name}">`,
    `# Skill: ${name}`,
    "",
    body.trim(),
    "",
    `Base directory for this skill: ${dir}`,
    "Relative paths in this skill (e.g., scripts/, reference/) are relative to this base directory.",
    "Note: file list is sampled.",
    "",
    "<skill_files>",
    files.map((file) => ` ${file} `).join("\n"),
    "</skill_files>",
    "</skill_content>",
  ].join("\n")
}

function createPilotSkillTool(): {
  description: string
  args: Record<string, { type: string; description: string }>
  execute: (args: Record<string, unknown>) => Promise<{ title: string; output: string; metadata: Record<string, unknown> }>
} {
  return {
    description:
      "Load an AscendC-Pilot workflow skill by name from the plugin-internal skills tree. Not registered as plugin.tool.skill (that would replace native Skill globally).",
    args: {
      name: {
        type: "string",
        description: "The name of the skill from available_skills",
      },
    },
    async execute(args: Record<string, unknown>) {
      const name = String(args.name || args.skill || args.skill_name || "").trim()
      const skillMdPath = resolveInstalledSkillPath(name)
      const body = skillMdPath ? resolveInstalledSkillMd(name) : ""
      if (!body) {
        return {
          title: name ? `skill ${name}` : "skill",
          output:
            `[ascendc-pilot] skill ${name || "(missing name)"} 未找到 SKILL.md。` +
            `请 Read ~/.config/opencode/ascendc-pilot-plugin/skills/<name>/SKILL.md。`,
          metadata: { name, ok: false },
        }
      }
      return {
        title: `Loaded skill: ${name}`,
        output: formatSkillToolOutput(name, body, skillMdPath),
        metadata: { name, dir: dirname(skillMdPath), ok: true },
      }
    },
  }
}

function tokenizeArgv(input: string): string[] {
  const out: string[] = []
  let cur = ""
  let quote = ""
  for (let i = 0; i < input.length; i++) {
    const ch = input[i]
    if (quote) {
      if (ch === quote) quote = ""
      else cur += ch
      continue
    }
    if (ch === '"' || ch === "'") {
      quote = ch
      continue
    }
    if (/\s/.test(ch)) {
      if (cur) {
        out.push(cur)
        cur = ""
      }
      continue
    }
    cur += ch
  }
  if (cur) out.push(cur)
  return out
}

function stripAcpPrefix(raw: string): string {
  return String(raw || "")
    .trim()
    .replace(/^(?:acp(?:\.exe|\.cmd)?)\s+/i, "")
}

function childSpawnEnv(project?: string): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = { ...process.env }
  if (process.platform === "win32") {
    const systemRoot = env.SystemRoot || env.SYSTEMROOT || "C:\\Windows"
    env.SystemRoot = systemRoot
    env.SYSTEMROOT = systemRoot
    if (!env.ComSpec) env.ComSpec = resolve(systemRoot, "System32", "cmd.exe")
    if (!env.PATHEXT) env.PATHEXT = ".COM;.EXE;.BAT;.CMD;.VBS;.JS;.MSC"
    const pathVal = envPathOf(env)
    env.PATH = pathVal
    env.Path = pathVal
  }
  env.PYTHONUNBUFFERED = "1"
  env.PYTHONIOENCODING = "utf-8"
  if (project) env.ASCENDC_PROJECT_ROOT = project
  const bin = resolveAcpBin()
  if (bin && bin !== "acp") env.ASCENDC_HARNESS_BIN = bin
  const cann = readCachedCannRoot()
  if (cann && !env.UO_CANN_ROOT) env.UO_CANN_ROOT = cann
  return env
}

const PILOT_CLI_ALLOWED_HEADS = new Set([
  "uo-query",
  "status",
  "inspect",
  "inspect-failure",
  "ro-search",
  "next",
  "scan-architectures",
  "abort",
  "answer",
  "interpret-user-turn",
  "retry-after-environment-fix",
])

function isPilotCliLongCommand(argv: string[]): boolean {
  const head = String(argv[0] || "").trim().toLowerCase()
  if (head === "start") return true
  if (head === "run-action") return true
  if (head === "drive") return true
  return false
}

function isPilotCliAllowedCommand(argv: string[]): boolean {
  const head = String(argv[0] || "").trim().toLowerCase()
  return PILOT_CLI_ALLOWED_HEADS.has(head)
}

function formatPilotCliOutput(opts: {
  stdout: string
  stderr: string
  err: string
  status: number | null
  timeout?: boolean
}): string {
  const parts: string[] = []
  const failed = Boolean(opts.err) || opts.status !== 0 || opts.timeout
  if (failed) {
    const code = opts.timeout ? "TIMEOUT" : `exit=${opts.status ?? "null"}`
    parts.push(`FAIL ${code}`)
  }
  const stdout = String(opts.stdout || "").trim()
  const stderr = String(opts.stderr || "").trim()
  const err = String(opts.err || "").trim()
  if (stdout) {
    parts.push(stdout)
    try {
      const jsonStart = stdout.indexOf("{")
      if (jsonStart >= 0) {
        const obj = JSON.parse(stdout.slice(jsonStart)) as Record<string, unknown>
        const zh = String(obj.message_zh || obj.hint_zh || "").trim()
        if (zh && !stdout.includes(zh)) parts.push(zh)
      }
    } catch {
      /* not json */
    }
  }
  if (stderr && stderr !== stdout) parts.push(stderr)
  if (err && err !== stderr) parts.push(err)
  if (opts.timeout) {
    parts.push(
      "短命令工具不可用于 uo-init drain。请用 Host 工具 pilot_run(workflow, project, architecture)。",
    )
  }
  const blob = parts.join("\n")
  if (/cann|UO_CANN_ROOT|ASCEND_CANN|impl\/include/i.test(blob)) {
    parts.push(
      "查 ~/.config/opencode/ascendc-cann-root；跑 python scripts/dev/check_cann.py；" +
        "必要时 python scripts/cann_extract.py --fixup --dest <pkg>。",
    )
  }
  return parts.join("\n").trim() || `(pilot_cli exited ${opts.status})`
}

function createPilotRunStub(err: unknown): Record<string, unknown> {
  const detail = String(err || "unknown").slice(0, 1200)
  return {
    pilot_run: {
      description:
        "Run an AscendC-Pilot workflow via Host Session Driver (start→auto). " +
        "Always present even when the driver failed to load.",
      args: {
        workflow: { type: "string", description: "Workflow id (uo-init, tg-init, ce-review, …). Never uo-query." },
        project: { type: "string", description: "Operator package absolute path" },
        architecture: { type: "string", description: "Optional arch* (required for uo-init/uo-update)" },
        intent: { type: "string", description: "User product intent verbatim" },
        force_new: { type: "boolean", description: "Wipe only when the user asked to 删除重开" },
      },
      async execute() {
        return {
          title: "pilot_run unavailable",
          output:
            "[ascendc-pilot] pilot-driver 加载失败，pilot_run 不可用。\n" +
            detail +
            "\n请完全退出 OpenCode，运行 .\\refresh-opencode.ps1 或 SKIP_PIP=1 ./install.sh opencode 后重开。",
          metadata: { ok: false, error: "PILOT_DRIVER_LOAD_FAILED" },
        }
      },
    },
  }
}

/**
 * Short ACP CLI. Not named `acp` — that collides with OpenCode ACP protocol
 * and can drop the whole plugin tool bag (ses_fefd). Long start/auto is
 * `pilot_run` only (streaming; no 120s/180s bash timeout).
 */
function createPilotCliTool(): {
  description: string
  args: Record<string, { type: string; description: string }>
  execute: (
    args: Record<string, unknown>,
    ctx?: Record<string, unknown>,
  ) => Promise<{ title: string; output: string; metadata: Record<string, unknown> }>
} {
  return {
    description:
      "Short AscendC-Pilot CLI (plugin tool `pilot_cli`, not bash). " +
      "Pass command as argv after the binary (example: " +
      "`uo-query --project <operator-abs> s1Inner`). Never `--mode`. " +
      "Workflows: use Host tool `pilot_run`. Do not call `--help`.",
    args: {
      command: {
        type: "string",
        description:
          "CLI argv after the binary (example: `uo-query --project <operator-abs> s1Inner`). " +
          "Do not pass --help / -h. Do not pass start / run-action auto (use pilot_run). Allowed: uo-query, status, inspect, inspect-failure, ro-search, next, scan-architectures, interpret-user-turn, retry-after-environment-fix.",
      },
    },
    async execute(args: Record<string, unknown>, ctx?: Record<string, unknown>) {
      noteLiveSession(String(ctx?.sessionID || ctx?.sessionId || ""))
      const raw = String(args.command || args.cmd || args.argv || "").trim()
      if (!raw) {
        return {
          title: "pilot_cli",
          output:
            "[ascendc-pilot] pilot_cli requires command, e.g. " +
            "`uo-query --project <operator-abs> <identifier>`. Workflows: use pilot_run.",
          metadata: { ok: false, error: "missing_command" },
        }
      }
      const full = /^(?:acp(?:\.exe|\.cmd)?)(\s|$)/i.test(raw) ? raw : `acp ${raw}`
      const hasExplicitProject = Boolean(extractProjectFromAcpCommand(full))
      const diagnostic = isAcpDiagnosticCommand(full)
      const projectHint =
        diagnostic && !hasExplicitProject ? "" : uoQueryPickProject(args, raw)
      if (isAcpHelpCommand(full) || raw === "-h" || raw === "--help" || raw === "help") {
        return {
          title: "pilot_cli help",
          output: PILOT_CLI_HELP_USAGE_CARD,
          metadata: { ok: false, error: "help_usage_card" },
        }
      }
      const rewritten = projectHint ? rewriteAcpProjectFlag(full, projectHint) : full
      const stripped = stripAcpPrefix(rewritten)
      const argv = tokenizeArgv(stripped)
      if (!argv.length) {
        return {
          title: "pilot_cli",
          output: "[ascendc-pilot] pilot_cli command parsed empty.",
          metadata: { ok: false, error: "empty_argv" },
        }
      }
      if (isPilotCliLongCommand(argv)) {
        return {
          title: `pilot_cli ${argv[0]}`,
          output:
            "[ascendc-pilot] start / run-action 必须用 Host 工具 `pilot_run(workflow, project, architecture)`。\n" +
            "`pilot_cli` 可做 uo-query / status / inspect / inspect-failure / ro-search / next / scan-architectures / interpret-user-turn / retry-after-environment-fix。",
          metadata: { ok: false, error: "USE_PILOT_RUN" },
        }
      }
      if (!isPilotCliAllowedCommand(argv)) {
        const head = String(argv[0] || "").trim()
        return {
          title: `pilot_cli ${head}`,
          output:
            `[ascendc-pilot] \`pilot_cli\` 不执行 \`${head}\`。查询只用四种 \`uo-query\` 形态` +
            "（标识符 / Dim=V / --file --line / 无参数索引）。\n" +
            "允许：uo-query / status / inspect / inspect-failure / ro-search / next / scan-architectures / abort / answer / interpret-user-turn / retry-after-environment-fix。\n" +
            "工作流用 Host `pilot_run`。不要 `uo impact` / `search` / `locate` / `explain-*`。",
          metadata: { ok: false, error: "USE_UO_QUERY" },
        }
      }
      const project =
        extractProjectFromAcpCommand(rewritten) ||
        projectHint ||
        (diagnostic ? "" : readRememberedProjectRoot() || detectProjectRoot()) ||
        hostOpenDirectory ||
        process.cwd()
      const sessionId = String(ctx?.sessionID || ctx?.sessionId || "")
      rememberSessionAgent(sessionId, String(ctx?.agent || ctx?.sessionAgent || ""))
      let agent = resolveAgent({
        agent: ctx?.agent as string | undefined,
        sessionAgent: ctx?.sessionAgent as string | undefined,
        sessionID: sessionId,
      })
      if (agent && !shouldEnforceHarness(agent, "pilot_cli")) {
        return {
          title: "pilot_cli",
          output:
            "[ascendc-pilot] pilot_cli 只在 AscendC-Pilot Tab 可用。Build / Plan 使用 OpenCode 原生权限，不走 Pilot harness。",
          metadata: { ok: false, error: "HARNESS_INACTIVE" },
        }
      }
      if (!agent) agent = "ascendc-pilot"
      const action = String(args.action || args.action_id || process.env.ASCENDC_ACTION || "")
      const verdict = runAuthorize({
        tool: "pilot_cli",
        command: stripped,
        agent,
        action,
        project,
        sessionId,
      })
      if (verdict.decision === "deny" || (verdict.ok === false && verdict.decision !== "ask")) {
        return {
          title: `pilot_cli ${argv[0]}`,
          output: denyMessage(verdict, "pilot_cli", stripped),
          metadata: { ok: false, error: verdict.reason_code || "denied" },
        }
      }
      const acpBin = resolveAcpBin()
      if (!acpBin || (acpBin === "acp" && process.platform === "win32")) {
        return {
          title: "pilot_cli",
          output:
            `[ascendc-pilot] harness binary not found (resolveAcpBin=${acpBin}). ` +
            `Run .\\refresh-opencode.ps1 so ~/.config/opencode/ascendc-harness-bin is rewritten. ` +
            `Do not search PATH or bash for the binary.`,
          metadata: { ok: false, error: "HARNESS_MISSING", bin: acpBin },
        }
      }
      const cwd = project && existsSync(project) ? project : undefined
      try {
        const res = spawnSync(acpBin, argv, {
          encoding: "utf-8",
          shell: false,
          windowsHide: true,
          cwd,
          env: childSpawnEnv(project),
          timeout: 180_000,
          maxBuffer: 8 * 1024 * 1024,
        })
        const stdout = String(res.stdout || "")
        const stderr = String(res.stderr || "")
        const err = res.error ? String(res.error) : ""
        const timedOut = /ETIMEDOUT|timed out/i.test(err)
        const output = formatPilotCliOutput({
          stdout,
          stderr,
          err,
          status: typeof res.status === "number" ? res.status : 1,
          timeout: timedOut,
        })
        return {
          title: `pilot_cli ${argv[0]}`,
          output,
          metadata: {
            ok: !res.error && res.status === 0,
            error: res.status === 0 ? undefined : err || `exit_${res.status}`,
            exit: res.status,
            bin: acpBin,
            argv,
            project,
          },
        }
      } catch (exc) {
        return {
          title: `pilot_cli ${argv[0]}`,
          output: formatPilotCliOutput({
            stdout: "",
            stderr: "",
            err: String(exc),
            status: 1,
            timeout: /timed out/i.test(String(exc)),
          }),
          metadata: { ok: false, error: "PILOT_CLI_THROW" },
        }
      }
    },
  }
}

function rgBinaryName(): string {
  return process.platform === "win32" ? "rg.exe" : "rg"
}

function openCodeRgBinDirs(): string[] {
  const home = homedir()
  const localApp = process.env.LOCALAPPDATA || resolve(home, "AppData", "Local")
  const xdgCache = process.env.XDG_CACHE_HOME || ""
  const dirs = [
    resolve(home, ".local", "share", "opencode", "bin"),
    resolve(home, ".cache", "opencode", "bin"),
    resolve(localApp, "opencode", "bin"),
  ]
  if (xdgCache) dirs.push(resolve(xdgCache, "opencode", "bin"))
  return [...new Set(dirs)]
}

function whichRg(): string {
  const exe = rgBinaryName()
  for (const dir of String(process.env.PATH || "").split(delimiter)) {
    if (!dir) continue
    const p = resolve(dir, exe)
    if (existsSync(p)) return p
  }
  return ""
}

function rgSeedSources(): string[] {
  const home = homedir()
  const localApp = process.env.LOCALAPPDATA || resolve(home, "AppData", "Local")
  const exe = rgBinaryName()
  return [
    whichRg(),
    resolve(home, ".local", "share", "opencode", "bin", exe),
    resolve(localApp, "Programs", "cursor", "resources", "app", "node_modules", "@vscode", "ripgrep", "bin", exe),
    resolve(
      localApp,
      "Programs",
      "Microsoft VS Code",
      "resources",
      "app",
      "node_modules",
      "@vscode",
      "ripgrep",
      "bin",
      exe,
    ),
  ].filter((p) => p && existsSync(p))
}

/** OpenCode 1.18 RipgrepBinary looks in xdgCache/opencode/bin, not data/bin. */
function ensureOpenCodeRipgrep(): void {
  const exe = rgBinaryName()
  const sources = rgSeedSources()
  const src = sources[0] || ""
  for (const dir of openCodeRgBinDirs()) {
    try {
      mkdirSync(dir, { recursive: true })
    } catch {
      continue
    }
    const dest = join(dir, exe)
    if (existsSync(dest) || !src) continue
    try {
      copyFileSync(src, dest)
    } catch {
      /* ignore */
    }
  }
  // Seed files only. Do not mutate process.env.PATH — that leaks into Build/Plan bash.
}

function prependOpenCodeRgPath(env: Record<string, string>): Record<string, string> {
  const prefix = openCodeRgBinDirs().join(delimiter)
  const cur = envPathOf(env)
  if (!prefix || !cur) return env
  const next = { ...env }
  next.PATH = prefix + delimiter + cur
  if (process.platform === "win32") next.Path = next.PATH
  return next
}

function acpBinDir(): string {
  const bin = resolveAcpBin()
  if (!bin || bin === "acp") return ""
  try {
    if (existsSync(bin)) return dirname(bin)
  } catch {
    return ""
  }
  return ""
}

/** Task children inherit a thin PATH; bare `acp` becomes NotFound (ses_ff9e follow-up). */
function prependAcpPath(env: Record<string, string>): Record<string, string> {
  const dir = acpBinDir()
  const bin = resolveAcpBin()
  const next = { ...env }
  if (bin && bin !== "acp") next.ASCENDC_HARNESS_BIN = bin
  if (!dir) return next
  const cur = envPathOf(next)
  if (!cur) return next
  if (cur.toLowerCase().split(delimiter.toLowerCase()).includes(dir.toLowerCase())) return next
  next.PATH = dir + delimiter + cur
  if (process.platform === "win32") next.Path = next.PATH
  return next
}

function ensureAcpOnPath(): void {
  const patched = prependAcpPath({
    PATH: envPathOf(),
    ...(process.env.Path ? { Path: String(process.env.Path) } : {}),
  })
  if (patched.PATH) process.env.PATH = patched.PATH
  if (patched.Path) process.env.Path = patched.Path
  if (patched.ASCENDC_HARNESS_BIN) process.env.ASCENDC_HARNESS_BIN = patched.ASCENDC_HARNESS_BIN
}

function injectCachedCannRoot(env: Record<string, string>): Record<string, string> {
  const cann = readCachedCannRoot()
  if (!cann || env.UO_CANN_ROOT) return env
  return { ...env, UO_CANN_ROOT: cann }
}

function prependPilotToolPath(env: Record<string, string>): Record<string, string> {
  ensureOpenCodeRipgrep()
  return injectCachedCannRoot(prependAcpPath(prependOpenCodeRgPath(env || {})))
}

function rgMissingRewrite(tool: string, skillName?: string): string {
  if (tool === "skill") {
    const hint = skillName ? `（${skillName}）` : ""
    return (
      `[ascendc-pilot] OpenCode skill 工具依赖 rg，本机 OpenCode PATH 没有 rg${hint}。` +
      `主控请 Read ~/.config/opencode/ascendc-pilot-plugin/skills/<name>/SKILL.md；` +
      `子代理请读 session method.md，不要用 skill。`
    )
  }
  return (
    `[ascendc-pilot] OpenCode 原生 ${tool} 需要 PATH 上的 rg（OpenCode 不使用 Cursor 自带的 rg）。` +
    `请用 pilot_cli command=\`uo-query --project <abs>\`，空了按 hint 再查，或 Read 已定位窗口。`
  )
}

/** Last skill name from tool.execute.before — after payload often has no args. */
let lastSkillName = ""

function recoverSkillToolOutput(
  input: Record<string, unknown> | undefined,
  output: Record<string, unknown> | undefined,
  tool: string,
): boolean {
  if (!output) return false
  if (tool !== "skill" && !tool.endsWith("skill")) return false
  const outArgs =
    output.args && typeof output.args === "object"
      ? (output.args as Record<string, unknown>)
      : {}
  const inArgs =
    input && typeof input.args === "object" ? (input.args as Record<string, unknown>) : {}
  const name = String(
    outArgs.name ||
      outArgs.skill ||
      outArgs.skill_name ||
      inArgs.name ||
      inArgs.skill ||
      lastSkillName ||
      "",
  ).trim()
  if (!isPilotManagedSkill(name)) return false
  const body = resolveInstalledSkillMd(name)
  const failed = isRipgrepHostFailure(
    `${extractToolError(output, tool)}\n${toolOutputText(output)}`,
  )
  if (!body && !failed) return false
  const text = body || rgMissingRewrite("skill", name)
  // OpenCode after-hook schema is { title, output, metadata }. Extra keys
  // (content) can reject the whole return and keep the original rg error.
  output.output = text
  output.title = name ? `Loaded skill: ${name}` : "skill"
  if ("error" in output) delete output.error
  if ("stderr" in output) delete output.stderr
  const meta =
    output.metadata && typeof output.metadata === "object"
      ? (output.metadata as Record<string, unknown>)
      : {}
  delete meta.error
  meta.recovered_skill = true
  output.metadata = meta
  return true
}

/** Pending Task registrations keyed by stable invocation id or dispatch_nonce. */
type PendingTaskReg = {
  registration_id: string
  dispatch_nonce: string
  action_id: string
  parent_session_id: string
  slice_id?: string
}

const pendingTaskRegs = new Map<string, PendingTaskReg>()

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
function extractSliceIdFromPrompt(prompt: string): string {
  const match = String(prompt || "").match(/(?:^|\n)\s*(?:AXIS|SLICE_ID)\s*=\s*([A-Za-z0-9_-]+)/i)
  return match ? String(match[1] || "").trim() : ""
}

function inflightSliceIds(): Set<string> {
  const out = new Set<string>()
  for (const reg of pendingTaskRegs.values()) {
    const sid = String(reg.slice_id || "").trim()
    if (sid) out.add(sid)
  }
  return out
}

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
      reg: PendingTaskReg
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
  if (/ripgrep execution failed|rg:\s*missing/i.test(text)) {
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

function quoteProjectArg(root: string): string {
  return `"${String(root || "").replace(/"/g, '\\"')}"`
}

function rewriteAcpProjectFlag(command: string, operatorRoot: string): string {
  const cmd = String(command || "")
  const root = String(operatorRoot || "").trim()
  if (!cmd || !root || !looksLikeOperatorDir(root)) return cmd
  if (!/\bacp(\.cmd|\.exe)?(\s|$)/i.test(cmd)) return cmd
  if (isAcpHelpCommand(cmd)) return cmd
  const quoted = `--project ${quoteProjectArg(root)}`
  const flag = /--project(?:\s+|=)(?:"[^"]*"|'[^']*'|\S+)/i
  if (flag.test(cmd)) {
    const current = extractProjectFromAcpCommand(cmd)
    if (current && looksLikeOperatorDir(current) && !isUnderHarnessCheckout(current)) {
      return cmd
    }
    return cmd.replace(flag, quoted)
  }
  return `${cmd} ${quoted}`
}

function pinOperatorBashContext(args: Record<string, unknown>, operatorRoot: string): void {
  const root = String(operatorRoot || "").trim()
  if (!root || !looksLikeOperatorDir(root) || isHarnessCheckout(root)) return
  const cwdNow = String(args.cwd || args.workdir || args.working_directory || "").trim()
  if (!cwdNow || isHarnessCheckout(cwdNow) || !looksLikeOperatorDir(cwdNow)) {
    args.workdir = root
  }
  const command = String(args.command || args.cmd || "")
  if (command) {
    const rewritten = rewriteAcpProjectFlag(command, root)
    if (rewritten !== command) {
      if ("command" in args) args.command = rewritten
      if ("cmd" in args) args.cmd = rewritten
      if (!("command" in args) && !("cmd" in args)) args.command = rewritten
    }
  }
  // Do NOT set args.env / args.cwd. OpenCode bash schema is
  // {command, workdir?, timeout?, description}. Extra env trains the LLM to
  // pass a non-schema field (ses_ff6fe: "env param is malformed"). Zod strips
  // it; a partial env would also stomp PATHEXT/SystemRoot if it ever leaked.
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
  // Pin bash cwd / env to the operator package when Host supports it.
  // Do NOT overwrite OpenCode Task `location.directory` — that is the Host
  // session project used for skill/agent discovery. Overwriting it to the
  // operator package made children unable to load workflow skills (ses_ffba).
  // Do NOT set Task cwd/workdir either: OpenCode may treat that as the child
  // session directory. Bash cwd is pinned in pinOperatorBashContext instead.
  // Consequence: operator-package Reads are OpenCode `external_directory`.
  // Compose sets permission.external_directory=allow on Pilot agents so the
  // child's first Read of session prompt.md is not an ask/red error.
  // acp still binds the operator via --project / ASCENDC_PROJECT_ROOT.
  // Identity travels via env/metadata only — do NOT mutate Task prompt body
  // (ses_0622: prefix + FIX ONLY identity churn). Finalize trusts artifact_identity.
  const envBag = (args.env || args.environment || args.envVars) as Record<string, string> | undefined
  const envPatch: Record<string, string> = {}
  if (action) envPatch.ASCENDC_ACTION = action
  if (actor) envPatch.ASCENDC_AGENT = actor
  if (projectRoot && !isHarnessCheckout(projectRoot)) envPatch.ASCENDC_PROJECT_ROOT = projectRoot
  if (envBag && typeof envBag === "object") {
    Object.assign(envBag, envPatch)
  } else {
    args.env = { ...envPatch }
  }
}


const uoQueryPendingByProject = new Map<string, string>()
const UO_QUERY_NATIVE_TASK_RESULT_CAP = 200_000

function collectTaskStrings(value: unknown, depth: number): string[] {
  if (depth < 0 || value == null) return []
  if (typeof value === "string") {
    const text = value.trim()
    return text ? [value] : []
  }
  if (Array.isArray(value)) {
    const out: string[] = []
    for (const item of value) out.push(...collectTaskStrings(item, depth - 1))
    return out
  }
  if (typeof value === "object") {
    const rec = value as Record<string, unknown>
    const out: string[] = []
    for (const key of ["output", "content", "message", "text", "result", "answer"]) {
      if (key in rec) out.push(...collectTaskStrings(rec[key], depth - 1))
    }
    for (const key of ["parts", "messages", "data"]) {
      if (key in rec) out.push(...collectTaskStrings(rec[key], depth - 1))
    }
    return out
  }
  return []
}

function uoQueryTaskText(output: Record<string, unknown> | undefined): string {
  if (!output) return ""
  return collectTaskStrings(output, 4).join("\n").slice(0, UO_QUERY_NATIVE_TASK_RESULT_CAP)
}

function fillEmptyUoQueryTaskOutput(
  output: Record<string, unknown> | undefined,
  args: Record<string, unknown>,
): void {
  if (!output || !isUoQueryTask(args)) return
  if (uoQueryTaskText(output).trim()) return
  const recovered = collectTaskStrings(output, 5).join("\n").trim()
  output.output = recovered
    ? recovered.slice(0, UO_QUERY_NATIVE_TASK_RESULT_CAP)
    : "(empty native task_result; use the child session last assistant message)"
}

function uoQueryPickProject(args: Record<string, unknown>, command = ""): string {
  const env =
    args.env && typeof args.env === "object"
      ? (args.env as Record<string, unknown>)
      : args.environment && typeof args.environment === "object"
        ? (args.environment as Record<string, unknown>)
        : {}
  const explicit = String(
    env.ASCENDC_PROJECT_ROOT ||
      args.project ||
      args.project_root ||
      args.cwd ||
      args.workdir ||
      "",
  ).trim()
  if (explicit) {
    try {
      const resolved = resolve(explicit)
      if (looksLikeOperatorDir(resolved) && !isHarnessCheckout(resolved)) return resolved
    } catch {
      /* fall through */
    }
  }
  const blob = `${command}\n${String(args.prompt || args.description || args.task || "")}`
  const bound = boundOperatorRoot(explicit || blob)
  if (bound) return bound
  const cached = readRememberedProjectRoot()
  return cached ? resolve(cached) : ""
}

function isUoQueryTask(args: Record<string, unknown>): boolean {
  const actor = String(
    args.agent || args.subagent || args.subagent_type || args.subagentType || args.name || "",
  ).toLowerCase()
  const action = String(args.action || args.action_id || args.actionId || "").toLowerCase()
  return actor === "uo-query" || action === "kb_lookup"
}

function isKbLookupFinalize(command: string): boolean {
  const text = String(command || "")
  return /\bacp\s+run-action\s+kb_lookup\b/i.test(text) && /--finalize\b/i.test(text)
}

function injectUoQueryResult(args: Record<string, unknown>, project: string, resultText: string): void {
  const existing =
    args.env && typeof args.env === "object"
      ? ({ ...(args.env as Record<string, unknown>) } as Record<string, unknown>)
      : args.environment && typeof args.environment === "object"
        ? ({ ...(args.environment as Record<string, unknown>) } as Record<string, unknown>)
        : ({} as Record<string, unknown>)
  existing.ASCENDC_ACTION_RESULT = resultText
  existing.ASCENDC_ACTION_RESULT_PROJECT = project
  existing.ASCENDC_ACTION_RESULT_ACTION = "kb_lookup"
  args.env = existing
  process.env.ASCENDC_ACTION_RESULT = resultText
  process.env.ASCENDC_ACTION_RESULT_PROJECT = project
  process.env.ASCENDC_ACTION_RESULT_ACTION = "kb_lookup"
}

function clearUoQueryResult(project: string): void {
  if (project) uoQueryPendingByProject.delete(resolve(project))
  delete process.env.ASCENDC_ACTION_RESULT
  delete process.env.ASCENDC_ACTION_RESULT_PROJECT
  delete process.env.ASCENDC_ACTION_RESULT_ACTION
}

/** Capture uo-query Task text. Primary synthesizes; do not kb_lookup --finalize.
 * This hook must not finalize itself (avoids a double-finalize race). */
function captureUoQueryTaskReturn(
  tool: string,
  args: Record<string, unknown>,
  output: Record<string, unknown> | undefined,
): void {
  if (tool === "task" || tool === "subagent" || tool === "task_tool") {
    if (!isUoQueryTask(args)) return
    fillEmptyUoQueryTaskOutput(output, args)
    const text = uoQueryTaskText(output)
    if (!String(text || "").trim()) return
    const project = uoQueryPickProject(args)
    if (!project) return
    const blob = `${args.prompt || ""}\n${args.description || ""}\n${args.task || ""}`
    if (/\bSLICE_ID=/.test(blob)) {
      if (output) {
        const oldMeta =
          output.metadata && typeof output.metadata === "object"
            ? (output.metadata as Record<string, unknown>)
            : {}
        output.metadata = {
          ...oldMeta,
          ascendc_uo_query_return_value: {
            captured: false,
            skipped: "fanout_slice",
            transport: "primary_synthesize",
            project,
          },
        }
      }
      return
    }
    uoQueryPendingByProject.set(project, text)
    if (output) {
      const oldMeta =
        output.metadata && typeof output.metadata === "object"
          ? (output.metadata as Record<string, unknown>)
          : {}
      output.metadata = {
        ...oldMeta,
        ascendc_uo_query_return_value: {
          captured: true,
          transport: "next_primary_finalize",
          project,
        },
      }
    }
    return
  }
  if (tool === "bash" || tool === "shell" || tool === "terminal") {
    const command = String(args.command || args.cmd || "")
    if (!isKbLookupFinalize(command)) return
    clearUoQueryResult(uoQueryPickProject(args, command))
  }
}

export const AscendCHarnessPlugin = async (ctx?: {
  client?: unknown
  directory?: string
  project?: unknown
  $?: unknown
}) => {
  ensureOpenCodeRipgrep()
  try {
    const rawDir = String(ctx?.directory || "").trim()
    hostOpenDirectory = rawDir ? resolve(rawDir) : ""
  } catch {
    hostOpenDirectory = ""
  }
  liveSessionId = ""
  const client = ctx && typeof ctx === "object" ? (ctx as any).client : undefined
  let pilotTools: Record<string, unknown> = {}
  let capturePilotToolSession:
    | ((input: Record<string, unknown>, output?: Record<string, unknown>) => void)
    | undefined
  let submitDispatchResult:
    | ((project: string, ticket: string, resultText: string) => Promise<Record<string, unknown>>)
    | undefined
  let extractKbAnswer: ((text: string) => string) | undefined
  let nativeTaskResultCap = 200_000
  let readPendingDispatch: ((project: string) => Record<string, unknown> | null) | undefined
  let clearPendingDispatch: ((project: string) => void) | undefined
  let rememberPendingDispatch:
    | ((entry: {
        project: string
        ticket: string
        actor: string
        action: string
        ts: number
      }) => void)
    | undefined
  let driveContinueGoalAfterAck:
    | ((args: {
        client: unknown
        pluginInput?: { directory?: string; serverUrl?: unknown }
        step: Record<string, unknown>
        sessionId?: string
      }) => Promise<Record<string, unknown>>)
    | undefined
  try {
    // OpenCode autoloads every *.ts in ~/.config/opencode/plugins/.
    // pilot-driver.ts is a library — load it from the installed bundle, never
    // from the plugins/ root (that path is treated as a second plugin factory).
    const bundled = resolve(
      openCodeHome(),
      "ascendc-pilot-plugin",
      "opencode-plugin",
      "pilot-driver.ts",
    )
    const mod = existsSync(bundled)
      ? await import(pathToFileURL(bundled).href)
      : await import("./pilot-driver")
    capturePilotToolSession = mod.capturePilotToolSession
    submitDispatchResult = mod.submitDispatchResult
    extractKbAnswer = mod.extractKbAnswer
    if (typeof mod.NATIVE_TASK_RESULT_CAP === "number") {
      nativeTaskResultCap = mod.NATIVE_TASK_RESULT_CAP
    }
    readPendingDispatch = mod.readPendingDispatch
    clearPendingDispatch = mod.clearPendingDispatch
    rememberPendingDispatch = mod.rememberPendingDispatch
    driveContinueGoalAfterAck = mod.driveContinueGoalAfterAck
    pilotTools = mod.createPilotRunTool(client, ctx) || {}
  } catch (err) {
    console.error("[ascendc-pilot] failed to load pilot-driver", err)
    pilotTools = createPilotRunStub(err) as Record<string, unknown>
  }
  // Do not assign plugin.tool.skill: that replaces native Skill globally and
  // leaks into Build/Plan. Pilot after-hook recovers plugin-internal SKILL.md.
  // Never register a tool named `acp` — OpenCode ACP protocol last-write-wins
  // can drop the whole plugin tool bag (ses_fefd: no pilot_run, no CLI).
  if (!pilotTools || typeof pilotTools !== "object") {
    pilotTools = createPilotRunStub("createPilotRunTool returned empty") as Record<string, unknown>
  }
  const bag = pilotTools as Record<string, unknown>
  if (!bag.pilot_run && !bag.pilotrun) {
    Object.assign(bag, createPilotRunStub("createPilotRunTool omitted pilot_run"))
  }
  bag.pilot_cli = createPilotCliTool()
  delete bag.acp

  return {
    // OpenCode 1.18 calls N.config / N.dispose on every loaded plugin.
    // Must return an object (undefined → schema rejection). Patches Pilot
    // agents so operator-package Reads are not `external_directory` ask.
    config: async (cfg?: Record<string, unknown>) => patchPilotReadPermissions(cfg),
    dispose: async () => ({}),
    tool: pilotTools,
    "shell.env": async (
      input: { cwd?: string; sessionID?: string; callID?: string },
      output: { env: Record<string, string> },
    ) => {
      const agent = resolveAgent({ sessionID: input.sessionID || "" })
      if (!shouldEnforceHarness(agent, "bash")) {
        return
      }
      const bag = output.env && typeof output.env === "object" ? output.env : {}
      const patched = prependPilotToolPath(bag)
      Object.assign(bag, patched)
      noteLiveSession(input.sessionID)
      const root = readRememberedProjectRoot()
      if (root) bag.ASCENDC_PROJECT_ROOT = root
      output.env = bag
    },
    "chat.message": async (
      input: { sessionID?: string; agent?: string },
      output?: { message?: unknown; parts?: unknown },
    ) => {
      rememberSessionAgent(String(input.sessionID || ""), String(input.agent || ""))
      noteLiveSession(input.sessionID)
      const agent = String(input.agent || "").trim()
      if (agent && !isPrimaryPilotAgent(agent) && !isPrimaryPilotAgent(resolveAgent({ sessionID: input.sessionID || "" }))) {
        return
      }
      const project = detectProjectRoot() || readRememberedProjectRoot()
      if (!project || !getPending(project)) return
      const text = extractUserTurnText(output)
      const interpreted = runAcpInterpretUserTurn(project, text, "user_message")
      if (
        interpreted.ok &&
        (interpreted.disposition === "answered" || interpreted.disposition === "superseded")
      ) {
        clearPending(project)
        const sid = String(input.sessionID || "").trim()
        if (sid && interpreted.messageZh) lastUserTurnNote.set(sid, interpreted.messageZh)
      }
    },
    "experimental.chat.system.transform": async (
      input: { sessionID?: string },
      output: { system?: string[] },
    ) => {
      const sid = String(input.sessionID || "").trim()
      const note = sid ? lastUserTurnNote.get(sid) : ""
      if (!note) return
      lastUserTurnNote.delete(sid)
      const system = Array.isArray(output.system) ? output.system : []
      system.push(note)
      output.system = system
    },
    "chat.params": async (input: { sessionID?: string; agent?: string }) => {
      rememberSessionAgent(String(input.sessionID || ""), String(input.agent || ""))
    },
    "chat.headers": async (input: { sessionID?: string; agent?: string }) => {
      rememberSessionAgent(String(input.sessionID || ""), String(input.agent || ""))
    },
    "tool.execute.before": async (
      input: {
        tool?: string
        agent?: string
        sessionAgent?: string
        sessionID?: string
        sessionId?: string
      },
      output: { args?: Record<string, unknown> },
    ) => {
      const tool = String(input.tool || "").toLowerCase()
      const args = output.args || {}
      const command = String(args.command || args.cmd || "")
      const sessionId = extractHostSessionId(input as Record<string, unknown>)
      rememberSessionAgent(sessionId, String(input.agent || input.sessionAgent || ""))
      noteLiveSession(sessionId)
      let agent = resolveAgent({ ...input, sessionID: sessionId })
      // Build / Plan / other non-Pilot tabs: stock OpenCode permissions, no harness.
      if (!shouldEnforceHarness(agent, tool)) {
        return output
      }
      capturePilotToolSession?.(input as Record<string, unknown>, output as Record<string, unknown>)
      const isSkillToolEarly = tool === "skill" || tool.endsWith("skill")
      if (isSkillToolEarly) {
        lastSkillName = String(args.name || args.skill || args.skill_name || "").trim()
      }
      // OpenCode todowrite schema requires priority — inject when Host omitted it.
      if (tool === "todowrite" || tool === "todo_write" || (tool.includes("todo") && tool.includes("write"))) {
        ensureTodowritePriority(args)
      }
      if (!agent && isPilotOnlyTool(tool)) agent = "ascendc-pilot"

      if ((tool === "bash" || tool === "shell" || tool === "terminal") && isKbLookupFinalize(command)) {
        const projectHint = uoQueryPickProject(args, command)
        const resultText = projectHint ? uoQueryPendingByProject.get(projectHint) : ""
        if (projectHint && resultText) injectUoQueryResult(args, projectHint, resultText)
      }
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
      agent = resolveEffectiveAgent(
        { ...input, agent, sessionAgent: agent, sessionID: sessionId },
        active,
        tool,
        command,
      )

      const nativeTools = new Set([
        "bash",
        "shell",
        "terminal",
        "write",
        "edit",
        "apply_patch",
        "strreplace",
        "patch",
        "read",
        "glob",
        "grep",
        "list",
        "search",
        "task",
        "subagent",
        "task_tool",
        "skill",
        "todowrite",
        "todo_write",
        "webfetch",
        "websearch",
        "question",
        "askquestion",
        "ask_question",
        "lsp",
        "pilot_cli",
        "pilot_run",
        "pilotrun",
      ])
      const isMcpTool = !nativeTools.has(tool) && tool.includes("_")
      if (isMcpTool && agent !== "ascendc-pilot") {
        throw new Error(
          `[ascendc-pilot] MCP tool '${tool}' is denied for Pilot child '${agent}'. Use pilot_cli / session METHOD.`,
        )
      }
      if (
        agent !== "ascendc-pilot" &&
        (tool === "webfetch" || tool === "websearch")
      ) {
        throw new Error(
          `[ascendc-pilot] ${tool} is denied for Pilot child '${agent}'.`,
        )
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
        const isAnswerCli =
          tool === "pilot_cli" && /\banswer\b/i.test(command)
        const isInterpretCli =
          tool === "pilot_cli" && /\binterpret-user-turn\b/i.test(command)
        const isInspectCli =
          tool === "pilot_cli" && isAcpDiagnosticCommand(command)
        const isHelpBash =
          (tool === "bash" || tool === "shell" || tool === "terminal") && isAcpHelpCommand(command)
        const isResumeStartBash =
          (tool === "bash" || tool === "shell" || tool === "terminal") &&
          isAcpResumeStartCommand(command)
        // Host Driver owns AskQuestion + start --decision; do not deadlock
        // a second pilot_run after EXISTING_RUN left pending yaml on disk.
        const isPilotDriver = tool === "pilot_run" || tool === "pilotrun"
        const isSkillTool = tool === "skill" || tool.endsWith("skill")
        const isPrimaryReadonly =
          isPrimaryPilotAgent(agent) &&
          (tool === "read" ||
            tool === "glob" ||
            tool === "grep" ||
            tool === "list" ||
            tool === "search" ||
            ((tool === "bash" || tool === "shell" || tool === "terminal") &&
              isReadonlyInspectBash(command)) ||
            (tool === "pilot_cli" && isAcpDiagnosticCommand(command)))
        if (
          !isQuestion &&
          !isAnswerCli &&
          !isInterpretCli &&
          !isInspectCli &&
          !isHelpBash &&
          !isResumeStartBash &&
          !isPilotDriver &&
          !isSkillTool &&
          !isPrimaryReadonly
        ) {
          const allowed = pending.allowed_values.length
            ? ` allowed=${pending.allowed_values.join("|")}`
            : ""
          const prompt = pending.prompt_zh ? ` ${pending.prompt_zh}` : ""
          throw new Error(
            `[ascendc-pilot] human interaction pending (request_id=${pending.request_id}).` +
              `${prompt}${allowed}. ` +
              `If the user already replied in chat, call interpret-user-turn with that text — do not re-ask. ` +
              `Clicking the question UI also works. ` +
              `Primary may Read / Glob / Get-ChildItem / inspect-failure / status while the prompt is open. ` +
              `Do not Write, Task, or run domain CLI until the pending question is answered or superseded.`,
          )
        }
      }

      if (tool === "bash" || tool === "shell" || tool === "terminal") {
        // Do NOT rewrite agent bash to an absolute acp.exe path.
        // OpenCode frontmatter only allows `acp *`; rewriting to
        // `C:\...\Scripts\acp.exe --help` turns green allow into red deny (ses_00c4 follow-up).
        // resolveAcpBin() is only for this plugin's internal spawnSync(authorize).
        const diagnosticBare =
          isAcpDiagnosticCommand(command) && !extractProjectFromAcpCommand(command)
        if (!diagnosticBare) pinOperatorBashContext(args, project)
        const commandNow = String(args.command || args.cmd || command)
        const authorizeProject = diagnosticBare
          ? hostOpenDirectory || process.cwd()
          : project
        const verdict = runAuthorize({
          tool: "bash",
          command: commandNow,
          agent,
          action,
          project: authorizeProject,
          sessionId,
        })
        if (verdict.decision === "deny" || (verdict.ok === false && verdict.decision !== "ask")) {
          throw new Error(denyMessage(verdict, "bash", commandNow))
        }
        if (verdict.decision === "ask") {
          throw new Error(denyMessage(verdict, "bash", commandNow))
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
          sessionId,
        })
        if (verdict.decision === "deny" || verdict.ok === false) {
          throw new Error(denyMessage(verdict, "write", path))
        }
      }

      if (tool === "read" || tool === "glob" || tool === "grep" || tool === "list" || tool === "search") {
        const offset = args.offset ?? args.startLine ?? args.line
        const limit = args.limit ?? args.count
        const rangeCmd =
          tool === "read" && (offset != null || limit != null)
            ? `offset=${Number(offset || 1)} limit=${Number(limit || 0)}`
            : String(args.pattern || args.query || "")
        const verdict = runAuthorize({
          tool: tool === "list" || tool === "search" ? "glob" : tool,
          path,
          command: rangeCmd,
          agent,
          action,
          project,
          sessionId,
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
            const entry: PendingTaskReg = {
              registration_id: regId,
              dispatch_nonce: resolvedNonce,
              action_id: dispatchAction,
              parent_session_id: hostSession,
              slice_id: extractSliceIdFromPrompt(promptText),
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

      const isSkillToolNow = tool === "skill" || tool.endsWith("skill")
      if (isSkillToolNow) {
        const skillName = String(args.name || args.skill || args.skill_name || "").trim()
        const verdict = runAuthorize({
          tool: "skill",
          command: skillName,
          path: skillName,
          agent,
          action,
          project,
          sessionId,
        })
        if (verdict.decision === "deny" || (verdict.ok === false && verdict.decision !== "ask")) {
          throw new Error(denyMessage(verdict, "skill", skillName || "denied"))
        }
      }
      return output
    },
    "tool.execute.after": async (
      input: { tool?: string; agent?: string; sessionAgent?: string; sessionID?: string; sessionId?: string },
      output: Record<string, unknown> | undefined,
    ) => {
      try {
        const tool = String(input.tool || "").toLowerCase()
        const sessionIdEarly = extractHostSessionId(input as Record<string, unknown>)
        rememberSessionAgent(sessionIdEarly, String(input.agent || input.sessionAgent || ""))
        noteLiveSession(sessionIdEarly)
        const afterAgent = resolveAgent({ ...input, sessionID: sessionIdEarly })
        if (!shouldEnforceHarness(afterAgent, tool)) {
          return
        }
        recoverSkillToolOutput(input as Record<string, unknown>, output, tool)
        const errEarly = extractToolError(output, tool)
        const outTextEarly = `${errEarly}\n${toolOutputText(output)}`
        if (output && isRipgrepHostFailure(outTextEarly)) {
          if (tool === "grep" || tool === "glob") {
            output.output = rgMissingRewrite(tool)
            if ("error" in output) delete output.error
          }
        }
        const args = (output && typeof output.args === "object" ? output.args : {}) as Record<
          string,
          unknown
        >
        const path = String(
          args.filePath || args.path || args.file || args.filepath || args.target || "",
        )
        const command = String(args.command || args.cmd || "")
        captureUoQueryTaskReturn(tool, args, output)
        const isTaskTool = tool === "task" || tool === "subagent" || tool === "task_tool"
        const taskPromptHint = String(args.prompt || args.description || args.task || "")
        const fromCmd = extractProjectFromAcpCommand(command)
        const fromArgs = String(
          args.project || args.project_root || args.projectRoot || "",
        ).trim()
        const projectRaw = isTaskTool
          ? detectProjectRootForTask(taskPromptHint)
          : detectProjectRoot(fromCmd || fromArgs || path)
        const isQuestionTool =
          tool === "question" ||
          tool === "askquestion" ||
          tool === "ask_question" ||
          tool.includes("question")
        let project = projectRaw
        if (isQuestionTool) {
          const remembered = readRememberedProjectRoot()
          if (remembered && (!project || !getPending(project))) {
            project = remembered
          }
        }
        if (project) rememberProjectRoot(project)

        const err = extractToolError(output, tool)
        const outText = `${err}\n${toolOutputText(output)}`
        let recoveredRg = recoverSkillToolOutput(input as Record<string, unknown>, output, tool)
        if (output && isRipgrepHostFailure(outText) && !recoveredRg) {
          if (tool === "grep" || tool === "glob") {
            output.output = rgMissingRewrite(tool)
            if ("error" in output) delete output.error
            recoveredRg = true
          }
        }
        if (err && !recoveredRg) {
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
        if (isQuestionTool && project) {
          const pending = getPending(project)
          if (pending) {
            const value = extractQuestionAnswer(args, output)
            if (value) {
              const answered = runAcpAnswer(project, pending.request_id, value)
              if (answered.ok) {
                clearPending(project)
              } else {
                throw new Error(
                  `[ascendc-pilot] record answer failed: ${answered.detail}`.slice(0, 1500),
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
            return chunks.join("\n").slice(0, nativeTaskResultCap)
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

          const pendingDispatch = readPendingDispatch ? readPendingDispatch(project) : null
          const answerText = extractKbAnswer ? extractKbAnswer(resultText) : resultText
          if (
            pendingDispatch &&
            submitDispatchResult &&
            answerText &&
            String(pendingDispatch.ticket || "")
          ) {
            const opProject = String(pendingDispatch.project || project)
            const sliceId =
              String((hit && hit.reg.slice_id) || "").trim() ||
              extractSliceIdFromPrompt(taskPromptHint)
            const finished = await submitDispatchResult(
              opProject,
              String(pendingDispatch.ticket),
              answerText,
              { sliceId },
            )
            const waiting = Boolean(finished && finished.waiting_slices)
            if (finished && finished.ok !== false && !waiting) {
              clearPendingDispatch?.(opProject)
            }
            const next =
              finished && finished.host_step && typeof finished.host_step === "object"
                ? (finished.host_step as Record<string, unknown>)
                : {}
            if (String(next.kind || "") === "continue_goal" && driveContinueGoalAfterAck && client) {
              const continued = await driveContinueGoalAfterAck({
                client,
                pluginInput: ctx,
                step: next,
                sessionId: liveSessionId,
              })
              if (output && typeof output.output === "string") {
                const msg = String(
                  (continued &&
                    (continued.message_zh ||
                      continued.message ||
                      (continued.host_step &&
                        typeof continued.host_step === "object" &&
                        (continued.host_step as Record<string, unknown>).message_zh))) ||
                    "审查已收口，已继续 task_plan 下一格。",
                )
                output.output += `\n\n${msg}`
              }
            } else if (String(next.kind || "") === "dispatch_subagent" && rememberPendingDispatch) {
              rememberPendingDispatch({
                project: opProject,
                ticket: String(next.dispatch_ticket || pendingDispatch.ticket || ""),
                actor: String(next.actor_id || pendingDispatch.actor || ""),
                action: String(next.action_id || pendingDispatch.action || ""),
                ts: Date.now(),
                sessionId: liveSessionId,
              })
              if (output && typeof output.output === "string") {
                if (waiting) {
                  const remaining = Array.isArray(finished.remaining_slices)
                    ? finished.remaining_slices.map((s) => String(s || "").trim()).filter(Boolean)
                    : []
                  const inflight = inflightSliceIds()
                  const missing = remaining.filter((sid) => !inflight.has(sid))
                  output.output += missing.length
                    ? `\n\n切片未齐，禁止 finalize。请用 host_step.task_prompt_stub 原样派发剩余切片：${missing.join(", ")}。`
                    : "\n\n切片未齐，另一轴仍在运行。禁止现在 finalize。"
                } else {
                  output.output +=
                    "\n\n还有下一步子代理。请再调用 pilot_run（同一 project，不要 force_new）领取原生 Task。"
                }
              }
            }
          }
        }
      } catch {
        // fail-open
      }
      return output || {}
    },
  }
}

export default AscendCHarnessPlugin
