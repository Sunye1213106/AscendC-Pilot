# 文档维护

文档应解释代码不容易直接表达的内容：为什么需要某个模块、数据为何这样流动、谁拥有最终决定权，以及失败时为何不能跨越边界。不要把实现手工复制一遍，也不要把旧 Markdown 当作事实来源。

## Source of Truth

修改说明前按以下优先级确认事实：

1. 当前 implementation
2. workflow、contract 与 schema
3. tests
4. 当前 runtime assets
5. 既有 docs

若文档与实现冲突，以实现为准并改写文档；若实现语义本身不清楚，应标记该歧义，不应凭空发明机制。

## 文档类型

| 类型 | 要解决的问题 | 适合的位置 |
| --- | --- | --- |
| Concept | 为什么需要、系统怎样协作 | `docs/architecture/` |
| Guide | 用户或开发者如何完成任务 | `docs/getting-started/`、`docs/development/` |
| Module | 一个模块如何工作和与谁衔接 | `docs/modules/` |
| Reference | 精确、可查、少解释的投影 | `docs/reference/` |

不同类型不应强行套用同一组“定位、职责、输入、输出”标题。对于复杂流程，优先使用问题说明、ASCII 流程图、少量关键表格和实现锚点。

## Runtime Markdown 的边界

人类项目说明集中在 `docs/`。会被 Agent、Composer 或 Harness 消费的 Markdown 必须留在 runtime 附近：`skills/*/SKILL.md`、skill references、`prompts/tasks/`、`pilot/policies/`、`pilot/runtime/`、`agents/CONTEXT.md`、examples 和 generated host instructions。

不要在 `pilot/`、`agents/`、`engines/`、`skills/`、`prompts/`、`tools/`、`adapters/` 或 `evals/` 下新增 developer-facing README。根 `README.md`、`docs/**/README.md` 与 runtime example 所需 README 是例外。

## 检查

```bash
python scripts/generate_reference_docs.py
python scripts/check_docs.py
```

检查会覆盖内部链接、废弃路径、README 边界和生成 Reference 的新鲜度；它不尝试用 lint 判断自然语言是否“写得好”。
