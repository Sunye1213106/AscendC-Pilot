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

import { spawnSync } from "node:child_process"
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

function runAcpJson(
  argv: string[],
  project: string,
  opts?: { timeoutMs?: number; env?: Record<string, string> },
): Record<string, unknown> {
  const acpBin = resolveAcpBin()
  const result = spawnSync(acpBin, argv, {
    encoding: "utf-8",
    shell: false,
    windowsHide: true,
    cwd: project,
    timeout: opts?.timeoutMs ?? 600_000,
    env: {
      ...process.env,
      ASCENDC_PROJECT_ROOT: project,
      ...(opts?.env || {}),
    },
  })
  const text = `${result.stdout || ""}\n${result.stderr || ""}`.trim()
  const jsonStart = text.indexOf("{")
  if (jsonStart < 0) {
    return {
      ok: false,
      error: "ACP_NO_JSON",
      message: (result.stderr || result.stdout || "").toString().slice(0, 800),
      exit: result.status,
    }
  }
  try {
    return JSON.parse(text.slice(jsonStart)) as Record<string, unknown>
  } catch {
    return { ok: false, error: "ACP_JSON_PARSE", message: text.slice(0, 800) }
  }
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
}

export type PilotRunArgs = {
  workflow: string
  project: string
  architecture?: string
  forceNew?: boolean
}

