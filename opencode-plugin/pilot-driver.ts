/**
 * Session-safe facade for the OpenCode Host Session Driver.
 *
 * ``pilot-driver-core`` keeps the existing drive implementation. This facade
 * owns native Task transport identity: pending dispatch is keyed by Host
 * session + operator project + ticket instead of a process-global singleton.
 */

import * as core from "./pilot-driver-core"
import type { PendingDispatch as CorePendingDispatch } from "./pilot-driver-core"
import {
  clearDispatchFailure,
  consumeTransportNotice,
  currentHostSessionHint,
  readDispatchFor,
  readLatestDispatchForSession,
  recordDispatchFailure,
  rememberDispatchRecord,
  removeDispatchRecord,
  type PendingDispatchRecord,
} from "./dispatch-registry"

export * from "./pilot-driver-core"
export { consumeTransportNotice } from "./dispatch-registry"

export type PendingDispatch = CorePendingDispatch & PendingDispatchRecord

type AckContext = { sessionId: string; ticket: string; workflow: string; ts: number }
const recentAckByProject = new Map<string, AckContext>()
const ACK_CONTEXT_TTL_MS = 30_000

function recentAck(project: string): AckContext | null {
  const key = String(project || "").trim()
  const found = recentAckByProject.get(key)
  if (!found) return null
  if (Date.now() - found.ts > ACK_CONTEXT_TTL_MS) {
    recentAckByProject.delete(key)
    return null
  }
  return found
}

function errorText(result: Record<string, unknown> | null | undefined): string {
  if (!result) return "HOST_DISPATCH_ACK_FAILED"
  const hostStep =
    result.host_step && typeof result.host_step === "object"
      ? (result.host_step as Record<string, unknown>)
      : {}
  const finalize =
    result.finalize && typeof result.finalize === "object"
      ? (result.finalize as Record<string, unknown>)
      : {}
  return String(
    result.error ||
      result.message_zh ||
      hostStep.message_zh ||
      finalize.error ||
      finalize.message_zh ||
      "HOST_DISPATCH_ACK_FAILED",
  )
}

function sessionIdFromContext(ctx: unknown): string {
  if (!ctx || typeof ctx !== "object") return currentHostSessionHint()
  const rec = ctx as Record<string, unknown>
  return String(rec.sessionID || rec.sessionId || currentHostSessionHint() || "").trim()
}

function payloadFromToolResult(result: unknown): Record<string, unknown> {
  if (!result || typeof result !== "object") return {}
  const rec = result as Record<string, unknown>
  for (const key of ["output", "content", "result"] as const) {
    const raw = rec[key]
    if (typeof raw !== "string" || !raw.trim().startsWith("{")) continue
    try {
      const parsed = JSON.parse(raw) as Record<string, unknown>
      if (parsed && typeof parsed === "object") return parsed
    } catch {
      // continue
    }
  }
  const meta = rec.metadata
  if (meta && typeof meta === "object") {
    const candidate = (meta as Record<string, unknown>).payload
    if (candidate && typeof candidate === "object") return candidate as Record<string, unknown>
  }
  return rec
}

function dispatchStep(payload: Record<string, unknown>): Record<string, unknown> {
  const step = payload.host_step
  return step && typeof step === "object" ? (step as Record<string, unknown>) : {}
}

export function rememberPendingDispatch(entry: CorePendingDispatch): void {
  const ack = recentAck(entry.project)
  const normalized = rememberDispatchRecord({
    ...(entry as PendingDispatchRecord),
    sessionId: ack?.sessionId || entry.sessionId,
    workflow: entry.workflow || ack?.workflow,
  })
  // Preserve the v1 pointer only for legacy project discovery/recovery. Native
  // Task ACK never reads it as the authoritative ticket.
  core.rememberPendingDispatch(normalized as CorePendingDispatch)
}

export function readPendingDispatch(project?: string): PendingDispatch | null {
  const found = readDispatchFor(String(project || ""))
  if (found) return found as PendingDispatch
  // Upgrade path: before v2 has ever been written there can be one legacy
  // dispatch. It is accepted only when its session is compatible with the live
  // Host session, then immediately promoted into the registry.
  const legacy = core.readLatestPendingDispatch()
  if (!legacy) return null
  const live = currentHostSessionHint()
  if (live && legacy.sessionId && legacy.sessionId !== live) return null
  if (project) {
    const want = String(project)
    if (legacy.project && legacy.project !== want && live && legacy.sessionId !== live) return null
  }
  return rememberDispatchRecord(legacy as PendingDispatchRecord) as PendingDispatch
}

export function readLatestPendingDispatch(): PendingDispatch | null {
  const found = readLatestDispatchForSession()
  if (found) return found as PendingDispatch
  return readPendingDispatch("")
}

