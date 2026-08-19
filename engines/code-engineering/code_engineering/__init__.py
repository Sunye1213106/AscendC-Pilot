# -*- coding: utf-8 -*-
"""Code Engineering (CE) engine for AscendC-Pilot.

Named markdown plans, apply gates, in-memory git capture, session handoff.
"""

from code_engineering.apply import apply_gate, patch_guard
from code_engineering.change.capture import (
    capture,
    extract_added_identifiers,
    parse_diff_ranges,
    parse_two_sided_spans,
    render_change_index,
)
from code_engineering.git import capture_change, extract_pr_url, parse_pr_url
from code_engineering.handoff import write_session_handoff
from code_engineering.plan_md import (
    declared_source_files,
    list_plan_files,
    resolve_active_plan,
    test_section,
    unfinished_todos,
)

__all__ = [
    "apply_gate",
    "capture",
    "capture_change",
    "declared_source_files",
    "list_plan_files",
    "extract_pr_url",
    "parse_diff_ranges",
    "parse_pr_url",
    "parse_two_sided_spans",
    "extract_added_identifiers",
    "render_change_index",
    "patch_guard",
    "resolve_active_plan",
    "test_section",
    "unfinished_todos",
    "write_session_handoff",
]
