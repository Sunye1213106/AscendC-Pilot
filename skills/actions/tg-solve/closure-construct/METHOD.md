# 构造式收尾

## Goal

对 open / distance-1 目标做 **best-effort 构造**，产出可回放 case；不在此步判定不可达。

## Input Interpretation

仅处理 `acp next` 提供的当前 unresolved / target 子集与上下文包。

## Domain Procedure

1. 列出目标（优先 distance-1，可扩到更远 open）。
2. 对每个目标调用 inverse construct（`construct_case` / hints）。
3. **禁止**因 `construct_reasons` 非空而跳过；理由只写入观测/explain。
4. 写 `tg/closure/construct/targets.yaml`（目标 key、case 摘要、诊断假设）。
5. 完整 construct+replay 依赖 Host oracle；本 action 不写 R/E。

## Domain Decisions

- 证据规则见 capability `tilingkey-closure`，勿在本文件复制。
- Schema 范例：`capabilities/tilingkey-closure/examples/construction_hints.excerpt.yaml`。
- 构造失败（引擎无法编码 knobs）→ 记 `constructor_gap` 观测，转 explain / harness，**不是** lemma。

## Output

- 合同 id：`closure-construct-v1`
- 不得写声明外路径。

## Cannot Decide

- 证据不足 → unresolved / needs_human
- 缺工具或 gate 前置 → 停止并回报 blocking reason

本文件不得描述 Pilot advance、complete 或其他阶段。
