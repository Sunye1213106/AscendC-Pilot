# 安装

AscendC-Pilot 支持 Windows 和 Linux。

基础运行需要 Python 3.10+。使用 UO 还需要 Clang 和 CANN Headers；使用 TG Host Replay 需要 Linux 或 WSL 中可用的 CANN 环境。

推荐按下面的顺序安装：

```text id="ejc5x7"
AscendC-Pilot → Host Adapter → Clang → CANN Headers → TG Replay Environment
```

## 1. 安装 AscendC-Pilot

获取源码并进入仓库：

```bash id="ya4wbh"
git clone https://github.com/Sunye1213106/AscendC-Pilot.git
cd AscendC-Pilot
```

安装全部 Python 依赖：

```bash id="zt9jdn"
python -m pip install -r requirements.txt
```

安装完成后检查：

```bash id="17r0qi"
acp doctor
```

如果需要查看 Python、Clang 等本机工具状态：

```bash id="gmv6ir"
python scripts/dev/check_env.py
```

---

## 2. 接入 OpenCode、Cursor 或 Codex

推荐使用 OpenCode。

Python 环境已经安装完成后，可以通过 `SKIP_PIP=1` 只安装 Host 侧的 Agent、Skill 和 Plugin。

### OpenCode

Windows：

```powershell id="dz4d9i"
$env:SKIP_PIP = "1"
.\install.ps1 opencode
Remove-Item Env:SKIP_PIP
```

Linux：

```bash id="91ru0h"
SKIP_PIP=1 ./install.sh opencode
```

重新打开 OpenCode 后，通过 **Tab** 切换到：

```text id="fjpe4u"
AscendC-Pilot
```

安装程序不会修改现有的 `opencode.json`。

### Cursor

Windows：

```powershell id="p2aymw"
$env:SKIP_PIP = "1"
.\install.ps1 cursor
Remove-Item Env:SKIP_PIP
```

Linux：

```bash id="4dexrs"
SKIP_PIP=1 ./install.sh cursor
```

### Codex

Windows：

```powershell id="yio8sh"
$env:SKIP_PIP = "1"
.\install.ps1 codex
Remove-Item Env:SKIP_PIP
```

Linux：

```bash id="eml7ex"
SKIP_PIP=1 ./install.sh codex
```

如果没有提前执行 `pip install -r requirements.txt`，也可以直接运行安装脚本而不设置 `SKIP_PIP`。

---

# UO 环境

UO 需要：

```text id="wuz5s3"
Clang + CANN Headers
```

目标算子源码不需要额外配置。实际使用时，在目标算子仓或算子目录中启动 AscendC-Pilot 即可。

## 3. 安装 Clang

Ubuntu / Debian：

```bash id="4dxi8n"
sudo apt-get update
sudo apt-get install -y clang
```

Windows：

```powershell id="qs66m8"
winget install LLVM.LLVM
```

检查：

```bash id="w46rxu"
clang --version
```

同时确认 Python 可以加载 libclang：

```bash id="wckp4t"
python -c "import clang.cindex as c; print(c.__file__)"
```

---

## 4. 准备 CANN Headers

UO 使用 CANN 的开发头文件解析 AscendC Host 和 Kernel 源码。

需要从华为昇腾社区下载与目标算子开发环境匹配的 **CANN Toolkit `.run` 安装包**，例如：

```text id="j61r5z"
Ascend-cann-toolkit_<version>_linux-x86_64.run
```

建议使用与目标算子实际编译环境相同或兼容的 CANN 版本。

### 提取 CANN Headers

对于 UO，不需要在当前机器完整安装 Toolkit。AscendC-Pilot 可以直接从 `.run` 包中提取需要的 CANN package tree。

Windows：

```powershell id="cjmtht"
python scripts/cann_extract.py `
  "D:\Downloads\Ascend-cann-toolkit_<version>_linux-x86_64.run" `
  --dest "D:\AscendC\cann\pkg"
```

Linux：

```bash id="qvqaqj"
python scripts/cann_extract.py \
  ~/Downloads/Ascend-cann-toolkit_<version>_linux-x86_64.run \
  --dest ~/ascendc/cann/pkg
```

提取完成后目录大致如下：

```text id="kh642t"
cann/pkg/
├── cann-metadef/
├── cann-asc-devkit/
├── cann-opbase/
├── cann-npu-runtime/
├── cann-ge-compiler/
└── bisheng/
```

将 package 根目录配置给 UO。

Windows：

```powershell id="f8u8rq"
$env:UO_CANN_ROOT = "D:\AscendC\cann\pkg"
```

Linux：

```bash id="xb7h94"
export UO_CANN_ROOT=$HOME/ascendc/cann/pkg
```

`UO_CANN_ROOT` 应指向 CANN package 根目录，而不是某个具体的 `include/`。

正确：

```text id="011gxc"
UO_CANN_ROOT=/path/to/cann/pkg
```

不要配置成：

```text id="5q7dkj"
UO_CANN_ROOT=/path/to/cann/pkg/cann-asc-devkit/.../include
```

检查 UO 是否正确找到 CANN：

```bash id="vzw9ke"
python scripts/dev/check_cann.py
```

正常情况下应能看到解析后的 `cann_root` 路径。

---

## 5. 使用 UO

环境准备完成后，进入需要分析的算子仓或算子目录。

例如：

```bash id="wc4t8j"
cd /path/to/operator
```

然后启动 OpenCode，切换到 `AscendC-Pilot`。

直接描述目标即可：

