---
name: uo-query
description: 只读查询已有 Operator CodeMap。用户问图上有什么、谁调用、Key/Data/Kernel 怎么连时使用。
---

# 查 CodeMap

本步用已有 `.uo` 回答本路 FOCUS：图上有什么、谁写谁读、某维是否注册。权威是已 commit 的 `.uo`，不是记忆、不是未校验草稿。查询工具是插件 `pilot_cli` 的 `uo-query`。形态见 code-access 不变量（无参数索引 / 标识符 / `Dim=V` / `--file --line`）。

不要改 `.uo`。不要宣布工作流 PASS。查询完成后立刻作答，不要为了先分类问题而空转。

## 输入 / 输出 / 停

读：本路 FOCUS、已有 `.uo`、查询卡片。写：对话里的作答（只读，不写正式产物）。

没有具体标识符时先做无参数索引，再跟卡片 `next` / `hint`。stub 已给出标识符、`Dim=V` 或 `--file --line` 时直接用那一种。缺 `.uo` 不是本步的事：停，让主控去 `/uo-init` 或改用源码作答。禁止在仓库根目录 Glob 找产物。

完成：本 FOCUS 能用 `file:line` 作答，或只能 PARTIAL 并写明缺什么。partial graph 不能证明「不存在」。

## 步骤

1. **选最短形态。** 名字 / 定义 / 字段写读 → 标识符。模板能否编过、kernel 是否注册 → `Dim=V`。从已知位点扩邻居 → `--file --line`。多阶段 launch 先看无参数索引里的 PIPE 阶段，不要把内层函数名当阶段。
2. **先图后源码。** 已有 `.uo` 时不要一上来 grep 整棵算子树。卡片带 `file:line` + snippet 视为已读；只要截断之外还需要行，才按卡片路径开最小窗口。路径从卡片 `file` / `next` 复制，禁止猜相对路径。
3. **空结果先缩短再查。** `count:0` 按 `hint` / `canonical` 缩短标识符再查一次。禁止仓级 findstr。最后才对**已 citation 的文件**做只读搜索。仍空则 PARTIAL / UNKNOWN，不要写成「图上不存在」。
4. **列表型结论用覆盖字段。** 声称某维没注册、某边没有，必须引用 `dim_coverage` / `edges` 的 `count` / `total_matched`。第一页 snippet 不是全集。
5. **问什么层就答什么层。** 主问只需 domain / 模板可接纳 / Host 写出时，不要扩到端到端可达。Host 不产生 ≠ 模板不接纳；Host 分支 ≠ Kernel 分支。
6. **锁当前 architecture。** 禁止用其他 arch 的命中闭合本 arch claim。差分题先给 verdict 再给证据，禁止「根因已定位」。

## 常驻判断

**Claim 五层（不静默扩大）**

1. domain — 声明域允许什么值
2. template-admissible — 编译期模板/宏是否接纳
3. host-produced — Host 在何条件下写出
4. kernel-consumed — Kernel 是否消费
5. full reachability — 端到端可达（常需测试生成，不在本步发明）

不同层级分开说。完整性用语（全部、唯一、从不、没有其他）依赖覆盖字段；索引 partial 时最多 PARTIAL。

**易错**

- 问句里的局部名常常不是 TILING_FIELD 名；空了看 `next` / `canonical` / `hint`。
- 同名函数看卡片全部 kind 与 `edges`，不要只信第一页。
- 运行时值不能回填成宏条件的唯一真值。
- unresolved 不可凭命名闭合。
- 配对、时序、仿真、sanitizer 不在 UO；不要用图回答 happens-before 或测量。

## 看到这样

| 现象 | 判断 |
| --- | --- |
| 没有标识符、不知道从哪开始 | 无参数索引，跟 `next` |
| 问「这个名字是什么 / 谁写谁读」 | 标识符查询 |
| 问「这个 Dim 值会不会编过 / 有没有 kernel」 | `Dim=V` |
| 已有 `file:line`，要邻居 | `--file --line`，路径从卡片复制 |
| `count:0` | 按 `hint` 缩短再查；不是「不存在」 |
| 第一页没看到某维 | 看 `dim_coverage`，不是看 snippet |
| 卡片已有 snippet | 视为已读，不要再 Read 同一段 |
| 问时序 / 测量 / sanitizer | 停：不在 UO |
| 缺 `.uo` | 停：不是本步 |

## 完成勾选

- [ ] 本 FOCUS 的结论能指到 `file:line`，或明确 PARTIAL 并写出缺什么
- [ ] 列表型结论引用了覆盖字段，没有用第一页当全集
- [ ] 没有把 Host 层结论说成 Kernel 层，也没有把「没查到」说成「不存在」
- [ ] 没有改 `.uo`，没有跨 arch 借命中

作答先给结论，再给窗口。差分题先 verdict 后证据。

## 循环

每一轮只推进本路 FOCUS，不要同时查三条无关线索。

1. 看手头有没有标识符 / `Dim=V` / `file:line`。没有 → 无参数索引。
2. 调用 `pilot_cli` `uo-query`。读卡片：`file`、`next`、`hint`、snippet、覆盖字段。
3. 够作答就停。snippet 已覆盖的窗口不要再 Read。
4. 不够：跟 `next`，或按 `hint` 缩短再查。仍不够 → 开最小源码窗，或 PARTIAL。
5. 写结论。问哪一层就答哪一层。不要把本轮变成全图巡检。

日常任务对照：名字/写读用标识符；能否编过用 `Dim=V`；已知位点扩邻居用 `--file --line`；多阶段 launch 先看 PIPE。配对、时序、仿真不在本步。

## 输出形状

```text
verdict: ANSWERED | PARTIAL | UNKNOWN
layer: domain | template | host | kernel
span: file:line
coverage: dim_coverage=... / count=...   # 列表型结论必填
missing: ...                             # PARTIAL 必填
```

不要写「图上不存在」。不要跨层把 Host 结论说成 Kernel。

## 指针

域专文（走到该域才打开）：

- TilingKey / packing：`references/uo-key.md`
- TilingData 写读：`references/uo-tilingdata.md`
- Kernel 分支：`references/uo-kernel.md`
- Template / BuildVariant：`references/uo-template.md`
- Buffer：`references/uo-buffer.md`
- unresolved：`references/uo-gaps.md`

权威分层与任务→形态表：`references/uo-product-map.md`。查询易错点：`references/codemap-query-gotchas.md`。
