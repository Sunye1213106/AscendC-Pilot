/**
 * Live progress for OpenCode GenericTool.
 *
 * GenericTool only renders primitive `state.input` args and ignores title.
 * Host `ctx.metadata()` is an un-run Effect AND resets input to the original
 * args — never call it from this path.
 *
 * The only visible channel is PATCH /session/:id/message/:mid/part/:pid with a
 * clean ToolStateRunning body whose first input key is `progress`.
 */
import { appendFileSync, mkdirSync } from "node:fs"
import { dirname, resolve } from "node:path"
import { openCodeHome } from "./opencode-home.mjs"

export function renderPilotProgressBar(done, total, width = 10) {
  const n = Math.max(1, total)
  const filled = Math.max(0, Math.min(width, Math.round((Math.max(0, done) / n) * width)))
  return `${"█".repeat(filled)}${"░".repeat(Math.max(0, width - filled))}`
}

export function formatPilotElapsed(ms) {
  const s = Math.max(0, Math.floor(ms / 1000))
  const m = Math.floor(s / 60)
  const r = s % 60
  return m > 0 ? `${m}:${String(r).padStart(2, "0")}` : `${r}s`
}

/** GenericTool: `⚙ tool [k=v, …]` over primitive input keys, insertion order. */
export function withProgressArg(input, progress) {
  const rest = { ...(input || {}) }
  delete rest.progress
  return { progress, ...rest }
}

export function genericToolInputLabel(input) {
  const primitives = Object.entries(input || {}).filter(
    ([, value]) => typeof value === "string" || typeof value === "number" || typeof value === "boolean",
  )
  if (!primitives.length) return ""
  return `[${primitives.map(([key, value]) => `${key}=${value}`).join(", ")}]`
}

function serializeUnknown(value) {
  if (value == null) return value
  if (typeof value === "string") return value.slice(0, 800)
  if (value instanceof Error) {
    return { name: value.name, message: value.message, stack: String(value.stack || "").slice(0, 400) }
  }
  try {
    return JSON.parse(JSON.stringify(value))
  } catch {
    return String(value).slice(0, 800)
  }
}

function defaultLogPath() {
  return resolve(openCodeHome(), "logs", "pilot-progress.jsonl")
}

const NOISY_EVENTS = new Set(["patch_fail", "find_miss", "patch_skip", "patch_queue_error", "session_list_fail"])
let lastNoisyLogAt = 0

export function progressLog(event, fields, sink) {
  const rec = { ts: new Date().toISOString(), event, ...(fields || {}) }
  if (typeof sink === "function") {
    sink(rec)
    return rec
  }
  // Never write stderr/stdout. OpenCode TUI prints console.error as extra
  // lines, which is the multi-line refresh that hides the single tool row.
  if (NOISY_EVENTS.has(event) && Date.now() - lastNoisyLogAt < 15000) return rec
  if (NOISY_EVENTS.has(event)) lastNoisyLogAt = Date.now()
  try {
    const line = `${JSON.stringify(rec)}\n`
    const path = defaultLogPath()
    mkdirSync(dirname(path), { recursive: true })
    appendFileSync(path, line, "utf-8")
  } catch {
    /* file log is best-effort */
  }
  return rec
}

export function unwrapSdk(res) {
  let cur = res
  for (let i = 0; i < 4; i++) {
    if (!cur || typeof cur !== "object") return cur
    const rec = cur
    if ("data" in rec && rec.data !== undefined && rec.data !== rec && !("type" in rec)) {
      cur = rec.data
      continue
    }
    break
  }
  return cur
}

function isEffectLike(value) {
  if (!value || typeof value !== "object") return false
  if (typeof value.then === "function") return false
  return typeof value.pipe === "function" || Boolean(value._op) || Boolean(value._tag)
}

export function sdkCallOk(res) {
  if (res == null) return true
  if (typeof res !== "object") return true
  if (isEffectLike(res)) return false
  const rec = res
  if (rec.error) return false
  const nested = rec.response
  if (nested && typeof nested.status === "number" && nested.status >= 400) return false
  if (typeof rec.ok === "boolean" && rec.ok === false) return false
  if (typeof rec.status === "number" && rec.status >= 400) return false
  return true
}

