# -*- coding: utf-8 -*-
"""Refresh fixture + isolated live session prompts from production Plan Owner."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OWNER = (ROOT / "prompts" / "tasks" / "tg" / "plan-owner.md").read_text(encoding="utf-8")
FIXTURES = ROOT / "evals" / "fixtures" / "tg-plan"
LIVE = ROOT / "evals" / "tg_plan" / "live"
METHOD_SRC = ROOT / "skills" / "test-plan" / "SKILL.md"
CASES = [
    "pr-9851-fag-deter-band",
    "pr-10335-fag-tnd-dense-swizzle",
    "pr-10295-fag-gqa-dense-swizzle",
    "pr-10546-fag-tnd-sparse-deter",
]


def _render(inp: str, method: Path) -> str:
    extra = (
        f"\n先读 `{method.as_posix()}`，那就是本窗形式规范。"
        "禁止打开 `evals/fixtures`。"
        "禁止读 plan.golden.md / rubric.yaml / grade_*.py / session/trial*.yaml。\n"
    )
    new = re.sub(r"<input>.*?</input>", inp, OWNER, count=1, flags=re.S)
    return new.replace("<method>", "<method>\n" + extra, 1)


def main() -> None:
    for case in CASES:
        fixture_prompt = FIXTURES / case / "session" / "prompt.md"
        old = fixture_prompt.read_text(encoding="utf-8")
        match = re.search(r"<input>.*?</input>", old, re.S)
        if not match:
            print(f"skip {case}: no <input> block")
            continue
        inp = match.group(0)
        fixture_method = FIXTURES / case / "session" / "method.md"
        shutil.copyfile(METHOD_SRC, fixture_method)
        fixture_prompt.write_text(_render(inp, fixture_method.resolve()), encoding="utf-8")
        print(f"wrote {fixture_prompt}")

        live_dir = LIVE / case
        live_dir.mkdir(parents=True, exist_ok=True)
        live_method = live_dir / "method.md"
        shutil.copyfile(METHOD_SRC, live_method)
        (live_dir / "prompt.md").write_text(_render(inp, live_method.resolve()), encoding="utf-8")
        print(f"wrote {live_dir / 'prompt.md'}")


if __name__ == "__main__":
    main()
