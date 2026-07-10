from __future__ import annotations

import functools
import sys
from pathlib import Path
from typing import Any, Callable

import click


def bootstrap() -> None:
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def common_options(fn: Callable[..., Any]) -> Callable[..., Any]:
    fn = click.option("--verbose", is_flag=True, help="Verbose logging")(fn)
    fn = click.option("--output-root", default=None, help="Override .testcase-generator parent dir")(fn)
    fn = click.option("--op-name", default=None, help="Operator name")(fn)
    fn = click.option(
        "--project-root",
        "project_root_opt",
        default=None,
        help="AscendC repo root (alternative to positional path)",
    )(fn)
    fn = click.argument("project_root_arg", required=False, default=None)(fn)
    return fn


def resolve_project_root(project_root_arg: str | None, project_root_opt: str | None) -> str:
    return project_root_opt or project_root_arg or "."


def log(verbose: bool, msg: str) -> None:
    if verbose:
        click.echo(msg)
