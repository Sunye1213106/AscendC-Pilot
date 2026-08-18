/**
 * Host Session Driver for AscendC-Pilot (OpenCode).
 *
 * Moves control-plane transport out of the Primary LLM:
 *   start → drive (host_step) → return dispatch_subagent → OpenCode native Task
 *   (user can jump into the child and see thinking) → plugin dispatch-result.
 *
 * Owns Todo sync and AskQuestion when Host APIs exist; falls back to a
 * structured ask_human payload only when the question UI cannot be invoked.
 *
 * Exposed as custom tool `pilot_run`.
 */

import { spawn } from "node:child_process"
import { existsSync, mkdirSync, readFileSync, unlinkSync, writeFileSync } from "node:fs"
import { resolve } from "node:path"
import { openCodeHome, readCachedCannRoot, resolveAcpBin } from "./opencode-home.mjs"
import {
  createToolRowProgressReporter,
  formatPilotElapsed,
  renderPilotProgressBar,
  withProgressArg,
} from "./pilot-progress.mjs"

export { formatPilotElapsed, renderPilotProgressBar, withProgressArg }

/** Test helper: parse ACP machine JSON from stdout, ignoring stderr heartbeats. */
export function parseAcpStdoutJson(
  stdout: string,
  stderr: string = "",
  exit?: number | null,
): Record<string, unknown> {
  const out = String(stdout || "").trim()
  const err = String(stderr || "").trim()
  const jsonStart = out.indexOf("{")
  if (jsonStart < 0) {
    const detail = (err || out).slice(0, 800)
    return {
      ok: false,
      error: "ACP_NO_JSON",
      message: detail,
      message_zh: detail || "ACP_NO_JSON",
      stdout: out.slice(0, 400),
      stderr: err.slice(0, 400),
      exit: exit ?? undefined,
    }
  }
  const slice = out.slice(jsonStart)
  try {
    return JSON.parse(slice) as Record<string, unknown>
  } catch {
    // Trailing logs after the JSON object must not turn a successful start into ACP_JSON_PARSE.
    let depth = 0
    for (let j = 0; j < slice.length; j++) {
      const ch = slice[j]
      if (ch === "{") depth++
      else if (ch === "}") {
        depth--
        if (depth === 0) {
          try {
            return JSON.parse(slice.slice(0, j + 1)) as Record<string, unknown>
          } catch {
            break
          }
        }
      }
    }
    return {
      ok: false,
      error: "ACP_JSON_PARSE",
      message: out.slice(0, 800),
      stdout: out.slice(0, 400),
      stderr: err.slice(0, 400),
      exit: exit ?? undefined,
    }
  }
}

const HOST_STEP_MODEL_KEYS = [
  "kind",
  "action_id",
  "actor_id",
  "message_zh",
  "dispatch_ticket",
  "ask_question",
  "next_workflow_id",
  "intent",
  "ticket_retryable",
  "quality_path",
  "unresolved_path",
  "answer_path",
  "answer_zh",
  "answer_status",
  "read_after_done",
  "task_prompt_stub",
  "tasks",
  "session_dir",
  "failed_action",
  "error_detail",
  "hint_zh",
  "suggested_fix",
  "issues",
  "stop_reason",
] as const

const HOST_STEP_TASK_KEYS = [
  "slice_id",
  "focus",
  "first_mode",
  "actor_id",
  "action_id",
  "task_prompt_stub",
] as const

function compactDispatchTasks(value: unknown): Array<Record<string, unknown>> | undefined {
  if (!Array.isArray(value) || value.length < 2) return undefined
  const out: Array<Record<string, unknown>> = []
  for (const row of value) {
    if (!row || typeof row !== "object") continue
    const rec = row as Record<string, unknown>
    const stub = String(rec.task_prompt_stub || "").trim()
    if (!stub) continue
    const compact: Record<string, unknown> = {}
    for (const key of HOST_STEP_TASK_KEYS) {
      const item = rec[key]
      if (item == null || item === "") continue
      compact[key] = item
    }
    compact.task_prompt_stub = stub
    out.push(compact)
  }
  return out.length >= 2 ? out : undefined
}

function compactHostStep(step: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const key of HOST_STEP_MODEL_KEYS) {
    const value = step[key]
    if (value == null || value === "") continue
    if (key === "tasks") {
      const tasks = compactDispatchTasks(value)
      if (tasks) out.tasks = tasks
      continue
    }
    out[key] = value
  }
  return out
}

/**
 * Model-facing pilot_run payload: host_step + message_zh + error code only.
 * Drive logs, todos, and full ACP blobs stay on the Host.
 */
export function compactPilotRunPayload(result: unknown): Record<string, unknown> {
  if (typeof result === "string") {
    return { ok: true, message_zh: result }
  }
  const rec =
    result && typeof result === "object"
      ? (result as Record<string, unknown>)
      : { ok: false, error: "EMPTY_RESULT" }
  const step =
    rec.host_step && typeof rec.host_step === "object"
      ? compactHostStep(rec.host_step as Record<string, unknown>)
      : {}
  const ok = rec.ok !== false
  const err = String(rec.error || rec.error_code || "")
  let messageZh = String(rec.message_zh || step.message_zh || rec.message || "")
  const errorDetail = String(step.error_detail || rec.error_detail || "")
  if (
    (!messageZh || messageZh === "deterministic_action_failed") &&
    errorDetail &&
    errorDetail !== "deterministic_action_failed"
  ) {
    messageZh = errorDetail
  }
  const out: Record<string, unknown> = { ok }
  if (Object.keys(step).length) out.host_step = step
  if (messageZh) out.message_zh = messageZh
  if (err) out.error = err
  if (rec.answer_from_source === true) out.answer_from_source = true
  if (rec.reason_code) out.reason_code = rec.reason_code
  const hintZh = String(rec.hint_zh || step.hint_zh || "")
  if (hintZh) out.hint_zh = hintZh
  if (rec.native_task === true) out.native_task = true
  if (rec.native_tasks === true) out.native_tasks = true
  return out
}

/**
 * OpenCode plugin tools must return a string or `{ output: string }`.
 * A bare object makes `result.output` undefined → Truncate.output does
 * `undefined.split("\n")` → `undefined is not an object (evaluating 'c.split')`.
 */
export function toPluginToolResult(result: unknown): {
  title: string
  output: string
  metadata: Record<string, unknown>
} {
  const rec = compactPilotRunPayload(result)
  const step =
    rec.host_step && typeof rec.host_step === "object"
      ? (rec.host_step as Record<string, unknown>)
      : {}
  const ok = rec.ok !== false
  const err = String(rec.error || "")
  const title = ok
    ? `pilot_run ${String(step.kind || "done")}`
    : `pilot_run ${err || step.kind || "failed"}`
  let output = ""
  try {
    output = JSON.stringify(rec)
  } catch {
    output = String(rec)
  }
  // Truncate.output crashes on undefined/empty in some OpenCode builds.
  if (!output) output = "{}"
  return {
    title,
    output,
    metadata: {
      ok,
      error: err || undefined,
      host_step_kind: step.kind,
    },
  }
}

export function isHumanDecision(payload: Record<string, unknown> | undefined | null): boolean {
  if (!payload || typeof payload !== "object") return false
  if (payload.ask_interrupted === true || payload.disposition === "superseded") return false
  if (payload.answered === true && payload.needs_human_decision === false) return false
  if (payload.needs_human_decision) return true
  const ask = payload.ask_question
  if (ask && typeof ask === "object" && Object.keys(ask as object).length) return true
  const step =
    payload.host_step && typeof payload.host_step === "object"
      ? (payload.host_step as Record<string, unknown>)
      : undefined
  if (step?.kind === "ask_human") return true
  if (step?.ask_question && typeof step.ask_question === "object") return true
  return false
}

