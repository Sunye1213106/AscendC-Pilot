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
| A | **可控面** | 逐列读 `init.yaml` 的 `control.status` / `confidence`，给出「可做确定 classifier 的列」集合 = `confirmed` + `active`。其余列（`partial` / `unresolved` / 非 `active`）**不得进入 plan 的 `controls` 或 `construct_hint.columns`**，只能在 `test_harness_gap` 的自然语言里描述并登记 `needs_binding` 提级 |
| B | **触发门禁** | 把主行为成立的条件写成**合取式**，逐项标注：由哪个列控制 / 该列 confidence / 还是「非列」（平台常量、环境值、内部派生量）。漏项等于让 fuse 建一个永远 MISS 的 Target |
| C | **可达性** | 现有 case 表里，同时满足 B 全部合取项的行数是多少。答**具体数字**。为 0 就明说 0，并指出是缺哪几项 |

| D | **新增 vs 既有** | 本次改动**引入**的符号，与同一文件里**原本就有**的符号，必须分开说。判不准的标「未证实」，不要并列成「新增了 X、Y、Z」 |

B 的合取项要一直拆到「单个列能否控制」这一层。典型漏项：奇偶 / 对齐 / 下界这类形状约束、核数与平台常量的关系、某个取值会**提前返回**而保持默认值。

C 的省力算法：`init.yaml` 的 `domains.<col>.profile` 已有每列的**边缘分布**（`topk` 计数、`min` / `max`、`n_unique`）。联合命中行数 **≤ 各门禁列边缘命中数的最小值**，先用这个取上界；上界已经很小（或为 0）就不必读全表。只有上界不够判定时，才去 case 表做联合筛选。

C 为 0 是常态而非异常，直说即可 —— 这正是 fuse 要写 `test_harness_gap` 的依据。

说 A 项时别用「可参与构造」这类含糊话。非 `confirmed`+`active` 的列在 plan 里**没有任何合法位置**（引擎对 `controls` 与 `construct_hint.columns` 用同一套校验）。要表达「构造这条 case 需要这些列」，说清它属于 `needs_binding`，由 fuse 写进 `test_harness_gap`。

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
3. 出四项必答（A 可控面 / B 触发门禁 / C 可达性 / D 新增 vs 既有）。
4. 说清：主行为、使它不成立的条件、还不确定的轴。原始 B/N/S/D 默认只是 control。
5. 没有确定性证据的东西，标明「未证实」，不要升级成已绑定 Target。

## 看到这样

| 现象 | 判断 |
| --- | --- |
| 对话没指定方向 | 说清：当前只能测 Host 已接受的 dispatch |
| 用户说按 PR 出 case | 说清改了哪类行为，不要按 diff 行铺开 |
| 门禁项里有列是 `partial` / `unresolved` | 照实说该项无法确定控制，列 `needs_binding`；不要绕过 |
| 门禁项不是任何列（平台常量 / 派生量） | 明说「非列可控」，让 fuse 登记 `untestable` |
| C 数出来是 0 行 | 直说 0，并列出缺失的门禁项；这是 `test_harness_gap` 的依据 |
| 测试脚本仓看不到目标字段 | 先问 Replay；不要直接判成覆盖缺口 |
| 想写 YAML / plan.md / 文件 | 禁止；这窗只回答 |
| 想写 L0–L3 | 交给 fuse + Primary 散文 |

## 反模式

- 交 `targets.yaml` 或任何磁盘产物
- 把「可能有关」写成已经确认的 UO 绑定
- 把既有符号说成本次新增（D 项就是防这个）
- 只说「门禁大致是确定性 + 某类稀疏」，不拆到列级（B 项就是防这个）
- 跳过 C 直接说「corpus 覆盖不足」——不给数字等于没答
- 没搞懂就退回全量 TilingKey 枚举
- packet 无 change_contract 时把目标改成「测当前实现」（引擎不会让本窗见到未 pin 的 PR）
- 把 clone 回执或 Host run state 当成已 pin 的 PR 文件集
- 在本窗回答里写 `PLAN_PR_CHANGE_REQUIRED` 或解析 return_value 当控制失败

## 停

四项必答齐 + 主行为说清即停。下一窗是 fuse（YAML）和 Primary（散文）。
