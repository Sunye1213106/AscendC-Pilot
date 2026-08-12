from __future__ import annotations

import time
from pathlib import Path

from uo_init.passes.kernel_scan import (
    _CXX_CALL_SKIP,
    _is_false_lexical_callee,
    _is_tpl_dsl_file,
    _strip_line_noise,
    lexical_source_call_sites,
)


def test_strip_line_noise_removes_copyright_call_shape() -> None:
    assert "Copyright" not in _strip_line_noise("Copyright (c) 2024 Example Corp.")
    assert "(c)" not in _strip_line_noise("Copyright (c) 2024 Example Corp.")


def test_cxx_call_skip_keeps_casts_not_constexpr() -> None:
    # Cast keywords are never AscendC callees; constexpr must NOT be blanket-skipped
    # because AscendC is compile-time / if-constexpr heavy.
    assert "static_cast" in _CXX_CALL_SKIP
    assert "constexpr" not in _CXX_CALL_SKIP


def test_if_constexpr_is_false_lexical_callee_not_skipped_concept() -> None:
    line = "    if constexpr (IS_ROPE) {"
    # match start of ``constexpr``
    idx = line.index("constexpr")
    assert _is_false_lexical_callee("constexpr", line, idx) is True


def test_tpl_dsl_file_matches_template_tiling_key() -> None:
    assert _is_tpl_dsl_file(Path("include/template_tiling_key.h"))


def test_lexical_calls_ignore_if_constexpr_and_copyright(tmp_path: Path) -> None:
    source = tmp_path / "tiny.cpp"
    source.write_text(
        """
Copyright (c) 2024 Example Corp.
void Kernel() {
  if constexpr (IS_ROPE) {
    RealCall(value);
  }
  static_cast<int>(value);
}
""",
        encoding="utf-8",
    )

    sites = lexical_source_call_sites(
        [source],
        reachable=set(),
        filter_strict=False,
        root=str(tmp_path),
        deadline=time.perf_counter() + 5,
    )
    callees = {str(site["callee"]) for site in sites}
    assert "c" not in callees
    assert "constexpr" not in callees
    assert "static_cast" not in callees
    assert "RealCall" in callees
