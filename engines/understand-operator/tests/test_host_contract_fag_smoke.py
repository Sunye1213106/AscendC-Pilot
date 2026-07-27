"""FAG smoke：路径仅在测试侧；生产代码无算子名硬编码。

需要 TEST 仓：
  TEST/ops-transformer/attention/flash_attention_score_grad
  TEST/ops-transformer/attention/common

为控制耗时，仅纳入 Host 注册/tiling/key 声明相关种子文件。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from uo.scripts._ir_io import read_yaml, write_yaml
from uo.scripts.ascendc_macro_facts import extract_macro_facts
from uo.scripts.host_compile_context import extract_host_compile_context
from uo.scripts.host_configuration_builder import build_host_configuration
from uo.scripts.macro_entrypoint_projection import project_macro_facts_to_entrypoint
from uo.scripts.materialize_extract_plan_view import materialize_extract_plan_view
from uo.scripts.tiling_contract_builder import build_tiling_contract

_WORKSPACE = Path(__file__).resolve().parents[4]  # PR-review
_FAG = _WORKSPACE / "TEST" / "ops-transformer" / "attention" / "flash_attention_score_grad"
_COMMON = _WORKSPACE / "TEST" / "ops-transformer" / "attention" / "common"


def _fag_available() -> bool:
    return _FAG.is_dir() and (_FAG / "op_host").is_dir()


def _seed_files(repo: Path) -> list[Path]:
    """精选 Host/Key 种子，避免扫全量 kernel。"""
    seeds: list[Path] = []
    patterns = [
        "op_host/flash_attention_score_grad_def.cpp",
        "op_host/flash_attention_score_grad_tiling.cpp",
        "op_host/arch35/*.cpp",
        "op_host/arch35/*.h",
        "op_kernel/arch35/*template_tiling_key*.h",
        "op_host/arch22/flash_attention_score_grad_tiling_common.h",
    ]
    for pattern in patterns:
        seeds.extend(sorted(repo.glob(pattern)))
    # common：仅 tiling 相关头（若存在）
    if _COMMON.is_dir():
        for pattern in (
            "op_host/**/*tiling*.h",
            "op_host/**/*tiling*.cpp",
        ):
            seeds.extend(sorted(_COMMON.glob(pattern))[:20])
    # 去重、只要存在的文件
    unique: dict[str, Path] = {}
    for path in seeds:
        if path.is_file():
            unique[str(path.resolve()).casefold()] = path
    return list(unique.values())[:80]


@pytest.mark.skipif(not _fag_available(), reason="TEST FAG 算子目录不存在")
def test_fag_host_contract_smoke():
    repo = _FAG
    uo = repo / ".ascendc-pilot" / "uo"
    (uo / "ir").mkdir(parents=True, exist_ok=True)
    architecture = os.environ.get("UO_SMOKE_ARCH", "arch35")

    seeds = _seed_files(repo)
    assert seeds, "未找到 FAG Host/Key 种子文件"

    rel_files: list[str] = []
    for path in seeds:
        try:
            rel_files.append(str(path.resolve().relative_to(repo.resolve())).replace("\\", "/"))
        except ValueError:
            rel_files.append(str(path.resolve()))

    write_yaml(uo / "ir" / "scope_confirmed.yaml", {"confirmed_source_files": rel_files})
    run_scope = uo / "runs" / "smoke" / "scope"
    run_scope.mkdir(parents=True, exist_ok=True)
    write_yaml(run_scope / "scope_confirmed.yaml", {"confirmed_source_files": rel_files})

    if not (uo / "ir" / "operator_boundary.yaml").is_file():
        write_yaml(
            uo / "ir" / "operator_boundary.yaml",
            {
                "inputs": [{"name": "query", "index": 0}, {"name": "key", "index": 1}],
                "attributes": [{"name": "input_layout"}],
            },
        )
    if not (uo / "ir" / "entrypoint_graph.yaml").is_file():
        write_yaml(uo / "ir" / "entrypoint_graph.yaml", {"nodes": [], "edges": []})

    # 分步执行并显式传入 seed 文件，避免 fallback 全仓 rglob
    facts = extract_macro_facts(
        repo,
        "flash_attention_score_grad",
        architecture=architecture,
        uo_root=uo,
        source_files=seeds,
    )
    ctx = extract_host_compile_context(
        repo, "flash_attention_score_grad", architecture=architecture, uo_root=uo
    )
    facts = extract_macro_facts(
        repo,
        "flash_attention_score_grad",
        architecture=architecture,
        uo_root=uo,
        compile_context_id=str(ctx.get("compile_context_id") or ""),
        source_files=seeds,
    )
    project_macro_facts_to_entrypoint(
        repo,
        "flash_attention_score_grad",
        architecture=architecture,
        uo_root=uo,
        macro_facts=facts,
    )
    build_host_configuration(
        repo, "flash_attention_score_grad", architecture=architecture, uo_root=uo
    )
    tcg = build_tiling_contract(
        repo, "flash_attention_score_grad", architecture=architecture, uo_root=uo
    )
    materialize_extract_plan_view(
        repo, "flash_attention_score_grad", uo_root=uo
    )

    assert tcg.get("kb_status") == "partial"
    assert tcg.get("contract_status") == "producer_only"
    assert (uo / "ir" / "macro_facts.yaml").is_file()
    assert (uo / "ir" / "host_configuration_graph.yaml").is_file()
    assert (uo / "ir" / "tiling_contract_graph.yaml").is_file()

    macros = {i.get("macro") for i in facts.get("invocations") or []}
    assert (
        "REG_OP" in macros
        or "IMPL_OP_OPTILING" in macros
        or "REGISTER_TILING_TEMPLATE_WITH_ARCH" in macros
        or "REGISTER_TILING_TEMPLATE" in macros
    ), f"未识别 Host 注册宏，got={sorted(macros)[:20]}"

    kinds = {e.get("kind") for e in tcg.get("entities") or []}
    assert (
        "TilingSchema" in kinds
        or "TilingSchemaVariant" in kinds
        or "TilingField" in kinds
        or "FieldWrite" in kinds
    ), f"未识别 TilingData schema/写入，kinds={sorted(kinds)}"

    dims = (tcg.get("declared_key_space") or {}).get("dimensions") or []
    assert dims, "应识别 Key dimensions"
    assert [d.get("ordinal") for d in dims] == list(range(len(dims)))

    field_writes = [e for e in tcg.get("entities") or [] if e.get("kind") == "FieldWrite"]
    key_comps = [
        e
        for e in tcg.get("entities") or []
        if e.get("kind")
        in {"KeyReturnComposer", "ObservedKeyComposition", "KeyDimensionSelection"}
    ]
    assert field_writes or "TilingField" in kinds, "应至少识别 TilingData field/写入"
    assert key_comps or dims, "应至少识别 Key 组成或声明"

    from uo.scripts._ir_io import read_yaml as _ry

    hcg = _ry(uo / "ir" / "host_configuration_graph.yaml") or {}
    hcg_un = int((hcg.get("counts") or {}).get("unresolved") or len(hcg.get("unresolved") or []))
    tcg_un = int((tcg.get("counts") or {}).get("unresolved") or len(tcg.get("unresolved") or []))
    total_un = hcg_un + tcg_un
    limit = int(os.environ.get("UO_HOST_UNRESOLVED_LIMIT", "50"))
    skipped = int((hcg.get("counts") or {}).get("skipped_external_calls") or 0)
    print(
        f"[fag-smoke] hcg_unresolved={hcg_un} tcg_unresolved={tcg_un} "
        f"sum={total_un} skipped_external_calls={skipped} limit={limit}"
    )
    if total_un >= limit:
        from collections import Counter

        reasons = Counter(
            str(u.get("reason_code") or "?")
            for u in list(hcg.get("unresolved") or []) + list(tcg.get("unresolved") or [])
            if isinstance(u, dict)
        )
        print("[fag-smoke] top unresolved reasons:", reasons.most_common(12))
    assert total_un < limit, (
        f"Host 未闭合合计 {total_un} >= {limit} "
        f"(hcg={hcg_un}, tcg={tcg_un}, skipped_external={skipped})"
    )

    scripts = Path(__file__).resolve().parents[1] / "uo" / "scripts"
    for py in scripts.glob("host_contract*.py"):
        text = py.read_text(encoding="utf-8")
        assert "FlashAttentionScoreGrad" not in text
        assert "RegbaseFAG" not in text
    for name in (
        "ascendc_macro_facts.py",
        "tiling_contract_builder.py",
        "host_configuration_builder.py",
    ):
        text = (scripts / name).read_text(encoding="utf-8")
        assert "FlashAttentionScoreGrad" not in text
        assert "flash_attention_score_grad" not in text
