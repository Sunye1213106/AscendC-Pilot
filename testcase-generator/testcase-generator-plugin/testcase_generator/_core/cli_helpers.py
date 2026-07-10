from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

import click

from testcase_generator._core.paths import safe_op_name, testcase_root, understand_root


def common_options(func: Callable) -> Callable:
    func = click.option(
        "--project-root",
        type=click.Path(exists=True, file_okay=False, path_type=Path),
        default=".",
        help="AscendC operator repository root",
    )(func)
    func = click.option("--op-name", default=None, help="Operator name (defaults to repo name)")(func)
    func = click.option(
        "--output-root",
        type=click.Path(file_okay=False, path_type=Path),
        default=None,
        help="Override .testcase-generator parent directory",
    )(func)
    func = click.option("--verbose", is_flag=True, help="Verbose logging")(func)
    return func


def resolve_context(project_root: Path, op_name: str | None, output_root: Path | None) -> tuple[Path, str, Path, Path]:
    repo = project_root.resolve()
    op = safe_op_name(op_name, repo)
    uo = understand_root(repo, op)
    tg = testcase_root(repo, op, output_root.resolve() if output_root else None)
    return repo, op, uo, tg


def log(verbose: bool, message: str) -> None:
    if verbose:
        click.echo(message, err=True)


def exit_missing_kb(missing: list[str]) -> None:
    click.echo(
        "Missing canonical understand-operator KB files:\n"
        + "\n".join(f"  - {m}" for m in missing)
        + "\n\nRun /uo-init or /uo-update first to generate canonical tiling KB.",
        err=True,
    )
    raise SystemExit(2)


def ensure_package_path() -> None:
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
