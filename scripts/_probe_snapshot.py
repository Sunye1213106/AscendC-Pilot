# -*- coding: utf-8 -*-
"""把一次运行的结论冻结下来, 好让下一次改动的每一处差异都必须被解释。

重构期间最容易发生的事是: 覆盖数字变了, 但没人说得清是修好了还是弄坏了。所以每
个阶段落一份快照, 四个集合各自成文件:

    witness_keys.txt    真实跑出来过的 key
    unreachable.yaml    被规则排除的 key, 连同是哪条规则排的
    unknown.txt         声明了、没排除、也没跑出来 —— 真正的缺口
    undeclared.txt      跑出来了但不在声明空间里 —— 要么模板漏声明, 要么解码错
    reachable_cases.csv 每个 witness key 对应的完整用例

判定口径是: witness 只增不减。少掉一个就是回归, 必须先解释再继续。

    python scripts/_probe_snapshot.py --tag S0
    python scripts/_probe_snapshot.py --tag S1 --against S0
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))


def _load(tag_dir: Path, name: str) -> set[int]:
    path = tag_dir / name
    if not path.is_file():
        return set()
    return {
        int(line.split()[0])
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", required=True, help="快照名, 例如 S0")
    ap.add_argument("--against", default="", help="和这个快照比")
    ap.add_argument("--corpus", default="*key_cases*.csv", help="语料 glob")
    args = ap.parse_args()

    import yaml

    from replay import runner as R
    from replay_closure_gate import load_declared, partition
    from replay_verdict import _witnesses

    seen: dict[int, dict] = {}
    sources: list[str] = []
    for p in sorted(R.CACHE.glob(args.corpus)):
        hits = _witnesses(p)
        if hits:
            sources.append(f"{p.name} ({len(hits)} keys)")
        for k, v in hits.items():
            seen.setdefault(k, v)
    if not seen:
        raise SystemExit(f"no witnesses under {R.CACHE} matching {args.corpus}")

    declared = load_declared()
    excluded, in_r, gap = partition(seen, declared)
    undeclared = sorted(k for k in seen if k not in declared)
    # A rule that excludes a key the host actually produced is the one failure
    # this whole scheme cannot absorb: the exclusion is wrong, not the run.
    conflicts = sorted(k for k in excluded if k in seen)

    out = R.CACHE / "snapshots" / args.tag
    out.mkdir(parents=True, exist_ok=True)

    (out / "witness_keys.txt").write_text(
        "\n".join(str(k) for k in sorted(seen)) + "\n", encoding="utf-8")
    (out / "unknown.txt").write_text(
        "\n".join(str(k) for k in sorted(gap)) + "\n", encoding="utf-8")
    (out / "undeclared.txt").write_text(
        "\n".join(str(k) for k in undeclared) + "\n", encoding="utf-8")
    (out / "unreachable.yaml").write_text(
        yaml.safe_dump({str(k): v for k, v in sorted(excluded.items())},
                       sort_keys=False, allow_unicode=True),
        encoding="utf-8")

    dims = [d.name for d in R.schema().dims]
    with (out / "reachable_cases.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["tiling_key"] + dims)
        for key in sorted(in_r):
            inst = in_r[key]
            w.writerow([key] + [inst.get(n, "") for n in dims])

    summary = {
        "tag": args.tag,
        "sources": sources,
        "declared": len(declared),
        "witness": len(seen),
        "reachable_declared": len(in_r),
        "excluded_by_rules": len(excluded),
        "unknown": len(gap),
        "undeclared_runtime": len(undeclared),
        "rule_conflicts": conflicts,
    }
    (out / "summary.yaml").write_text(
        yaml.safe_dump(summary, sort_keys=False, allow_unicode=True), encoding="utf-8")

    print(f"snapshot {args.tag} -> {out}")
    for k, v in summary.items():
        if k not in ("sources", "rule_conflicts"):
            print(f"  {k:<22}{v}")
    for s in sources:
        print(f"  source                {s}")
    if conflicts:
        print(f"\n  RULE CONFLICT: {len(conflicts)} key(s) excluded by a rule but "
              f"produced by a real run:")
        for k in conflicts[:10]:
            print(f"    {k}  excluded by {excluded[k]}")
        print("  每一条都说明那条规则是错的 —— 规则要撤, 不是把 witness 丢掉。")

    if args.against:
        base = R.CACHE / "snapshots" / args.against
        if not base.is_dir():
            raise SystemExit(f"no snapshot {args.against} at {base}")
        was = _load(base, "witness_keys.txt")
        lost = sorted(was - set(seen))
        gained = sorted(set(seen) - was)
        print(f"\nagainst {args.against}: witness {len(was)} -> {len(seen)}  "
              f"+{len(gained)}  -{len(lost)}")
        if lost:
            print(f"  LOST {len(lost)} witness key(s), first 10: {lost[:10]}")
            print("  witness 只能增不能减。先解释, 再继续。")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
