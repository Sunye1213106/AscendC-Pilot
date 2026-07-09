from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from understand_operator._core.cbm_resolver import resolve_cbm_binary
from understand_operator._operator.artifacts import write_json, write_text


@dataclass
class CbmCall:
    tool: str
    payload: dict[str, Any]
    ok: bool
    output_path: str
    error: str = ""


class OperatorCbmClient:
    def __init__(self, repo_root: Path, artifact_root: Path, config: dict[str, Any]):
        self.repo_root = repo_root
        self.artifact_root = artifact_root
        self.cbm_dir = artifact_root / "cbm"
        self.cbm_dir.mkdir(parents=True, exist_ok=True)
        self.config = config
        self.binary = resolve_cbm_binary(config)
        scanner_cfg = config.get("scanner", {}) if isinstance(config, dict) else {}
        preset_project = scanner_cfg.get("cbm_project")
        self.project_name: str | None = str(preset_project).strip() if preset_project else None
        self.calls: list[CbmCall] = []

    def available(self) -> bool:
        return self.binary is not None

    def with_project(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.project_name and "project" not in payload:
            return {**payload, "project": self.project_name}
        return payload

    def remember_project(self, result: Any) -> None:
        if not isinstance(result, dict):
            return
        for key in ("project", "name"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                self.project_name = value.strip()
                return
        projects = result.get("projects")
        if isinstance(projects, list):
            repo_text = str(self.repo_root).replace("\\", "/").lower()
            for item in projects:
                if not isinstance(item, dict):
                    continue
                root_path = str(item.get("root_path", "")).replace("\\", "/").lower()
                name = item.get("name")
                if isinstance(name, str) and root_path and root_path == repo_text:
                    self.project_name = name
                    return
            if len(projects) == 1 and isinstance(projects[0], dict):
                name = projects[0].get("name")
                if isinstance(name, str) and name.strip():
                    self.project_name = name.strip()

    def call(
        self,
        tool: str,
        payload: dict[str, Any] | None = None,
        *,
        output_name: str | None = None,
        persist: bool = True,
    ) -> dict[str, Any]:
        payload = payload or {}
        output_name = output_name or f"{len(self.calls) + 1:02d}_{tool}.json"
        output_path = self.cbm_dir / output_name
        if not self.binary:
            data = {"ok": False, "tool": tool, "error": "codebase-memory-mcp binary not found"}
            if persist:
                write_json(output_path, data)
            self.calls.append(CbmCall(tool, payload, False, "(stdout)" if not persist else output_path.name, data["error"]))
            return data

        env = os.environ.copy()
        env.setdefault("CBM_CACHE_DIR", str(self.cbm_dir / "cache"))
        Path(env["CBM_CACHE_DIR"]).mkdir(parents=True, exist_ok=True)

        attempted_tools = [tool]
        if tool == "trace_path":
            attempted_tools.append("trace_call_path")

        last_error = ""
        for actual_tool in attempted_tools:
            cmd = [str(self.binary), "cli", "--json", actual_tool, json.dumps(self.with_project(payload), ensure_ascii=False)]
            result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
            if result.returncode == 0:
                parsed = self._parse_stdout(result.stdout)
                semantic_error = self._semantic_error(parsed)
                data = {
                    "ok": semantic_error is None,
                    "requested_tool": tool,
                    "actual_tool": actual_tool,
                    "payload": payload,
                    "result": parsed,
                }
                if semantic_error:
                    data["error"] = semantic_error
                if persist:
                    write_json(output_path, data)
                self.remember_project(parsed)
                sink = output_path.name if persist else "(stdout)"
                self.calls.append(CbmCall(tool, payload, semantic_error is None, sink, semantic_error or ""))
                return data
            last_error = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"

        data = {
            "ok": False,
            "requested_tool": tool,
            "payload": payload,
            "error": last_error,
        }
        if persist:
            write_json(output_path, data)
        self.calls.append(CbmCall(tool, payload, False, "(stdout)" if not persist else output_path.name, last_error))
        return data

    def write_log(self) -> None:
        lines = [
            "# CBM Query Log",
            "",
            f"- generated_at: {datetime.now(tz=timezone.utc).isoformat()}",
            f"- repo_root: {self.repo_root}",
            f"- cbm_binary: {self.binary or 'not found'}",
            f"- cbm_project: {self.project_name or 'not resolved'}",
            "",
            "Runtime queries use `cbm_query.py` (stdout + optional `cbm/query_journal.jsonl`).",
            "",
            "| # | Tool | Output | Status | Notes |",
            "|---|---|---|---|---|",
        ]
        for idx, call in enumerate(self.calls, start=1):
            status = "ok" if call.ok else "failed"
            error = call.error.replace("|", "\\|")[:180]
            lines.append(f"| {idx} | `{call.tool}` | `{call.output_path}` | {status} | {error} |")
        write_text(self.cbm_dir / "cbm_query_log.md", "\n".join(lines) + "\n")

    @staticmethod
    def _parse_stdout(stdout: str) -> Any:
        try:
            envelope = json.loads(stdout)
        except json.JSONDecodeError:
            return {"text": stdout}
        if isinstance(envelope, dict):
            content = envelope.get("content")
            if isinstance(content, list) and content:
                text = content[0].get("text") if isinstance(content[0], dict) else None
                if isinstance(text, str):
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        return {"text": text}
        return envelope

    @staticmethod
    def _semantic_error(parsed: Any) -> str | None:
        if not isinstance(parsed, dict):
            return None
        error = parsed.get("error")
        if isinstance(error, str) and error.strip():
            hint = parsed.get("hint")
            if isinstance(hint, str) and hint.strip():
                return f"{error} ({hint})"
            return error
        text = parsed.get("text")
        if isinstance(text, str) and text.strip().endswith("required"):
            return text.strip()
        return None


def load_index_meta(artifact_root: Path) -> dict[str, Any]:
    path = artifact_root / "cbm" / "index_meta.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def write_index_meta(artifact_root: Path, data: dict[str, Any]) -> None:
    write_json(artifact_root / "cbm" / "index_meta.json", data)


def summarize_result(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {"kind": type(result).__name__}
    summary: dict[str, Any] = {}
    for key in ("count", "total", "matches", "nodes", "edges", "functions", "files"):
        if key in result:
            summary[key] = result[key]
    for key in ("results", "matches", "nodes", "items", "functions", "files", "paths"):
        value = result.get(key)
        if isinstance(value, list):
            summary[f"{key}_count"] = len(value)
    if not summary and result.get("text"):
        text = str(result["text"])
        summary["text_preview"] = text[:200]
    return summary


def append_query_journal(
    artifact_root: Path,
    *,
    tool: str,
    payload: dict[str, Any],
    ok: bool,
    phase: str,
    error: str,
    result: Any,
    saved_to: str | None = None,
) -> None:
    journal = artifact_root / "cbm" / "query_journal.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "at": datetime.now(tz=timezone.utc).isoformat(),
        "tool": tool,
        "phase": phase,
        "payload": payload,
        "ok": ok,
        "error": error,
        "summary": summarize_result(result),
        "saved_to": saved_to,
    }
    with journal.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def run_operator_cbm_prefetch(
    repo_root: Path,
    artifact_root: Path,
    config: dict[str, Any],
    *,
    op_name: str,
    full: bool,
    prefetch_queries: bool = False,
) -> list[CbmCall]:
    """Phase 0: index only by default. Bulk search_graph/search_code files are opt-in."""
    client = OperatorCbmClient(repo_root, artifact_root, config)
    list_result = client.call("list_projects", {}, persist=False)
    client.remember_project(list_result.get("result"))

    index_summary: dict[str, Any] = {}
    if full:
        mode = str(config.get("scanner", {}).get("cbm_mode") or "fast")
        index_result = client.call(
            "index_repository",
            {"repo_path": str(repo_root), "mode": mode},
            persist=False,
        )
        client.remember_project(index_result.get("result"))
        index_summary["index_repository"] = summarize_result(index_result.get("result"))
        status_result = client.call(
            "index_status",
            client.with_project({}) if client.project_name else {"repo_path": str(repo_root)},
            persist=False,
        )
        index_summary["index_status"] = summarize_result(status_result.get("result"))
    else:
        status_result = client.call("index_status", {"repo_path": str(repo_root)}, persist=False)
        client.remember_project(status_result.get("result"))
        index_summary["index_status"] = summarize_result(status_result.get("result"))
        if not client.project_name:
            refresh = client.call("list_projects", {}, persist=False)
            client.remember_project(refresh.get("result"))

    write_index_meta(
        artifact_root,
        {
            "repo_root": str(repo_root),
            "op_name": op_name,
            "cbm_project": client.project_name,
            "cbm_binary": str(client.binary) if client.binary else None,
            "indexed_at": datetime.now(tz=timezone.utc).isoformat(),
            "prefetch_mode": "full_queries" if prefetch_queries else "index_only",
            "index_summary": index_summary,
        },
    )

    if prefetch_queries:
        if client.project_name:
            client.call("get_graph_schema", client.with_project({}), output_name="04_graph_schema.json")
            client.call("get_architecture", client.with_project({}), output_name="05_architecture.json")
        else:
            client.call("get_graph_schema", {}, output_name="04_graph_schema.json")
            client.call("get_architecture", {"repo_path": str(repo_root)}, output_name="05_architecture.json")

        graph_patterns = [_graph_pattern(op_name), ".*Tiling.*", ".*Kernel.*", ".*Host.*"]
        for idx, pattern in enumerate(graph_patterns, start=1):
            if pattern and pattern != "unknown":
                client.call(
                    "search_graph",
                    client.with_project({"name_pattern": pattern}),
                    output_name=f"10_search_graph_{idx:02d}.json",
                )

        keywords = [
            "tiling",
            "tiling key",
            "tiling data",
            "kernel",
            "host",
            "op proto",
            "golden",
            "test",
            "DataCopy",
            "SetFlag",
            "WaitFlag",
            "Sync",
            "PIPE_MTE",
            "fixpipe",
        ]
        for idx, keyword in enumerate(keywords, start=1):
            client.call(
                "search_code",
                client.with_project({"pattern": keyword}),
                output_name=f"20_search_code_{idx:02d}_{_slug(keyword)}.json",
            )

        client.call("detect_changes", {"repo_path": str(repo_root)}, output_name="30_detect_changes.json")

    client.write_log()
    return client.calls


def _graph_pattern(op_name: str) -> str:
    if any(ch in op_name for ch in ".*+?[](){}|^$\\"):
        return op_name
    return f".*{op_name}.*"


def _slug(text: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in text).strip("_") or "query"
