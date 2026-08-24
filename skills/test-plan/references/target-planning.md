# 弄清要测什么（scope）

像 `uo-query`：把用户测试意图说清楚。不写 partition、不写 L0–L3、不造 case、**不写磁盘、不交产物文件**。最终消息用自然语言回答。Primary 读到即可。

## 输入 / 输出 / 停

读：`tg/init.yaml`、对话 / `--intent`、可选 CE plan / handoff、算子 `.ascendc-pilot/control/change_contract.yaml`（已 pin 才会进本窗）。

改动文件只作方向线索，不要当覆盖清单。允许取**符号级**变更摘要来判定「本次新增 / 本次修改 / 未动」（`--stat`、`--function-context`、按符号名定位到最小行窗）。禁止把整份 diff 读进回答，禁止按 diff 行铺覆盖清单。禁止 `git diff HEAD`（PR checkout 工作区干净，该命令为空且无意义；要比就比 pin 住的 base..head）。

generic TilingKey 仅 `change_contract.kind=implementation_coverage`（且没有 PR clone_receipt）。`legal_keys` 仅本地覆盖 pin `enumerate: legal_keys`。PR 未 pin 时引擎停在 `plan_precheck`，本窗看不到该状态，不要在回答里写 `PLAN_PR_CHANGE_REQUIRED`。

交回：一段说清楚「测什么」的回答。禁止 Write。禁止为了格式去凑 YAML。

完成：四项必答齐备，Primary 能据此写 plan 散文、fuse 能据此建覆盖模型。没说清就继续问，不要假装已经有 Target 表。

## 四项必答

缺任何一项，fuse 就只能靠猜；宁可回答短，也要这四项齐。

| # | 必答 | 怎么答 |
| --- | --- | --- |
| A | **可控面** | 逐列读 `init.yaml` 的 `control.status` / `confidence`，给出「可做确定 classifier 的列」集合 = `confirmed` + `active`。其余列（`partial` / `unresolved` / 非 `active`）**不得进入 plan 的 `controls` 或 `construct_hint.columns`**，只能在 `test_harness_gap.needs_binding` 里点名提级 |
| B | **触发门禁** | 先 `uo_query` 出该行为字段的**唯一写点**，再从写点回溯到入口，把**到写点的路径条件**写成合取式 —— 沿途每个被跨过的 `if (...) return` 都贡献一个**否定项**。逐项标：**直接列** / **派生** / **环境** / **host 局部量**（有 `<name> =` 就能 probe，不是 opaque） / **真 opaque**（三层都观测不到）。漏否定 = 永久 MISS。派生和环境**不是** untestable |
| C | **构造种子** | 现有 case 表只提供 seed/default。答一个数字可以，但 **0 行不是 gap**，不要据此要求写 `test_harness_gap`。Solve 用 confirmed 列构造新行 |
| D | **新增 vs 既有** | 本次改动**引入**的符号，与同一文件里**原本就有**的符号，必须分开说。判不准的标「未证实」，不要并列成「新增了 X、Y、Z」 |

B 的合取项要一直拆到类别：直接列、派生、环境、可 probe 的 host 局部量、还是真 opaque。典型漏项：奇偶/对齐/下界（派生）、核数关系（环境）、提前返回、host 分支门被误标 opaque。

B 项最贵的两个错，都在「方向」上，说 B 项时必须一并交代：

- **漏否定。** 写点前面每一个 `if (cond) return` 都意味着路径条件里有 `¬cond`。只交正向合取式，Owner 建出来的 partition 常常恰好满足某个早退，Target 永久 MISS 而没有任何校验会报错。
- **抄错分支。** 同一个入口函数里，另一条 legacy / 兼容分支的入口门（它自己那串 `&&`）对本行为的路径条件**没有贡献**。把它当成前置约束交上去，等于帮那条早退成立。每报一个门禁项，都要能说出它是「到写点必须成立」还是「到写点必须不成立」。
- **误杀析取支。** 写点 RHS 含 `||` 时，先问：把一支取反后 expected 是否还能被另一支打到。能 → 那是 Dimension（切臂），不是「Target 不可达」的 Guard。

