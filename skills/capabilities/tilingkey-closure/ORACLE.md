# Oracle 与观测纪律

阶段 0（`oracle_probe`）与观测绑定（`observations.yaml`）必须遵守本文件。
这些规则原先只写在算子包注释里；任何算子接入都适用。

## 1. `withheld_from`：防自证

用日志里打印的维度值去「预测」同一个 Key 维度，答案就是问题——不是检验。

- 每个观测必须记录它来自哪个维度（`withheld_from`）
- 当被预测的维度正是该观测的来源时，**必须扣掉**该观测
- 用同一中间状态去预测**另一个**读它的维度，才是真检验

## 2. 常量按名解析，禁止手抄数字

观测 / 规则里的常量只写**名字**（源码头里的 `constexpr` / 枚举名）。

- 名字在导出时解析；解析不到 → export **失败**（fail closed）
- 手抄数字会在 header 重编号当天变错，且没有任何 gate 能发现

## 3. 日志协议四槽分层

`log_protocol.yaml` 把两种打印源（driver 标记 + 算子 `OP_LOGD`）归入同一套槽：

| 槽 | 含义 |
|---|---|
| `marks` | driver 结构化标记；引擎只认命名捕获组（如 `case_id` / `ok` / `key`） |
| `scrapes` → `dim` / `state` / `series` | 从算子日志 scrape 进同名槽 |
| `reject` | 拒绝原因 |
| `report_state` | 哪些 state 进宽表列（未列出的仍被解析，只是不 widen 每行） |

纪律：

- scrape 的 `into: state` 行**故意不写**封闭 field 列表，以免下个版本新增的字段被静默丢掉；`report_state` 决定谁进宽表
- `into: series` 承载逐样本证据（循环内每条），聚合摘要不能替代它
- 阶段 0 判据：随便造约 10 个用例，能拿到 Key、各维取值、至少一个中间状态、以及非法用例的拒绝原因

## 4. 裁决三态

| 前缀 | 含义 | 可否进 Corpus |
|---|---|---|
| （无前缀 / 正常 reject） | Host 接受或明确拒绝 | 是 |
| `HOST_CRASHED` | driver 死在该用例 | 否 |
| `NOT_RUN` | 未实际执行（截断 / 重试耗尽） | 否 |

批次送入数与 `###DONE` 数不符 → `ORACLE_SUSPECT`，不得继续当负样本训练。
