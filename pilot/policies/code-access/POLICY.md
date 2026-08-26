# Policy: code-access

算子语义走路由，不是 UO / Grep / 源码三个并列入口。查到 ≠ 已比对（见 `evidence`）。

| 问题 | 第一手证据 | 允许的兜底 |
| --- | --- | --- |
| 符号身份、写者 / 读者、调用、控制依赖、Tiling 身份 | `uo-query` | 卡片给出的窗口精读 |
| 本次改了什么 | 已 pin 的 diff 元数据 / packet | 按符号定位的最小行窗 |
| 表达式原文、字面量 | 源码窗口 | — |
| 测试 harness 仓（runner / golden / compare） | 源码 | — |

兜底到算子源码时写原因码：`SOURCE_FALLBACK_UO_EMPTY`（`count: 0`）、`SOURCE_FALLBACK_UO_AMBIGUOUS`（同名多候选）、`SOURCE_FALLBACK_UNSUPPORTED_SEMANTIC`（图上本来就不存的原文 / 字面量）。没有原因码而 Grep / Read 算子源码求语义结论 = 越界。harness 仓没有 UO 图，直接 Read / Grep。

卡片已给 `file_path` + `line` 时只打开那个窗口。Grep 只定位。只读当前结论所需的最小窗口：不扫父仓，不倾倒整文件。`count: 0` ≠ 符号不存在。

`uo-query` 的合法参数形态由当前查询步的 method 给出。禁止 `--mode`、`explain-*`、`search`、`locate`，以及四种形态之外的参数（含 Task 正文）。0 命中不得回填全集覆盖。around 只扩 1 跳。

语义表面与浅 writer 见 `semantic-grounding`。
