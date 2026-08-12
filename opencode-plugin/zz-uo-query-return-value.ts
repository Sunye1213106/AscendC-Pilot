/**
 * uo-query return_value handoff for OpenCode.
 *
 * The main AscendC plugin owns authorization, Task correlation, debug export,
 * and workflow control. This narrow hook only transports the finished
 * uo-query Task result into the Primary's next normal
 * `acp run-action kb_lookup --finalize` invocation.
 *
 * No temporary result file is written and this hook never finalizes by itself,
 * avoiding a double-finalize race with the Primary runtime loop.
 */

import { existsSync, readFileSync } from "node:fs"
import { homedir } from "node:os"
import { resolve } from "node:path"

const pendingByProject = new Map<string, string>()

function lastProject(): string {
  const cache = resolve(homedir(), ".config", "opencode", "ascendc-last-project")
  if (existsSync(cache)) {
    try {
      const p = readFileSync(cache, "utf8").trim()
      if (p) return p
    } catch {
      // fall through
    }
  }
  return ""
}

function taskText(output: Record<string, unknown> | undefined): string {
  if (!output) return ""
  const chunks: string[] = []
  for (const key of ["output", "content", "message", "text", "result"] as const) {
    const value = output[key]
    if (typeof value === "string" && value.trim()) chunks.push(value)
  }
  return chunks.join("\n").slice(0, 24000)
}

function isKbAnswer(text: string): boolean {
  return /\bschema\s*:\s*["']?kb-answer-v1\b/i.test(String(text || ""))
}

function pickProject(args: Record<string, unknown>, command = ""): string {
  const env =
    args.env && typeof args.env === "object"
      ? (args.env as Record<string, unknown>)
      : args.environment && typeof args.environment === "object"
        ? (args.environment as Record<string, unknown>)
        : {}
  const explicit = String(
    env.ASCENDC_PROJECT_ROOT ||
      args.project ||
      args.project_root ||
      args.cwd ||
      args.workdir ||
      "",
  ).trim()
  if (explicit) return resolve(explicit)

  const blob = `${command}\n${String(args.prompt || args.description || args.task || "")}`
  const projectFlag = blob.match(/--project\s+["']?([^\s"'`]+)/i)?.[1]
  if (projectFlag) return resolve(projectFlag)
  const cached = lastProject()
  return cached ? resolve(cached) : ""
}

function isUoQueryTask(args: Record<string, unknown>): boolean {
  const actor = String(
    args.agent || args.subagent || args.subagent_type || args.subagentType || args.name || "",
  ).toLowerCase()
  const action = String(args.action || args.action_id || args.actionId || "").toLowerCase()
  return actor === "uo-query" || action === "kb_lookup"
}

function isKbLookupFinalize(command: string): boolean {
  const text = String(command || "")
  return /\bacp\s+run-action\s+kb_lookup\b/i.test(text) && /--finalize\b/i.test(text)
}

function injectResult(args: Record<string, unknown>, project: string, resultText: string): void {
  const existing =
    args.env && typeof args.env === "object"
      ? ({ ...(args.env as Record<string, unknown>) } as Record<string, unknown>)
      : args.environment && typeof args.environment === "object"
        ? ({ ...(args.environment as Record<string, unknown>) } as Record<string, unknown>)
        : ({} as Record<string, unknown>)
  existing.ASCENDC_ACTION_RESULT = resultText
  existing.ASCENDC_ACTION_RESULT_PROJECT = project
  existing.ASCENDC_ACTION_RESULT_ACTION = "kb_lookup"
  args.env = existing

  // Compatibility fallback for Hosts that spawn bash from the plugin process
  // environment instead of honoring a tool-local env bag.
  process.env.ASCENDC_ACTION_RESULT = resultText
  process.env.ASCENDC_ACTION_RESULT_PROJECT = project
  process.env.ASCENDC_ACTION_RESULT_ACTION = "kb_lookup"
}

function clearResult(project: string): void {
  if (project) pendingByProject.delete(resolve(project))
  delete process.env.ASCENDC_ACTION_RESULT
  delete process.env.ASCENDC_ACTION_RESULT_PROJECT
  delete process.env.ASCENDC_ACTION_RESULT_ACTION
}

export const UoQueryReturnValuePlugin = async () => {
  return {
    "tool.execute.before": async (
      input: { tool?: string },
      output: { args?: Record<string, unknown> },
    ) => {
      const tool = String(input.tool || "").toLowerCase()
      if (tool !== "bash" && tool !== "shell" && tool !== "terminal") return
      const args = output.args || {}
      const command = String(args.command || args.cmd || "")
      if (!isKbLookupFinalize(command)) return
      const project = pickProject(args, command)
      if (!project) return
      const resultText = pendingByProject.get(project)
      if (!resultText) return
      injectResult(args, project, resultText)
    },

    "tool.execute.after": async (
      input: { tool?: string },
      output: Record<string, unknown> | undefined,
    ) => {
      const tool = String(input.tool || "").toLowerCase()
      const args = (output && typeof output.args === "object" ? output.args : {}) as Record<
        string,
        unknown
      >

      if (tool === "task" || tool === "subagent" || tool === "task_tool") {
        if (!isUoQueryTask(args)) return
        const text = taskText(output)
        if (!isKbAnswer(text)) return
        const project = pickProject(args)
        if (!project) return
        pendingByProject.set(project, text)
        if (output) {
          const oldMeta =
            output.metadata && typeof output.metadata === "object"
              ? (output.metadata as Record<string, unknown>)
              : {}
          output.metadata = {
            ...oldMeta,
            ascendc_uo_query_return_value: {
              captured: true,
              transport: "next_primary_finalize",
              project,
            },
          }
        }
        return
      }

      if (tool === "bash" || tool === "shell" || tool === "terminal") {
        const command = String(args.command || args.cmd || "")
        if (!isKbLookupFinalize(command)) return
        const project = pickProject(args, command)
        clearResult(project)
      }
    },
  }
}

export default UoQueryReturnValuePlugin
