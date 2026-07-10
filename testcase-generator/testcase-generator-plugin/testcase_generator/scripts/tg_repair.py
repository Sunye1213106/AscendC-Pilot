from __future__ import annotations

import click

from testcase_generator.scripts._cli import bootstrap, common_options, log, resolve_project_root


@click.command()
@click.option("--max-rounds", default=3, show_default=True)
@common_options
def main(
    project_root_arg: str | None,
    project_root_opt: str | None,
    op_name: str | None,
    output_root: str | None,
    verbose: bool,
    max_rounds: int,
) -> int:
    bootstrap()
    from testcase_generator._core.paths import resolve_paths
    from testcase_generator._core.yaml_io import dump_yaml, load_yaml

    project_root = resolve_project_root(project_root_arg, project_root_opt)
    _, op, _, tg = resolve_paths(project_root, op_name, output_root)
    audit_path = tg / "audit" / "coverage_audit.yaml"
    if not audit_path.exists():
        click.echo("ERROR: audit/coverage_audit.yaml missing. Run tg-audit first.", err=True)
        return 1

    audit = load_yaml(audit_path)
    missing = audit.get("missing", [])
    repair_plan = {
        "version": 1,
        "op_name": op,
        "status": "stub",
        "max_rounds": max_rounds,
        "missing_count": len(missing),
        "repair_targets": [
            {"obligation_id": m.get("id"), "type": m.get("type"), "action": "generate_repair_case"}
            for m in missing[:10]
        ],
        "note": "MVP stub: re-run tg-generate/tg-probe/tg-audit after manual rule/realization fixes.",
    }
    dump_yaml(tg / "repair" / "repair_plan.yaml", repair_plan)
    log(verbose, f"repair targets: {len(repair_plan['repair_targets'])}")
    click.echo("Wrote repair/repair_plan.yaml (MVP stub)")
    if missing and max_rounds > 0:
        click.echo("Suggestion: fix rule_model or input_realization, then re-run generate/probe/audit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
