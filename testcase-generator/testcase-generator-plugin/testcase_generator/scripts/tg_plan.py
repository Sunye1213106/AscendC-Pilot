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
    from testcase_generator.engine.obligations import expand_obligations, plan_summary_text

    project_root = resolve_project_root(project_root_arg, project_root_opt)
    _, op, _, tg = resolve_paths(project_root, op_name, output_root)
    snap_path = tg / "kb_snapshot.yaml"
    if not snap_path.exists():
        click.echo("ERROR: kb_snapshot.yaml missing. Run tg-init first.", err=True)
        return 1
    snapshot = load_yaml(snap_path)
    obligations = expand_obligations(snapshot)
    dump_yaml(tg / "plan" / "coverage_obligations.yaml", obligations)
    summary = plan_summary_text(obligations)
    (tg / "plan" / "coverage_plan_summary.md").write_text(summary, encoding="utf-8")
    log(verbose, summary)
    click.echo(f"Wrote plan/coverage_obligations.yaml ({obligations['summary']['total']} obligations)")
    click.echo("Human review: approve | approve_with_extra_constraints | add_obligation | remove_obligation | stop")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
