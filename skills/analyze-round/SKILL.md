---
name: analyze-round
description: 为本轮构造写 worklog：场景、收窄、引理线索。执行 analyze_round 时使用。
---

# 写本轮记录

为本轮已构造的行写 worklog：场景与命中、构造、收窄、引理线索。权威闭合证据是 Host Replay 与经审查的源码引理。本步不签发、不改 cases 表、不写证书森林。

worklog 文首 `open:` 列出仍开放的义务。open 非空不得假装本轮已闭合。需要改构造就保持 open。

## 输入 / 输出 / 停

读：本轮草稿行、Replay 收据、计划义务、init 列。写：本轮 worklog 草稿。

完成：本轮草稿能说明每条义务怎么被观察或为何仍开放。

没有 Replay 收据时，不要用「看起来能过」关闭 dispatch/key 义务。没有经审查引理时，不要用搜索失败关闭不可达义务。

## 步骤

1. **按 case 写四段。** 每一行：(a) 场景与命中（对上哪条义务、Host 是 HIT / REWRITE / REFUSE / CRASH）；(b) 构造（控制列取了什么、recipe 复算了什么）；(c) 收窄（这条观测排除了什么、还剩什么）；(d) 引理线索（若有 P⇒Q，写成可反驳命题，不要写「感觉正确」）。
2. **Replay 怎么读。** HIT 可增长 dispatch/key 的 R。REWRITE / REFUSE 是观测，供引理，不是 E。CRASH / NOT_RUN 是环境，禁止写 E，也不是 golden 失败。`Replay reject ≠ E`。
3. **精度 / 性能另算。** Host 命中 TilingKey 关不了 `P-*` / `F-*`。这些看 harness 收据。缺收据 → 保持 open，标 `harness_missing`。
4. **硬命题指针。** 需要证明或反驳线索时读 `skills/source-proof/SKILL.md`。出证书由 `skills/lemma-mine/SKILL.md` 做；本步只挂线索，不升级 exclusion。
5. **open 清单。** 文首列出仍开放的义务 id 与原因。能关的写清证据窗口；不能关的写还缺什么观测或哪条引理。

## 常驻判断

正式产物是 `worklog.md` + cases 表。不要再写 `tg/closure/**`。引理 span 来自查图；Grep 只作定位辅助。

禁止：

- 把 Host reject 写成源码不可达
- 把搜索失败写成「不存在」
- 无观测写运行时不可达
- 用精度失败解释 dispatch 未命中，或反过来

需要改构造（行填错列、recipe 算错、shape 不合法）→ 保持 open，回到构造，不要在 worklog 里「解释掉」。

完整性用语（全部 / 唯一 / 从不）依赖经审查引理或覆盖字段。本步最多提出线索。

## 看到这样

| 现象 | 判断 |
| --- | --- |
| HIT | 可收窄 dispatch/key；写进该 case 命中段 |
| REWRITE / REFUSE | 观测；挂引理线索，不是 E |
| CRASH / NOT_RUN | 环境；open，禁止写 E |
| 精度/性能无 harness 收据 | `harness_missing`，保持 open |
| Host key 命中 | 关不了 `P-*` / `F-*` |
| 行填错列 / recipe 错 | 保持 open，回构造 |
| 「搜索没找到」 | 不是不可达；最多挂证明线索 |

## 完成勾选

- [ ] 每个 case 有四段：场景与命中、构造、收窄、引理
- [ ] 文首 `open:` 与正文一致；能关的有窗口，不能关的有原因
- [ ] 没有用 Replay reject 当源码不可达
- [ ] 没有签发、没有写证书森林

## 循环

按 case 走，不要按「我觉得本轮过了」走。

1. 写下这条行对应哪条义务、控制列取了什么。
2. 写下 Replay / harness 收据。没有收据就 open。
3. 收窄：这条观测排除了什么、还剩什么。排除不了的不要写死。
4. 若有 P⇒Q，挂线索，不要在本步 PROVED。
5. 更新文首 `open:`。空了才能谈闭合；非空必须列原因。

worklog 是给下一轮构造和引理看的。写不清「还缺什么」，下一轮就会假装已经闭合。

## 输出形状

文首：

```text
open: [义务id — 原因]
```

每个 case 四段：场景与命中、构造、收窄、引理线索。HIT/REWRITE/REFUSE/CRASH 写在命中段，不要混进精度结论。

## 指针

失败模式（残差停滞 / 假 gap=0 / R-E 冲突）：`references/failure-patterns.md`。硬命题：`skills/source-proof/SKILL.md`。证明引理：`skills/lemma-mine/SKILL.md`。
