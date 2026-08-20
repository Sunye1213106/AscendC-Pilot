# Oracle 与观测

**何时加载**：解释 Host 回放结果、写入观测或判断能否进 R 时。

## 裁决分类

| 结果 | 含义 | 对 R/E |
|---|---|---|
| HIT | 得到目标 key | 可增长 R |
| REWRITE | 得到其他 key | 观测，供引理 |
| REFUSE | 明确拒绝（非 crash） | 观测，供引理 |
| CRASH / NOT_RUN | 不可信 | 禁止写 E；修环境 |

## 纪律

- `withheld_from`：禁止用同源日志字段自证同一维度
- 常量按名解析，禁止手抄易漂移数字
- 批次送入与完成标记不符 → 裁决可疑，停止当负样本训练

精度/性能场景的 oracle 是测试仓 harness 的精度/性能 mode，不是上表 Host HIT。
预期报错 / Disable 行不是精度失败，也不是 Host REFUSE 证明。
Host 回放只能增长 dispatch / key `R`，不能把 `P-*`/`F-*` 写入 CE `V`。缺测试仓或 runner 时精度/性能保持 Open（`harness_missing`）。Crash / not-run 是环境，不是不可达，也不是 golden 失败。
