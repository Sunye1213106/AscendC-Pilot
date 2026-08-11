# 安装与运行环境

AscendC-Pilot 可以在 Windows 或 Linux 上安装控制面，但完整算子分析与真实 TG replay 依赖的系统环境不同。先明确要运行的层级，再配置依赖。

## 1. 控制面与基础开发

支持 Python 3.10+。根 `requirements.txt` 提供 `PyYAML` 与 `jsonschema`，可用于 CLI、host 安装、文档检查和大部分不依赖外部 CANN 树的测试。

```bash
pip install -r requirements.txt
pip install -e ./pilot
pip install -e ./engines/common
pip install -e ./engines/understand-operator
pip install -e "./engines/testcase-generation[ml]"
pip install -e ./engines/code-engineering
acp doctor
```

`z3-solver` 仍然在项目中使用，但它不是纯控制面或文档检查的前置条件。`engines/common` 提供 `acp_common.z3_backend`，并通过依赖安装 `z3-solver`；UO 的 key reachability、loop summary、lineage 以及 TG 的约束/覆盖求解会使用这层有限域 solver。只安装 Host Adapter 或运行基础 CLI 时，不需要把它理解成 CANN 环境要求。

`acp doctor` 验证 Python package、engine import 和 generated host runtime；它不会证明 CANN、Clang 或 replay 已可用。检查当前 Python 与本地工具可见性：

```bash
python scripts/dev/check_env.py
```

## 2. UO 完整 AscendC 源码抽取

UO package 依赖 `libclang>=18.1.1`。完整 Translation Unit 抽取还需要可执行的 `clang` 驱动，以及与目标算子相匹配的 CANN header tree 和 `ops-transformer` 源码。`libclang` 能否导入并不等于完整 CANN 上下文已可解析。

UO 解析外部目录时使用以下变量，而不是猜测某位开发者的本地路径：

```text
UO_CANN_ROOT / ASCEND_CANN_PACKAGE_PATH / CANN_ROOT
UO_OPS_ROOT / OPS_TRANSFORMER_ROOT
UO_OP_DIR
```

其中 CANN root 应包含 `cann-metadef` 或 `cann-asc-devkit` 等子包；OPS root 应为包含 `common/include` 的 `ops-transformer` checkout。可运行：

```bash
python scripts/dev/check_cann.py
```

脚本会报告实际解析到的 CANN/OPS 根目录、环境变量和候选路径。若只运行不需要完整 CANN Translation Unit 的离线分析，部分 UO 测试和 fallback 仍可能可用；不要将其误读为真实算子已完成完整抽取。

`uo_walk` 是可选的 native helper。若需要构建它，安装 CMake 3.16+、C++17 编译器、libclang 的 headers 与 library，并通过 `LLVM_DIR` 或 `CLANG_DIR` 提供查找路径；安装脚本会尽力构建，找不到 libclang 时会跳过。

## 3. TG 的真实 Host replay

真实 L2/L3 replay 不在纯 Windows Python 环境中完成。执行环境必须是原生 Linux，或安装了 Linux 发行版的 Windows WSL；并且该 Linux/WSL 环境内需要：

- CANN Toolkit/Runtime，并能 `source` 对应的 `set_env.sh`。默认探测 `/usr/local/Ascend/cann/set_env.sh` 或版本化目录，也可显式设置 `CANN_SET_ENV`。
- 可由 CANN 与 `ops-transformer` 构建使用的 C++17 工具链。
- 与目标算子匹配的 `ops-transformer` checkout。replay bootstrap 使用 `OPS_TRANSFORMER_ROOT`、`UO_OPS_ROOT` 或 `OPS_ROOT` 查找它，并会在缺少 host UT 产物时调用 `./build.sh --ophost_test --ops=<operator> --noexec`。

Windows 控制端还要设置能执行 replay 的发行版，例如：

```powershell
$env:UO_REPLAY_DISTRO = "Ubuntu-22.04"
```

WSL 必须能访问算子源码和上述 OPS/CANN 路径。默认 replay bootstrap 会建立 driver；也可通过 `UO_REPLAY_HOST=native` 或显式 replay entry 覆盖执行方式。环境准备失败时，TG 会写入 replay environment receipt 并报告如 `CANN_ENV_NOT_FOUND`、`WSL_UNAVAILABLE` 或 `OPHOST_BOOTSTRAP_FAILED`，而不会把候选当作覆盖证据。

## 4. Host Adapter

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

## 5. 算子根目录

工作流应在目标 AscendC 算子仓中运行，或通过 `--project` 指定算子源码目录。

也可以使用 `ASCENDC_PROJECT_ROOT` 或 `UO_OP_DIR` 指向算子源码目录。Pilot 默认拒绝把 AscendC-Pilot 自身 checkout 当作算子根目录，只有测试专用路径会显式放开。

## 6. 架构参数

默认架构是 `arch35`。可通过 `--architecture`、`UO_ARCH` 或 `ASCENDC_ARCH` 覆盖。
