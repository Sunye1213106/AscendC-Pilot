/**
 * AscendC Harness OpenCode plugin.
 *
 * Install: copy this file to ~/.config/opencode/plugins/ascendc-harness.ts
 * Does NOT merge or rewrite the user's opencode.json.
 *
 * Intercepts bash/write before execution and asks `harness authorize`.
 * Soft control plane only — not OS-level security.
 */

import { spawnSync } from "node:child_process"

type AuthorizeResult = {
  ok?: boolean
  decision?: string
  reason_zh?: string
  reason_code?: string
}

function runAuthorize(args: {
  tool: string
  command?: string
  path?: string
  agent?: string
}): AuthorizeResult {
  const argv = [
    "authorize",
    "--tool",
    args.tool,
    "--command",
    args.command ?? "",
    "--path",
    args.path ?? "",
    "--agent",
    args.agent ?? "ascendc-agent",
  ]
  const result = spawnSync("harness", argv, {
    encoding: "utf-8",
    shell: true,
    windowsHide: true,
  })
  if (result.error || result.status === 127) {
    // harness not on PATH — fail closed for bash domain CLIs only
    return { ok: false, decision: "ask", reason_code: "HARNESS_MISSING", reason_zh: "未找到 harness CLI" }
  }
  try {
    const text = (result.stdout || "").trim()
    const jsonStart = text.indexOf("{")
    if (jsonStart < 0) {
      return { ok: result.status === 0, decision: result.status === 0 ? "allow" : "deny" }
    }
    return JSON.parse(text.slice(jsonStart)) as AuthorizeResult
  } catch {
    return { ok: false, decision: "deny", reason_code: "AUTHORIZE_PARSE", reason_zh: "authorize 输出无法解析" }
  }
}

export const AscendCHarnessPlugin = async () => {
  return {
    "tool.execute.before": async (
      input: { tool?: string; agent?: string },
      output: { args?: Record<string, unknown> },
    ) => {
      const tool = String(input.tool || "")
      const args = output.args || {}
      const command = String(args.command || args.cmd || "")
      const path = String(args.filePath || args.path || args.file || "")

      if (tool === "bash" || tool === "shell") {
        const verdict = runAuthorize({ tool: "bash", command, agent: "ascendc-agent" })
        if (verdict.decision === "deny" || (verdict.ok === false && verdict.decision !== "ask")) {
          throw new Error(
            `[ascendc-harness] blocked bash: ${verdict.reason_zh || verdict.reason_code || "denied"}`,
          )
        }
        if (verdict.decision === "ask") {
          // Soft block for primary: require harness-only by default
          if (!/^\s*harness(\s|$)/i.test(command)) {
            throw new Error(
              `[ascendc-harness] bash 仅允许 harness *：${verdict.reason_zh || ""}`.trim(),
            )
          }
        }
      }

      if (tool === "write" || tool === "edit") {
        const verdict = runAuthorize({ tool: "write", path, agent: "ascendc-agent" })
        if (verdict.decision === "deny" || verdict.ok === false) {
          throw new Error(
            `[ascendc-harness] blocked write: ${verdict.reason_zh || path}`,
          )
        }
      }
    },
  }
}

export default AscendCHarnessPlugin
