# 对照本轮

构造 + Replay 刚结束。先按「跟预期是否一样」切开，再只对不一样的做分析。本步写 worklog 草稿：记下 R、分类、引理、下轮怎么改。不签发、不改 cases 表、不写 `tg/closure/**`。

权威证据：dispatch/key 看 Host Replay；不可达看经审查的源码引理；`P-*` / `F-*` 看 harness 收据。

worklog 文首 `open:` 列出仍开放的义务。open 非空不得假装本轮已闭合。需要改构造就保持 open。

## 输入 / 输出 / 停

读：本轮行、Replay 收据、计划义务（含预期 `hit`）、init 列、已有引理。写：本轮 worklog 草稿。

完成：每条义务被标成「进 R」或「仍 open + 原因」；不一致的已分类；有 P⇒Q 的已更新引理并写下轮改哪几列。

没有 Replay 收据时，不要用「看起来能过」关闭 dispatch/key。没有经审查引理时，不要用搜索失败关闭不可达。

## 步骤

1. **先切两堆。** 拿计划里这条义务的预期（目标 key / 分支 / 公式结果 / harness 口径），对照本轮收据。
   - 一样 → 进 R（或关 derived / 记下 harness 通过）。不要再分析。
   - 不一样 → 留下，进入分类。缺收据 → 保持 open，不要猜。分类桶见本窗装载的失败模式表。

2. **预期一样的直接进 R。** 只认真实 oracle 的成功观测。
   - dispatch/key：Host **HIT**（实际 TilingKey = 目标 key）才能进 R。
   - `P-*` / `F-*`：看 harness 收据，不是 Host HIT。缺收据 → `harness_missing`，保持 open。
   - target / 模型预测 / 构造意图都不是 R。

3. **不一样的先分类。** 不要按 case 写散文，按类归堆。类目录见本窗装载的失败模式表。先认这几桶：
   - `REWRITE`：Host 接受但改写到别的 key
   - `REFUSE`：Host 拒绝
   - `CRASH` / `NOT_RUN`：环境，不是语义
   - 构造错：列填错 / recipe 错 / shape 不合法
   - oracle 错位：拿 Host 命中当精度/性能
   - 未声明态：Host 产出计划域外的值

4. **分类 + 源码 → 推引理。** 每一类写成可反驳的 P⇒Q，读 `skills/source-proof/SKILL.md` 做推导；要出证书草稿再读 `skills/lemma/SKILL.md`（先 `INDEX.md` 再最多 3 份正文）。本步更新 worklog 里的引理，不写排除集、不填 review。`Replay reject ≠ E`。CRASH 禁止写 E。

5. **指导下轮 + 同步 worklog。** 用引理写「下轮改哪几列、别再盲搜什么」。更新文首 `open:`：能关的写证据窗口，不能关的写还缺什么观测或哪条引理。需要改构造 → 保持 open，回构造。

## 常驻判断

HIT / REWRITE / REFUSE 是 Host tiling 回放裁决（无 NPU），只对 dispatch/key 有意义。**HIT** = Host 接受且实际 TilingKey 等于目标 key。`REWRITE` / `REFUSE` 是预期外观测，供分类和引理，不是 E。

`P-*` 是精度场景 id（如 `P-DTYPE`），`F-*` 是性能场景 id（如 `F-SHAPE-TYPICAL`）。它们的 oracle 是 harness，不是 Host。Host 命中 TilingKey 关不了这两类义务。

正式产物是稍后 promote 的 `worklog.md`。引理 span 来自查图；Grep 只作定位辅助。

禁止：

- 把预期不一致的行解释成「其实也算命中」硬塞进 R
- 把 Host reject 写成源码不可达或 E
- 把搜索失败写成「不存在」
- 无观测写运行时不可达
- 用精度失败解释 dispatch 未命中，或反过来
- 未分类就盲搜下一轮

需要改构造 → 保持 open，回到构造，不要在 worklog 里「解释掉」。

完整性用语（全部 / 唯一 / 从不）依赖经审查引理。本步最多提出或更新线索；PROVED 只能来自带源码窗口的推导。

## 看到这样

| 现象 | 判断 |
| --- | --- |
| 与义务预期一致且是 HIT | 进 R；这条不必再推引理 |
| REWRITE / REFUSE | 预期外；分类后推引理，不是 E |
| CRASH / NOT_RUN | 环境；open，禁止写 E |
| `P-*` / `F-*` 只有 Host HIT | 关不了；缺 harness → `harness_missing` |
| 行填错列 / recipe 错 | 保持 open，回构造 |
| 「搜索没找到」 | 不是不可达；最多挂证明线索 |
| 同类 rewrite 重复出现 | 停盲搜；按引理改控制列 |

## 完成勾选

- [ ] 先按预期切堆，没有从散文四段写起
- [ ] 预期一致的已进 R（或已标 harness / derived 通过）
- [ ] 预期外的已分类，每类有 P⇒Q 或「还缺窗口」
- [ ] 下轮构造指令写清：改哪些列 / 停什么盲搜
- [ ] 文首 `open:` 与正文一致
- [ ] 没有签发、没有改 cases、没有写 `tg/closure/**`

## 循环

1. 取出本轮每条行的义务预期与 Replay / harness 收据。没有收据就 open。
2. 一样 → 记入 R（或关对应义务）。
3. 不一样 → 归类。同类合并，不要一条 case 一篇。
4. 每类写成 P⇒Q，结合源码推引理；能证 / 能驳都写进 worklog 引理段。
5. 用引理写下轮构造。更新 `open:`。空了才能谈闭合。

worklog 是给下一轮构造看的。只记现象、不写「下轮怎么改」，下一轮就会重复盲搜。

## 输出形状

文首：

```text
open: [义务id — 原因]
```

然后三块：预期一致（进 R 的 key / 义务 + 证据窗口）；预期不一致（类 → 观测 → 引理 P⇒Q → 下轮改哪列）；引理清单（本轮新增 / 改写 / 驳回）。

## 指针

预期外分类与记账红线见本窗装载的失败模式表。硬命题：`skills/source-proof/SKILL.md`。引理：`skills/lemma/SKILL.md`。已有引理产物先读其 `INDEX.md`，再最多打开 3 份正文。
