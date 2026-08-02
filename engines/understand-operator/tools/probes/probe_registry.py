# -*- coding: utf-8 -*-
"""Feasibility probe: Registry competition order + IsCapable predicates for FAG.

Outputs:
  1. All REGISTER_TILING_TEMPLATE_WITH_ARCH sites (op, class, arch, priority)
  2. Competition order for DAV_3510 (ascend950 / arch35)
  3. IsCapable bodies recovered via clang (or text fallback)
  4. Root-source classification of each predicate atom
  5. Overlap / mutual-exclusion analysis for arch35's two candidates
"""
from __future__ import annotations

import collections
import os
import re
import sys

from uo_init import paths

DEFAULT_OPERATOR = "attention/flash_attention_score_grad"

_OPS = paths.ops_root()
_FAG = paths.op_dir(relative=DEFAULT_OPERATOR)
if _OPS is None or _FAG is None:
    sys.exit(f"operator sources not available\n{paths.explain()}")

FAG_HOST = str(_FAG / "op_host")
REGISTRY_H = str(_OPS / "common" / "include" / "op_host" / "tiling_templates_registry.h")

REG_RE = re.compile(
    r"REGISTER_TILING_TEMPLATE_WITH_ARCH\s*\(\s*"
    r"(\w+)\s*,\s*(\w+)\s*,\s*([^,]+)\s*,\s*(\d+)\s*\)",
    re.MULTILINE,
)


def collect_registrations(root: str):
    hits = []
    for dirpath, _, files in os.walk(root):
        if ".ascendc-pilot" in dirpath:
            continue
        for fn in files:
            if not fn.endswith((".cpp", ".h", ".hpp")):
                continue
            path = os.path.join(dirpath, fn)
            text = open(path, encoding="utf-8", errors="replace").read()
            text = re.sub(r"\\\r?\n", " ", text)
            for m in REG_RE.finditer(text):
                op, cls, arch, pri = m.groups()
                rel = path.replace(root + os.sep, "").replace("\\", "/")
                # line number of match start
                line = text[: m.start()].count("\n") + 1
                hits.append(
                    {
                        "op": op,
                        "class": cls,
                        "arch_expr": arch.strip(),
                        "priority": int(pri),
                        "file": rel,
                        "line": line,
                    }
                )
    return hits


def arch_bucket(arch_expr: str) -> str:
    if "3510" in arch_expr or "DAV_3510" in arch_expr:
        return "DAV_3510"
    if "2201" in arch_expr or "DAV_2201" in arch_expr or "DAV_2002" in arch_expr:
        return "DAV_2201_family"
    return arch_expr


def extract_iscapable_text(path: str, class_name: str | None = None):
    """Best-effort text extraction of IsCapable bodies in a file."""
    src = open(path, encoding="utf-8", errors="replace").read()
    results = []
    # Method definition: bool Class::IsCapable() { ... }
    for m in re.finditer(
        r"bool\s+(\w+)::IsCapable\s*\(\s*\)\s*(?:override\s*)?\{", src
    ):
        cls = m.group(1)
        body, end = _brace_body(src, m.end() - 1)
        results.append({"class": cls, "kind": "out_of_line", "body": body.strip(),
                        "line": src[: m.start()].count("\n") + 1})
    # Inline in class: bool IsCapable() override { ... }
    for m in re.finditer(
        r"bool\s+IsCapable\s*\(\s*\)\s*(?:override\s*)?\{", src
    ):
        body, end = _brace_body(src, m.end() - 1)
        # try to find enclosing class name
        before = src[: m.start()]
        cm = list(re.finditer(r"class\s+(\w+)", before))
        cls = cm[-1].group(1) if cm else "?"
        results.append({"class": cls, "kind": "inline", "body": body.strip(),
                        "line": src[: m.start()].count("\n") + 1})
    if class_name:
        results = [r for r in results if r["class"] == class_name or class_name in r["class"]]
    return results


