# Standalone code review（`/ce-review`）

只读检视。不签发 CE 证书，不关闭 verification obligation。无 diff 要定位改哪里：`/ce-intent`。有 diff 要范围与证书：`/ce-impact` → `/ce-verify`。

详见 `references/cross-layer-contracts.md`、`references/ascendc-checks.md`、`references/finding-format.md`、`references/evidence-quality.md`、`references/gotchas.md`。

review 阶段由 Host 并行派两个隔离子代理（`spec-review` / `standards-review`）。本 METHOD 只覆盖 **scope**。stub 含 `AXIS=` 时不要用这份方法写那一轴的报告。`summary` 是用户对「只看结论 / 落盘报告」的确认，不由本 METHOD 填 YAML。

scope 仍做假设检验：H0 = 入口/侧别/邻域判断成立；H1 = 入口判错或 PR 无 diff。Finding 必须有 `path:line`。

## 入口

- **quick**：快速看风险。短 finding，不写长报告。
- **file**：指定文件或全量检视当前算子。
- **pr**：存在 change capture / diff。没有 diff 时不要猜 PR，标 UNRESOLVED 并停。

侧别：`op_kernel/` → Kernel，`op_host/` → Tiling。分侧陈述。

## 阶段

- `scope`：确认入口、侧别、CodeMap 邻域；PR 确认 diff。在会话中说明入口。不要写长报告。
- `review`：不要自己写两轴。Host 已并行派 Spec / Standards 子代理。结论在 Task 回复里。
- 面向用户的报告默认不落盘；用户选「落盘审查报告」后由 Host 写入 `ce/review/*.yaml`。

两轴分开，禁止合成一个「LGTM」，禁止一个子代理写两轴。

- **Spec**：有 `plan.md` 对照计划；没有则从 diff 推断意图，再看 diff 是否满足该预期。
- **Standards**：对照 `references/ascendc-checks.md`、跨层契约、H0/H1。

PR 入口必须有 diff。禁止写入 `ce/verify/**`。不要读 `ce/**` 下除 `plan.md` 与 change capture 以外的 YAML。
