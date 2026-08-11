# 扩展 Skill

Skill 是 runtime method bundle，应该自包含。

## 新增或修改 Skill

1. 修改 `skills/<domain>/SKILL.md`。
2. 必要参考材料放在 `skills/<domain>/references/`。
3. 示例放在 `skills/<domain>/examples/<case>/`。
4. 行为变化时更新 `evals/skills/<domain>/`。
5. 运行：

```bash
python scripts/check_skill_architecture.py
```

## 规则

- 不依赖 `skills/_shared/`；它已经废弃。
- 不把项目架构说明复制进 Skill。
- evidence、completeness、gotcha 规则要靠近消费它们的 skill。
