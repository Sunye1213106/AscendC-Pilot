# FlashAttentionScoreGrad arch35：WSL 全量 tilingkey replay 执行记录

时间：2026-08-06/07（Asia/Shanghai）  
Pilot 仓库：`D:\TEST\AscendC-Pilot`  
Pilot HEAD：`c099dd12c879a75dae393a31ac0419a438dd91c6`  
FAG 算子路径：`D:\TEST\ops-transformer\attention\flash_attention_score_grad`  
FAG 源码 HEAD：`4e09c2ec15a414f6e312caf5b3da16cd965af07b`  
WSL distro：`Ubuntu-2204`

## 结论

WSL Host replay 已完成 clean run。最终 closure：

```text
D = 8705
R = 3521
E = 5184
R - D = 0
R ∩ E = 0
D - R - E = 0
```

也就是说：3521 个 tilingkey 有真实 Host replay 样例；剩余 5184 个不是“没构造到”，而是经 FAG arch35 host 源码 guard 证明不可达，并由 source-lemma rules 排除。

## 1. 清理旧产物

删除范围限定在本算子的可再生产物：

- `D:\TEST\ops-transformer\attention\flash_attention_score_grad\.ascendc-pilot\arch35\tg\closure`
- `D:\TEST\ops-transformer\attention\flash_attention_score_grad\.ascendc-pilot\arch35\tg\replay`

清理后重新建立 declared domain：

```text
D = 8705
R = 0
E = 0
gap = 8705
```

## 2. 执行环境

Windows 本机负责静态产物和 candidate 构造；WSL 负责 Host replay。使用的环境变量：

```powershell
$env:PYTHONPATH='D:\TEST\AscendC-Pilot;D:\TEST\AscendC-Pilot\engines\testcase-generation;D:\TEST\AscendC-Pilot\scripts;D:\TEST\AscendC-Pilot\engines\understand-operator\src;D:\TEST\AscendC-Pilot\pilot'
$env:ASCENDC_PROJECT_ROOT='D:\TEST\ops-transformer\attention\flash_attention_score_grad'
$env:UO_OP_DIR='D:\TEST\ops-transformer\attention\flash_attention_score_grad'
$env:UO_OPERATOR='flash_attention_score_grad'
$env:UO_ARCH='arch35'
$env:UO_REPLAY_DISTRO='Ubuntu-2204'
```

注意：本轮没有依赖 Windows 本机 `clang.exe` 跑 replay。静态分析产物来自本机完整 Python/源码环境；Host replay 通过 WSL 执行。

## 3. replay 策略

本轮执行的策略是 KB-guided direct construction first：

1. 从 `D - R - E` open set 取 target key。
2. 用 FAG operator-specific `construct_case()` 反向构造输入。
3. direct `kb_construct` 候选优先 replay。
4. sklearn 只用于排序/观察，不过滤 direct 构造候选。
5. 默认关闭 witness mutation exploration，避免漂移样本污染 target accounting。
6. model arm 写回 `R` 后重算 open，再生成 random/control arm，避免同轮重复。
7. 每轮检查 `R - D`；出现 undeclared key 就标记 `domain_suspect`，不能计入 clean closure。

## 4. WSL replay 回合

日志目录：

`D:\TEST\ops-transformer\attention\flash_attention_score_grad\.ascendc-pilot\arch35\runs\RUN_20260806_145234_1b8a792b\manual_logs`

| round | log | model | random | new declared R | undeclared | reject/crash/parse fail | 备注 |
|---:|---|---:|---:|---:|---:|---:|---|
| 1 | `tg_search_round_final_clean6_seq_0001_budget1024.out.log` | 512 | 512 | 1024 | 0 | 0 | 初始 open=8705 |
| 2 | `tg_search_round_final_clean6_seq_0002_budget2048.out.log` | 1024 | 1024 | 2048 | 0 | 0 | open 从 7681 开始 |
| 3 | `tg_search_round_final_clean6_seq_0003_budget8192.out.log` | 448 | 0 | 448 | 0 | 0 | direct KB 构造基本耗尽 |
| 4 | `tg_search_round_final_clean6_seq_0004_budget1024.out.log` | 0 | 0 | 0 | 0 | 0 | 暴露 empty tensor 构造漏项 |
| 5 | `tg_search_round_final_clean6_seq_0005_empty_budget64.out.log` | 1 | 0 | 1 | 0 | 0 | 补上 empty tensor key |