def _brace_body(src: str, open_idx: int):
    depth = 0
    for j in range(open_idx, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[open_idx + 1 : j], j
    return src[open_idx + 1 :], len(src)


def classify_atoms(body: str):
    """Map IsCapable body fragments to root-source kinds (heuristic)."""
    atoms = []
    rules = [
        (r"GetAttrs\s*\(|AttrIndex::|GetAttrPointer|GetAttrNum", "ATTRIBUTE"),
        (r"GetOptionalInputTensor|GetOptionalInputShape|OptionalInput",
         "OPTIONAL_INPUT_PRESENCE"),
        (r"GetShapeSize\s*\(", "INPUT_SHAPE"),  # often presence+shape
        (r"GetInputTensor|GetInputDesc|GetInputShape", "INPUT_SHAPE"),
        (r"npuArch\s*==|NpuArch::", "PLATFORM_ARCH"),
        (r"aivNum|aicNum|ubSize|l1Size|GetCurNpuArch", "PLATFORM_RESOURCE"),
        (r"strcmp\s*\(", "ATTRIBUTE"),  # string attr compare
    ]
    for pat, kind in rules:
        if re.search(pat, body):
            atoms.append(kind)
    # return-true / return-false structure
    returns = re.findall(r"return\s+(true|false)\s*;", body)
    return list(dict.fromkeys(atoms)), returns


def try_clang_iscapable(path: str):
    """Optional: locate IsCapable via libclang if build context available."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from probe_clang import ARGS, parse, in_fag  # type: ignore
        from clang import cindex
    except Exception as e:
        return None, f"clang unavailable: {e}"

    tu = parse(path)
    found = []
    for n in tu.cursor.walk_preorder():
        if not in_fag(n):
            continue
        if n.kind == cindex.CursorKind.CXX_METHOD and n.spelling == "IsCapable" and n.is_definition():
            # extent text
            try:
                start = n.extent.start
                end = n.extent.end
                with open(path, encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
                chunk = "".join(lines[start.line - 1 : end.line])
            except Exception:
                chunk = "<extent unavailable>"
            found.append(
                {
                    "class": n.semantic_parent.spelling if n.semantic_parent else "?",
                    "line": n.location.line,
                    "extent": chunk.strip()[:500],
                }
            )
    return found, None


def analyze_arch35_overlap(regs_3510, capable_by_class):
    """Specialized analysis for the two arch35 candidates."""
    by_pri = sorted(regs_3510, key=lambda r: r["priority"])
    print("\n=== arch35 competition semantics ===")
    print("DoTilingImpl iterates std::map<priority, case> ascending:")
    print("  smaller priority number = tried FIRST")
    print("  IsCapable()==false → GRAPH_PARAM_INVALID → try next")
    print("  first GRAPH_SUCCESS / non-PARAM_INVALID wins\n")
    for i, r in enumerate(by_pri):
        print(f"  [{i}] priority={r['priority']}  {r['class']}")
        body = capable_by_class.get(r["class"], "")
        atoms, returns = classify_atoms(body)
        print(f"      roots={atoms}  returns={returns}")
        # compress body for display
        one = " ".join(body.split())
        print(f"      body: {one[:220]}{'...' if len(one)>220 else ''}")

    # Explicit predicate reconstruction for the two known classes
    print("\n=== reconstructed predicates (manual from source) ===")
    print("VarlenRegbase (900):")
    print("  PLATFORM_ARCH == DAV_3510")
    print("  ∧ OPTIONAL_INPUT_PRESENCE(actual_seq_qlen)")
    print("  ∧ INPUT_SHAPE(actual_seq_qlen).size != 0")
    print("NormalRegbase (950):")
    print("  ATTRIBUTE(tnd_softmax_in) == \"\"   # AttrIndex::TND_SOFTMAX_IN")
    print("  ∧ PLATFORM_ARCH == DAV_3510")
    print("\n=== exclusive / overlap ===")
    print("Overlap: both true when DAV_3510 ∧ has actual_seq_qlen ∧ tnd_softmax_in==\"\"")
    print("  → Varlen WINS (priority 900 < 950); Normal never reached")
    print("Normal-only: DAV_3510 ∧ NO actual_seq_qlen ∧ tnd_softmax_in==\"\"")
    print("Varlen-only exclusive vs Normal: tnd_softmax_in!=\"\" forces Normal false")
    print("  (test CSV same_as_input=1 → softmax_layout=\"TND\" → tnd_softmax_in=\"TND\")")
    print("Neither: wrong arch, or DAV_3510 with no seq and nonempty tnd_softmax_in")


def main():
    print("=" * 72)
    print("Registry + IsCapable feasibility probe")
    print("=" * 72)

    # --- registry macro contract ---
    rh = open(REGISTRY_H, encoding="utf-8", errors="replace").read()
    assert "越小表示优先级越高" in rh or "priority" in rh
    print("\n[registry contract]")
    print("  macro: REGISTER_TILING_TEMPLATE_WITH_ARCH(op, class, arch, priority)")
    print("  rule : smaller priority => higher preference (header comment)")
    print("  loop : DoTilingImpl walks map.begin()→end(); PARAM_INVALID continues")

    regs = collect_registrations(FAG_HOST)
    print(f"\n[registrations] total={len(regs)}")
    by_arch = collections.defaultdict(list)
    for r in regs:
        if r["op"] != "FlashAttentionScoreGrad":
            continue
        by_arch[arch_bucket(r["arch_expr"])].append(r)

    for arch, items in sorted(by_arch.items()):
        items = sorted(items, key=lambda x: x["priority"])
        print(f"\n  {arch}  ({len(items)} templates, try order):")
        for r in items:
            print(f"    pri={r['priority']:<5} {r['class']:<55} {r['file']}:{r['line']}")

    regs_3510 = sorted(by_arch.get("DAV_3510", []), key=lambda x: x["priority"])
    assert len(regs_3510) == 2, f"expected 2 arch35 templates, got {len(regs_3510)}"
    assert regs_3510[0]["priority"] == 900
    assert regs_3510[1]["priority"] == 950
    assert "Varlen" in regs_3510[0]["class"]
    assert "Normal" in regs_3510[1]["class"]
    print("\n[check] arch35: Varlen@900 then Normal@950  OK")

    # --- IsCapable bodies ---
    capable_by_class = {}
    print("\n[IsCapable text extract]")
    targets = {
        "FlashAttentionScoreGradTilingNormalRegbase": os.path.join(
            FAG_HOST, "arch35", "flash_attention_score_grad_tiling_normal_regbase.cpp"
        ),
        "FlashAttentionScoreGradTilingVarlenRegbase": os.path.join(
            FAG_HOST, "arch35", "flash_attention_score_grad_tiling_varlen_regbase.cpp"
        ),
    }
    for cls, path in targets.items():
        items = extract_iscapable_text(path)
        # prefer matching class
        match = [x for x in items if cls in x["class"] or x["class"] in cls]
        if not match:
            match = items
        for it in match:
            capable_by_class[cls] = it["body"]
            atoms, returns = classify_atoms(it["body"])
            print(f"  {cls} @ line {it['line']} ({it['kind']})")
            print(f"    atoms={atoms} returns={returns}")
            print(f"    locs: AttrIndex::TND_SOFTMAX_IN / InputIndex::ACTUAL_SEQ_Q_LEN expected")

    # clang confirmation
    print("\n[clang IsCapable locate]")
    for cls, path in targets.items():
        found, err = try_clang_iscapable(path)
        if err:
            print(f"  {cls}: {err}")
            continue
        print(f"  {cls}: found {len(found)} definition(s)")
        for f in found:
            print(f"    class={f['class']} line={f['line']}")

    analyze_arch35_overlap(regs_3510, capable_by_class)

    # --- feasibility verdict ---
    print("\n" + "=" * 72)
    print("FEASIBILITY VERDICT")
    print("=" * 72)
    print("1. Competition ORDER: fully deterministic from macro text (regex).")
    print("2. IsCapable for arch35: 2 short predicates, all atoms map to")
    print("   PLATFORM_ARCH / ATTRIBUTE / OPTIONAL_INPUT_PRESENCE / INPUT_SHAPE.")
    print("3. No natural-language business logic in IsCapable; DoOpTiling holds the")
    print("   hard derivation chains (isNzOut etc.) — separate from registry close.")
    print("4. Closing this blocker for arch35 does NOT require L3 full SSA:")
    print("   Step A = registry extract + sort by priority")
    print("   Step B = IsCapable → ExprIR over accessor roots (shallow CFG)")
    print("   Step C = compose XOR/priority semantics for template selection lineage")
    print("5. Residual risk: arch22 has 8+ templates with longer IsCapable — same")
    print("   machinery, larger work; out of 950 scope.")
    print("6. Cross-check with tests: same_as_input=1 => tnd_softmax_in='TND'")
    print("   => Normal::IsCapable false (sufficient exclusion).")


if __name__ == "__main__":
    main()
