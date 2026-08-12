/**
 * Pure Host-context helpers for AscendC Pilot OpenCode adapter.
 *
 * Keep this module free of OpenCode plugin APIs so Node contract tests can
 * execute the resolver without starting OpenCode or an LLM.
 *
 * Algorithm must stay aligned with `ascendc-pilot.ts` (findPilotStateFile /
 * parseHostContext / readActiveActionFromContext).
 */
import {
  existsSync,
  readFileSync,
  readdirSync,
} from "node:fs"
import { spawnSync } from "node:child_process"
import { resolve } from "node:path"

/** Prefer control/active_run.yaml, then sole arch state, then legacy flat. */
export function findPilotStateFile(root) {
  const r = String(root || "").trim()
  if (!r) return ""
  const pilot = resolve(r, ".ascendc-pilot")
  if (!existsSync(pilot)) return ""

  // Durable active-run pointer (arch-neutral SSOT written by ACP).
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

  const flat = resolve(pilot, "state", "workflow.yaml")
  if (existsSync(flat)) return flat

  try {
    const hits = []
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

export function parseHostContextText(text, root = "") {
  const body = String(text || "").trim()
  const jsonStart = body.indexOf("{")
  if (jsonStart < 0) {
    return { ok: false, error: "host_context_parse_failed", project_root: root || undefined }
  }
  try {
    return JSON.parse(body.slice(jsonStart))
  } catch {
    return { ok: false, error: "host_context_json_invalid", project_root: root || undefined }
  }
}

export function readActiveActionFromContext(ctx) {
  return {
    action_id: String(ctx.action_id || "").trim(),
    actor_id: String(ctx.actor_id || "").trim(),
    // Never fall back to workflow status (`running`) — that defeats finalized skip.
    status: String(ctx.active_action_status || "").trim(),
  }
}

/**
 * Call `acp host-context` via an injectable spawn (tests pass a fake acp).
 */
export function fetchHostContextWithBin(project, acpBin, spawnImpl = spawnSync) {
  const root = String(project || "").trim()
  if (!root) return { ok: false, error: "missing_project" }
  if (!acpBin) {
    return { ok: false, error: "HARNESS_MISSING", project_root: root }
  }
  const res = spawnImpl(acpBin, ["host-context", "--project", root], {
    encoding: "utf-8",
    shell: false,
    windowsHide: true,
    cwd: root,
    env: { ...process.env, ASCENDC_PROJECT_ROOT: root },
    timeout: 15_000,
  })
  const text = `${res.stdout || ""}\n${res.stderr || ""}`.trim()
  if (!text && (res.error || res.status === 127)) {
    return { ok: false, error: "HARNESS_MISSING", project_root: root }
  }
  return parseHostContextText(text, root)
}
