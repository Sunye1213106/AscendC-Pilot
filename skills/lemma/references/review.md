# 审查引理

复查上一步写出的证书。搜索失败或单次 Host reject 单独不能升级为 exclusion。本步不另开新命题，不重新做一遍开放式源码研究，不改上一步草稿正文。

任务是验证：claim 是否明确、CLOSED 义务的证据是否真的证明该义务、枚举是完整还是 partial 却声称「全部」。

## 输入 / 输出 / 停

读：证书草稿、其 citation 指向的源码窗口、当前 Replay 事实。写：accept / reject / defer 的裁决，不要发明缺失 citation。

完成：每条升级都有源码窗口；否则保持开放。

缺外部信息（源码不可读、宏上下文未知）且无法当场关闭 → defer，不要用「看起来对」accept。

## 步骤

1. **claim 是否为 P⇒Q。** 没有明确 antecedent→consequent → reject。观测命题是否解释了 REWRITE/REFUSE，还是把先验拒采写成不可达。
2. **逐项 replay CLOSED 义务。** 入口、控制流、写点、调用、后续覆盖、替代路径。证据窗口是否覆盖该义务。标 CLOSED 但 citation 对不上 → reject。
3. **完整性。** 写入/调用枚举声称「全部」时，completeness 必须是 full。partial 却 PROVED → reject。第一行分流、后续覆盖、别名写是否漏掉。
4. **反例检查。** 声称 none 是否可信。Replay 已出现反例 → 撤销规则，不是降级继续用。
5. **与当前事实冲突。** 证书与 Host HIT/REWRITE 打架 → reject。不得把未引用假设提升为已证明。

裁决：

| 结果 | 条件 |
| --- | --- |
| accept | 证书完整，义务关闭可信，无冲突，每条有源码窗口 |
| reject | 证据不足、推理断裂、与事实冲突、或发现反例 |
| defer | 缺外部信息且无法当场关闭 |

## 常驻判断

禁止：

- 搜索失败升级为 exclusion
- 裸 Host reject 当源码不可达
- 发明缺失 citation
- 上一步自己填 review
- domain 当可达域、derived 当 exact

value domain ≠ reachable domain。无观测不得声称运行时不可达。宏/模板条件保留编译期出处。

accept 之后才由确定性路径写入排除；本步不写 excluded 集，不改 `.uo`。

## 看到这样

| 现象 | 裁决 |
| --- | --- |
| claim 不是 P⇒Q | reject |
| CLOSED 但 citation 对不上 | reject |
| partial 却 PROVED | reject |
| Replay 已有反例 | reject（撤销，不是降级） |
| 搜索失败 / 裸 Host reject | 不得 accept 为 exclusion |
| 源码不可读 / 宏未知 | defer |
| 证书完整、无冲突、有窗口 | accept |

## 完成勾选

- [ ] 逐项 replay 过 CLOSED 义务，不是只看结论词
- [ ] 完整性声称与 completeness 字段一致
- [ ] 没有发明 citation，没有改上一步草稿正文
- [ ] 不能升级的保持开放

## 循环

1. 只读证书与其 citation。不要另开搜索当「补充证明」。
2. 先问 claim 是否为 P⇒Q，再逐项 replay CLOSED。
3. 核对 completeness：声称全部就必须 full。
4. 看反例检查与 Replay 事实是否打架。
5. accept / reject / defer。reject 时指出哪条义务的哪条 citation 断了。

## 输出形状

```text
verdict: accept | reject | defer
on: <claim>
broken: <obligation> <citation>   # reject 时必填
```

accept 才允许确定性路径写入排除。本步不写 excluded 集。

## 指针

replay 清单由本窗装载。证明方法与假证：`skills/source-proof/SKILL.md`。
