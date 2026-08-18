from __future__ import annotations

import sqlite3
from pathlib import Path


def _minimal_uo(path: Path, *, arch: str = "arch35") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO meta(key,value) VALUES('schema','uo-codemap/v1')")
        conn.execute("INSERT INTO meta(key,value) VALUES('architecture',?)", (arch,))
        conn.execute("INSERT INTO meta(key,value) VALUES('op_name','flash_attention_score_grad')")
        conn.commit()
    finally:
        conn.close()


def test_uo_review_compaction_leaves_only_formal_product(tmp_path: Path) -> None:
    from ascendc_pilot.actions.uo_product_compaction import compact_reviewed_uo

    work = tmp_path / ".ascendc-pilot" / "arch35" / "uo"
    product = work / "flash_attention_score_grad.arch35.uo"
    _minimal_uo(product)
    (work / "ir").mkdir(parents=True)
    (work / "ir" / "operator_graph.yaml").write_text("nodes: []\n", encoding="utf-8")
    (work / "indexes").mkdir()
    (work / "indexes" / "kb_graph.sqlite").write_bytes(b"legacy")

    out = compact_reviewed_uo(tmp_path, {"ok": True, "verdict": "pass", "path": str(product)})
    assert out["ok"] is True, out
    assert product.is_file()
    assert work.is_dir()
    remaining = [p for p in work.rglob("*") if p.is_file()]
    assert remaining == [product]
    assert out["removed_files"] == 2


def test_effective_tg_io_contract_reads_only_binary_uo() -> None:
    # Importing actions installs the runtime overlay used by acp.
    import ascendc_pilot.actions  # noqa: F401
    from ascendc_pilot.actions.engines import OUTPUT_CONTRACT_PATHS
    from ascendc_pilot.workflows import WORKFLOWS

    assert OUTPUT_CONTRACT_PATHS["uo-commit-v1"] == ["uo/*.uo"]
    assert OUTPUT_CONTRACT_PATHS["uo-verify-v1"] == [
        "uo/checks/integrity.yaml",
        "uo/checks/quality.yaml",
    ]
    assert "uo-review-v1" not in OUTPUT_CONTRACT_PATHS

    # TG may read the durable product glob ``uo/*.uo`` only — not the YAML work tree.
    allowed_uo = {"uo/*.uo"}
    for workflow_id in ("tg-init", "tg-plan", "tg-solve"):
        for action in (WORKFLOWS.get(workflow_id) or {}).get("actions") or []:
            reads = [str(p) for p in (action.get("allowed_read_paths") or [])]
            bad = [
                p
                for p in reads
                if (p == "uo" or p == "uo/**" or p.startswith("uo/")) and p not in allowed_uo
            ]
            assert not bad, (workflow_id, action.get("id"), reads)
