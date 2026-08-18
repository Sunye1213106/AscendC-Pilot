# ACP 工具使用说明

OpenCode 的 AscendC-Pilot 模式里有两个 Host 工具：`pilot_run` 和 `pilot_cli`。日常任务按本页选工具即可。这两个工具只属于 **AscendC-Pilot Tab**；Build / Plan 保持 OpenCode 原生权限、原生 skill、原生 shell，不会套用 Pilot harness，也看不到 Pilot workflow skill。不要注册名为 `acp` 的插件工具（会撞上 OpenCode ACP 协议）。

**不要用 `--help` 来摸协议。** argparse 帮助会列出三十多个内部子命令（`authorize`、`debug`、`serve-authorize` 等），那不是 Session Driver 合同，也不是查询路由。Agent 跟着帮助文字去编排 `start` → `run-action` → `finalize`，或在 Windows 上改走 bash，就会表现为卡住（ses_fefd：120s bash 杀掉 uo-init analyze）。

命令清单见 [CLI Reference](../reference/cli.generated.md)。协议与权限见 [Agent Runtime](../architecture/agent-runtime.md)。查询怎么走见 [UO Query Router](../../skills/operator-analysis/routing/uo-query.md)。

---

## 两个工具怎么选

```text
用户目标
  ├─ 建库 / 更新 / TG / CE / 调查 unresolved
  │     → Host 工具 pilot_run（workflow + project + architecture）
  └─ 只读问 CodeMap / 看状态 / 看失败卡
        → 插件工具 pilot_cli（command 里不要带前导 acp）
```

| 目标 | 用什么 | 不要用 |
| --- | --- | --- |
| `/uo-init`、`/uo-update`、`/tg-*`、`/ce-*`、`/uo-investigate` | `pilot_run` | 手工 `acp start` / `acp next` / `acp run-action auto` 串环 |
| 简单查询（一个标识符或一种参数形态） | 插件 `pilot_cli`：`uo-query --project <算子绝对路径> …` | `pilot_run workflow=uo-query`；`acp start uo-query` |
| 复杂查询（多个可独立查询的起始点） | 同一轮 `Task(agent=uo-query)`，子代用插件 `pilot_cli` | 主控自己把多路查完再假装委派 |
| 缺 architecture、要列 `arch*` 选项 | 插件 `pilot_cli`：`scan-architectures --project <算子绝对路径>` | 在仓库根目录 Glob / 翻 cmake |
| `pilot_run` 失败、要看原因 | 插件 `pilot_cli`：`inspect-failure` / `status`（都要 `--project`） | `--help`、读 Pilot 源码、bash 管道 |

插件 `pilot_cli` 的 `command` 是 **二进制后面的 argv**，不要再写一遍 `acp`，也不要找 `acp.exe`：

```text
uo-query --project D:\ops\attention\flash_attention_score_grad --architecture arch35 s1Inner
status --project D:\ops\attention\flash_attention_score_grad
inspect-failure --project D:\ops\attention\flash_attention_score_grad
scan-architectures --project D:\ops\attention\flash_attention_score_grad
```

`--project` 必须是算子包根（含 `op_host/` / `op_kernel/`），不是 AscendC-Pilot 仓库，也不是 `ops-transformer` 仓根。

---

## 为什么 `--help` 会卡住

这是运行时最常见的空转，不是 argparse 本身算得慢。

1. **把帮助当成协议。** `acp --help` 列出的是全部 CLI，包括 Host 内部命令。Agent 接着对 `start`、`run-action`、`uo` 再调一次 `--help`，不再推进用户任务。
2. **Windows 上用 bash 调 `acp`。** OpenCode 1.18 的 bash 可能把整行 `acp …` 当成可执行文件，出现 `NotFound: ChildProcess.spawn`，或 120s 杀掉 uo-init。工作流必须用 `pilot_run`；短命令必须用插件 `pilot_cli`（内部 `spawnSync(acp.exe, shell:false)`），不要 bash。
3. **绝对路径触发权限等待。** 写成 `C:\…\Scripts\acp.exe --help` 对不上 frontmatter 白名单，OpenCode 会变成 ask/deny，界面像卡死、其实在等人点允许。不要搜 `acp.exe`。
4. **有待回答问题时继续 `--help`。** 插件在 pending AskQuestion 期间仍放行 `--help`，但帮助不会消费这个问题。正确动作是把 `ask_question` 的选项原样交给用户，而不是再摸一遍 CLI。
5. **管道缓冲。** `acp … | Select-Object -Last` / `Out-String` / `tail` 会被 authorize 拒绝；Agent 换写法重试，看起来也在空转。

