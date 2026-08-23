# 写 plan 散文

读上一窗 `plan_scope` 回答和 `plan_fuse` YAML。不要重新分析源码，不要改覆盖模型。

## 输入 / 输出 / 停

写三节，标题固定：

```text
## 测什么
## 覆盖什么
## 怎么判定
```

禁止 Write。禁止交 YAML。`plan_promote` 只拼盘。

## 步骤

1. **测什么**：用 scope 的话说清主行为、使它不成立的条件、还不确定的轴。
2. **覆盖什么**：对照 fuse 的 Dimension / L0–L3，用散文说覆盖面；不要把 unresolved 写成已绑定。
3. **怎么判定**：对照 fuse 的 Target evidence / classifier，说 Replay 看什么。

未 `confirmed` 的轴写「未证实 / untestable」，不要升级成确定性 classifier。
