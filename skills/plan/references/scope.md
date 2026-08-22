# 测试用途

本步给后续 `plan_fuse` 一份 **Planning Context**：这次测什么、碰到哪些维/路径、哪些列是编码控制面。不是 bind 第三路，不是正式 `tg/plan.md`。

读 `tg/init.yaml` 和 `runs/.../receipts/plan_scope_packet.yaml`。包里已做标识符预取，**不要 around**。无 PR diff 时用途来自用户意图 / CE plan / L0，不要假装有改动清单。

禁止枚举全量 TilingKey。禁止写正式 `tg/plan.md`。身份字段由框架写入，不要从 stub 抄进文首 YAML。

## 输入 / 输出 / 停

读：`tg/init.yaml`（列、mapping.role / encoding、call、精度/性能入口）、改动包、可选 `ce/plan/*_plan.md` / `session_handoff.md`。

写：`runs/.../actions/plan_scope/parts/purpose.md` 一篇短文。

完成：fuse 能直接引用这份用途，不必再派自由查询。缺这份草稿时 fuse/promote 失败并回到本步。

## 步骤

1. **读 init。** 调用接口 `call.kind`、API 入参列、`script_meta`、encoding 警告。这些是控制面事实，不要改口径。
2. **读改动包。** `has_diff` 为假 → 写明「无 diff，按意图 / L0」。为真 → 用包里的 ident 卡（kind / file:line），缺的再用**一个标识符**补查，不要扫全图。
3. **写成用途，不是义务表。** 说明：测哪条路径、哪些维会被碰到、哪些列是打包/前缀和/别名所以不能按字面填。点名 3–8 个维或路径即可。
4. **冲突先写下来。** 例如 profile 比产品覆盖更宽、encoding 会让「看起来合法」的列值对不上算子。留给 fuse 做 `untestable` / `test_harness_gap`，本步不编造义务行。
5. **精度/性能只点名入口。** 引用 init 里的 harness mode，不要在本步设计阈值。Host HIT 不是精度口径。

## 常驻判断

正式产物仍只有三份：`init.yaml` → `plan.md` → `worklog.md` + cases。purpose 是 run 草稿，fuse 把它收进计划上半散文。

禁止另写意图 YAML，也不要把本步当成审查。审查不是测试用途的前置。

查图四种形态见 code-access 不变量。包已跳过 around；本步默认也不 around。需要覆盖列表时用 `Dim=<维名>`，组合过滤用 `Name=Value`。

默认 L0 仍然要能 root 到列：每维点一次还不够写进 plan，但本步至少要说「没有特殊意图时测哪些入口」。

## 看到这样

| 现象 | 判断 |
| --- | --- |
| 包里 has_diff=false | 用途来自意图 / CE plan / 默认 L0 |
| 想写完整 Key 清单 | 停止；点名路径即可 |
| 想开始写 plan.md YAML 围栏 | 那是 fuse，本步只写 purpose.md |
| 列的 encoding 说是前缀和 | 写进用途，提醒 fuse 不要当物理长度 |
| 想在 init 与 plan 之间自由连查 | 禁止；本步就是那次调查 |
| mapping 只有 script_meta | 写明没有 API 控制面，fuse 会闸门 |

## 完成勾选

- [ ] 文首能一句话说清这次测什么
- [ ] 点名了会碰到的维或路径（3–8 个），没有全量 Key 清单
- [ ] encoding / 打包列的坑已经写给 fuse
- [ ] 无 diff 时没有假装有 PR 焦点
- [ ] 没有写正式 `plan.md`，没有 YAML 义务表围栏

## 循环

ident 卡不够时最多再查几个单标识符。不要把本步变成第二轮 bind。不要把用途写成审查评论。

用户意图、CE「测试内容」节、handoff 三者冲突时，写清冲突并让 fuse 闸门，不要静默选一边。

## 产物形状

`purpose.md` 用短节即可，例如：

- 这次测什么（一段）
- 会碰到的维 / 路径（列表）
- 编码控制面（哪些列不能按字面填）
- 已知缺口（缺列、profile 宽于产品面）

不要在文末再贴一份义务表。那是 `plan_fuse` 的 YAML 围栏。

## 停

`purpose.md` 落盘即停。下一状态是 fuse。不要自称已批准。

用途写完后，主控直接进入 fuse，不要再派一轮自由查询。

