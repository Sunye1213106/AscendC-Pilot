# Policy: evidence

## Purpose

关键结论必须可追溯；禁止伪造置信度。本策略对**所有**语义 Action / Agent 生效（经 `DEFAULT_POLICY_IDS` 注入），禁止只在个别 skill 里另写一套证据规则。

## Rules

1. 关键结论必须有 `path:line`、KB reference 或确定性产物证据。
2. 不能以命名猜测闭合 KEY。
3. 不能伪造 `confidence: high`。
4. 推断必须明确标记为 `inference`。
5. 证据不足时保留 `unresolved` / `needs_human`，不得猜测闭合。
6. 仅 `confidence: high` 可闭合 true / false / not_input_derivable 类字段。
7. **高置信 = 源码比对（全局硬规则）**：凡写入 `confidence: high` 或 `source_verified: true` 的结论，必须同时具备：
   - `evidence_source: source|cbm`（禁止 `candidate_only` 冒充 verified）
   - 非空 `evidence_files` + `evidence_lines: [start, end]`（1-based inclusive）
   - `evidence_window_sha256`：磁盘窗口 sha（pad=0；可从候选 `source_window.sha256` 拷贝）
   - `evidence_snippet`：该窗口内**连续**真实源码文本（足够长），**必须为磁盘窗口连续子串**（可去缩进比对）；禁止挑行拼贴
   - `decision_reason`：说明「读了哪段、为何成立」
8. **CBM / search 不是比对**：`search_graph` / `search_code` / 候选表只能定位；定位后必须 `get_code_snippet` 或定向 Read 窗口，再写 snippet。仅有搜索命中不得标 high / source_verified。
9. **证据载体（硬 · AND 不是 OR）**：高置信必须 **同时** 有 `evidence_window_sha256` **与** 连续 `evidence_snippet`。仅 sha、仅 snippet、或 sha 对但 snippet 非连续窗口子串 → Gate / apply **拒绝**。共享校验：`uo.scripts.source_evidence.require_disk_window_proof`。
10. **产品韧性（公共）**：apply 可在 files/lines 可解析时从磁盘窗口（或候选 `source_window.text`）**回填**连续 snippet 与 sha（`enrich_item_evidence_from_disk`）；禁止省略号拼贴残留。回填不是放宽合同，而是消除易碎 YAML。
11. **禁止占位证据**：`candidates_sha256`、snippet、行号不得填 `PLACEHOLDER` / `TODO` / 编造 hash；Gate 必须拒绝。
12. 校验实现统一走共享模块（`uo.scripts.source_evidence` / `yaml_literal_sanitize`），各 Action finalize **复用**，不得各自发明宽松规则。

## Hard Constraints

- MUST：每个闭合结论附证据类型与引用。
- MUST：`confidence: high` ⇒ `source_verified: true` + 磁盘窗口 sha **且** 连续可核验 `evidence_snippet`。
- MUST NOT：发明证据、行号、KB 节点或 snippet；禁止用「仅 window sha」放行拼贴 snippet。
- MUST NOT：用「命名像 / 候选表有 / search 命中」当作 high 的唯一依据。
- MUST NOT：在个别 skill prompt 里弱化或覆盖本策略；skill 只可引用本策略，不可另立例外。
