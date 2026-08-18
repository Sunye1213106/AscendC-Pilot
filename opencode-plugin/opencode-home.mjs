/**
 * OpenCode config root + acp.exe resolution.
 *
 * Used by bundle files under ascendc-pilot-plugin/opencode-plugin/.
 * Do not statically import this from plugins/ascendc-pilot.ts — OpenCode
 * autoloads that copy without siblings. Keep a matching copy inlined there.
 */
import { existsSync, readFileSync } from "node:fs"
import { homedir } from "node:os"
import { delimiter, resolve } from "node:path"

export function openCodeHome() {
  const xdg = String(process.env.XDG_CONFIG_HOME || "").trim()
  if (xdg) return resolve(xdg, "opencode")
  return resolve(homedir(), ".config", "opencode")
}

export function resolveAcpBin() {
  const fromEnv = String(process.env.ASCENDC_HARNESS_BIN || "").trim()
  if (fromEnv && existsSync(fromEnv)) return fromEnv
  try {
    const cached = readFileSync(resolve(openCodeHome(), "ascendc-harness-bin"), "utf-8")
      .replace(/^\uFEFF/, "")
      .trim()
    if (cached && existsSync(cached)) return cached
  } catch {
    /* ignore */
  }
  if (process.platform === "win32") {
    const pathEnv = String(process.env.PATH || process.env.Path || "")
    for (const dir of pathEnv.split(delimiter)) {
      if (!dir) continue
      const p = resolve(dir, "acp.exe")
      if (existsSync(p)) return p
    }
  }
  return "acp"
}

export function readCachedCannRoot() {
  try {
    const cached = readFileSync(resolve(openCodeHome(), "ascendc-cann-root"), "utf-8")
      .replace(/^\uFEFF/, "")
      .trim()
    if (cached && existsSync(cached)) return cached
  } catch {
    /* ignore */
  }
  return ""
}
