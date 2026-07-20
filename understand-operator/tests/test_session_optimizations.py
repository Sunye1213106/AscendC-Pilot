from __future__ import annotations

from pathlib import Path

import yaml

from uo._operator.artifacts import init_operator_contract_layout, operator_root
from uo.scripts.apply_resolution import apply_resolution, _normalize_patch
from uo.scripts.reconcile_bridge import _is_non_tiling_key, _norm_key
from uo.scripts.extract_host_subgraph import FIELD_WRITE_RE, RECV_SETTER_RE, SET_FIELD_RE
from uo.scripts.extract_kernel_subgraph import (
    KERNEL_DERIVED_READ_RE,
    TILING_DATA_READ_RE,
    build_field_domain_payload,
    extract_field_enum_comparisons,
    parse_constexpr_block_domains,
    parse_enum_class_domains,
    resolve_declared_domain,
    FieldEnumUsage,
)
from uo.scripts.macro_scope_scan import _filter_architecture
from uo.scripts.stage_cbm_scope import _resolve_source, _workspace_root


def test_architecture_filter_drops_other_arch() -> None:
    paths = [
        "op_host/arch35/a.cpp",
        "op_host/arch22/b.cpp",
        "op_kernel/arch35/k.h",
        "op_api/x.cpp",
        "common/op_kernel/arch35/u.h",
        "common/op_kernel/arch22/u_old.h",
    ]
    kept = _filter_architecture(paths, "arch35", op_rel_prefix="DemoOp")
    assert "op_host/arch35/a.cpp" in kept
    assert "op_kernel/arch35/k.h" in kept
    assert "op_api/x.cpp" in kept
    assert "common/op_kernel/arch35/u.h" in kept
    assert "op_host/arch22/b.cpp" not in kept
    assert "common/op_kernel/arch22/u_old.h" not in kept


def test_bridge_filters_non_tiling_symbols() -> None:
    assert _is_non_tiling_key(_norm_key("ORIG_DTYPE_QUERY"))
    assert _is_non_tiling_key(_norm_key("g_coreType"))
    assert _is_non_tiling_key(_norm_key("MM_IDX"))
    assert _is_non_tiling_key(_norm_key("SPLIT_AXIS"))
    assert not _is_non_tiling_key(_norm_key("s1Inner"))
    assert not _is_non_tiling_key(_norm_key("formerDkNum"))


def test_normalize_legacy_resolutions_patch() -> None:
    patch = _normalize_patch(
        {
            "version": 1,
            "resolutions": [
                {"id": "DIAG_A", "decision": "resolve", "rationale": "ok"},
                {"id": "DIAG_B", "decision": "accept_warning", "rationale": "host only"},
                {"id": "DIAG_C", "decision": "false_positive", "rationale": "fp"},
            ],
        }
    )
    items = {item["id"]: item["status"] for item in patch["unresolved_resolutions"]}
    assert items["DIAG_A"] == "resolved"
    assert items["DIAG_B"] == "accepted"
    assert items["DIAG_C"] == "false_positive"


def test_normalize_residuals_warning_alias() -> None:
    patch = _normalize_patch(
        {
            "version": 1,
            "residuals": [
                {"id": "DIAG_A", "resolution": "warning", "rationale": "keep"},
                {"id": "DIAG_B", "resolution": "false_positive", "rationale": "fp"},
                {
                    "id": "DIAG_C",
                    "status": "resolved",
                    "rationale": "host writes",
                    "resolution": {"kind": "label", "label": "host_producer", "evidence": "a.cpp:1"},
                },
            ],
        }
    )
    items = {item["id"]: item for item in patch["unresolved_resolutions"]}
    assert items["DIAG_A"]["status"] == "accepted"
    assert items["DIAG_B"]["status"] == "false_positive"
    assert items["DIAG_C"]["status"] == "resolved"
    assert items["DIAG_C"]["resolution"]["kind"] == "label"