/** OpenCode 1.18 plugin client is v1 SDK: `_client` + `session`, no `part`. */
export function sdkInner(client) {
  return client?._client || client?.client || null
}

export function clientConfig(client) {
  const inner = sdkInner(client)
  try {
    if (inner && typeof inner.getConfig === "function") return inner.getConfig() || {}
  } catch {
    /* ignore */
  }
  return {}
}

function headerRecord(headers) {
  if (!headers) return {}
  const out = {}
  if (typeof headers.forEach === "function") {
    headers.forEach((value, key) => {
      out[String(key)] = String(value)
    })
    return out
  }
  if (typeof headers === "object") {
    for (const [key, value] of Object.entries(headers)) {
      if (value != null && typeof value !== "object") out[key] = String(value)
    }
  }
  return out
}

function stripSlash(url) {
  return String(url || "").replace(/\/$/, "")
}

function isDummyOpenCodeUrl(url) {
  try {
    const parsed = new URL(url)
    const host = parsed.hostname
    return (host === "localhost" || host === "127.0.0.1") && parsed.port === "4096"
  } catch {
    return false
  }
}

export function clientBaseUrl(client, serverUrl) {
  const cfg = clientConfig(client)
  const fromCfg = stripSlash(cfg.baseUrl)
  const fromClient = stripSlash(client?.baseUrl || client?._baseUrl)
  const fromPlugin = stripSlash(serverUrl)
  // Prefer the SDK client's baseUrl. Plugin `serverUrl` falls back to
  // http://localhost:4096 when Server.url is unset; global fetch then fails
  // ("Unable to connect") while GET still works via in-process app.fetch.
  for (const candidate of [fromCfg, fromClient, fromPlugin]) {
    if (candidate && !isDummyOpenCodeUrl(candidate)) return candidate
  }
  return fromCfg || fromClient || fromPlugin
}

async function clientFetch(client, url, init = {}) {
  const cfg = clientConfig(client)
  const fetchFn = typeof cfg.fetch === "function" ? cfg.fetch : fetch
  const headers = { ...headerRecord(cfg.headers), ...headerRecord(init.headers) }
  const req = new Request(url, { ...init, headers })
  return fetchFn(req)
}

function withDirectoryQuery(query, directory) {
  const dir = String(directory || "").trim()
  if (!dir) return query
  return { ...(query || {}), directory: dir }
}

function collectToolParts(node, out = [], depth = 0) {
  if (depth > 8 || node == null) return out
  if (Array.isArray(node)) {
    for (const row of node) collectToolParts(row, out, depth + 1)
    return out
  }
  if (typeof node !== "object") return out
  const rec = node
  if (typeof rec.type === "string" && rec.type === "tool") out.push(rec)
  if (Array.isArray(rec.parts)) collectToolParts(rec.parts, out, depth + 1)
  if (rec.info && typeof rec.info === "object") collectToolParts(rec.info, out, depth + 1)
  if (Array.isArray(rec.messages)) collectToolParts(rec.messages, out, depth + 1)
  if (rec.data !== undefined && rec.data !== rec && !("type" in rec)) {
    collectToolParts(rec.data, out, depth + 1)
  }
  return out
}

export function partsFromMessagePayload(payload) {
  return collectToolParts(unwrapSdk(payload))
}

export function isPilotRunPart(part, callID) {
  if (!part || part.type !== "tool") return false
  const name = String(part.tool || "").toLowerCase()
  if (name !== "pilot_run" && name !== "pilotrun") return false
  if (callID && part.callID && String(part.callID) !== String(callID)) return false
  return true
}

function pickId(part, keys) {
  for (const key of keys) {
    const v = part?.[key]
    if (typeof v === "string" && v.trim()) return v.trim()
  }
  return ""
}

