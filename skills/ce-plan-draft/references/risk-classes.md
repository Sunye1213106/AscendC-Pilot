# 风险怎么分类

**何时加载**：写计划「测试内容」、要按失败模式分类时。

按可观察失败模式分类，不要按文件名。CE 不写义务 yaml，也不把精度/性能写进 `V`。

| 失败怎么说 | class | 何时想到 |
| --- | --- | --- |
| Tiling 失败、Kernel 找不到、dispatch 漏分支 | **dispatch** | TILING_KEY / TEMPLATE / PREDICATE |
| 接口、字段布局、输入输出合同 | **contract** | INPUT/OUTPUT、TILING_FIELD/DATA |
| 覆盖缺口、路径没跑到 | **coverage** | BRANCH / KERNEL |
| 越界、rank/dtype/tail、切分公式 | **shape** | TILING_FIELD/DATA |
| 同步缺失、卡死、队列/Buffer 生命周期 | **sync** | BUFFER/REGISTER/QUEUE/PIPE/EVENT |
| 精度不对（Cast / DataCopy / 多 dtype） | **precision** | Cast / DataCopy；测量在 TG |
| 性能回退 | **perf** | BUFFER 等；profiling 在 TG |

测试内容写成可观察风险散文（精度 / 性能 / 跨层 / 同步），不要写 TG 场景 id。不要静默扩成全部合法 Key。
