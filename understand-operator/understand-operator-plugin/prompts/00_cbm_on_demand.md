# CBM On-Demand Query Protocol

Phase 0 只做 **CBM 索引**（`cbm/index_meta.json`）。语义查询在各 phase **按需**调用 `cbm_query.py`。

## Windows / PowerShell（优先）

**不要**把 JSON 作为位置参数传入（易被 PowerShell 拆碎、引号丢失）。请用 **简写参数** 或 **`--payload-file`**。

```powershell
# 推荐：简写参数（无需 JSON）
python "$SKILL_DIR/cbm_query.py" "$PROJECT_ROOT" search_graph `
  --op-name "$OP_NAME" --phase phase1 `
  --name-pattern ".*FlashAttentionScoreGrad.*" --label Function

python "$SKILL_DIR/cbm_query.py" "$PROJECT_ROOT" search_code `
  --op-name "$OP_NAME" --phase phase1 `
  --code-pattern "tiling_key"

python "$SKILL_DIR/cbm_query.py" "$PROJECT_ROOT" trace_path `
  --op-name "$OP_NAME" --phase host `
  --function-name FlashAttentionScoreGradTiling --depth 5

python "$SKILL_DIR/cbm_query.py" "$PROJECT_ROOT" get_code_snippet `
  --op-name "$OP_NAME" --phase host `
  --file "op_host/flash_attention_score_grad_tiling.cpp" `
  --symbol FlashAttentionScoreGradTiling
```

复杂 payload 写文件再传：

```powershell
@'
{"query": "MATCH (f:Function) WHERE f.name CONTAINS 'Tiling' RETURN f.name, f.file LIMIT 20"}
'@ | Set-Content -Encoding utf8 "$UO_ROOT/cbm/_last_payload.json"

python "$SKILL_DIR/cbm_query.py" "$PROJECT_ROOT" query_graph `
  --op-name "$OP_NAME" --phase phase1 `
  --payload-file "$UO_ROOT/cbm/_last_payload.json"
```

也可用命名参数 `--payload`（整段 JSON 一个参数）：

```powershell
python "$SKILL_DIR/cbm_query.py" "$PROJECT_ROOT" search_graph `
  --op-name "$OP_NAME" --payload '{"name_pattern": ".*Tiling.*"}'
```

**禁止**使用非 JSON 的伪参数（如 `query:foo bar,limit:20`）——会触发 argparse 错误。

## 简写参数对照

| tool | 简写参数 |
|---|---|
| `search_graph` | `--name-pattern`；可选 `--label` |
| `search_code` | `--code-pattern` |
| `trace_path` | `--function-name`；可选 `--direction`、`--depth` |
| `get_code_snippet` | `--file` + `--symbol` |
| 其他 / Cypher | `--payload-file` 或 `--payload` |

`project` 从 `cbm/index_meta.json` 自动注入。`repo` 参数必须是 **AscendC 算子仓库根**（Phase 0 索引过的那个路径），不是 understand-operator 插件目录。

## 输出与落盘

- 完整结果在 **stdout**（读命令输出里的 `result` 字段）
- 默认只追加一行到 `cbm/query_journal.jsonl`（摘要，非完整 body）
- `--save` 才额外写 `cbm/NNNN_<tool>.json`

## 证据获取顺序（CBM-first，强制）

全局规则见 `prompts/00_cbm_first_rule.md`。**每一步「查代码 / 找符号 / 看实现 / 跟调用链」的第一个动作都必须是 `cbm_query.py`。** 适用于宿主与所有 subagent。

1. 先 `cbm_query.py`（简写参数优先）
2. 从 stdout 提取符号、文件、行号
3. CBM 成功后：优先**带行号小范围** `Read` 核对片段；宏/模板/字符串 CBM 拿不全时也可小范围补读。
4. **仅当 CBM 失败**（空结果 / 报错 / 无法定位）时，才允许回退读源码；此时可整文件 `Read`（须先记录该次失败查询）。
5. **禁止**未查 CBM 就读源码；**禁止**以「快 / 稳 / 顺手」为由跳过 CBM。

## evidence 写法

```yaml
evidence:
  - type: cbm
    tool: search_graph
    phase: phase1
  args:
    name_pattern: ".*MyOpTiling.*"
    label: Function
    symbol: MyOpTiling
    file: op_host/my_op_tiling.cpp
    confidence: high
```

## 常见错误

| 现象 | 原因 | 修复 |
|---|---|---|
| `invalid payload JSON` | 单引号 JSON 或引号被 shell 吃掉 | 用 `--name-pattern` 等简写，或 `--payload-file` |
| `unrecognized arguments: query\:` | 把查询词当位置参数传入 | 改用 `--code-pattern` 或 `--name-pattern` |
| `project not found or not indexed` | `repo` 路径错，或 Phase 0 未 `--full` | 对算子仓库跑 `prepare_operator.py --full` |
