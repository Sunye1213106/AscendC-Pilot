# input_derivable 断边补全（建库期 · uo-semantic-resolve）

`build_layered_kb` → `classify_input_derivable` 之后，凡
`ir/input_derivable.yaml` 中 `input_derivable: unsolved` 的 KEY，必须由
**`uo-semantic-resolve` + CBM 源码证据** 把断裂处连上（或高置信标
`not_input_derivable`）。


## 紧凑产物（强制）

| 字段 | 含义 |
|---|---|
| `host_parent` | 一跳：谁 write / set_by 上一级 |
| `derivation_roots` | 闭合到 Host 输入面时的根节点 |
| `graph_markers` | 图上标记 `determined_by` / `reaches_input`（由 classify 生成） |

**禁止**在 contract / prompt 倾倒整条 `host_derivation_chain` / 长 `function_chain`。  
多跳：沿图走 `determined_by`。

## 父代理流程（硬门禁）

1. 读 `ir/input_derivable_gaps.yaml`；若 `status: open` → **不得**跳过本步。
2. 按 KEY 分批（默认并行 cap **8**），派发 **`uo-semantic-resolve`**，任务名：
   `input_derivable 断边补全`（见 `prompts/init/references/tpl_input_derivable.md`）。
3. 子代理只写 `ir/input_derivable_patch.yaml`（及必要时把简单 DIAG 仍写入
   `resolution_patch`——本任务以 input_derivable patch 为主）。
4. **仅 `confidence: high`** 可把 KEY 标为 `true` 或 `not_input_derivable`。
5. 父代理重跑 classify + **`check_final_confidence.py`** + contract/sqlite 导出。
6. 仍无法 high → 写 `summary/confidence_report.md`（中文原因）；**禁止伪标 high**。
   详见 `confidence-gate.md`。

```powershell
python -X utf8 "$SCRIPT_DIR/classify_input_derivable.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
python -X utf8 "$SCRIPT_DIR/check_final_confidence.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
python -X utf8 "$SCRIPT_DIR/kb_query_export.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --view testcase-contract
python -X utf8 "$SCRIPT_DIR/export_kb_graph.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
```

## 子代理要做什么（连断裂）

对每个 gap `target`（如 `KEY_ISNZOUT`）：

1. 读 gap 的 `host_parent`、`gap_kind`、`tried_frontier`；沿图 `writes`/`derives` 到 Host 符号与 `file_path`（勿依赖 key_cards）。
2. CBM：对 `host_parent` / 赋值表达式里的符号 `get_code_snippet`（禁止整文件）。
3. 判断：
   - 能接到 Attribute / Input / OptionalInput / Shape / DType / Layout →  
     `input_derivable: true` + `derivation_roots` + 一跳 `host_parent`
   - 明确是核内局部 / 分批索引（如 blockId）→ `not_input_derivable: true`
   - 证据不足 → **不要**写 true；留在 gaps（父代理汇总）
4. 目标是**补语义连接**（父级与输入根），不是查已建成的 KB 问答。

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

- `ir/unresolved.yaml`：桥接/抽取诊断（unused TDF 等）→ `resolution_patch.yaml`
- `ir/input_derivable_gaps.yaml`：KEY 能否从 Host 输入面推导 → `input_derivable_patch.yaml`

两者都由 **`uo-semantic-resolve`** 处理；都不要在 init 转去 uo-query。
