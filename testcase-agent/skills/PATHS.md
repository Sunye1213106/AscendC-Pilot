# Testcase Agent path hints

## 三段

| Skill | 角色 |
|-------|------|
| `/tg-init` | 摄入+绑定；父代理**全自动** KEY/mid/kernel 套娃 Task + merge + `--verify-csv-closure` + audit + confirm（**用户零操作追符号**） |
| `/tg-plan` | init confirmed；Allow solve 门禁 |
| `/tg-solve` | 域对称再校验后 SMT→CSV |

**Lexicon = 可执行真值**；`uo_query_resolve` 必须 merge。`mid_symbol_queue` 非空时父代理必须自动开 Task，禁止甩给用户。终审：`agents/tg-init-audit.md`。

详见 `tg-init/SKILL.md`、`tg-init/references/tg-mid-symbol-nesting.md`。
