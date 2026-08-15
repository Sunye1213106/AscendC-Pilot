# -*- coding: utf-8 -*-
"""Can we actually *evaluate* kernel-side compile-time dispatch, not just count it?
Checks three things:
  1. are `if constexpr` statements distinguishable from ordinary `if`?
  2. does clang instantiate the FAG kernel class templates (so NTTPs are bound)?
  3. can a constexpr condition be folded to a concrete value?"""
import collections
import probe_kernel as P
from clang import cindex
from measure import EXTRA, PRELUDE, QUALS2

TARGET = P.KDIR + r"\flash_attention_score_grad_apt.cpp"


def main():
    args = list(P.ARGS) + ["-I" + p for p in EXTRA] + [f"-D{q}=" for q in QUALS2]
    args += ["-include", PRELUDE]
    tu = cindex.Index.create().parse(TARGET, args=args)

    n_if = n_ifce = 0
    folded = 0
    fold_samples = []
    unfolded_samples = []
    insts = []
    nttp_bound = []

    for n in tu.cursor.walk_preorder():
        f = n.location.file
        if f is None or "flash_attention_score_grad" not in f.name:
            continue

        if n.kind == cindex.CursorKind.IF_STMT:
            n_if += 1
            toks = [t.spelling for t in n.get_tokens()][:2]
            if toks[:2] == ["if", "constexpr"]:
                n_ifce += 1
                kids = list(n.get_children())
                if kids:
                    cond = kids[0]
                    txt = "".join(t.spelling for t in cond.get_tokens())[:70]
                    try:
                        r = cond.evaluate()
                        kind = r.kind
                    except Exception:
                        kind = None
                    if kind is not None and int(kind.value) != 0:  # 0 == Unexposed
                        folded += 1
                        if len(fold_samples) < 6:
                            fold_samples.append((txt, r.kind.name, r.value))
                    elif len(unfolded_samples) < 6:
                        unfolded_samples.append(txt)

        # template instantiations: a ClassDecl whose semantic parent chain came
        # from a template shows up with a specialised display name
        if n.kind in (cindex.CursorKind.CLASS_DECL, cindex.CursorKind.STRUCT_DECL):
            dn = n.displayname or ""
            if "<" in dn and n.is_definition():
                insts.append(dn[:80])
        if n.kind == cindex.CursorKind.TEMPLATE_NON_TYPE_PARAMETER:
            nttp_bound.append((n.spelling, n.type.spelling))

    print("=" * 74)
    print(f"if total          : {n_if}")
    print(f"  of which constexpr: {n_ifce}")
    print(f"  condition folded to a constant: {folded} / {n_ifce}")
    print()
    print("folded samples:")
    for t, k, v in fold_samples:
        print(f"   [{k}={v}]  {t}")
    print()
    print("NOT folded samples:")
    for t in unfolded_samples:
        print(f"   {t}")
    print()
    print(f"specialised class definitions seen: {len(insts)}")
    for d in sorted(set(insts))[:8]:
        print("   ", d)
    print()
    c = collections.Counter(t for _, t in nttp_bound)
    print(f"non-type template params declared: {len(nttp_bound)}  by type: {dict(c)}")


if __name__ == "__main__":
    main()
