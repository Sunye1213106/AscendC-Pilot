# parse-intent

读用户原文，判断要跑哪些**用户工作流**。五个认知 skill 是领域方法，不是意图标签。

## 方法

1. 读 session `refs/workflow-catalog.md`（由 Harness 从工作流注册表生成）。
2. 原文原样理解。拆独立交付目标，对到目录里的工作流 id。不要改写用户没说的目标。
3. 写出 `needed_workflows`：目录内 id 的**并集**（无序）。多目标是常态。
4. 写出 `source`：
   - 用户给了 GitCode / GitHub PR 链接 → `{kind: pull_request, url: ...}`
   - 只是本地目录 / 当前改动 → `{kind: local}` 或 `{kind: git_diff}`
   - 没有输入源 → `{kind: none}`
5. `source` 与工作流正交：有 URL 只填 source，不隐含某个 workflow。
6. `constraints` 只收录用户说过的限制。

## 禁止

- 发明目录外的工作流 id
- 写出执行顺序或前置（`uo-init` / `tg-init` 等由 Harness 按磁盘产物补）
- 输出 skill 名或 `needed_capabilities` 作为真值
