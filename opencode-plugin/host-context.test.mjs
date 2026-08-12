/**
 * Executable Host-context contract test (no OpenCode, no LLM).
 * Run: node opencode-plugin/host-context.test.mjs
 */
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join, resolve } from "node:path"
import { spawnSync } from "node:child_process"
import {
  fetchHostContextWithBin,
  findPilotStateFile,
  parseHostContextText,
  readActiveActionFromContext,
} from "./host-context.mjs"

function assert(cond, msg) {
  if (!cond) throw new Error(msg || "assertion failed")
}

function writeFakeAcp(dir, payload) {
  const script = join(dir, "fake-acp.mjs")
  writeFileSync(
    script,
    `process.stdout.write(${JSON.stringify(JSON.stringify(payload))} + "\\n");\n`,
    "utf-8",
  )
  return script
}

function spawnFakeAcp(bin, _argv, opts) {
  // bin is the Node script; ignore acp argv — contract only needs JSON stdout.
  return spawnSync(process.execPath, [bin], opts)
}

function main() {
  const root = mkdtempSync(join(tmpdir(), "acp-host-ctx-"))
  try {
    const pilot = join(root, ".ascendc-pilot")
    mkdirSync(join(pilot, "arch22", "state"), { recursive: true })
    mkdirSync(join(pilot, "arch35", "state"), { recursive: true })
    mkdirSync(join(pilot, "control"), { recursive: true })
    writeFileSync(join(pilot, "arch22", "state", "workflow.yaml"), "workflow_id: old\n", "utf-8")
    writeFileSync(join(pilot, "arch35", "state", "workflow.yaml"), "workflow_id: cur\n", "utf-8")
    writeFileSync(
      join(pilot, "control", "active_run.yaml"),
      "schema: pilot-active-run/v1\narchitecture: arch35\nrun_id: RUN_X\n",
      "utf-8",
    )

    const stateFile = findPilotStateFile(root)
    const norm = stateFile.replace(/\\/g, "/")
    assert(norm.includes("arch35/state/workflow.yaml"), `expected arch35 state, got ${stateFile}`)

    const parsed = parseHostContextText(
      'noise\n{"ok":true,"architecture":"arch35","action_id":"prepare","actor_id":"deterministic-uo-engine"}\n',
      root,
    )
    assert(parsed.ok === true, "parse ok")
    assert(parsed.architecture === "arch35", "arch")
    const active = readActiveActionFromContext(parsed)
    assert(active.action_id === "prepare", "action_id")
    assert(active.actor_id === "deterministic-uo-engine", "actor_id")

    const payload = {
      ok: true,
      architecture: "arch35",
      action_id: "prepare",
      actor_id: "deterministic-uo-engine",
      active_action_path: resolve(pilot, "arch35", "state", "active_action.yaml"),
      active_run_path: resolve(pilot, "control", "active_run.yaml"),
    }
    const fake = writeFakeAcp(root, payload)
    const ctx = fetchHostContextWithBin(root, fake, spawnFakeAcp)
    assert(ctx.ok === true, `fake acp ok: ${JSON.stringify(ctx)}`)
    assert(ctx.architecture === "arch35", "fake arch")
    assert(readActiveActionFromContext(ctx).action_id === "prepare", "fake action")

    const missing = fetchHostContextWithBin(root, "", spawnFakeAcp)
    assert(missing.error === "HARNESS_MISSING", "missing harness")

    console.log("host-context.mjs contract OK")
  } finally {
    try {
      rmSync(root, { recursive: true, force: true })
    } catch {
      // ignore
    }
  }
}

main()
