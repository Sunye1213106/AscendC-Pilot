# FAG arch35 Kernel 语义：uo-query 对照源码

Host 侧 TilingKey 引理（13 组）噪声确实偏低：cover 分层对、函数窗口准。本轮改测 **Kernel**：TPipe 三相、TQue、Buffer/TBuf、MutexBuffer 策略、核间/核内同步。权威是当前算子源码，查询走刚冷启动的 `.uo`。

探针：53 次串行 `uo-query`，约 7 s。卡片：`uoquery-kernel-cards.json`。

## 源码里的预期答案

读 `entry_regbase.h` / `kernel_base.h` / `mutex_buffer*.h` / `common.h` 后，期望图上能指到：

| 主题 | 源码事实 |
| --- | --- |
| 单 launch 三相 | `RegbaseFAG` 里 `TPipe pipeIn`（213）→ Pre `SyncALLCores` → `pipeIn.Destroy` → `TPipe pipeBase`（宏 63）→ Main；非 FP32 再 `pipeBase.Destroy` + `TPipe pipePost`（94） |
| TQue | Pre：`helpQue/inputQue/castQue` VECIN、`outQue` VECOUT；Post：`inQueuePing` VECIN / `outQueuePing` VECOUT |
| Mutex | `class MutexBuffer`（mutex_buffer.h:52）；`AllocMutexID` 72 / `ReleaseMutexID` 81；`Lock`/`Unlock` 用 `AscendC::Mutex`；`Wait`/`Set` = delete（替代 HardEvent） |
| 策略 | P/dS：`IS_PRELOAD_TWO_TIMES` 时 `MutexBuffersPolicyDB`，否则 `SingleBuffer`（kernel_base.h:127–130）；另有 3buff/4buff 类 |
| 使用点 | `dSL1Buf.Get()` / `pL1Buf.Get()` → `MutexBuffer<L1, NO_SYNC>`（kernel.h:60–61） |
| 同步 | Pre `SyncALLCores` → `SyncAll<false>`；Main `CrossCoreSet/WaitFlag`；Post `SetFlag/WaitFlag<HardEvent>` |
| flag 重叠 | `SYNC_DETER_FIX_FLAG=10` 与 `SYNC_V2_TO_C1_FLAG={10,11}` 写在 common.h:41–45 相邻 |

## 能不能找到

### 能，而且对得上源码

**三相 TPipe（实例名）**

| 查询 | 命中 | 与源码 |
| --- | --- | --- |
| `pipeIn` | PIPE @ entry:213 `TPipe pipeIn` | 对 |
| `pipeBase` | PIPE @ entry:63，snippet 含 `pipeIn.Destroy` + Pre `SyncALLCores` | 对 |
| `pipePost` | PIPE @ entry:94，snippet 含 `ORIG_DTYPE_QUERY != DT_FLOAT`、`pipeBase.Destroy` | 对 |
| 无参数索引 | 三点 63 / 94 / 213，同一文件 | 位点对；**名字只标 1/2/3，没有 Pre/Main/Post** |

`RegbaseFAG` @ 201 是入口，不是 `ProcessVec*`。索引 hint 仍是 TilingKey 口径，没有写 PIPE 名——要三相必须再查 `pipeIn/pipeBase/pipePost`，或从 63/94/213 around。

**TQue 实例（不要查类型名 `TQue`）**

`inQueuePing` / `helpQue` / `inputQue` / `outQue` 全部 QUEUE，行号与声明一致；snippet 带 `QuePosition::VECIN/VECOUT`；`next` 有 `AllocTensor`/`EnQue`/`DeQue`/`AscendC::TQue`。  
`TQue` 类型名 **count=0**（故意不回 catalog 根），和契约一致。

**MutexBuffer 家族**

| 查询 | 命中 |
| --- | --- |
| `MutexBuffer` | TYPE :52 + 构造 METHOD :61 |
| `MutexBufferManager` | TYPE :22，snippet 含 `pipe->InitBuffer` |
| `MutexBuffersPolicySingleBuffer/DB/3buff/4buff` | 各自 class 行 41/74/143/256 |
| `AllocMutexID` / `ReleaseMutexID` | OPERATION :72 / :81 |
| `Lock` / `Unlock` | METHOD + `AscendC::Mutex::Lock/Unlock` |
| `l1BufferManager` | BUFFER @ kernel_base.h:126，**snippet 已带 DB vs SingleBuffer 的 conditional** |
| `dSL1Buf` / `pL1Buf` | 使用点 kernel.h:60–61，`MutexBuffer<L1, NO_SYNC>` |

around `MutexBuffer:52` 邻居含 `tensor_` CONTAINS；around `pipeBase:63` 邻居 `mm1ResBuf` BINDS。这是预期里的「谁管 L1、谁绑在 Main pipe 上」。

