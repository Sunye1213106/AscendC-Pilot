"""Generate Reference pages from workflow, agent, CLI and path authorities."""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "docs" / "reference"
CLI_HELP_ZH = {
    "abort": "终止当前 run 并标记为失败",
    "advance": "仅在当前 phase gate 通过后推进状态",
    "authorize": "执行 host hook 的授权检查",
    "block": "标记为 blocked、failed 或 human_required",
    "complete": "全部 gate 通过后标记 workflow 完成",
    "context": "构建 context pack",
    "debug": "采集诊断信息并导出 session bundle",
    "doctor": "执行环境预检",
    "emit-confidence-report": "已移除：改用 /uo-init verify 或 `acp uo-query --status-only`",
    "inspect": "查询结构化 IR / 证据窗口（tasks、YAML 计数、evidence-window）",
    "inspect-failure": "查看结构化 failure 信息",
    "next": "查看可执行的下一动作与 obligations",
    "retry-after-environment-fix": "环境修复后恢复失败动作的 rework 状态",
    "rework": "沿声明的 rework edge 恢复",
    "ro-search": "只读源码搜索，不执行 shell 重定向",
    "route": "将自然语言或 Slash 路由到 workflow",
    "run-action": "准备或 finalize 一个 workflow action",
    "run-summary": "汇总中断的 uo-init run，供人工询问使用",
    "scan-architectures": "快速扫描算子 op_host/op_kernel 布局与 arch* 选项",
    "spec-hashes": "输出四类 Spec Hash 摘要",
    "start": "从 entry state 启动 workflow",
    "status": "查看 workflow 状态",
    "uo": "查询和解释 UO Host contract",
    "uo-query": "通过 Pilot wrapper 查询 UO KB graph",
    "uo-scope": "执行 UO 源码范围扫描与校验",
    "validate": "执行当前 workflow 的全部 gate",
    "validate-key-gates": "执行关键硬 gate",
    "answer": "把 Host 问答结果记为已签名的 HumanDecisionReceipt",
    "dispatch-result": "Host Session Driver：消费 dispatch ticket、finalize 并继续驱动",
    "host-context": "解析 arch 作用域的 Host 适配器上下文",
    "serve-authorize": "长驻 authorize 守护进程（stdio JSON-lines）",
}


def _action_execution_cell(actions: list[dict]) -> str:
    """Summarize per-Action execution_mode (+ actor when not deterministic)."""
    parts: list[str] = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        aid = str(action.get("id") or "").strip()
        if not aid:
            continue
        mode = str(action.get("execution_mode") or "").strip() or "?"
        actor = str(action.get("agent_id") or "").strip()
        if mode == "deterministic":
            parts.append(f"`{aid}`:deterministic")
        elif actor:
            parts.append(f"`{aid}`:{mode}(`{actor}`)")
        else:
            parts.append(f"`{aid}`:{mode}")
    return "<br>".join(parts) if parts else ""


def _workflow_agents_cell(agents: list[dict]) -> str:
    names: list[str] = []
    for row in agents:
        if not isinstance(row, dict):
            continue
        aid = str(row.get("id") or "").strip()
        if aid:
            names.append(f"`{aid}`")
    return ", ".join(names)


