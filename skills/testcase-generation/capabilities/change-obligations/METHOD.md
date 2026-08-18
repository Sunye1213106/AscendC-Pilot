# change-obligations

把已 promote 的改动影响收成结构化测试义务。正式文件由 `obligations_promote` 写入。TG 只负责把义务求成具体 case。

## 方法

1. 读 Goal `artifacts.impact`。
2. 每条义务是一个对象，字段：
   - `change`：改了什么
   - `condition`：触发条件
   - `affected`：受影响节点/符号（必须能在 impact 或 CodeMap 对上）
   - `contrast`：对照点
   - `boundaries`：边界
   - `required_hits`：生成的 case 必须打到的点
3. 只覆盖这次改动 + 必要对照，不要偷偷写成全量 TilingKey。

## 禁止

- 写 `tg/plan.md` / `tg/cases.csv`
- 复用 `ce-review` 的审查结论当义务
- 发明不存在的标识符
