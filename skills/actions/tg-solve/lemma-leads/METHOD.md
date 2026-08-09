# 生成引理线索包

## Goal

从**构造→回放观测**生成引理线索封闭包；统计 mine 只作辅助排序。

## Input Interpretation

仅处理 `acp next` 提供的当前 unresolved / target 子集与上下文包。  
优先读取：`construct/targets.yaml`、`explain` 产物、最近 search-round 的 rewrite/refuse 行。

## Domain Procedure

1. 收集 open 上已回放且非 HIT 的观测：REWRITE（要的→给的）、REFUSE。
2. 将稳定组合写成 lead（绑定观测 id / case 摘要）。
3. 可调用 `mine.mine_pairs/triples` **过滤/排序** lead，不得单独发明无观测支撑的 lead。
4. 写封闭包 `tg/closure/lemmas/leads.yaml`。
5. producer 不得自行发明 lead；不得把 `construct_reasons` 假设直接拷成 lead。

## Domain Decisions

- 证据规则见 capability `tilingkey-closure`，勿在本文件复制。

## Output

- 合同 id：`lemma-leads-v1`
- 不得写声明外路径。

## Cannot Decide

- 尚无构造/回放观测 → 回到 construct/search，不写空 lead 充数
- 证据不足 → unresolved / needs_human

本文件不得描述 Pilot advance、complete 或其他阶段。