/** `acp start` success is a workflow state blob; it historically omitted `ok: true`. */
export function isAcpStartSuccess(payload: Record<string, unknown> | undefined | null): boolean {
  if (!payload || typeof payload !== "object") return false
  if (payload.ask_interrupted === true || payload.disposition === "superseded") return false
  if (isHumanDecision(payload)) return false
  if (payload.ok === false) return false
  if (payload.ok === true) return true
  const status = String(payload.status || "").toLowerCase()
  if (payload.run_id && (payload.fresh_start === true || payload.resumed === true)) return true
  if (payload.run_id && (status === "running" || status === "passed")) return true
  return false
}

export function normalizeResumeDecision(raw: string): string {
  const key = String(raw || "").trim()
  if (!key) return ""
  const low = key.toLowerCase()
  if (
    low === "continue" ||
    low === "reinit" ||
    low === "query" ||
    low === "uo-init" ||
    low === "source"
  ) {
    return low
  }
  const aliases: Record<string, string> = {
    resume: "continue",
    reuse: "continue",
    继续: "continue",
    继续上次: "continue",
    reset: "reinit",
    "force-new": "reinit",
    force_new: "reinit",
    删除重开: "reinit",
    重开: "reinit",
    去查询: "query",
    query: "query",
    "uo-init": "uo-init",
    source: "source",
    源码作答: "source",
    回退到源码作答: "source",
  }
  if (aliases[key]) return aliases[key]
  if (aliases[low]) return aliases[low]
  if (key.startsWith("开始") || key.includes("继续")) return "continue"
  if (key.includes("删除") || key.includes("重开")) return "reinit"
  if (key.includes("源码")) return "source"
  if (key.includes("uo-init") || key.includes("CodeMap")) return "uo-init"
  if (key.includes("查询")) return "query"
  return ""
}

function sourceFallbackPayload(log: Array<Record<string, unknown>>, todo?: unknown): Record<string, unknown> {
  const messageZh =
    "开发者选择本次不建 CodeMap。请只读算子源码回答当前问题。" +
    "禁止再 Glob/dir/tree 找 .uo，禁止再调 pilot_cli uo-query。"
  return {
    ok: true,
    answered: true,
    needs_human_decision: false,
    answer_from_source: true,
    host_step: {
      kind: "answer_from_source",
      message_zh: messageZh,
    },
    message_zh: messageZh,
    log,
    todo,
  }
}

export function extractAskAnswer(answers: unknown): string {
  if (typeof answers === "string") return answers.trim()
  if (Array.isArray(answers)) {
    for (const item of answers) {
      const got = extractAskAnswer(item)
      if (got) return got
    }
    return ""
  }
  if (answers && typeof answers === "object") {
    const o = answers as Record<string, unknown>
    for (const k of ["label", "value", "answer", "selection", "choice", "text"]) {
      const v = o[k]
      if (typeof v === "string" && v.trim()) return v.trim()
    }
    if (o.answers != null) return extractAskAnswer(o.answers)
    const strings = Object.values(o).filter((v) => typeof v === "string" && String(v).trim())
    if (strings.length) return String(strings[strings.length - 1]).trim()
  }
  return ""
}

export type ProgressStep = { id: string; content: string }

export type ProgressReporter = {
  note: (title: string, detail?: string) => void
  applyStderrLine: (line: string) => void
  applyTodo: (todo: unknown) => void
  setWorkflow: (id: string) => void
  setStatus: (status: "running" | "ok" | "fail" | "ask" | "done") => void
  flush: () => void
  flushAsync: () => Promise<unknown>
  close: () => void
}

function stepsFromTodo(todo: unknown): ProgressStep[] {
  return extractTodoItems(todo).map((it) => ({ id: it.id, content: it.content }))
}

/** Host must not invent workflow steps. Progress comes from ACP `todo.todo_sync`. */
function defaultSteps(_workflow: string): ProgressStep[] {
  return []
}

export function parseAcpProgressLine(line: string): {
  kind: "run" | "ok" | "fail" | "advance" | "detail" | "ignore"
  id?: string
  label?: string
  detail?: string
} {
  const text = String(line || "").trim()
  if (!text) return { kind: "ignore" }
  const auto = text.match(/^\[acp-auto\]\s+(.*)$/)
  if (auto) {
    const msg = auto[1] || ""
    const run = msg.match(/^run\s+(\S+)(?:\s+\(phase=(\S+)\s*(.*)\))?/)
    if (run) {
      const label = String(run[3] || run[2] || run[1] || "").trim()
      return { kind: "run", id: run[1], label }
    }
    const ok = msg.match(/^(\S+)\s+ok\b/)
    if (ok) return { kind: "ok", id: ok[1] }
    const fail = msg.match(/^(\S+)\s+FAIL\b(.*)$/)
    if (fail) return { kind: "fail", id: fail[1], detail: msg }
    const adv = msg.match(/^advance\s+(\S+)(?:→|->)(\S+)/)
    if (adv) return { kind: "advance", id: adv[2], label: adv[2], detail: msg }
    if (/^drain (start|stop)\b/.test(msg)) return { kind: "detail", detail: msg }
    return { kind: "detail", detail: msg }
  }
  const uo = text.match(/^\[uo\]\s+(.*)$/)
  if (uo) return { kind: "detail", detail: uo[1] }
  const engine = text.match(/^\[acp-engine\]\s+(.*)$/)
  if (engine) return { kind: "detail", detail: engine[1] }
  return { kind: "ignore" }
}

function primitiveToolArgs(args: Record<string, unknown> | undefined): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  if (!args) return out
  for (const [key, value] of Object.entries(args)) {
    if (key === "progress") continue
    if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
      out[key] = value
    }
  }
  return out
}

