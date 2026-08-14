/**
 * Prove OpenCode GenericTool progress PATCH against a 1.18-shaped validator.
 * Run: node opencode-plugin/pilot-progress.test.mjs
 */
import { createServer } from "node:http"
import {
  buildToolPartProgressPatch,
  clientBaseUrl,
  createToolRowProgressReporter,
  genericToolInputLabel,
  partsFromMessagePayload,
  sdkCallOk,
  validateOpencodeToolPartPatch,
  withProgressArg,
} from "./pilot-progress.mjs"

function assert(cond, msg) {
  if (!cond) throw new Error(msg || "assertion failed")
}

const IDS = { sessionID: "ses_1", messageID: "msg_1", partID: "prt_1" }

function pendingPilotPart() {
  return {
    id: IDS.partID,
    sessionID: IDS.sessionID,
    messageID: IDS.messageID,
    type: "tool",
    callID: "call_1",
    tool: "pilot_run",
    extraGarbage: true,
    state: {
      status: "pending",
      input: {
        workflow: "uo-init",
        project: "d:/op",
        architecture: "arch35",
        intent: "建库",
        force_new: false,
      },
      raw: '{"workflow":"uo-init"}',
    },
  }
}

function oldSpreadBody(part, title) {
  return {
    ...part,
    state: {
      ...(part.state || {}),
      status: "running",
      title,
      metadata: { progress: title },
      input: withProgressArg(part.state.input, title),
    },
  }
}

async function testCleanBodyVsOldSpread() {
  const part = pendingPilotPart()
  const title = "uo-init  [██░░░░░░░░] 2/5  extract  1:12"
  const clean = buildToolPartProgressPatch(part, title, part.state.input, IDS)
  const old = oldSpreadBody(part, title)
  const cleanOk = validateOpencodeToolPartPatch(IDS, clean)
  const oldOk = validateOpencodeToolPartPatch(IDS, old)
  assert(cleanOk.ok, `clean body should PATCH: ${JSON.stringify(cleanOk)}`)
  assert(!oldOk.ok, "old spread body must 400")
  assert(oldOk.error.includes("raw") || oldOk.error.includes("time"), oldOk.error)
  const label = genericToolInputLabel(clean.state.input)
  assert(label.startsWith("[progress=uo-init"), `GenericTool label: ${label}`)
  assert(label.includes("workflow=uo-init"), label)
  assert(Object.keys(clean.state.input)[0] === "progress", "progress must be first key")
}

async function testEnvelopeUnwrap() {
  const part = pendingPilotPart()
  const wrapped = { data: { info: { id: IDS.messageID, role: "assistant" }, parts: [part] } }
  const parts = partsFromMessagePayload(wrapped)
  assert(parts.length === 1 && parts[0].id === IDS.partID, `unwrap parts=${parts.length}`)
  const listed = { data: [{ info: { id: "x" }, parts: [part] }] }
  assert(partsFromMessagePayload(listed)[0].id === IDS.partID, "messages list unwrap")
}

async function testEffectNotSuccess() {
  const effect = { pipe() {}, _op: "succeed" }
  assert(sdkCallOk(effect) === false, "un-run Effect must not count as PATCH ok")
}

function testClientBaseUrl() {
  const url = new URL("http://127.0.0.1:4096/")
  assert(clientBaseUrl({}, url) === "http://127.0.0.1:4096", clientBaseUrl({}, url))
  const client = {
    _client: { getConfig: () => ({ baseUrl: "http://127.0.0.1:4096/" }) },
  }
  assert(clientBaseUrl(client) === "http://127.0.0.1:4096", clientBaseUrl(client))
}

function mockClient(part, { failFirst = false } = {}) {
  let stored = part
  const logs = []
  return {
    stored: () => stored,
    session: {
      message: async () => ({ data: { info: { id: IDS.messageID }, parts: [stored] } }),
    },
    part: {
      update: async (args) => {
        const body = args.part || args.body
        if (failFirst) {
          failFirst = false
          return { error: { message: "first shape rejected" }, response: { status: 400 } }
        }
        const check = validateOpencodeToolPartPatch(
          {
            sessionID: args.sessionID || args.path?.sessionID,
            messageID: args.messageID || args.path?.messageID,
            partID: args.partID || args.path?.partID,
          },
          body,
        )
        if (!check.ok) return { error: check, response: { status: 400 } }
        stored = body
        logs.push(body)
        return { data: body }
      },
    },
    logs,
  }
}

async function testReporterPatchesInput() {
  const part = pendingPilotPart()
  const client = mockClient(part)
  const events = []
  const metadataCalls = []
  const row = createToolRowProgressReporter({
    client,
    sessionId: IDS.sessionID,
    messageId: IDS.messageID,
    callID: "call_1",
    baseInput: part.state.input,
    log: (rec) => events.push(rec),
  })
  const title = "uo-init  [██░░░░░░░░] 2/5  extract  1:12"
  row.publish(title)
  const result = await row.flushAsync()
  row.close()
  assert(result && result.ok, `patch result ${JSON.stringify(result)}`)
  const stored = client.stored()
  assert(stored.state.input.progress === title, `stored progress=${stored.state.input.progress}`)
  assert(stored.state.raw === undefined, "running state must drop pending raw")
  assert(typeof stored.state.time?.start === "number", "time.start required")
  assert(
    genericToolInputLabel(stored.state.input).startsWith("[progress=uo-init"),
    genericToolInputLabel(stored.state.input),
  )
  assert(
    events.some((e) => e.event === "find_hit"),
    `missing find_hit: ${events.map((e) => e.event).join(",")}`,
  )
  assert(
    events.some((e) => e.event === "patch_ok"),
    `missing patch_ok: ${JSON.stringify(events)}`,
  )
  assert(metadataCalls.length === 0, "must not call ctx.metadata")
}