插件 `pilot_cli` 收到 `--help` / `-h` / `help` 时会返回本页的短用法卡，**不会**再 spawn argparse。收到 `start` / `run-action auto` 时直接拒绝并要求改用 `pilot_run`。人类在自己的终端里仍可直接运行 `acp --help`。

---

## Agent 允许的日常命令

插件 `pilot_cli` 只应用下面这些；`start` / `run-action auto` 必须走 `pilot_run`。

| `command` | 何时用 |
| --- | --- |
| `uo-query --project <abs> [--architecture arch] <标识符或 Dim=V>` | 简单查询；stdout 即答案。也可 `--file <path> --line <n>`，或省略查询词拿算子索引 |
| `uo-query --project <abs> --status-only` | 只看产物是否存在 / 是否 fresh |
| `scan-architectures --project <abs>` | 启动前列出 `arch*` 选项，供 AskQuestion |
| `status --project <abs>` | 当前 workflow / run 状态 |
| `inspect-failure --project <abs>` | `pilot_run` 或确定性 Action 失败后的失败卡 |
| `next --project <abs>` | 调试：看下一步允许的 Action（正常路径由 `pilot_run` 持有） |

查询四种参数形态（禁止 `--mode`）：

```text
pilot_cli command=`uo-query --project <abs> [--architecture arch35] s1Inner`
pilot_cli command=`uo-query --project <abs> [--architecture arch35] SparseMode=3`
pilot_cli command=`uo-query --project <abs> [--architecture arch35] --file op_host/arch35/foo.cpp --line 120`
pilot_cli command=`uo-query --project <abs> [--architecture arch35]`
```

`pilot_run` 参数：

| 参数 | 说明 |
| --- | --- |
| `workflow` | `uo-init` / `uo-update` / `tg-init` / `tg-plan` / `tg-solve` / `ce-review` / `ce-intent` / `ce-impact` / `ce-verify` / `uo-investigate` 等。**不要**填 `uo-query` |
| `project` | 算子包绝对路径 |
| `architecture` | `uo-init` / `uo-update` 必填；从 `scan-architectures` 的选项里选，不要猜 |
| `intent` | 用户原话里的产品意图；不要编造 |
| `force_new` | 默认不要设。只有用户明确说删除重开时才为 true |

`pilot_run` 返回 `host_step.kind=dispatch_subagent` 时，用原生 `Task`，`prompt` 必须是 `task_prompt_stub` 原文。返回 `ask_question` / `host_owned_ask` 时，选项必须原样使用。

---

## 失败时怎么做

`pilot_run` 失败时，返回的 JSON **必须带** `message_zh`（以及可能的 `error` / `hint_zh` / `error_detail`）。环境问题（例如没配 CANN package 目录）会直接写在 `message_zh` 里，告诉你设置 `UO_CANN_ROOT` / `ASCEND_CANN_PACKAGE_PATH`。把这段话转述给用户即可。

失败后 workflow 可能进入 `human_required`。写、派 Task、直调领域脚本、读引擎实现仍然会被挡住。主控可以 `Read` / `Glob` / `Get-ChildItem` 看算子目录和失败产物，方便核对环境。优先用：

```text
插件 pilot_cli：inspect-failure --project <abs>
插件 pilot_cli：status --project <abs>
缺 architecture：scan-architectures，然后 AskQuestion
主控只读：Read / Glob / Get-ChildItem / ls / dir / pwd
诊断：python scripts/dev/check_cann.py / check_env.py / python -m ascendc_pilot doctor / cann_extract.py --fixup
不要：--help、读引擎脚本、bash acp start、Write / Task
```

`inspect-failure` 的 `message_zh` 面向用户；不要把 `reason_code` 当成唯一解释。外部环境修好后才用 `retry-after-environment-fix`（这是恢复命令，不是日常路径）。

有未完成 run 时，由 Host AskQuestion 在「继续上次」和「删除重开」之间选；Agent 不要为了「确保能跑」先 wipe。

---

## 人类在终端里怎么用

安装后 `acp` 与 `python -m ascendc_pilot` 等价。PATH 上没有 `acp` 时用后者。

```bash
python -m ascendc_pilot doctor
python -m ascendc_pilot doctor --host opencode
acp status --project <算子目录>
acp inspect-failure --project <算子目录>
acp scan-architectures --project <算子目录>
acp uo-query --project <算子目录> --architecture arch35 s1Inner
```

终端里的 `acp --help` 给开发者看命令清单。Agent 在 OpenCode 里不要学这个入口。
