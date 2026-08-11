# Quick Start

以下操作在**目标 AscendC 算子仓**中进行，而不是在 AscendC-Pilot checkout 中。完成安装后先运行：

```bash
acp doctor
```

它会检查 Python 包、UO/TG 引擎、host runtime 以及必要的环境提示。若 UO 无法找到 libclang 或 CANN 编译上下文，先根据 [安装](installation.md) 修复环境。

## 1. 建立 CodeMap

进入算子仓后执行：

```text
/uo-init
```

此操作会发现源码范围，使用 Clang 提取 CompilerFacts，生成并验证 CodeMap。成功后可在如下位置找到正式产品：

```text
<operator-repo>/.ascendc-pilot/uo/<op_name>.<arch>.uo
```

源码或构建条件变化后，运行 `/uo-update`，不要让 TG 或 CE 直接使用旧 CodeMap。

## 2. 查询源码关系

```text
/uo-query
```

可以直接询问：

```text
这个算子的 TilingKey 是如何决定的？
这个 TilingData 字段来自哪里？
哪个 Host 条件控制了这个 Kernel 分支？
```

查询只读取 CodeMap；如果回答显示源码范围、extract 或 unresolved 问题，应先回到 UO 修复对应阶段。

## 3. 建立并关闭测试义务

```text
/tg-init
/tg-plan
/tg-solve
```

`/tg-init` 从 UO 建立契约并审计输入；`/tg-plan` 选择目标域和 L2/L3 计划；`/tg-solve` 通过 search、construct、host replay、lemma 和 audit 推进义务账本。closure、replay evidence 和 certificate 位于：

```text
<operator-repo>/.ascendc-pilot/<arch>/tg/
```

L2 关闭 TilingKey 义务，L3 关闭同一可达 TilingKey 下的运行时分支结果。候选输入本身不是 coverage，必须查看 replay 和 gate 的结果。

## 4. 审查代码改动

```text
/ce-review
```

CE 会基于 CodeMap 追踪改动的影响传播，并写出带证据和可观测后果的 finding。若 UO 已过期，先更新 UO 再信任审查结果。

更多命令见 [CLI Reference](../reference/cli.generated.md)，完整的产物归属见 [产物与权威](../architecture/artifacts-and-authority.md)。
