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
    from testcase_generator.engine.snapshot import SnapshotError, write_snapshot_artifacts

    project_root = resolve_project_root(project_root_arg, project_root_opt)
    repo, op, uo, tg = resolve_paths(project_root, op_name, output_root)
    log(verbose, f"UO_ROOT={uo}")
    log(verbose, f"TG_ROOT={tg}")
    try:
        result = write_snapshot_artifacts(tg, op, uo)
    except SnapshotError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        return 1
    click.echo(f"Initialized testcase-generator context for {op}")
    click.echo(f"Output: {tg}")
    click.echo(f"kb_snapshot: {tg / 'kb_snapshot.yaml'}")
    if result.missing:
        click.echo(f"WARNING: still missing: {result.missing}", err=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
