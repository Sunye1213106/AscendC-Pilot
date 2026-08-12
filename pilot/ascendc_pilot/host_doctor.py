"""Host adapter contract checks for ``acp doctor --host``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _opencode_home() -> Path:
    return Path.home() / ".config" / "opencode"


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
    add(
        "plugin_return_value_ts",
        (plugins / "zz-uo-query-return-value.ts").is_file()
        or (plugins / "uo-query-return-value.ts").is_file(),
        "zz-uo-query-return-value.ts",
    )
    add(
        "plugin_pilot_driver_ts",
        (plugins / "pilot-driver.ts").is_file()
        or (home / "ascendc-pilot-plugin" / "opencode-plugin" / "pilot-driver.ts").is_file()
        or (Path(__file__).resolve().parents[2] / "opencode-plugin" / "pilot-driver.ts").is_file(),
        "pilot-driver.ts required for Host Session Driver",
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
        if "skills/testcase-generation/SKILL.md" in text and "cognitive-skills/" not in text:
            # Still pointing at non-discoverable path without cognitive remap.
            skill_path = home / "skills" / "testcase-generation" / "SKILL.md"
            cog = home / "ascendc-pilot-plugin" / "cognitive-skills" / "testcase-generation" / "SKILL.md"
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

    harness_bin = home / "ascendc-harness-bin"
    add("harness_bin_cache", harness_bin.is_file(), str(harness_bin))

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
        + ("通过" if ok else "失败——请重装 install.ps1 opencode / compose_runtime"),
    }


__all__ = ["doctor_host"]