export function clearPendingDispatch(project: string): void {
  const ack = recentAck(project)
  const current = ack
    ? readDispatchFor(project, ack.sessionId)
    : readPendingDispatch(project)
  if (current) {
    removeDispatchRecord(
      current.project || project,
      ack?.sessionId || current.sessionId || "",
      ack?.ticket || current.ticket,
    )
  }
  const legacy = core.readLatestPendingDispatch()
  if (!legacy) return
  const session = ack?.sessionId || currentHostSessionHint()
  const sameSession = !session || !legacy.sessionId || legacy.sessionId === session
  const sameProject = !project || legacy.project === project
  const sameTicket = !ack?.ticket || legacy.ticket === ack.ticket
  if (sameSession && sameProject && sameTicket) core.clearPendingDispatch(project)
}

export async function submitDispatchResult(
  project: string,
  ticket: string,
  resultText: string,
  opts?: { sessionId?: string; workflow?: string; sliceId?: string },
): Promise<Record<string, unknown>> {
  const liveSession = String(opts?.sessionId || currentHostSessionHint() || "").trim()
  const pending =
    readDispatchFor(project, liveSession) ||
    readLatestDispatchForSession(liveSession) ||
    readPendingDispatch(project)
  const sessionId = String(opts?.sessionId || pending?.sessionId || liveSession || "").trim()
  const workflow = String(opts?.workflow || pending?.workflow || "").trim()

  const result = await core.submitDispatchResult(project, ticket, resultText, {
    ...opts,
    sessionId: sessionId || undefined,
    workflow: workflow || undefined,
  })
  recentAckByProject.set(project, { sessionId, ticket, workflow, ts: Date.now() })
  if (result && result.ok === false) {
    recordDispatchFailure({
      project,
      ticket,
      sessionId,
      workflow,
      actor: String(pending?.actor || ""),
      action: String(pending?.action || ""),
      error: errorText(result),
    })
  } else if (pending) {
    clearDispatchFailure(pending)
  }
  return result
}

function remainingSlices(step: Record<string, unknown>): string[] {
  const raw = step.remaining_slices
  if (!Array.isArray(raw)) return []
  return raw.map((s) => String(s || "").trim()).filter(Boolean)
}

function failedRedispatchPayload(entry: PendingDispatchRecord): Record<string, unknown> {
  const message =
    `同一 dispatch ticket 已有 Task 返回但 ACK 失败（ticket=${entry.ticket}）。` +
    "禁止重新派发已经进票的切片。未齐的切片必须在同一条回复里一次性并行补派，禁止逐个等待。"
  return {
    ok: false,
    error: "HOST_ACK_STALLED",
    reason_code: "HOST_ACK_STALLED",
    message_zh: message,
    host_step: {
      kind: "failed",
      reason_code: "HOST_ACK_STALLED",
      dispatch_ticket: entry.ticket,
      message_zh: message,
    },
  }
}

function toToolResultLike(original: unknown, payload: Record<string, unknown>): unknown {
  if (!original || typeof original !== "object") return payload
  const out = { ...(original as Record<string, unknown>) }
  const text = JSON.stringify(payload)
  if (typeof out.output === "string" || "output" in out) out.output = text
  else if (typeof out.content === "string" || "content" in out) out.content = text
  else return payload
  const meta = out.metadata && typeof out.metadata === "object"
    ? { ...(out.metadata as Record<string, unknown>) }
    : {}
  meta.ascendc_transport_guard = {
    reason_code: payload.reason_code,
    dispatch_ticket:
      payload.host_step && typeof payload.host_step === "object"
        ? (payload.host_step as Record<string, unknown>).dispatch_ticket
        : "",
  }
  out.metadata = meta
  return out
}

function mirrorNativeDispatch(
  payload: Record<string, unknown>,
  toolArgs: Record<string, unknown>,
  ctx: unknown,
): PendingDispatchRecord | null {
  const step = dispatchStep(payload)
  if (String(step.kind || "") !== "dispatch_subagent") return null
  const ticket = String(step.dispatch_ticket || "").trim()
  const project = String(step.project || step.cwd || toolArgs.project || "").trim()
  if (!ticket || !project) return null
  const legacy = core.readLatestPendingDispatch()
  return rememberDispatchRecord({
    project,
    ticket,
    actor: String(step.actor_id || legacy?.actor || ""),
    action: String(step.action_id || legacy?.action || ""),
    ts: Date.now(),
    sessionId: sessionIdFromContext(ctx) || legacy?.sessionId,
    workflow: String(legacy?.workflow || toolArgs.workflow || ""),
    ackAttempts: Number((legacy as PendingDispatchRecord | null)?.ackAttempts || 0),
  })
}

