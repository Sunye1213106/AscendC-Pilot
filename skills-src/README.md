# skills-src

Skill **单一来源**。安装前由 `scripts/compile_skills.py` 编译到 `generated/<host>/skills/`。

```text
python scripts/compile_skills.py --repo .
# → generated/opencode|cursor|codex/skills/
```

- 领域方法与 references 写在本树
- 宿主差异（frontmatter）在 `hosts/*.yaml`
- 编译器注入「Harness control plane」循环；禁止在 Skill 内另起状态机
- `/operator` 只调用 `harness route`，不维护第二路由表
- `/uo-diff` 已并入 `uo-update`（本树保留重定向 Skill）

遗留根目录 `skills/` 仅作对照，**install 部署 generated/**。
