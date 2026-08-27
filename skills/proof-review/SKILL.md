---
name: proof-review
description: 审查 source-proof 证书是否可信。已有 PROVED/REFUTED/INSUFFICIENT 证书、要决定 accept/reject/defer 时使用。不要用于补证、构造 case、或自行写 exclusion。
---

# 独立审证

复查已写出的证明证书。搜索失败或单次 Host reject 单独不能升级为 exclusion。本步不另开新命题，不重新做一遍开放式源码研究，不改证书草稿正文。

证明结果与审证裁决不是同一套状态：

```text
proof result:     PROVED | REFUTED | INSUFFICIENT
certificate review: accept | reject | defer
```

任务是验证：claim 是否明确、CLOSED 义务的证据是否真的证明该义务、枚举是完整还是 partial 却声称「全部」。completeness 的 `full` 必须能指到机器 receipt。

## 输入 / 输出 / 停

读：证书草稿、其 citation 指向的源码窗口、当前 Replay 事实。写：accept / reject / defer。不要发明缺失 citation。

完成：每条升级都有源码窗口；否则保持开放。缺外部信息且无法当场关闭 → defer。

## 步骤

1. **claim 是否为 P⇒Q。** 没有明确 antecedent→consequent → reject。layer 必须是 `domain` / `template` / `host` / `kernel`，不得是 `full`。
2. **逐项 replay CLOSED 义务。** 入口、控制流、写点、调用、后续覆盖、替代路径。标 CLOSED 但 citation 对不上 → reject。
3. **完整性。** 声称「全部」时，对应 `completeness.*.status` 必须是 `full` 且 `source` 非空。partial 却 PROVED → reject。
4. **反例检查。** 声称 none 是否可信。Replay 已出现反例 → 撤销规则，不是降级继续用。
5. **与当前事实冲突。** 证书与 Host HIT/REWRITE 打架 → reject。

## 看到这样

| 现象 | 裁决 |
| --- | --- |
| claim 不是 P⇒Q，或 layer=`full` | reject |
| CLOSED 但 citation 对不上 | reject |
| 自填 full、无 receipt | reject |
| partial 却 PROVED | reject |
| Replay 已有反例 | reject（撤销，不是降级） |
| 搜索失败 / 裸 Host reject | 不得 accept 为 exclusion |
| 源码不可读 / 宏未知 | defer |
| 证书完整、无冲突、有窗口 | accept |

## 完成勾选

- [ ] 逐项 replay 过 CLOSED 义务，不是只看结论词
- [ ] 完整性声称与 receipt 一致
- [ ] 没有发明 citation，没有改上一步草稿正文
- [ ] 不能升级的保持开放

## 输出形状

```text
verdict: accept | reject | defer
on: <claim>
broken: <obligation> <citation>   # reject 时必填
```

accept 之后由引擎写 exclusion。本步不写 excluded 集，不改 `.uo`。
