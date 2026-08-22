# Grade a live FAG parts/bind.yaml. Keys stay here, never in the skill.

from __future__ import annotations

from pathlib import Path

import yaml

ACTUAL = Path(
    r"D:/TEST/pr_workspace/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-9851/"
    r"attention/flash_attention_score_grad/.ascendc-pilot/arch35/runs/"
    r"RUN_20260822_135454_8f9307bd/actions/bind_init/parts/bind.yaml"
)

ROLE = {
    "Testcase_Name": {"script_meta"},
    "Enable": {"script_meta"},
    "Dtype": {"api_arg"},
    "out_dtype": {"api_arg", "feature"},
    "Input_Layout": {"api_arg"},
    "B": {"api_arg"},
    "N1": {"api_arg"},
    "N2": {"api_arg"},
    "S1": {"api_arg"},
    "S2": {"api_arg"},
    "D": {"api_arg"},
    "D_V": {"api_arg"},
    "Drop_Out_Possibility": {"api_arg"},
    "Pre_Tockens": {"api_arg"},
    "Next_Tockens": {"api_arg"},
    "Atten_mask_dtype": {"api_arg", "feature"},
    "Atten_mask_shape": {"api_arg", "feature"},
    "sparse_mode": {"api_arg"},
    "PSE_type": {"api_arg"},
    "PSE_shape": {"api_arg", "feature"},
    "seqlens_list_q": {"api_arg"},
    "seqlens_list_kv": {"api_arg"},
    "cu_seqlens_q": {"api_arg", "feature"},
    "cu_seqlens_kv": {"api_arg", "feature"},
    "eod": {"feature"},
    "same_as_input": {"api_arg", "feature"},
    "seed": {"api_arg"},
    "offset": {"api_arg"},
    "is_deter": {"feature"},
    "rope": {"feature", "api_arg"},
    "inner_drop": {"feature"},
    "is_sink": {"feature", "api_arg"},
    "prefix": {"api_arg"},
    "Actual_dq_pricision": {"result_sink"},
    "Actual_dk_pricision": {"result_sink"},
    "Actual_dv_pricision": {"result_sink"},
    "Actual_kernel_time_backward": {"result_sink"},
    "Actual_dq_Md5sum": {"result_sink"},
    "Actual_dk_Md5sum": {"result_sink"},
    "Actual_dv_Md5sum": {"result_sink"},
}

UO_OK = {
    "D": {"d"},
    "D_V": {"d1"},
    "B": {"b"},
    "N2": {"n2"},
    "S1": {"s1"},
    "S2": {"s2"},
    "N1": {"headnum", "head_num"},
    "Drop_Out_Possibility": {"keepprob", "keep_prob"},
    "prefix": {"prefix"},
    "Dtype": {""},
    "out_dtype": {""},
    "Pre_Tockens": {"pretokens", "pre_tokens", "s1token"},
    "Next_Tockens": {"nexttokens", "next_tokens", "s2token"},
    "seed": {"seed"},
    "offset": {"offset"},
    "sparse_mode": {"sparsemode", "sparse_mode"},
    "PSE_type": {"psetype", "pse_type"},
    "Input_Layout": {"inputlayout", "layout", "input_layout"},
    "seqlens_list_q": {"actualseqqlen", "actual_seq_qlen"},
    "cu_seqlens_q": {"actualseqqlen", "actual_seq_qlen", ""},
    "seqlens_list_kv": {"actualseqkvlen", "actual_seq_kvlen"},
    "cu_seqlens_kv": {"actualseqkvlen", "actual_seq_kvlen", ""},
    "inner_drop": {"dropmaskouter"},
    "eod": {""},
}

UO_BAN = {
    "D": {"scalevalue", "scale", "scale_value"},
    "seqlens_list_q": {"istnd", "dim=istnd"},
    "seqlens_list_kv": {"istnd", "dim=istnd"},
    "cu_seqlens_q": {"istnd", "dim=istnd"},
    "eod": {"b", "actualseqqlen", "s1", "d"},
    "inner_drop": {"keepprob", "keep_prob"},
    "N1": {"n2", "g"},
    "Dtype": {"inputdtype", "outdtype", "istnd"},
    "out_dtype": {"outdtype", "inputdtype", "istnd"},
    "prefix": {""},
}

MUST_EMPTY_UO = {
    "Testcase_Name",
    "Enable",
    "Actual_dq_pricision",
    "Actual_dk_pricision",
    "Actual_dv_pricision",
    "Actual_kernel_time_backward",
    "Actual_dq_Md5sum",
    "Actual_dk_Md5sum",
    "Actual_dv_Md5sum",
}


def _s(val) -> str:
    if val is None:
        return ""
    return str(val).strip().strip("'\"")


def grade(path: Path | None = None) -> dict[str, bool]:
    path = path or ACTUAL
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    mapping = doc.get("mapping") if isinstance(doc.get("mapping"), dict) else {}
    domains = doc.get("domains") if isinstance(doc.get("domains"), dict) else {}
    call = doc.get("call") if isinstance(doc.get("call"), dict) else {}
    call_args = doc.get("call_args") if isinstance(doc.get("call_args"), list) else []
    out: dict[str, bool] = {}
    out["call_kind_pta"] = _s(call.get("kind")) == "pta"
    out["call_api_v2"] = "npu_fusion_attention_grad" in _s(call.get("api"))
    scale_src = None
    for row in call_args:
        if isinstance(row, dict) and _s(row.get("name")) == "scale_value":
            scale_src = row.get("source_column")
            break
    out["scale_value_source_null"] = scale_src in (None, "", "null")
    filled = 0
    api = 0
    for name, row in mapping.items():
        if not isinstance(row, dict):
            continue
        role = _s(row.get("role"))
        uo = _s(row.get("uo_id"))
        if role:
            filled += 1
        if role == "api_arg":
            api += 1
        want_role = ROLE.get(name)
        if want_role:
            out[f"role:{name}"] = role in want_role
        if name in UO_OK:
            allowed = {x.lower() for x in UO_OK[name]}
            if role == "feature" and uo == "":
                out[f"uo:{name}"] = "" in allowed
            else:
                out[f"uo:{name}"] = uo.lower() in allowed
        if name in UO_BAN:
            banned = {x.lower() for x in UO_BAN[name]}
            out[f"ban:{name}"] = uo.lower() not in banned
        if name in MUST_EMPTY_UO:
            out[f"empty_uo:{name}"] = uo == ""
        if role == "feature":
            op = _s((domains.get(name) or {}).get("operator"))
            out[f"feat_op_empty:{name}"] = op == ""
        if role == "api_arg":
            op = _s((domains.get(name) or {}).get("operator"))
            cmp_ = _s((domains.get(name) or {}).get("compare"))
            if op == "":
                out[f"api_no_false_match:{name}"] = cmp_ != "match"
    out["all_roles_filled"] = filled >= 38
    out["has_api_args"] = api >= 12
    return out


def main() -> None:
    g = grade()
    passed = sum(1 for v in g.values() if v)
    failed = [k for k, v in g.items() if not v]
    print(f"{passed}/{len(g)}")
    for k, v in g.items():
        print(f"  {'PASS' if v else 'FAIL'} {k}")
    if failed:
        print("FAILED:", ", ".join(failed))


if __name__ == "__main__":
    main()
