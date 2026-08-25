# -*- coding: utf-8 -*-
"""Refresh isolated live Solve sessions from production construct-cases prompt."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OWNER = (ROOT / "prompts" / "tasks" / "tg" / "construct-cases.md").read_text(encoding="utf-8")
METHOD_SRC = ROOT / "skills" / "solve" / "references" / "construct.md"
LIVE = ROOT / "evals" / "tg_solve" / "live"
ENGINE = ROOT / "engines" / "testcase-generation"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

CASES = {
    "pr-9851-fag-deter-band": {
        "plan": ROOT / "evals/fixtures/tg-plan/pr-9851-fag-deter-band/session/trial-c25-fill1.yaml",
        "init": Path(r"D:/PR-review/TEST/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-9851/attention/flash_attention_score_grad/.ascendc-pilot/arch35/tg/init.yaml"),
        "project": Path(r"D:/PR-review/TEST/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-9851/attention/flash_attention_score_grad"),
    },
    "pr-10335-fag-tnd-dense-swizzle": {
        "plan": ROOT / "evals/fixtures/tg-plan/pr-10335-fag-tnd-dense-swizzle/session/trial-c25-fill2.yaml",
        "init": Path(r"D:/PR-review/TEST/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-10335/attention/flash_attention_score_grad/.ascendc-pilot/arch35/tg/init.yaml"),
        "project": Path(r"D:/PR-review/TEST/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-10335/attention/flash_attention_score_grad"),
    },
    "pr-10295-fag-gqa-dense-swizzle": {
        "plan": ROOT / "evals/fixtures/tg-plan/pr-10295-fag-gqa-dense-swizzle/session/trial-c25-fill3.yaml",
        "init": Path(r"D:/PR-review/TEST/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-10295/attention/flash_attention_score_grad/.ascendc-pilot/arch35/tg/init.yaml"),
        "project": Path(r"D:/PR-review/TEST/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-10295/attention/flash_attention_score_grad"),
    },
    "pr-10546-fag-tnd-sparse-deter": {
        "plan": ROOT / "evals/fixtures/tg-plan/pr-10546-fag-tnd-sparse-deter/session/trial-c25-fill1.yaml",
        "init": Path(r"D:/PR-review/TEST/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-10546/attention/flash_attention_score_grad/.ascendc-pilot/arch35/tg/init.yaml"),
        "project": Path(r"D:/PR-review/TEST/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-10546/attention/flash_attention_score_grad"),
    },
}


def _dump_index(plan_path: Path, init_path: Path, out: Path) -> None:
    from testcase_agent.plan_fill import ensure_v3, load_yaml
    from testcase_agent.solve_fill import index_plan

    plan = ensure_v3(load_yaml(plan_path.read_text(encoding="utf-8")), load_yaml(init_path.read_text(encoding="utf-8")))
    init = load_yaml(init_path.read_text(encoding="utf-8"))
    idx = index_plan(plan, init)
    payload = {
        "schema": "tg-solve-index/v1",
        "needs_hit": idx.get("needs_hit") or [],
        "auto": idx.get("auto") or [],
        "guards": idx.get("guards") or [],
    }
    import yaml

    out.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _to_yaml(doc: dict) -> str:
    import yaml

    return yaml.safe_dump({k: v for k, v in doc.items() if k != "schema"}, allow_unicode=True, sort_keys=False)


def main() -> None:
    LIVE.mkdir(parents=True, exist_ok=True)
    method = METHOD_SRC.read_text(encoding="utf-8")
    for case, meta in CASES.items():
        dest = LIVE / case
        dest.mkdir(parents=True, exist_ok=True)
        idx_path = dest / "solve_index.yaml"
        _dump_index(meta["plan"], meta["init"], idx_path)
        inp = f"""<input>
- Plan: `{meta["plan"].as_posix()}`
- Init: `{meta["init"].as_posix()}`
- Solve index: `{idx_path.as_posix()}`
- project_root: `{meta["project"].as_posix()}`
</input>"""
        extra = (
            f"\n先读 `{ (dest / 'method.md').as_posix() }`，那就是本窗形式规范。"
            "禁止打开 `evals/fixtures` 下除 Plan 输入路径以外的文件。"
            "禁止读 rubric / grade / trial。\n"
        )
        text = re.sub(r"<input>.*?</input>", inp, OWNER, count=1, flags=re.S)
        text = text.replace("<method>", "<method>\n" + extra, 1)
        (dest / "prompt.md").write_text(text, encoding="utf-8")
        (dest / "method.md").write_text(method, encoding="utf-8")
        print("wrote", dest)


if __name__ == "__main__":
    main()
