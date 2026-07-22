# `/uo-query` prompts

## Purpose

本目录不重复 skill 正文；只给出派发时的最小指针与边界。

## Follow

- 主合同：`skills/uo-query/SKILL.md`
- 分类：`skills/uo-query/references/question-taxonomy.md`
- 文件地图：`skills/uo-query/references/kb-file-map.md`
- 源码门禁：`skills/uo-query/references/source-lookup-gate.md`
- 复杂升级：`skills/uo-query/references/complex-unresolved-escalation.md`
- 语言/CBM：`common/language.md` · `common/cbm.md`

## Hard boundary

| 阶段 | 允许 |
|---|---|
| KB 定稿后（integrity + review 过） | `/uo-query` 只读问答 / TG bind |
| `/uo-init` 建库期 | **禁止**；断边用 `uo-semantic-resolve`（见 init `uo-input-derivable-resolve.md`） |

## Parent dispatch tip

```text
Follow skills/uo-query/SKILL.md
PROJECT_ROOT=... OP_NAME=... UO_ROOT=...
Keys: [KEY_...]
```

并行 cap≈8；父代理禁循环 `uo_kb_query` 当主路径。
