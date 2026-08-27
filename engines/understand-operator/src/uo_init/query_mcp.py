# -*- coding: utf-8 -*-
"""Stdio MCP server for uo-query.

One tool, four agent shapes: index / identifier / Dim=V|Name=Value / file+line.
Long-lived MCP holds an in-process ``UoSqlQuery``. One-shot CLI still uses the
query daemon. Set ``UO_QUERY_MCP_DAEMON=1`` to force a daemon hop for benches.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

PROTOCOL = "2024-11-05"
SERVER_NAME = "ascendc-pilot"
SERVER_VERSION = "1.0.0"
_CACHE: dict[str, Any] = {}
_DEBUG = Path(r"D:\PR-review\AscendC-Pilot\cursor-plugin\mcp-debug.jsonl")


def _debug(row: dict[str, Any]) -> None:
    try:
        with _DEBUG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass


def _qid() -> str:
    path = str(os.environ.get("UO_QUERY_EVAL_QID_FILE") or "").strip()
    if path:
        try:
            text = Path(path).read_text(encoding="utf-8").strip()
            if text:
                return text
        except OSError:
            pass
    return str(os.environ.get("UO_QUERY_EVAL_QID") or "mcp").strip() or "mcp"


def _append_eval(row: dict[str, Any]) -> None:
    log = str(os.environ.get("UO_QUERY_EVAL_LOG") or "").strip()
    if not log:
        return
    path = Path(log)
    lock = path.with_suffix(path.suffix + ".lock")
    line = json.dumps(row, ensure_ascii=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(200):
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            try:
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(line)
            finally:
                try:
                    lock.unlink()
                except OSError:
                    pass
            return
        except FileExistsError:
            time.sleep(0.02)
        except OSError:
            break
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)


def _product(project: str, architecture: str) -> Path:
    from uo_init.store.reader import find_uo_product

    root = Path(project).expanduser()
    found = find_uo_product(root, architecture=architecture)
    if found is None or found.suffix != ".uo":
        raise FileNotFoundError(
            f"no .uo product under {root}; expected "
            f".ascendc-pilot/{architecture or '<arch>'}/uo/<op>.{architecture or '<arch>'}.uo"
        )
    return found


def run_query(
    *,
    project: str = "",
    architecture: str = "",
    pattern: str = "",
    file: str = "",
    line: int = 0,
    line_end: int = 0,
) -> dict[str, Any]:
    project = str(project or os.environ.get("UO_QUERY_PROJECT") or "").strip()
    architecture = str(architecture or os.environ.get("UO_QUERY_ARCHITECTURE") or "").strip()
    if not project:
        raise ValueError("project is required (or set UO_QUERY_PROJECT)")
    # Defaulting to arch35 answered from whichever CodeMap happened to exist,
    # which reads as confident but belongs to another architecture.
    if not architecture:
        raise ValueError(
            "ARCHITECTURE_MISSING_IN_RUN_STATE: architecture is required "
            "(or set UO_QUERY_ARCHITECTURE)"
        )
    product = _product(project, architecture)
    t0 = time.perf_counter()
    if str(os.environ.get("UO_QUERY_MCP_DAEMON") or "").strip().lower() in {
        "1",
        "true",
        "yes",
    }:
        from uo_init.query_client import try_agent_query

        hopped = try_agent_query(
            product,
            pattern=str(pattern or ""),
            file=str(file or ""),
            line=int(line or 0),
            line_end=int(line_end or 0),
            architecture=architecture,
        )
        if isinstance(hopped, dict):
            hopped = dict(hopped)
            hopped["engine"] = hopped.get("engine") or "uo_init.uo_query"
            hopped["daemon"] = True
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            raw = json.dumps(hopped, ensure_ascii=False, default=str)
            utf8 = raw.encode("utf-8", errors="replace")
            _append_eval(
                {
                    "qid": _qid(),
                    "pid": os.getpid(),
                    "elapsed_ms": elapsed_ms,
                    "exit_code": 0 if hopped.get("ok") else 1,
                    "pattern": str(pattern or ""),
                    "file": str(file or ""),
                    "line": int(line or 0),
                    "ok": bool(hopped.get("ok")),
                    "shape": hopped.get("shape"),
                    "matching_block_count": hopped.get("matching_block_count"),
                    "count": hopped.get("count"),
                    "payload_chars": len(raw),
                    "est_tokens": max(1, len(utf8) // 4),
                    "daemon": True,
                    "next_head": list(hopped.get("next") or [])[:6],
                    "via": "mcp-daemon",
                }
            )
            return hopped
    key = str(product)
    try:
        mtime = int(product.stat().st_mtime_ns)
    except OSError:
        mtime = 0
    cached = _CACHE.get(key)
    q = None
    if isinstance(cached, tuple) and len(cached) == 2 and cached[1] == mtime:
        q = cached[0]
    if q is None:
        from uo_init.query.sql import UoSqlQuery

        q = UoSqlQuery(product)
        _CACHE[key] = (q, mtime)
    payload = q.agent_query(
        pattern=str(pattern or ""),
        file=str(file or ""),
        line=int(line or 0),
        line_end=int(line_end or 0),
    )
    payload["engine"] = "uo_init.uo_query"
    payload["daemon"] = False
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    raw = json.dumps(payload, ensure_ascii=False, default=str)
    utf8 = raw.encode("utf-8", errors="replace")
    _append_eval(
        {
            "qid": _qid(),
            "pid": os.getpid(),
            "elapsed_ms": elapsed_ms,
            "exit_code": 0 if payload.get("ok") else 1,
            "pattern": str(pattern or ""),
            "file": str(file or ""),
            "line": int(line or 0),
            "ok": bool(payload.get("ok")),
            "shape": payload.get("shape"),
            "matching_block_count": payload.get("matching_block_count"),
            "count": payload.get("count"),
            "payload_chars": len(raw),
            "est_tokens": max(1, len(utf8) // 4),
            "daemon": False,
            "next_head": list(payload.get("next") or [])[:6],
            "via": "mcp",
        }
    )
    return payload


def _tool_schema() -> dict[str, Any]:
    return {
        "name": "uo_query",
        "title": "uo_query",
        "description": (
            "Read-only Operator CodeMap query. Four shapes only: "
            "(1) no pattern = index, (2) identifier e.g. IsPse, "
            "(3) Dim=Name or Name=Value e.g. IsPse=1, "
            "(4) file + line copied from a previous card. "
            "Do not pass natural-language sentences."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Identifier, Dim=Name, or Name=Value. Omit for index.",
                },
                "file": {
                    "type": "string",
                    "description": "Relative path copied from a previous card.",
                },
                "line": {
                    "type": "integer",
                    "description": "Line number copied from a previous card.",
                },
                "line_end": {"type": "integer"},
                "project": {
                    "type": "string",
                    "description": "Operator directory. Defaults to UO_QUERY_PROJECT.",
                },
                "architecture": {
                    "type": "string",
                    "description": "e.g. arch35. Required; or set UO_QUERY_ARCHITECTURE.",
                },
            },
        },
    }


def _read_message() -> dict[str, Any] | None:
    content_length: int | None = None
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        if line.startswith(b"{") and content_length is None:
            return json.loads(line.decode("utf-8"))
        decoded = line.decode("utf-8", errors="replace").strip()
        if decoded.lower().startswith("content-length:"):
            content_length = int(decoded.split(":", 1)[1].strip())
    if content_length is None:
        return None
    body = sys.stdin.buffer.read(content_length)
    if not body:
        return None
    return json.loads(body.decode("utf-8"))


def _write_message(msg: dict[str, Any]) -> None:
    # Cursor MCP stdio is newline-delimited JSON (same as FastMCP / MCP SDK).
    # Content-Length replies are ignored by that client, so discovery hangs.
    raw = json.dumps(msg, ensure_ascii=False, default=str).encode("utf-8")
    sys.stdout.buffer.write(raw + b"\n")
    sys.stdout.buffer.flush()


def _result(req_id: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": payload}


def _error(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message[:500]},
    }


def handle(msg: dict[str, Any]) -> dict[str, Any] | None:
    method = str(msg.get("method") or "")
    req_id = msg.get("id")
    params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
    _debug({"method": method, "id": req_id, "param_keys": list(params.keys())})
    if method == "initialize":
        client_proto = str(params.get("protocolVersion") or PROTOCOL)
        return _result(
            req_id,
            {
                "protocolVersion": client_proto or PROTOCOL,
                "capabilities": {
                    "tools": {"listChanged": False},
                    "resources": {"listChanged": False},
                    "prompts": {"listChanged": False},
                },
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        )
    if method == "notifications/initialized" or method.startswith("notifications/"):
        return None
    if method == "ping":
        return _result(req_id, {})
    if method in {"shutdown", "exit"}:
        return _result(req_id, {})
    if method == "tools/list":
        return _result(req_id, {"tools": [_tool_schema()]})
    if method == "resources/list":
        return _result(req_id, {"resources": []})
    if method == "prompts/list":
        return _result(req_id, {"prompts": []})
    if method == "resources/templates/list":
        return _result(req_id, {"resourceTemplates": []})
    if method == "tools/call":
        name = str(params.get("name") or "")
        args = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        if name != "uo_query":
            return _result(
                req_id,
                {
                    "content": [{"type": "text", "text": f"unknown tool: {name}"}],
                    "isError": True,
                },
            )
        try:
            payload = run_query(
                project=str(args.get("project") or ""),
                architecture=str(args.get("architecture") or ""),
                pattern=str(args.get("pattern") or ""),
                file=str(args.get("file") or ""),
                line=int(args.get("line") or 0),
                line_end=int(args.get("line_end") or 0),
            )
            text = json.dumps(payload, ensure_ascii=False, default=str)
            return _result(
                req_id,
                {"content": [{"type": "text", "text": text}], "isError": False},
            )
        except Exception as exc:  # noqa: BLE001
            return _result(
                req_id,
                {
                    "content": [{"type": "text", "text": str(exc)[:500]}],
                    "isError": True,
                },
            )
    if req_id is None:
        return None
    return _error(req_id, -32601, f"method not found: {method}")


def _legacy_main() -> int:
    while True:
        try:
            msg = _read_message()
        except Exception as exc:  # noqa: BLE001
            _debug({"read_error": str(exc)})
            continue
        if msg is None:
            return 0
        if not isinstance(msg, dict):
            continue
        reply = handle(msg)
        if reply is not None:
            _write_message(reply)
        if str(msg.get("method") or "") in {"shutdown", "exit"}:
            return 0


def main() -> int:
    # Default is the in-repo JSON-RPC loop. FastMCP logs INFO to stderr (Cursor
    # treats that as MCP errors) and its NDJSON-only reader used to race with
    # Content-Length probes. Force FastMCP with UO_MCP_FASTMCP=1 if needed.
    if str(os.environ.get("UO_MCP_FASTMCP") or "").strip() in {"1", "true", "yes"}:
        try:
            from mcp.server.fastmcp import FastMCP
        except Exception as exc:  # noqa: BLE001
            _debug({"fastmcp_import": str(exc)})
            return _legacy_main()
        server = FastMCP("ascendc-pilot")

        @server.tool(
            name="uo_query",
            title="uo_query",
            description=(
                "Read-only Operator CodeMap query. Four shapes only: "
                "(1) no pattern = index, (2) identifier e.g. IsPse, "
                "(3) Dim=Name or Name=Value e.g. IsPse=1, "
                "(4) file + line copied from a previous card. "
                "Do not pass natural-language sentences."
            ),
            structured_output=False,
        )
        def uo_query(
            pattern: str = "",
            file: str = "",
            line: int = 0,
            line_end: int = 0,
            project: str = "",
            architecture: str = "",
        ) -> str:
            payload = run_query(
                project=project,
                architecture=architecture,
                pattern=pattern,
                file=file,
                line=line,
                line_end=line_end,
            )
            return json.dumps(payload, ensure_ascii=False, default=str)

        _debug({"boot": "fastmcp"})
        server.run(transport="stdio")
        return 0
    _debug({"boot": "legacy"})
    return _legacy_main()


if __name__ == "__main__":
    raise SystemExit(main())
