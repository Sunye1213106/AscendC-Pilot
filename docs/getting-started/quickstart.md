# Quick Start

以下命令在目标 AscendC 算子仓中运行。

## 构建 CodeMap

```text
/uo-init
```

UO 会建立 source scope，通过 Clang 抽取 CompilerFacts，分析算子关系，提交 canonical `.uo` 产物，并校验结构完整性。

查询 CodeMap：

```text
/uo-query
```

典型问题：

```text
这个算子的 TilingKey 是怎么决定的？
这个 TilingData 字段来自哪里？
哪个 Host 分支控制了这个 Kernel 分支？
```

## 生成测试

```text
/tg-init
/tg-plan
/tg-solve
```

`/tg-init` 从 UO 构建 TG contract，`/tg-plan` 选择覆盖义务，`/tg-solve` 执行搜索、replay、排除证明与 referee 审查。

使用 `L2` 做 TilingKey 闭环，使用 `L3` 做 runtime branch outcome 覆盖。

## 代码审查

```text
/ce-review
```

CE 使用 UO CodeMap 分析改动、受影响状态、不变量和可观测后果。
