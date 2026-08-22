# 识别独立测试变量

本步给 fuse 一组**正交、可单独取值**的独立变量：这次要命中哪些代码状态。

对话优先：没点方向 → TilingKey 维；点了「按 PR 设计」→ 才读 diff；点了场景 → 才对代码。相关状态先归并，能单独改的才进表。

写 `runs/.../actions/plan_scope/parts/targets.yaml`。观测、L 档、正式 `plan.md` 是 fuse 的事。包里已预取标识符，直接用包。

## 输入 / 输出 / 停

读：`tg/init.yaml`（列、encoding、call、已声明的 TilingKey 维）、改动包、对话 / `--intent`、可选 `ce/plan/*_plan.md` / `session_handoff.md`。

写：`parts/targets.yaml`。

完成：`intent` 已填；`variables` 非空且彼此正交；fuse 能直接引用这份表。缺这份时 fuse/promote 失败并回到本步。

## 步骤

1. **读 init。** 列、encoding、mapping。TilingKey 维来自 UO / init 已声明的 key 维（dtype、layout、s1/s2 形态等）。
2. **判对话有没有指定方向。**
   - 没指定 → `intent: default_tilingkey`，独立变量 = 这些 TilingKey 维。
   - 「按 PR 设计」→ 用改动包 ident 卡，从关键表达抽出受影响状态，**合并成正交变量**。
   - 点名场景（确定性、kvMerge、tail）→ NL 对到代码符号，列出被这条路径影响的状态，相关的并、独立的分。
3. **归并。** 能单独改的才进表；Host 派生字段并进控制它的那个变量。每个变量写 `id`、`kind`、`symbol`；点名场景时加 `why_independent`。
4. **encoding 坑留给 fuse。** 前缀和 / 打包列写进草稿备注。
5. **冲突写下来。** 用户意图、CE「测试内容」、handoff 不一致时点名冲突，让 fuse 闸门。

## 常驻判断

正式产物仍是 `init.yaml` → `plan.md` → `worklog.md` + cases。本步只交 run 草稿。

补查只查本步还缺的标识符。包已跳过 around。覆盖链可以多个变量，但必须先归并。

## 看到这样

| 现象 | 判断 |
| --- | --- |
| 对话没指定方向 | TilingKey 各维；`intent: default_tilingkey` |
| 用户说按 PR 出 case | 读 diff / ident 卡，合并正交变量 |
| 用户说「确定性」「kvMerge」 | 对到代码，相关的并、独立的分 |
| 包里 has_diff=false | 走对话默认，不当成 PR 焦点 |
| 想列完整合法 Key | 列维 |
| 想写 direction / evidence / ladder | 交给 fuse |
| 列 encoding 是前缀和 | 备注给 fuse |

## 完成勾选

- [ ] `intent` 写清：默认 TilingKey / PR / 点名场景
- [ ] `variables` 非空、彼此正交
- [ ] 无指定方向时 `intent` 是 `default_tilingkey`
- [ ] 落盘的是 `targets.yaml`，不是正式 `plan.md`

## 循环

1. 读 init 与对话。未指定 → TilingKey 维。
2. 指定了再查 ident / 单符号。
3. 合并正交变量。冲突写进草稿。
4. `targets.yaml` 落盘即停。

## 输出形状

```yaml
intent: default_tilingkey
variables:
  - id: V-dtype
    kind: tilingkey_dim
    symbol: InputDType
  - id: V-layout
    kind: tilingkey_dim
    symbol: Layout
```

点名场景时多 `why_independent`。

## 反模式

- 有 diff 就按 Changed Targets 铺开（用户没点 PR）
- 把不能独立取的派生字段拆成维
- 本步写 evidence 或 L0–L3
- 枚举全部合法 TilingKey

## 停

`targets.yaml` 落盘即停。下一状态是 fuse。
