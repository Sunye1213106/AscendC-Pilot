# Policy: code-access

## Purpose

约束代码语义查阅方式，禁止无边界全仓扫描；与 `evidence` 策略配套——**查到 ≠ 已比对**。

## Rules

1. 理解普通函数/类/调用关系时优先使用 UO KB 图查询。
2. 已有明确 `file_path` 时可直接打开目标源码窗口。
3. Grep / rg / `Select-String` **只用于定位**（OpenCode Grep 或 bash 只读搜索均允许），不可单独作为复杂语义结论 / high / `source_verified` 的唯一证据。Windows `findstr` 路径须用反斜杠（`D:\…\file`）；正斜杠 `D:/…` 会被当成开关导致「无法打开」。
4. 不允许无边界扫描整个仓库或父仓。**大 IR 公共模式**：prepare 须写 `*.summary.yaml`（`section_lines` + `must` + 本步导航字段如 `source_window_sha256` / `non_sink_root_names`；共享 `uo.scripts.ir_summary`）；dispatch `read` 把 summary（及 `*.rework_hints.yaml`）排在全量 IR 前；Host stub 见 `*.summary.yaml` 即注入 `MUST_READ_ORDER`。禁止先 Grep/offset 扫整份 candidates。
5. UO 图空结果不代表符号不存在；须回退定向源码阅读或受控 source_closure。
6. 禁止无边界探索父仓；读取必须位于 confirmed scope。
7. 宏表 / 注册宏 / Host 谓词 / CMake / 模板参数绑定：以确定性脚本 + 范围内 Read 为主路径。
8. 官方文档只提供接口/宏契约；权威序：算子源码 → 目标 CANN 版本文档 → latest → 其它。文档不得创建无源码边。
9. CMake/构建文件走 `extract_build_evidence`。
10. 符号身份使用 `semantic_identity` / `entrypoint_graph` 稳定 id，禁止短名唯一键。
11. **标准读码路径（全局）**：`search_graph` / `search_code` 定位 → `get_code_snippet(qualified_name=...)` 或定向 Read **函数体窗口** → 再写结论。禁止「最省事」捷径（只 search 不拉 snippet、整文件 dump、凭记忆编 snippet）。
12. **窗口预算**：只读当前结论所需最小窗口（函数/宏块附近）；禁止整文件倾倒进上下文。
13. 高置信结论的源码比对要求见 `evidence` 策略（本策略不另开例外）。
14. **TilingData 定值写点**：UO `host_writer_sites` 若只停在最终 `set_*` / `fBaseParams` 拷贝，而缺少 `value_defining_sites`（真正决定字段取值的赋值），**不得**据此宣称「字段不可达 / 无需读码」。须定向阅读定值函数最小窗口，并走 `uo-update` / gap-patch 回灌 UO；禁止在 TG 脚本里写死算子特判。
15. **Lemma / 不可达证明**：将某 branch outcome 或 key 划入 E 时，**必须**读 host 源码最小窗口写 P⇒Q（见 `source-lemma-proof` + `evidence`）；UO 只提供 writer / guard / branch anchor，不能单独充当证明。

## Hard Constraints

- MUST：语义结论前完成「定位 → 窗口读」；高置信前完成「窗口 ↔ snippet 比对」。
- MUST NOT：`index_repository(repo_path=父仓)`。
- MUST NOT：整文件 dump 或无关大段源码加载。
- MUST NOT：把 UO 图空结果当作「不可解」的唯一证据。
- MUST NOT：仅凭浅 `host_writer_sites`（无 `value_defining_sites`）宣称字段/分支不可达。
- MUST：lemma / E 结论具备源码窗口证据（`source_verified`），不得「UO 有字段名即闭合」。
- MUST NOT：把 BuildConfig / CompileMacro / PlatformInfo 伪装成 CSV 可控输入。
- MUST NOT：恢复 `roles.*.selected` 单入口契约。
- MUST NOT：candidate 边假闭合主链；patch 直接改写派生图。
- MUST NOT：因评分低自动把主链必需缺口降为 informational。
- MUST NOT：仅用 search 命中标 `source_verified` / `confidence: high`。
- MUST：LLM 消歧仅在候选窗内；过期 snapshot/candidate hash 的 patch 必须拒绝。
