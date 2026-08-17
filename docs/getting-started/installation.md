# 安装

AscendC-Pilot 支持 Windows 和 Linux。

基础运行需要 **Python 3.10+**。接入 OpenCode 还需要已安装的 **OpenCode 1.18**（V1 plugin API：`~/.config/opencode/plugins/*.ts` 自动加载）。使用 UO 还需要 Clang 和 CANN Headers；使用 TG Host Replay 需要 Linux 或 WSL 中可用的 CANN 环境。

`pip install -r requirements.txt` 使用可编辑安装（`-e`），**必须保留本仓库 checkout**，不要装完就删。

推荐按下面的顺序安装：

```text id="ejc5x7"
OpenCode 1.18 → Python venv → AscendC-Pilot → Host Adapter → Clang → CANN Headers → TG Replay Environment
```

## 0. 安装 OpenCode

从 [opencode.ai](https://opencode.ai) 安装 **1.18.x**。当前插件导出的是 V1 `export default async (ctx) => hooks`，不是 V2 的 `Plugin.define({ id, setup })`。

安装后确认：

```bash
opencode --version
```

配置目录默认为 `~/.config/opencode`（若设置了 `XDG_CONFIG_HOME`，则为 `$XDG_CONFIG_HOME/opencode`）。**运行本仓库的 install 脚本前，请完全退出 OpenCode**（不是只关聊天标签）。

---

## 1. 安装 AscendC-Pilot

获取源码并进入仓库：

```bash id="ya4wbh"
git clone https://github.com/Sunye1213106/AscendC-Pilot.git
cd AscendC-Pilot
```

建议使用虚拟环境（Linux / macOS 用 `python3`，Windows 用 `python`）：

```bash
python3 -m venv .venv
source .venv/bin/activate
```

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

安装全部 Python 依赖：

```bash id="zt9jdn"
python -m pip install -r requirements.txt
```

若 `python` 不存在，改用 `python3`。Windows 若禁止运行脚本：

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 opencode
```

安装完成后检查 Python 包（不需要 `--architecture`，不创建算子 arch 树，**不要求已经提取 CANN**）：

```bash id="17r0qi"
python scripts/dev/check_install.py
python -m ascendc_pilot doctor
```

`acp doctor` 与 `python -m ascendc_pilot doctor` 等价；若 `Scripts` / `~/.local/bin` 不在 PATH 上，请用后者。缺 CANN / Clang 在这一步只是警告，不会让预检失败。

如果需要查看 Python、Clang 等本机工具状态：

```bash id="gmv6ir"
python scripts/dev/check_env.py
```

---

## 2. 接入 OpenCode、Cursor 或 Codex

推荐使用 OpenCode 1.18。

Python 环境已经安装完成后，可以通过 `SKIP_PIP=1` 只安装 Host 侧的 Agent、Skill 和 Plugin。

### OpenCode

Windows（若 ExecutionPolicy 受限，见上面的 Bypass 调用）：

```powershell id="dz4d9i"
$env:SKIP_PIP = "1"
.\install.ps1 opencode
Remove-Item Env:SKIP_PIP
```

Linux：

```bash id="91ru0h"
SKIP_PIP=1 ./install.sh opencode
```

脚本会：

- 把 plugin 拷到 `~/.config/opencode/plugins/ascendc-pilot.ts`（不修改现有 `opencode.json`）
- 把 Session Driver 库放在 `~/.config/opencode/ascendc-pilot-plugin/opencode-plugin/`（不要把 `pilot-driver.ts` 放进 `plugins/` 自动加载目录）
- 写入 `ascendc-harness-bin`（`acp.exe` 的绝对路径；即使 `acp` 不在 PATH 也会从 Python `Scripts` 目录回退查找）
- 安装 `/uo-*`、`/tg-*`、`/ce-*` slash command，Tab 主控为 **AscendC-Pilot**

校验 Host 契约：

```bash
python -m ascendc_pilot doctor --host opencode
```

然后 **完全退出再打开 OpenCode**，通过 **Tab** 切换到：

```text id="fjpe4u"
AscendC-Pilot
```

日常改 plugin / skill 后，Windows 可用仓库根目录的 `.\refresh-opencode.ps1`（默认跳过 pip、复用 engines 拷贝）。Linux 重新跑 `SKIP_PIP=1 ./install.sh opencode`。

OpenCode 进程通常没有 Cursor 自带的 `rg`，且 1.18 把 bundled rg 放在 **cache** bin（Windows：`%LOCALAPPDATA%\opencode\bin`），不是 `~/.local/share/opencode/bin`。安装程序与插件会把 `rg.exe` 种到 cache/data 两套目录。主控 `skill` 由插件**覆盖**原生工具：直接读 OpenCode skills 目录下的 `SKILL.md`，不 spawn rg。子代理读 session `method.md`，不要走 OpenCode skill 发现。AscendC-Pilot 模式对任意目录 Read 直接放行（不弹 `external_directory` 确认）；Write 仍要确认。

MCP 保持放行。

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
# Prefer LLVM 18.x to match pip libclang 18.1.x (harness -ast-dump format).
winget install --id LLVM.LLVM --version 18.1.8 -e
# Or latest: winget install LLVM.LLVM
```

检查：

```bash id="w46rxu"
clang --version
```

若 `clang` 不在 PATH，可设置：

```powershell
$env:UO_CLANG = "C:\Program Files\LLVM\bin\clang.exe"
$env:CLANG_EXE = $env:UO_CLANG
```

内核 `if constexpr` 折叠与显式实例化 harness **需要 clang 可执行文件**；仅有 pip `libclang` DLL 不够。

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

**推荐解到当前仓库的 `_cann/pkg`**：安装脚本和 `acp doctor` 会自动发现它，不必再设环境变量。不要依赖某个开发机上的绝对路径（例如 `D:\AscendC\cann\pkg`）。

Windows（在仓库根目录）：

```powershell id="cjmtht"
$pkg = Join-Path (Get-Location) "_cann\pkg"
python scripts/cann_extract.py `
  "D:\Downloads\Ascend-cann-toolkit_<version>_linux-x86_64.run" `
  --dest $pkg
# 若 doctor 报缺 impl/include（junction 失败或悬空），只补链接、不解包：
python scripts/cann_extract.py --fixup --dest $pkg
```

Linux：

```bash id="qvqaqj"
pkg="$(pwd)/_cann/pkg"
python scripts/cann_extract.py \
  ~/Downloads/Ascend-cann-toolkit_<version>_linux-x86_64.run \
  --dest "$pkg"
python scripts/cann_extract.py --fixup --dest "$pkg"
```

也支持 `~/ascendc/cann/pkg`（自动发现）。若必须解到别处，再设**用户级**环境变量；只写 `$env:UO_CANN_ROOT=...` 关掉终端就会丢。

Windows 持久化：

```powershell id="f8u8rq"
[Environment]::SetEnvironmentVariable("UO_CANN_ROOT", "<abs-pkg>", "User")
```

Linux：

```bash id="xb7h94"
echo 'export UO_CANN_ROOT=/abs/path/to/cann/pkg' >> ~/.bashrc
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

将 package 根目录配置给 UO。解到 `<checkout>/_cann/pkg` 时无需再设变量。

`UO_CANN_ROOT` 若使用，应指向 CANN package 根目录，而不是某个具体的 `include/`。

正确：

```text id="011gxc"
UO_CANN_ROOT=/path/to/cann/pkg
```

不要配置成：

```text id="5q7dkj"
UO_CANN_ROOT=/path/to/cann/pkg/cann-asc-devkit/.../include
```

检查 UO 是否正确找到 CANN（会打印 candidates 和 layout，缺 `impl/include` 时提示 `--fixup`）：

```bash id="vzw9ke"
python scripts/dev/check_cann.py
python -m ascendc_pilot doctor
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

Architecture **对 `/uo-init` 和 `/uo-update` 强制**：选项从当前算子仓的 `op_host/arch*` / `op_kernel/arch*` 中发现；缺一会要求从发现的架构中选择，不会静默默认，扫描不到时也不会编造固定 architecture 作为兜底。TG / CE / 查询从已有 `.uo` 取 arch，不再从源码目录另选；没有 CodeMap 时会提示先 `/uo-init`。

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

Python 包与 Host 契约（缺 CANN 只警告，不失败）：

```bash id="gz1vae"
python scripts/dev/check_install.py
python -m ascendc_pilot doctor --host opencode
```

Python 和本机工具：

```bash id="vqbknt"
python scripts/dev/check_env.py
```

CANN Headers（UO 建库前再确认）：

```bash id="osxds5"
python scripts/dev/check_cann.py
```

至少确认：

```text id="fq1w6r"
acp / python -m ascendc_pilot   available
plugin_ascendc_pilot_ts         ok
plugin_pilot_driver_ts          ok
clang                           available（UO）
clang.cindex                    import OK（UO）
cann_root                       found（UO）
```

然后进入目标算子目录，**完全退出再打开 OpenCode**，Tab 切换到 `AscendC-Pilot`，即可开始：

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
Windows:  .\refresh-opencode.ps1          （日常；改 plugin/skill）
          .\install.ps1 opencode          （完整重装）
Linux:    SKIP_PIP=1 ./install.sh opencode
```

装完后完全退出再打开 OpenCode。

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
<checkout>/_cann/pkg
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
