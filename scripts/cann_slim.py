# -*- coding: utf-8 -*-
"""Cut the extracted CANN tree down to what parsing an operator needs.

The installer unpacks about 1.4 GB, nearly all of it compiler binaries,
libraries and Python packages. This analysis never links or runs anything: it
parses C++, so the only thing it needs from the toolkit is headers.

What to keep is decided by the include paths in `spec/build_context.yaml`, not
by which headers one operator happened to pull in. Copying only the transitive
closure of one operator's includes would produce a tree that works for that
operator and fails confusingly on the next -- exactly the kind of specialisation
this repository is trying not to acquire.

    python scripts/cann_slim.py                 # trim, then verify
    python scripts/cann_slim.py --no-verify     # trim only
    python scripts/cann_slim.py --dry-run       # report what it would copy
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "engines" / "understand-operator" / "src"
sys.path.insert(0, str(SRC))

from uo_init import paths  # noqa: E402
from uo_init.paths import SLIM_MARKER  # noqa: E402

SPEC = ROOT / "engines" / "understand-operator" / "spec" / "build_context.yaml"

#: Verification parses one operator to confirm the copied headers resolve. Any
#: operator answers that question; this is just the one checked in.
VERIFY_OPERATOR = os.environ.get("UO_OPERATOR", "attention/flash_attention_score_grad")

#: Extensions that cannot be a header. Everything else under an include path is
#: kept, because the C++ standard library headers have no extension at all
#: (`vector`, `type_traits`) and a whitelist would silently drop them.
BINARY_SUFFIXES = {
    ".so", ".a", ".o", ".obj", ".dll", ".lib", ".dylib", ".exe", ".bin",
    ".pyc", ".pyo", ".pyd", ".whl", ".egg", ".zip", ".tar", ".gz", ".xz",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".pdf", ".mp4", ".ttf",
    ".json_bak", ".log",
}

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def include_paths_from_spec(cann_root: Path) -> list[Path]:
    """Every directory under the CANN root that the build context names."""
    import yaml

    raw = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    wanted: list[str] = []
    wanted += list(raw.get("sysroot_includes") or [])
    for section in ("host", "kernel"):
        block = raw.get(section) or {}
        wanted += list(block.get("includes") or [])
        for item in block.get("force_include") or []:
            wanted.append(item)

    out: list[Path] = []
    for entry in wanted:
        if "{cann_root}" not in entry:
            continue
        rel = entry.replace("{cann_root}/", "").replace("{cann_root}", "")
        rel = _PLACEHOLDER.sub("*", rel)
        out.append(cann_root / rel)
    return out


def platform_config_dirs(cann_root: Path) -> list[Path]:
    """`platform_config/*.ini` carries the SoC facts the variable model locks to.

    Not an include path, so the spec does not list it, but dropping it would
    make every platform-derived constant unknown.
    """
    found: list[Path] = []
    for path in cann_root.rglob("platform_config"):
        if path.is_dir():
            found.append(path)
    return found


def find_source() -> Path:
    """The full extracted tree to trim from.

    Deliberately not `paths.cann_root()`: that prefers an already-trimmed tree,
    which is the right answer for analysis and the wrong one here. Once `slim`
    existed, taking it as the source made the trim impossible to re-run.
    """
    found = paths.cann_root()
    candidates: list[Path] = []
    if found is not None:
        candidates += [found.parent / "pkg", found]
    candidates.append(Path("_cann") / "pkg")
    for candidate in candidates:
        if candidate.is_dir() and candidate.name != "slim":
            return candidate
    raise SystemExit(f"no full CANN tree to trim.\n{paths.explain()}")


def _is_probably_binary(path: Path) -> bool:
    if path.suffix.lower() in BINARY_SUFFIXES:
        return True
    try:
        with path.open("rb") as fh:
            return b"\0" in fh.read(8192)
    except OSError:
        return True


def copy_tree(
    src: Path, dst: Path, *, dry_run: bool, seen: set[Path]
) -> tuple[int, int, int]:
    """Copy the text files under `src`. Returns (files, bytes, skipped).

    `seen` spans every call because the spec's include paths nest: it names an
    `asc` directory and two directories inside it. Walking each independently
    reaches the same file more than once, which copied it repeatedly and, more
    misleadingly, reported a file count and size well above what landed on disk.
    """
    files = written = skipped = 0
    if not src.exists():
        return (0, 0, 0)
    for dirpath, dirnames, filenames in os.walk(src):
        here = Path(dirpath)
        # A junction inside the tree would be walked twice; the target is
        # already being copied under its real name.
        dirnames[:] = [d for d in dirnames if not (here / d).is_symlink()]
        for name in filenames:
            source = here / name
            relative = source.relative_to(src)
            target = dst / relative
            if target in seen:
                continue
            if _is_probably_binary(source):
                skipped += 1
                continue
            seen.add(target)
            files += 1
            written += source.stat().st_size
            if dry_run:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    return (files, written, skipped)


def verify(slim: Path) -> bool:
    """Parse an operator's host TUs against the trimmed tree, expecting no errors.

    Counts clang's own diagnostics rather than anything the analysis derives:
    the question is whether every `#include` still resolves from `slim` alone,
    and a missing header shows up as an error long before it changes a node
    count. Any operator will do.
    """
    from clang import cindex

    from uo_init.build_context import BuildContext

    ops = paths.ops_root()
    if ops is None:
        print("cannot verify: ops-transformer not found")
        return False
    op_dir = paths.op_dir(relative=VERIFY_OPERATOR)
    if op_dir is None:
        print(f"cannot verify: operator {VERIFY_OPERATOR} not found under {ops}")
        return False

    host = op_dir / "op_host"
    targets = sorted(host.glob("*.cpp")) + sorted((host / "arch35").glob("*.cpp"))
    if not targets:
        print(f"cannot verify: no host sources under {host}")
        return False

    ctx = BuildContext.load(
        cann_root=str(slim), ops_root=str(ops), op_dir=str(op_dir), arch_dir="arch35"
    )
    args = ctx.host_args()
    index = cindex.Index.create()
    total = 0
    for path in targets:
        tu = index.parse(str(path), args=args)
        errors = [d for d in tu.diagnostics if d.severity >= 3]
        total += len(errors)
        print(f"  {path.name}: {len(errors)} error(s)")
        for diag in errors[:5]:
            where = diag.location
            name = Path(where.file.name).name if where.file else "?"
            print(f"      {name}:{where.line} {diag.spelling}")
    return total == 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, default=None, help="extracted CANN tree")
    ap.add_argument("--dest", type=Path, default=None, help="trimmed tree")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-verify", action="store_true")
    args = ap.parse_args()

    source = args.source or find_source()
    dest = args.dest or source.parent / "slim"
    if dest.resolve() == source.resolve():
        raise SystemExit(
            f"source and destination are the same tree ({source}); "
            "pass --source to name the full extracted tree"
        )

    wanted = include_paths_from_spec(source) + platform_config_dirs(source)
    # A file named directly (force_include) rather than a directory.
    dirs = [p for p in wanted if p.is_dir()]
    loose = [p for p in wanted if p.is_file()]
    missing = [p for p in wanted if not p.exists()]

    print(f"source : {source}")
    print(f"dest   : {dest}")
    print(f"include paths named by the spec: {len(wanted)} "
          f"({len(dirs)} dirs, {len(loose)} files, {len(missing)} missing)")
    for path in missing:
        print(f"  missing: {path}")

    if not args.dry_run and dest.exists():
        marker = dest / SLIM_MARKER
        if marker.exists():
            marker.unlink()

    files = written = skipped = 0
    seen: set[Path] = set()
    for path in dirs:
        relative = path.relative_to(source)
        got = copy_tree(path, dest / relative, dry_run=args.dry_run, seen=seen)
        files += got[0]
        written += got[1]
        skipped += got[2]
    for path in loose:
        relative = path.relative_to(source)
        target = dest / relative
        if target in seen:
            continue
        seen.add(target)
        files += 1
        written += path.stat().st_size
        if not args.dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)

    before = sum(
        f.stat().st_size for f in source.rglob("*") if f.is_file() and not f.is_symlink()
    )
    print(f"\nkept   : {files} files, {written / 1e6:.1f} MB")
    print(f"skipped: {skipped} binary files")
    print(f"source tree was {before / 1e6:.1f} MB -> {100 * written / before:.1f}%")

    if args.dry_run:
        return 0
    if args.no_verify:
        print(f"\nnot verified; {SLIM_MARKER} not written, so nothing will use this tree")
        return 0

    print("\nverifying against the trimmed tree:")
    if verify(dest):
        # Parsing one operator cleanly does not prove the tree is complete --
        # it proves it covers that operator. What makes it reusable is having
        # copied everything the spec names, so the spec digest is the thing
        # worth pinning: a tree built from an older spec must not be picked up.
        (dest / SLIM_MARKER).write_text(
            json.dumps(
                {
                    "spec_digest": paths.spec_digest(),
                    "files": files,
                    "bytes": written,
                    "source": str(source),
                    "verified_operator": VERIFY_OPERATOR,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"ok - wrote {dest / SLIM_MARKER}")
        return 0
    print("verification FAILED; leaving the tree unmarked so it is not picked up")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