export function normalizePartIds(part, fallback = {}) {
  return {
    partID: pickId(part, ["id", "partID", "partId"]) || String(fallback.partID || "").trim(),
    sessionID:
      pickId(part, ["sessionID", "sessionId", "session_id"]) ||
      String(fallback.sessionID || "").trim(),
    messageID:
      pickId(part, ["messageID", "messageId", "message_id"]) ||
      String(fallback.messageID || "").trim(),
    callID: pickId(part, ["callID", "callId", "call_id"]) || String(fallback.callID || "").trim(),
    tool: String(part?.tool || "pilot_run"),
  }
}

/**
 * OpenCode 1.18 PATCH validates SessionV1.Part. Spreading the GET part keeps
 * pending `raw` / extra keys and 400s. Build a minimal ToolStateRunning body.
 */
export function buildToolPartProgressPatch(part, title, baseInput, fallbackIds = {}) {
  const ids = normalizePartIds(part, fallbackIds)
  const start = Number(part?.state?.time?.start)
  return {
    id: ids.partID,
    sessionID: ids.sessionID,
    messageID: ids.messageID,
    type: "tool",
    callID: ids.callID,
    tool: ids.tool,
    state: {
      status: "running",
      input: withProgressArg(baseInput, title),
      title,
      metadata: { progress: title },
      time: { start: Number.isFinite(start) && start > 0 ? start : Date.now() },
    },
  }
}

/**
 * Mirrors OpenCode 1.18 SessionHttpApi.updatePart + ToolStateRunning.
 * Used by tests; also documents why the old spread-body 400'd.
 */
export function validateOpencodeToolPartPatch(params, body) {
  if (!body || typeof body !== "object") return { ok: false, status: 400, error: "empty body" }
  if (
    body.id !== params.partID ||
    body.messageID !== params.messageID ||
    body.sessionID !== params.sessionID
  ) {
    return {
      ok: false,
      status: 400,
      error: "id mismatch",
      expected: params,
      got: { id: body.id, sessionID: body.sessionID, messageID: body.messageID },
    }
  }
  if (body.type !== "tool") return { ok: false, status: 400, error: "type must be tool" }
  const st = body.state
  if (!st || typeof st !== "object") return { ok: false, status: 400, error: "missing state" }
  if (st.status !== "running") return { ok: false, status: 400, error: "status must be running" }
  if (st.raw !== undefined) {
    return { ok: false, status: 400, error: "raw not allowed on ToolStateRunning" }
  }
  if (!st.time || typeof st.time.start !== "number") {
    return { ok: false, status: 400, error: "time.start required" }
  }
  if (!st.input || typeof st.input !== "object" || Array.isArray(st.input)) {
    return { ok: false, status: 400, error: "input object required" }
  }
  return { ok: true, status: 200, part: body }
}

async function awaitClientResult(res) {
  if (res == null) return res
  if (typeof res.then === "function") return await res
  if (isEffectLike(res)) return { error: "EFFECT_NOT_RUN", effect: true, raw: serializeUnknown(res) }
  return res
}

function pickPilotPart(parts, callID) {
  const rev = [...parts].reverse()
  const match = (cid) =>
    rev.find(
      (p) =>
        isPilotRunPart(p, cid) &&
        (p.state?.status === "running" || p.state?.status === "pending"),
    ) || rev.find((p) => isPilotRunPart(p, cid))
  return match(callID) || (callID ? match(undefined) : null)
}

function requestHeaders(client, extra) {
  return { ...headerRecord(clientConfig(client).headers), ...(extra || {}) }
}

function withQuery(url, directory) {
  const dir = String(directory || "").trim()
  if (!dir) return url
  const join = url.includes("?") ? "&" : "?"
  return `${url}${join}directory=${encodeURIComponent(dir)}`
}

