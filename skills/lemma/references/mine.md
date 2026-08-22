# 证明引理

只处理已经写成「若 P 则 Q」的线索。主动找反例。本步只出证书草稿，交给下一步审查；不自己决定能不能写进排除集，也不填 review。

问：在给定前提下，是否存在合法执行路径可以推翻这个结论？未找到 ≠ 不存在。也可读 `skills/source-proof/SKILL.md`（同一套完成条件）。

## 输入 / 输出 / 停

读：lead pack（每条应已是可反驳的 P⇒Q）、相关源码窗口、Replay 观测（若有）。没有明确 antecedent→consequent 的「感觉正确」不是引理，退回 analyze 窗。

写：本 Action `parts/` 里的证书草稿。不得写 excluded 集。不得改 `.uo`。

完成：每个候选 `PROVED` | `REFUTED` | `INSUFFICIENT`，附源码窗口。

## 步骤

1. **写成最小命题。** 前提 P ⇒ 结论 Q。观测绑定义务：若命题来自 REWRITE/REFUSE，须解释走了哪条入口、为何改写或拒绝。禁止把构造器先验拒采写成源码不可达。
2. **分解义务并关闭。** 入口、控制流、赋值、调用、后续覆盖、替代路径。每项 `OPEN | CLOSED | BLOCKED`。漏入口、写点声明为 partial、调用目标未解析 → 不得 `PROVED`。关闭法见 `skills/source-proof/SKILL.md`。
3. **先结构查询，再读窗口。** 先查图拿 span，再按 `file:line` 开最小窗口。partial 索引不能证明不存在。Grep 只作定位辅助。
4. **主动找反例。** 其他入口、第一行分流、模板/宏/重载、alias、保存-修改-恢复。Host/Kernel 条件须经 TilingKey 映射，跳过 TemplateArg 的跨层蕴含通常错误。
5. **出证书。** 最低字段见 `skills/source-proof/SKILL.md`。只贴 `file:line` 不够——必须有推理链 + 无后续覆盖。反例检查必须做过；声称 none 要可信。

## 常驻判断

语义结论只有 `PROVED | REFUTED | INSUFFICIENT`。能不能写进排除集由下一步审查决定；本步不升级 exclusion。

假证模式（详见 `skills/source-proof/SKILL.md`）：

- 漏入口 / 第一行分流
- 搜索耗尽当不可达
- domain 当可达域（value domain ≠ reachable domain）
- derived 当 exact
- 复合赋值 / 容器写漏记
- 把所有 failure return 扔掉从而放宽合法域
- 无观测写运行时不可达
- 把运行时观察当成宏/模板的必然条件

宏条件保留编译期出处。审查必须另开上下文；自审自批无效。

## 看到这样

| 现象 | 判断 |
| --- | --- |
| 线索不是 P⇒Q | 退回，不要硬证 |
| 漏了第一行分流 | 不得 PROVED |
| 写点集合 partial | 该项 BLOCKED |
| 索引 count:0 | INSUFFICIENT，不是 REFUTED |
| 只有 Host reject | 不够当源码不可达 |
| 静态 domain 很窄 | ≠ 可达域 |
| 有 REWRITE/REFUSE | 必须解释入口与原因 |
| 想写 excluded | 禁止 |

## 完成勾选

- [ ] 每个候选是 `PROVED` / `REFUTED` / `INSUFFICIENT` 之一
- [ ] 每条 CLOSED 义务有源码窗口和推理链
- [ ] 反例检查做过
- [ ] 只写了 `parts/`，没有填 review、没有写排除集

## 循环

1. 取出下一条线索。不是 P⇒Q 就退回。
2. 列义务清单（入口 / 控制流 / 写点 / 调用 / 覆盖 / 替代路径）。
3. 先查图拿 span，再开窗口。主动找反例。
4. 能关的标 CLOSED 并引用窗口；不能关的 OPEN/BLOCKED。
5. 出三选一结论。partial 不得 PROVED。停，把 review 留给裁判。

## 输出形状

```text
result: PROVED | REFUTED | INSUFFICIENT
claim: P ⇒ Q
obligations: entry/control/writes/calls/overwrite/alternatives/completeness
  各 CLOSED|OPEN|BLOCKED，CLOSED 必有 file:line
counterexample: none | {condition, path}
```

只贴行号不算证书。本步不写 excluded。

## 指针

证明方法与假证：`skills/source-proof/SKILL.md`。