function createProgressReporter(
  ctx: PilotToolContext | undefined,
  workflow: string,
  opts?: {
    client?: any
    sessionId?: string
    messageId?: string
    callID?: string
    serverUrl?: unknown
    directory?: string
    baseInput?: Record<string, unknown>
  },
): ProgressReporter {
  const state = {
    workflow: workflow || "pilot",
    steps: defaultSteps(workflow),
    currentId: "",
    currentLabel: "starting",
    detail: "",
    status: "running" as "running" | "ok" | "fail" | "ask" | "done",
    startedAt: Date.now(),
    closed: false,
  }
  let lastToastKey = ""
  let lastTodoAt = 0
  let lastTodoStage = ""
  const row = createToolRowProgressReporter({
    client: opts?.client,
    sessionId: resolvedSessionId(ctx, opts),
    messageId: String(opts?.messageId || ctx?.messageID || lastToolSession.messageID || "").trim(),
    callID: String(opts?.callID || ctx?.callID || lastToolSession.callID || "").trim(),
    serverUrl: opts?.serverUrl,
    directory: opts?.directory,
    baseInput: primitiveToolArgs(opts?.baseInput),
  })

  const currentIndex = (): number => {
    if (!state.steps.length) return 0
    const idx = state.steps.findIndex((s) => s.id === state.currentId)
    return idx >= 0 ? idx : 0
  }

  const render = (): string => {
    const total = state.steps.length || 1
    const idx = currentIndex()
    const done =
      state.status === "done" || state.status === "ok"
        ? total
        : state.status === "fail" || state.status === "ask"
          ? idx
          : idx
    const bar = renderPilotProgressBar(done, total)
    const n =
      state.status === "done" || state.status === "ok"
        ? `${total}/${total}`
        : `${Math.min(idx + 1, total)}/${total}`
    const label = String(state.currentLabel || state.currentId || state.workflow)
      .replace(/\s+/g, " ")
      .slice(0, 28)
    const elapsed = formatPilotElapsed(Date.now() - state.startedAt)
    return `${state.workflow} [${bar}] ${n} ${label} ${elapsed}`
  }

  const liveTodoItems = (): TodoItem[] => {
    const total = Math.max(1, state.steps.length)
    const idx = currentIndex()
    const bar = renderPilotProgressBar(
      state.status === "done" || state.status === "ok" ? total : idx,
      total,
    )
    const n =
      state.status === "done" || state.status === "ok"
        ? `${total}/${total}`
        : `${Math.min(idx + 1, total)}/${total}`
    const elapsed = formatPilotElapsed(Date.now() - state.startedAt)
    return state.steps.map((s, i) => {
      let status = "pending"
      if (state.status === "done" || state.status === "ok") status = "completed"
      else if (i < idx) status = "completed"
      else if (i === idx) status = "in_progress"
      const content =
        status === "in_progress"
          ? `${s.content}  [${bar}] ${n}  ${elapsed}`
          : s.content
      return {
        id: s.id,
        content,
        status,
        priority: status === "in_progress" ? "high" : status === "completed" ? "low" : "medium",
      }
    })
  }

  const showProgressToast = (title: string) => {
    const client = opts?.client
    const toastKey = `${state.workflow}:${state.currentId}:${state.status}:${title.slice(0, 24)}`
    if (!client?.tui?.showToast || toastKey === lastToastKey) return
    lastToastKey = toastKey
    const variant =
      state.status === "fail"
        ? "error"
        : state.status === "done" || state.status === "ok"
          ? "success"
          : "info"
    const payload = { title: "pilot_run", message: title, variant, duration: 8000 }
    try {
      const ret =
        client.tui.showToast(payload) ||
        client.tui.showToast({ body: payload })
      if (ret && typeof (ret as { then?: unknown }).then === "function") {
        void Promise.resolve(ret).catch(() => {})
      }
    } catch {
      try {
        const ret = client.tui.showToast({ body: payload })
        if (ret && typeof (ret as { then?: unknown }).then === "function") {
          void Promise.resolve(ret).catch(() => {})
        }
      } catch {
        /* toast is best-effort */
      }
    }
  }

  const publishVisibleProgress = (title: string) => {
    // Do not call ctx.metadata: OpenCode fromPlugin does not run the Effect,
    // and a successful metadata write resets input to the original args.
    row.publish(title)
    const sessionId = String(opts?.sessionId || ctx?.sessionID || ctx?.sessionId || "").trim()
    const client = opts?.client
    if (client && sessionId && state.steps.length) {
      const stageKey = `${state.currentId}:${state.status}`
      const now = Date.now()
      if (stageKey !== lastTodoStage || now - lastTodoAt >= 900) {
        lastTodoStage = stageKey
        lastTodoAt = now
        const items = liveTodoItems()
        void syncTodos(client, sessionId, {
          native_items: items,
          todo_sync: { items, merge: true },
        })
      }
    }
    showProgressToast(title)
  }

  const flush = () => {
    publishVisibleProgress(render())
  }

  const timer = setInterval(flush, 1000)
  flush()

  return {
    note(title: string, detail?: string) {
      if (title) state.currentLabel = title
      if (detail != null) state.detail = detail
      flush()
    },
    applyStderrLine(line: string) {
      const ev = parseAcpProgressLine(line)
      if (ev.kind === "ignore") return
      if (ev.kind === "run" || ev.kind === "advance") {
        if (ev.id) state.currentId = ev.id
        if (ev.label) state.currentLabel = ev.label
        if (ev.kind === "run") state.detail = ""
        else if (ev.detail) state.detail = ev.detail
        state.status = "running"
      } else if (ev.kind === "ok") {
        state.detail = ""
      } else if (ev.kind === "fail") {
        state.status = "fail"
        if (ev.detail) state.detail = ev.detail
      } else if (ev.detail) {
        state.detail = ev.detail
      }
      flush()
    },
    applyTodo(todo: unknown) {
      const steps = stepsFromTodo(todo)
      if (steps.length) state.steps = steps
      const current = steps.find((s) => {
        const items = extractTodoItems(todo)
        const hit = items.find((it) => it.id === s.id)
        return hit?.status === "in_progress"
      })
      if (current) {
        state.currentId = current.id
        state.currentLabel = current.content
      }
      flush()
    },
    setWorkflow(id: string) {
      if (id) {
        state.workflow = id
        if (!state.steps.length) state.steps = defaultSteps(id)
      }
      flush()
    },
    setStatus(status) {
      state.status = status
      if (status === "ask") state.currentLabel = "waiting for confirmation"
      if (status === "done" || status === "ok") {
        state.currentLabel = "done"
        state.detail = ""
      }
      flush()
    },
    flush,
    flushAsync: () => row.flushAsync(),
    close() {
      state.closed = true
      row.close()
      clearInterval(timer)
    },
  }
}

function acpControlEnv(opts?: {
  sessionId?: string
  workflow?: string
}): Record<string, string> {
  const env: Record<string, string> = {}
  const sid = String(opts?.sessionId || "").trim()
  const wf = String(opts?.workflow || "").trim()
  if (sid) env.ASCENDC_SESSION_ID = sid
  if (wf) env.ASCENDC_WORKFLOW_ID = wf
  return env
}

function runAcpJson(
  argv: string[],
  project: string,
  opts?: {
    timeoutMs?: number
    env?: Record<string, string>
    onStderrLine?: (line: string) => void
    abort?: AbortSignal
  },
): Promise<Record<string, unknown>> {
  return new Promise((resolvePromise) => {
    const acpBin = resolveAcpBin()
    let stdout = ""
    let stderr = ""
    let stderrBuf = ""
    let settled = false
    const finish = (payload: Record<string, unknown>) => {
      if (settled) return
      settled = true
      resolvePromise(payload)
    }

    let proc: ReturnType<typeof spawn>
    const cann = readCachedCannRoot()
    try {
      proc = spawn(acpBin, argv, {
        shell: false,
        windowsHide: true,
        cwd: project,
        env: {
          ...process.env,
          PYTHONUNBUFFERED: "1",
          PYTHONIOENCODING: "utf-8",
          ASCENDC_PROJECT_ROOT: project,
          ...(cann && !process.env.UO_CANN_ROOT ? { UO_CANN_ROOT: cann } : {}),
          ...(opts?.env || {}),
        },
      })
    } catch (err) {
      finish({
        ok: false,
        error: "ACP_SPAWN",
        message: String(err).slice(0, 800),
      })
      return
    }

    const timeoutMs = opts?.timeoutMs ?? 3_600_000
    const timer = setTimeout(() => {
      try {
        proc.kill()
      } catch {
        /* ignore */
      }
      const minutes = Math.round(timeoutMs / 60_000)
      const messageZh =
        `工作流仍可能在跑，但 Host 已等待 ${minutes} 分钟并停止等待（ACP_TIMEOUT）。` +
        `请用 pilot_cli inspect-failure / status 查看，不要立刻再 bash acp start / run-action auto。`
      finish({
        ok: false,
        error: "ACP_TIMEOUT",
        message: `acp ${argv[0] || ""} timed out after ${timeoutMs}ms`,
        message_zh: messageZh,
        host_step: { kind: "failed", message_zh: messageZh },
        stdout: stdout.slice(0, 400),
        stderr: stderr.slice(0, 400),
      })
    }, timeoutMs)

    const onAbort = () => {
      try {
        proc.kill()
      } catch {
        /* ignore */
      }
    }
    opts?.abort?.addEventListener("abort", onAbort)

    const pushStderr = (chunk: string) => {
      stderr += chunk
      stderrBuf += chunk
      const parts = stderrBuf.split(/\r?\n/)
      stderrBuf = parts.pop() || ""
      for (const line of parts) {
        if (line.trim()) opts?.onStderrLine?.(line)
      }
    }

    proc.stdout?.setEncoding("utf-8")
    proc.stderr?.setEncoding("utf-8")
    proc.stdout?.on("data", (chunk: string) => {
      stdout += chunk
    })
    proc.stderr?.on("data", (chunk: string) => {
      pushStderr(chunk)
    })
    proc.on("error", (err) => {
      clearTimeout(timer)
      opts?.abort?.removeEventListener("abort", onAbort)
      finish({
        ok: false,
        error: "HARNESS_MISSING",
        message: String(err).slice(0, 800),
      })
    })
    proc.on("close", (code) => {
      clearTimeout(timer)
      opts?.abort?.removeEventListener("abort", onAbort)
      if (stderrBuf.trim()) opts?.onStderrLine?.(stderrBuf)
      finish(parseAcpStdoutJson(stdout, stderr, code))
    })
  })
}

