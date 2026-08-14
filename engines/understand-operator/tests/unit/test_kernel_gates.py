# -*- coding: utf-8 -*-
from pathlib import Path

from uo_init.build_context import BuildContext, source_uses_dtype_variants
from uo_init.kernel_gates import discover_kernel_gates, try_eval_pp


def _write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_try_eval_pp_arch_macros():
    macros = {"__NPU_ARCH__": "2201", "__CCE_AICORE__": "220", "__DAV_C220__": ""}
    assert try_eval_pp("(__NPU_ARCH__ == 5102)", macros) is False
    assert try_eval_pp("(__CCE_AICORE__ > 200)", macros) is True
    assert try_eval_pp("defined(__DAV_C220__)", macros) is True
    assert try_eval_pp("defined(__DAV_310R6__)", macros) is False
    assert try_eval_pp("(ORIG_DTYPE_QUERY == DT_FLOAT16)", macros) is None


def test_include_closure_skips_inactive_arch_header(tmp_path: Path):
    entry = _write(
        tmp_path,
        "op_kernel/entry.cpp",
        """
#if (__NPU_ARCH__ == 5102)
#include "wrong.h"
#else
#include "right.h"
#endif
""",
    )
    _write(
        tmp_path,
        "op_kernel/wrong.h",
        """
#if ORIG_DTYPE_QUERY == DT_BF16
#if TILING_KEY_VAR == WRONG_KEY
#endif
#endif
""",
    )
    _write(
        tmp_path,
        "op_kernel/right.h",
        """
#if (ORIG_DTYPE_QUERY == DT_FLOAT16) && (ORIG_DTYPE_KEY == DT_FLOAT16)
#if TILING_KEY_VAR == RIGHT_KEY
    INVOKE();
#endif
#elif (ORIG_DTYPE_QUERY == DT_BF16)
#if TILING_KEY_VAR == BF16_KEY
    INVOKE();
#endif
#endif
""",
    )
    macros = {"__NPU_ARCH__": "2201"}
    gates = discover_kernel_gates(
        entry, op_dir=tmp_path, macros=macros
    )
    assert "ORIG_DTYPE_QUERY" in gates.orig_dtypes
    assert "ORIG_DTYPE_KEY" in gates.orig_dtypes
    assert gates.pick_tiling_key_var("DT_FLOAT16") == "RIGHT_KEY"
    assert gates.pick_tiling_key_var("DT_BF16") == "BF16_KEY"
    idents = {ident for _, ident in gates.tiling_key_choices}
    assert "WRONG_KEY" not in idents


def test_kernel_args_inject_all_orig_and_one_tiling_key(tmp_path: Path):
    entry = _write(
        tmp_path,
        "op_kernel/entry.cpp",
        '#include "dispatch.h"\n',
    )
    _write(
        tmp_path,
        "op_kernel/dispatch.h",
        """
using xType = DTYPE_X;
#if (ORIG_DTYPE_QUERY == DT_FLOAT16) && (ORIG_DTYPE_ATTENTION_OUT == DT_FLOAT16)
#if TILING_KEY_VAR == QF16_PATH
#endif
#endif
""",
    )
    ctx = BuildContext.load(
        cann_root="D:/c",
        ops_root=str(tmp_path),
        op_dir=str(tmp_path),
        arch_dir="arch22",
    )
    joined = " ".join(
        ctx.kernel_args(dtype_variant="DT_FLOAT16", source_path=entry)
    )
    assert "ORIG_DTYPE_QUERY=DT_FLOAT16" in joined
    assert "ORIG_DTYPE_ATTENTION_OUT=DT_FLOAT16" in joined
    assert "TILING_KEY_VAR=QF16_PATH" in joined
    assert "DTYPE_X=half" in joined
    assert "DT_FLOAT16=1" in joined
    assert source_uses_dtype_variants(
        entry,
        op_dir=tmp_path,
        macros=ctx.kernel_defines(),
    )


