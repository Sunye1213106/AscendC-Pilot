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
    from testcase_generator._core.yaml_io import dump_yaml, load_jsonl, load_yaml
    from testcase_generator.engine.audit import audit_coverage, coverage_matrix_md

    project_root = resolve_project_root(project_root_arg, project_root_opt)
    _, op, _, tg = resolve_paths(project_root, op_name, output_root)
    obligations = load_yaml(tg / "plan" / "coverage_obligations.yaml")
    realized = load_yaml(tg / "generate" / "realized_cases.yaml")
    observed_path = tg / "probe" / "observed_keys.jsonl"
    if not observed_path.exists():
        click.echo("ERROR: probe/observed_keys.jsonl missing. Run tg-probe first.", err=True)
        return 1

    observed = load_jsonl(observed_path)
    mock_probe = any(row.get("mock_probe") for row in observed)
    cases = realized.get("cases", [])
    audit = audit_coverage(obligations, cases, observed, mock_probe=mock_probe)
    matrix = coverage_matrix_md(audit)

    audit_dir = tg / "audit"
    dump_yaml(audit_dir / "coverage_audit.yaml", audit)
    (audit_dir / "coverage_matrix.md").write_text(matrix, encoding="utf-8")
    log(verbose, matrix)
    click.echo(f"Audit complete: verified={audit['summary']['verified']}")
    click.echo("Wrote audit/coverage_audit.yaml and coverage_matrix.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
