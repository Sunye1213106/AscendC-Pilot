# prepare

确定性发现 operator root、architecture、BuildVariant 与候选源码范围。

内部步骤：`prepare_layout` → `scope_scan` → `scope_confirm`。范围唯一时自动接受；只有确定性扫描留下真实歧义时，才由 primary 使用 `uo/scope-confirmation` 做最小选择。

不在本 Action 做 Host/Kernel 语义分析。
