from __future__ import annotations

from pathlib import Path

from uo.scripts.extract_tilingkey_space import (
    _parse_template_aliases,
    extract_tilingkey_space,
)
from uo.scripts.resolve_entrypoints import (
    EXACT_PREFERRED,
    ROLE_PATTERNS,
    _exact_preferred_for_op,
    _role_patterns_for_op,
    _snake_to_pascal,
)


def test_kernel_entry_patterns_are_op_derived_not_fag_hardcoded() -> None:
    assert "FlashAttentionScoreGradKernel" not in ROLE_PATTERNS["kernel_entry"]
    assert "RegbaseFAG" not in ROLE_PATTERNS["kernel_entry"]
    assert "FlashAttentionScoreGradKernel" not in EXACT_PREFERRED["kernel_entry"]
    assert "RegbaseFAG" not in EXACT_PREFERRED["kernel_entry"]

    patterns = _role_patterns_for_op("flash_attention_score_grad")
    preferred = _exact_preferred_for_op("flash_attention_score_grad")
    assert "FlashAttentionScoreGradKernel" in patterns["kernel_entry"]
    assert "FlashAttentionScoreGrad" in patterns["kernel_entry"]
    assert preferred["kernel_entry"][0] == "FlashAttentionScoreGradKernel"

    other = _role_patterns_for_op("other_op")
    assert "OtherOpKernel" in other["kernel_entry"]
    assert "FlashAttentionScoreGradKernel" not in other["kernel_entry"]
    assert _snake_to_pascal("foo_bar_baz") == "FooBarBaz"


def test_parse_template_aliases_generic_with_param_names(tmp_path: Path) -> None:
    data_h = tmp_path / "op_tiling_data.h"
    data_h.write_text(
        """
template<const bool isFoo = false, const bool isBar = false>
class DemoTilingData {
};
""",
        encoding="utf-8",
    )
    key_h = tmp_path / "op_template_tiling_key.h"
    key_h.write_text(
        """
#include "op_tiling_data.h"
using DemoTilingWithTemplateFF = ns::DemoTilingData<false, false>;
using DemoTilingWithTemplateTF = ns::DemoTilingData<true, false>;
""",
        encoding="utf-8",
    )
    text = key_h.read_text(encoding="utf-8")
    aliases = _parse_template_aliases(text, "op_template_tiling_key.h", header=key_h)
    assert len(aliases) == 2
    assert aliases[0]["flags"] == {"isFoo": False, "isBar": False}
    assert aliases[1]["flags"] == {"isFoo": True, "isBar": False}
    assert "isDeter" not in aliases[0]["flags"]
    assert "FagTiling" not in aliases[0]["name"]


def test_parse_template_aliases_positional_fallback(tmp_path: Path) -> None:
    key_h = tmp_path / "op_template_tiling_key.h"
    key_h.write_text(
        "using AliasTT = SomeClass<true, true>;\n",
        encoding="utf-8",
    )
    aliases = _parse_template_aliases(key_h.read_text(encoding="utf-8"), "x.h", header=key_h)
    assert aliases[0]["flags"] == {"arg0": True, "arg1": True}


def test_extract_tilingkey_space_on_synthetic_tree(tmp_path: Path) -> None:
    arch = tmp_path / "demo_op" / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (arch / "demo_op_tiling_data.h").write_text(
        """
template<const bool isDeter = false, const bool isTnd = false>
class DemoOpTilingData {
};
""",
        encoding="utf-8",
    )
    (arch / "demo_op_template_tiling_key.h").write_text(
        """
#include "demo_op_tiling_data.h"
using DemoTilingWithTemplateFF = DemoOpTilingData<false, false>;
ASCENDC_TPL_ARGS_DECL(DemoOp,
  ASCENDC_TPL_BOOL_DECL(IsDeter, 0, 1),
  ASCENDC_TPL_BOOL_DECL(IsTnd, 0, 1),
);
ASCENDC_TPL_ARGS_SEL(
  ASCENDC_TPL_BOOL_SEL(IsDeter, 0),
);
""",
        encoding="utf-8",
    )
    payload = extract_tilingkey_space(tmp_path, "demo_op", architecture="arch35")
    assert payload["status"] == "ok"
    assert payload["template_aliases"][0]["flags"] == {"isDeter": False, "isTnd": False}
    assert any(d["name"] == "IsDeter" for d in payload["dimensions"])


def test_host_extract_has_no_fag_closed_gates() -> None:
    """Host extractor must not use FAG-specific closed name sets as logic gates."""
    src = Path(__file__).resolve().parents[1] / "uo" / "scripts" / "extract_host_subgraph.py"
    text = src.read_text(encoding="utf-8").casefold()
    for banned in (
        "fbaseparams",
        "dopretiling",
        "pretilingdata",
        "writes_tiling_helpers",
        "keep_helpers",
        "host_intermediate_roots",
        "savetotilingdata",
    ):
        # Identifier-style gates only; comments mentioning history are ok if not as constants.
        assert f"{banned} =" not in text
        assert f"{banned} = " not in text
        assert f'"{banned}"' not in text
        assert f"'{banned}'" not in text
        assert f"{{{banned}" not in text
    # Closed frozenset/set name gates removed
    assert "writes_tiling_helpers" not in text
    assert "keep_helpers" not in text
    assert "host_intermediate_roots" not in text
