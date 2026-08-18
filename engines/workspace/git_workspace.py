# -*- coding: utf-8 -*-
"""Compatibility surface for workspace helpers with PR isolation enforced."""

from git_workspace_legacy import *  # noqa: F401,F403
from git_workspace_legacy import _diff_digest, _resolve_sha, _run_git  # noqa: F401
from pr_workspace import acquire_pull_request, detect_operator_roots  # noqa: F401
