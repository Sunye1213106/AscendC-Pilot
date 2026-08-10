import json
from pathlib import Path

from uo_init.store.reader import find_uo_product
from uo_init.tg_projection import legal_key_rows

op = Path("/work/ops-transformer/attention/flash_attention_score_grad")
p = find_uo_product(op, op_name="flash_attention_score_grad", architecture="arch35")
D = {int(r["tiling_key"]) for r in legal_key_rows(p)}
details = Path(
    "/mnt/d/PR-review/AscendC-Pilot/artifacts/fa-pr13/host_replay_details.jsonl"
)
hit: set[int] = set()
wit: set[int] = set()
rewrite_in: set[int] = set()
rewrite_out: set[int] = set()
for line in details.read_text(encoding="utf-8").splitlines():
    d = json.loads(line)
    a = int(d.get("actual") or 0)
    t = int(d.get("target") or 0)
    if d.get("verdict") == "HIT":
        hit.add(t)
    if d.get("ok") and a:
        wit.add(a)
        if d.get("verdict") == "REWRITE":
            if a in D:
                rewrite_in.add(a)
            else:
                rewrite_out.add(a)
R = hit | (wit & D)
rpath = op / ".ascendc-pilot" / "arch35" / "tg" / "closure" / "R.txt"
rpath.write_text("".join(f"{k}\n" for k in sorted(R)), encoding="utf-8")
summary = {
    "D": len(D),
    "HIT_targets": len(hit),
    "unique_actual_ok": len(wit),
    "actual_in_D": len(wit & D),
    "REWRITE_actual_in_D": len(rewrite_in),
    "REWRITE_actual_out_D": len(rewrite_out),
    "R_after_merge": len(R),
    "open_D_minus_R": len(D - R),
    "coverage_R_over_D": round(len(R) / len(D), 4) if D else 0.0,
}
out = Path("/mnt/d/PR-review/AscendC-Pilot/artifacts/fa-pr13/host_replay_r_merge.json")
out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False, indent=2))
