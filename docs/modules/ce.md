# CE - Code Engineering

## 定位

CE 把 UO CodeMap 用到日常代码工程任务中，当前重点是 code review 与 impact analysis。

## 职责

- 基于 operator context 审查代码改动。
- 从 changed source 追踪到受影响的 Host state、TilingData fields、predicates 和 Kernel branches。
- 解释 propagation、invariant risk 和 observable consequence。
- 写入 bounded CE review artifacts。

## 非职责

- 不重建 UO CodeMap。
- 不替代 TG closure。
- 当前公开 workflow 不直接修改代码。

## 入口

- Slash：`/ce-review`
- Engine CLI：`ce-impact`
- Agent：`agents/ce-reviewer.yaml`

## 输入

- UO CodeMap 与 query views
- source diff 或 review target
- code-review skill references

## 处理流程

```text
change
  -> impacted state
  -> propagation
  -> invariant
  -> observable consequence
```

当前 engine package 有意保持较小：它给 CE 留出稳定实现锚点，未来可继续加入 impact analysis、context pack、code modification、debug 和 PR assistance。

## 输出

- `.ascendc-pilot/<arch>/ce/review/**`
- `.ascendc-pilot/<arch>/runs/**/actions/code_review/**`

## 不变量

- UO 是 operator semantics 的来源。
- Finding 必须绑定 evidence 和 observable consequence。
- CE reviewer 只写 review output，不写 Pilot state。

## 失败与恢复

如果 CodeMap 缺失或 stale，先运行 `/uo-init` 或 `/uo-update`，再信任 CE review。

## 集成关系

CE 读取 UO；当代码改动影响生成覆盖时，可消费 TG regression context。

## 实现锚点

- `engines/code-engineering/code_engineering/`
- `skills/code-review/`
- `agents/ce-reviewer.yaml`
- `prompts/tasks/ce/code-review.md`

## 测试

- `engines/code-engineering/tests/`
- `evals/skills/code-review/`
