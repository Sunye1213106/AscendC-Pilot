# uo-init clang 引擎重构记录

> 本文只记录**本次重构的重要变化与决策理由**，是变更日志性质的文档。
>
> - 设计说明书见 [control-closure.md](./control-closure.md)
> - 工作流说明见 [../workflows/uo-init.md](../workflows/uo-init.md)
> - 文档索引见 [../README.md](../README.md)

状态：`uo-init` / `uo-update` / `uo-query` 均挂 `uo_init`；旧 `understand-operator-old` 已删除。

---

## 1. 为什么重构

旧 uo-init 的抽取层是正则加启发式，产出不可靠，只能让大模型兜底确认关系。结果是控制面被撑成 16 个 Action、7 个 subagent，`extract_plan` 靠 LLM Map worker 分片，`key_triage` / `key_resolution` 也是 LLM，单次运行产生数百个 LLM 任务。

同时下游对不上：uo 产出的是扁平 JSON 加分类标签（`root_kind = "INPUT_SHAPE"`、`expression` 是原始源码文本），而 TG 的 Z3 后端要的是具名变量加值域，CE 的影响分析要的是可多跳查询的图。中间缺一整层归一化。

重构的前提是 libclang 在 Windows 原生环境下已实测跑通 host / kernel 两侧解析，抽取可以做成确定性的，不需要大模型参与。

## 2. 关键决策

### D1 抽取层全部改为 libclang 确定性遍历

控制节点、写事件、函数摘要、TilingKey 三方绑定、Registry 竞价全部由 `clang_walk` / `tpl_bind` / `registry_capable` 产出，不再有 LLM 参与抽取。

**理由**：编译器的 AST 是唯一不会猜错的来源。抽取一旦可靠，大模型兜底的必要性就消失了。

### D2 LLM 三级触发，顺利路径零任务

- 默认：确定性归一化闭合所有节点，`resolve_gaps` 与 `kb_review` auto-finalize 为 `skipped`，全程零 LLM
- 有残余项：`resolve_gaps` 触发
- 残余项影响可控性：`kb_review` referee 才介入，且只审 `unresolved` 与低 confidence 项

`scope_confirm` 同样不再无条件打断人：libclang 探针 0 error 且文件集与 opdef 声明一致时自动签 receipt，只在发现多个 arch 目录、多个 kernel entry 或探针报错时才询问。

**理由**：LLM 是兜底手段不是主链环节。确定性手段没用尽之前不应该调用它。

### D3 LLM 分片单位从「节点」改为「blocker」

未闭合节点数远大于真实问题数。实测 63 个开放节点背后是同一批符号，`fBaseParams.queryType` 一个字段就导致 39 个节点开放，修好这一个原子，39 个节点同时闭合。

分片单位改成归一化失败的原子（`Atom.text` 加 `reason_code` 去重）。63 个节点聚类后约 25 个 blocker。`ir/unresolved.yaml` 直接按 blocker 组织，节点降级为 blocker 的 `affected_nodes` 列表。聚类逻辑放共享模块 `uo_init/gaps.py`。

**理由**：任务数应该反映真实问题数，而不是问题的表现次数。

### D4 知识库：YAML 权威 + SQLite 派生索引

YAML 是权威层，因为它能 git diff、能人工审查、能被 Gate 校验、能签 Receipt、能做 Producer/Referee 写域隔离。SQLite 是派生索引，提供 YAML 给不了的能力：单文件零依赖（stdlib `sqlite3`，离线可用）、`WITH RECURSIVE` 多跳可达（CE 影响分析必需）、FTS5 证据全文检索。

`kb_index.py` 必须是 `YAML -> sqlite` 的纯函数，同输入同输出，**禁止手改 sqlite**。这与项目「`generated/` 是可丢弃编译产物，不能成为第二权威源」是同一条原则。

**理由**：不选 Neo4j/DuckDB 是部署依赖和离线问题；不选纯 JSON 是因为 CE 的多跳影响分析会退化成全量扫描。

### D5 节点 ID 改为内容稳定

旧 `CtrlNode.id` 是 `file:line:col:kind:ordinal`，上面插一行 ID 就全变，增量更新和 CE 历史对比全部失效。改为：

```text
KBR_<hash12(rel_file + "::" + function + "::" + normalized_guard + "#" + ordinal_in_function)>
```

`normalized_guard` 取谓词归一化后的 SMT-lite 规范形，改格式改注释都不影响，只有语义变了才变。行号退到 `evidence` 表（本来就允许漂移）。

### D6 值域按可证据性切分，而不是按模块切分

- UO 负责源码能证明的部分：`enum class` 成员集合、TPL dim 的 `vals`、opdef 的 dtype/format 列表、optional 的 bool 域、从校验分支反推的边界（`if (dim > 65535) return FAILED` 推出 `hi = 65535`）
- TG 负责属于测试策略的部分：边界值选取、`SAFE_CAPS` 上限、随机采样、组合覆盖强度

关键是 `completeness: closed | open` 字段，诚实告诉 TG「这个 int 只推出了下界，上界你定策略」，而不是假装闭合。

### D7 闭合度量拆成两个口径

旧口径有水分：244 个「已闭合」里 `LOOP_INDUCTION` 100 个、`CONSTANT` 36 个、`TILING_DATA` 8 个对测试用例都不可控，真正落到输入面的只有 110 个。

`quality.yaml` 同时给两个数：

- `source_closure` — 追到任意根 Source
- `input_controllability` — 分子只算 `INPUT_SHAPE / INPUT_DTYPE / INPUT_FORMAT / INPUT_VALUE / OPTIONAL_INPUT_PRESENCE / ATTRIBUTE`

