# Bring-up log：本机把覆盖流程跑通的全过程

这份日志记的是**每一处需要人介入的地方**。它不是环境搭建说明，是后面把流程固化成
workflow 时划分 action 边界的依据：凡是这里出现过的手工干预，固化时要么变成
`env_probe` 的一条自检，要么变成一个确定性 action。

机器：Windows + WSL2 `Ubuntu-2204`，日期 2026-08-03。

---

## 1. 环境解析（无需干预）

```powershell
python -c "from uo_init import paths; print(paths.explain())"
```

```text
cann_root: D:\TEST\_cann\pkg
ops_root: D:\TEST\ops-transformer
  skipped trimmed tree D:\TEST\_cann\slim: built from a different build_context.yaml
```

slim 树因 `build_context.yaml` 摘要变了而失效，自动退回 `pkg`。**这是正确行为**，不是故障：
slim 是按某份 build context 裁剪的，context 变了就不能再用。代价是 clang 解析慢一些
（实测 bundle 97.6s）。

> 固化提示：`env_probe` 应报告 slim 是否可用及失效原因，但不应因此失败。

## 2. 卡点一：WSL 发行版名字对不上

`operator.yaml` 写的是 `distro: Ubuntu-22.04`，本机实际注册的是 `Ubuntu-2204`。

`runner._require_host()` 的报错是准确的，会列出已注册的名字并提示设
`UO_REPLAY_DISTRO`。**不改 YAML**，走环境覆盖：

```powershell
$env:UO_REPLAY_DISTRO = "Ubuntu-2204"
```

`operator.yaml` 的注释其实预见了这件事——`wsl --install` 装的带点，导入 tarball 的名字
随便取。所以这是设计内的可变项，不是配置错误。

> 固化提示：`env_probe` 必须比对 `wsl -l -q` 与 manifest 的 distro，不一致时直接给出
> 要设的环境变量和值。

## 3. 卡点二：entry 脚本不存在，且接口与 driver 不一致

manifest 指向 `/work/wsl/setup/run_replay.sh`，该文件不存在。WSL 里已有的是：

| 件 | 路径 | 状态 |
| --- | --- | --- |
| CANN | `/usr/local/Ascend/cann` | 在位 |
| host UT so | `/work/ops-transformer/build/tests/ut/framework_normal/op_host/libophost_transformer_ut.so` | 已构建 |
| driver | `/work/replay/build/fag_replay` | 已编译 |
| driver 源 | `/work/replay/src/replay_main.cpp` | `fag_replay_SOURCE_DIR` 指向它 |

**接口不是一一对应的**，这是写 entry 脚本时唯一需要动脑的地方：

| runner 传的 | driver 收的 |
| --- | --- |
| `$1` in_csv | `argv[1]` in_path |
| `$2` out_csv | `argv[2]` out_path |
| `$3` log_txt | **不接受**——driver 只往 stdout 打 |
| `$4` with_log | **不接受**——靠 slog 环境变量控制 |
| — | `argv[3]` so_path（runner 不传，脚本要自己知道） |
| — | `argv[4]` op_name（可选） |
| stdout 需含 `BATCH_DONE` | **driver 不打**——脚本负责 |

所以 entry 脚本的职责是三件事：把 so 路径补上、把 stdout 重定向进 log_txt、自己打
`BATCH_DONE`。

还有一处容易漏：`log_protocol.yaml` 的 scrape 要的不只是 driver 的 `###CASE` /
`###DONE`，还有 tiling 自己的 `OP_LOGD` 行（19 维的值在那里）。那些要靠

```bash
export ASCEND_SLOG_PRINT_TO_STDOUT=1
export ASCEND_GLOBAL_LOG_LEVEL=1
```

才会进 stdout。不设的话运行照样出 key，但每个 `log_*` 列都是空的——**读起来像"这一维
没动"，而不是"没人看过它"**。

脚本落在 `scripts/replay/wsl/run_replay.sh`（版本化的权威副本）。不能直接从 `/mnt/d`
执行：Windows 写的文件带 CRLF，bash 在 shebang 行就失败。装法：

```powershell
wsl -d Ubuntu-2204 -e bash -c "mkdir -p /work/wsl/setup && tr -d '\r' < /mnt/d/TEST/AscendC-Pilot/scripts/replay/wsl/run_replay.sh > /work/wsl/setup/run_replay.sh && chmod +x /work/wsl/setup/run_replay.sh"
```

