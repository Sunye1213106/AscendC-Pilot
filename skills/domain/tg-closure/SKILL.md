---
name: tg-closure
description: >
  TilingKey 全覆盖闭环的领域方法：如何合法增长可达集 R 与排除集 E，
  何时继续搜索构造、何时转入源码引理、何时停止并审计。不描述 Pilot 编排。
---

# TilingKey 闭环

维护可审计闭环状态：声明域 D、可达集 R、排除集 E、观测 Corpus、候选模型、RuleBook。

## 不变量

```text
R ∩ E = ∅
R 只来自真实 Host 命中裁决
E 只来自可审计证明（源码引理或求解器），且过反例检验
模型分数 / 统计共现 / 构造器拒采假设 不得进入 E
D = (R ∩ D) ∪ E 才允许宣称 gap=0
```

**未找到 ≠ 不可达。** 搜索失败不能写入 E。

## 核心循环

```text
oracle 就绪
 ↓
构造 / 搜索候选输入
 ↓
Host 回放分类
 ├─ HIT      → 增长 R
 ├─ REWRITE  → 记观测 → 可转引理
 ├─ REFUSE   → 记观测 → 可转引理
 ├─ CRASH / NOT_RUN → 修环境，禁止写 E
 ↓
残差评估
 ├─ 仍有进展 → 继续搜索
 ├─ 饱和且有观测 → 引理证明（见 domain/source-lemma-proof）
 └─ gap=0 候选 → 审计 → 签发
```

## 何时 search

- open key 仍可能通过新输入命中
- 构造/搜索仍能改善残差
- 尚无可靠 REWRITE/REFUSE 观测可支撑引理

## 何时 lemma

- 对剩余 open 已构造且回放，连续多轮无新 R
- 存在绑定观测的 lead（REWRITE 或非 crash 的 REFUSE）
- 证明走 `domain/source-lemma-proof`；本 Skill 不重复证明算法

引理生命周期：观测 lead → 证明证书 → 裁判 replay → 确定性 apply → E。  
Producer 只给 `PROVED|REFUTED|INSUFFICIENT`；是否进入 E 由裁判与引擎决定。

## 何时停止

- `GAP_ZERO`：D 被 R∪E 覆盖且不变量成立，经 audit
- `ORACLE_SUSPECT`：裁决不可信，停止当负样本
- 完整性阻塞：调用/写入闭包 partial 且无法关闭 → 保留 unresolved，不猜

## 角色

| 角色 | 认知任务 |
|---|---|
| 搜索/构造 | 找输入、跑 oracle、记观测 |
| 引理 producer | 构造证明证书 |
| 裁判 | replay 证书 / 审计闭环，不自由开新 hypothesis |
| 引擎 | ledger、apply、certify |

## 审计要点

- 每条 E 规则有源码或求解器证书
- 与当前 R 无冲突；冲突则 revoke
- Corpus 不含 CRASH/NOT_RUN
- 常量按名解析，禁止手抄易漂移数字

细节：`references/oracle.md`、`references/search.md`、`references/certificate.md`
