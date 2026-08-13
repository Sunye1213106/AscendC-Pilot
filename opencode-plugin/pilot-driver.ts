/**
 * Host Session Driver for AscendC-Pilot (OpenCode).
 *
 * Moves control-plane transport out of the Primary LLM:
 *   start → drive (host_step) → session.create/prompt → dispatch-result → …
 *
 * Owns Todo sync and AskQuestion when Host APIs exist; falls back to a
 * structured ask_human payload only when the question UI cannot be invoked.
 *
 * Exposed as custom tool `pilot_run`.
 */

import { spawn } from "node:child_process"
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs"
import { homedir } from "node:os"
import { resolve } from "node:path"

function resolveAcpBin(): string {
  const fromEnv = String(process.env.ASCENDC_HARNESS_BIN || "").trim()
  if (fromEnv && existsSync(fromEnv)) return fromEnv
  try {
    const cached = readFileSync(
      resolve(homedir(), ".config", "opencode", "ascendc-harness-bin"),
      "utf-8",
    ).trim()
    if (cached && existsSync(cached)) return cached
  } catch {
    /* ignore */
  }
  return "acp"
}

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
    return {
      ok: false,
      error: "ACP_NO_JSON",
      message: (err || out).slice(0, 800),
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
] as const

function compactHostStep(step: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const key of HOST_STEP_MODEL_KEYS) {
    const value = step[key]
    if (value == null || value === "") continue
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
  const messageZh = String(rec.message_zh || step.message_zh || rec.message || "")
  const out: Record<string, unknown> = { ok }
  if (Object.keys(step).length) out.host_step = step
  if (messageZh) out.message_zh = messageZh
  if (err) out.error = err
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
  if (low === "continue" || low === "reinit") return low
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
  }
  if (aliases[key]) return aliases[key]
  if (aliases[low]) return aliases[low]
  if (key.includes("继续")) return "continue"
  if (key.includes("删除") || key.includes("重开")) return "reinit"
  return ""
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

export function renderPilotProgressBar(done: number, total: number, width = 10): string {
  const n = Math.max(1, total)
  const filled = Math.max(0, Math.min(width, Math.round((Math.max(0, done) / n) * width)))
  return `${"█".repeat(filled)}${"░".repeat(Math.max(0, width - filled))}`
}

export function formatPilotElapsed(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000))
  const m = Math.floor(s / 60)
  const r = s % 60
  return m > 0 ? `${m}:${String(r).padStart(2, "0")}` : `${r}s`
}

export type ProgressStep = { id: string; content: string }

