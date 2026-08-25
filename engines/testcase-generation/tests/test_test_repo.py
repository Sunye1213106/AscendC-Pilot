# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from testcase_agent import test_repo as TR

REPO = Path(__file__).resolve().parents[3]
FIXTURE = REPO / "tests" / "fixtures" / "_generic_test_repo"


def test_scan_empty_is_default_input():
    inv = TR.scan("")
    assert inv["kind"] == "default_input"
    doc = TR.contract_from_inventory(inv, knob_defaults={"n": 4, "dtype": "fp16"})
    assert doc["kind"] == "default_input"
    row = TR.fill_row(doc, name="default_input")
    assert row["n"] == "4"
    assert row["dtype"] == "fp16"


def test_scan_generic_repo_finds_entry_and_csv():
    inv = TR.scan(FIXTURE)
    assert inv["kind"] == "script_repo"
    assert any(str(e.get("path") or "").endswith("run_op.py") for e in inv["entries"])
    assert any(str(t.get("path") or "").endswith("cases.csv") for t in inv["tables"])
    doc = TR.contract_from_inventory(
        inv,
        host_fields=["dtype"],
        key_dims=["n"],
    )
    assert doc["kind"] == "script_repo"
    assert doc["entry"].endswith("run_op.py")
    assert doc["case_arg"] == "--case"
    assert "--mode" in doc["modes"]["precision"]
    assert "dtype" in doc["columns"]
    row = TR.fill_row(doc, {"dtype": "bf16"}, name="generated")
    assert row["dtype"] == "bf16"
    assert row["Testcase_Name"] == "generated"


def test_cross_check_flags_unmapped_columns():
    inv = TR.scan(FIXTURE)
    doc = TR.contract_from_inventory(inv, host_fields=[], key_dims=[])
    codes = {f["code"] for f in doc["findings"]}
    assert "unmapped_column" in codes


def test_cross_check_flags_missing_key_dim_column():
    inv = TR.scan(FIXTURE)
    doc = TR.contract_from_inventory(inv, host_fields=["dtype"], key_dims=["SplitAxis"])
    codes = {f["code"] for f in doc["findings"]}
    assert "missing_column" in codes
    row = TR.fill_row(doc, {"dtype": "fp16", "SplitAxis": "1"}, name="generated")
    assert row["dtype"] == "fp16"
    assert "SplitAxis" not in row


def test_scan_column_profile_has_stats_and_truncates_long_uniques(tmp_path: Path):
    root = tmp_path / "repo"
    (root / "data").mkdir(parents=True)
    lines = ["Testcase_Name,D,Layout,tiling_key,empty_col,tags"]
    lines.append('keep,1,TND,1,,"[a]"')
    lines.append("# comment,999,BNSD,0,,")
    lines.append(",16,TND,2,,")  # empty Testcase_Name skipped
    for i in range(80):
        lines.append(f'case_{i},{16 if i % 2 == 0 else 32},TND,{1000 + i},,"[a,b]"')
    (root / "data" / "cases.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (root / "run_op.py").write_text(
        "import argparse\n"
        "p = argparse.ArgumentParser()\n"
        "p.add_argument('--case')\n"
        "if __name__ == '__main__':\n"
        "    p.parse_args()\n",
        encoding="utf-8",
    )
    inv = TR.scan(root)
    table = next(t for t in inv["tables"] if str(t.get("path") or "").endswith("cases.csv"))
    profile = table["profile"]
    cols = profile["columns"]
    assert profile["n_rows"] == 81  # keep + 80 numbered; comment + empty name skipped
    assert cols["D"]["inferred_type"] == "int"
    assert cols["D"]["n_unique"] >= 2
    assert cols["D"]["min"] == 1
    assert cols["D"]["max"] == 32
    assert cols["D"]["topk"]
    assert cols["Layout"]["inferred_type"] == "enum-string"
    assert cols["empty_col"]["inferred_type"] == "empty-heavy"
    assert cols["tags"]["inferred_type"] == "list-literal"
    assert cols["tiling_key"]["n_unique"] > 64
    assert cols["tiling_key"].get("unique_truncated") is True
    assert len(cols["tiling_key"]["topk"]) <= 4
    doc = TR.contract_from_inventory(inv)
    assert doc["column_profile"]["n_rows"] == 81
    assert "D" in doc["column_profile"]["columns"]