同时修掉 `source_resolver._chase_field` 的逃生舱：找不到写点就 `return Atom(root="TILING_DATA")` 判 closed，改成 `status: partial`。

**理由**：一个自己骗自己的指标比没有指标更危险。

### D8 去 FAG 特化

新增 `op_spec.py` 自动发现算子布局，可选 `spec/operators/<op>.yaml` override。清掉 `workflow.py` 的 `HOST_TARGETS` 写死文件名、`tpl_bind.py` 的 `void flash_attention_score_grad` 正则、`branch_inventory.py` 的 `GOLDEN_HOST_DENOMINATORS` 与 `INVOKE_FAG_` 前缀、`bridges.py` 写死的 TilingData 类名等。

### D9 本次重构的根因记录落在本文

联调级根因写入本文档变更日志，或按主题落到 `docs/debug/` 下的现行调试笔记；旧 `extract_plan` 时代联调长文已移除。

## 3. 变更清单

**新增**

- `uo_init/pilot_engines.py`：16 Action 的 `fn(project_root, payload)` 入口（含 `derive_key_fields`）
- `uo_init/{kb_export,kb_index,uo_query,assemble_kb,variable_model,predicate,controllability,op_spec}.py`
- gates：`layout_receipt` / `scope_probe_clean` / `extract_receipt` / `normalize_receipt` / `gap_patch_evidence`
- TG：`OPTIONAL_KB_EXPORT_FILES`，`not_extracted` 视为已声明缺失

**修改**

- `specs.py` `WORKFLOWS["uo-init"]` → 6 阶段 16 Action / 2 subagent（`uo-gap-resolve`、`uo-kb-review`）
- `engines.py` ENGINE_REGISTRY 改挂 `uo_init.pilot_engines`（不再 `uo.scripts.*`）
- `ownership.py` 写路径切到分层 YAML + `resolve_gaps` staging
- `Node.to_dict`：保留字段优先于 `data`，避免 `data.kind` 覆盖节点 kind
- `checks/artifact_hashes.yaml`：同时写 `artifacts` 与 TG 消费的扁平 `hashes`

**删除（部分）**

- `engines/understand-operator/_diag.py`、`fag_report.json`
- 旧 16-Action 控制面 Spec 条目已替换；skills/agents 因 `uo-update` 仍复用暂留

## 4. 破坏性变更与迁移

- `uo.scripts.*`：uo-init 主链已不依赖；替代入口为 `uo_init.pilot_engines` / `assemble_kb.export_operator_closure`
- TG `validate_intake`：pipeline/resources/flow 等改为 OPTIONAL；`status: not_extracted` 不挡 intake
- 旧 receipt（`extract_plan.yaml` 等）不再由新 uo-init 写入；请用新分层产物
- 改完 Spec 后执行：`python scripts/compose_runtime.py --sync`，再 `refresh-opencode.ps1` / 重启会话

## 5. 验证结论

Host 高置信闭合（FAG arch35 作回归样本，**无 FAG 特化**）：

| 指标 | 结果 |
|------|------|
| PRODUCTION 节点 | 740 |
| `source_closure` | **0.9662**（≥ 0.95） |
## 5. 当前基线（2026-07-28，脚本闭环）

| 指标 | 值 |
|---|---|
| `source_closure` | **0.9595** |
| `input_controllability` | **0.2405** |
| `blocker_count`（LLM task） | **12**（&lt; 20） |

Kernel / KB / TG（2026-07-28 UO↔TG 闭环）：

- pairwise×`DT_FLOAT16` → 37 job → **2** 唯一 `KBR_*`
- tiling materialize（**脚本** `export_operator_closure` 传 `tpl_schema`）：`legal_keys=8705`
- Pilot 主链 `export_kb_action` **常未传** `tpl_schema` → materialize 可能跳过；K6 真 Z3（`value_expr` 联立）**未完成**
- KeyField 派生已进主链 Action `derive_key_fields`；调试快照见 `docs/fag/` + `docs/debug/handoff.md`（非契约）

Action 数：**16**（含 `derive_key_fields`）。`resolve_gaps` 按 blocker 分片（≤30/shard，`uo_init.blocker_shards`）。

对应验收项：

| 项 | 结果 |
|---|---|
| 单测（含 materialize_tiling） | 通过 |
| 引擎链冒烟 `prepare→scope→export→index→integrity` | 通过 |
| TG L2 `expand_l2_tiling_keys` | **8705 reachable**（脚本路径） |
| TG `gate_uo_ready` / `built_kb_ready` | **pass**（脚本路径） |
| Pilot 主链 K6 / 8705 全表 | **未宣称完成** |
| `acp start uo-init` 全流程 UI | 后置 |

残留（有意）：

- 旧引擎目录已删除；`uo-update` 挂 `uo_init.update`
- key_triage LLM 链：见 `docs/debug/open-problems.md`（当前 stub）
- K6：删硬编码不变式、联立 `host_derivation.value_expr`

## 6. 变更日志

- 2026-07-28 建立本文档，记录重构启动时已确定的 D1-D9 决策。
- 2026-07-28 Host gate：`source_closure` 0.9595、`blocker_count` 18；Kernel fold KBR + KB assemble/export 接通。
- 2026-07-28 收尾：KBR evidence、kind 覆盖修复、hashes 扁平化、sqlite/integrity/kb_review、TG intake pass、CE impact 冒烟、第二算子泛化、文档重写；临时产物 `_diag.py`/`fag_report.json` 删除。
- 2026-07-28 UO↔TG 闭环：materialize tiling 契约、8705 L2 + L1 CSV、gate_uo_ready 新实现、调试日志归档。
- 2026-07-30 对齐：16 Action + `derive_key_fields`；`resolve_gaps` 分片调度落 `uo_init.blocker_shards`；诚实化 8705/K6 口径。
