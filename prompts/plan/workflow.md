# `/tg-plan` 命令块

```powershell
$PROJECT_ROOT = "<算子仓>"
$OP_NAME = "<op>"

# 0) 先根据人工输入定范围：空 = 全部输入可达；有说明则 LLM 写成 --focus
# 1) 默认 L0+L1
tg-plan "$PROJECT_ROOT" --op-name $OP_NAME

# 指定变量 / KEY（示例）
tg-plan "$PROJECT_ROOT" --op-name $OP_NAME --focus "KEY_IsRope KEY_MaskType"

# 可选 L2 / topic
tg-plan "$PROJECT_ROOT" --op-name $OP_NAME --level L0,L1,L2
tg-plan "$PROJECT_ROOT" --op-name $OP_NAME --topic determinism
```

## 范围规则

- **有人工输入** → LLM 映射到 `KEY_*` / `VAR_*` / `KBR_*` → `--focus`
- **无输入** → 不加 `--focus`，覆盖全部 **输入可达** 义务
- 核内 `loopId` / `blockId` / `taskId` 等与 `not_input_derivable` KEY **默认剔除**，勿塞进 focus 强测

## 门禁

- 失败 `init_required` → 先 `/tg-init` 至 confirmed
- review 中 `Allow solve: no` → 禁止 AskQuestion approve
- 大缺口 → 回 init：uo-query Tasks → `--merge-uo-resolve`，勿手改 lexicon

## 批准后

```powershell
tg-solve "$PROJECT_ROOT" --op-name $OP_NAME --level L0
```

级别：`skills/tg-plan/references/levels.md`。详文：`docs/tg-plan-workflow.md`。
