# apply_gap_patch

确定性校验并合并 `resolve` 产生的 staged semantic patch。

只接受当前 run/action identity、Output Contract 与 provenance 校验通过的 patch；失败项保持 unresolved。该 Action 不调用 Agent、不绑定 task prompt，也不新增模型推断。