C 可以看 `init.yaml` 的 `domains.<col>.profile` 边缘分布当 **seed 线索**，但 **0 行不是 gap**，也不要去全表做「联合命中」来决定能不能测。Solve 用 confirmed 列构造新行。

说 A 项时别用「可参与构造」这类含糊话。非 `confirmed`+`active` 的列在 plan 里**没有任何合法位置**（引擎对 `controls` 与 `construct_hint.columns` 用同一套校验）。要表达「构造这条 case 需要这些列」，说清它属于 `needs_binding`。

## 载体分工

别把两个载体混成一个，否则会把「能观测」误判成「缺口」。

| 载体 | 出什么 | 说明 |
| --- | --- | --- |
| **Replay**（引擎能力） | `evidence` | TilingKey、TilingData 字段、blockDim、workspace。host 侧回放，不需要 NPU |
| **测试脚本仓** | `oracle` | 精度 / 性能 / 复现比对。**通常看不到任何 tiling 字段** |

测试脚本仓看不到 tiling ≠ 该状态不可观测。先问 Replay 能不能给。

提 Replay 字段时用**解码后的纯字段名**（`deterBandScheduleMode` 这种叶子名）。TilingData 在源码里是嵌套结构，但解码器展平且不带 struct 名 —— 顺手抄成 `s1s2BNGS1S2BaseParams.deterBandScheduleMode` 会被 fuse 照搬进 plan，然后该 Target 永远 `UNKNOWN`。

## 步骤

1. 读用户要测的行为（PR 改动、点名状态、或「把这个算子测明白」）。
2. 用 init 列和 UO 查询核对：这个行为能不能被 case 控制、Replay 能不能看见。
3. 出四项必答（A 可控面 / B 触发门禁 / C 构造种子 / D 新增 vs 既有）。
4. 说清：主行为、使它不成立的条件、还不确定的轴。原始 B/N/S/D 默认只是 control。
5. 没有确定性证据的东西，标明「未证实」，不要升级成已绑定 Target。

## 看到这样

| 现象 | 判断 |
| --- | --- |
| 对话没指定方向 | 说清：当前只能测 Host 已接受的 dispatch |
| 用户说按 PR 出 case | 说清改了哪类行为，不要按 diff 行铺开 |
| 门禁项里有列是 `partial` / `unresolved` | 照实说该项无法确定控制，列 `needs_binding`；不要绕过 |
| 门禁项是派生等式 | 标成 constraint，不要写成 untestable |
| 门禁项是平台常量 / 核数关系 | 标成 environment fact，不要写成 untestable |
| C 数出来是 0 行 | 直说 0；这只是 seed 线索，**不是** `test_harness_gap` |
| 测试脚本仓看不到目标字段 | 先问 Replay；不要直接判成覆盖缺口 |
| 想写 YAML / plan.md / 文件 | 禁止；这窗只回答 |
| 想写 L0–L3 | 交给 fuse + Primary 散文 |

## 反模式

- 交 `targets.yaml` 或任何磁盘产物
- 把「可能有关」写成已经确认的 UO 绑定
- 把既有符号说成本次新增（D 项就是防这个）
- 只说「门禁大致是确定性 + 某类稀疏」，不拆到列级/派生/环境（B 项就是防这个）
- 把 corpus 0 行说成覆盖缺口 —— C 不是可达性门
- 没搞懂就退回全量 TilingKey 枚举
- packet 无 change_contract 时把目标改成「测当前实现」（引擎不会让本窗见到未 pin 的 PR）
- 把 clone 回执或 Host run state 当成已 pin 的 PR 文件集
- 在本窗回答里写 `PLAN_PR_CHANGE_REQUIRED` 或解析 return_value 当控制失败

## 停

四项必答齐 + 主行为说清即停。同一 Task 接着写 Coverage IR YAML，不要再交给另一个 agent。