export async function findRunningPilotPart(
  client,
  sessionId,
  messageId,
  callID,
  serverUrl,
  log,
  directory,
) {
  if (!sessionId) {
    progressLog("find_miss", { reason: "no_session", messageId, callID }, log)
    return null
  }
  const attempts = []
  const record = (name, fn) => attempts.push({ name, fn })
  const dirQuery = withDirectoryQuery({ limit: 8 }, directory)
  if (client && messageId && typeof client.session?.message === "function") {
    // OpenCode 1.18 v1 SDK: path.id, not sessionID.
    record("session.message.v1", () =>
      client.session.message({
        path: { id: sessionId, messageID: messageId },
        query: withDirectoryQuery(undefined, directory),
      }),
    )
    record("session.message", () =>
      client.session.message({ sessionID: sessionId, messageID: messageId, directory }),
    )
    record("session.message.path", () =>
      client.session.message({
        path: { sessionID: sessionId, messageID: messageId },
        query: withDirectoryQuery(undefined, directory),
      }),
    )
  }
  if (client && typeof client.session?.messages === "function") {
    record("session.messages.v1", () =>
      client.session.messages({ path: { id: sessionId }, query: dirQuery }),
    )
    record("session.messages", () => client.session.messages({ sessionID: sessionId, limit: 8, directory }))
    record("session.messages.path", () =>
      client.session.messages({ path: { id: sessionId }, query: { limit: 8 } }),
    )
  }
  const inner = sdkInner(client)
  if (inner && typeof inner.get === "function" && messageId) {
    record("inner.get.message", () =>
      inner.get({
        url: "/session/{id}/message/{messageID}",
        path: { id: sessionId, messageID: messageId },
        query: withDirectoryQuery(undefined, directory),
      }),
    )
    record("inner.get.message.sessionID", () =>
      inner.get({
        url: "/session/{sessionID}/message/{messageID}",
        path: { sessionID: sessionId, messageID: messageId },
        query: withDirectoryQuery(undefined, directory),
      }),
    )
  }
  const base = clientBaseUrl(client, serverUrl)
  if (base && messageId && !isDummyOpenCodeUrl(base)) {
    record("http.message", async () => {
      const url = withQuery(
        `${base}/session/${encodeURIComponent(sessionId)}/message/${encodeURIComponent(messageId)}`,
        directory,
      )
      const res = await clientFetch(client, url)
      const text = await res.text()
      if (!res.ok) throw new Error(`GET message ${res.status} ${text.slice(0, 200)}`)
      return JSON.parse(text)
    })
  }
  if (base && !isDummyOpenCodeUrl(base)) {
    record("http.messages", async () => {
      const url = withQuery(`${base}/session/${encodeURIComponent(sessionId)}/message?limit=8`, directory)
      const res = await clientFetch(client, url)
      const text = await res.text()
      if (!res.ok) throw new Error(`GET messages ${res.status} ${text.slice(0, 200)}`)
      return JSON.parse(text)
    })
  }

  const errors = []
  for (const attempt of attempts) {
    try {
      const payload = await awaitClientResult(attempt.fn())
      if (payload && payload.error === "EFFECT_NOT_RUN") {
        errors.push({ via: attempt.name, error: "EFFECT_NOT_RUN" })
        continue
      }
      const parts = partsFromMessagePayload(payload)
      const hit = pickPilotPart(parts, callID)
      if (hit) {
        progressLog(
          "find_hit",
          {
            via: attempt.name,
            partId: hit.id,
            status: hit.state?.status,
            sessionID: hit.sessionID || hit.sessionId,
            messageID: hit.messageID || hit.messageId,
            hasRaw: hit.state?.raw !== undefined,
            inputKeys: hit.state?.input ? Object.keys(hit.state.input) : [],
          },
          log,
        )
        return hit
      }
      errors.push({ via: attempt.name, parts: parts.length, error: "no_pilot_run_part" })
    } catch (err) {
      errors.push({ via: attempt.name, error: serializeUnknown(err) })
    }
  }
  progressLog(
    "find_miss",
    { sessionId, messageId, callID, attempts: errors },
    log,
  )
  return null
}

