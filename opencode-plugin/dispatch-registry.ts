/** Session-safe pending dispatch registry for the OpenCode Host Adapter. */

import {
  existsSync,
  mkdirSync,
  readFileSync,
  renameSync,
  unlinkSync,
  writeFileSync,
} from "node:fs"
import { resolve } from "node:path"
import { openCodeHome } from "./opencode-home.mjs"

export type PendingDispatchRecord = {
  project: string
  ticket: string
  actor: string
  action: string
  ts: number
  sessionId?: string
  workflow?: string
  ackAttempts?: number
  lastAckError?: string
  lastAckFailedAt?: number
  errorReportedAt?: number
}

type RegistryDoc = {
  schema: "ascendc-pending-dispatch/v2"
  entries: PendingDispatchRecord[]
}

const SCHEMA: RegistryDoc["schema"] = "ascendc-pending-dispatch/v2"
const MAX_ENTRIES = 128

export function pendingDispatchRegistryPath(): string {
  return resolve(openCodeHome(), "ascendc-pending-dispatch-v2.json")
}

function liveSessionPath(): string {
  return resolve(openCodeHome(), "ascendc-last-project.session")
}

export function currentHostSessionHint(): string {
  try {
    const path = liveSessionPath()
    return existsSync(path) ? readFileSync(path, "utf-8").trim() : ""
  } catch {
    return ""
  }
}

function normalizeProject(project: string): string {
  const raw = String(project || "").trim()
  if (!raw) return ""
  try {
    return resolve(raw)
  } catch {
    return raw
  }
}

function normalizeEntry(entry: PendingDispatchRecord): PendingDispatchRecord {
  return {
    ...entry,
    project: normalizeProject(entry.project),
    ticket: String(entry.ticket || "").trim(),
    actor: String(entry.actor || "").trim(),
    action: String(entry.action || "").trim(),
    sessionId: String(entry.sessionId || "").trim() || undefined,
    workflow: String(entry.workflow || "").trim() || undefined,
    ts: Number(entry.ts || Date.now()),
  }
}

function keyOf(entry: PendingDispatchRecord): string {
  const item = normalizeEntry(entry)
  return `${item.sessionId || "-"}\n${item.project}\n${item.ticket}`
}

export function loadPendingDispatchRegistry(): RegistryDoc {
  try {
    const path = pendingDispatchRegistryPath()
    if (!existsSync(path)) return { schema: SCHEMA, entries: [] }
    const parsed = JSON.parse(readFileSync(path, "utf-8")) as Partial<RegistryDoc>
    const entries = Array.isArray(parsed.entries)
      ? parsed.entries
          .filter((item): item is PendingDispatchRecord => Boolean(item && typeof item === "object"))
          .map(normalizeEntry)
          .filter((item) => item.project && item.ticket)
      : []
    return { schema: SCHEMA, entries }
  } catch {
    return { schema: SCHEMA, entries: [] }
  }
}

function saveRegistry(doc: RegistryDoc): void {
  const path = pendingDispatchRegistryPath()
  const tmp = `${path}.tmp-${process.pid}-${Date.now()}`
  mkdirSync(openCodeHome(), { recursive: true })
  const entries = [...doc.entries]
    .sort((a, b) => Number(b.ts || 0) - Number(a.ts || 0))
    .slice(0, MAX_ENTRIES)
  writeFileSync(tmp, JSON.stringify({ schema: SCHEMA, entries }), "utf-8")
  renameSync(tmp, path)
}

export function rememberDispatchRecord(entry: PendingDispatchRecord): PendingDispatchRecord {
  const normalized = normalizeEntry(entry)
  if (!normalized.project || !normalized.ticket) return normalized
  const doc = loadPendingDispatchRegistry()
  const wanted = keyOf(normalized)
  const prior = doc.entries.find((item) => keyOf(item) === wanted)
  const merged = normalizeEntry({ ...prior, ...normalized })
  doc.entries = [merged, ...doc.entries.filter((item) => keyOf(item) !== wanted)]
  saveRegistry(doc)
  return merged
}

