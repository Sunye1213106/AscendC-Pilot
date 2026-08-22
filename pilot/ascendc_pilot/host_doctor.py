"""Host adapter contract checks for ``acp doctor --host``."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ascendc_pilot.paths import opencode_home as _opencode_home


def plugin_hook_redeclared_consts(src: str) -> list[str]:
    """Catch the load-breaker: ``const sessionId`` twice in ``tool.execute.before``.

    Nested ``if`` blocks may legally redeclare other names; Bun/Node only
    reject same-scope bindings. ``sessionId`` must be extracted once at the
    start of that hook and reused.
    """
    before_at = src.find('"tool.execute.before"')
    after_at = src.find('"tool.execute.after"')
    errors: list[str] = []
    if before_at < 0:
        errors.append("missing tool.execute.before")
    if after_at < 0:
        errors.append("missing tool.execute.after")
    if errors:
        return errors
    n = len(re.findall(r"\bconst\s+sessionId\s*=", src[before_at:after_at]))
    if n != 1:
        errors.append(f"tool.execute.before declares const sessionId {n} time(s); expected 1")
    return errors


def parse_opencode_plugin_ts(path: Path, *, check_hooks: bool | None = None) -> dict[str, Any]:
    """Parse-check an OpenCode plugin .ts so a syntax error cannot install silently."""
    if not path.is_file():
        return {"ok": False, "detail": f"missing {path}"}
    src = path.read_text(encoding="utf-8")
    if check_hooks is None:
        check_hooks = path.name == "ascendc-pilot.ts"
    if check_hooks:
        dups = plugin_hook_redeclared_consts(src)
        if dups:
            return {"ok": False, "detail": "; ".join(dups)}
    node = shutil.which("node")
    if not node:
        return {"ok": True, "detail": "hook consts unique; node not on PATH"}
    commands = (
        [node, "--experimental-strip-types", "--check", str(path)],
        [node, "--check", str(path)],
    )
    last_err = "node --check failed"
    for cmd in commands:
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
            )
        except OSError as exc:
            return {"ok": False, "detail": str(exc)[:200]}
        err = f"{proc.stderr or ''}{proc.stdout or ''}"
        if proc.returncode == 0:
            return {"ok": True, "detail": "parsed"}
        if any("strip-types" in str(part) for part in cmd) and (
            "bad option" in err.lower() or "unrecognized" in err.lower() or "unknown option" in err.lower()
        ):
            last_err = err.strip()[-800:] or last_err
            continue
        return {"ok": False, "detail": (err.strip() or f"exit {proc.returncode}")[-800:]}
    return {"ok": False, "detail": last_err[-800:]}


def doctor_host(host: str, *, project: Path | None = None) -> dict[str, Any]:
    host_l = (host or "").strip().lower()
    if host_l == "opencode":
        return _doctor_opencode(project=project)
    return {
        "ok": False,
        "error": "HOST_UNSUPPORTED",
        "message_zh": f"未知 host={host!r}（当前支持 opencode）",
    }


def _doctor_opencode(*, project: Path | None = None) -> dict[str, Any]:
    home = _opencode_home()
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    plugins = home / "plugins"
    add(
        "plugin_ascendc_pilot_ts",
        (plugins / "ascendc-pilot.ts").is_file(),
        str(plugins / "ascendc-pilot.ts"),
    )
    bundled_driver = home / "ascendc-pilot-plugin" / "opencode-plugin" / "pilot-driver.ts"
    add(
        "plugin_pilot_driver_ts",
        bundled_driver.is_file(),
        str(bundled_driver),
    )

    agents = home / "agents"
    agent_files = list(agents.glob("*.md")) if agents.is_dir() else []
    add("agents_installed", bool(agent_files), f"count={len(agent_files)}")

    # Description path existence for subagents (skills vs cognitive-skills).
    bad_desc: list[str] = []
    for md in agent_files:
        try:
            text = md.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            continue
        if "skills/solve/SKILL.md" in text and "cognitive-skills/" not in text:
            skill_path = home / "skills" / "solve" / "SKILL.md"
            cog = home / "ascendc-pilot-plugin" / "cognitive-skills" / "solve" / "SKILL.md"
            if not skill_path.is_file() and cog.is_file():
                bad_desc.append(md.name)
    add(
        "agent_description_paths",
        len(bad_desc) == 0,
        ("ok" if not bad_desc else "stale skills/ paths: " + ", ".join(bad_desc[:6])),
    )

    cog = home / "ascendc-pilot-plugin" / "cognitive-skills"
    cog_ids = [p.name for p in cog.iterdir()] if cog.is_dir() else []
    add("cognitive_skills_present", bool(cog_ids), ",".join(cog_ids[:8]))

    workflow_skill_names = (
        "uo-init",
        "uo-update",
        "uo-query",
        "uo-investigate",
        "ce-review",
        "ce-plan",
        "ce-apply",
        "handoff",
        "tg-init",
        "tg-plan",
        "tg-solve",
        "operator",
    )
    leaked = [n for n in workflow_skill_names if (home / "skills" / n).exists()]
    add(
        "workflow_skills_not_in_global_discovery",
        len(leaked) == 0,
        "ok" if not leaked else "leaked into ~/.config/opencode/skills: " + ",".join(leaked[:8]),
    )
    internal_uo = home / "ascendc-pilot-plugin" / "skills" / "uo-init" / "SKILL.md"
    add(
        "workflow_skills_plugin_internal",
        internal_uo.is_file(),
        str(internal_uo),
    )

    plug_ts = plugins / "ascendc-pilot.ts"
    plug_text = plug_ts.read_text(encoding="utf-8") if plug_ts.is_file() else ""
    if plug_ts.is_file():
        parsed = parse_opencode_plugin_ts(plug_ts)
        add("plugin_parses", bool(parsed.get("ok")), str(parsed.get("detail") or "")[:240])
    add(
        "plugin_does_not_override_native_skill",
        plug_ts.is_file()
        and ").skill = createPilotSkillTool" not in plug_text
        and "pilotTools as Record<string, unknown>).skill" not in plug_text,
        "native OpenCode skill tool left intact for Build/Plan",
    )
    add(
        "plugin_uo_query_return_capture",
        "captureUoQueryTaskReturn" in plug_text and "ASCENDC_ACTION_RESULT" in plug_text,
        "uo-query Task return captured in ascendc-pilot.ts",
    )
    add(
        "plugin_skill_rg_recovery",
        "resolveInstalledSkillMd" in plug_text and "Do NOT overwrite OpenCode Task" in plug_text,
        "skill rg recovery + Host session location",
    )
    add(
        "plugin_keeps_host_session_location",
        "Do NOT overwrite OpenCode Task" in plug_text
        and "args.location = { directory: projectRoot }" not in plug_text,
        "Task location stays Host workspace",
    )

    acp_bin = shutil.which("acp")
    if acp_bin:
        query_alias = False
        query_detail = "uo-query --help"
        try:
            proc = subprocess.run(
                [acp_bin, "uo-query", "--help"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                check=False,
            )
            help_text = f"{proc.stdout or ''}{proc.stderr or ''}"
            query_alias = "--query" in help_text
        except Exception as exc:  # noqa: BLE001
            query_detail = str(exc)[:160]
        add("acp_uo_query_query_alias", query_alias, query_detail)

    harness_bin = home / "ascendc-harness-bin"
    add("harness_bin_cache", harness_bin.is_file(), str(harness_bin))

    expected_cmds = (
        "uo-init",
        "uo-update",
        "uo-query",
        "uo-investigate",
        "ce-review",
        "ce-plan",
        "ce-apply",
        "handoff",
        "tg-init",
        "tg-plan",
        "tg-solve",
    )
    cmd_dir = home / "commands"
    missing_cmds = [n for n in expected_cmds if not (cmd_dir / f"{n}.md").is_file()]
    add(
        "opencode_commands",
        len(missing_cmds) == 0,
        "ok" if not missing_cmds else "missing: " + ",".join(missing_cmds),
    )
    primary_md = home / "agents" / "ascendc-pilot.md"
    add("opencode_primary_agent", primary_md.is_file(), str(primary_md))

    # serve-authorize importable
    try:
        from ascendc_pilot.authorize.serve import handle_request

        ping = handle_request({"method": "ping"})
        add("serve_authorize_ping", bool(ping.get("ok")), json.dumps(ping)[:120])
    except Exception as exc:  # noqa: BLE001
        add("serve_authorize_ping", False, str(exc)[:200])

    # Bundle helpers
    try:
        from ascendc_pilot.actions.method_bundle import check_bundle_readable
        from ascendc_pilot.actions.dispatch import build_host_step

        _ = check_bundle_readable
        _ = build_host_step
        add("bundle_and_dispatch_modules", True, "import ok")
    except Exception as exc:  # noqa: BLE001
        add("bundle_and_dispatch_modules", False, str(exc)[:200])

    if project is not None:
        pr = Path(project)
        add("project_exists", pr.is_dir(), str(pr))
        add(
            "project_looks_like_operator",
            (pr / "op_host").is_dir() or (pr / "op_kernel").is_dir() or (pr / "CMakeLists.txt").is_file(),
            "op_host|op_kernel|CMakeLists",
        )

    ok = all(bool(c.get("ok")) for c in checks)
    return {
        "ok": ok,
        "host": "opencode",
        "checks": checks,
        "message_zh": "OpenCode host contract "
        + (
            "通过"
            if ok
            else "失败——请重新运行安装脚本（Windows: .\\install.ps1 opencode；Linux: ./install.sh opencode）"
        ),
    }


__all__ = ["doctor_host", "parse_opencode_plugin_ts", "plugin_hook_redeclared_consts"]
