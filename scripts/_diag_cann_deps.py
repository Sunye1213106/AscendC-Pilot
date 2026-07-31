"""Which CANN headers a real host parse actually reads, and how big they are.

The package is thousands of files, but a translation unit only pulls in what it
includes. This reports the closure so we can judge whether vendoring a fixture
is feasible instead of depending on a local CANN install.
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

WORKSPACE = Path(os.environ.get("UO_WORKSPACE", ROOT.parent))
OP = Path(
    os.environ.get(
        "UO_OP_DIR", WORKSPACE / "TEST/ops-transformer/attention/flash_attention_score_grad"
    )
)
CANN = Path(os.environ.get("UO_CANN_ROOT", WORKSPACE / "_cann/pkg"))
OPS = Path(os.environ.get("UO_OPS_ROOT", WORKSPACE / "TEST/ops-transformer"))


def main() -> int:
    from clang import cindex

    from uo_init.build_context import BuildContext

    ctx = BuildContext.load(cann_root=str(CANN), ops_root=str(OPS), op_dir=str(OP))
    args = ctx.host_args()

    srcs = sorted((OP / "op_host" / "arch35").glob("*.cpp"))
    print(f"parsing {len(srcs)} host sources with {len(args)} args\n")

    groups: dict[str, list[Path]] = defaultdict(list)
    seen: set[str] = set()
    idx = cindex.Index.create()
    for src in srcs:
        tu = idx.parse(str(src), args=args)
        for inc in tu.get_includes():
            p = Path(inc.include.name)
            key = str(p).replace("\\", "/")
            if key in seen:
                continue
            seen.add(key)
            try:
                rel = p.resolve()
            except OSError:
                continue
            if str(rel).lower().startswith(str(CANN.resolve()).lower()):
                bucket = "CANN"
            elif str(rel).lower().startswith(str(OPS.resolve()).lower()):
                bucket = "OPS"
            else:
                bucket = "SYSTEM/OTHER"
            groups[bucket].append(rel)

    for bucket in ("CANN", "OPS", "SYSTEM/OTHER"):
        files = groups.get(bucket) or []
        size = sum(f.stat().st_size for f in files if f.is_file())
        print(f"{bucket:14} files={len(files):5}  {size/1024:9.0f} KiB")

    cann_files = sorted(groups.get("CANN") or [])
    print(f"\n--- CANN headers actually included ({len(cann_files)}) ---")
    for f in cann_files:
        try:
            rel = f.relative_to(CANN.resolve())
        except ValueError:
            rel = f
        print(f"  {f.stat().st_size/1024:8.1f} KiB  {rel}")

    tops: dict[str, int] = defaultdict(int)
    for f in cann_files:
        try:
            rel = f.relative_to(CANN.resolve())
            tops[rel.parts[0] if rel.parts else "?"] += f.stat().st_size
        except ValueError:
            pass
    print("\n--- by top-level dir ---")
    for k, v in sorted(tops.items(), key=lambda kv: -kv[1]):
        print(f"  {v/1024:9.0f} KiB  {k}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
