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


def test_prune_common_rejects_unique_basename_only(tmp_path: Path) -> None:
    from uo.scripts.macro_scope_scan import _prune_common_by_includes

    workspace = tmp_path / "ws"
    op = workspace / "DemoOp"
    common = workspace / "common" / "op_kernel"
    op.mkdir(parents=True)
    common.mkdir(parents=True)
    (op / "k.cpp").write_text('#include "pse.h"\n', encoding="utf-8")
    # Only basename match available — must NOT select (would false-hit sibling libs).
    (common / "pse.h").write_text("// other lib\n", encoding="utf-8")
    selected = _prune_common_by_includes(
        workspace,
        ["DemoOp/k.cpp"],
        ["common/op_kernel/pse.h"],
    )
    assert selected == []


def test_prune_common_accepts_suffix_path(tmp_path: Path) -> None:
    from uo.scripts.macro_scope_scan import _prune_common_by_includes

    workspace = tmp_path / "ws"
    op = workspace / "DemoOp"
    common = workspace / "common" / "op_kernel" / "arch35"
    op.mkdir(parents=True)
    common.mkdir(parents=True)
    (op / "k.cpp").write_text('#include "common/op_kernel/arch35/pse.h"\n', encoding="utf-8")
    (common / "pse.h").write_text("// ok\n", encoding="utf-8")
    selected = _prune_common_by_includes(
        workspace,
        ["DemoOp/k.cpp"],
        ["common/op_kernel/arch35/pse.h"],
    )
    assert selected == ["common/op_kernel/arch35/pse.h"]


def test_common_scope_gate_requires_common_paths() -> None:
    from uo.scripts.review_checkpoint import _require_common_in_confirmed

    scan = {"common_rel": "common", "files": {}}
    try:
        _require_common_in_confirmed(scan, [{"path": "DemoOp/a.cpp"}])
        assert False, "expected SystemExit"
    except SystemExit as exc:
        assert "COMMON_SCOPE_REQUIRED" in str(exc)

    _require_common_in_confirmed(scan, [{"path": "common/op_kernel/x.h"}, {"path": "DemoOp/a.cpp"}])


def test_infer_key_field_role_needs_binding_without_invented_columns() -> None:
    from uo.scripts.kb_query_export import _infer_key_field_role

    drop = _infer_key_field_role("IsDrop")
    assert drop["role"] == "optional_presence"
    assert drop["csv_determinants"] == []
    assert drop.get("needs_binding") is True

    pse = _infer_key_field_role("IsPse")
    assert pse["csv_determinants"] == []
    assert pse.get("needs_binding") is True

    tnd = _infer_key_field_role("IsTnd")
    assert tnd["role"] == "layout_flag"
    assert tnd["csv_determinants"][0]["column"] == "input_layout"


def test_merge_human_facts_supplements(tmp_path: Path) -> None:
    from uo.scripts.kb_query_export import _merge_human_facts_supplements
    from uo.scripts._ir_io import write_yaml

    uo = tmp_path / ".understand-operator" / "Demo"
    (uo / "supplements").mkdir(parents=True)
    write_yaml(
        uo / "supplements" / "human_facts.yaml",
        {
            "notes": "confirmed binding",
            "key_determinants": {
                "KEY_ISDROP": {
                    "role": "optional_presence",
                    "csv_determinants": [{"column": "keep_prob", "op": "ne", "value": 1}],
                    "needs_binding": False,
                }
            },
        },
    )
    contract = {
        "key_determinants": {
            "KEY_ISDROP": {"role": "optional_presence", "csv_determinants": [], "needs_binding": True}
        }
    }
    merged = _merge_human_facts_supplements(uo, contract)
    dets = merged["key_determinants"]["KEY_ISDROP"]
    assert dets["csv_determinants"][0]["column"] == "keep_prob"
    assert dets.get("needs_binding") is False
    assert merged.get("supplement_notes")


def test_arch_filter_keeps_common_arch_match() -> None:
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

