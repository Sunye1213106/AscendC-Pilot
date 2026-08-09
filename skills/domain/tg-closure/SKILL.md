---
name: tg-closure
description: >
  TilingKey 全覆盖闭环的领域方法：如何合法增长可达集 R 与排除集 E，
  何时继续搜索构造、何时转入源码引理、何时停止并审计。不描述 Pilot 编排。
---

# TilingKey 闭环

维护可审计闭环：声明域 D、可达集 R、排除集 E、观测 Corpus、候选模型、RuleBook。

安全不变量与负证据纪律：`references/closure-safety.md`。

## 核心循环

```text
oracle 就绪 → 构造/搜索 → Host 回放分类
 ├─ HIT → 增长 R
 ├─ REWRITE / REFUSE → 观测 → 可转引理
 ├─ CRASH / NOT_RUN → 修环境，禁止写 E
 → 残差：继续搜 / 引理 / 审计签发
```

## 何时 search / lemma / 停止

- **search**：仍可能有新命中；尚无可靠观测支撑引理
- **lemma**：饱和且有 REWRITE/REFUSE 观测；证明走 `domain/source-lemma-proof`
- **停止**：`GAP_ZERO` 且不变量成立；或 oracle 可疑；或完整性阻塞

Producer 只给 `PROVED|REFUTED|INSUFFICIENT`；是否进 E 由裁判与引擎决定。

## 按需参考

| 条件 | 文件 |
|---|---|
| R/E/负证据/未声明/冲突 | `references/closure-safety.md` |
| 假闭环踩坑 | `references/failure-patterns.md` |
| oracle 观测 | `references/oracle.md` |
| 搜索/构造 | `references/search.md` |
| 审计签发 | `references/certificate.md` |
| 旧证书能否用 | `_shared/artifact-freshness.md` |
| 源码证明 | `../source-lemma-proof/SKILL.md` |
