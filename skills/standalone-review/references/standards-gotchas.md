# Standards 易错点

**何时加载**：写仓规范 / 跨层 / 并发发现时。

- 跨层合同优先于本地风格。Host 改动必须对照 Tiling / Kernel 合同；只看 diff 行不够。
- TilingData 来源 ≠ 已校验：必须能 locate 到 `OP_CHECK_IF` 且变量同一。
- UT 不在图里：只读 `tests/**` 搜新字段名；对 test 文件查图为空是预期。
- 并发与 Buffer 冲突看 tposition + 调用点。EnQue/DeQue 是 TQue，看 QUEUE 方向；Set/Wait、CrossCore 看 `flag_paired`。happens-before 不是 UO。
- 发现必须有 `path:line`。