def test_prune_common_normalizes_relative_common_include(tmp_path: Path) -> None:
    from uo.scripts.macro_scope_scan import _prune_common_by_includes

    workspace = tmp_path / "ws"
    op = workspace / "DemoOp" / "op_kernel" / "arch35"
    common = workspace / "common" / "op_kernel" / "arch35"
    op.mkdir(parents=True)
    common.mkdir(parents=True)
    (op / "k.cpp").write_text('#include "../../../../common/op_kernel/arch35/pse.h"\n', encoding="utf-8")
    (common / "pse.h").write_text("// ok\n", encoding="utf-8")
    selected = _prune_common_by_includes(
        workspace,
        ["DemoOp/op_kernel/arch35/k.cpp"],
        ["common/op_kernel/arch35/pse.h"],
    )
    assert selected == ["common/op_kernel/arch35/pse.h"]


def test_candidate_paths_hard_bound_op_prefix() -> None:
    from uo.scripts.macro_scope_scan import _candidate_paths

    all_files = [
        "DemoOp/op_host/a.cpp",
        "DemoOp/op_kernel/k.cpp",
        "SiblingOp/op_host/b.cpp",
        "SiblingOp/op_kernel/attention_helper.cpp",
        "common/op_kernel/x.h",
    ]
    matched = _candidate_paths(Path("."), "flash_attention_score_grad", all_files, [], op_rel_prefix="DemoOp")
    assert "DemoOp/op_host/a.cpp" in matched
    assert "DemoOp/op_kernel/k.cpp" in matched
    assert "SiblingOp/op_host/b.cpp" not in matched
    assert "SiblingOp/op_kernel/attention_helper.cpp" not in matched
    assert "common/op_kernel/x.h" not in matched  # common via prune only


def test_replace_initial_scope_changes() -> None:
    from uo.scripts.review_checkpoint import _scope_changes
    import argparse

    ns = argparse.Namespace(
        include=["old/a.cpp"],
        replace_initial=["DemoOp/a.cpp", "common/x.h"],
        exclude=[],
        approve_dependency=[],
        reject_dependency=[],
        approve_architecture=[],
        exclude_architecture=[],
        resolve_uncertain=[],
    )
    changes = _scope_changes(ns)
    assert changes["replaced_initial"] == ["DemoOp/a.cpp", "common/x.h"]


def test_propagate_empty_tensor_siblings(tmp_path: Path) -> None:
    repo = tmp_path / "op"
    repo.mkdir()
    root = operator_root(repo, "DemoOp")
    init_operator_contract_layout(root, "DemoOp", repo)
    ir = root / "ir"
    ir.mkdir(parents=True, exist_ok=True)
    items = [
        {
            "id": "DIAG_MISSING_FORMERDKNUM",
            "kind": "missing_tiling_field_producer",
            "snippet": "formerDkNum",
        },
        {
            "id": "DIAG_MISSING_FORMERDQNUM",
            "kind": "missing_tiling_field_producer",
            "snippet": "formerDqNum",
        },
        {
            "id": "DIAG_UNUSED_S1TAIL",
            "kind": "unused_tiling_field",
            "snippet": "s1Tail",
        },
        {
            "id": "DIAG_UNUSED_S2INNER",
            "kind": "unused_tiling_field",
            "snippet": "s2Inner",
        },
    ]
    (ir / "operator_graph.yaml").write_text(
        yaml.safe_dump({"version": 1, "op_name": "DemoOp", "nodes": [{"id": "N1"}], "unresolved": items}, sort_keys=False),
        encoding="utf-8",
    )
    (ir / "unresolved.yaml").write_text(
        yaml.safe_dump({"version": 1, "op_name": "DemoOp", "items": items}, sort_keys=False),
        encoding="utf-8",
    )
    graph = apply_resolution(
        repo,
        "DemoOp",
        {
            "version": 1,
            "unresolved_resolutions": [
                {
                    "id": "DIAG_MISSING_FORMERDKNUM",
                    "status": "resolved",
                    "rationale": "EmptyTensor path",
                    "resolution": {"kind": "label", "label": "empty_tensor_tiling_producer", "evidence": "t.cpp:1"},
                },
                {
                    "id": "DIAG_UNUSED_S1TAIL",
                    "status": "accepted",
                    "rationale": "host reserved",
                },
            ],
        },
        propagate=True,
    )
    assert graph["unresolved"] == []
    assert int(graph["resolution"]["propagated_count"]) >= 2
    ledger = yaml.safe_load((ir / "resolution_ledger.yaml").read_text(encoding="utf-8"))
    ids = {row["id"] for row in ledger["items"]}
    assert ids == {i["id"] for i in items}
    assert ledger["open_unresolved_count"] == 0