export function readDispatchFor(
  project: string,
  sessionId: string = currentHostSessionHint(),
): PendingDispatchRecord | null {
  const normalizedProject = normalizeProject(project)
  const sid = String(sessionId || "").trim()
  const entries = loadPendingDispatchRegistry().entries

  const bySession = sid ? entries.filter((item) => item.sessionId === sid) : []
  if (sid) {
    const exact = normalizedProject
      ? bySession.filter((item) => item.project === normalizedProject)
      : bySession
    if (exact.length) return exact.sort((a, b) => b.ts - a.ts)[0]
    // Task hooks may report workspace cwd instead of operator cwd. A unique
    // session record is still safe; never cross session to guess the ticket.
    if (bySession.length === 1) return bySession[0]
    return null
  }

  if (normalizedProject) {
    const matches = entries.filter((item) => item.project === normalizedProject)
    if (matches.length === 1) return matches[0]
    if (matches.length > 1) return null
  }
  return entries.length === 1 ? entries[0] : null
}

export function readLatestDispatchForSession(
  sessionId: string = currentHostSessionHint(),
): PendingDispatchRecord | null {
  const sid = String(sessionId || "").trim()
  const entries = loadPendingDispatchRegistry().entries
  if (sid) {
    const matches = entries.filter((item) => item.sessionId === sid)
    return matches.length ? matches.sort((a, b) => b.ts - a.ts)[0] : null
  }
  return entries.length === 1 ? entries[0] : null
}

export function removeDispatchRecord(
  project: string,
  sessionId: string = currentHostSessionHint(),
  ticket = "",
): void {
  const normalizedProject = normalizeProject(project)
  const sid = String(sessionId || "").trim()
  const tid = String(ticket || "").trim()
  const doc = loadPendingDispatchRegistry()
  doc.entries = doc.entries.filter((item) => {
    if (normalizedProject && item.project !== normalizedProject) return true
    if (sid && item.sessionId !== sid) return true
    if (tid && item.ticket !== tid) return true
    return false
  })
  if (doc.entries.length) {
    saveRegistry(doc)
    return
  }
  try {
    unlinkSync(pendingDispatchRegistryPath())
  } catch {
    // already gone
  }
}

export function recordDispatchFailure(args: {
  project: string
  ticket: string
  sessionId?: string
  workflow?: string
  actor?: string
  action?: string
  error: string
}): PendingDispatchRecord {
  const existing = readDispatchFor(args.project, args.sessionId) || {
    project: args.project,
    ticket: args.ticket,
    actor: args.actor || "",
    action: args.action || "",
    ts: Date.now(),
    sessionId: args.sessionId,
    workflow: args.workflow,
  }
  return rememberDispatchRecord({
    ...existing,
    project: args.project,
    ticket: args.ticket,
    sessionId: args.sessionId || existing.sessionId,
    workflow: args.workflow || existing.workflow,
    actor: args.actor || existing.actor,
    action: args.action || existing.action,
    ts: Date.now(),
    ackAttempts: Number(existing.ackAttempts || 0) + 1,
    lastAckError: String(args.error || "HOST_DISPATCH_ACK_FAILED").slice(0, 800),
    lastAckFailedAt: Date.now(),
    errorReportedAt: undefined,
  })
}

export function clearDispatchFailure(entry: PendingDispatchRecord): PendingDispatchRecord {
  return rememberDispatchRecord({
    ...entry,
    lastAckError: undefined,
    lastAckFailedAt: undefined,
    errorReportedAt: undefined,
    ts: Date.now(),
  })
}

export type TransportNotice = {
  reason_code: "HOST_DISPATCH_ACK_FAILED"
  ticket: string
  project: string
  sessionId: string
  error: string
  message_zh: string
}

export function consumeTransportNotice(
  sessionId: string = currentHostSessionHint(),
): TransportNotice | null {
  const sid = String(sessionId || "").trim()
  const doc = loadPendingDispatchRegistry()
  const candidates = doc.entries
    .filter((item) => Boolean(item.lastAckError) && !item.errorReportedAt)
    .filter((item) => !sid || item.sessionId === sid)
    .sort((a, b) => Number(b.lastAckFailedAt || b.ts) - Number(a.lastAckFailedAt || a.ts))
  const entry = candidates[0]
  if (!entry) return null
  entry.errorReportedAt = Date.now()
  saveRegistry(doc)
  return {
    reason_code: "HOST_DISPATCH_ACK_FAILED",
    ticket: entry.ticket,
    project: entry.project,
    sessionId: String(entry.sessionId || sid || ""),
    error: String(entry.lastAckError || "HOST_DISPATCH_ACK_FAILED"),
    message_zh:
      `原生 Task 已返回，但 Host ACK/dispatch-result 失败（ticket=${entry.ticket}）。` +
      "已阻止把同一 ticket 当成新的 CE Task 重派；请查看 status / inspect-failure 后重试传输。",
  }
}