脚本里一个刻意的决定：driver 中途死掉但已完成若干 case 时，**仍然报 `BATCH_DONE`**，
因为已完成的都是真 witness；只有一个 case 都没完成才按失败退出。否则最后一个 case 崩溃
会丢掉整批。

> 固化提示：`env_probe` 应检查 entry 脚本存在、可执行、且 driver 与 so 都在；缺失时
> 打印上面那条安装命令。

## 4. 冒烟：一次通过

```powershell
python scripts/replay_smoke.py
```

6/6 全 ok，每个都 `cross-checked 18/18 dims`，5 秒跑完。`diag` 里 `isExceedL2Cache`、
`enableSwizzle`、`sparseType` 都有值，说明 slog 抓取生效。

## 5. 覆盖基线

```powershell
python scripts/replay_runtime_counterexample_gate.py
```

```text
declared 8705   runtime_total 4212   R_declared 4116   undeclared 96
U 5073   excluded 3632   U-R 957
gate PASS - no witnessed key is excluded by any rule
```

这是**当前分支的真实基线**，取代此前文档里引用的旧数字。

## 6. 静态派生基线

```powershell
python scripts/_probe_derive.py --refresh
```

bundle 97.6s + derive 65.4s。结果与旧产物一致：

```text
CLOSED 15/19  INPUT_DERIVABLE 13/19  free_vars=6  implicit_zero=5
WARNING: OutDType encodes ['4','5','6'] but the template declares ['0','1','2','3']
```

四个未闭合维度：`SplitAxis`(free=4)、`IsBn2MultiBlk`(3)、`IsNzOut`(3)、`IsTndSwizzle`(6)。
`DeterType` 标着 `<- was overapproximated`，即上一轮新闭合的那个。

## 7. 分母 D 的两处争议，已查清

开始追 100% 之前必须先确认分母可信。两处都查了：

### 7.1 `undeclared 96`：算子契约 bug，不是覆盖问题

`scripts/_probe_undeclared.py`（本次新增）解码全部 96 个：

```text
dimension pairs that occur at runtime and in no declared instance:
  InputDType=1 with IsRope=1    96 keys
  IsRope=1     with OutDType=1  96 keys
```

每一维取值都在声明域内，**不合法的是组合**。这正是
`docs/debug/bug_report_fag_fp32_rope_undeclared_key.md` 已经报告的问题：OpDef 允许
FP32 + rope，host 接受并编码，kernel TPL 的 FP32 段却全部写死 `IsRope=0`。

报告写于语料较小时（32 个 key / 174 条用例），语料扩大后**同一根因现在是 96 个 key**。
根因未变，数字要更新。

结论：这 96 个既不进 `R` 也不进 `D`，`gate` 单列 `undeclared_runtime` 的做法是对的。
它们不影响 `U_sound − R = 0` 这个目标，但**必须在最终报表里始终可见**。

### 7.2 `domain_violations: 1`：同类，且是独立的一处

`OutDType` 能编码 4/5/6，模板只声明 0..3。派生器自己判定为
"operator-side contract conflict, not a derivation gap"，判断是对的。与 7.1 是两处独立的
host/TPL 契约裂缝。

> 固化提示：这两条应成为 `coverage_gate` 的常驻报表项，而不是一次性发现。分母有裂缝时
> 报表要显式说出来，不能让 `U_sound − R = 0` 掩盖它。

---

## 8. 阶段 A 小结

打通实跑总共只需两处人工干预：**设一个环境变量**、**装一个 entry 脚本**。两处都可以
被 `env_probe` 自动检出并给出精确修复指令，所以固化后弱模型不会卡在这里。

基线：

| 量 | 值 |
| --- | ---: |
| declared D | 8705 |
| R_declared | 4116 |
| U（当前口径，含未分档规则） | 5073 |
| excluded | 3632 |
| U − R | 957 |
| undeclared_runtime | 96（算子 bug，另计） |
| CLOSED | 15/19 |
| free_vars | 6 |

---

## 9. 阶段 B 进展（2026-08-03 夜）

### 9.1 空前提短路（soundness 安全版）

`loop_summary.guards_cover`：空前提按 `True` 送求解器。  
`derive_key_fields._read_forces_a_write`：仅当写点全是 local 或 `_always_runs` 时才问空前提覆盖。  
验收：`test_read_coverage.py` 通过；不安全版会打破
`test_a_member_covered_only_inside_a_conditional_helper_keeps_its_assumption`。  
`free_vars` 仍为 6（INIT 不能单靠空前提消掉）。

