from __future__ import annotations

import click

from testcase_generator.scripts._cli import bootstrap, common_options, log, resolve_project_root


@click.command()
@click.option("--mock", is_flag=True, help="Use MockTilingProbe (verified=false)")
@common_options
def main(
    project_root_arg: str | None,
    project_root_opt: str | None,
    op_name: str | None,
    output_root: str | None,
    verbose: bool,
    mock: bool,
) -> int:
    bootstrap()
    from testcase_generator._core.paths import resolve_paths
    from testcase_generator._core.yaml_io import load_jsonl, load_yaml, write_jsonl
    from testcase_generator.probe.base import ExternalTilingProbe, MockTilingProbe

    project_root = resolve_project_root(project_root_arg, project_root_opt)
    _, op, _, tg = resolve_paths(project_root, op_name, output_root)
    probe_cases_path = tg / "generate" / "probe_cases.jsonl"
    if not probe_cases_path.exists():
        click.echo("ERROR: generate/probe_cases.jsonl missing. Run tg-generate first.", err=True)
        return 1

    snap = load_yaml(tg / "kb_snapshot.yaml")
    key_space = snap.get("tiling", {}).get("key_space", {})
    cases = load_jsonl(probe_cases_path)

    if mock:
        probe = MockTilingProbe(key_space)
    else:
        probe = ExternalTilingProbe()

    probe_results: list[dict] = []
    observed_keys: list[dict] = []
    for case in cases:
        try:
            result = probe.run_case(case)
        except NotImplementedError as exc:
            click.echo(f"ERROR: {exc}", err=True)
            return 1
        probe_results.append({**result, "inputs": case.get("inputs", {})})
        observed_keys.append(
            {
                "case_id": result.get("case_id"),
                "status": result.get("status"),
                "tiling_key": result.get("tiling_key"),
                "decoded_key": result.get("decoded_key", {}),
                "family_guess": result.get("family_guess"),
                "mock_probe": result.get("mock_probe", mock),
                "coverage_verified": result.get("coverage_verified", not mock),
            }
        )

    probe_dir = tg / "probe"
    write_jsonl(probe_dir / "probe_results.jsonl", probe_results)
    write_jsonl(probe_dir / "observed_keys.jsonl", observed_keys)
    log(verbose, f"Probed {len(observed_keys)} cases (mock={mock})")
    click.echo(f"Wrote probe/observed_keys.jsonl (mock_probe={mock})")
    if mock:
        click.echo("coverage_verified: false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