def test_export_kb_graph_materializes_symbol_stubs(tmp_path: Path) -> None:
    from uo.scripts.export_kb_graph import _collect_relations

    uo = tmp_path / ".understand-operator" / "Demo"
    uo.mkdir(parents=True)
    entities = [
        {
            "id": "N1",
            "kind": "Node",
            "label": "DoOpTiling",
            "layer": "host",
            "detail_ref": "",
            "file_path": "op_host/a.cpp",
            "start_line": 1,
            "fields": {},
        }
    ]
    graph = {"edges": []}
    rels = _collect_relations(uo, graph, entities)
    ids = {e["id"] for e in entities}
    assert "SYM::DoOpTiling" in ids
    assert "FILE::op_host/a.cpp" in ids
    assert any(r["type"] == "anchors_to_symbol" for r in rels)
    for r in rels:
        assert r["source_id"] in ids
        assert r["target_id"] in ids


def test_integrity_fails_on_open_unresolved(tmp_path: Path) -> None:
    from uo.scripts.check_kb_integrity import check_kb_integrity, map_rework_stage

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
                "nodes": [
                    {"id": "H1", "layer": "host", "node_type": "Host"},
                    {"id": "K1", "layer": "kernel", "node_type": "Kernel"},
                    {"id": "TK1", "layer": "bridge", "node_type": "TilingKey"},
                ],
                "edges": [],
                "unresolved": [{"id": "DIAG_X", "kind": "unused_tiling_field"}],
                "tilingkey": {"args_sel_count": 1},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (ir / "unresolved.yaml").write_text(
        yaml.safe_dump({"version": 1, "op_name": "DemoOp", "items": [{"id": "DIAG_X", "kind": "unused_tiling_field"}]}, sort_keys=False),
        encoding="utf-8",
    )
    (ir / "entrypoints.yaml").write_text(
        yaml.safe_dump(
            {
                "roles": {
                    "host_tiling_entry": {"status": "confirmed", "selected": {"name": "DoOpTiling"}},
                    "kernel_entry": {"status": "confirmed", "selected": {"name": "Kernel"}},
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    # minimal required exports for validate_kb
    for rel in (
        "contracts/testcase.yaml",
        "tiling/exhaustive_key_space.yaml",
        "tiling/coverage_model.yaml",
        "kernel/branches.yaml",
        "cross_layer/impact_graph.yaml",
    ):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("version: 1\n", encoding="utf-8")

    result = check_kb_integrity(repo, "DemoOp", write_outputs=True)
    assert result["status"] == "fail"
    assert result["open_unresolved_count"] == 1
    codes = {i["code"] for i in result["issues"]}
    assert "OPEN_UNRESOLVED" in codes
    assert map_rework_stage({"rework_stage": "residual_resolve"}) == "residual_resolve"
    assert (root / "checks" / "integrity.yaml").is_file()


def test_uo_kb_query_status_only_without_pattern(tmp_path: Path) -> None:
    from uo.scripts.uo_kb_query import main as kb_query_main

    repo = tmp_path / "op"
    repo.mkdir()
    root = operator_root(repo, "DemoOp")
    init_operator_contract_layout(root, "DemoOp", repo)
    (root / "indexes").mkdir(parents=True, exist_ok=True)
    # Missing sqlite → status missing, but CLI must accept --status-only alone
    rc = kb_query_main([str(repo), "--op-name", "DemoOp", "--status-only"])
    assert rc == 0


def test_strip_cbm_stage_path() -> None:
    from uo.scripts.export_kb_graph import _strip_cbm_stage_path

    raw = (
        ".understand-operator/Demo/cbm/index_stage/Demo/"
        "op_kernel/arch35/kernel.h"
    )
    assert _strip_cbm_stage_path(raw) == "op_kernel/arch35/kernel.h"
    assert _strip_cbm_stage_path("op_host/a.cpp") == "op_host/a.cpp"


def test_export_adds_entrypoint_entities(tmp_path: Path) -> None:
    from uo.scripts.export_kb_graph import _collect_entities
    from uo.scripts._ir_io import write_yaml

    uo = tmp_path / ".understand-operator" / "Demo"
    (uo / "ir").mkdir(parents=True)
    write_yaml(
        uo / "ir" / "operator_graph.yaml",
        {"version": 1, "op_name": "Demo", "nodes": [], "edges": []},
    )
    write_yaml(
        uo / "ir" / "entrypoints.yaml",
        {
            "roles": {
                "kernel_entry": {
                    "status": "confirmed",
                    "selected": {
                        "name": "FlashAttentionScoreGradKernel",
                        "file_path": (
                            ".understand-operator/Demo/cbm/index_stage/Demo/"
                            "op_kernel/arch35/flash_attention_score_grad_kernel.h"
                        ),
                        "start_line": 28,
                    },
                },
                "host_tiling_entry": {
                    "status": "confirmed",
                    "selected": {"name": "DoOpTiling", "file_path": "op_host/a.cpp", "start_line": 1},
                },
            }
        },
    )
    ents = _collect_entities(uo, {"nodes": [], "edges": []})
    by_id = {e["id"]: e for e in ents}
    assert "ENTRY::kernel_entry" in by_id
    assert by_id["ENTRY::kernel_entry"]["label"] == "FlashAttentionScoreGradKernel"
    assert by_id["ENTRY::kernel_entry"]["file_path"] == "op_kernel/arch35/flash_attention_score_grad_kernel.h"
    assert by_id["ENTRY::host_tiling_entry"]["label"] == "DoOpTiling"


def test_uo_kb_query_status_only_without_pattern(tmp_path: Path) -> None:
    from uo.scripts.uo_kb_query import main as kb_query_main

    repo = tmp_path / "op"
    repo.mkdir()
    root = operator_root(repo, "DemoOp")
    init_operator_contract_layout(root, "DemoOp", repo)
    (root / "indexes").mkdir(parents=True, exist_ok=True)
    # Missing sqlite → status missing, but CLI must accept --status-only alone
    rc = kb_query_main([str(repo), "--op-name", "DemoOp", "--status-only"])
    assert rc == 0


def test_strip_cbm_stage_path() -> None:
    from uo.scripts.export_kb_graph import _strip_cbm_stage_path

    raw = (
        ".understand-operator/Demo/cbm/index_stage/Demo/"
        "op_kernel/arch35/kernel.h"
    )
    assert _strip_cbm_stage_path(raw) == "op_kernel/arch35/kernel.h"
    assert _strip_cbm_stage_path("op_host/a.cpp") == "op_host/a.cpp"


def test_export_adds_entrypoint_entities(tmp_path: Path) -> None:
    from uo.scripts.export_kb_graph import _collect_entities
    from uo.scripts._ir_io import write_yaml

    uo = tmp_path / ".understand-operator" / "Demo"
    (uo / "ir").mkdir(parents=True)
    write_yaml(
        uo / "ir" / "operator_graph.yaml",
        {"version": 1, "op_name": "Demo", "nodes": [], "edges": []},
    )
    write_yaml(
        uo / "ir" / "entrypoints.yaml",
        {
            "roles": {
                "kernel_entry": {
                    "status": "confirmed",
                    "selected": {
                        "name": "FlashAttentionScoreGradKernel",
                        "file_path": (
                            ".understand-operator/Demo/cbm/index_stage/Demo/"
                            "op_kernel/arch35/flash_attention_score_grad_kernel.h"
                        ),
                        "start_line": 28,
                    },
                },
                "host_tiling_entry": {
                    "status": "confirmed",
                    "selected": {"name": "DoOpTiling", "file_path": "op_host/a.cpp", "start_line": 1},
                },
            }
        },
    )
    ents = _collect_entities(uo, {"nodes": [], "edges": []})
    by_id = {e["id"]: e for e in ents}
    assert "ENTRY::kernel_entry" in by_id
    assert by_id["ENTRY::kernel_entry"]["label"] == "FlashAttentionScoreGradKernel"
    assert by_id["ENTRY::kernel_entry"]["file_path"] == "op_kernel/arch35/flash_attention_score_grad_kernel.h"
    assert by_id["ENTRY::host_tiling_entry"]["label"] == "DoOpTiling"