```text id="boez3r"
帮我为这个算子的 arch35 建立 CodeMap。
```

或者执行：

```text id="ath6ri"
/uo-init
```

Architecture 通常由当前算子仓中的 `op_host/arch*` 和 `op_kernel/arch*` 自动发现。存在多个架构时，AscendC-Pilot 会要求选择目标架构；扫描不到时不会编造固定 architecture 作为兜底。

也可以在任务中显式指定，或通过环境变量设置：

```text id="pvhzcf"
UO_ARCH
ASCENDC_ARCH
```

正常使用时不需要配置算子源码路径，也不需要手工维护 include 文件列表。UO 会从当前目标算子和实际编译依赖中确定 Source Scope。

---

# TG Host Replay 环境

UO 的 CANN Headers 和 TG Replay 使用的 CANN 环境需要区分：

```text id="0w66ad"
UO → CANN Header Package
TG → Linux / WSL 中可运行的 CANN Environment
```

## 6. 准备 Linux / WSL

Linux 用户可以直接使用当前环境。

Windows 用户需要 WSL。

检查：

```powershell id="1c3huq"
wsl -l -v
```

如果尚未安装：

```powershell id="5enmn5"
wsl --install
```

安装完成后准备一个可正常使用的 Linux 发行版。

---

## 7. 安装 TG 使用的 CANN

在 Linux 或 WSL 中，从华为昇腾社区下载与目标环境匹配的 CANN Toolkit / Runtime。

安装包通常类似：

```text id="zuwytq"
Ascend-cann-toolkit_<version>_linux-<arch>.run
```

按照对应 CANN 版本的官方安装说明完成安装。

安装后找到：

```text id="tupdiv"
set_env.sh
```

可以搜索：

```bash id="rye6vs"
find /usr/local/Ascend "$HOME/Ascend" -name set_env.sh 2>/dev/null
```

加载环境：

```bash id="ocxic0"
source /path/to/set_env.sh
```

如果 CANN 不在默认位置，可以设置：

```bash id="hh3jhg"
export CANN_SET_ENV=/path/to/set_env.sh
```

Windows 使用 WSL Replay 时，可以指定发行版：

```powershell id="dj2cu1"
$env:UO_REPLAY_DISTRO = "Ubuntu-22.04"
```

Replay 环境还需要基本 C++ 构建工具：

```bash id="u3yxsm"
sudo apt-get install -y build-essential cmake
```

Host Replay driver、Host UT 构建和 testcase 执行由 TG workflow 在运行过程中处理，不需要在安装阶段逐个配置。

---

## 8. 验证安装

基础运行环境：

```bash id="gz1vae"
acp doctor
```

Python 和本机工具：

```bash id="vqbknt"
python scripts/dev/check_env.py
```

CANN Headers：

```bash id="osxds5"
python scripts/dev/check_cann.py
```

至少确认：

```text id="fq1w6r"
acp             available
clang           available
clang.cindex    import OK
cann_root       found
```

然后进入目标算子目录，在 OpenCode 中切换到 `AscendC-Pilot`，即可开始：

```text id="zk5j1w"
/uo-init
```

---

# 更新

拉取最新代码：

```bash id="n5ijym"
git pull
```

重新安装依赖：

```bash id="058z44"
python -m pip install -r requirements.txt
```

然后重新安装当前使用的 Host Adapter。

OpenCode：

```text id="kp3isw"
Windows:  .\install.ps1 opencode
Linux:    ./install.sh opencode
```

Cursor：

```text id="iy2kae"
Windows:  .\install.ps1 cursor
Linux:    ./install.sh cursor
```

Codex：

```text id="j7mxzf"
Windows:  .\install.ps1 codex
Linux:    ./install.sh codex
```

如果 CANN 版本没有变化，不需要重新提取 Headers 或重新配置 `UO_CANN_ROOT`。

---

# 卸载

## 卸载 Host 接入

OpenCode：

```text id="qkwge2"
Windows:  .\install.ps1 uninstall-opencode
Linux:    ./install.sh uninstall-opencode
```

Cursor：

```text id="9nqvsz"
Windows:  .\install.ps1 uninstall-cursor
Linux:    ./install.sh uninstall-cursor
```

Codex：

```text id="9hqlrf"
Windows:  .\install.ps1 uninstall-codex
Linux:    ./install.sh uninstall-codex
```

这只删除 AscendC-Pilot 安装的 Agent、Skill 和 Plugin，不会修改用户原有 Host 配置。

## 卸载 Python 包

如果不再使用 AscendC-Pilot，可以删除安装的 Python packages：

```bash id="ei1c9j"
python -m pip uninstall -y ascendc-pilot acp-common uo-init testcase-agent code-engineering
```

公共 Python 依赖不会自动删除。

## 删除 CANN Headers

如果提取的 CANN package tree 只用于 AscendC-Pilot，可以直接删除对应目录，例如：

```text id="jaw6oi"
D:\AscendC\cann\pkg
```

或：

```text id="fr4zs9"
~/ascendc/cann/pkg
```

同时删除 `UO_CANN_ROOT` 环境变量即可。

这不会影响 Linux / WSL 中已经安装的 CANN Toolkit。

## 删除算子产物

卸载 AscendC-Pilot 不会删除目标算子目录中的：

```text id="a8tf5v"
<operator-repo>/.ascendc-pilot/
```

其中保存已有 CodeMap、TG coverage、Replay evidence 和运行记录。

确认不再需要后可以手工删除。