export type PilotToolContext = {
  sessionID?: string
  sessionId?: string
  askQuestion?: (input: Record<string, unknown>) => Promise<unknown>
  question?: (input: Record<string, unknown>) => Promise<unknown>
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
  step: HostStep
  ask: Record<string, unknown>
  log: Array<Record<string, unknown>>
  todo?: unknown
}): Promise<Record<string, unknown>> {
  const { client, toolCtx, parentSessionId, step, ask, log, todo } = args
  await syncTodos(client, parentSessionId, todo)

  const asked = await invokeAskHuman(client, toolCtx, ask, parentSessionId)
  log.push({ event: "ask_human", via: asked.via, answered: asked.answered })

  if (asked.answered) {
    return {
      ok: true,
      needs_human_decision: false,
      host_owned_ask: true,
      host_step: step,
      ask_question: ask,
      answers: asked.answers,
      log,
      message_zh:
        "Host Driver 已通过 AskQuestion 收集答复；请用原样答案继续 acp answer / resume / start。",
      todo,
    }
  }

  // UI missing: still mark host-owned so Primary must not invent options.
  return {
    ok: false,
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
}): Promise<{
  ok: boolean
  finished?: Record<string, unknown>
  error?: string
  host_step?: HostStep
}> {
  const { client, project, workflow, step, log } = args
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

  const finished = runAcpJson(
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
    { timeoutMs: 300_000 },
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
): Promise<Record<string, unknown>> {
  const project = resolve(String(args.project || "").trim())
  const workflow = String(args.workflow || "").trim()
  if (!project || !workflow) {
    return { ok: false, error: "PILOT_RUN_ARGS", message_zh: "pilot_run 需要 workflow + project" }
  }

  const parentSessionId = String(
    toolCtx?.sessionID || toolCtx?.sessionId || "",
  ).trim()

  const startArgv = ["start", workflow, "--project", project]
  if (args.architecture) startArgv.push("--architecture", String(args.architecture))
  if (args.forceNew) startArgv.push("--force-new")
  const started = runAcpJson(startArgv, project)
  if (!started.ok && !started.run_id) {
    const ask =
      started.ask_question && typeof started.ask_question === "object"
        ? (started.ask_question as Record<string, unknown>)
        : {}
    if (started.needs_human_decision || Object.keys(ask).length) {
      return handleAskHumanStep({
        client,
        toolCtx,
        parentSessionId,
        step: {
          kind: "ask_human",
          ask_question: ask,
          message_zh: String(started.message_zh || started.error || "acp start needs human"),
        },
        ask,
        log: [{ event: "start", ok: false }],
        todo: started.todo,
      })
    }
    return {
      ok: false,
      phase: "start",
      start: started,
      host_step: {
        kind: "failed",
        message_zh: started.message_zh || started.error || "acp start failed",
      },
    }
  }

  const log: Array<Record<string, unknown>> = [{ event: "start", ok: !!started.ok }]
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
    } else {
      const driven = runAcpJson(["run-action", "auto", "--project", project], project, {
        timeoutMs: 900_000,
      })
      step = (driven.host_step || {}) as HostStep
      todoPayload = driven.todo
      pendingTodo = driven.todo
      lastStep = step
      log.push({
        event: "drive",
        stop_reason: driven.stop_reason,
        host_step_kind: step.kind,
        ok: driven.ok,
      })
      const synced = await syncTodos(client, parentSessionId, todoPayload)
      log.push({ event: "todo_sync", ...synced })

      if (step.kind === "done") {
        await syncTodos(client, parentSessionId, todoPayload)
        return { ok: true, host_step: step, log, todo: todoPayload, drive: driven }
      }
      if (step.kind === "failed") {
        return { ok: false, host_step: step, log, drive: driven, todo: todoPayload }
      }
      if (step.kind === "ask_human") {
        const ask =
          (step.ask_question as Record<string, unknown>) ||
          (driven.ask_question as Record<string, unknown>) ||
          {}
        return handleAskHumanStep({
          client,
          toolCtx,
          parentSessionId,
          step,
          ask,
          log,
          todo: todoPayload,
        })
      }
      if (step.kind !== "dispatch_subagent") {
        return {
          ok: false,
          host_step: step,
          log,
          drive: driven,
          error: "UNKNOWN_HOST_STEP",
          todo: todoPayload,
        }
      }

      if (!client?.session?.create || !client?.session?.prompt) {
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

    lastStep = step
    const dispatched = await dispatchSubagentOnce({
      client,
      project,
      workflow,
      step,
      log,
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
      return {
        ok: false,
        error: "DISPATCH_INCOMPLETE",
        host_step: step,
        log,
        message_zh: "host_step 缺少 actor / stub / ticket",
      }
    }
    if (dispatched.error === "SESSION_CREATE_FAILED") {
      return { ok: false, error: "SESSION_CREATE_FAILED", host_step: step, log }
    }

    const finished = dispatched.finished || {}
    await syncTodos(client, parentSessionId, finished.todo)
    pendingTodo = finished.todo

    if (finished.host_step && typeof finished.host_step === "object") {
      const next = finished.host_step as HostStep
      if (next.kind === "done") {
        return { ok: true, host_step: next, log, todo: finished.todo }
      }
      if (next.kind === "ask_human") {
        const ask = (next.ask_question as Record<string, unknown>) || {}
        return handleAskHumanStep({
          client,
          toolCtx,
          parentSessionId,
          step: next,
          ask,
          log,
          todo: finished.todo,
        })
      }
      if (next.kind === "failed") {
        return { ok: false, host_step: next, log, todo: finished.todo }
      }
      if (next.kind === "dispatch_subagent") {
        // Consume finished.host_step directly — do not re-call auto.
        pendingStep = next
        continue
      }
    }
    if (!finished.ok) {
      return {
        ok: false,
        host_step: (finished.host_step as HostStep) || lastStep,
        log,
        dispatch_result: finished,
      }
    }
  }

  return {
    ok: false,
    error: "PILOT_RUN_STEP_LIMIT",
    host_step: lastStep,
    log,
    message_zh: "pilot_run 达到安全步数上限",
  }
}

/** OpenCode plugin tool definition factory. */
export function createPilotRunTool(client: any) {
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
          askQuestion: ctx?.askQuestion,
          question: ctx?.question,
        }
        return runPilotDriver(
          client,
          {
            workflow: String(toolArgs.workflow || ""),
            project: String(toolArgs.project || ""),
            architecture: toolArgs.architecture ? String(toolArgs.architecture) : undefined,
            forceNew: Boolean(toolArgs.force_new),
          },
          toolCtx,
        )
      },
    },
  }
}