def test_kernel_args_without_source_still_skip_dtype_macros():
    ctx = BuildContext.load(cann_root="D:/c", ops_root="D:/o", op_dir="D:/o/fag")
    joined = " ".join(ctx.kernel_args(dtype_variant="DT_FLOAT16"))
    assert "ORIG_DTYPE_QUERY=DT_FLOAT16" not in joined
    assert "TILING_KEY_VAR=" not in joined


def test_defined_orig_dtype_does_not_close_include(tmp_path: Path):
    """``defined(ORIG_DTYPE_X)`` is true at clang time; discovery must not skip it."""
    entry = _write(
        tmp_path,
        "op_kernel/entry.cpp",
        """
#if defined(ORIG_DTYPE_X) && ORIG_DTYPE_X == DT_INT4 && ORIG_DTYPE_WEIGHT == DT_INT4
#include "quant.h"
#endif
""",
    )
    _write(
        tmp_path,
        "op_kernel/quant.h",
        """
#if TILING_KEY_VAR == QUANT_KEY
    INVOKE();
#endif
""",
    )
    gates = discover_kernel_gates(entry, op_dir=tmp_path, macros={})
    assert "ORIG_DTYPE_X" in gates.orig_dtypes
    assert "ORIG_DTYPE_WEIGHT" in gates.orig_dtypes
    assert gates.pick_tiling_key_var("DT_INT4") == "QUANT_KEY"


def test_mixed_orig_assignment_is_opt_in(tmp_path: Path):
    """Uniform preferred dtype stays on the primary walk; mixed map is separate."""
    entry = _write(
        tmp_path,
        "op_kernel/entry.cpp",
        '#include "dispatch.h"\n',
    )
    _write(
        tmp_path,
        "op_kernel/dispatch.h",
        """
#if (ORIG_DTYPE_QUERY == DT_FLOAT16) && (ORIG_DTYPE_KEY == DT_FLOAT16)
#if TILING_KEY_VAR == F16_PATH
#endif
#endif
#if defined(ORIG_DTYPE_X) && defined(ORIG_DTYPE_WEIGHT) && defined(ORIG_DTYPE_SCALE)
#if ORIG_DTYPE_X == DT_INT8 && ORIG_DTYPE_WEIGHT == DT_INT4 && ORIG_DTYPE_SCALE == DT_UINT64
#include "quant.h"
#endif
#endif
""",
    )
    _write(tmp_path, "op_kernel/quant.h", "void EnQueBody();\n")
    ctx = BuildContext.load(
        cann_root="D:/c",
        ops_root=str(tmp_path),
        op_dir=str(tmp_path),
        arch_dir="arch35",
    )
    gates = discover_kernel_gates(
        entry,
        op_dir=tmp_path,
        macros=ctx.kernel_defines(),
    )
    mixed = gates.pick_mixed_orig_assignment("DT_FLOAT16")
    assert mixed is not None
    assert mixed.get("ORIG_DTYPE_X") == "DT_INT8"
    assert mixed.get("ORIG_DTYPE_WEIGHT") == "DT_INT4"
    assert mixed.get("ORIG_DTYPE_SCALE") == "DT_UINT64"

    uniform = " ".join(ctx.kernel_args(dtype_variant="DT_FLOAT16", source_path=entry))
    assert "ORIG_DTYPE_QUERY=DT_FLOAT16" in uniform
    assert "ORIG_DTYPE_X=DT_INT8" not in uniform

    mixed_args = " ".join(
        ctx.kernel_args(
            dtype_variant="DT_FLOAT16",
            source_path=entry,
            orig_assignment=mixed,
        )
    )
    assert "ORIG_DTYPE_X=DT_INT8" in mixed_args
    assert "ORIG_DTYPE_WEIGHT=DT_INT4" in mixed_args
    assert "ORIG_DTYPE_SCALE=DT_UINT64" in mixed_args
    assert "DT_INT8=2" in mixed_args
    assert "DT_INT4=" in mixed_args
    assert "DT_UINT64=" in mixed_args
