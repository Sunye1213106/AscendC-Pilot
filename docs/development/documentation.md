# 文档维护规则

## 什么属于 Docs

人类说明放在 `docs/`。

例如：

- 架构总览
- 模块职责
- 开发指南
- reference tables
- 历史 case studies 和 benchmark notes

## 什么留在代码旁边

Runtime inputs 留在 runtime 期望的位置：

- `skills/*/SKILL.md`
- `skills/*/references/*.md`
- `skills/*/examples/**`
- `prompts/tasks/**/*.md`
- `pilot/policies/**`
- `pilot/runtime/**`
- `tools/**`
- `generated/**`

## 不再新增模块 README

不要在 `pilot/`、`agents/`、`engines/`、`skills/`、`prompts/`、`tools/`、`adapters/` 或 `evals/` 这类模块目录下新增 developer-facing `README.md`。

允许的 README：

- `README.md`
- `docs/**/README.md`
- `skills/*/examples/**` 下作为 runtime example 的 README
- eval tooling 需要读取的 live-case README

## Module Doc 模板

模块页统一使用这些章节：

```text
# Module Name
## 定位
## 职责
## 非职责
## 入口
## 输入
## 处理流程
## 输出
## 不变量
## 失败与恢复
## 集成关系
## 实现锚点
## 测试
```

## 检查

```bash
python scripts/check_docs.py
```
