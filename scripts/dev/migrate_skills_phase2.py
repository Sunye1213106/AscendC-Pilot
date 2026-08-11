"""One-shot migrate domain skills → 4 top-level skills."""
from __future__ import annotations

import shutil
from pathlib import Path

root = Path(__file__).resolve().parents[2]
skills = root / "skills"
domain = skills / "domain"

mapping = {
    "operator-analysis": {
        "refs": [
            ("uo-codemap-build/references/authority-model.md", "codemap-authority.md"),
            ("uo-codemap-build/references/completeness.md", "codemap-completeness.md"),
            ("uo-codemap-build/references/extraction-quality.md", "codemap-extraction.md"),
            ("uo-codemap-build/references/gotchas.md", "codemap-build-gotchas.md"),
            ("uo-codemap-query/references/gotchas.md", "codemap-query-gotchas.md"),
        ],
    },
    "testcase-generation": {
        "refs": [
            ("tg-plan/references/coverage-obligations.md", "planning.md"),
            ("tg-plan/references/gotchas.md", "planning-gotchas.md"),
            ("tg-init/references/binding.md", "construction-binding.md"),
            ("tg-init/references/contract.md", "construction-contract.md"),
            ("tg-init/references/gotchas.md", "construction-gotchas.md"),
            ("tg-closure/references/certificate.md", "certificate.md"),
            ("tg-closure/references/closure-safety.md", "closure-safety.md"),
            ("tg-closure/references/failure-patterns.md", "failure-patterns.md"),
            ("tg-closure/references/oracle.md", "oracle.md"),
            ("tg-closure/references/search.md", "search.md"),
            ("tg-closure/references/gotchas.md", "closure-gotchas.md"),
        ],
        "examples": "tg-closure/examples",
    },
    "source-proof": {"copy_from": "source-lemma-proof"},
    "code-review": {"copy_from": "code-review"},
}

shared_dst = skills / "_shared"
if shared_dst.exists():
    shutil.rmtree(shared_dst)
shutil.copytree(domain / "_shared", shared_dst)

for skill_id, cfg in mapping.items():
    dst = skills / skill_id
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    (dst / "references").mkdir(exist_ok=True)
    if cfg.get("copy_from"):
        src = domain / cfg["copy_from"]
        for p in src.rglob("*"):
            if p.is_file() and p.name != "SKILL.md":
                rel = p.relative_to(src)
                target = dst / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, target)
    for src_rel, new_name in cfg.get("refs", []):
        src = domain / src_rel
        if src.is_file():
            shutil.copy2(src, dst / "references" / new_name)
    if cfg.get("examples"):
        ex_src = domain / cfg["examples"]
        if ex_src.is_dir():
            shutil.copytree(ex_src, dst / "examples")

print("ok", sorted(p.name for p in skills.iterdir() if p.is_dir()))
