# 生成引理线索包

## Goal

从**构造→回放观测**生成引理线索封闭包；统计 mine 只作辅助排序。

## Input Interpretation

仅处理 `acp next` 提供的当前 unresolved / target 子集与上下文包。  
优先读取：最近 search-round 的 rewrite/refuse 行（corpus 中的 `_target_key` / `_target_hit` / `_mismatch_dims` / `reject`）。

## Domain Procedure

1. 由 deterministic engine 分类 Host 观测：HIT / REWRITE / REFUSE（排除 HOST_CRASHED / NOT_RUN / parse failure）。
2. 仅将 REWRITE / REFUSE 聚类为 lead（绑定 observation id、when、mismatch / reject family）。
3. 可调用 `mine.mine_pairs/triples` **过滤/排序** lead，不得单独发明无观测支撑的 lead。
4. 写封闭包 `tg/closure/lemmas/leads.yaml`；每条 lead 预填 `evidence_path: tg/closure/lemmas/evidence/<lead_id>.yaml`。
5. producer 不得自行发明 lead；不得把 `construct_reasons` 假设直接拷成 lead。

## Domain Decisions

- 证据规则见 capability `tilingkey-closure`，勿在本文件复制。
- **没有 oracle observation，就不允许产生 lemma lead。**

## Output

- 合同 id：`lemma-leads-v1`
- 不得写声明外路径。

## Cannot Decide

- 尚无构造/回放观测 → 回到 construct/search，不写空 lead 充数
- 证据不足 → unresolved / needs_human

本文件不得描述 Pilot advance、complete 或其他阶段。
