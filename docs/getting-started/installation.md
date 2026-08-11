# 安装

## Python 环境

```bash
pip install -r requirements.txt
pip install -e ./pilot
pip install -e ./engines/common
pip install -e ./engines/understand-operator
pip install -e "./engines/testcase-generation[ml]"
pip install -e ./engines/code-engineering
```

检查安装：

```bash
acp doctor
```

## Host Adapter

Windows：

```powershell
./install.ps1 opencode
./install.ps1 cursor
./install.ps1 codex
```

Linux：

```bash
./install.sh opencode
```

## 算子根目录

工作流应在目标 AscendC 算子仓中运行，或通过 `--project` 指定算子源码目录。

也可以使用 `ASCENDC_PROJECT_ROOT` 或 `UO_OP_DIR` 指向算子源码目录。Pilot 默认拒绝把 AscendC-Pilot 自身 checkout 当作算子根目录，只有测试专用路径会显式放开。

## 架构参数

默认架构是 `arch35`。可通过 `--architecture`、`UO_ARCH` 或 `ASCENDC_ARCH` 覆盖。
