import assert from "node:assert/strict"
import { mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { resolve } from "node:path"
import { pathToFileURL } from "node:url"

const tmp = mkdtempSync(resolve(tmpdir(), "ascendc-dispatch-registry-"))
process.env.XDG_CONFIG_HOME = tmp

try {
  const modulePath = resolve(process.cwd(), "opencode-plugin", "dispatch-registry.ts")
  const registry = await import(pathToFileURL(modulePath).href)
  const opencodeHome = resolve(tmp, "opencode")

  registry.rememberDispatchRecord({
    project: "/tmp/operator",
    ticket: "ticket-A",
    actor: "ce-reviewer",
    action: "code_review",
    sessionId: "ses_A",
    workflow: "ce-review",
    ts: 1,
  })
  registry.rememberDispatchRecord({
    project: "/tmp/operator",
    ticket: "ticket-B",
    actor: "ce-reviewer",
    action: "code_review",
    sessionId: "ses_B",
    workflow: "ce-review",
    ts: 2,
  })

  assert.equal(registry.readDispatchFor("/tmp/operator", "ses_A")?.ticket, "ticket-A")
  assert.equal(registry.readDispatchFor("/tmp/operator", "ses_B")?.ticket, "ticket-B")
  assert.equal(registry.readDispatchFor("/tmp/operator", ""), null)

  writeFileSync(resolve(opencodeHome, "ascendc-last-project.session"), "ses_A", "utf8")
  assert.equal(registry.readDispatchFor("/tmp/operator")?.ticket, "ticket-A")

  registry.recordDispatchFailure({
    project: "/tmp/operator",
    ticket: "ticket-A",
    sessionId: "ses_A",
    workflow: "ce-review",
    error: "synthetic ack failure",
  })
  const notice = registry.consumeTransportNotice("ses_A")
  assert.equal(notice?.reason_code, "HOST_DISPATCH_ACK_FAILED")
  assert.equal(notice?.ticket, "ticket-A")
  assert.equal(registry.consumeTransportNotice("ses_A"), null)

  registry.removeDispatchRecord("/tmp/operator", "ses_A", "ticket-A")
  assert.equal(registry.readDispatchFor("/tmp/operator", "ses_A"), null)
  assert.equal(registry.readDispatchFor("/tmp/operator", "ses_B")?.ticket, "ticket-B")
} finally {
  rmSync(tmp, { recursive: true, force: true })
}
