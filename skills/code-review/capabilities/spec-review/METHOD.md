只做 **Spec** 轴：判断改动是不是这次需求要的。不要做 Standards 轴。

详见 `references/finding-format.md`、`references/gotchas.md`、`references/evidence-quality.md`。

## 对照

1. 有当前 `ce/plan/{slug}_plan.md` 则对照该计划（todo 是否做完、有无超范围）。
2. 纯 PR、没有计划时：**从 PR 标题、`git log --oneline base...head`、`change_capture/index.md` 与新增标识符推断 3–8 条粗意图**，再逐条用 UO 验收是否做完 / 半截 / 超范围。允许粗，禁止编造 `ce/plan` 产品，禁止「只陈述理解就算完成」。
3. 不要读任何 CE yaml。禁止线性通读 `change_capture/diff.md`。

PR 入口必须有 diff 索引。Finding 必须有 `path:line`。

## 方法

```text
index 的 Added identifiers → 并行 form-1 新字段/新函数 → 字段 readers 定位 Kernel 定义 → 完成度 → FINDING
```

1. 先读 `runs/<RUN>/actions/change_capture/index.md` 与若存在的 `uo_hints.md`。需要某 hunk 细节时只读对应 `hunks/` 小窗。禁止先 form-3 打 format hunk。
2. 插件 `pilot_cli` `uo-query`：**并行 form-1 标识符**（一张 `deterBandScheduleMode` 即 Host 写 + Kernel 读）。形态 3 `--file --line` 只用于有 ident 的位点，不要打纯空白/format 行。不要传 `--mode`。禁止 `explain-*`。禁止 Grep 通读算子源码。
3. snippet 截断不得下「枚举未用」。Kernel 以字段卡 `extras.readers` 行为准，不要把 `kernel_call_boundary` 调用点当定义。
4. 只读 git 仅用于标题：`git log --oneline`、`git show --stat`、`git diff --stat`、`git rev-parse`。禁止 `git checkout` / 全量 patch。
5. 报告：(a) 意图要但缺失或只做了一半；(b) 意图没要的行为；(c) 看起来做了但实现不对。每个 changed file：finding / format-only / UNREVIEWED。未审 `op_kernel` 禁止「无 high/medium」。
6. UT 不在 CodeMap：只读 `tests/**` 搜新字段名。本 PR 测试文件零次出现新字段 → Spec I5 是缺口。
7. 报告前尝试推翻 H1。

两轴 parts 收齐后 Primary 用字段卡裁定矛盾（例如 Host 已赋 BAND/DENSE/CAUSAL 则收回「枚举未用」），写 `runs/<RUN>/actions/code_review/parts/merged.md`。禁止再 prepare 同一对 spec/standards。

## 产物

`path:line` 结论写在 **Task 回复**里。不要 Write `parts/*.md` 收票；插件用 Task 原文 ACK。禁止 Write `ce/**`。禁止合成 LGTM。对人说审查结论时不要堆 I5/H0 编号表。
