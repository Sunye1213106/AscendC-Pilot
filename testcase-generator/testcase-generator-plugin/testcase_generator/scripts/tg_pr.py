from __future__ import annotations

import click

from testcase_generator.scripts._cli import bootstrap, common_options, log, resolve_project_root


@click.command()
@common_options
def main(
    project_root_arg: str | None,
    project_root_opt: str | None,
    op_name: str | None,
    output_root: str | None,
    verbose: bool,
) -> int:
    bootstrap()
    from testcase_generator._core.paths import resolve_paths
    from testcase_generator._core.yaml_io import dump_yaml, load_yaml

    project_root = resolve_project_root(project_root_arg, project_root_opt)
    _, op, uo, tg = resolve_paths(project_root, op_name, output_root)
    change_set = uo / "cbm" / "change_set.yaml"
    update_plan = uo / "summary" / "update_plan.yaml"
    _ = load_yaml(tg / "kb_snapshot.yaml")

    status = "ready" if change_set.exists() and update_plan.exists() else "stub_missing_inputs"
    pr_report = {
        "version": 1,
        "op_name": op,
        "status": status,
        "change_set": str(change_set) if change_set.exists() else None,
        "update_plan": str(update_plan) if update_plan.exists() else None,
        "impacted_obligations": [],
        "note": "MVP stub: PR incremental analysis reserved. Run full tg-plan/generate when change_set missing.",
    }
    if not change_set.exists() or not update_plan.exists():
        click.echo(
            "WARNING: cbm/change_set.yaml or summary/update_plan.yaml missing. Wrote stub pr_test_report.",
            err=True,
        )

    dump_yaml(tg / "pr" / "pr_test_report.yaml", pr_report)
    (tg / "pr" / "pr_test_report.md").write_text(
        f"# PR Test Report (stub) — {op}\n\nstatus: {status}\n",
        encoding="utf-8",
    )
    log(verbose, str(pr_report))
    click.echo(f"Wrote pr/pr_test_report.md (status={status})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
