# UO query hooks for scenarios

**When to load**：给 CE / TG 从 CodeMap 找结构事实时。查询面见 `skills/uo-query/SKILL.md`。场景 id 若出现在计划「测试内容」里，TG 自己对照 `scenario-catalog.md` 总结；CE 不写场景 yaml。

形态见 code-access 不变量。

UO 只定位结构。不判断 golden、happens-before、profiler。

| 要找什么 | 形态 |
| --- | --- |
| Cast / DataCopy / DataCopyPad / EnQue / DeQue | 标识符：API 名 |
| INPUT dtype / 维名 | 标识符，或无参数索引看维 |
| Buffer / queue / InitBuffer | 标识符：buffer 或 API 名 |
| 切分字段写点 / 公式 / 占核 | 标识符：字段名；不够再 `--file --line` |
| 某维有没有编进模板 | `Dim=V` |
| Pre / Main / Post / 三相 launch | 无参数索引（看 launch 阶段） |
| Host TilingContext / 同名函数 | 标识符；定义点跟卡片 `next` |
| diff 邻域 | `--file --line`，再对 FOCUS 名做标识符查询 |
| tail / 运行时分支 | `--file --line` 或标识符 |

空图命中按卡片 `next` 再查；禁止 `findstr /S`。最后才 `pilot_cli` `ro-search --pattern <pat> --paths <已 citation 文件>`。