最终 replay corpus：

```text
rows = 3521
accepted = 3521
refused = 0
unique declared keys = 3521
undeclared = 0
```

## 5. replay 中遇到的问题

### empty tensor 构造漏掉

现象：round 4 direct constructor 无候选，但 residual 里仍有一个 distance=6 的 open key。

处理：

- 从 `construction_hints.yaml` 移除 `IsEmptyTensor: "0"` 的硬限制。
- 在 FAG `construct_case()` 中增加 `IsEmptyTensor=1` 的 canonical witness。
- WSL probe 验证该类样例能命中 key `18014398509481985`。

结果：round 5 新增 1 个 declared key，`R=3521`。

### exploration mutation 发现 host/kernel 域不一致

早期探索 mutation 曾发现 63 个 Host replay key 不在 kernel declared domain `D`，集中在 FLOAT32 + RoPE 相关区域。

处理：

- clean run 不把这些 key 计入 `R`。
- `search_round` 增加 `domain_suspect` 和 `undeclared_R` 统计。
- 默认关闭 exploration fill，避免在 full closure 账本里混入域外 key。

最终 clean run：`undeclared=0`。

### 候选漂移和重复 replay

处理：

- direct KB 构造候选的 `_target_key` 保持真实目标 key。
- mutation exploration 的 `_target_key=0`，只用于观察，不伪装成 target hit。
- model arm 先跑并写回，random arm 使用更新后的 open set。

结果：round1/round2 都没有同轮重复命中，budget 转化为 declared `R`。

## 6. residual 和 source lemma

replay 后：

```text
R = 3521
open = 5184
distance = {1: 3576, 2: 1392, 3: 216}
```

`construct_reasons()` 将 5184 个 open 压缩为 45 个 reason combination，归并为 10 个 FAG arch35 host 源码 guard 家族。完整明细：

`D:\TEST\ops-transformer\attention\flash_attention_score_grad\.ascendc-pilot\arch35\tg\closure\construct_blocker_summary.csv`

source lemma 处理：

```text
source guard families = 10
expanded combo rules = 83
dry_run.excluded = 5184
dry_run.bad_R = 0
promoted = 83
apply.excluded = 5184
revoked_count = 0
```

active rules：

`D:\TEST\ops-transformer\attention\flash_attention_score_grad\.ascendc-pilot\arch35\tg\closure\lemmas\active_rules.yaml`

## 7. 最终校验

执行：

```powershell
python -m testcase_agent.closure.cli --root 'D:\TEST\ops-transformer\attention\flash_attention_score_grad' state
python -m testcase_agent.closure.cli --root 'D:\TEST\ops-transformer\attention\flash_attention_score_grad' report
python -m testcase_agent.closure.cli --root 'D:\TEST\ops-transformer\attention\flash_attention_score_grad' residual --rows 10
python -m testcase_agent.closure.cli --root 'D:\TEST\ops-transformer\attention\flash_attention_score_grad' route
pytest engines/testcase-generation/tests/test_closure_generation_policy.py engines/testcase-generation/tests/test_fag_arch35_input_semantics.py engines/testcase-generation/tests/test_closure_key_precision.py engines/testcase-generation/tests/test_closure_w5_gates.py engines/understand-operator/tests/test_tg_host_view.py -q
```

结果：

```text
state:    ok=true, D=8705, R=3521, E=5184, gap=0, violation=0, undeclared=0
report:   ok=true, witnessed=3521, excluded=5184, open=0, problem_count=0
residual: ok=true, open=0, row_count=0
route:    ok=true, reason=GAP_ZERO
pytest:   26 passed in 2.66s
```