### 9.2 LEAF_COLLAPSE 降级

`collapsed_leaf_values` + finish 路径：归一化丢掉叶值且仍标 exact/constant → 降为
`overapproximated`，note 带 `LEAF_COLLAPSE:`。  
实测 `DeterType`：`exact` → `overapproximated`，CLOSED 15→14（诚实降级）。

### 9.3 lit 出处

`_folded_lit` 给折叠常量打 `origin=source|assumed`；`has_constant_dead_arm(..., source_only=True)`
可只拦 assumed。默认行为不变（仍保守）。

### 9.4 U 分档

`SOUND_GRADES = {solver_derived, source_lemma}`；gate 报表拆
`U_sound` / `U_reviewed`。

### 9.5 Binding 写侧

新增 `scripts/replay/knobs.py`；`_from_bindings` 覆盖 ≥9 维 named knobs
（IsPse/IsDrop/IsRope/IsAttenMask/InputDType/OutDType/IsDNoEqual/S1/S2/D/IsNEqual）。  
`special_generators` 仍优先；写侧可独立测。

### 9.6 摘要原语 + next-fit bailout 折叠

`interval_union_covers` / `next_fit_cores` 已进 `loop_summary.py`（含 float32 拒收）。  
**next-fit 已接入 soft-guard**：`coreIdx >= CORE_LIST_NUM|aicNum` 在 key-path 上折成
`lit false (origin=bailout)`，不再 mint `VAR_SCHED_*`。  
实测 unique free_vars **7→6**（`VAR_SCHED_C91EC6CDF0E1` 消失）。  
interval 仍未接到 mint（HostIR 缺 invalidS1Array 区间写事件）。

### 9.7 Codemap + tk-cover

- `uo_init/host_codemap.py`：YAML + SQLite；`writers_of` / `guards_at` / `callers_of`
- workflow `tk-cover` 已挂 Spec/引擎/ownership/gates/agent；`compose_runtime` ok
- 干跑：`python scripts/_drive_tk_cover.py`（必须 `python -m ascendc_pilot.cli`；
  安装版 `acp.exe` 是打包二进制，读不到本地 pilot 改动）
- 产物文件名勿带 `receipt.yaml`（会触发 ARTIFACT_IDENTITY_MISSING）
- 路径 prepare→derive→close→certify；`tk_*` gates 通过

### 9.8 solver 规则 → U_sound

单维：`IsRegbase=0`（D 里已无 0）。  
exact 成对进 `derived_rules.yaml`（绳 + dtype×template 等）；其中 **只有 rope×D 命中
declared D**（TPL 本身已不含非法 dtype/template 组合）。  
**`excluded_sound=512`，`U_sound=8193`，`U_sound−R=4077`**，gate PASS。  
`load_derived` 修了 implication 误当 `value_unreachable`。  
`*=0` 四条单维 UNSAT 被 replay 打脸（域裂缝），已撤。

### 9.9 剩余 6 个 free_vars（诚实阻塞）

| var | 含义 | 结论 |
|---|---|---|
| `VAR_INIT_36CDA…` | bandIdx | `guards_cover` 对 sparseMode∈{7,8} vs attenMask 写为 **sat**；源码读点不共享写守卫，**勿强关** |
| `VAR_INIT_ECF6…` | blockOuter | 与 deterSparseType 循环，勿强关 |
| `VAR_LOOPELEM_…` ×2 | invalidS1Array | HostIR `writers_of` = 0，需数组写事件才接 interval |
| `VAR_UNDECIDED_…` | CheckExceedL2Cache | 需 L2 footprint 模型 |
| `VAR_AUX_…DETERSPARSETYPE` | unsettled aux | 跟 DeterType 塌缩一起解 |

再压 `U_sound−R` 必须先消 free_vars / 让更多维 exact，否则 UNSAT 不可信。

### 9.11 Composer 工作流入口（2026-08-04）

单一入口：`python scripts/run_tk_cover.py --reset`（内部只用 `python -m ascendc_pilot.cli`）。  
清空 `uo/tk` + tk runs + `coverage_closure.yaml`，跑 prepare→derive→close→certify→complete。  
`coverage_gate` 现跑真门并写 `residual.yaml`。  
实测：workflow `passed`，`gate_pass=true`，`complete=false`，`open_gap_sound=4077`（exit 3）。  
**达不到全量覆盖的原因**见 residual blockers（bandIdx / invalidS1Array HostIR / L2 / blockOuter / DeterType），不是 recipe 没挖到。

