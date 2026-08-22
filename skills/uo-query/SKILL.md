---
name: uo-query
description: 只读查询已有 Operator CodeMap。用户问图上有什么、谁调用、Key/Data/Kernel 怎么连时使用。
---

# 查 CodeMap

用已 commit 的 `.uo` 回答本路 FOCUS。工具：插件 `pilot_cli` 的 `uo-query`。合法形态见 kb-query capability；本步定义选哪种、何时停、怎么解释 partial / coverage。全局访问约束见 code-access。

## 输入 / 输出 / 停

读：本路 FOCUS、已有 `.uo`、查询卡片。写：对话作答。不写正式产物，不改 `.uo`。

缺 `.uo`：停，交给主控 `/uo-init` 或源码作答。stub 已给标识符 / `Dim=V` / `--file --line` 时直接用。否则先无参数索引，跟 `next` / `hint`。

完成：本 FOCUS 能用 `file:line` 作答，或 PARTIAL 并写明缺什么。partial 图不能证明「不存在」。

## 步骤

1. **选最短形态。** 名字 / 定义 / 写读 → 标识符。某维合法集 → `Dim=<维名>`。某组能否编过 → `Name=Value`。已知位点扩 1 跳 → `--file --line`（路径只从上一张卡复制）。多阶段 launch 先看无参数索引的 PIPE 名。
2. **调用 `uo-query`，卡片即窗口。** 有 `file:line` + snippet 视为已读；只要截断之外还需要行，才按卡片路径开最小窗口。
3. **`count:0` 缩短再查。** 跟 `hint` / `canonical`。仍空：只对已 citation 文件做 `pilot_cli` `ro-search`。然后 PARTIAL / UNKNOWN。
4. **列表结论引用覆盖字段。** `dim_coverage` / `edges` 的 `count` / `total_matched`。第一页 snippet 不是全集。
5. **问哪一层答哪一层。** Host 不产生 ≠ 模板不接纳；Host 分支 ≠ Kernel 分支。锁当前 architecture。差分题先 verdict 后证据。

## 常驻判断

**Claim 五层（不静默扩大）**

1. domain — 声明域允许什么值
2. template-admissible — 编译期模板/宏是否接纳
3. host-produced — Host 在何条件下写出
4. kernel-consumed — Kernel 是否消费
5. full reachability — 端到端可达（常需测试生成，不在本步发明）

完整性用语（全部 / 唯一 / 从不）依赖覆盖字段；索引 partial 时最多 PARTIAL。

`coverage_checked` = 合法宇宙（template_blocks / declared）已扫完，与 `matching_block_count` 无关。0 命中且已扫完仍是已覆盖的空集。`first_hit` 只留给未扫完的列表。`nearby` 属于 coverage（缺一维后的剩余宇宙）。

Host 失败码标识符打到 `ge.graphStatus` 根：拒单入口，不是 Kernel catalog。边上的站点才是 guard；有失败根 ≠ 某维永不产生。

问句里的局部名常常不是 TILING_FIELD 名；空了看 `next` / `canonical` / `hint`。同名函数看卡片全部 kind 与 `edges`。运行时值不能回填成宏条件。unresolved 不可凭命名闭合。配对 / 时序 / 仿真 / sanitizer 不在 UO。

## 看到这样

| 现象 | 判断 |
| --- | --- |
| 没有标识符 | 无参数索引，跟 `next` |
| 这个名字是什么 / 谁写谁读 | 标识符 |
| 这维会不会编过 / 有没有 kernel | `Dim=V` |
| 已有 `file:line`，要邻居 | `--file --line` |
| `count:0` | 按 `hint` 缩短再查；不是「不存在」 |
| 第一页没看到某维 | `dim_coverage`，不是 snippet |
| 卡片已有 snippet | 视为已读 |
| 时序 / 测量 / sanitizer | 停：不在 UO |
| 缺 `.uo` | 停：不是本步 |

## 完成勾选

- [ ] 结论有 `file:line`，或 PARTIAL 并写出缺什么
- [ ] 列表型结论引用了覆盖字段
- [ ] 层没扩：Host 没说成 Kernel，「没查到」没说成「不存在」
- [ ] 没有改 `.uo`，没有跨 arch 借命中

## 循环

每一轮只推进本路 FOCUS。

1. 手头有标识符 / `Dim=V` / `file:line`？没有 → 无参数索引。
2. 调用 `pilot_cli` `uo-query`。读 `file`、`next`、`hint`、snippet、覆盖字段。
3. 够作答就停。
4. 不够：跟 `next`，或按 `hint` 缩短。仍不够 → 最小源码窗，或 PARTIAL。
5. 写结论：先 verdict，再窗口。问哪一层答哪一层。

## 输出形状

```text
verdict: ANSWERED | PARTIAL | UNKNOWN
layer: domain | template | host | kernel
span: file:line
coverage: dim_coverage=... / count=...   # 列表型结论必填
missing: ...                             # PARTIAL 必填
```

## 指针

走到该域才打开：

- TilingKey / packing：`references/uo-key.md`
- TilingData 写读：`references/uo-tilingdata.md`
- Kernel 分支：`references/uo-kernel.md`
- Template / BuildVariant：`references/uo-template.md`
- Buffer：`references/uo-buffer.md`
- unresolved：`references/uo-gaps.md`

权威分层与任务→形态（含「再补 / UO 不回答」）：`references/uo-product-map.md`。
