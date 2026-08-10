# review

确定性审查最终 `.uo` 的结构与证据一致性。

至少检查：产品可读、BuildVariant/ARCH 一致、Host 与 Kernel 存在、关键跨层路径有 provenance、无笛卡尔积补边、unresolved 与 audit/summary 一致。

结构或证据不满足时 fail closed 并返回 rework reason；本 Action 不调用 Agent、不绑定 task prompt。