export type ProgressReporter = {
  note: (title: string, detail?: string) => void
  applyStderrLine: (line: string) => void
  applyTodo: (todo: unknown) => void
  setWorkflow: (id: string) => void
  setStatus: (status: "running" | "ok" | "fail" | "ask" | "done") => void
  flush: () => void
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

function invokeToolMetadata(
  fn: ((input: { title?: string; metadata?: Record<string, unknown> }) => unknown) | undefined,
  input: { title?: string; metadata?: Record<string, unknown> },
): void {
  if (typeof fn !== "function") return
  try {
    const ret = fn(input)
    if (ret && typeof (ret as { then?: unknown }).then === "function") {
      void Promise.resolve(ret).catch(() => {})
    }
  } catch {
    /* Host metadata is best-effort; OpenCode 1.18.x fromPlugin does not bridge ctx.metadata Effect */
  }
}

function unwrapSdk(res: unknown): unknown {
  if (!res || typeof res !== "object") return res
  const rec = res as Record<string, unknown>
  if ("data" in rec && rec.data !== undefined && !("type" in rec)) return rec.data
  return res
}

/** GenericTool renders `input(props.input)` and ignores state.title — put the bar first. */
export function withProgressArg(
  input: Record<string, unknown> | undefined,
  progress: string,
): Record<string, unknown> {
  const rest = { ...(input || {}) }
  delete rest.progress
  return { progress, ...rest }
}

function partsFromMessagePayload(payload: unknown): any[] {
  const data = unwrapSdk(payload) as Record<string, unknown> | unknown[] | null
  const collect = (rows: unknown[]): any[] => {
    const out: any[] = []
    for (const row of rows) {
      if (!row || typeof row !== "object") continue
      const rec = row as Record<string, unknown>
      if (typeof rec.type === "string" && rec.type === "tool") {
        out.push(row)
        continue
      }
      if (Array.isArray(rec.parts)) out.push(...(rec.parts as any[]))
      else if (rec.info && Array.isArray((rec as any).parts)) out.push(...((rec as any).parts as any[]))
    }
    return out
  }
  if (Array.isArray(data)) {
    if (data.length && (data[0] as any)?.type) return data
    return collect(data)
  }
  if (!data || typeof data !== "object") return []
  const rec = data as Record<string, unknown>
  if (Array.isArray(rec.parts)) return rec.parts as any[]
  if (Array.isArray(rec.messages)) return collect(rec.messages as unknown[])
  return []
}

function isPilotRunPart(part: any, callID?: string): boolean {
  if (!part || part.type !== "tool") return false
  const name = String(part.tool || "").toLowerCase()
  if (name !== "pilot_run" && name !== "pilotrun") return false
  if (callID && part.callID && String(part.callID) !== callID) return false
  return true
}

async function findRunningPilotPart(
  client: any,
  sessionId: string,
  messageId: string,
  callID?: string,
  serverUrl?: unknown,
): Promise<any | null> {
  if (!sessionId) return null
  const attempts: Array<() => Promise<unknown>> = []
  if (client && messageId && typeof client.session?.message === "function") {
    attempts.push(() => client.session.message({ sessionID: sessionId, messageID: messageId }))
    attempts.push(() =>
      client.session.message({ path: { sessionID: sessionId, messageID: messageId } }),
    )
  }
  if (client && typeof client.session?.messages === "function") {
    attempts.push(() => client.session.messages({ sessionID: sessionId, limit: 8 }))
    attempts.push(() => client.session.messages({ path: { id: sessionId }, query: { limit: 8 } }))
  }
  const base = clientBaseUrl(client, serverUrl)
  if (base && messageId) {
    attempts.push(async () => {
      const res = await fetch(
        `${base}/session/${encodeURIComponent(sessionId)}/message/${encodeURIComponent(messageId)}`,
      )
      if (!res.ok) throw new Error(String(res.status))
      return res.json()
    })
  }
  if (base) {
    attempts.push(async () => {
      const res = await fetch(
        `${base}/session/${encodeURIComponent(sessionId)}/message?limit=8`,
      )
      if (!res.ok) throw new Error(String(res.status))
      return res.json()
    })
  }
  for (const fn of attempts) {
    try {
      const parts = partsFromMessagePayload(await fn())
      const running = [...parts]
        .reverse()
        .find(
          (p) =>
            isPilotRunPart(p, callID) &&
            (p.state?.status === "running" || p.state?.status === "pending"),
        )
      if (running) return running
      const anyHit = [...parts].reverse().find((p) => isPilotRunPart(p, callID))
      if (anyHit) return anyHit
    } catch {
      /* try next shape */
    }
  }
  return null
}

function sdkCallOk(res: unknown): boolean {
  if (res == null) return true
  if (typeof res !== "object") return true
  const rec = res as Record<string, unknown>
  if (rec.error) return false
  const nested = rec.response as { status?: number } | undefined
  if (nested && typeof nested.status === "number" && nested.status >= 400) return false
  return true
}

function clientBaseUrl(client: any, serverUrl?: unknown): string {
  const fromPlugin = serverUrl ? String(serverUrl) : ""
  const fromClient = String(client?.baseUrl || client?._baseUrl || "")
  return (fromPlugin || fromClient).replace(/\/$/, "")
}

async function patchRunningToolPart(
  client: any,
  part: any,
  title: string,
  baseInput: Record<string, unknown>,
  serverUrl?: unknown,
): Promise<boolean> {
  if (!part?.id) return false
  const sessionID = String(part.sessionID || "")
  const messageID = String(part.messageID || "")
  const partID = String(part.id)
  const next = {
    ...part,
    state: {
      ...(part.state || {}),
      status: part.state?.status === "pending" ? "running" : part.state?.status || "running",
      title,
      metadata: { ...(part.state?.metadata || {}), progress: title },
      input: withProgressArg(baseInput, title),
    },
  }
  const attempts: Array<() => Promise<unknown>> = []
  if (typeof client.part?.update === "function") {
    attempts.push(() =>
      client.part.update({ sessionID, messageID, partID, part: next }),
    )
    attempts.push(() =>
      client.part.update({
        path: { sessionID, messageID, partID },
        body: next,
        part: next,
      }),
    )
  }
  if (typeof client.session?.updatePart === "function") {
    attempts.push(() =>
      client.session.updatePart({ sessionID, messageID, partID, part: next }),
    )
  }
  const base = clientBaseUrl(client, serverUrl)
  if (base && sessionID && messageID && partID) {
    const url = `${base}/session/${encodeURIComponent(sessionID)}/message/${encodeURIComponent(messageID)}/part/${encodeURIComponent(partID)}`
    attempts.push(async () => {
      const res = await fetch(url, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(next),
      })
      if (!res.ok) {
        const retry = await fetch(url, {
          method: "PUT",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(next),
        })
        if (!retry.ok) throw new Error(`part update ${retry.status}`)
        return retry
      }
      return res
    })
  }
  for (const fn of attempts) {
    try {
      const res = await fn()
      if (sdkCallOk(res)) return true
    } catch {
      /* try next shape */
    }
  }
  return false
}

