# 弄清要测什么（scope）

像 `uo-query`：把用户测试意图说清楚。不写 partition、不写 L0–L3、不造 case、**不写磁盘、不交产物文件**。最终消息用自然语言回答。Primary 读到即可。

## 输入 / 输出 / 停

读：`tg/init.yaml`、对话 / `--intent`、可选 CE plan / handoff、算子 `.ascendc-pilot/control/change_contract.yaml`（若已 pin）。改动文件只作方向线索，不要当覆盖清单。没有 pin 时禁止 `git diff HEAD`。`kind=pr_regression` 且 pin 的 `changed_files` 为空时，回答缺口是 `PLAN_PR_CHANGE_REQUIRED`，不要改口去测「当前实现」。generic TilingKey 仅 `kind=implementation_coverage`。`legal_keys` 仅 pin `enumerate: legal_keys`。

交回：一段说清楚「测什么」的回答。禁止 Write。禁止为了格式去凑 YAML。

完成：Primary 能据此写 plan 散文、fuse 能据此建覆盖模型。没说清就继续问，不要假装已经有 Target 表。

## 步骤

1. 读用户要测的行为（PR 改动、点名状态、或「把这个算子测明白」）。
2. 用 init 列和 UO 查询核对：这个行为能不能被 case 控制、Replay 能不能看见。
3. 说清：主行为、使它不成立的条件、还不确定的轴。原始 B/N/S/D 默认只是 control。
4. 没有确定性证据的东西，标明「未证实」，不要升级成已绑定 Target。

## 看到这样

| 现象 | 判断 |
| --- | --- |
| 对话没指定方向 | 说清：当前只能测 Host 已接受的 dispatch |
| 用户说按 PR 出 case | 说清改了哪类行为，不要按 diff 行铺开 |
| 想写 YAML / plan.md / 文件 | 禁止；这窗只回答 |
| 想写 L0–L3 | 交给 fuse + Primary 散文 |

## 反模式

- 交 `targets.yaml` 或任何磁盘产物
- 把「可能有关」写成已经确认的 UO 绑定
- 没搞懂就退回全量 TilingKey 枚举
- packet 无 change_contract 时把目标改成「测当前实现」
- 把 clone 回执或 Host run state 当成已 pin 的 PR 文件集

## 停

回答说清即停。下一窗是 fuse（YAML）和 Primary（散文）。
