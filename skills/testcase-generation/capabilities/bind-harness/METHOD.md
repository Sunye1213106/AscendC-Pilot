# TG bind-harness

只写 **一份** `runs/<run_id>/actions/bind_init/parts/harness.yaml`。正式 `tg/init.yaml` 由 `bind_promote` 写入。查图只用 `pilot_cli` `uo-query`。

本步 refs：`references/test-script-repo.md`、`references/construction-gotchas.md`。

## 方法

1. 读 `runs/<run_id>/receipts/repo_scan.yaml`。`kind=script_repo` 才读测试脚本仓；`kind=default_input` 不要假装已有仓。仓内 `tests/` / `ut` 未经用户确认，不得当成 harness。
2. **golden**：脚本 golden 计算流 vs 算子逻辑。取值 `match` / `mismatch` / 缺口。把矛盾写清楚。
3. **compare**：精度怎么比（脚本真实 flag，或脚本内比对函数）。argparse 没有的 `atol`/`rtol` 不要编。禁止写成 `--golden-only`。
4. **modes.precision** / **modes.perf**：脚本里有没有精度、性能测试，怎么跑、性能怎么比对。没有就写缺口，不要编。
5. **generate_inputs**：现在怎么造数。核对待测轴：接近 0、空 tensor、标量 tensor、inf/-inf/nan、上/下边界、末维对齐 vs +1、合法 vs 非法 range。常规值和特殊值分开记。参数有依赖（轴必须落在 rank 内等）不能靠列间独立组合。不够则写入 `gaps`（给后面 plan / ce-apply）。
6. **findings**：本路事实与缺口。

查图形态见 code-access 不变量。禁止整句 `--query`。

无仓时从算子 / 图提 golden 计算流和精度/性能口径，为后续改脚本或 `/ce-apply` 生成脚本打底。

## 禁止

- 写正式 `tg/init.yaml` 或另一路的 `bind.yaml`
- 把精度启发式标成 `--golden-only`
- 无仓时假装 `script_repo`
- 语义不得用仓级 Grep 代替 uo-query（Grep 只作定位辅助）