export async function patchRunningToolPart(
  client,
  part,
  title,
  baseInput,
  serverUrl,
  log,
  fallbackIds = {},
  directory,
) {
  const body = buildToolPartProgressPatch(part, title, baseInput, fallbackIds)
  const sessionID = body.sessionID
  const messageID = body.messageID
  const partID = body.id
  if (!partID || !sessionID || !messageID) {
    progressLog(
      "patch_skip",
      { reason: "missing_ids", partID, sessionID, messageID, title: String(title).slice(0, 80) },
      log,
    )
    return { ok: false, error: "missing_ids", body }
  }

  const localCheck = validateOpencodeToolPartPatch({ sessionID, messageID, partID }, body)
  if (!localCheck.ok) {
    progressLog("patch_body_invalid", { error: localCheck.error, body }, log)
    return { ok: false, error: localCheck.error, body }
  }

  const attempts = []
  const jsonHeaders = { "Content-Type": "application/json" }
  const inner = sdkInner(client)
  // OpenCode 1.18 HTTP API is /session/{sessionID}/.../part/{partID}.
  // Use the plugin SDK's inner client (in-process fetch + auth). Global
  // fetch to plugin serverUrl (often localhost:4096) cannot connect.
  if (inner && typeof inner.patch === "function") {
    attempts.push({
      name: "inner.patch.sessionID",
      run: () =>
        inner.patch({
          url: "/session/{sessionID}/message/{messageID}/part/{partID}",
          path: { sessionID, messageID, partID },
          query: withDirectoryQuery(undefined, directory),
          body,
          headers: jsonHeaders,
        }),
    })
    attempts.push({
      name: "inner.patch.v1",
      run: () =>
        inner.patch({
          url: "/session/{id}/message/{messageID}/part/{partID}",
          path: { id: sessionID, messageID, partID },
          query: withDirectoryQuery(undefined, directory),
          body,
          headers: jsonHeaders,
        }),
    })
  }
  if (typeof client?.part?.update === "function") {
    attempts.push({
      name: "client.part.update",
      run: () => client.part.update({ sessionID, messageID, partID, directory, part: body }),
    })
    attempts.push({
      name: "client.part.update.path",
      run: () =>
        client.part.update({
          path: { sessionID, messageID, partID },
          query: withDirectoryQuery(undefined, directory),
          body,
          part: body,
        }),
    })
  }
  if (typeof client?.session?.updatePart === "function") {
    attempts.push({
      name: "client.session.updatePart",
      run: () => client.session.updatePart({ sessionID, messageID, partID, part: body }),
    })
  }
  const base = clientBaseUrl(client, serverUrl)
  if (base && !isDummyOpenCodeUrl(base)) {
    const url = withQuery(
      `${base}/session/${encodeURIComponent(sessionID)}/message/${encodeURIComponent(messageID)}/part/${encodeURIComponent(partID)}`,
      directory,
    )
    attempts.push({
      name: "http.PATCH",
      run: async () => {
        const res = await clientFetch(client, url, {
          method: "PATCH",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(body),
        })
        const text = await res.text()
        let parsed = text
        try {
          parsed = text ? JSON.parse(text) : null
        } catch {
          parsed = text
        }
        if (!res.ok) {
          return { error: parsed || text, status: res.status, response: { status: res.status } }
        }
        return { data: parsed, status: res.status }
      },
    })
  }

  const errors = []
  for (const attempt of attempts) {
    try {
      const res = await awaitClientResult(attempt.run())
      if (!sdkCallOk(res)) {
        errors.push({
          via: attempt.name,
          error: serializeUnknown(res?.error || res),
          status: res?.status || res?.response?.status,
        })
        continue
      }
      progressLog(
        "patch_ok",
        {
          via: attempt.name,
          partID,
          progress: String(title).slice(0, 120),
          inputKeys: Object.keys(body.state.input),
        },
        log,
      )
      return { ok: true, via: attempt.name, body, result: res }
    } catch (err) {
      errors.push({ via: attempt.name, error: serializeUnknown(err) })
    }
  }
  progressLog(
    "patch_fail",
    {
      partID,
      sessionID,
      messageID,
      progress: String(title).slice(0, 80),
      attempts: errors.map((row) => ({
        via: row.via,
        status: row.status,
        error:
          typeof row.error === "string"
            ? row.error.slice(0, 160)
            : row.error?.message || row.error?.name || "error",
      })),
    },
    log,
  )
  return { ok: false, error: "all_attempts_failed", attempts: errors, body }
}