def test_apply_resolution_check_rejects_unknown_without_write(tmp_path: Path) -> None:
    repo = tmp_path / "op"
    repo.mkdir()
    root = operator_root(repo, "DemoOp")
    init_operator_contract_layout(root, "DemoOp", repo)
    ir = root / "ir"
    ir.mkdir(parents=True, exist_ok=True)
    unresolved_before = {
        "version": 1,
        "op_name": "DemoOp",
        "items": [{"id": "DIAG_A", "kind": "unused_tiling_field"}],
    }
    (ir / "operator_graph.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "op_name": "DemoOp",
                "nodes": [{"id": "N1", "name": "n"}],
                "unresolved": list(unresolved_before["items"]),
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (ir / "unresolved.yaml").write_text(yaml.safe_dump(unresolved_before, sort_keys=False), encoding="utf-8")
    result = apply_resolution(
        repo,
        "DemoOp",
        {
            "version": 1,
            "unresolved_resolutions": [
                {"id": "DIAG_A", "status": "false_positive", "rationale": "ok"},
                {"id": "DIAG_BOGUS", "status": "accepted", "rationale": "nope"},
            ],
        },
        dry_run=True,
    )
    assert result["resolution"]["applied_count"] == 1
    assert result["resolution"]["rejected_count"] == 1
    assert result["resolution"]["rejected"][0]["id"] == "DIAG_BOGUS"
    # Dry-run must not mutate unresolved.yaml
    remaining = yaml.safe_load((ir / "unresolved.yaml").read_text(encoding="utf-8"))
    assert [i["id"] for i in remaining["items"]] == ["DIAG_A"]


def test_apply_resolution_accepts_legacy_resolutions(tmp_path: Path) -> None:
    repo = tmp_path / "op"
    repo.mkdir()
    root = operator_root(repo, "DemoOp")
    init_operator_contract_layout(root, "DemoOp", repo)
    ir = root / "ir"
    ir.mkdir(parents=True, exist_ok=True)
    (ir / "operator_graph.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "op_name": "DemoOp",
                "nodes": [{"id": "N1", "name": "n"}],
                "unresolved": [
                    {"id": "DIAG_A", "kind": "unused_tiling_field"},
                    {"id": "DIAG_B", "kind": "missing_tiling_field_producer"},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (ir / "unresolved.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "op_name": "DemoOp",
                "items": [
                    {"id": "DIAG_A", "kind": "unused_tiling_field"},
                    {"id": "DIAG_B", "kind": "missing_tiling_field_producer"},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    graph = apply_resolution(
        repo,
        "DemoOp",
        {
            "version": 1,
            "resolutions": [
                {"id": "DIAG_A", "decision": "resolve", "rationale": "setter found"},
                {"id": "DIAG_B", "decision": "accept_warning", "rationale": "host intermediate"},
            ],
        },
    )
    remaining_ids = {item["id"] for item in graph.get("unresolved") or []}
    assert "DIAG_A" not in remaining_ids
    assert "DIAG_B" not in remaining_ids
    assert graph["resolution"]["applied_count"] == 2


def test_host_write_patterns_prefer_setters() -> None:
    body = """
    void SaveStuff() {
      blob_->set_coreNum(8);
      mid_.enableSwizzle = true;
      tilingData->s1Inner = 1;
    }
    """
    recv_fields = [f for _, f in RECV_SETTER_RE.findall(body)]
    setters = recv_fields + SET_FIELD_RE.findall(body)
    assert "coreNum" in setters
    # Intermediate assignment should not match tilingData-only FIELD_WRITE_RE
    assert "enableSwizzle" not in FIELD_WRITE_RE.findall(body)
    assert "s1Inner" in FIELD_WRITE_RE.findall(body)


def test_kernel_derived_not_tiling_data() -> None:
    cond = "bIdx >= constInfo.bSize * constInfo.commonConstInfo.n2G"
    assert TILING_DATA_READ_RE.findall(cond) == []
    derived = KERNEL_DERIVED_READ_RE.findall(cond)
    assert any("bSize" in d for d in derived)

    tiling_cond = "tilingData->s1s2BNGS1S2BaseParams.sparseMode == RIGHT_DOWN"
    assert TILING_DATA_READ_RE.findall(tiling_cond)


def test_enum_class_full_domain_and_branch_split() -> None:
    text = """
    enum class FooMode : uint32_t {
        NONE = 0,
        ALL,
        LEFT = 2,
        RIGHT = 3,
        BAND = 4,
        EXTRA = 5
    };
    """
    domains = parse_enum_class_domains(text)
    assert len(domains) == 1
    assert domains[0].names == ["NONE", "ALL", "LEFT", "RIGHT", "BAND", "EXTRA"]
    assert domains[0].entries[1].value == 1

    hits = extract_field_enum_comparisons(
        "info.fooMode == LEFT || info.fooMode == RIGHT || info.fooMode == BAND"
    )
    assert {h[0] for h in hits} == {"fooMode"}
    literals = {h[1] for h in hits}
    declared = resolve_declared_domain(literals, domains)
    assert declared is not None
    usage = FieldEnumUsage(field="fooMode", branch_literals=literals, declared=declared)
    payload = build_field_domain_payload(usage)
    assert payload["domain"] == ["NONE", "ALL", "LEFT", "RIGHT", "BAND", "EXTRA"]
    assert payload["domain_with_kernel_branch"] == ["BAND", "LEFT", "RIGHT"]
    assert payload["domain_without_kernel_branch"] == ["ALL", "EXTRA", "NONE"]
    assert any(e["name"] == "ALL" and e["has_kernel_branch"] is False for e in payload["domain_entries"])


def test_constexpr_block_enum_like_and_rejects_sizes() -> None:
    text = """
    constexpr uint32_t MODE_A = 0;
    constexpr uint32_t MODE_B = 1;
    constexpr uint32_t MODE_C = 2;

    constexpr uint16_t ALIGN_16 = 15;
    constexpr uint16_t ALIGN_32 = 31;
    constexpr uint16_t ALIGN_64 = 63;
    """
    domains = parse_constexpr_block_domains(text)
    names_sets = [set(d.names) for d in domains]
    assert {"MODE_A", "MODE_B", "MODE_C"} in names_sets
    assert not any("ALIGN_16" in s for s in names_sets)


def test_field_eq_supports_static_cast_scope() -> None:
    cond = "tilingData->base.kind == static_cast<uint8_t>(KindType::DENSE"
    hits = extract_field_enum_comparisons(cond)
    assert hits == [("kind", "DENSE")]


def test_stage_resolve_prefers_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    op = workspace / "DemoOp"
    common = workspace / "common" / "x.h"
    common.parent.mkdir(parents=True)
    common.write_text("// common\n", encoding="utf-8")
    (op / "op_host").mkdir(parents=True)
    host = op / "op_host" / "a.cpp"
    host.write_text("void f(){}\n", encoding="utf-8")

    scan = {"workspace_root": str(workspace), "project_root": str(op)}
    assert _workspace_root(op, scan) == workspace.resolve()
    assert _resolve_source(workspace, op, "common/x.h") == common.resolve()
    assert _resolve_source(workspace, op, "DemoOp/op_host/a.cpp") == host.resolve()
