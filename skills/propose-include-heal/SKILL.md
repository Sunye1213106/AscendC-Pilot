---
name: propose-include-heal
description: 为未解析 include 提议额外 -I。uo-init 的 include-heal 提议步使用。
---

# 提议补 include

只写 staging。探针失败是 **include 路径与当前 CANN 树没对齐**，不是官方包缺文件，也不是算子图上的 `unknown`。本步提议额外 `-I`，不手改算子源码，不假造缺失头，不改共享 `spec/build_context.yaml`。

正式 extras 由 `heal_promote` 校验后追加。staging ≠ canonical。

## 输入 / 输出 / 停

读：探针 / scope 失败收据（`clang_probe_unclean`、`SCOPE_VALIDATE_BLOCKED`、缺头文件报错）、当前 cann_root 线索。写：本 Action staging 里的 extras 提议。

`CANN_ENV_NOT_READY` 只表示 cann_root 没配上或目录不像 CANN。那不是本步靠加 `-I` 能补上的；先让环境就绪。

完成：提议的 extras 可被引擎 promote，或说明补不上。

## 步骤

1. **先排除环境。** cann_root 是否指向真实 CANN（有 `cann-asc-devkit/` / `cann-metadef/` 一类结构）。不是 → 停止提议，写明要配根目录。官方 `.run` 不缺常见头；不要把 `tuple.h` 当成算子 bug。
2. **读失败是哪颗头、从哪份源码 include。** 提议的 `-I` 必须能解释这次缺失，不要堆一组「常用 CANN 路径」碰运气。
3. **只加 include 根。** 不要把 `ascendc/include/basic_api` 加成 kernel 主 include（相对路径会解析错）。不要把 CANN / 共享头残差当成算子错误。不要把 `RegTensor` / `VecReg` 再 stub 一遍。
4. **写 staging。** 每条 extra 写：路径、为什么、对应哪次探针报错。不要手改 `uo/summary/build_context_extras.yaml`（那是 prepare / promote 的事）。
5. **补不上就说。** 缺的是算子自己的头、或不在 CANN 树、或需要改源码 include 行 → 标明补不上，不要用假路径换绿灯。

## 常驻判断

确定性提取优先。未闭合项记入 unresolved；不要用 LLM 补进正式 `.uo`。本步甚至不碰图。

范围不由人工确认文件清单。发现 common ≠ 消费 common：共享头进范围后必须按范围成员走，不得按算子名丢掉。

禁止跳过编译验证、禁止命名闭合、禁止跨 architecture 混符号。Clang 是权威，regex 不是。

脚本仍找不到时 workflow 进入 heal；本步只负责提议。不要宣布 PASS。

## 看到这样

| 现象 | 判断 |
| --- | --- |
| `CANN_ENV_NOT_READY` | 先配 cann_root，不要堆 `-I` |
| 探针点名某颗头 | 提议能解释这次缺失的 include 根 |
| 想加 `basic_api` 当 kernel 主 include | 禁止 |
| 想 stub `RegTensor` / `VecReg` | 禁止 |
| 想手改 extras 或 `spec/build_context.yaml` | 禁止 |
| 缺的是算子自己的头 / 要改 include 行 | 标明补不上 |
| 想补进 `.uo` | 禁止 |

## 完成勾选

- [ ] 每条 extra 有路径、原因、对应报错
- [ ] 没有假造头、没有改源码
- [ ] 可 promote，或明确补不上

## 循环

1. 先排除 cann_root 未就绪。
2. 读探针缺的是哪颗头、从哪 include。
3. 提议能解释这次缺失的 `-I`，写进 staging。
4. 补不上（算子自己的头、要改 include 行）就标明。
5. 停。不要手改 extras，不要 stub 符号，不要改 `.uo`。

## 输出形状

staging 里每条 extra：路径、为什么、对应哪次探针报错。补不上则写原因（环境 / 算子自己的头 / 需要改 include 行），不要用假路径换绿灯。

## 反模式

- cann_root 没配就堆一组常用 `-I`
- 把 `basic_api` 加成 kernel 主 include
- stub `RegTensor` / `VecReg` 或假造缺失头
- 手改 `build_context_extras.yaml` 或共享 spec
- 把 CANN 残差写成算子图 unknown
- 跳过编译验证换绿灯
- 把 include 失败写成算子 `unknown` 去调查

staging ≠ canonical。promote 之前 extras 不是正式构建上下文。

## 指针

探针 / include 失败时怎么分环境 vs 真缺头：`references/codemap-build-gotchas.md`。
