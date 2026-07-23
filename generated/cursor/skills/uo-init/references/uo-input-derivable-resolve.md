# input_derivable / KEY 语义补全（建库期 · uo-key-resolve）

`build_layered_kb` → `classify_input_derivable` 之后，凡
`ir/input_derivable.yaml` 中 `input_derivable: unsolved` 的 KEY，由
**`uo-key-resolve`（先 triage，再按复杂度 resolve）** 补全推导关系（或高置信标
`not_input_derivable`）。

**主路径**：Host `file_path` 定向阅读 + gaps 邻接。  
**CBM**：MAY 辅助，非闭合必要条件。  
勿仅凭静态图一跳结论硬解强 shape 相关 KEY。

## 紧凑产物（强制）

| 字段 | 含义 |
|---|---|
| `host_parent` | 一跳：谁 write / set_by 上一级 |
| `derivation_roots` | 闭合到 Host 输入面时的根节点 |
| `graph_markers` | 图上标记 `determined_by` / `reaches_input`（由 classify 生成） |
| `shape_expr`（可选） | 写入 `ir/key_shape_resolve/<KEY>.yaml` |

**禁止**在 contract / prompt 倾倒整条 `host_derivation_chain` / 长 `function_chain`。  
多跳：沿图走 `determined_by` 或继续读 Host 源码。

## 父代理流程（硬门禁）

1. 读 `ir/input_derivable_gaps.yaml`；若 `status: open` → **不得**跳过本步。
2. 派发 **一次** `tpl_key_triage` → `ir/key_triage.yaml`（只分类）。
3. 按 triage 分流派发 `uo-key-resolve` + `tpl_key_resolve`：
   - **complex**（IsNzOut、分轴、sparse/NZ、强 shape）→ **一 KEY 一 Task**
   - **simple**（empty_tensor、纯 regbase 开关等）→ **多 KEY 打包**（≤6）
   - 并行 Tasks cap 建议 **8**（禁止默认「每个 KEY 一个 subagent」）
4. 子代理写 `ir/input_derivable_patch.yaml`（及可选 `ir/key_shape_resolve/<KEY>.yaml`）。
5. **仅 `confidence: high`** 可把 KEY 标为 `true` 或 `not_input_derivable`。
6. 父代理重跑 classify + **`check_final_confidence.py`** + **`harness validate-key-gates`** + contract/sqlite 导出。
7. 仍无法 high → 写 `summary/confidence_report.md`（中文原因，禁止多 KEY 同文 bit-pack）；**禁止伪标 high**。
   missing_producer 仅 empty 路径 → 不得最终 accepted；须 escalate 并查主 tiling（GetTilingKey / SaveToTilingData）。
   详见 `confidence-gate.md`。

```powershell
python -X utf8 "$SCRIPT_DIR/classify_input_derivable.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
python -X utf8 "$SCRIPT_DIR/check_final_confidence.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
harness validate-key-gates "$PROJECT_ROOT"
python -X utf8 "$SCRIPT_DIR/kb_query_export.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --view testcase-contract
python -X utf8 "$SCRIPT_DIR/export_kb_graph.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
```

## 子代理要做什么

对每个 gap `target`（如 `KEY_ISNZOUT`）：

1. 读 gap 的 `host_parent`、`gap_kind`、`tried_frontier`；沿图 `writes`/`derives` 到 Host 符号与 `file_path`。
2. **主路径**：按 `file_path` 读 Host 相关代码，提取谓词 / shape / 开关含义。
3. **MAY**：CBM `get_code_snippet` 旁证；MCP 空不得直接判不可解。
4. 判断：
   - 能接到 Attribute / Input / OptionalInput / Shape / DType / Layout →  
     `input_derivable: true` + `derivation_roots` + 一跳 `host_parent`
   - 明确是核内局部 / 分批索引（如 blockId）→ `not_input_derivable`
   - 证据不足 → **不要**写 true；留在 gaps（父代理汇总）
5. 目标是补语义连接（含 shape 条件），不是查已建成的 KB 问答。

## Patch schema（紧凑）

```yaml
version: 1
keys:
  - key_id: KEY_ISNZOUT
    confidence: high
    input_derivable: true          # 或 false / not_input_derivable
    host_parent: SYM::enableSwizzle
    derivation_roots: [HOST_ATTR_sparseMode, HOST_START_INPUTSHAPE]
    reason: "中文：说明如何接到输入根（一跳父级即可）"
    evidence: ["path:line"]
```

低置信 patch **不会**被 classify 采纳为 true/false（保持 unsolved）。

## 与 unresolved 的关系

- `ir/unresolved.yaml`：桥接/抽取诊断 → `resolution_patch.yaml`（任务 B · `uo-semantic-resolve`）
- `ir/input_derivable_gaps.yaml`：KEY 能否从 Host 输入面推导 → triage + `input_derivable_patch.yaml`（`uo-key-resolve`）

建库期不派 `/uo-query`；定稿后复杂 KEY 升级仍走 `uo-key-resolve`（见 `complex-unresolved-escalation.md`）。
