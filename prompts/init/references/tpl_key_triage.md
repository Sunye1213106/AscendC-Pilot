## Task

对宿主给出的待解 KEY 列表做**粗分**（只分类，不闭合）。写出 `ir/key_triage.yaml`，供父代理按复杂度分流派发。

## Target

KEY ids：`<KEY_IDS>`

## Context

- UO_ROOT: `<UO_ROOT>`
- 读：`<UO_ROOT>/ir/input_derivable_gaps.yaml`（及 escalate_keys / residual 中的 KEY）
- 可扫：Host `file_path` 邻接摘要（勿整文件倾倒）
- Agent：`agents/uo-key-resolve.md`（mode=triage）

## Authoritative Sources

1. gaps / KEY 名 / Host 邻接
2. 下方粗分启发式（可覆盖，须写理由）

非权威：记忆猜测、宽仓库扫描。

## 粗分启发式

| complexity | 典型信号 | 后续派发 |
|---|---|---|
| `complex` | 依赖 shape/layout/分轴(SplitAxis)/sparse/deter/NZ(IsNzOut)/多字段联合谓词 | **一 KEY 一** `uo-key-resolve` |
| `simple` | empty_tensor、纯 regbase/模板开关、一眼可读的宏/常量、无 shape 表达式 | **多 KEY 打包**（≤6，同主题优先） |

拿不准 → 标 `complex`（宁可单派，勿把难 KEY 打进 batch）。

## Required Procedure

1. 枚举宿主 KEY 列表（勿增删 id）
2. 对每个 KEY：看 gap_kind / set_by / 名称信号 → 标 `complex|simple`
3. 为 simple 填可选 `batch_hint`（同主题短标签，便于父代理组批）
4. 写 `ir/key_triage.yaml`；**禁止**写 input_derivable 闭合字段
5. 汇报计数后 stop

## Hard Constraints

- MUST NOT：在 triage 里标 confidence/high 或闭合 gaps
- MUST NOT：发明列表外 KEY
- ONLY write：`<UO_ROOT>/ir/key_triage.yaml`
- Cap ~12 tool calls

## Output Schema

```yaml
version: 1
confirmed_by: llm
keys:
  - key_id: KEY_...
    complexity: complex | simple
    batch_hint: <可选短标签，simple 用>
    reason: <中文一句>
```

## Acceptance Criteria

- 每个输入 KEY 恰好一条
- complex/simple 均有中文 reason
- 无闭合字段、无假 high

## Failure Handling

无法判断 → `complexity: complex` 并说明；勿丢弃 KEY。