export type PendingDispatch = {
  project: string
  ticket: string
  actor: string
  action: string
  ts: number
  sessionId?: string
  workflow?: string
}

export function pendingDispatchPath(): string {
  return resolve(openCodeHome(), "ascendc-pending-dispatch.json")
}

export function rememberPendingDispatch(entry: PendingDispatch): void {
  try {
    mkdirSync(openCodeHome(), { recursive: true })
    writeFileSync(pendingDispatchPath(), JSON.stringify(entry), "utf-8")
  } catch {
    /* ignore */
  }
}

/** Singleton handoff from the last ``dispatch_subagent`` (pilot_run project). */
export function readLatestPendingDispatch(): PendingDispatch | null {
  try {
    const rec = JSON.parse(readFileSync(pendingDispatchPath(), "utf-8")) as PendingDispatch
    if (!rec?.ticket || !rec?.project) return null
    return rec
  } catch {
    return null
  }
}

export function readPendingDispatch(_project?: string): PendingDispatch | null {
  // Singleton slot: Task hooks often pass workspace cwd instead of the operator.
  return readLatestPendingDispatch()
}

export function clearPendingDispatch(project: string): void {
  try {
    const rec = readPendingDispatch(project)
    if (!rec) return
    unlinkSync(pendingDispatchPath())
  } catch {
    /* ignore */
  }
}

export async function submitDispatchResult(
  project: string,
  ticket: string,
  resultText: string,
  opts?: { sessionId?: string; workflow?: string },
): Promise<Record<string, unknown>> {
  const pending = readLatestPendingDispatch()
  return runAcpJson(
    [
      "dispatch-result",
      "--project",
      project,
      "--ticket",
      ticket,
      "--result-text",
      String(resultText || "").slice(0, 200_000),
    ],
    project,
    {
      timeoutMs: 180_000,
      env: acpControlEnv({
        sessionId: opts?.sessionId || pending?.sessionId,
        workflow: opts?.workflow || pending?.workflow,
      }),
    },
  )
}

/** Cap matches ``acp dispatch-result --result-text`` (keep Explore-length answers). */
export const NATIVE_TASK_RESULT_CAP = 200_000

/**
 * Native Task handoff (Cursor Explore style): keep the full child message.
 * Do not strip to the yaml fence — that discarded citations and source windows.
 */
export function extractKbAnswer(text: string): string {
  return String(text || "").slice(0, NATIVE_TASK_RESULT_CAP)
}

function authIpcDir(): string {
  return resolve(openCodeHome(), "ascendc-auth-ipc")
}

/** Best-effort register-session via authorize daemon IPC (same dir as plugin). */
function registerSessionIpc(args: {
  project: string
  sessionId: string
  actorId: string
  actionId: string
  leaseId?: string
  runId?: string
}): void {
  try {
    const dir = authIpcDir()
    mkdirSync(dir, { recursive: true })
    const id = `reg_${Date.now().toString(36)}`
    writeFileSync(
      resolve(dir, `${id}.req.json`),
      JSON.stringify({
        id,
        method: "register-session",
        project: args.project,
        session_id: args.sessionId,
        actor_id: args.actorId,
        action_id: args.actionId,
        lease_id: args.leaseId || "",
        run_id: args.runId || "",
      }),
      "utf-8",
    )
  } catch {
    /* ignore */
  }
}