def test_modes_candidates_come_from_entry_not_sidecar_help(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "run_x.py").write_text(
        "import argparse\n"
        "p = argparse.ArgumentParser()\n"
        "p.add_argument('--case')\n"
        "p.add_argument('--pta_mode', choices=['only_grad', 'profiler', 'auto_grad'])\n"
        "if __name__ == '__main__':\n"
        "    p.parse_args()\n",
        encoding="utf-8",
    )
    (root / "show_prof.py").write_text(
        "import argparse\n"
        "p = argparse.ArgumentParser(description='wait for profiler dump')\n"
        "p.add_argument('--wait', help='wait until profiler file appears')\n"
        "if __name__ == '__main__':\n"
        "    p.parse_args()\n",
        encoding="utf-8",
    )
    (root / "cases.csv").write_text("Testcase_Name,Dtype\na,fp16\n", encoding="utf-8")
    inv = TR.scan(root)
    doc = TR.contract_from_inventory(inv)
    precision = " ".join(str(x) for x in (doc.get("modes") or {}).get("precision") or [])
    perf = " ".join(str(x) for x in (doc.get("modes") or {}).get("perf") or [])
    assert "--wait" not in precision
    assert "--wait" not in perf
    candidates = doc.get("mode_candidates") or (doc.get("modes") or {}).get("candidates") or []
    flags = [str(row.get("flag") or row) for row in candidates] if candidates and isinstance(candidates[0], dict) else [str(x) for x in candidates]
    assert any("pta_mode" in f for f in flags)
    assert not any("wait" in f for f in flags)


def test_scan_canonical_call_prefers_precision_over_profiler(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "cases.csv").write_text("Testcase_Name,Dtype\na,fp16\n", encoding="utf-8")
    (root / "runner.py").write_text(
        "import torch_npu\n"
        "def run(pta_mode, q, k, v, dx, Nq):\n"
        "    if pta_mode == 'only_grad':\n"
        "        torch_npu.npu_fusion_attention_grad_v2(\n"
        "            q, k, v, dx, Nq, keep_prob=0.9, input_layout='BSH',\n"
        "            query_rope=q, key_rope=k, scale_value=1.0,\n"
        "        )\n"
        "    else:\n"
        "        with torch_npu.profiler.profile():\n"
        "            torch_npu.npu_fusion_attention_grad(q, k, v, dx, Nq, keep_prob=0.9)\n",
        encoding="utf-8",
    )
    (root / "run_op.py").write_text(
        "import argparse\n"
        "p = argparse.ArgumentParser()\n"
        "p.add_argument('--case')\n"
        "if __name__ == '__main__':\n"
        "    p.parse_args()\n",
        encoding="utf-8",
    )
    inv = TR.scan(root)
    call = inv.get("canonical_call") or {}
    assert call.get("kind") == "pta"
    assert "npu_fusion_attention_grad_v2" in str(call.get("api") or "")
    assert str(call.get("site") or "").endswith("runner.py:4")
    assert "keep_prob" in (call.get("args") or [])
    contract = TR.contract_from_inventory(inv)
    assert contract.get("canonical_call", {}).get("api") == call.get("api")


def test_scan_fag_canonical_call_site() -> None:
    fag = Path(r"d:\PR-review\pr_workspace\.ascendc-harness\gitcode.com--coder_linx--fag_debug_tools")
    if not fag.is_dir():
        return
    inv = TR.scan(fag)
    call = inv.get("canonical_call") or {}
    assert call.get("kind") == "pta"
    assert "npu_fusion_attention_grad_v2" in str(call.get("api") or "")
    assert "runner.py:333" in str(call.get("site") or "")