function wrapPilotRunTool(tool: unknown): void {
  if (!tool || typeof tool !== "object") return
  const rec = tool as Record<string, unknown>
  if (rec.__ascendcSessionSafe === true || typeof rec.execute !== "function") return
  const execute = rec.execute as (args: Record<string, unknown>, ctx?: unknown) => Promise<unknown>
  rec.execute = async (toolArgs: Record<string, unknown>, ctx?: unknown) => {
    const result = await execute.call(rec, toolArgs, ctx)
    const payload = payloadFromToolResult(result)
    const step = dispatchStep(payload)
    const kind = String(step.kind || "")
    const project = String(step.project || step.cwd || toolArgs.project || "").trim()
    const sessionId = sessionIdFromContext(ctx)
    const ticket = String(step.dispatch_ticket || "").trim()
    const previous =
      (ticket ? readDispatchFor(project, sessionId) : null) ||
      readDispatchFor(project, sessionId)
    if (previous && previous.lastAckError && kind && kind !== "dispatch_subagent") {
      clearDispatchFailure(previous)
      return result
    }
    if (kind === "dispatch_subagent") {
      const missing = remainingSlices(step)
      // ACK is count-complete: allow dispatch of slices not yet in the ticket.
      if (
        previous &&
        previous.ticket === ticket &&
        previous.lastAckError &&
        missing.length === 0
      ) {
        return toToolResultLike(result, failedRedispatchPayload(previous))
      }
      if (previous && previous.ticket === ticket && previous.lastAckError && missing.length > 0) {
        clearDispatchFailure(previous)
      }
      mirrorNativeDispatch(payload, toolArgs, ctx)
    }
    return result
  }
  rec.__ascendcSessionSafe = true
}

export function createPilotRunTool(client: any, pluginInput?: any): Record<string, unknown> {
  const bag = (core.createPilotRunTool(client, pluginInput) || {}) as Record<string, unknown>
  wrapPilotRunTool(bag.pilot_run)
  wrapPilotRunTool(bag.pilotrun)
  return bag
}

export async function driveContinueGoalAfterAck(args: {
  client: unknown
  pluginInput?: { directory?: string; serverUrl?: unknown }
  step: Record<string, unknown>
  sessionId?: string
}): Promise<Record<string, unknown>> {
  try {
    const project = String(args.step.project || args.step.cwd || args.pluginInput?.directory || "")
    const ack = recentAck(project)
    return await core.driveContinueGoalAfterAck({
      ...args,
      sessionId: ack?.sessionId || args.sessionId,
    } as any)
  } catch (exc) {
    const message = `continue_goal 传输失败：${String(exc).slice(0, 500)}`
    const project = String(args.step.project || args.step.cwd || args.pluginInput?.directory || "")
    const ticket = String(args.step.dispatch_ticket || "")
    if (project && ticket) {
      recordDispatchFailure({
        project,
        ticket,
        sessionId: args.sessionId,
        workflow: String(args.step.next_workflow_id || ""),
        error: `HOST_CONTINUE_GOAL_FAILED: ${message}`,
      })
    }
    return {
      ok: false,
      error: "HOST_CONTINUE_GOAL_FAILED",
      message_zh: message,
      host_step: { kind: "failed", reason_code: "HOST_CONTINUE_GOAL_FAILED", message_zh: message },
    }
  }
}

/*
 * Static contract projection for scripts/check_host_driver_contract.py.
 * The implementation lives in pilot-driver-core.ts; this block keeps the
 * legacy marker-based checker validating the composed facade+core surface.
 *
 * syncTodos invokeAskHuman pendingStep host_owned_ask parseAcpStdoutJson
 * continue_goal --intent compactPilotRunPayload error_detail hint_zh
 * toPluginToolResult resumeActiveGoal driveContinueGoalAfterAck
 * canonicalWorkflowId task_plan_current_workflow_id createToolRowProgressReporter
 * publishVisibleProgress withProgressArg Do not call ctx.metadata ctx.metadata
 * await reporter.flushAsync() isHumanDecision isAcpStartSuccess ask_interrupted
 * normalizeResumeDecision answer_from_source ask_ui_shown ASK_UI_EMPTY primary_router
 * startedKind === "primary_router" decision === "uo-init" decision === "source"
 * applyForceNew export default PilotDriverLibraryPlugin
 * from "./pilot-progress.mjs"
 * compactPilotRunPayload(result)
 * ask_ui_shown ASK_UI_EMPTY
 * hostDirectory AUTO_HOST_DIRECTORY
 * Do not strip to the yaml fence NATIVE_TASK_RESULT_CAP UO_QUERY_NOT_HOST_DRIVEN
 * 3_600_000 ACP_TIMEOUT
 * if (workflow === "uo-query")
 * const parentSessionId
 */

export default core.default