function snapshotBaseInput(part, provided) {
  if (provided && typeof provided === "object") {
    const copy = { ...provided }
    delete copy.progress
    return copy
  }
  const input = part?.state?.input
  if (input && typeof input === "object") {
    const copy = { ...input }
    delete copy.progress
    return copy
  }
  return {}
}

export function createToolRowProgressReporter(opts = {}) {
  const log = opts.log
  let cachedPart = null
  let baseInput = snapshotBaseInput(null, opts.baseInput)
  let closed = false
  let chain = Promise.resolve()
  let lastFindMissAt = 0
  let transportDead = false
  let failCount = 0
  const inner = sdkInner(opts.client)
  progressLog(
    "reporter_start",
    {
      hasPartUpdate: typeof opts.client?.part?.update === "function",
      hasSessionMessage: typeof opts.client?.session?.message === "function",
      hasInnerPatch: typeof inner?.patch === "function",
      baseUrl: clientBaseUrl(opts.client, opts.serverUrl),
      directory: Boolean(opts.directory),
      sessionId: opts.sessionId ? "set" : "",
      messageId: opts.messageId ? "set" : "",
      callID: opts.callID ? "set" : "",
    },
    log,
  )

  async function resolveSessionId() {
    let sid = String(opts.sessionId || "").trim()
    if (sid) return sid
    const client = opts.client
    if (!client?.session?.list) return ""
    try {
      const listed = await awaitClientResult(client.session.list({}) || client.session.list())
      const rows = unwrapSdk(listed)
      const arr = Array.isArray(rows) ? rows : []
      const newest = arr[0]
      sid = String(newest?.id || newest?.sessionID || "").trim()
    } catch (err) {
      progressLog("session_list_fail", { error: serializeUnknown(err) }, log)
    }
    return sid
  }

  async function patchOnce(title) {
    if (closed) return { ok: false, error: "closed" }
    if (transportDead) return { ok: false, error: "transport_dead" }
    const client = opts.client
    if (!client) {
      progressLog("patch_skip", { reason: "no_client", title: String(title).slice(0, 80) }, log)
      return { ok: false, error: "no_client" }
    }
    const sid = await resolveSessionId()
    const messageId = String(opts.messageId || "").trim()
    const callID = String(opts.callID || "").trim()
    if (!sid) {
      progressLog("find_miss", { reason: "no_session_after_list", messageId, callID }, log)
      return { ok: false, error: "no_session" }
    }
    if (!cachedPart) {
      cachedPart = await findRunningPilotPart(
        client,
        sid,
        messageId,
        callID || undefined,
        opts.serverUrl,
        log,
        opts.directory,
      )
      if (!cachedPart) {
        const now = Date.now()
        if (now - lastFindMissAt > 4000) lastFindMissAt = now
        return { ok: false, error: "part_not_found" }
      }
      baseInput = snapshotBaseInput(cachedPart, Object.keys(baseInput).length ? baseInput : null)
    }
    const ids = {
      sessionID: sid,
      messageID: messageId,
      callID,
    }
    const result = await patchRunningToolPart(
      client,
      cachedPart,
      title,
      baseInput,
      opts.serverUrl,
      log,
      ids,
      opts.directory,
    )
    if (result.ok && result.body) {
      failCount = 0
      cachedPart = { ...cachedPart, ...result.body, state: result.body.state }
    } else if (result.error === "all_attempts_failed") {
      failCount += 1
      if (failCount >= 2) transportDead = true
      const statuses = (result.attempts || []).map((a) => a.status)
      if (statuses.includes(404)) cachedPart = null
    }
    return result
  }

  return {
    publish(title) {
      if (closed) return
      const next = String(title || "")
      chain = chain
        .then(() => patchOnce(next))
        .catch((err) => {
          progressLog("patch_queue_error", { error: serializeUnknown(err) }, log)
          return { ok: false, error: String(err) }
        })
    },
    flushAsync() {
      return chain
    },
    close() {
      closed = true
    },
  }
}