function registerSessionDisk(args: {
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
  registerSessionIpc(args)
}

type HostStep = {
  kind?: string
  action_id?: string
  actor_id?: string
  cwd?: string
  dispatch_ticket?: string
  task_prompt_stub?: string
  tasks?: Array<Record<string, unknown>>
  session_dir?: string
  lease_id?: string
  run_id?: string
  ask_question?: Record<string, unknown>
  message_zh?: string
  next_workflow_id?: string
  architecture?: string
  intent?: string
}

export type PilotRunArgs = {
  workflow: string
  project: string
  architecture?: string
  intent?: string
  forceNew?: boolean
}

export type PilotToolContext = {
  sessionID?: string
  sessionId?: string
  messageID?: string
  callID?: string
  askQuestion?: (input: Record<string, unknown>) => Promise<unknown>
  question?: (input: Record<string, unknown>) => Promise<unknown>
  metadata?: (input: { title?: string; metadata?: Record<string, unknown> }) => void
  abort?: AbortSignal
}

type CapturedToolSession = {
  sessionID: string
  messageID: string
  callID: string
}

const lastToolSession: CapturedToolSession = { sessionID: "", messageID: "", callID: "" }

function pickSessionField(src: Record<string, unknown> | undefined, keys: string[]): string {
  if (!src) return ""
  for (const key of keys) {
    const v = src[key]
    if (typeof v === "string" && v.trim()) return v.trim()
  }
  const nested = src.session
  if (nested && typeof nested === "object") {
    const rec = nested as Record<string, unknown>
    for (const key of ["id", "sessionID", "sessionId"]) {
      const v = rec[key]
      if (typeof v === "string" && v.trim()) return v.trim()
    }
  }
  return ""
}

/** Hook `tool.execute.before` fills this so progress can patch the running tool row. */
export function capturePilotToolSession(
  input?: Record<string, unknown>,
  output?: Record<string, unknown>,
): void {
  const sessionID =
    pickSessionField(input, ["sessionID", "sessionId", "session_id"]) ||
    pickSessionField(output, ["sessionID", "sessionId", "session_id"])
  const messageID =
    pickSessionField(input, ["messageID", "messageId", "message_id"]) ||
    pickSessionField(output, ["messageID", "messageId", "message_id"])
  const callID =
    pickSessionField(input, ["callID", "callId", "call_id", "toolCallID"]) ||
    pickSessionField(output, ["callID", "callId", "call_id", "toolCallID"])
  if (sessionID) lastToolSession.sessionID = sessionID
  if (messageID) lastToolSession.messageID = messageID
  if (callID) lastToolSession.callID = callID
}

function resolvedSessionId(ctx?: PilotToolContext, opts?: { sessionId?: string }): string {
  return String(
    opts?.sessionId ||
      ctx?.sessionID ||
      ctx?.sessionId ||
      lastToolSession.sessionID ||
      "",
  ).trim()
}

type TodoItem = {
  id: string
  content: string
  status: string
  priority: string
}

function extractTodoItems(todoPayload: unknown): TodoItem[] {
  if (!todoPayload || typeof todoPayload !== "object") return []
  const todo = todoPayload as Record<string, unknown>
  const sync = (todo.todo_sync || {}) as Record<string, unknown>
  const raw = (Array.isArray(sync.items) ? sync.items : todo.native_items) as unknown
  if (!Array.isArray(raw)) return []
  const out: TodoItem[] = []
  for (const row of raw) {
    if (!row || typeof row !== "object") continue
    const it = row as Record<string, unknown>
    const id = String(it.id || "").trim()
    const content = String(it.content || it.label_zh || id).trim()
    if (!id || !content) continue
    const status = String(it.status || "pending").toLowerCase()
    const priority =
      String(it.priority || "").trim() ||
      (status === "in_progress" || status === "current"
        ? "high"
        : status === "completed" || status === "done"
          ? "low"
          : "medium")
    const nativeStatus =
      status === "done" || status === "completed"
        ? "completed"
        : status === "current" || status === "in_progress"
          ? "in_progress"
          : "pending"
    out.push({ id, content, status: nativeStatus, priority })
  }
  return out
}

/** Sync ACP todo_sync into OpenCode session sidebar (plugin-owned, not LLM). */
async function syncTodos(
  client: any,
  sessionId: string,
  todoPayload: unknown,
): Promise<{ ok: boolean; via?: string; error?: string }> {
  const items = extractTodoItems(todoPayload)
  if (!sessionId || !items.length) return { ok: true, via: "skip" }
  const attempts: Array<() => Promise<void>> = [
    async () => {
      await client.session.todoUpdate({ sessionID: sessionId, todos: items })
    },
    async () => {
      await client.session.todoUpdate({
        path: { id: sessionId },
        body: { todos: items },
      })
    },
    async () => {
      await client.session.todo({
        path: { id: sessionId },
        body: { todos: items },
        method: "POST",
      })
    },
    async () => {
      await client.post({
        url: `/session/${encodeURIComponent(sessionId)}/todo`,
        body: { todos: items },
      })
    },
  ]
  for (const [i, fn] of attempts.entries()) {
    try {
      await fn()
      return { ok: true, via: `todoUpdate#${i}` }
    } catch {
      /* try next shape */
    }
  }
  return { ok: false, error: "TODO_SYNC_UNAVAILABLE" }
}

function normalizeAskOptions(ask: Record<string, unknown>): Array<{
  label: string
  description?: string
  value?: string
}> {
  const opts = ask.options
  if (!Array.isArray(opts)) return []
  const out: Array<{ label: string; description?: string; value?: string }> = []
  for (const o of opts) {
    if (typeof o === "string") {
      out.push({ label: o, value: o })
      continue
    }
    if (!o || typeof o !== "object") continue
    const row = o as Record<string, unknown>
    const label = String(row.label || row.value || row.id || "").trim()
    if (!label) continue
    const value = String(row.value || "").trim()
    out.push({
      label,
      description: row.description ? String(row.description) : undefined,
      value: value || undefined,
    })
  }
  return out
}

/**
 * Invoke Host AskQuestion UI when available.
 * Returns answers when the user replied; null when UI unavailable (caller surfaces).
 */
async function invokeAskHuman(
  client: any,
  toolCtx: PilotToolContext | undefined,
  ask: Record<string, unknown>,
  sessionId: string,
): Promise<{ answered: boolean; answers?: unknown; via?: string; error?: string }> {
  const header = String(ask.header || ask.title || "AscendC-Pilot").trim()
  const question = String(ask.question || ask.prompt || ask.message_zh || "").trim()
  const options = normalizeAskOptions(ask)
  if (!question) return { answered: false, error: "ASK_EMPTY" }

  const payload = {
    header,
    question,
    options: options.map((o) => ({
      label: o.label,
      description: o.description || "",
      value: o.value || o.label,
    })),
    multiple: Boolean(ask.multiple),
  }

  // 1) Tool-context askQuestion (OpenCode plugin tool ctx)
  const askFn = toolCtx?.askQuestion || toolCtx?.question
  if (typeof askFn === "function") {
    try {
      const answers = await askFn({
        ...payload,
        sessionID: sessionId,
        sessionId,
      })
      return { answered: true, answers, via: "toolCtx.askQuestion" }
    } catch (exc) {
      return { answered: false, error: String(exc).slice(0, 200) }
    }
  }

  // 2) client.question.ask (SDK endpoint when present)
  if (client?.question?.ask) {
    try {
      const answers = await client.question.ask({
        body: {
          sessionID: sessionId,
          sessionId,
          ...payload,
        },
      })
      return { answered: true, answers, via: "client.question.ask" }
    } catch (exc) {
      return { answered: false, error: String(exc).slice(0, 200) }
    }
  }

  // 3) Unavailable — Host still owns the payload; Primary only presents exact options.
  return { answered: false, via: "deferred_exact_options", error: "ASK_UI_UNAVAILABLE" }
}

function isAskInterrupted(
  asked: { error?: string; answered?: boolean },
  toolCtx?: PilotToolContext,
): boolean {
  if (toolCtx?.abort?.aborted) return true
  const err = String(asked.error || "")
  return /\babort(?:ed|ing)?\b|\binterrupt(?:ed)?\b|\bcancel(?:led|ed)?\b/i.test(err)
}

async function handleAskHumanStep(args: {
  client: any
  toolCtx?: PilotToolContext
  parentSessionId: string
  project?: string
  requestId?: string
  step: HostStep
  ask: Record<string, unknown>
  log: Array<Record<string, unknown>>
  todo?: unknown
}): Promise<Record<string, unknown>> {
  const { client, toolCtx, parentSessionId, project, requestId, step, ask, log, todo } = args
  await syncTodos(client, parentSessionId, todo)

  const asked = await invokeAskHuman(client, toolCtx, ask, parentSessionId)
  log.push({ event: "ask_human", via: asked.via, answered: asked.answered })

  if (asked.answered) {
    const extracted = extractAskAnswer(asked.answers)
    let label = extracted
    const options = Array.isArray(ask.options) ? ask.options : []
    for (const opt of options) {
      if (!opt || typeof opt !== "object") continue
      const o = opt as Record<string, unknown>
      const lab = String(o.label || "").trim()
      const val = String(o.value || "").trim()
      if (extracted && (extracted === lab || extracted === val)) {
        label = val || lab
        break
      }
    }
    if (project && requestId && label) {
      const recorded = await runAcpJson(
        ["answer", "--project", project, "--request-id", requestId, "--value", label],
        project,
        {
          timeoutMs: 60_000,
          abort: toolCtx?.abort,
          env: acpControlEnv({ sessionId: parentSessionId }),
        },
      )
      log.push({ event: "acp_answer", ok: recorded.ok !== false, value: label })
    }
    const decision = normalizeResumeDecision(label)
    const archChoice = /^arch[0-9A-Za-z._-]+$/i.test(label) ? label : ""
    return {
      ok: true,
      answered: true,
      needs_human_decision: false,
      host_owned_ask: true,
      answers: asked.answers,
      resume_decision: decision,
      choice: label,
      architecture_choice: archChoice,
      action_id: String(step.action_id || ""),
      log,
      message_zh: "Host Driver 已收集答复并写入 acp answer。",
      todo,
    }
  }

  // UI missing: still mark host-owned so Primary must not invent options.
  if (isAskInterrupted(asked, toolCtx)) {
    log.push({ event: "ask_interrupted", error: asked.error })
    return {
      ok: true,
      answered: false,
      ask_interrupted: true,
      needs_human_decision: false,
      host_owned_ask: false,
      log,
      todo,
      message_zh:
        "确认框被打断。请按用户本轮新消息继续：能对应原选项则 interpret-user-turn，否则不要重问上一题。未点选不等于批准删除/重开。",
      ask_ui_error: asked.error,
    }
  }

  return {
    ok: false,
    answered: false,
    needs_human_decision: true,
    host_owned_ask: true,
    host_step: step,
    ask_question: ask,
    log,
    todo,
    message_zh:
      step.message_zh ||
      "需要人工确认：请立即用 AskQuestion，options 必须原样使用 ask_question.options；禁止自行改写选项。若用户已在对话里回复，改为 interpret-user-turn，不要重问。",
    ask_ui_error: asked.error,
  }
}

async function dispatchSubagentOnce(args: {
  client: any
  project: string
  workflow: string
  step: HostStep
  log: Array<Record<string, unknown>>
  reporter?: ProgressReporter
  abort?: AbortSignal
}): Promise<{
  ok: boolean
  finished?: Record<string, unknown>
  error?: string
  host_step?: HostStep
}> {
  const { client, project, workflow, step, log, reporter, abort } = args
  const actor = String(step.actor_id || "").trim()
  const stub = String(step.task_prompt_stub || "").trim()
  const ticket = String(step.dispatch_ticket || "").trim()
  if (!actor || !stub || !ticket) {
    return {
      ok: false,
      error: "DISPATCH_INCOMPLETE",
      host_step: step,
    }
  }

  if (!client?.session?.create || !client?.session?.prompt) {
    return {
      ok: false,
      error: "SESSION_API_MISSING",
      host_step: step,
    }
  }

  const child = await client.session.create({
    body: {
      title: `acp:${workflow}:${step.action_id}:${actor}`,
      agent: actor,
      location: { directory: project },
    },
  })
  const childId = String(child?.data?.id || child?.id || "").trim()
  if (!childId) {
    return { ok: false, error: "SESSION_CREATE_FAILED", host_step: step }
  }
  registerSessionDisk({
    project,
    sessionId: childId,
    actorId: actor,
    actionId: String(step.action_id || ""),
    leaseId: String(step.lease_id || ""),
    runId: String(step.run_id || ""),
  })

  const prompted = await client.session.prompt({
    path: { id: childId },
    body: {
      agent: actor,
      parts: [{ type: "text", text: stub }],
    },
  })

  let finalText = ""
  const data = prompted?.data || prompted
  if (typeof data === "string") finalText = data
  else if (data?.parts) {
    for (const p of data.parts) {
      if (p?.type === "text" && p.text) finalText += String(p.text) + "\n"
    }
  } else if (data?.info?.content) {
    finalText = String(data.info.content)
  } else {
    finalText = JSON.stringify(data || {}).slice(0, NATIVE_TASK_RESULT_CAP)
  }
  const resultText = extractKbAnswer(finalText)

  reporter?.note(`dispatch ${actor}`, String(step.action_id || ""))
  const finished = await runAcpJson(
    [
      "dispatch-result",
      "--project",
      project,
      "--ticket",
      ticket,
      "--result-text",
      resultText.slice(0, 200_000),
    ],
    project,
    {
      timeoutMs: 300_000,
      abort,
      onStderrLine: (line) => reporter?.applyStderrLine(line),
      env: acpControlEnv({ workflow }),
    },
  )
  log.push({
    event: "dispatch-result",
    ticket,
    ok: finished.ok,
    next_kind: (finished.host_step as HostStep | undefined)?.kind,
  })
  return { ok: Boolean(finished.ok), finished, host_step: step }
}

function hostStepTasks(step: HostStep): Array<Record<string, unknown>> {
  return compactDispatchTasks(step.tasks) || []
}

function nativeTaskHandoff(args: {
  step: HostStep
  project: string
  log: Array<Record<string, unknown>>
  todo?: unknown
  sessionId?: string
  workflow?: string
}): Record<string, unknown> {
  const actor = String(args.step.actor_id || "").trim()
  const stub = String(args.step.task_prompt_stub || "").trim()
  const ticket = String(args.step.dispatch_ticket || "").trim()
  const tasks = hostStepTasks(args.step)
  if (!actor || !ticket || (!stub && tasks.length < 2)) {
    return {
      ok: false,
      error: "DISPATCH_INCOMPLETE",
      host_step: args.step,
      log: args.log,
      message_zh: "host_step 缺少 actor / stub / ticket",
    }
  }
  rememberPendingDispatch({
    project: args.project,
    ticket,
    actor,
    action: String(args.step.action_id || ""),
    ts: Date.now(),
    sessionId: args.sessionId,
    workflow: args.workflow,
  })
  if (tasks.length >= 2) {
    const ids = tasks
      .map((row) => String(row.slice_id || "").trim())
      .filter(Boolean)
      .join(", ")
    const messageZh =
      `请在同一轮并行派发 ${tasks.length} 个 OpenCode 原生 Task：agent=\`${actor}\`。` +
      `每个 Task 的 prompt 必须原样为 host_step.tasks[i].task_prompt_stub（禁止改写）。` +
      `不要再用 host_step.task_prompt_stub 开第 ${tasks.length + 1} 个子代理。` +
      `点各 Task 卡片可跳进子会话看思考。全部返回后由 Primary 综合成一份 kb-answer-v1，` +
      `禁止只转述某一个，禁止发明子代理没引用的事实。综合后再 finalize（一张 ticket）。` +
      (ids ? `切片：${ids}。` : "")
    return {
      ok: true,
      native_task: true,
      native_tasks: true,
      host_step: { ...args.step, tasks, message_zh: messageZh },
      log: args.log,
      todo: args.todo,
      message_zh: messageZh,
    }
  }
  const messageZh =
    `请用 OpenCode 原生 Task：agent=\`${actor}\`，prompt 必须原样为 host_step.task_prompt_stub（禁止改写）。` +
    `点 Task 卡片可跳进子会话看思考过程。子代理答完后把答案说给人听。`
  return {
    ok: true,
    native_task: true,
    host_step: { ...args.step, message_zh: messageZh },
    log: args.log,
    todo: args.todo,
    message_zh: messageZh,
  }
}

export async function runPilotDriver(
  client: any,
  args: PilotRunArgs,
  toolCtx?: PilotToolContext,
  reporter?: ProgressReporter,
): Promise<Record<string, unknown>> {
  if (!args || typeof args !== "object") {
    return { ok: false, error: "PILOT_RUN_ARGS", message_zh: "pilot_run 需要 workflow + project" }
  }
  const project = resolve(String(args.project || "").trim())
  let workflow = String(args.workflow || "").trim()
  if (!project || !workflow) {
    return { ok: false, error: "PILOT_RUN_ARGS", message_zh: "pilot_run 需要 workflow + project" }
  }
  if (workflow === "uo-query") {
    reporter?.setStatus("done")
    const messageZh =
      "查询不是 Host 工作流，不要再用 pilot_run。直接用插件工具 `pilot_cli` command=`uo-query --project <算子绝对路径> <identifier>`，" +
      "或同一轮原生 Task(agent=`uo-query`)。禁止单独一轮只宣布路数。禁止 `--mode`。禁止为空转「问题路由」开子代理。"
    return {
      ok: true,
      reason_code: "UO_QUERY_NOT_HOST_DRIVEN",
      host_step: { kind: "primary_router", message_zh: messageZh },
      message_zh: messageZh,
    }
  }

  const parentSessionId = String(
    toolCtx?.sessionID || toolCtx?.sessionId || "",
  ).trim()

  let architecture = args.architecture ? String(args.architecture) : ""
  let intent = args.intent ? String(args.intent) : ""
  reporter?.setWorkflow(workflow)
  reporter?.note("starting")

  const acpOpts = (timeoutMs?: number) => ({
    timeoutMs,
    abort: toolCtx?.abort,
    onStderrLine: (line: string) => reporter?.applyStderrLine(line),
    env: acpControlEnv({ sessionId: parentSessionId, workflow }),
  })

  // force_new / 删除重开 applies only to this start, not continue_goal's next workflow.
  let applyForceNew = Boolean(args.forceNew)
  try {
    const cache = resolve(openCodeHome(), "ascendc-last-project")
    mkdirSync(openCodeHome(), { recursive: true })
    const looksLikeOperator =
      existsSync(resolve(project, ".ascendc-pilot")) ||
      existsSync(resolve(project, "op_kernel")) ||
      existsSync(resolve(project, "op_host"))
    if (looksLikeOperator) writeFileSync(cache, project, "utf-8")
  } catch {
    // best-effort
  }
  const startOnce = (extra: string[] = []) => {
    const argv = ["start", workflow, "--project", project, ...extra]
    if (architecture) argv.push("--architecture", architecture)
    if (intent) argv.push("--intent", intent)
    if (applyForceNew) argv.push("--force-new")
    return runAcpJson(argv, project, acpOpts())
  }

  let lastResumeDecision = ""
  const consumeStartAsks = async (
    initial: Record<string, unknown>,
  ): Promise<Record<string, unknown>> => {
    let payload = initial
    if (
      String(payload.decision || "") === "query" ||
      String(payload.next_workflow_id || "") === "uo-query"
    ) {
      const messageZh =
        "上一场建库已经完成，产物锁已释放。查询不是 Host 工作流。" +
        "直接 `pilot_cli` `uo-query` 或同一轮 Task(agent=`uo-query`)。禁止单独一轮只宣布路数。" +
        "不要 pilot_run / acp start uo-query。"
      return {
        ok: true,
        reason_code: "UO_QUERY_NOT_HOST_DRIVEN",
        host_step: { kind: "primary_router", message_zh: messageZh },
        message_zh: messageZh,
      }
    }
    const logAcc: Array<Record<string, unknown>> = [
      { event: "start", ok: isAcpStartSuccess(payload), workflow },
    ]
    for (let i = 0; i < 4 && isHumanDecision(payload); i++) {
      reporter?.setStatus("ask")
      const req =
        payload.human_interaction_request && typeof payload.human_interaction_request === "object"
          ? (payload.human_interaction_request as Record<string, unknown>)
          : {}
      const ask =
        payload.ask_question && typeof payload.ask_question === "object"
          ? (payload.ask_question as Record<string, unknown>)
          : ((req.ask_question as Record<string, unknown>) || {})
      const asked = await handleAskHumanStep({
        client,
        toolCtx,
        parentSessionId,
        project,
        requestId: String(req.request_id || ""),
        step: {
          kind: "ask_human",
          ask_question: ask,
          message_zh: String(payload.message_zh || payload.error || "acp start needs human"),
        },
        ask,
        log: logAcc,
        todo: payload.todo,
      })
      if (!asked.answered) return asked
      const decision = String(asked.resume_decision || asked.choice || "")
      const archChoice = String(asked.architecture_choice || "")
      if (decision === "query") {
        const messageZh =
          "上一场建库已经完成，产物锁已释放。新会话直接查询即可，不是卡住。" +
          "直接 `pilot_cli` `uo-query` 或同一轮 Task(agent=`uo-query`)。禁止单独一轮只宣布路数。" +
          "不要 pilot_run / acp start uo-query。"
        return {
          ok: true,
          reason_code: "UO_QUERY_NOT_HOST_DRIVEN",
          host_step: { kind: "primary_router", message_zh: messageZh },
          message_zh: messageZh,
          log: logAcc,
          todo: payload.todo,
        }
      }
      if (decision === "uo-init") {
        workflow = "uo-init"
        applyForceNew = false
        lastResumeDecision = ""
        payload = await startOnce()
        continue
      }
      if (decision === "source") {
        return sourceFallbackPayload(logAcc, payload.todo)
      }
      if (decision) {
        lastResumeDecision = decision
        payload = await startOnce(["--decision", decision])
        continue
      }
      if (archChoice) {
        architecture = archChoice
        const extra = lastResumeDecision ? ["--decision", lastResumeDecision] : []
        payload = await startOnce(extra)
        continue
      }
      return asked
    }
    return payload
  }

  const live = applyForceNew
    ? { ok: false }
    : await runAcpJson(["status", "--project", project], project, acpOpts(30_000))
  const liveWf = String((live as Record<string, unknown>).workflow_id || "")
  const liveStatus = String((live as Record<string, unknown>).status || "")
  const sameLive =
    !applyForceNew &&
    liveWf === workflow &&
    ["running", "rework_required", "human_required"].includes(liveStatus)

  const started = sameLive
    ? {
        ok: true,
        resumed: true,
        skip_start: true,
        run_id: (live as Record<string, unknown>).run_id,
        status: liveStatus,
        workflow_id: liveWf,
        todo: (live as Record<string, unknown>).todo,
      }
    : await consumeStartAsks(await startOnce())
  const startedKind = String((started.host_step as HostStep | undefined)?.kind || "")
  if (started.answer_from_source === true || startedKind === "answer_from_source") {
    return started
  }
  // leftover「去查询」returns ok:true + primary_router; must not enter auto-drive.
  if (
    startedKind === "primary_router" ||
    String(started.reason_code || "") === "UO_QUERY_NOT_HOST_DRIVEN"
  ) {
    reporter?.setStatus("done")
    return started
  }
  if (started.ask_interrupted === true || started.disposition === "superseded") {
    reporter?.setStatus("done")
    return started
  }
  // Answered AskQuestion blobs still carry ask_question; do not treat them as start-failed.
  if (isHumanDecision(started)) {
    return started
  }
  if (!isAcpStartSuccess(started)) {
    reporter?.setStatus("fail")
    const failMsg = String(
      started.message_zh || started.message || started.error || "acp start failed",
    )
    return {
      ok: false,
      phase: "start",
      start: started,
      error: String(started.error || "ACP_START_FAILED"),
      message: String(started.message || failMsg),
      host_step: {
        kind: "failed",
        message_zh: failMsg,
      },
    }
  }
  reporter?.applyTodo(started.todo)
  applyForceNew = false

  const log: Array<Record<string, unknown>> = [
    { event: "start", ok: true, workflow, run_id: started.run_id },
  ]
  let guard = 0
  let lastStep: HostStep | null = null
  /** When dispatch-result already returned the next dispatch_subagent, skip re-auto. */
  let pendingStep: HostStep | null = null
  let pendingTodo: unknown = started.todo

  while (guard++ < 64) {
    let step: HostStep
    let todoPayload: unknown = pendingTodo

    if (pendingStep && pendingStep.kind === "dispatch_subagent") {
      step = pendingStep
      pendingStep = null
      log.push({ event: "reuse_host_step", host_step_kind: step.kind })
    } else if (pendingStep && pendingStep.kind === "continue_goal") {
      step = pendingStep
      pendingStep = null
    } else {
      const driven = await runAcpJson(
        ["run-action", "auto", "--project", project],
        project,
        acpOpts(3_600_000),
      )
      step = (driven.host_step || {}) as HostStep
      todoPayload = driven.todo
      pendingTodo = driven.todo
      lastStep = step
      reporter?.applyTodo(todoPayload)
      log.push({
        event: "drive",
        stop_reason: driven.stop_reason,
        host_step_kind: step.kind,
        ok: driven.ok,
      })
      const synced = await syncTodos(client, parentSessionId, todoPayload)
      log.push({ event: "todo_sync", ...synced })

      if (step.kind === "continue_goal") {
        // Fall through to continue_goal handler below.
      } else if (step.kind === "done") {
        reporter?.setStatus("done")
        await syncTodos(client, parentSessionId, todoPayload)
        return { ok: true, host_step: step, log, todo: todoPayload, drive: driven }
      } else if (step.kind === "failed") {
        reporter?.setStatus("fail")
        const failMsg = String(
          step.message_zh ||
            driven.message_zh ||
            step.error_detail ||
            driven.error ||
            "deterministic_action_failed",
        )
        return {
          ok: false,
          host_step: { ...step, kind: "failed", message_zh: failMsg },
          error: String(driven.error || step.error_detail || ""),
          message_zh: failMsg,
          hint_zh: step.hint_zh || driven.hint_zh,
          log,
          todo: todoPayload,
        }
      } else if (step.kind === "ask_human") {
        reporter?.setStatus("ask")
        const ask =
          (step.ask_question as Record<string, unknown>) ||
          (driven.ask_question as Record<string, unknown>) ||
          {}
        const req =
          driven.human_interaction_request && typeof driven.human_interaction_request === "object"
            ? (driven.human_interaction_request as Record<string, unknown>)
            : {}
        const asked = await handleAskHumanStep({
          client,
          toolCtx,
          parentSessionId,
          project,
          requestId: String(req.request_id || ""),
          step,
          ask,
          log,
          todo: todoPayload,
        })
        if (!asked.answered) return asked
        const decision = String(asked.resume_decision || asked.choice || "")
        if (decision === "source") {
          return sourceFallbackPayload(log, todoPayload)
        }
        if (decision === "uo-init") {
          workflow = "uo-init"
          applyForceNew = false
          const switched = await consumeStartAsks(await startOnce())
          if (switched.answer_from_source === true) return switched
          if (isHumanDecision(switched)) return switched
          if (!isAcpStartSuccess(switched)) {
            reporter?.setStatus("fail")
            return {
              ok: false,
              host_step: {
                kind: "failed",
                message_zh: String(switched.message_zh || switched.error || "start uo-init failed"),
              },
              log,
            }
          }
          pendingTodo = switched.todo
          continue
        }
        if (decision === "query") {
          reporter?.setStatus("done")
          const messageZh =
            "上一场建库已经完成，产物锁已释放。查询不是 Host 工作流。" +
            "直接 `pilot_cli` `uo-query` 或同一轮 Task(agent=`uo-query`)。禁止单独一轮只宣布路数。不要 pilot_run uo-query。"
          return {
            ok: true,
            reason_code: "UO_QUERY_NOT_HOST_DRIVEN",
            host_step: { kind: "primary_router", message_zh: messageZh },
            message_zh: messageZh,
            log,
            todo: todoPayload,
          }
        }
        const actionId = String(step.action_id || asked.action_id || "")
        if (actionId && decision !== "reinit" && decision !== "continue") {
          const fin = await runAcpJson(
            ["run-action", actionId, "--finalize", "--project", project],
            project,
            acpOpts(180_000),
          )
          log.push({ event: "finalize_after_ask", action_id: actionId, ok: fin.ok !== false })
          if (fin.ok === false) {
            reporter?.setStatus("fail")
            return {
              ok: false,
              host_step: {
                kind: "failed",
                message_zh: String(fin.message_zh || fin.error || `finalize ${actionId} failed`),
              },
              log,
              finalize: fin,
            }
          }
        }
        continue
      } else if (!step.kind) {
        reporter?.setStatus("fail")
        const err = String(driven.error || driven.error_code || "ACP_NO_JSON")
        const failMsg = String(
          driven.message_zh || driven.message || driven.stderr || err,
        )
        return {
          ok: false,
          host_step: { kind: "failed", message_zh: failMsg, error_detail: err },
          log,
          error: err,
          message_zh: failMsg,
          todo: todoPayload,
        }
      } else if (step.kind !== "dispatch_subagent") {
        reporter?.setStatus("fail")
        const err = String(driven.error || step.kind || "UNEXPECTED_HOST_STEP")
        const failMsg = String(driven.message_zh || step.message_zh || driven.message || err)
        return {
          ok: false,
          host_step: { ...step, kind: "failed", message_zh: failMsg },
          log,
          error: err,
          message_zh: failMsg,
          todo: todoPayload,
        }
      }
    }

    if (step.kind === "continue_goal") {
      const nextWf = String(step.next_workflow_id || "").trim()
      if (!nextWf) {
        reporter?.setStatus("fail")
        return {
          ok: false,
          error: "CONTINUE_GOAL_MISSING_WORKFLOW",
          host_step: step,
          log,
        }
      }
      const nextArch = String(step.architecture || architecture || "").trim()
      const nextIntent = String(step.intent || intent || "").trim()
      architecture = nextArch || architecture
      intent = nextIntent || intent
      workflow = nextWf
      reporter?.setWorkflow(nextWf)
      reporter?.note(`continue ${nextWf}`)
      const continued = await consumeStartAsks(await startOnce())
      log.push({
        event: "continue_goal",
        next_workflow_id: nextWf,
        ok: isAcpStartSuccess(continued),
      })
      if (continued.answer_from_source === true) {
        return continued
      }
      if (isHumanDecision(continued)) {
        return continued
      }
      if (!isAcpStartSuccess(continued)) {
        reporter?.setStatus("fail")
        return {
          ok: false,
          host_step: {
            kind: "failed",
            message_zh: continued.message_zh || continued.error || `start ${nextWf} failed`,
          },
          log,
          start: continued,
        }
      }
      reporter?.applyTodo(continued.todo)
      pendingTodo = continued.todo
      continue
    }

    lastStep = step
    reporter?.note(`Task ${String(step.actor_id || "")}`, String(step.action_id || ""))
    const handed = nativeTaskHandoff({
      step,
      project,
      log,
      todo: todoPayload,
      sessionId: parentSessionId,
      workflow,
    })
    if (handed.ok === false) reporter?.setStatus("fail")
    else reporter?.setStatus("ok")
    return handed
  }

  reporter?.setStatus("fail")
  return {
    ok: false,
    error: "PILOT_RUN_STEP_LIMIT",
    host_step: lastStep,
    log,
    message_zh: "pilot_run 达到安全步数上限",
  }
}

/** OpenCode plugin tool definition factory. */
export function createPilotRunTool(
  client: any,
  pluginInput?: { serverUrl?: unknown; directory?: string },
) {
  return {
    pilot_run: {
      description:
        "Run an AscendC-Pilot workflow via Host Session Driver (start→auto). " +
        "Prefer this over manually chaining acp start / run-action. " +
        "When it returns host_step.kind=dispatch_subagent, use OpenCode native Task " +
        "(agent=actor_id, prompt=task_prompt_stub verbatim) so the user can jump into the child and see thinking. " +
        "If host_step.tasks has two or more entries, launch ALL of them in the same turn " +
        "(each prompt=tasks[i].task_prompt_stub verbatim), wait, then synthesize one kb-answer-v1. " +
        "Host Driver syncs Todo and owns AskQuestion when the UI is available. " +
        "Args: workflow (e.g. uo-init / tg-init / ce-review), project (operator dir), optional architecture. Never uo-query.",
      args: {
        workflow: { type: "string", description: "Workflow id (uo-init, tg-init, ce-review, …). Never uo-query." },
        project: { type: "string", description: "Operator package absolute path" },
        architecture: {
          type: "string",
          description: "Optional arch* (required for uo-init/uo-update)",
        },
        intent: {
          type: "string",
          description:
            "User product intent verbatim. For /ce-review include the GitCode/GitHub PR URL when reviewing a pull request.",
        },
        force_new: {
          type: "boolean",
          description:
            "Wipe an existing run and start fresh. Do not set on first start; omit unless the user asked to 删除重开.",
        },
      },
      async execute(toolArgs: Record<string, unknown>, ctx?: PilotToolContext) {
        capturePilotToolSession(ctx as unknown as Record<string, unknown>, toolArgs)
        const toolCtx: PilotToolContext = {
          sessionID: String(
            ctx?.sessionID ||
              ctx?.sessionId ||
              lastToolSession.sessionID ||
              (toolArgs as any).sessionID ||
              (toolArgs as any).sessionId ||
              "",
          ).trim(),
          sessionId: String(
            ctx?.sessionId || ctx?.sessionID || lastToolSession.sessionID || "",
          ).trim(),
          messageID: String(
            (ctx as any)?.messageID || lastToolSession.messageID || "",
          ).trim(),
          callID: String((ctx as any)?.callID || lastToolSession.callID || "").trim(),
          askQuestion: ctx?.askQuestion || (ctx as any)?.ask,
          question: ctx?.question,
          metadata: ctx?.metadata,
          abort: ctx?.abort,
        }
        const reporter = createProgressReporter(toolCtx, String(toolArgs.workflow || "pilot"), {
          client,
          sessionId: toolCtx.sessionID || toolCtx.sessionId,
          messageId: toolCtx.messageID,
          callID: toolCtx.callID,
          serverUrl: pluginInput?.serverUrl,
          directory: pluginInput?.directory ? String(pluginInput.directory) : undefined,
          baseInput: primitiveToolArgs(toolArgs),
        })
        try {
          const result = await runPilotDriver(
            client,
            {
              workflow: String(toolArgs.workflow || ""),
              project: String(toolArgs.project || ""),
              architecture: toolArgs.architecture ? String(toolArgs.architecture) : undefined,
              intent: toolArgs.intent ? String(toolArgs.intent) : undefined,
              forceNew: Boolean(toolArgs.force_new),
            },
            toolCtx,
            reporter,
          )
          if (isHumanDecision(result)) reporter.setStatus("ask")
          else if (result.ok === false) reporter.setStatus("fail")
          else reporter.setStatus("done")
          return toPluginToolResult(result)
        } catch (exc) {
          reporter.setStatus("fail")
          return toPluginToolResult({
            ok: false,
            error: "PILOT_RUN_THROW",
            message: String(exc),
            message_zh: "pilot_run 内部异常，已返回结构化错误；请根据 message 排查。",
          })
        } finally {
          try {
            await reporter.flushAsync()
          } catch {
            /* last PATCH is best-effort */
          }
          reporter.close()
        }
      },
    },
  }
}

/**
 * OpenCode autoloads every `*.ts` in `~/.config/opencode/plugins/`.
 * This file is a library imported by `ascendc-pilot.ts`. Without a default
 * export, the host calls a named export (`runPilotDriver` / `capturePilotToolSession`)
 * as the plugin factory: `args` is undefined → `args.project` throws, then the
 * config hook chain dies (`N.config`) and the TUI shows "Unexpected server error".
 */
export default async function PilotDriverLibraryPlugin(_ctx?: unknown) {
  return {
    config: async () => ({}),
    dispose: async () => {},
  }
}
