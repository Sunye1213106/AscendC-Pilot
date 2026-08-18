# parse-intent

读用户原文，判断要做什么。不要猜 slash，不要把 PR 链接当成「去审查」。

## 方法

1. 原文原样理解。不要改写用户没说的目标。
2. 写出 `needed_capabilities`（可多选）：
   - `knowledge`：需要建立或更新算子理解
   - `change_analysis`：需要理解这次改动（不是默认 code review）
   - `test_generation`：需要生成测试用例
   - `code_review`：用户明确要求审查时才加
   - `implement`：用户明确要求改代码时才加
3. 写出 `source`：
   - 用户给了 GitCode / GitHub PR 链接 → `{kind: pull_request, url: ...}`
   - 只是本地目录 / 当前改动 → `{kind: local}` 或 `{kind: git_diff}`
   - 没有输入源 → `{kind: none}`
4. PR URL 只是输入，不是意图。用户说「生成 case」就填 `test_generation`，即使文里有 PR 链接。
5. `constraints` 只收录用户说过的限制（dtype、不要某模式等）。

## 禁止

- 发明 `uo-init` / `tg-plan` / `ce-review` 工作流链
- 因为看到 URL 就填 `code_review`
- 把 URL 当成唯一 intent