**同步**

| 查询 | 命中 | 评价 |
| --- | --- | --- |
| `SyncALLCores` | PreRegbase:280 → `SyncAll<false>()` | 对，但是 **kernel_base.h:2392 同名实现没出现**（第一张吃掉） |
| `CrossCoreSetFlag` | kernel.h:68 `PIPE_MTE3` + `SYNC_V3_TO_C3_FLAG` | 对，CV 等 L1 的那条 |
| `CrossCoreWaitFlag` | kernel.h:57 | 对 |
| `SetFlag`/`WaitFlag` | Post:138–139 `HardEvent::MTE3_S` | 对，核内 event |
| `SYNC_DETER_FIX_FLAG` | COMPILE_VAR common.h:41 **和** EVENT 使用点 kernel.h:288 | 对 |
| `SYNC_V2_TO_C1_FLAG` | common.h:45 `{10,11}`，snippet 紧挨着 FLAG=10 | **重叠证据在同一窗** |
| `SetScheduleMode` | **Host** PostTiling :1504，`BN2 && isBn2MultiBlk && TND` 不设 | 问「为何 PostTiling 设 1」能答；不是 Kernel API |

`Destroy` @ 62：`pipeIn.Destroy()`，三相里 Pre→Main 的交接。

### 空结果是预期，不是漏图

`LocalTensor` / `TQue` / `HardEvent` / `PIPE_MTE3` / `PIPE_MTE2` / `PIPE_FIX` → count=0。  
类型名不回 catalog 根；要用实例（`inQueuePing`）或 `next` 里的 `AscendC::TQue`。`TPipe`/`TBuf` 这次命中了 **实例** `tPipe`（空 tensor apt.cpp:56）和 `tbuf`（manager:28），不是类型根。比纯空更有用，但不要当成「类型 catalog 已打开」。

## 噪声 / 缺口（比 Host 引理大一档，但仍可用）

1. **泛名第一张偏了**  
   - `pipe` → NzPost 成员 `TPipe *pipe`（:46），不是 launch 上的 `pipeIn`。  
   - `buffer` → common `class Buffer`（buffer.h:161），**不是** mutex policy。问策略要打 `MutexBuffersPolicy*` 或 `l1BufferManager`。  
   - `InitBuffer` 只落到 MutexBufferManager:29，Pre/Post 里一串 `pipe->InitBuffer(helpQue, …)` 不在第一张。

2. **同名多定义只出一张**  
   `SyncALLCores` 有 Pre 与 KernelBase 两处，卡只给 Pre。around 邻居是 Pre 的 class，不会自动列出 Base。要第二处得再查 `FlashAttentionScoreGradKernelBase` 或从索引 `next` 猜。

3. **name 卡缺投影字段**  
   QUEUE snippet 里有 `QuePosition::VECIN`，但卡上 `tposition`/`wrapper` 为空。Mutex BUFFER 的 `wrapper=MutexBuffer` 也没出现在 name 卡上（init 报告的 graph 里有，查询层没带出来）。要位置语义得读 snippet 或再 around。

4. **索引三相不命名**  
   63/94/213 对，但 `name=1/2/3`。不会自己写出「pipeIn Pre → pipeBase Main → pipePost」。这是已知评分点，这次复现。

5. **around 会拌进邻近 EVENT**  
   `dSL1Buf:60` 的 around 带上 `SYNC_C4_TO_V3_FLAG`；`MutexBuffer` 构造行 around 第一 seed 曾标成 `LockCons`（同行折叠）。1 跳有用，但第一 seed 不一定是你点的那个符号。

## 和 Host 侧对比

| | Host TilingKey 引理 | Kernel 同步 / Buffer |
| --- | --- | --- |
| 查对名字 | 高（函数名稳定） | 高（实例名）；类型名故意空 |
| 第一张 kind | 偶发 KEY/TilingData | 偶发泛 `pipe`/`buffer` |
| 预期答案能否找到 | 13/13 分层对 | 三相、TQue、Mutex 策略、flag 重叠、CV flag **都能找到** |
| 不能当全集的 | cover 第一页 | 同名 METHOD / 全量 InitBuffer 站点 |

**结论**：Host 提取噪声小这个判断成立。Kernel 侧 **实例 + 专用类型名**（`pipeIn`、`MutexBuffersPolicyDB`、`dSL1Buf`、`SYNC_DETER_FIX_FLAG`）同样能打到源码预期窗，质量够用；**不要用 catalog 类型名，不要用泛名 `pipe`/`buffer` 结案，不要假设第一张是唯一实现**。`tposition`/`wrapper` 还没进 name 卡，位置语义要靠 snippet。
