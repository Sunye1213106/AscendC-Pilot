# plan_build (migrated domain method)

> Domain content migrated from skills-src/tg-plan/references/levels.md. Do not advance Harness state from this file.

# 覆盖级别（tg-plan）

| Level | 含义 | 默认 |
| --- | --- | --- |
| `L0` | 功能冒烟：功能开关 / 可选输入取值（在选定范围内） | ✅ 默认生成 |
| `L1` | 范围内的 kernel branch（focus / topic / impact；省略 = 整仓输入可达） | ✅ 默认生成 |
| `L2` | 全部可达 TilingKey | 可选 |

**无 L3。**

## 范围

| 来源 | 行为 |
| --- | --- |
| 人工输入 → LLM → `--focus` | 只覆盖命中的 KEY / VAR / branch |
| 无 focus | 全部 **输入可达**（已剔除核内不可控 / `not_input_derivable`） |
| `--topic` | 主题再裁剪；可与 focus 叠加 |

```powershell
# 禁止 tg-plan CLI（Plugin 会拦截）；经 Harness：
harness start tg-plan --project <算子仓> --op-name <op> --level L0
harness run-action plan_build --project <算子仓>
# focus / topic / level 经 harness start 或 context/harness_params.yaml 传入
```

产物目录：`plan/levels/<L0|L1|L2>/`，互不覆盖。
