from __future__ import annotations

import click

from testcase_generator.scripts._cli import bootstrap, common_options, resolve_project_root


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
    from testcase_generator._core.yaml_io import load_yaml

    project_root = resolve_project_root(project_root_arg, project_root_opt)
    _, op, _, tg = resolve_paths(project_root, op_name, output_root)
    audit_path = tg / "audit" / "coverage_audit.yaml"
    if not audit_path.exists():
        click.echo("ERROR: audit/coverage_audit.yaml missing. Run tg-audit first.", err=True)
        return 1

    audit = load_yaml(audit_path)
    s = audit.get("summary", {})
    lines = [
        f"# Final Test Report — {op}",
        "",
        "## Coverage Summary",
        f"- verified: {s.get('verified')}",
        f"- mock_probe: {s.get('mock_probe')}",
        f"- family_coverage: {s.get('family_coverage')}",
        f"- key_field_value_coverage: {s.get('key_field_value_coverage')}",
        f"- key_relation_coverage: {s.get('key_relation_coverage')}",
        f"- tilingdata_coverage: {s.get('tilingdata_coverage')}",
        f"- expected_observed_match_rate: {s.get('expected_observed_match_rate')}",
        "",
        f"Missing obligations: {len(audit.get('missing', []))}",
        f"Mismatches: {len(audit.get('mismatches', []))}",
        "",
        "## Notes",
        "- Family coverage != tiling_key coverage.",
        "- observed_key is the only coverage evidence.",
    ]
    if s.get("mock_probe"):
        lines.append("- mock_probe: true — do not claim verified coverage.")

    report = "\n".join(lines)
    out = tg / "report" / "final_report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    click.echo("Wrote report/final_report.md")
    if verbose:
        click.echo(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
