# 任务：FAG arch35 uo-init 压到 2 分钟内

## 目标
测出现在 FAG arch35 全流程墙钟，在保证正确性的前提下压到小于 2 分钟。不加单测、不加超时跳过。

## 待办事项
- [x] 真冷测量并压榨：最好 153s（prepare 21 + extract 57 + analyze 67），gold 通过
- [x] 去掉 host 双遍 walk、prepare↔extract 活 TU、跳过嵌套 .ascendc-pr 扫描
- [x] 确认 disk AST 无法 from_ast_file；prepare 内 walk 会 GIL 互抢，不能再塞回去

## 进度
3/3

## 结论
全流程真冷最好约 153s，未进 120s。剩余地板：host 单 TU walk ~50s + clang parse ~20s + analyze ~60s。