async function testHttpPatchServer() {
  const part = pendingPilotPart()
  let stored = part
  const server = createServer((req, res) => {
    const url = new URL(req.url || "/", "http://127.0.0.1")
    const send = (status, body) => {
      res.writeHead(status, { "content-type": "application/json" })
      res.end(JSON.stringify(body))
    }
    if (req.method === "GET" && url.pathname.endsWith(`/message/${IDS.messageID}`)) {
      send(200, { info: { id: IDS.messageID }, parts: [stored] })
      return
    }
    const partMatch = url.pathname.match(
      /\/session\/([^/]+)\/message\/([^/]+)\/part\/([^/]+)$/,
    )
    if (req.method === "PATCH" && partMatch) {
      const chunks = []
      req.on("data", (c) => chunks.push(c))
      req.on("end", () => {
        const body = JSON.parse(Buffer.concat(chunks).toString("utf-8") || "{}")
        const check = validateOpencodeToolPartPatch(
          { sessionID: partMatch[1], messageID: partMatch[2], partID: partMatch[3] },
          body,
        )
        if (!check.ok) {
          send(400, check)
          return
        }
        stored = body
        send(200, body)
      })
      return
    }
    send(404, { error: "not found", path: url.pathname })
  })
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve))
  const { port } = server.address()
  try {
    const events = []
    const row = createToolRowProgressReporter({
      client: { session: {} },
      sessionId: IDS.sessionID,
      messageId: IDS.messageID,
      callID: "call_1",
      serverUrl: `http://127.0.0.1:${port}`,
      baseInput: part.state.input,
      log: (rec) => events.push(rec),
    })
    const title = "uo-init  [████░░░░░░] 3/5  analyze  8s"
    row.publish(title)
    const result = await row.flushAsync()
    row.close()
    assert(result && result.ok, `http patch ${JSON.stringify(result)} ${JSON.stringify(events)}`)
    assert(stored.state.input.progress === title, `http stored=${stored.state.input.progress}`)
    assert(events.some((e) => e.event === "patch_ok" && e.via === "http.PATCH"), JSON.stringify(events))
  } finally {
    await new Promise((resolve) => server.close(resolve))
  }
}

async function testV1SdkUsesPathIdAndInnerPatch() {
  const part = pendingPilotPart()
  let stored = part
  let sawV1Path = false
  const events = []
  const client = {
    session: {
      message: async (opts) => {
        if (opts?.path?.id === IDS.sessionID && opts?.path?.messageID === IDS.messageID) {
          sawV1Path = true
          return { info: { id: IDS.messageID }, parts: [stored] }
        }
        throw new Error("v1 client rejects sessionID-shaped args")
      },
    },
    _client: {
      getConfig: () => ({
        baseUrl: "http://127.0.0.1:9",
        headers: { authorization: "Basic dGVzdA==" },
      }),
      patch: async (opts) => {
        const ids = {
          sessionID: opts.path?.id || opts.path?.sessionID,
          messageID: opts.path?.messageID,
          partID: opts.path?.partID,
        }
        const check = validateOpencodeToolPartPatch(
          { sessionID: ids.sessionID, messageID: ids.messageID, partID: ids.partID },
          opts.body,
        )
        if (!check.ok) return { error: check, response: { status: 400 } }
        stored = opts.body
        return { data: opts.body }
      },
    },
  }
  const row = createToolRowProgressReporter({
    client,
    sessionId: IDS.sessionID,
    messageId: IDS.messageID,
    callID: "call_1",
    baseInput: part.state.input,
    log: (rec) => events.push(rec),
  })
  const title = "uo-init  [██░░░░░░░░] 2/5  extract  1:12"
  row.publish(title)
  const result = await row.flushAsync()
  row.close()
  assert(sawV1Path, "must call session.message with path.id")
  assert(result && result.ok, `v1 patch ${JSON.stringify(result)} ${JSON.stringify(events)}`)
  assert(result.via === "inner.patch.sessionID", `via=${result.via} ${JSON.stringify(events)}`)
  assert(stored.state.input.progress === title, `stored=${stored.state.input.progress}`)
  assert(
    events.some((e) => e.event === "patch_ok" && e.via === "inner.patch.sessionID"),
    JSON.stringify(events),
  )
}

async function main() {
  await testCleanBodyVsOldSpread()
  await testEnvelopeUnwrap()
  await testEffectNotSuccess()
  testClientBaseUrl()
  await testReporterPatchesInput()
  await testHttpPatchServer()
  await testV1SdkUsesPathIdAndInnerPatch()
  console.log("pilot-progress.mjs contract OK")
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