def render_workflows() -> str:
    # Use normalized registry so Action execution_mode / agent_id match runtime.
    sys.path.insert(0, str(ROOT / "pilot"))
    from ascendc_pilot.workflows import WORKFLOWS

    lines = [
        "# 工作流 Reference",
        "",
        "本文件由 `pilot/ascendc_pilot/workflows/specs.py`（经 registry normalize）生成，请不要手工编辑。",
        "",
        "`Action 执行` 来自各 Action 的 `execution_mode` / `agent_id`；`Workflow Agents` 是 workflow 声明的身份清单（含 Primary），**不是**逐步执行者。",
        "",
        "| 工作流 | 入口 | 状态 | Action | Action 执行 | Workflow Agents | Gate |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for workflow_id, spec in WORKFLOWS.items():
        states = ", ".join(str(row.get("id") or "") for row in spec.get("states", []))
        actions = list(spec.get("actions") or [])
        action_ids = ", ".join(str(row.get("id") or "") for row in actions if isinstance(row, dict))
        exec_cell = _action_execution_cell(actions)
        agents_cell = _workflow_agents_cell(list(spec.get("agents") or []))
        gates = ", ".join(str(value) for value in spec.get("gates", []))
        slash = str(spec.get("slash") or "")
        entry = f"`{slash}`" if slash else "内部（无 Slash 入口）"
        lines.append(
            f"| `{workflow_id}` | {entry} | {states} | {action_ids} | {exec_cell} | {agents_cell} | {gates} |"
        )
    lines.append("")
    return "\n".join(lines)


def _console_scripts(pyproject: Path) -> list[str]:
    """Names from ``[project.scripts]``; comments and other tables are ignored."""
    if not pyproject.is_file():
        return []
    names: list[str] = []
    in_scripts = False
    for line in pyproject.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped == "[project.scripts]":
            in_scripts = True
            continue
        if in_scripts:
            if stripped.startswith("["):
                break
            if not stripped or stripped.startswith("#"):
                continue
            if "=" in stripped:
                names.append(stripped.split("=", 1)[0].strip())
    return names


def render_cli() -> str:
    source = (ROOT / "pilot" / "ascendc_pilot" / "cli.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    rows: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        if not (
            isinstance(call.func, ast.Attribute)
            and call.func.attr == "add_parser"
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "sub"
            and call.args
            and isinstance(call.args[0], ast.Constant)
            and isinstance(call.args[0].value, str)
        ):
            continue
        help_text = ""
        for keyword in call.keywords:
            if keyword.arg == "help" and isinstance(keyword.value, ast.Constant):
                help_text = str(keyword.value.value)
                break
        rows.append((str(call.args[0].value), help_text))
    rows.sort()
    lines = [
        "# CLI Reference",
        "",
        "本文件从 `pilot/ascendc_pilot/cli.py` 和 engine package metadata 生成，请不要手工编辑。",
        "",
        "主 CLI：`acp <command>`；安装 package 后也可使用 `ascendc-pilot <command>`。",
        "",
        "## Pilot 命令",
        "",
        "| 命令 | 说明 |",
        "| --- | --- |",
    ]
    for command, help_text in rows:
        lines.append(f"| `acp {command}` | {CLI_HELP_ZH.get(command, help_text)} |")
    lines.extend(
        [
            "",
            "## Engine 命令",
            "",
            "| 命令 | 软件包 |",
            "| --- | --- |",
        ]
    )
    engine_packages = (
        (ROOT / "engines" / "understand-operator" / "pyproject.toml", "engines/understand-operator"),
        (ROOT / "engines" / "testcase-generation" / "pyproject.toml", "engines/testcase-generation"),
        (ROOT / "engines" / "code-engineering" / "pyproject.toml", "engines/code-engineering"),
    )
    for pyproject, package in engine_packages:
        scripts = _console_scripts(pyproject)
        if not scripts:
            continue
        listed = "、".join(f"`{name}`" for name in scripts)
        lines.append(f"| {listed} | `{package}` |")
    lines.extend(["", ""])
    return "\n".join(lines)


def render_artifacts() -> str:
    sys.path.insert(0, str(ROOT / "pilot"))
    from ascendc_pilot.paths import (
        AGENT_DIR,
        CACHE_SUBDIR,
        CE_SUBDIR,
        CONTEXT_SUBDIR,
        LOCAL_SUBDIR,
        MEMORY_SUBDIR,
        RUNS_SUBDIR,
        STATE_SUBDIR,
        TG_SUBDIR,
        UO_SUBDIR,
        uo_codemap_path,
    )

    example_op = "<op>"
    example_arch = "<arch>"
    codemap = uo_codemap_path(Path("operator-repo"), example_op, arch=example_arch)
    product_rel = f"{example_arch}/{UO_SUBDIR}/{example_op}.{example_arch}.uo"
    if codemap.name != f"{example_op}.{example_arch}.uo" or product_rel not in codemap.as_posix().replace("\\", "/"):
        raise RuntimeError(f"uo_codemap_path() drifted from <arch>/uo/<op>.<arch>.uo: {codemap}")

    lines = [
        "# 产物布局 Reference",
        "",
        "本文件从 `pilot/ascendc_pilot/paths/` 的路径约定生成，请不要手工编辑。",
        "",
        "```text",
        f"<operator-repo>/{AGENT_DIR}/",
        f"  {product_rel:<28} UO canonical product (uo_codemap_path)",
        f"  <arch>/{UO_SUBDIR}/               UO projections and receipts",
        f"  <arch>/{TG_SUBDIR}/               TG contracts, plans, closure, replay",
        f"  <arch>/{CE_SUBDIR}/               CE review and impact products",
        f"  <arch>/{STATE_SUBDIR}/            Pilot state and leases",
        f"  <arch>/{RUNS_SUBDIR}/             action bundles, staging and receipts",
        f"  <arch>/{CONTEXT_SUBDIR}/          compiled context packs",
        f"  <arch>/{MEMORY_SUBDIR}/           candidate and stable memory",
        f"  <arch>/{LOCAL_SUBDIR}/            operator-local extensions",
        f"  <arch>/{CACHE_SUBDIR}/            rebuildable caches",
        "```",
        "",
        "路径的归属、canonical 语义与 freshness 规则见 [产物与权威](../architecture/artifacts-and-authority.md)。",
        "",
    ]
    return "\n".join(lines)


def generated() -> dict[Path, str]:
    return {
        REFERENCE / "workflows.generated.md": render_workflows(),
        REFERENCE / "cli.generated.md": render_cli(),
        REFERENCE / "artifact-layout.generated.md": render_artifacts(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail when generated files are stale")
    args = parser.parse_args()
    stale: list[str] = []
    for path, expected in generated().items():
        actual = path.read_text(encoding="utf-8") if path.is_file() else ""
        if actual != expected:
            stale.append(path.relative_to(ROOT).as_posix())
            if not args.check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(expected, encoding="utf-8")
    matrix_cmd = [sys.executable, "scripts/generate_agent_matrix.py"]
    if args.check:
        matrix_cmd.append("--check")
    matrix = subprocess.run(matrix_cmd, cwd=ROOT, check=False)
    if matrix.returncode:
        stale.append("docs/reference/agent-matrix.generated.md")
    if args.check and stale:
        for path in stale:
            print(f"stale generated reference: {path}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