function createProgressReporter(
  ctx: PilotToolContext | undefined,
  workflow: string,
  opts?: { client?: any; sessionId?: string; messageId?: string; callID?: string; serverUrl?: unknown },
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
  let cachedPart: any = null
  let baseInput: Record<string, unknown> | null = null
  let patchingToolRow = false

  const emit = (title: string, extra?: Record<string, unknown>) => {
    if (state.closed) return
    invokeToolMetadata(ctx?.metadata, { title, metadata: extra })
  }

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
    const label = state.currentLabel || state.currentId || state.workflow
    const detail = state.detail ? ` · ${state.detail.slice(0, 36)}` : ""
    const elapsed = formatPilotElapsed(Date.now() - state.startedAt)
    return `${state.workflow}  [${bar}] ${n}  ${label}${detail}  ${elapsed}`
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

  const publishToolRow = (title: string) => {
    const client = opts?.client
    const sessionId = String(opts?.sessionId || ctx?.sessionID || ctx?.sessionId || "").trim()
    const messageId = String(opts?.messageId || ctx?.messageID || "").trim()
    const callID = String(opts?.callID || ctx?.callID || "").trim()
    if (!client || !sessionId || patchingToolRow) return
    patchingToolRow = true
    void (async () => {
      try {
        if (!cachedPart) {
          cachedPart = await findRunningPilotPart(
            client,
            sessionId,
            messageId,
            callID || undefined,
            opts?.serverUrl,
          )
          if (cachedPart?.state?.input && typeof cachedPart.state.input === "object") {
            const inp = { ...(cachedPart.state.input as Record<string, unknown>) }
            delete inp.progress
            baseInput = inp
          } else {
            baseInput = {}
          }
        }
        if (!cachedPart) return
        if (!cachedPart.sessionID) cachedPart.sessionID = sessionId
        if (!cachedPart.messageID && messageId) cachedPart.messageID = messageId
        await patchRunningToolPart(client, cachedPart, title, baseInput || {}, opts?.serverUrl)
      } catch {
        cachedPart = null
        baseInput = null
      } finally {
        patchingToolRow = false
      }
    })()
  }

  const showProgressToast = (title: string) => {
    const client = opts?.client
    const toastKey = `${state.workflow}:${state.currentId}:${state.status}`
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
    publishToolRow(title)
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
    const title = render()
    emit(title, {
      workflow: state.workflow,
      phase: state.currentId,
      status: state.status,
      elapsed_ms: Date.now() - state.startedAt,
    })
    publishVisibleProgress(title)
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
    close() {
      state.closed = true
      clearInterval(timer)
    },
  }
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

    const timeoutMs = opts?.timeoutMs ?? 600_000
    const timer = setTimeout(() => {
      try {
        proc.kill()
      } catch {
        /* ignore */
      }
      finish({
        ok: false,
        error: "ACP_TIMEOUT",
        message: `acp ${argv[0] || ""} timed out after ${timeoutMs}ms`,
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

function extractKbAnswer(text: string): string {
  const src = String(text || "")
  const fence = src.match(/```(?:ya?ml)?\s*\n([\s\S]*?```)/i)
  if (fence) {
    const inner = fence[1].replace(/```\s*$/, "").trim()
    if (/schema\s*:\s*kb-answer-v1/i.test(inner)) return inner
  }
  if (/schema\s*:\s*kb-answer-v1/i.test(src)) return src
  return src.slice(0, 24000)
}

function authIpcDir(): string {
  return resolve(homedir(), ".config", "opencode", "ascendc-auth-ipc")
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
  registerSessionIpc(args)
}

type HostStep = {
  kind?: string
  action_id?: string
  actor_id?: string
  cwd?: string
  dispatch_ticket?: string
  task_prompt_stub?: string
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
}> {
  const opts = ask.options
  if (!Array.isArray(opts)) return []
  const out: Array<{ label: string; description?: string }> = []
  for (const o of opts) {
    if (typeof o === "string") {
      out.push({ label: o })
      continue
    }
    if (!o || typeof o !== "object") continue
    const row = o as Record<string, unknown>
    const label = String(row.label || row.value || row.id || "").trim()
    if (!label) continue
    out.push({
      label,
      description: row.description ? String(row.description) : undefined,
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
        { timeoutMs: 60_000, abort: toolCtx?.abort },
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
      host_step: step,
      ask_question: ask,
      answers: asked.answers,
      resume_decision: decision,
      architecture_choice: archChoice,
      log,
      message_zh: "Host Driver 已收集答复并写入 acp answer。",
      todo,
    }
  }

  // UI missing: still mark host-owned so Primary must not invent options.
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
      "需要人工确认：请立即用 AskQuestion，options 必须原样使用 ask_question.options；禁止自行改写选项。",
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
    finalText = JSON.stringify(data || {}).slice(0, 24000)
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

export async function runPilotDriver(
  client: any,
  args: PilotRunArgs,
  toolCtx?: PilotToolContext,
  reporter?: ProgressReporter,
): Promise<Record<string, unknown>> {
  const project = resolve(String(args.project || "").trim())
  let workflow = String(args.workflow || "").trim()
  if (!project || !workflow) {
    return { ok: false, error: "PILOT_RUN_ARGS", message_zh: "pilot_run 需要 workflow + project" }
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
  })

  // force_new / 删除重开 applies only to this start, not continue_goal's next workflow.
  let applyForceNew = Boolean(args.forceNew)
  const startOnce = (extra: string[] = []) => {
    const argv = ["start", workflow, "--project", project, ...extra]
    if (architecture) argv.push("--architecture", architecture)
    if (intent) argv.push("--intent", intent)
    if (applyForceNew) argv.push("--force-new")
    return runAcpJson(argv, project, acpOpts())
  }

  const consumeStartAsks = async (
    initial: Record<string, unknown>,
  ): Promise<Record<string, unknown>> => {
    let payload = initial
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
      const decision = String(asked.resume_decision || "")
      const archChoice = String(asked.architecture_choice || "")
      if (decision) {
        payload = await startOnce(["--decision", decision])
        continue
      }
      if (archChoice) {
        architecture = archChoice
        payload = await startOnce()
        continue
      }
      return asked
    }
    return payload
  }

  const started = await consumeStartAsks(await startOnce())
  // Answered AskQuestion blobs still carry ask_question; do not treat them as start-failed.
  if (isHumanDecision(started)) {
    return started
  }
  if (!isAcpStartSuccess(started)) {
    reporter?.setStatus("fail")
    return {
      ok: false,
      phase: "start",
      start: started,
      host_step: {
        kind: "failed",
        message_zh: String(started.message_zh || started.error || "acp start failed"),
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
        acpOpts(900_000),
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
        return { ok: false, host_step: step, log, drive: driven, todo: todoPayload }
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
        return handleAskHumanStep({
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
      } else if (step.kind !== "dispatch_subagent") {
        reporter?.setStatus("fail")
        return {
          ok: false,
          host_step: step,
          log,
          drive: driven,
          error: "UNKNOWN_HOST_STEP",
          todo: todoPayload,
        }
      } else if (!client?.session?.create || !client?.session?.prompt) {
        return {
          ok: true,
          deferred_to_llm: true,
          host_step: step,
          log,
          todo: todoPayload,
          message_zh:
            "OpenCode client.session API 不可用；请 Primary 用 Task 原样派发 task_prompt_stub，再 acp dispatch-result",
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
    const dispatched = await dispatchSubagentOnce({
      client,
      project,
      workflow,
      step,
      log,
      reporter,
      abort: toolCtx?.abort,
    })

    if (dispatched.error === "SESSION_API_MISSING") {
      return {
        ok: true,
        deferred_to_llm: true,
        host_step: step,
        log,
        message_zh:
          "OpenCode client.session API 不可用；请 Primary 用 Task 原样派发 task_prompt_stub，再 acp dispatch-result",
      }
    }
    if (dispatched.error === "DISPATCH_INCOMPLETE") {
      reporter?.setStatus("fail")
      return {
        ok: false,
        error: "DISPATCH_INCOMPLETE",
        host_step: step,
        log,
        message_zh: "host_step 缺少 actor / stub / ticket",
      }
    }
    if (dispatched.error === "SESSION_CREATE_FAILED") {
      reporter?.setStatus("fail")
      return { ok: false, error: "SESSION_CREATE_FAILED", host_step: step, log }
    }

    const finished = dispatched.finished || {}
    await syncTodos(client, parentSessionId, finished.todo)
    pendingTodo = finished.todo

    if (finished.host_step && typeof finished.host_step === "object") {
      const next = finished.host_step as HostStep
      if (next.kind === "done") {
        reporter?.setStatus("done")
        return { ok: true, host_step: next, log, todo: finished.todo }
      }
      if (next.kind === "ask_human") {
        reporter?.setStatus("ask")
        const ask = (next.ask_question as Record<string, unknown>) || {}
        return handleAskHumanStep({
          client,
          toolCtx,
          parentSessionId,
          project,
          requestId: String(
            (finished.human_interaction_request &&
            typeof finished.human_interaction_request === "object"
              ? (finished.human_interaction_request as Record<string, unknown>).request_id
              : "") || "",
          ),
          step: next,
          ask,
          log,
          todo: finished.todo,
        })
      }
      if (next.kind === "failed") {
        reporter?.setStatus("fail")
        return { ok: false, host_step: next, log, todo: finished.todo }
      }
      if (next.kind === "continue_goal") {
        pendingStep = next
        continue
      }
      if (next.kind === "dispatch_subagent") {
        // Consume finished.host_step directly — do not re-call auto.
        pendingStep = next
        continue
      }
    }
    if (!finished.ok) {
      reporter?.setStatus("fail")
      return {
        ok: false,
        host_step: (finished.host_step as HostStep) || lastStep,
        log,
        dispatch_result: finished,
      }
    }
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
export function createPilotRunTool(client: any, pluginInput?: { serverUrl?: unknown }) {
  return {
    pilot_run: {
      description:
        "Run an AscendC-Pilot workflow via Host Session Driver (start→auto→dispatch→finalize). " +
        "Prefer this over manually chaining acp start / run-action / Task. " +
        "Host Driver syncs Todo and owns AskQuestion when the UI is available. " +
        "Args: workflow (e.g. uo-init), project (operator dir), optional architecture.",
      args: {
        workflow: { type: "string", description: "Workflow id (uo-init, tg-init, uo-query, …)" },
        project: { type: "string", description: "Operator package absolute path" },
        architecture: {
          type: "string",
          description: "Optional arch* (required for uo-init/uo-update)",
        },
        intent: {
          type: "string",
          description:
            "User product intent verbatim (e.g. 建立全量 TilingKey 覆盖测试). Required for User Goal chaining.",
        },
        force_new: { type: "boolean", description: "Pass --force-new to acp start" },
      },
      async execute(toolArgs: Record<string, unknown>, ctx?: PilotToolContext) {
        const toolCtx: PilotToolContext = {
          sessionID: String(
            ctx?.sessionID ||
              ctx?.sessionId ||
              (toolArgs as any).sessionID ||
              (toolArgs as any).sessionId ||
              "",
          ).trim(),
          sessionId: String(ctx?.sessionId || ctx?.sessionID || "").trim(),
          messageID: String((ctx as any)?.messageID || "").trim(),
          callID: String((ctx as any)?.callID || "").trim(),
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
          reporter.close()
        }
      },
    },
  }
}
