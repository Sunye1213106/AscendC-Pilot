# -*- coding: utf-8 -*-
"""Kernel Root Trace — source-rooted graph symmetric with Host UO.

Algorithm (no execution analysis):

  1. Collect source facts (Clang walks + lexical fallback)
  2. Build complete type / alias / member / call graph
  3. Seed AscendC / CANN terminal roots (+ known framework wrapper contracts)
  4. Single reverse fixed-point over WRAPS / ALIASES / CALLS
  5. Mark REACHED / UNRESOLVED / EXTERNAL with auditable gaps

Does **not** compute exec_rank, RAW/WAR/WAW, happens-before, pipeline,
buffer lifecycle, or engine scheduling. Flag APIs (Set/Wait, CrossCore*, IB*)
record identity-level pair appearance. TQue EnQue/DeQue stay outside that
check — CANN encapsulates their handshake.
"""

from __future__ import annotations

from uo_init.paths import require_architecture
import os
import re
import time
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any

from uo_init.perf import TimeBudget, kernel_root_trace_budget_s
from uo_init.ids import buffer_site_id, make_id, operation_site_id, register_site_id
from uo_init.ir.codemap import CodeMap, _rid
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.passes import kernel_scan as kscan
from uo_init.passes.source_text_cache import read_text
from uo_init.semantics import registry as semreg
from uo_init.semantics.ascendc_storage import (
    ASCENDC_BUFFER_TYPES,
    ASCENDC_REGISTER_TYPES,
    ASCENDC_STORAGE_WRAPPER_TYPES,
    MUTEX_BUFFER_METHOD_BRIDGES,
    TENSOR_METHOD_BRIDGES,
    TPIPE_METHOD_BRIDGES,
    TQUE_METHOD_BRIDGES,
    is_non_storage_type,
    is_storage_type_text,
    is_storage_wrapper_type,
    is_valid_storage_name,
    memory_space_from_type_text,
    register_class_from_type,
    resolve_buffer_decl,
    storage_root_kind_from_space,
    tposition_from_type_text,
)
from uo_init.semantics.ascendc_vf import (
    AMBIGUOUS_VF_ROOTS,
    VF_ALIASES,
    is_ambiguous_vf_name,
    is_cann_vf_api,
    vf_root_spelling,
)
from uo_init.semantics.ascendc_util import is_cann_util_api
from uo_init.semantics.ascendc_sync import (
    FLAG_PAIR_MATE,
    SYNC_MECHANISM,
    flag_pair_key,
    is_flag_sync,
    is_tpipe_callee,
    is_tque_callee,
    resolve_sync_site,
)

# ---------------------------------------------------------------------------
# Reason codes (auditable gaps)
# ---------------------------------------------------------------------------

REASON_NO_ASCENDC_ROOT = "NO_ASCENDC_ROOT_REACHED"
REASON_TYPE_UNRESOLVED = "TYPE_CANONICALIZATION_FAILED"
REASON_CALL_UNRESOLVED = "NO_ASCENDC_ROOT_REACHED"
REASON_EXTERNAL = "EXTERNAL_DECL_UNAVAILABLE"
REASON_UNPAIRED_FLAG_SYNC = "UNPAIRED_FLAG_SYNC"

_ROOT_KIND_BY_CATEGORY: dict[str, str] = {
    "memory_transfer": "MEMORY_API",
    "memory_init": "MEMORY_API",
    "buffer_init": "MEMORY_API",
    "buffer_acquire": "MEMORY_API",
    "buffer_release": "MEMORY_API",
    "buffer_view": "MEMORY_API",
    "queue_enqueue": "MEMORY_API",
    "queue_dequeue": "MEMORY_API",
    "util": "UTIL_API",
    "sync_signal": "SYNC",
    "sync_wait": "SYNC",
    "sync_barrier": "SYNC",
    "reg_mask": "REGISTER",
    "vector": "COMPUTE_API",
    "vector_compute": "COMPUTE_API",
    "cube": "COMPUTE_API",
    "cube_compute": "COMPUTE_API",
    "cube_load": "COMPUTE_API",
    "cube_store": "COMPUTE_API",
    "memory_atomic": "MEMORY_API",
}

# AscendC / CANN terminal API spellings used as catalog roots (not project names).
_ASCENDC_API_ROOTS: frozenset[str] = frozenset(
    set(ASCENDC_BUFFER_TYPES)
    | set(ASCENDC_REGISTER_TYPES)
    | set(SYNC_MECHANISM)
    | {
        "DataCopy",
        "DataCopyPad",
        "InitBuffer",
        "AllocTensor",
        "FreeTensor",
        "EnQue",
        "DeQue",
        "Cast",
        "Get",
        "GetTensor",
        "SetAtomicAdd",
        "SetAtomicNone",
        "SetAtomicType",
        "Mmad",
        "LoadData",
        "Fixpipe",
        "Matmul",
        # TPipe / tensor (kernel_tpipe.h, kernel_tensor.h, kernel_common.h)
        "TPipe",
        "FetchEventID",
        "GetTPipePtr",
        "GetBlockIdx",
        "GetSubBlockIdx",
        "SetGlobalBuffer",
        "GetPhyAddr",
        "InitOutput",
        # AscendC::Reg public free functions (kernel_reg_compute_*_intf.h)
        "LoadAlign",
        "StoreAlign",
        "StoreUnAlign",
        "CreateMask",
        "UpdateMask",
        "Interleave",
        "Duplicate",
        "ReduceSum",
        "Muls",
        "Adds",
        "Mul",
        "Add",
        "Sub",
        "Div",
        "Exp",
        "Abs",
        "Ceil",
        "Select",
        "sqrt",
        "Log",
        "DataCopyScatter",
        "LocalMemBar",
    }
)

# Min/Max/Or/And/Xor also exist as project scalar/logic helpers. Prove only
# when the call looks like vector/Reg (3+ args or a typed tensor/register operand).
_VECTOR_AMBIGUOUS_ROOTS: frozenset[str] = frozenset(AMBIGUOUS_VF_ROOTS)

# Catalog spellings that are member contracts, never free-function roots.
_MEMBER_ONLY_ROOTS: frozenset[str] = frozenset(
    {"Get", "GetTensor", "GetPre", "GetReused", "LockProd", "UnlockProd", "LockCons", "UnlockCons"}
)

_CLASS_RE = re.compile(r"\b(?:class|struct)\s+(?P<name>[A-Za-z_]\w*)\b")
_USING_RE = re.compile(
    r"\busing\s+(?P<alias>[A-Za-z_]\w*)\s*=\s*(?P<target>[^;{]{1,400})\s*;"
)
_TYPEDEF_RE = re.compile(
    r"\btypedef\s+(?P<target>[\w:<>,\s*&]+?)\s+(?P<alias>[A-Za-z_]\w*)\s*;"
)
_MEMBER_RE = re.compile(
    r"(?P<type>(?:[\w:<>,\s*&]+?))\s+(?P<name>[A-Za-z_]\w*)\s*;"
)
_CONTINUATION_NAME_RE = re.compile(r"^\s*(?P<name>[A-Za-z_]\w*)\s*;\s*$")
_CXX_SKIP_BASE = frozenset(
    {
        "public",
        "private",
        "protected",
        "return",
        "if",
        "for",
        "while",
        "switch",
        "int",
        "float",
        "double",
        "bool",
        "char",
        "void",
        "auto",
        "size_t",
        "uint8_t",
        "uint16_t",
        "uint32_t",
        "uint64_t",
        "int8_t",
        "int16_t",
        "int32_t",
        "int64_t",
        "half",
        "bfloat16_t",
    }
)


def _budget_s() -> float:
    return kernel_root_trace_budget_s()


def _enabled() -> bool:
    raw = str(os.environ.get("UO_KERNEL_ROOT_TRACE") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _norm_file(path: str, root: str = "") -> str:
    return kscan.norm_file(path, root)


def _base_type_name(type_text: str) -> str:
    text = str(type_text or "").strip()
    text = re.sub(r"\b(?:const|volatile|static|mutable|typename|template)\b", " ", text)
    text = text.replace("&", " ").replace("*", " ")
    no_tpl = text.split("<", 1)[0].strip()
    token = no_tpl.split("::")[-1].strip()
    return token if token.isidentifier() else ""


def _persist_type_name(type_text: str) -> str:
    """Short type spelling for CodeMap attrs — never the class body."""
    return _base_type_name(type_text) or str(type_text or "").split("<", 1)[0].strip()[:120]


_SYNC_PRECEDES_CALLEES: frozenset[str] = frozenset(
    {
        "DataCopy",
        "DataCopyPad",
        "AllocTensor",
        "FreeTensor",
        "EnQue",
        "DeQue",
        "SetFlag",
        "WaitFlag",
        "CrossCoreSetFlag",
        "CrossCoreWaitFlag",
        "PipeBarrier",
        "DataSyncBarrier",
        "InitBuffer",
        "Cast",
    }
    | set(SYNC_MECHANISM)
)


def _type_identity_key(type_text: str, *, usr: str = "", qualified: str = "") -> str:
    """Stable TYPE key: USR > qualified > templated spelling > short base name."""
    if usr:
        return f"usr:{usr}"
    if qualified:
        return f"q:{qualified}"
    text = str(type_text or "").strip()
    if not text:
        return ""
    # Keep template args so Buffer<TPosition::VECIN> ≠ bare / project Buffer.
    if "<" in text:
        compact = re.sub(r"\s+", "", text)
        return f"tpl:{compact}"
    return _base_type_name(text)


def _is_ascendc_root_spelling(name: str) -> bool:
    """Catalog candidate check only — not REACHED proof."""
    short = vf_root_spelling(name)
    return (
        name in _ASCENDC_API_ROOTS
        or short in _ASCENDC_API_ROOTS
        or name in ASCENDC_BUFFER_TYPES
        or name in ASCENDC_REGISTER_TYPES
        or is_cann_vf_api(name)
        or is_cann_util_api(name)
    )


_FRAMEWORK_DECL_MARKERS = (
    "/ascendc",
    "ascendc/",
    "/cann",
    "cann-",
    "tikcfw",
    "bisheng",
    "metadef",
    "kernel_operator",
    "basic_api",
    "impl/dav_",
    "include/aclnn",
)


def _is_framework_decl_file(path: str) -> bool:
    f = str(path or "").replace("\\", "/").lower()
    if not f:
        return False
    # Operator project sources are never AscendC catalog origins.
    if "/op_kernel/" in f or "/op_host/" in f:
        return False
    return any(m in f for m in _FRAMEWORK_DECL_MARKERS)


def _qualified_looks_ascendc(qualified: str) -> bool:
    q = str(qualified or "")
    if not q:
        return False
    return q.startswith("AscendC::") or "::AscendC::" in f"::{q}" or q.startswith("Cann::")


def _short_from_qualified(qualified: str, fallback: str = "") -> str:
    text = str(qualified or fallback or "").strip()
    if not text:
        return ""
    no_tpl = text.split("<", 1)[0].strip()
    short = no_tpl.split("::")[-1].strip()
    # Clang call-expr / ctor spellings: ``RegTensor()``, ``FixpipeConfig(CO2Layout, bool)``.
    if "(" in short:
        short = short.split("(", 1)[0].strip()
    return short


def _looks_like_framework_type_name(name: str) -> bool:
    """CANN param/config structs and similar type-like identifiers."""
    if not name or not name[0].isupper():
        return False
    if not re.match(r"^[A-Za-z_]\w*$", name):
        return False
    return True


_SPELLING_ALIASES: dict[str, str] = {"abs": "Abs", **VF_ALIASES}

_BUILTIN_SPELLINGS: frozenset[str] = frozenset(
    {
        "vector_bool",
        "vector_align",
        "__bs_f16",
        "memcpy",
        "conditional",
        "conditional_t",
    }
)


def _is_project_decl_file(path: str) -> bool:
    f = str(path or "").replace("\\", "/").lower()
    return "/op_kernel/" in f or "/op_host/" in f


def _is_compiler_builtin(
    name: str,
    *,
    usr: str = "",
    decl_file: str = "",
    qualified: str = "",
) -> bool:
    n = str(name or "")
    if n.startswith("__builtin_") or n.startswith("__bs_"):
        return True
    if n in _BUILTIN_SPELLINGS:
        return True
    q = str(qualified or "")
    if q.startswith("std::") or "::std::" in f"::{q}":
        return True
    f = str(decl_file or "").replace("\\", "/").lower()
    if "bisheng_prelude" in f:
        return True
    u = str(usr or "")
    if "c:@F@__builtin" in u or u.startswith("c:@S@vector_") or u.startswith("c:@S@__bs_"):
        return True
    return False


def _is_type_like_root(callee: str) -> bool:
    """RegTensor / LocalTensor / *Params are types, not execution operations."""
    short = str(callee or "").split("::")[-1]
    if short in ASCENDC_REGISTER_TYPES or short in ASCENDC_BUFFER_TYPES:
        return True
    if short in {"TPipe"}:
        return True
    if short.endswith(("Params", "Config", "ExtParams", "PadParams")) or "Params" in short:
        return True
    return False


def _should_mint_operation(
    *,
    callee: str,
    is_root: bool,
    is_builtin: bool,
    is_project: bool,
) -> bool:
    """OPERATION nodes are source call sites of execution primitives, not every CallExpr."""
    if is_builtin:
        return False
    if _is_type_like_root(callee):
        return False
    if is_project and not is_root:
        return False
    # Or/Min/Max/And live in the VF catalog and as project scalars. Only mint
    # when this site was already proven as an AscendC root.
    if callee in _VECTOR_AMBIGUOUS_ROOTS or is_ambiguous_vf_name(callee):
        return bool(is_root)
    return bool(is_root or semreg.is_execution_primitive(callee))


def _receiver_looks_tensor(*texts: str) -> bool:
    blob = " ".join(str(t or "") for t in texts)
    return "LocalTensor" in blob or "GlobalTensor" in blob


def _usr_is_ascendc_tensor_method(usr: str) -> bool:
    u = str(usr or "")
    if "AscendC" not in u:
        return False
    return "LocalTensor" in u or "GlobalTensor" in u


def _prove_ascendc_api_root(
    *,
    callee: str,
    callee_qualified: str = "",
    callee_usr: str = "",
    callee_decl_file: str = "",
    receiver: str = "",
    receiver_type: str = "",
    receiver_canonical_type: str = "",
    has_identity: bool = False,
) -> tuple[bool, str]:
    """Return (proven, root_spelling). Spelling alone never proves member calls.

    Proof order:
      1. AscendC/CANN qualified name
      2. Framework declaration file (API catalog **or** param/config ctor)
      3. Free-function catalog match only when identity is unavailable (lexical)
         and there is no receiver (not a member call)
    """
    short = _short_from_qualified(callee_qualified, callee)
    short = _SPELLING_ALIASES.get(short, short)
    callee_canon = _SPELLING_ALIASES.get(callee, callee)
    in_catalog = bool(short and _is_ascendc_root_spelling(short)) or _is_ascendc_root_spelling(
        callee_canon
    )
    if in_catalog and not (short and _is_ascendc_root_spelling(short)):
        short = callee_canon
    if not short:
        short = callee_canon

    if _usr_is_ascendc_tensor_method(callee_usr) and callee in TENSOR_METHOD_BRIDGES:
        return True, callee
    if _receiver_looks_tensor(receiver_type, receiver_canonical_type) and callee in TENSOR_METHOD_BRIDGES:
        return True, callee
    # Get/GetTensor/LockProd are member contracts. A CANN header hit is not
    # proof of a free AscendC::Get — Policy/Selector/TBuf all share the name.
    if short in _MEMBER_ONLY_ROOTS:
        if _qualified_looks_ascendc(callee_qualified) and not (
            receiver or receiver_type or receiver_canonical_type
        ):
            return True, short
        return False, ""

    # Framework-declared free/ctor symbols (DataCopyExtParams, FixpipeParams*, …)
    # need not sit in the compute-API catalog — the CANN header is the proof.
    if (
        _is_framework_decl_file(callee_decl_file)
        and not (receiver or receiver_type or receiver_canonical_type)
        and _looks_like_framework_type_name(short)
    ):
        if short in _VECTOR_AMBIGUOUS_ROOTS:
            # Min/Max still need call-shape evidence at the call site.
            pass
        else:
            return True, short

    if not in_catalog:
        if _qualified_looks_ascendc(callee_qualified):
            short = _SPELLING_ALIASES.get(
                _short_from_qualified(callee_qualified, callee),
                _short_from_qualified(callee_qualified, callee),
            )
            if short and _is_ascendc_root_spelling(short):
                return True, short
            # AscendC::DataCopyScatter and similar live in CANN headers even when
            # they are not in the small catalog.
            if _is_framework_decl_file(callee_decl_file) and not (
                receiver or receiver_type or receiver_canonical_type
            ):
                return True, short or callee
        if (
            _is_framework_decl_file(callee_decl_file)
            and "AscendC" in str(callee_usr or callee_qualified or "")
            and not (receiver or receiver_type or receiver_canonical_type)
        ):
            return True, short or callee
        return False, ""

    if _qualified_looks_ascendc(callee_qualified):
        return True, short
    if _is_framework_decl_file(callee_decl_file):
        return True, short
    # USR often encodes AscendC::Reg::RegTensor even when qualified is bare.
    if "AscendC" in str(callee_usr or "") and _is_ascendc_root_spelling(short):
        return True, short

    # Identity present but not AscendC/framework → project symbol, never root.
    if has_identity or callee_usr or callee_qualified or callee_decl_file:
        return False, ""

    # Lexical / unresolved free call: catalog match without receiver only.
    if receiver or receiver_type or receiver_canonical_type:
        return False, ""
    # Member-only contracts and Min/Max/Or never prove from the spelling alone.
    if short in _MEMBER_ONLY_ROOTS or short in _VECTOR_AMBIGUOUS_ROOTS or is_ambiguous_vf_name(short):
        return False, ""
    return True, short


def _root_entity_id(spelling: str) -> str:
    return make_id("Root", "ascendc", spelling)


def _ensure_ascendc_root(codemap: CodeMap, spelling: str, *, root_kind: str) -> str:
    eid = _root_entity_id(spelling)
    codemap.upsert(
        EntityKind.TYPE,
        f"AscendC::{spelling}",
        eid=eid,
        attrs={
            "root_status": "REACHED",
            "root_kind": root_kind,
            "root": f"AscendC::{spelling}",
            "catalog": "ascendc",
            "spelling": spelling,
        },
        status="extracted",
        confidence=1.0,
    )
    return eid


def _category_root_kind(category: str, callee: str) -> str:
    if callee in SYNC_MECHANISM or category.startswith("sync_"):
        return "SYNC"
    if callee in ASCENDC_REGISTER_TYPES or category.startswith("reg_"):
        return "REGISTER"
    if category in _ROOT_KIND_BY_CATEGORY:
        return _ROOT_KIND_BY_CATEGORY[category]
    if callee in ASCENDC_BUFFER_TYPES or is_storage_wrapper_type(callee):
        return "STORAGE"
    low = str(callee or "")
    if low.endswith(("Params", "Config", "ExtParams", "PadParams")) or "Params" in low:
        return "FRAMEWORK_TYPE"
    return "COMPUTE_API"


def _decl_fields(decl: Any) -> tuple[str, str, str, str, int]:
    if isinstance(decl, dict):
        return (
            str(decl.get("type_text") or decl.get("type") or ""),
            str(decl.get("name") or ""),
            str(decl.get("function") or decl.get("scope") or ""),
            str(decl.get("file") or ""),
            int(decl.get("line") or 0),
        )
    return (
        str(getattr(decl, "type_text", "") or getattr(decl, "type", "") or ""),
        str(getattr(decl, "name", "") or ""),
        str(getattr(decl, "function", "") or getattr(decl, "scope", "") or ""),
        str(getattr(decl, "file", "") or ""),
        int(getattr(decl, "line", 0) or 0),
    )


def _sync_object_kind(type_text: str) -> EntityKind | None:
    """Classify only explicit AscendC sync/storage type spellings."""
    text = re.sub(r"\s+", "", str(type_text or ""))
    if re.search(r"(?:^|::)TPipe(?:<|$)", text):
        return EntityKind.PIPE
    if re.search(r"(?:^|::)TQue(?:Bind)?(?:<|$)", text):
        return EntityKind.QUEUE
    if re.search(r"(?:^|::)HardEvent(?:Aic|Aiv)?(?:<|$)", text):
        return EntityKind.EVENT
    return None


def infer_kernel_phase(name: str, *, file: str = "", scope: str = "") -> str:
    """Cheap pre/main/post label from TPipe / op names. Not happens-before."""
    blob = f"{name} {scope} {file}".lower().replace("\\", "/")
    if any(tok in blob for tok in ("pipein", "pipepre", "oppre")):
        return "pre"
    if any(tok in blob for tok in ("pipepost", "oppost")):
        return "post"
    if any(tok in blob for tok in ("pipebase", "pipemain")):
        return "main"
    return ""


def _mutex_policy_attrs(type_text: str) -> dict[str, str]:
    """Policy token on a wrapper/selector type — not a project class catalog.

    Matches ``*Policy<Suffix>`` (PolicyDB, Policy3buff, L1PolicySingleBuffer, …)
    and ``std::conditional`` flags. Does not require MutexBuffer in the spelling.
    """
    text = str(type_text or "")
    out: dict[str, str] = {}
    m = re.search(
        r"\b(?:[A-Za-z_]\w*?)?Policy([A-Za-z][A-Za-z0-9]*|\d+[Bb]uff)\b",
        text,
    )
    if m:
        raw = m.group(1)
        low = raw.lower()
        if low in {"3buff", "4buff"}:
            out["mutex_policy"] = low
        elif raw in {"DB", "PolicyDB"}:
            out["mutex_policy"] = "PolicyDB"
        elif "SingleBuffer" in raw:
            out["mutex_policy"] = "PolicySingleBuffer"
        else:
            out["mutex_policy"] = raw
    cm = re.search(r"std::conditional(?:_t)?\s*<\s*([^,>]+)", text)
    if cm:
        out["conditional_flag"] = cm.group(1).strip()
    return out


def _receiver_is_tque(
    *,
    bid_recv: str,
    receiver_type: str,
    receiver_canonical: str,
    codemap: CodeMap,
) -> bool:
    if bid_recv and bid_recv in codemap.entities:
        ent = codemap.entities[bid_recv]
        if ent.kind_name() == EntityKind.QUEUE.value:
            return True
        blob = " ".join(
            str(ent.attrs.get(k) or "")
            for k in ("type_name", "root", "wrapper")
        )
        if "TQue" in blob:
            return True
    for text in (receiver_type, receiver_canonical):
        if _sync_object_kind(text) == EntityKind.QUEUE:
            return True
        if "TQue" in str(text or ""):
            return True
    return False


def _receiver_is_tpipe(
    *,
    bid_recv: str,
    receiver_type: str,
    receiver_canonical: str,
    codemap: CodeMap,
) -> bool:
    if bid_recv and bid_recv in codemap.entities:
        ent = codemap.entities[bid_recv]
        if ent.kind_name() == EntityKind.PIPE.value:
            return True
        blob = " ".join(
            str(ent.attrs.get(k) or "")
            for k in ("type_name", "root", "wrapper")
        )
        if "TPipe" in blob:
            return True
    for text in (receiver_type, receiver_canonical):
        if _sync_object_kind(text) == EntityKind.PIPE:
            return True
        if "TPipe" in str(text or ""):
            return True
    return False


def _looks_like_reg_or_vector_call(args: list[str] | None, targs: list[str] | None) -> bool:
    """True for CANN vector/Reg APIs, not 2-arg project scalar helpers."""
    args = [str(a) for a in (args or [])]
    targs = [str(a) for a in (targs or [])]
    blob = " ".join(targs + args)
    if any(
        tok in blob
        for tok in (
            "MaskReg",
            "RegTensor",
            "UnalignReg",
            "LocalTensor",
            "GlobalTensor",
            "preg_",
            "vreg_",
        )
    ):
        return True
    if re.search(r"\b(?:preg|vreg)\b", blob):
        return True
    return len(args) >= 3


_DTYPE_TARG_RE = re.compile(
    r"^(?:CALC_TYPE|half|float|double|bool|bfloat16_t|(?:u?int(?:8|16|32|64)_t)|T(?:\d+)?)$"
)


def _looks_like_typed_buffer_get(targs: list[str] | None) -> bool:
    """TBuf/TQue ``Get<DType>()`` — not a project Policy ``Get()``."""
    if not targs or len(targs) != 1:
        return False
    tok = str(targs[0] or "").split("::")[-1].strip()
    return bool(_DTYPE_TARG_RE.match(tok))


def _owner_from_receiver_type(type_text: str) -> str:
    """Class name for a member call, or empty when the type is a selector/conditional.

    ``std::conditional<…, PolicyA, PolicyB>`` names several Get methods; picking
    one Policy is a guess. cannbot locates via the buffer/receiver instead.
    """
    text = str(type_text or "")
    if not text:
        return ""
    compact = re.sub(r"\s+", "", text)
    if "std::conditional" in compact or "conditional_t" in compact:
        return ""
    if "Selector" in text:
        return ""
    base = _base_type_name(text)
    if base.lower() in {"conditional", "conditional_t", "type", "nullptr_t"}:
        return ""
    return base


def _select_framework_bridge(
    *,
    callee: str,
    receiver: str,
    recv_is_wrapper: bool,
    recv_is_tque: bool,
    recv_is_tpipe: bool,
    receiver_type: str = "",
    receiver_canonical: str = "",
    callee_usr: str = "",
    targs: list[str] | None = None,
) -> tuple[str, str] | None:
    """Explicit CANN/framework method contracts. Spelling alone never proves members."""
    if recv_is_wrapper:
        hit = MUTEX_BUFFER_METHOD_BRIDGES.get(callee)
        if hit:
            return hit
    # TBuf / TQueBind ``.template Get<T>()`` returns LocalTensor.
    if callee == "Get" and _looks_like_typed_buffer_get(targs):
        return ("LocalTensor", "STORAGE")
    # TPipe::InitBuffer / FetchEventID. Receiver is the pipe; TQue is an argument.
    if callee in TPIPE_METHOD_BRIDGES and (recv_is_tpipe or (receiver and not recv_is_tque)):
        return TPIPE_METHOD_BRIDGES[callee]
    # EnQue/DeQue/Alloc/Free exist only on TQueBind in CANN.
    if callee in TQUE_METHOD_BRIDGES and (recv_is_tque or (receiver and not recv_is_tpipe)):
        return TQUE_METHOD_BRIDGES[callee]
    if callee in TENSOR_METHOD_BRIDGES and (
        receiver
        or _receiver_looks_tensor(receiver_type, receiver_canonical)
        or _usr_is_ascendc_tensor_method(callee_usr)
    ):
        return TENSOR_METHOD_BRIDGES[callee]
    return None


# ---------------------------------------------------------------------------
# Source scanners (complete graph — not storage-filtered)
# ---------------------------------------------------------------------------


def _scan_type_aliases(files: list[Path], *, root: str, deadline: float) -> list[dict[str, Any]]:
    from uo_init.source_index import get_or_build

    if time.perf_counter() > deadline:
        return []
    return get_or_build(files, root=root, deadline=deadline).aliases_for(files)


def _scan_class_members(files: list[Path], *, root: str, deadline: float) -> list[dict[str, Any]]:
    """All class/struct field members in source scope (complete composition graph)."""
    from uo_init.source_index import get_or_build

    if time.perf_counter() > deadline:
        return []
    return get_or_build(files, root=root, deadline=deadline).members_for(files)


def _existing_type_id(codemap: CodeMap, spell: str) -> str | None:
    name = str(spell or "").strip()
    if not name:
        return None
    preferred: str | None = None
    for hit in codemap.by_name(name, kind=EntityKind.TYPE):
        if str(hit.id).startswith("SRCTYPE::"):
            return hit.id
        if preferred is None:
            preferred = hit.id
    return preferred


def _collapse_duplicate_type_hashes(codemap: CodeMap) -> dict[str, str]:
    """Drop clang ``TYPE_<hash>`` nodes when a same-name ``SRCTYPE::`` exists.

    Rewrites incident edges onto the source type. Does not delete wrappers,
    buffers, or other live graph nodes. Returns old-id → canonical-id.
    """
    canonical: dict[str, str] = {}
    for ent in codemap.by_kind(EntityKind.TYPE):
        if str(ent.id).startswith("SRCTYPE::"):
            canonical.setdefault(str(ent.name), ent.id)
    if not canonical:
        return {}
    rewrite: dict[str, str] = {}
    for ent in list(codemap.by_kind(EntityKind.TYPE)):
        eid = str(ent.id)
        if not eid.startswith("TYPE_"):
            continue
        target = canonical.get(str(ent.name))
        if not target or target == eid:
            continue
        rewrite[eid] = target
    if not rewrite:
        return {}
    for eid in rewrite:
        codemap.entities.pop(eid, None)
    rebuilt: dict[str, Any] = {}
    for rel in list(codemap.relations.values()):
        src = rewrite.get(rel.src, rel.src)
        dst = rewrite.get(rel.dst, rel.dst)
        if src == dst or src not in codemap.entities or dst not in codemap.entities:
            continue
        rel.src = src
        rel.dst = dst
        rid = _rid(rel.kind_name(), src, dst)
        rel.id = rid
        rebuilt[rid] = rel
    codemap.relations.clear()
    codemap.relations.update(rebuilt)
    return rewrite


def _purge_root_trace_entities(codemap: CodeMap) -> None:
    """Drop previously minted root-trace nodes so finalize can rebuild them."""
    drop_kinds = {
        EntityKind.OPERATION.value,
        EntityKind.BUFFER.value,
        EntityKind.REGISTER.value,
        EntityKind.PIPE.value,
        EntityKind.EVENT.value,
        EntityKind.QUEUE.value,
    }
    drop_ids = {e.id for e in codemap.entities.values() if e.kind_name() in drop_kinds}
    for e in list(codemap.entities.values()):
        if e.kind_name() != EntityKind.TYPE.value:
            continue
        if e.attrs.get("catalog") == "ascendc":
            drop_ids.add(e.id)
        if e.attrs.get("role") in {
            "storage_wrapper_type",
            "project_wrapper_type",
            "type_alias",
            "source_type",
        }:
            drop_ids.add(e.id)
    for eid in drop_ids:
        codemap.entities.pop(eid, None)
    keep_rel = {
        RelationKind.WRAPS.value,
        RelationKind.ROOTED_AT.value,
        RelationKind.ALIASES.value,
        RelationKind.REFERENCES.value,
        RelationKind.CALLS.value,
        RelationKind.CONTAINS.value,
    }
    for rid, rel in list(codemap.relations.items()):
        if rel.src in drop_ids or rel.dst in drop_ids:
            if (
                rel.kind_name() == RelationKind.CALLS.value
                and rel.src not in drop_ids
                and rel.dst not in drop_ids
            ):
                continue
            if (
                rel.kind_name() == RelationKind.REFERENCES.value
                and rel.src not in drop_ids
                and rel.dst not in drop_ids
                and str(rel.attrs.get("provenance") or "") != "kernel_root_trace"
            ):
                continue
            if rel.kind_name() in keep_rel or rel.src in drop_ids or rel.dst in drop_ids:
                if str(rel.attrs.get("provenance") or "") == "kernel_root_trace" or (
                    rel.src in drop_ids or rel.dst in drop_ids
                ):
                    codemap.relations.pop(rid, None)


def _link(
    codemap: CodeMap,
    kind: RelationKind,
    src: str,
    dst: str,
    *,
    attrs: dict[str, Any] | None = None,
    status: str = "confirmed",
) -> None:
    """Topology-unique edge; accumulate call-site evidence under attrs['sites']."""
    payload = {**(attrs or {}), "provenance": "kernel_root_trace"}
    site = None
    if any(k in payload for k in ("file", "line", "column")):
        site = {
            "file": str(payload.get("file") or ""),
            "line": int(payload.get("line") or 0),
            "column": int(payload.get("column") or 0),
            "receiver": str(payload.get("receiver") or ""),
            "via": str(payload.get("via") or ""),
        }
    rel = codemap.link(kind, src, dst, attrs=payload, status=status)
    if site is None:
        return
    sites = list(rel.attrs.get("sites") or [])
    key = (site["file"], site["line"], site["column"], site["receiver"], site["via"])
    seen = {
        (
            str(s.get("file") or ""),
            int(s.get("line") or 0),
            int(s.get("column") or 0),
            str(s.get("receiver") or ""),
            str(s.get("via") or ""),
        )
        for s in sites
        if isinstance(s, dict)
    }
    if key not in seen:
        sites.append(site)
        rel.attrs["sites"] = sites
    # Keep first-seen file/line as the primary display site; do not overwrite.


def _record_flag_pair_appearance(codemap: CodeMap, gaps: list[dict[str, Any]]) -> dict[str, int]:
    """Identity-level Set/Wait appearance. TQue ops never enter this check."""
    groups: dict[tuple[str, str, str], dict[str, list[str]]] = defaultdict(
        lambda: {"signals": [], "awaits": []}
    )
    event_ids: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for rel in codemap.relations.values():
        kn = rel.kind_name()
        if kn not in {RelationKind.SIGNALS.value, RelationKind.AWAITS.value}:
            continue
        op = codemap.entities.get(rel.src)
        event = codemap.entities.get(rel.dst)
        if op is None or event is None:
            continue
        callee = str(op.attrs.get("callee") or op.name or "")
        if is_tque_callee(callee) or not is_flag_sync(callee):
            continue
        identity = str(event.attrs.get("identity") or event.name or "")
        sync = {
            "mechanism": str(event.attrs.get("mechanism") or op.attrs.get("mechanism") or ""),
            "event": str(event.attrs.get("event_type") or ""),
        }
        key = flag_pair_key(identity, sync)
        if not key[1]:
            continue
        side = "signals" if kn == RelationKind.SIGNALS.value else "awaits"
        groups[key][side].append(op.id)
        event_ids[key].add(event.id)

    paired_keys = 0
    unpaired_keys = 0
    for key, sides in groups.items():
        paired = bool(sides["signals"] and sides["awaits"])
        if paired:
            paired_keys += 1
        else:
            unpaired_keys += 1
            present_id = (sides["signals"] or sides["awaits"])[0]
            present_op = codemap.entities.get(present_id)
            present = str((present_op.attrs.get("callee") if present_op else "") or "")
            gaps.append(
                {
                    "code": REASON_UNPAIRED_FLAG_SYNC,
                    "mechanism": key[0],
                    "identity": key[1],
                    "event": key[2],
                    "present": present,
                    "missing": FLAG_PAIR_MATE.get(present, ""),
                    "entity_id": present_id,
                }
            )
        for oid in sides["signals"] + sides["awaits"]:
            ent = codemap.entities.get(oid)
            if ent is not None:
                ent.attrs["flag_paired"] = paired
        for eid in event_ids.get(key, ()):
            ev = codemap.entities.get(eid)
            if ev is not None:
                ev.attrs["paired"] = paired
                ev.attrs["signal_count"] = len(sides["signals"])
                ev.attrs["await_count"] = len(sides["awaits"])
    return {"flag_pairs": paired_keys, "unpaired_flag_sync": unpaired_keys}


def _propagate_reachability(codemap: CodeMap) -> None:
    """Single reverse fixed-point over WRAPS / ALIASES / CALLS from REACHED nodes."""
    reverse: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for rel in codemap.relations.values():
        if str(rel.attrs.get("provenance") or "") != "kernel_root_trace":
            # Also follow CALLS from kernel call binder if present.
            if rel.kind_name() != RelationKind.CALLS.value:
                continue
        kn = rel.kind_name()
        if kn not in {
            RelationKind.WRAPS.value,
            RelationKind.ALIASES.value,
            RelationKind.CALLS.value,
            RelationKind.ROOTED_AT.value,
        }:
            continue
        # Reverse: dst → src means "src reaches via dst"
        if kn == RelationKind.ROOTED_AT.value:
            continue
        reverse[rel.dst].append((rel.src, kn))

    queue: deque[str] = deque()
    seen: set[str] = set()
    for eid, e in codemap.entities.items():
        if e.attrs.get("root_status") == "REACHED":
            queue.append(eid)
            seen.add(eid)

    while queue:
        cur = queue.popleft()
        cur_e = codemap.entities.get(cur)
        if cur_e is None:
            continue
        cur_root = str(cur_e.attrs.get("root") or cur_e.name)
        cur_kind = str(cur_e.attrs.get("root_kind") or "")
        for parent, via in reverse.get(cur, []):
            pe = codemap.entities.get(parent)
            if pe is None:
                continue
            if pe.attrs.get("root_status") == "REACHED" and pe.attrs.get("root"):
                # Already rooted; still allow ROOTED_AT edge refresh below.
                pass
            else:
                pe.attrs["root_status"] = "REACHED"
                pe.attrs["root"] = cur_root if cur_root.startswith("AscendC::") else (
                    cur_root if "::" in cur_root else f"AscendC::{cur_root.replace('AscendC::', '')}"
                )
                if not str(pe.attrs.get("root") or "").startswith("AscendC::") and cur_e.attrs.get("catalog") == "ascendc":
                    pe.attrs["root"] = cur_e.name
                pe.attrs["root_kind"] = cur_kind or pe.attrs.get("root_kind") or "STORAGE"
                trace = list(pe.attrs.get("trace") or [pe.name])
                if cur_e.name not in trace:
                    trace.append(cur_e.name)
                pe.attrs["trace"] = trace
                pe.status = "extracted"
                pe.confidence = max(float(pe.confidence or 0), 0.9)

            # Point ROOTED_AT at AscendC catalog when available.
            target = cur
            root_spell = str(pe.attrs.get("root") or "").replace("AscendC::", "")
            if root_spell and _is_ascendc_root_spelling(root_spell):
                target = _ensure_ascendc_root(
                    codemap, root_spell, root_kind=str(pe.attrs.get("root_kind") or "STORAGE")
                )
            elif cur_e.attrs.get("catalog") == "ascendc":
                target = cur
            _link(
                codemap,
                RelationKind.ROOTED_AT,
                parent,
                target,
                attrs={"via": f"{via}_closure"},
            )
            if parent not in seen:
                seen.add(parent)
                queue.append(parent)


def _normalize_settled_entities(codemap: CodeMap) -> None:
    """Four-state root_status: REACHED / PROJECT / BUILTIN / UNRESOLVED.

    Project types, compiler intrinsics and settled buffers are extracted — they
    are not locate-surface holes. Storage wrappers that never canonicalized
    stay UNRESOLVED.
    """
    settled = {"REACHED", "PROJECT", "BUILTIN"}
    for e in codemap.entities.values():
        rs = str(e.attrs.get("root_status") or "")
        kind = e.kind_name()
        name = e.name
        usr = str(e.attrs.get("usr") or e.attrs.get("callee_usr") or "")
        decl = str(e.attrs.get("callee_decl_file") or e.file or "")
        qualified = str(e.attrs.get("qualified_name") or e.attrs.get("callee_qualified") or "")
        if rs in settled:
            e.status = "extracted"
            continue
        if kind == EntityKind.TYPE.value:
            if e.attrs.get("catalog") == "ascendc":
                e.status = "extracted"
                continue
            if str(e.attrs.get("role") or "") == "storage_wrapper_type":
                continue
            if _is_compiler_builtin(name, usr=usr, decl_file=decl, qualified=qualified):
                e.attrs["root_status"] = "BUILTIN"
                e.attrs["root_kind"] = "STD"
            else:
                e.attrs["root_status"] = "PROJECT"
                e.attrs["root_kind"] = e.attrs.get("root_kind") or "PROJECT"
            e.status = "extracted"
            continue
        if kind == EntityKind.METHOD.value:
            if _is_compiler_builtin(name, usr=usr, decl_file=decl, qualified=qualified):
                e.attrs["root_status"] = "BUILTIN"
                e.attrs["root_kind"] = "BUILTIN"
            elif _usr_is_ascendc_tensor_method(usr):
                e.attrs["root_status"] = "REACHED"
                e.attrs["root"] = e.attrs.get("root") or "AscendC::LocalTensor"
                e.attrs["root_kind"] = e.attrs.get("root_kind") or "MEMORY_API"
            else:
                e.attrs["root_status"] = "PROJECT"
                e.attrs["root_kind"] = "PROJECT"
            e.status = "extracted"
            continue
        if kind == EntityKind.OPERATION.value:
            callee = str(e.attrs.get("callee") or name)
            if _is_compiler_builtin(
                callee,
                usr=usr,
                decl_file=decl,
                qualified=qualified,
            ):
                e.attrs["root_status"] = "BUILTIN"
                e.attrs["root_kind"] = "BUILTIN"
                e.attrs["root_proof"] = e.attrs.get("root_proof") or "compiler_builtin"
                e.status = "extracted"
            elif str(e.attrs.get("root_proof") or "").startswith("project_"):
                e.attrs["root_status"] = "PROJECT"
                e.attrs["root_kind"] = "PROJECT"
                e.status = "extracted"
            continue
        if kind == EntityKind.BUFFER.value and rs == "REACHED":
            e.status = "extracted"


def _add_clang_path(dst: set[str], raw: str) -> None:
    p = str(raw or "").replace("\\", "/")
    if not p:
        return
    dst.add(Path(p).name.lower())
    dst.add(p.lower())


def _cited_files_from_walk(wr: Any, dst: set[str]) -> None:
    """Union files named by a WalkResult so lexical skip covers included headers."""
    _add_clang_path(dst, str(getattr(wr, "path", "") or ""))
    for site in getattr(wr, "call_sites", None) or []:
        _add_clang_path(dst, getattr(site, "file", "") or "")
        _add_clang_path(dst, getattr(site, "callee_decl_file", "") or "")
    for decl in getattr(wr, "local_decls", None) or []:
        _add_clang_path(dst, getattr(decl, "file", "") or "")
    for decl in getattr(wr, "type_decls", None) or []:
        _add_clang_path(dst, getattr(decl, "file", "") or "")
    for decl in getattr(wr, "alias_decls", None) or []:
        _add_clang_path(dst, getattr(decl, "file", "") or "")
    fds = getattr(wr, "field_decls", None) or {}
    if isinstance(fds, dict):
        fds = fds.values()
    for fd in fds:
        _add_clang_path(dst, getattr(fd, "file", "") or "")
    for ctrl in getattr(wr, "controls", None) or []:
        _add_clang_path(dst, getattr(ctrl, "file", "") or "")
    fns = getattr(wr, "functions", None) or {}
    if isinstance(fns, dict):
        fns = fns.values()
    for rec in fns:
        _add_clang_path(dst, getattr(rec, "file", "") or "")


def finalize_kernel_root_trace(
    codemap: CodeMap,
    source_root: Path | str,
    *,
    architecture: str = "",
) -> CodeMap:
    if not _enabled():
        codemap.meta["kernel_root_trace"] = {"skipped": True, "reason": "UO_KERNEL_ROOT_TRACE=0"}
        return codemap

    t0 = time.perf_counter()
    budget = TimeBudget(_budget_s())
    deadline = budget.deadline
    root = str(Path(source_root).expanduser().resolve())
    arch = require_architecture(architecture or codemap.architecture)
    reachable, filter_strict = kscan.reachable_function_names(codemap)
    files = kscan.selected_kernel_files(codemap, Path(root))
    identity_filled = 0

    _purge_root_trace_entities(codemap)

    try:
        from uo_init import tu_cache as _tu_cache

        _tu_cache.load_walk_bundle(Path(root), arch, path_substr="op_kernel")
    except Exception:  # noqa: BLE001
        pass
    if files:
        from uo_init.source_index import get_or_build

        get_or_build(files, root=root, deadline=deadline)

    # --- 1. Source facts -------------------------------------------------
    calls, decls, _controls, provenance = kscan.collect_call_sites_from_walks(
        Path(root),
        architecture=arch,
        reachable=reachable,
        filter_strict=filter_strict,
        deadline=deadline,
    )
    walk_stats = {}
    try:
        from uo_init import tu_cache as _tu_cache

        walk_stats = dict(_tu_cache.stats() or {})
    except Exception:  # noqa: BLE001
        walk_stats = {}

    # Files already covered by a successful clang walk: skip full lexical merge
    # there (primitives-only lexical fill-in only). Uncovered files still get
    # the broader lexical fallback so we do not go silent.
    clang_files: set[str] = set()
    try:
        from uo_init import tu_cache as _tu_cache

        for wr in _tu_cache.iter_cached_walks(
            Path(root), arch, path_substr="op_kernel", limit=96
        ):
            _cited_files_from_walk(wr, clang_files)
    except Exception:  # noqa: BLE001
        clang_files = set()

    uncovered = [
        f
        for f in files
        if f.name.lower() not in clang_files
        and str(f).replace("\\", "/").lower() not in clang_files
        and not any(str(f).replace("\\", "/").lower().endswith(cf) for cf in clang_files if "/" in cf)
    ]
    covered = [f for f in files if f not in uncovered]

    # Lexical fallback: uncovered files get full scan; covered files only
    # registry primitives (to catch APIs clang may have missed as dependent names).
    if files and time.perf_counter() < deadline:
        lexical: list = []
        if uncovered:
            lexical.extend(
                kscan.lexical_source_call_sites(
                    uncovered,
                    reachable=reachable,
                    filter_strict=filter_strict,
                    root=root,
                    deadline=deadline,
                    primitives_only=False,
                )
            )
        if covered and provenance.startswith("clang_walk"):
            lexical.extend(
                kscan.lexical_source_call_sites(
                    covered,
                    reachable=reachable,
                    filter_strict=filter_strict,
                    root=root,
                    deadline=deadline,
                    primitives_only=True,
                )
            )
        elif not provenance.startswith("clang_walk"):
            # No walk cache at all — full lexical across all selected files.
            lexical = kscan.lexical_source_call_sites(
                files,
                reachable=reachable,
                filter_strict=filter_strict,
                root=root,
                deadline=deadline,
                primitives_only=False,
            )
        calls, added = kscan.merge_lexical_sites(calls, lexical, root=root)
        if added:
            provenance = f"{provenance}+lexical_source_calls"
        identity_filled = 0
        if files and time.perf_counter() < deadline:
            from uo_init.passes.kernel_call_identity import (
                build_source_symbol_index,
                enrich_call_sites,
            )

            calls = [kscan.site_as_dict(s) for s in (calls or [])]
            sym_index = build_source_symbol_index(files, root=root, deadline=deadline)
            identity_filled = enrich_call_sites(calls, sym_index, root=root)
        lex_decls = kscan.lexical_buffer_decls(
            files,
            reachable=reachable,
            filter_strict=False,
            deadline=deadline,
        )
        decls = list(decls or []) + list(lex_decls or [])

    # Gated source n is this_op + sibling_op. Fill those primitives on the
    # same TimeBudget; family_common cube templates stay clang-only.
    extra_arch = kscan.kernel_corpus(
        Path(root),
        arch,
        deadline=deadline,
    )
    extra_added = 0
    gated_fill_complete = True
    priority: list[Path] = []
    for path in extra_arch:
        owner = kscan.kernel_file_owner(path, Path(root))
        if owner in {"this_op", "sibling_op"}:
            priority.append(path)
    if priority:
        extra_sites = kscan.lexical_source_call_sites(
            priority,
            reachable=reachable,
            filter_strict=False,
            root=root,
            deadline=deadline,
            primitives_only=True,
        )
        calls, extra_added = kscan.merge_lexical_sites(calls, extra_sites, root=root)
        if extra_added:
            provenance = f"{provenance}+arch_kernel_primitives"
        if budget.expired():
            gated_fill_complete = False
    try:
        from uo_init.diagnostics.source_api import count_source_kernel_apis

        source_api_gated = count_source_kernel_apis(
            Path(root), arch, files=priority or extra_arch
        )
    except Exception:  # noqa: BLE001
        source_api_gated = {}

    kernel_backend = (
        "clang"
        if provenance.startswith("clang_walk")
        else ("lexical" if "lexical" in provenance else "none")
    )

    aliases_lex = _scan_type_aliases(files, root=root, deadline=deadline) if files else []
    members_lex = _scan_class_members(files, root=root, deadline=deadline) if files else []
    clang_graph = kscan.collect_type_graph_from_walks(
        Path(root), architecture=arch, deadline=deadline
    )
    # Clang-first; lexical regex only fills parse gaps.
    aliases = list(clang_graph.get("aliases") or [])
    members = list(clang_graph.get("members") or [])
    clang_types = list(clang_graph.get("types") or [])
    clang_bases = list(clang_graph.get("bases") or [])
    seen_alias = {
        (str(r.get("alias") or ""), str(r.get("file") or ""), int(r.get("line") or 0))
        for r in aliases
    }
    for row in aliases_lex:
        key = (str(row.get("alias") or ""), str(row.get("file") or ""), int(row.get("line") or 0))
        if key in seen_alias:
            continue
        row = dict(row)
        row.setdefault("provenance", "lexical_regex")
        aliases.append(row)
        seen_alias.add(key)
    seen_member = {
        (
            str(r.get("owner") or ""),
            str(r.get("member") or ""),
            str(r.get("file") or ""),
            int(r.get("line") or 0),
        )
        for r in members
    }
    for row in members_lex:
        key = (
            str(row.get("owner") or ""),
            str(row.get("member") or ""),
            str(row.get("file") or ""),
            int(row.get("line") or 0),
        )
        if key in seen_member:
            continue
        row = dict(row)
        row.setdefault("provenance", "lexical_regex")
        members.append(row)
        seen_member.add(key)

    alias_to_target: dict[str, str] = {
        str(row["alias"]): str(row["target"]) for row in aliases if row.get("alias")
    }

    def _resolve_alias_chain(type_text: str) -> str:
        base = _base_type_name(type_text)
        seen: set[str] = set()
        while base and base in alias_to_target and base not in seen:
            seen.add(base)
            type_text = alias_to_target[base]
            base = _base_type_name(type_text)
        return type_text

    type_ents: dict[str, str] = {}

    # --- 2. Complete type / alias / member graph -------------------------
    for row in aliases:
        alias = str(row["alias"])
        target = str(row["target"])
        tid = make_id("Type", "alias", alias, row["file"], int(row["line"]))
        resolved = _resolve_alias_chain(target)
        root_spell = _base_type_name(resolved)
        reached = _is_ascendc_root_spelling(root_spell)
        ent = codemap.upsert(
            EntityKind.TYPE,
            alias,
            eid=tid,
            attrs={
                "role": "type_alias",
                "alias_of": target,
                "resolved_type": resolved,
                "root_status": "REACHED" if reached else "UNRESOLVED",
                "root_kind": (
                    "REGISTER"
                    if reached and root_spell in ASCENDC_REGISTER_TYPES
                    else ("STORAGE" if reached and root_spell in ASCENDC_BUFFER_TYPES else (
                        "SYNC" if reached and root_spell in SYNC_MECHANISM else (
                            "COMPUTE_API" if reached else ""
                        )
                    ))
                ),
                "root": f"AscendC::{root_spell}" if reached else "",
                "trace": [alias, _base_type_name(target)] + ([root_spell] if reached else []),
            },
            file=str(row["file"]),
            line=int(row["line"]),
            status="extracted" if reached else "partial",
            confidence=1.0 if reached else 0.5,
        )
        type_ents[alias] = ent.id
        # Always ALIASES to target type node (complete graph).
        tbase = _base_type_name(target)
        if tbase and tbase not in type_ents:
            if _is_ascendc_root_spelling(tbase):
                type_ents[tbase] = _ensure_ascendc_root(
                    codemap,
                    tbase,
                    root_kind="STORAGE" if tbase in ASCENDC_BUFFER_TYPES else (
                        "REGISTER" if tbase in ASCENDC_REGISTER_TYPES else "COMPUTE_API"
                    ),
                )
            else:
                mid = make_id("Type", "alias_target", tbase, row["file"], int(row["line"]))
                ment = codemap.upsert(
                    EntityKind.TYPE,
                    tbase,
                    eid=mid,
                    attrs={"role": "source_type", "root_status": "UNRESOLVED"},
                    file=str(row["file"]),
                    line=int(row["line"]),
                    status="partial",
                    confidence=0.5,
                )
                type_ents[tbase] = ment.id
        if tbase and tbase in type_ents:
            _link(codemap, RelationKind.ALIASES, ent.id, type_ents[tbase], attrs={"via": "using"})
        if reached:
            rid = _ensure_ascendc_root(
                codemap,
                root_spell,
                root_kind=str(ent.attrs.get("root_kind") or "STORAGE"),
            )
            _link(codemap, RelationKind.ROOTED_AT, ent.id, rid)

    # Every class that appears as an owner or member type gets a TYPE node.
    for row in members:
        owner = str(row["owner"])
        if owner not in type_ents:
            existing = _existing_type_id(codemap, owner)
            if existing:
                type_ents[owner] = existing
                continue
            oid = make_id("Type", "class", owner, row["file"], int(row["line"]))
            ent = codemap.upsert(
                EntityKind.TYPE,
                owner,
                eid=oid,
                attrs={
                    "role": "source_type",
                    "root_status": "UNRESOLVED",
                    "root_kind": "",
                    "root": "",
                    "trace": [owner],
                },
                file=str(row["file"]),
                line=int(row["line"]),
                status="partial",
                confidence=0.5,
            )
            type_ents[owner] = ent.id

    # Seed clang TypeDecl nodes (USR / qualified identity).
    for row in clang_types:
        name = str(row.get("name") or "")
        if not name:
            continue
        ikey = _type_identity_key(
            name,
            usr=str(row.get("usr") or ""),
            qualified=str(row.get("qualified_name") or ""),
        ) or name
        if ikey in type_ents:
            continue
        existing = _existing_type_id(codemap, name)
        if existing:
            type_ents[ikey] = existing
            type_ents.setdefault(name, existing)
            continue
        display = str(row.get("qualified_name") or name)
        mid = make_id(
            "Type",
            "clang",
            str(row.get("usr") or display),
            row.get("file") or "",
            int(row.get("line") or 0),
        )
        ment = codemap.upsert(
            EntityKind.TYPE,
            name,
            eid=mid,
            attrs={
                "role": "source_type",
                "root_status": "UNRESOLVED",
                "qualified_name": str(row.get("qualified_name") or ""),
                "usr": str(row.get("usr") or ""),
                "trace": [name],
            },
            file=str(row.get("file") or ""),
            line=int(row.get("line") or 0),
            status="partial",
            confidence=0.6,
        )
        type_ents[ikey] = ment.id
        if name and name not in type_ents:
            type_ents[name] = ment.id

    wraps_edges: list[tuple[str, str, dict[str, Any]]] = []
    for row in members:
        owner = str(row["owner"])
        if owner not in type_ents:
            continue
        type_text = str(row["type_text"])
        resolved = _resolve_alias_chain(type_text)
        resolved_base = _base_type_name(resolved) or str(row.get("base_type") or "")
        if not resolved_base or resolved_base in _CXX_SKIP_BASE:
            continue
        member_ikey = _type_identity_key(
            resolved,
            usr=str(row.get("referenced_type_usr") or ""),
            qualified="",
        ) or resolved_base
        # Reuse an already-materialised owner/class node for the same short name.
        if member_ikey not in type_ents and resolved_base in type_ents and "<" not in resolved:
            type_ents[member_ikey] = type_ents[resolved_base]
        display = resolved.strip() if "<" in resolved else resolved_base
        if member_ikey not in type_ents:
            existing = _existing_type_id(codemap, resolved_base) or _existing_type_id(
                codemap, display
            )
            if existing:
                type_ents[member_ikey] = existing
                type_ents.setdefault(resolved_base, existing)
            elif is_storage_wrapper_type(resolved) or resolved_base in ASCENDC_STORAGE_WRAPPER_TYPES:
                mid = make_id("Type", "wrapper", member_ikey, row["file"], int(row["line"]))
                ment = codemap.upsert(
                    EntityKind.TYPE,
                    display,
                    eid=mid,
                    attrs={
                        "role": "storage_wrapper_type",
                        "root_status": "UNRESOLVED",
                        "type_name": _persist_type_name(resolved),
                        "spelling_base": resolved_base,
                    },
                    file=str(row["file"]),
                    line=int(row["line"]),
                    status="partial",
                    confidence=0.5,
                )
                type_ents[member_ikey] = ment.id
                type_ents.setdefault(resolved_base, ment.id)
            elif _is_ascendc_root_spelling(resolved_base):
                type_ents[member_ikey] = _ensure_ascendc_root(
                    codemap,
                    resolved_base,
                    root_kind=(
                        "STORAGE"
                        if resolved_base in ASCENDC_BUFFER_TYPES
                        else (
                            "REGISTER"
                            if resolved_base in ASCENDC_REGISTER_TYPES
                            else "COMPUTE_API"
                        )
                    ),
                )
                type_ents.setdefault(resolved_base, type_ents[member_ikey])
            else:
                mid = make_id("Type", "member_type", member_ikey, row["file"], int(row["line"]))
                ment = codemap.upsert(
                    EntityKind.TYPE,
                    display,
                    eid=mid,
                    attrs={
                        "role": "source_type",
                        "root_status": "UNRESOLVED",
                        "type_name": _persist_type_name(resolved),
                        "spelling_base": resolved_base,
                    },
                    file=str(row["file"]),
                    line=int(row["line"]),
                    status="partial",
                    confidence=0.5,
                )
                type_ents[member_ikey] = ment.id
                type_ents.setdefault(resolved_base, ment.id)
        wraps_edges.append(
            (
                type_ents[owner],
                type_ents[member_ikey],
                {
                    "member": row["member"],
                    "type_name": _persist_type_name(type_text),
                    "file": row["file"],
                    "line": row["line"],
                },
            )
        )

    for src, dst, attrs in wraps_edges:
        _link(codemap, RelationKind.WRAPS, src, dst, attrs=attrs)

    # Inheritance edges from Clang BaseDecl.
    for row in clang_bases:
        derived = str(row.get("derived") or "")
        base = str(row.get("base") or "")
        if not derived or not base:
            continue
        dkey = _type_identity_key(
            derived, usr=str(row.get("derived_usr") or "")
        ) or derived
        bkey = _type_identity_key(base, usr=str(row.get("base_usr") or "")) or base
        if dkey not in type_ents and derived in type_ents:
            type_ents[dkey] = type_ents[derived]
        if bkey not in type_ents:
            if _is_ascendc_root_spelling(base):
                type_ents[bkey] = _ensure_ascendc_root(
                    codemap,
                    base,
                    root_kind="STORAGE" if base in ASCENDC_BUFFER_TYPES else "COMPUTE_API",
                )
            else:
                mid = make_id("Type", "base", bkey, row.get("file") or "", int(row.get("line") or 0))
                ment = codemap.upsert(
                    EntityKind.TYPE,
                    base,
                    eid=mid,
                    attrs={"role": "source_type", "root_status": "UNRESOLVED", "usr": str(row.get("base_usr") or "")},
                    file=str(row.get("file") or ""),
                    line=int(row.get("line") or 0),
                    status="partial",
                    confidence=0.5,
                )
                type_ents[bkey] = ment.id
                type_ents.setdefault(base, ment.id)
        if type_ents.get(dkey) and type_ents.get(bkey):
            _link(
                codemap,
                RelationKind.WRAPS,
                type_ents[dkey],
                type_ents[bkey],
                attrs={
                    "via": "inherits",
                    "file": row.get("file") or "",
                    "line": int(row.get("line") or 0),
                },
            )

    # --- 3. Seed AscendC / CANN roots (+ framework wrapper contracts) ----
    for spell in sorted(ASCENDC_BUFFER_TYPES):
        type_ents.setdefault(spell, _ensure_ascendc_root(codemap, spell, root_kind="STORAGE"))
    for spell in sorted(ASCENDC_REGISTER_TYPES):
        type_ents.setdefault(spell, _ensure_ascendc_root(codemap, spell, root_kind="REGISTER"))
    for spell in sorted(SYNC_MECHANISM):
        type_ents.setdefault(spell, _ensure_ascendc_root(codemap, spell, root_kind="SYNC"))
    for spell in sorted(_ASCENDC_API_ROOTS - ASCENDC_BUFFER_TYPES - set(ASCENDC_REGISTER_TYPES) - set(SYNC_MECHANISM)):
        type_ents.setdefault(
            spell,
            _ensure_ascendc_root(codemap, spell, root_kind=_category_root_kind("", spell)),
        )

    def _seed_wrapper_contract(eid: str, spell: str) -> None:
        rid = _ensure_ascendc_root(codemap, "LocalTensor", root_kind="STORAGE")
        _link(
            codemap,
            RelationKind.WRAPS,
            eid,
            rid,
            attrs={"via": "framework_storage_contract"},
        )
        me = codemap.entities[eid]
        me.attrs["root_status"] = "REACHED"
        me.attrs["root"] = "AscendC::LocalTensor"
        me.attrs["root_kind"] = "STORAGE"
        me.attrs["role"] = "storage_wrapper_type"
        me.attrs["trace"] = list(me.attrs.get("trace") or [spell]) + ["AscendC::LocalTensor"]
        me.status = "extracted"
        _link(codemap, RelationKind.ROOTED_AT, eid, rid)

    # Framework wrapper contract: concrete MutexBuffer / Buffer<...> nodes.
    # Bare ambiguous "Buffer" spelling is never seeded; templated Buffer is.
    for spell in sorted(ASCENDC_STORAGE_WRAPPER_TYPES):
        if spell == "Buffer":
            continue
        if spell not in type_ents:
            existing = None
            for hit in codemap.by_name(spell, kind=EntityKind.TYPE):
                if str(hit.id).startswith("SRCTYPE::"):
                    existing = hit
                    break
                if existing is None:
                    existing = hit
            if existing is not None:
                type_ents[spell] = existing.id
            else:
                mid = make_id("Type", "wrapper", spell, "catalog", 0)
                ment = codemap.upsert(
                    EntityKind.TYPE,
                    spell,
                    eid=mid,
                    attrs={
                        "role": "storage_wrapper_type",
                        "root_status": "UNRESOLVED",
                        "trace": [spell],
                        "type_name": spell,
                    },
                    status="partial",
                    confidence=0.5,
                )
                type_ents[spell] = ment.id
        _seed_wrapper_contract(type_ents[spell], spell)

    for e in list(codemap.by_kind(EntityKind.TYPE)):
        if e.attrs.get("catalog") == "ascendc":
            continue
        tt = str(e.attrs.get("type_name") or e.attrs.get("type_text") or "")
        base = str(e.attrs.get("spelling_base") or _base_type_name(tt) or e.name)
        if not (is_storage_wrapper_type(tt) or is_storage_wrapper_type(e.name) or base == "MutexBuffer"):
            # Buffer only when templated (Buffer<...>), never bare Buffer.
            if not (base == "Buffer" and ("<" in tt or "<" in e.name)):
                continue
        if e.attrs.get("root_status") == "REACHED" and "LocalTensor" in str(e.attrs.get("root") or ""):
            continue
        _seed_wrapper_contract(e.id, base or e.name)

    rewrite = _collapse_duplicate_type_hashes(codemap)
    if rewrite:
        for key, eid in list(type_ents.items()):
            type_ents[key] = rewrite.get(eid, eid)

    # --- 4. BUFFER / REGISTER decl sites ---------------------------------
    buffer_by_key: dict[tuple[str, str], str] = {}
    buffer_by_name: dict[str, str] = {}
    gaps: list[dict[str, Any]] = []
    buf_count = 0
    reg_count = 0
    pipe_count = 0
    event_count = 0
    queue_count = 0

    # Member fields as BUFFER anchors when typed as storage/wrapper/alias-to-them.
    for row in members:
        type_text = str(row.get("type_text") or "")
        expanded = _resolve_alias_chain(type_text)
        name = str(row["member"])
        if not is_valid_storage_name(name):
            continue
        base = _base_type_name(expanded) or str(row.get("base_type") or "")
        sync_kind = _sync_object_kind(expanded) or _sync_object_kind(type_text)
        if sync_kind is not None:
            nfile = str(row["file"])
            line = int(row["line"])
            owner = str(row["owner"])
            sid = make_id(sync_kind.value.title(), "decl", owner, name, nfile, line)
            root_spell = (
                "TPipe"
                if sync_kind == EntityKind.PIPE
                else ("TQue" if sync_kind == EntityKind.QUEUE else "HardEvent")
            )
            root_id = _ensure_ascendc_root(codemap, root_spell, root_kind="SYNC")
            pipe_attrs = {
                    "scope": owner,
                    "type_name": _persist_type_name(type_text),
                    "tposition": tposition_from_type_text(expanded)
                    or tposition_from_type_text(type_text)
                    or "",
                    "memory_space": memory_space_from_type_text(expanded)
                    or memory_space_from_type_text(type_text)
                    or "",
                    "root_status": "REACHED",
                    "root_kind": "SYNC",
                    "root": f"AscendC::{root_spell}",
                    "provenance": str(row.get("provenance") or "kernel_root_trace"),
            }
            phase = infer_kernel_phase(name, file=nfile, scope=owner)
            if phase:
                pipe_attrs["kernel_phase"] = phase
            ent = codemap.upsert(
                sync_kind,
                name,
                eid=sid,
                attrs=pipe_attrs,
                file=nfile,
                line=line,
                status="extracted",
                confidence=1.0,
            )
            _link(codemap, RelationKind.ROOTED_AT, ent.id, root_id)
            buffer_by_key[(owner, name)] = ent.id
            buffer_by_name[name] = ent.id
            pipe_count += int(sync_kind == EntityKind.PIPE)
            event_count += int(sync_kind == EntityKind.EVENT)
            queue_count += int(sync_kind == EntityKind.QUEUE)
            continue
        mutex_attrs = _mutex_policy_attrs(type_text + " " + expanded)
        known = (
            is_storage_type_text(expanded)
            or is_storage_wrapper_type(expanded)
            or base in alias_to_target
            or (
                base in type_ents
                and str(codemap.entities[type_ents[base]].attrs.get("root_status") or "") == "REACHED"
            )
            or is_storage_wrapper_type(type_text)
            or bool(mutex_attrs.get("mutex_policy"))
        )
        if not known:
            continue
        nfile = str(row["file"])
        line = int(row["line"])
        owner = str(row["owner"])
        bid = buffer_site_id(file=nfile, line=line, scope=owner, name=name, root=root)
        is_wrapper = is_storage_wrapper_type(expanded) or is_storage_wrapper_type(type_text)
        resolved = resolve_buffer_decl(expanded) or resolve_buffer_decl(type_text)
        space = memory_space_from_type_text(expanded) or memory_space_from_type_text(type_text) or "UNKNOWN"
        root_spell = ""
        if is_wrapper:
            root_spell = str((resolved or {}).get("storage_root_kind") or "LocalTensor")
        elif base in ASCENDC_BUFFER_TYPES:
            root_spell = base
        elif base in type_ents and codemap.entities[type_ents[base]].attrs.get("root_status") == "REACHED":
            root_spell = str(codemap.entities[type_ents[base]].attrs.get("root") or "").replace("AscendC::", "")
        attrs = {
            "memory_space": space,
            "tposition": tposition_from_type_text(expanded)
            or tposition_from_type_text(type_text)
            or "",
            "scope": owner,
            "type_name": _persist_type_name(type_text),
            "role": (
                "storage_wrapper"
                if is_wrapper
                else ("mutex_policy" if mutex_attrs.get("mutex_policy") else "project_wrapper")
            ),
            "wrapper": "MutexBuffer" if is_wrapper and "MutexBuffer" in (expanded + type_text) else (
                _base_type_name(expanded) if is_wrapper else ""
            ),
            "root_status": "REACHED" if root_spell else "UNRESOLVED",
            "root_kind": "STORAGE" if root_spell else "",
            "root": f"AscendC::{root_spell}" if root_spell else "",
            "trace": [name] + ([base] if base else []) + ([root_spell] if root_spell else []),
        }
        attrs.update(mutex_attrs)
        ent = codemap.upsert(
            EntityKind.BUFFER,
            name,
            eid=bid,
            attrs=attrs,
            file=nfile,
            line=line,
            status="extracted" if root_spell else "partial",
            confidence=0.9 if root_spell else 0.4,
        )
        buffer_by_key[(owner, name)] = ent.id
        buffer_by_name[name] = ent.id
        buf_count += 1
        if base in type_ents:
            _link(codemap, RelationKind.WRAPS, ent.id, type_ents[base], attrs={"via": "member_type"})
        if root_spell:
            rid = _ensure_ascendc_root(codemap, root_spell, root_kind="STORAGE")
            _link(codemap, RelationKind.WRAPS, ent.id, rid, attrs={"via": "storage_root"})
            _link(codemap, RelationKind.ROOTED_AT, ent.id, rid)

    for decl in decls or []:
        type_text, name, function, file, line = _decl_fields(decl)
        if not name or not is_valid_storage_name(name):
            continue
        expanded = _resolve_alias_chain(type_text)
        base = _base_type_name(expanded)
        sync_kind = _sync_object_kind(expanded) or _sync_object_kind(type_text)
        if sync_kind is not None:
            nfile = _norm_file(file, root)
            sid = make_id(sync_kind.value.title(), "decl", function, name, nfile, line)
            root_spell = (
                "TPipe"
                if sync_kind == EntityKind.PIPE
                else ("TQue" if sync_kind == EntityKind.QUEUE else "HardEvent")
            )
            root_id = _ensure_ascendc_root(codemap, root_spell, root_kind="SYNC")
            pipe_attrs = {
                    "scope": function,
                    "type_name": _persist_type_name(type_text),
                    "tposition": tposition_from_type_text(expanded)
                    or tposition_from_type_text(type_text)
                    or "",
                    "memory_space": memory_space_from_type_text(expanded)
                    or memory_space_from_type_text(type_text)
                    or "",
                    "root_status": "REACHED",
                    "root_kind": "SYNC",
                    "root": f"AscendC::{root_spell}",
                    "provenance": "kernel_root_trace",
            }
            phase = infer_kernel_phase(name, file=nfile, scope=function)
            if phase:
                pipe_attrs["kernel_phase"] = phase
            ent = codemap.upsert(
                sync_kind,
                name,
                eid=sid,
                attrs=pipe_attrs,
                file=nfile,
                line=line,
                status="extracted",
                confidence=1.0,
            )
            _link(codemap, RelationKind.ROOTED_AT, ent.id, root_id)
            buffer_by_key[(function, name)] = ent.id
            buffer_by_name[name] = ent.id
            pipe_count += int(sync_kind == EntityKind.PIPE)
            event_count += int(sync_kind == EntityKind.EVENT)
            queue_count += int(sync_kind == EntityKind.QUEUE)
            continue
        mutex_attrs = _mutex_policy_attrs(type_text + " " + expanded)
        known = (
            is_storage_type_text(expanded)
            or is_storage_type_text(type_text)
            or base in alias_to_target
            or (
                base in type_ents
                and str(codemap.entities[type_ents[base]].attrs.get("root_status") or "") == "REACHED"
            )
            or bool(mutex_attrs.get("mutex_policy"))
        )
        if not known:
            continue
        if is_non_storage_type(expanded):
            continue
        nfile = _norm_file(file, root)
        reg_class = register_class_from_type(expanded) or register_class_from_type(type_text)
        if reg_class:
            if not nfile or int(line or 0) <= 0:
                continue
            rid = register_site_id(file=file, line=line, scope=function, name=name, root=root)
            root_id = _ensure_ascendc_root(
                codemap, _base_type_name(expanded) or "RegTensor", root_kind="REGISTER"
            )
            ent = codemap.upsert(
                EntityKind.REGISTER,
                name,
                eid=rid,
                attrs={
                    "register_class": reg_class,
                    "type_name": _persist_type_name(type_text),
                    "scope": function,
                    "root_status": "REACHED",
                    "root_kind": "REGISTER",
                    "root": codemap.entities[root_id].name,
                    "trace": [name, _base_type_name(expanded) or type_text],
                },
                file=nfile,
                line=line,
                status="extracted",
                confidence=1.0,
            )
            _link(codemap, RelationKind.ROOTED_AT, ent.id, root_id)
            reg_count += 1
            continue

        resolved = resolve_buffer_decl(expanded) or resolve_buffer_decl(type_text)
        space = memory_space_from_type_text(expanded) or memory_space_from_type_text(type_text) or "UNKNOWN"
        is_wrapper = bool((resolved or {}).get("is_wrapper")) or is_storage_wrapper_type(expanded)
        wrapper_spell = ""
        if is_wrapper:
            wrapper_spell = (
                "MutexBuffer" if "MutexBuffer" in (expanded or type_text) else _base_type_name(expanded)
            )
        project_reached = (
            base in type_ents
            and str(codemap.entities[type_ents[base]].attrs.get("root_status") or "") == "REACHED"
        )
        root_status = "REACHED"
        root_spell = ""
        if is_wrapper:
            root_spell = str((resolved or {}).get("storage_root_kind") or "LocalTensor")
        elif base in ASCENDC_BUFFER_TYPES:
            root_spell = base
        elif project_reached:
            root_spell = str(codemap.entities[type_ents[base]].attrs.get("root") or "").replace(
                "AscendC::", ""
            ) or "LocalTensor"
        elif space != "UNKNOWN" and (resolved or is_storage_type_text(expanded)):
            # Memory space only from type template args (TPosition/BufferType), not names.
            root_spell = storage_root_kind_from_space(space)
        else:
            root_status = "UNRESOLVED"

        bid = buffer_site_id(file=file, line=line, scope=function, name=name, root=root)
        attrs = {
            "memory_space": space,
            "tposition": tposition_from_type_text(expanded)
            or tposition_from_type_text(type_text)
            or "",
            "scope": function,
            "type_name": _persist_type_name(type_text),
            "role": (
                "storage_wrapper"
                if is_wrapper
                else (
                    "mutex_policy"
                    if mutex_attrs.get("mutex_policy")
                    else ("project_wrapper" if project_reached else "cann_storage")
                )
            ),
            "wrapper": wrapper_spell,
            "root_status": root_status,
            "root_kind": "STORAGE" if root_status == "REACHED" else "",
            "root": f"AscendC::{root_spell}" if root_spell else "",
            "trace": [name]
            + ([wrapper_spell] if wrapper_spell else [])
            + ([root_spell] if root_spell else []),
        }
        attrs.update(mutex_attrs)
        if root_status == "UNRESOLVED":
            attrs["gap_code"] = REASON_NO_ASCENDC_ROOT
            gaps.append(
                {
                    "code": REASON_NO_ASCENDC_ROOT,
                    "entity_id": bid,
                    "name": name,
                    "file": nfile,
                    "line": line,
                }
            )
        ent = codemap.upsert(
            EntityKind.BUFFER,
            name,
            eid=bid,
            attrs=attrs,
            file=nfile,
            line=line,
            status="extracted" if root_status == "REACHED" else "partial",
            confidence=1.0 if root_status == "REACHED" else 0.4,
        )
        buffer_by_key[(function, name)] = ent.id
        buffer_by_name[name] = ent.id
        buf_count += 1
        if root_spell:
            rid = _ensure_ascendc_root(codemap, root_spell, root_kind="STORAGE")
            if is_wrapper and wrapper_spell in type_ents:
                _link(codemap, RelationKind.WRAPS, ent.id, type_ents[wrapper_spell])
            if base in type_ents:
                _link(codemap, RelationKind.WRAPS, ent.id, type_ents[base], attrs={"via": "decl_type"})
            _link(codemap, RelationKind.WRAPS, ent.id, rid, attrs={"via": "storage_root"})
            _link(codemap, RelationKind.ROOTED_AT, ent.id, rid)

    # --- 5. METHOD + OPERATION call sites (all source calls) -------------
    method_ents: dict[str, str] = {}  # identity key → METHOD entity id

    def _ensure_method(
        name: str,
        *,
        file: str = "",
        line: int = 0,
        usr: str = "",
        qualified: str = "",
        owner: str = "",
    ) -> str:
        short = str(name or "").split("::")[-1]
        if not short or not short.isidentifier():
            return ""
        q = str(qualified or "").strip()
        if not q and owner:
            q = f"{owner}::{short}"
        # Bare short "qualified" from lexical enclosing-func is not a real
        # qualifier — collapse it so caller/callee METHOD nodes unify.
        if q and "::" not in q and q.split("::")[-1] == short:
            q = ""
        # Identity: USR > qualified > owner::name > spelling.
        # Do not key by call-site line — that forks caller/callee METHOD nodes
        # for the same lexical function and breaks CALLS closure.
        if usr:
            key = f"usr:{usr}"
        elif q:
            key = f"q:{q}"
        elif owner:
            key = f"q:{owner}::{short}"
        else:
            key = f"name:{short}"
        if key in method_ents:
            return method_ents[key]
        mid = make_id("Method", "kernel", key, file or "kernel", line)
        ent = codemap.upsert(
            EntityKind.METHOD,
            short,
            eid=mid,
            attrs={
                "role": "source_method",
                "root_status": "UNRESOLVED",
                "root_kind": "",
                "root": "",
                "trace": [q or short],
                "usr": usr,
                "qualified_name": q,
                "spelling": short,
            },
            file=file,
            line=line,
            status="partial",
            confidence=0.5,
        )
        method_ents[key] = ent.id
        return ent.id

    op_count = 0
    seen_op_ids: set[str] = set()
    for site in calls or []:
        d = site if isinstance(site, dict) else kscan.site_as_dict(site)
        callee = str(d.get("callee") or "").split("::")[-1]
        if not callee or not callee.isidentifier():
            continue
        file = str(d.get("file") or "")
        line = int(d.get("line") or 0)
        column = int(d.get("column") or 0)
        category, _engine, conf = semreg.classify(callee)
        receiver = str(d.get("receiver") or "")
        function = str(d.get("caller") or "")
        nfile = _norm_file(file, root)
        caller_qualified = str(d.get("caller_qualified") or "")
        caller_usr = str(d.get("caller_usr") or "")
        callee_qualified = str(d.get("callee_qualified") or "")
        callee_usr = str(d.get("callee_usr") or "")
        callee_decl_file = str(d.get("callee_decl_file") or "")
        callee_decl_line = int(d.get("callee_decl_line") or 0)
        identity_kind = str(d.get("identity_kind") or "")
        receiver_type = str(d.get("receiver_type") or "")
        receiver_canonical = str(d.get("receiver_canonical_type") or "")
        has_identity = bool(callee_usr or callee_qualified or callee_decl_file)

        # Receiver buffer / type for framework bridges (MutexBuffer / TQue).
        bid_recv = ""
        if receiver:
            bid_recv = buffer_by_key.get((function, receiver)) or buffer_by_name.get(receiver) or ""
        recv_is_wrapper = False
        if bid_recv and bid_recv in codemap.entities:
            be = codemap.entities[bid_recv]
            recv_is_wrapper = be.attrs.get("role") in {
                "storage_wrapper",
                "project_wrapper",
            } or is_storage_wrapper_type(
                str(be.attrs.get("wrapper") or be.attrs.get("type_name") or "")
            )
        if not recv_is_wrapper and (receiver_type or receiver_canonical):
            recv_is_wrapper = is_storage_wrapper_type(receiver_type) or is_storage_wrapper_type(
                receiver_canonical
            )
        recv_is_tque = _receiver_is_tque(
            bid_recv=bid_recv,
            receiver_type=receiver_type,
            receiver_canonical=receiver_canonical,
            codemap=codemap,
        )
        recv_is_tpipe = _receiver_is_tpipe(
            bid_recv=bid_recv,
            receiver_type=receiver_type,
            receiver_canonical=receiver_canonical,
            codemap=codemap,
        )

        args = [str(a) for a in (d.get("args") or [])]
        targs = [str(a) for a in (d.get("template_args") or [])]
        # Incomplete member-Get / empty Or: spelling alone is a guess.
        if callee == "Get" and not receiver and not targs and not has_identity:
            continue
        if callee in _VECTOR_AMBIGUOUS_ROOTS and not args and not targs and not has_identity:
            continue
        bridge = _select_framework_bridge(
            callee=callee,
            receiver=receiver,
            recv_is_wrapper=recv_is_wrapper,
            recv_is_tque=recv_is_tque,
            recv_is_tpipe=recv_is_tpipe,
            receiver_type=receiver_type,
            receiver_canonical=receiver_canonical,
            callee_usr=callee_usr,
            targs=targs,
        )
        proven, proven_spell = _prove_ascendc_api_root(
            callee=callee,
            callee_qualified=callee_qualified,
            callee_usr=callee_usr,
            callee_decl_file=callee_decl_file,
            receiver=receiver,
            receiver_type=receiver_type,
            receiver_canonical_type=receiver_canonical,
            has_identity=has_identity,
        )
        if (
            not proven
            and not bridge
            and not receiver
            and _looks_like_reg_or_vector_call(args, targs)
            and (
                callee in _VECTOR_AMBIGUOUS_ROOTS
                or is_cann_vf_api(callee)
                or is_ambiguous_vf_name(callee)
            )
        ):
            proven, proven_spell = True, vf_root_spelling(callee)
        is_root = bool(proven or bridge)
        root_kind = ""
        root_spell = ""
        if bridge:
            root_spell, root_kind = bridge
        elif proven:
            root_spell = proven_spell
            root_kind = _category_root_kind(category, proven_spell)
        is_builtin = _is_compiler_builtin(
            callee,
            usr=callee_usr,
            decl_file=callee_decl_file,
            qualified=callee_qualified,
        )
        is_scalar_minmax = bool(
            callee in {"Min", "Max"}
            and not receiver
            and not _looks_like_reg_or_vector_call(args, targs)
        )
        is_project = bool(
            not is_root
            and not is_builtin
            and (
                (
                    callee_qualified
                    and callee_decl_file
                    and not _qualified_looks_ascendc(callee_qualified)
                    and not _is_framework_decl_file(callee_decl_file)
                )
                or (
                    _is_project_decl_file(callee_decl_file)
                    and not _qualified_looks_ascendc(callee_qualified)
                    and not _is_framework_decl_file(callee_decl_file)
                )
                or is_scalar_minmax
                or bool(receiver)
            )
        )
        # The declaration line itself is not a call site.
        if (
            not is_root
            and not receiver
            and callee_decl_line == line
            and _norm_file(callee_decl_file, root) == nfile
        ):
            continue

        mint_op = _should_mint_operation(
            callee=callee,
            is_root=is_root,
            is_builtin=is_builtin,
            is_project=is_project,
        )
        if not mint_op and (is_builtin or _is_type_like_root(callee)):
            continue
        oid = (
            operation_site_id(
                file=file, line=line, column=column, callee=callee, root=root
            )
            if mint_op
            else ""
        )
        trace = [callee_qualified or callee]
        if bridge or proven:
            trace.append(f"AscendC::{root_spell}")
        elif is_project:
            trace.append(callee_qualified)
        project_proof = (
            "project_method"
            if identity_kind == "method" or (is_project and receiver)
            else ("project_free" if is_project else "")
        )
        if is_root:
            op_root_status, op_root_kind = "REACHED", (root_kind or "")
            op_root = f"AscendC::{root_spell}" if root_spell else ""
            op_proof = (
                "framework_bridge"
                if bridge
                else ("qualified_or_decl" if proven and has_identity else "lexical_free_catalog")
            )
        elif is_builtin:
            op_root_status, op_root_kind, op_root = "BUILTIN", "BUILTIN", ""
            op_proof = "compiler_builtin"
        elif is_project:
            op_root_status, op_root_kind, op_root = "PROJECT", "PROJECT", ""
            op_proof = project_proof or "project_free"
        elif category == "UNKNOWN" and nfile and line > 0:
            op_root_status, op_root_kind, op_root = "PROJECT", "PROJECT", ""
            op_proof = "project_unclassified"
        else:
            op_root_status, op_root_kind, op_root = "UNRESOLVED", "", ""
            op_proof = project_proof
        attrs = {
            "callee": callee,
            "callee_qualified": callee_qualified,
            "callee_usr": callee_usr,
            "callee_decl_file": callee_decl_file,
            "callee_decl_line": callee_decl_line,
            "identity_kind": identity_kind,
            "category": (
                category
                if category != "UNKNOWN"
                else (
                    "framework_bridge"
                    if bridge
                    else (
                        "compiler_builtin"
                        if is_builtin
                        else ("project_symbol" if (is_project or op_root_status == "PROJECT") else "UNKNOWN")
                    )
                )
            ),
            "function": function,
            "args": args,
            "template_args": targs,
            "receiver": receiver,
            "receiver_type": receiver_type,
            "receiver_canonical_type": receiver_canonical,
            "root_status": op_root_status,
            "root_kind": op_root_kind,
            "root": op_root,
            "wrapper": callee if bridge else "",
            "trace": trace,
            "provenance": str(d.get("provenance") or provenance),
            "column": column,
            "root_proof": op_proof,
            "owner": kscan.kernel_file_owner(nfile or file, Path(root)),
            "instantiation_n": int(d.get("instantiation_n") or 1),
        }
        if targs:
            attrs["template_arg_sets"] = [list(targs)]
        if is_tque_callee(callee):
            attrs["mechanism"] = "tque"
        elif is_tpipe_callee(callee):
            attrs["mechanism"] = "tpipe"
        elif is_flag_sync(callee) or callee in SYNC_MECHANISM:
            attrs["mechanism"] = str(resolve_sync_site(callee, args, targs).get("mechanism") or "")
        if not is_root and not is_builtin:
            if not nfile or line <= 0 or not callee.isidentifier():
                continue
        if (
            mint_op
            and not is_root
            and not is_project
            and not is_builtin
            and (category != "UNKNOWN" or conf not in {"", "unresolved"})
        ):
            attrs["gap_code"] = REASON_CALL_UNRESOLVED
            gaps.append(
                {
                    "code": REASON_CALL_UNRESOLVED,
                    "entity_id": oid,
                    "callee": callee,
                    "callee_qualified": callee_qualified,
                    "file": nfile,
                    "line": line,
                }
            )
        ent = None
        if mint_op and oid:
            existing = codemap.entities.get(oid)
            if existing is not None:
                existing.attrs["instantiation_n"] = int(
                    existing.attrs.get("instantiation_n") or 1
                ) + int(attrs.get("instantiation_n") or 1)
                if targs:
                    sets = existing.attrs.setdefault("template_arg_sets", [])
                    if isinstance(sets, list) and list(targs) not in sets:
                        sets.append(list(targs))
                ent = existing
            else:
                ent = codemap.upsert(
                    EntityKind.OPERATION,
                    callee,
                    eid=oid,
                    attrs=attrs,
                    file=nfile,
                    line=line,
                    status="extracted" if is_root else "partial",
                    confidence=(
                        1.0
                        if is_root and conf == "confirmed"
                        else (0.85 if bridge else 0.5)
                    ),
                )
                seen_op_ids.add(oid)
                op_count += 1
            phase = infer_kernel_phase(callee, file=nfile, scope=function)
            if phase:
                ent.attrs["kernel_phase"] = phase

        # Flag identity only. TQue EnQue/DeQue have no user event; CANN owns that
        # handshake, so they never get SIGNALS/AWAITS.
        if ent is not None and is_flag_sync(callee) and not is_tque_callee(callee):
            sync = resolve_sync_site(callee, args, targs)
            identity = str(sync.get("flag") or (args[0] if args else "")).strip()
            if re.fullmatch(r"[A-Za-z_]\w*", identity):
                event_id = make_id("Event", "sync", function, identity)
                event = codemap.upsert(
                    EntityKind.EVENT,
                    identity,
                    eid=event_id,
                    attrs={
                        "scope": function,
                        "identity": identity,
                        "event_type": str(sync.get("event") or ""),
                        "mechanism": str(sync.get("mechanism") or ""),
                        "cross_core": bool(sync.get("cross_core")),
                        "provenance": str(d.get("provenance") or provenance),
                    },
                    file=nfile,
                    line=line,
                    status="extracted",
                    confidence=1.0,
                )
                relation_kind = (
                    RelationKind.SIGNALS
                    if "Wait" in FLAG_PAIR_MATE.get(callee, "")
                    else RelationKind.AWAITS
                )
                _link(
                    codemap,
                    relation_kind,
                    ent.id,
                    event.id,
                    attrs={
                        "identity_arg": identity,
                        "file": nfile,
                        "line": line,
                        "column": column,
                    },
                )
                event_count += 1
                for role in ("src_pipe", "dst_pipe"):
                    pipe_name = str(sync.get(role) or "")
                    if not pipe_name:
                        continue
                    if not pipe_name.startswith("PIPE_"):
                        pipe_name = f"PIPE_{pipe_name}"
                    pipe_id = make_id("Pipe", "hard_event", pipe_name)
                    pipe = codemap.upsert(
                        EntityKind.PIPE,
                        pipe_name,
                        eid=pipe_id,
                        attrs={
                            "role": role,
                            "root_status": "REACHED",
                            "root_kind": "SYNC",
                            "root": f"AscendC::{pipe_name}",
                            "provenance": str(d.get("provenance") or provenance),
                        },
                        status="extracted",
                        confidence=1.0,
                    )
                    _link(
                        codemap,
                        RelationKind.REFERENCES,
                        event.id,
                        pipe.id,
                        attrs={"role": role},
                    )
                    pipe_count += 1

        # Source METHOD CALLS graph (caller → callee method or this op).
        caller_mid = (
            _ensure_method(
                function.split("::")[-1] if function else "",
                file=nfile,
                line=line,
                usr=caller_usr,
                qualified=caller_qualified or function,
            )
            if function
            else ""
        )
        callee_mid = ""
        if not proven and not bridge:
            owner_guess = ""
            if callee_qualified and "::" in callee_qualified:
                owner_guess = callee_qualified.rsplit("::", 1)[0].split("::")[-1]
                if owner_guess.lower() in {"conditional", "conditional_t"}:
                    owner_guess = ""
            elif receiver_type or receiver_canonical:
                owner_guess = _owner_from_receiver_type(receiver_canonical or receiver_type)
            callee_mid = _ensure_method(
                callee,
                file=_norm_file(callee_decl_file, root) or nfile,
                line=callee_decl_line or line,
                usr=callee_usr,
                qualified=callee_qualified,
                owner=owner_guess,
            )
            if is_project and callee_mid:
                me = codemap.entities.get(callee_mid)
                if me is not None:
                    me.status = "extracted"
                    me.confidence = max(float(me.confidence or 0), 0.9)
                    me.attrs["decl_file"] = _norm_file(callee_decl_file, root) or nfile
                    me.attrs["decl_line"] = callee_decl_line or line
                    if receiver:
                        me.attrs.setdefault("receivers", [])
                        recs = me.attrs.get("receivers")
                        if isinstance(recs, list) and receiver not in recs:
                            recs.append(receiver)
                bind_via = (
                    "project_decl"
                    if callee_decl_file
                    else ("method_receiver" if receiver else "project_free")
                )
                if ent is not None:
                    _link(
                        codemap,
                        RelationKind.BINDS,
                        ent.id,
                        callee_mid,
                        attrs={
                            "via": bind_via,
                            "file": nfile,
                            "line": line,
                            "column": column,
                            "decl_file": _norm_file(callee_decl_file, root),
                            "decl_line": callee_decl_line,
                            "receiver": receiver,
                        },
                    )
        if caller_mid and callee_mid and caller_mid != callee_mid:
            _link(
                codemap,
                RelationKind.CALLS,
                caller_mid,
                callee_mid,
                attrs={
                    "via": "source_call",
                    "file": nfile,
                    "line": line,
                    "column": column,
                    "receiver": receiver,
                },
            )
        if caller_mid and ent is not None:
            _link(
                codemap,
                RelationKind.CALLS,
                caller_mid,
                ent.id,
                attrs={
                    "via": "call_site",
                    "file": nfile,
                    "line": line,
                    "column": column,
                    "receiver": receiver,
                },
            )
        if ent is not None and is_root and root_spell:
            rid = _ensure_ascendc_root(codemap, root_spell, root_kind=root_kind or "COMPUTE_API")
            if bridge and "MutexBuffer" in type_ents:
                _link(
                    codemap,
                    RelationKind.WRAPS,
                    ent.id,
                    type_ents["MutexBuffer"],
                    attrs={"via": "framework_method_bridge"},
                )
            _link(
                codemap,
                RelationKind.ROOTED_AT,
                ent.id,
                rid,
                attrs={"via": "framework_method_bridge" if bridge else "ascendc_catalog"},
            )
            if caller_mid:
                # Direct edge so fixed-point can climb methods that call rooted ops.
                _link(
                    codemap,
                    RelationKind.CALLS,
                    caller_mid,
                    rid,
                    attrs={
                        "via": "rooted_call",
                        "file": nfile,
                        "line": line,
                        "column": column,
                    },
                    status="partial",
                )
        if ent is not None and bid_recv:
            _link(
                codemap,
                RelationKind.REFERENCES,
                ent.id,
                bid_recv,
                attrs={"symbol": receiver},
            )
            if not is_project:
                _link(
                    codemap,
                    RelationKind.CALLS,
                    bid_recv,
                    ent.id,
                    attrs={
                        "via": "method_receiver",
                        "file": nfile,
                        "line": line,
                        "column": column,
                    },
                    status="partial",
                )

    pair_stats = _record_flag_pair_appearance(codemap, gaps)

    # Bounded lexical statement order.  PRECEDES is adjacency in one source
    # function/file, not flag pairing and not a happens-before relation.
    def _sync_op(item: Any) -> bool:
        name = str(item.attrs.get("callee") or item.name or "")
        return name in _SYNC_PRECEDES_CALLEES

    ordered_ops: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for operation in codemap.by_kind(EntityKind.OPERATION):
        if not _sync_op(operation):
            continue
        ordered_ops[
            (str(operation.attrs.get("function") or ""), str(operation.file or ""))
        ].append(operation)
    precedes_count = 0
    for (_function, _file), operations in sorted(ordered_ops.items()):
        operations.sort(
            key=lambda item: (
                int(item.line_start or 0),
                int(item.attrs.get("column") or 0),
                item.id,
            )
        )
        for previous, current in zip(operations, operations[1:]):
            if precedes_count >= 500:
                break
            _link(
                codemap,
                RelationKind.PRECEDES,
                previous.id,
                current.id,
                attrs={"via": "same_function_source_order"},
            )
            precedes_count += 1
        if precedes_count >= 500:
            break

    # --- 6. Single fixed-point -------------------------------------------
    _propagate_reachability(codemap)

    # Project declaration identity is not an AscendC root. Undo any
    # CALLS/WRAPS climb that would stamp catalog REACHED on those sites.
    for e in codemap.by_kind(EntityKind.OPERATION):
        proof = str(e.attrs.get("root_proof") or "")
        if proof == "compiler_builtin":
            e.attrs["root_status"] = "BUILTIN"
            e.attrs["root_kind"] = "BUILTIN"
            e.attrs["root"] = ""
            e.status = "extracted"
            e.confidence = max(float(e.confidence or 0), 0.9)
            continue
        if not proof.startswith("project_"):
            continue
        e.attrs["root_status"] = "PROJECT"
        e.attrs["root"] = ""
        e.attrs["root_kind"] = "PROJECT"
        e.status = "extracted"
        e.confidence = max(float(e.confidence or 0), 0.9)

    # Propagate REACHED onto METHOD entities that CALL a REACHED node.
    # (Fixed-point already walks CALLS; refresh METHOD attrs from ROOTED_AT.)
    for e in codemap.by_kind(EntityKind.METHOD):
        if e.attrs.get("root_status") == "REACHED":
            continue
        for rel, other in codemap.neighbors(e.id, kind=RelationKind.CALLS, direction="out"):
            if other.attrs.get("root_status") == "REACHED" or other.attrs.get("catalog") == "ascendc":
                e.attrs["root_status"] = "REACHED"
                e.attrs["root"] = other.attrs.get("root") or other.name
                e.attrs["root_kind"] = other.attrs.get("root_kind") or e.attrs.get("root_kind") or ""
                trace = list(e.attrs.get("trace") or [e.name])
                if other.name not in trace:
                    trace.append(other.name)
                e.attrs["trace"] = trace
                e.status = "extracted"
                break

    _normalize_settled_entities(codemap)

    # --- 7. Gaps for still-unresolved source types that participate in WRAPS
    unresolved_types = 0
    for e in codemap.entities.values():
        if e.kind_name() != EntityKind.TYPE.value:
            continue
        if e.attrs.get("catalog") == "ascendc":
            continue
        if e.attrs.get("root_status") != "UNRESOLVED":
            continue
        # Only gap types that appear in a WRAPS edge (participated in composition).
        participates = bool(
            codemap.neighbors(e.id, kind=RelationKind.WRAPS, direction="both")
        )
        if not participates:
            continue
        unresolved_types += 1
        gaps.append(
            {
                "code": REASON_NO_ASCENDC_ROOT,
                "entity_id": e.id,
                "name": e.name,
                "file": e.file,
                "line": e.line_start,
            }
        )

    elapsed = time.perf_counter() - t0
    gap_counts = Counter(str(g.get("code") or "") for g in gaps)
    reached_bufs = 0
    reached_ops = 0
    tque_ops = 0
    tpipe_ops = 0
    project_resolved_ops = 0
    for e in codemap.by_kind(EntityKind.BUFFER):
        if e.attrs.get("root_status") == "REACHED":
            reached_bufs += 1
    for e in codemap.by_kind(EntityKind.OPERATION):
        if e.attrs.get("root_status") == "REACHED":
            reached_ops += 1
        callee = str(e.attrs.get("callee") or e.name or "")
        if is_tque_callee(callee):
            tque_ops += 1
        if is_tpipe_callee(callee):
            tpipe_ops += 1
        if str(e.attrs.get("root_proof") or "").startswith("project_"):
            project_resolved_ops += 1
    signals = awaits = wraps = rooted_at = alias_rels = binds = 0
    for r in codemap.relations.values():
        kind = r.kind_name()
        if kind == RelationKind.SIGNALS.value:
            signals += 1
        elif kind == RelationKind.AWAITS.value:
            awaits += 1
        elif kind == RelationKind.WRAPS.value:
            wraps += 1
        elif kind == RelationKind.ROOTED_AT.value:
            rooted_at += 1
        elif kind == RelationKind.ALIASES.value:
            alias_rels += 1
        elif kind == RelationKind.BINDS.value:
            binds += 1
    quality = {
        "operations": op_count,
        "buffers": buf_count,
        "registers": reg_count,
        "pipes": len(codemap.by_kind(EntityKind.PIPE)),
        "events": len(codemap.by_kind(EntityKind.EVENT)),
        "queues": len(codemap.by_kind(EntityKind.QUEUE)),
        "precedes": precedes_count,
        "signals": signals,
        "awaits": awaits,
        "tque_ops": tque_ops,
        "tpipe_ops": tpipe_ops,
        "flag_pairs": int(pair_stats.get("flag_pairs") or 0),
        "unpaired_flag_sync": int(pair_stats.get("unpaired_flag_sync") or 0),
        "reached_operations": reached_ops,
        "reached_buffers": reached_bufs,
        "wraps": wraps,
        "rooted_at": rooted_at,
        "aliases": alias_rels,
        "project_resolved_ops": project_resolved_ops,
        "identity_filled": identity_filled,
        "binds": binds,
    }
    meta = {
        "architecture": arch,
        "elapsed_s": round(elapsed, 3),
        "budget_s": _budget_s(),
        "provenance": provenance,
        "kernel_backend": kernel_backend,
        "walk_cache_stats": walk_stats,
        "clang_covered_files": len(covered),
        "lexical_uncovered_files": len(uncovered),
        "selected_files": len(files),
        "class_members": len(members),
        "type_aliases": len(aliases),
        "clang_type_decls": len(clang_types),
        "clang_base_decls": len(clang_bases),
        "operations": op_count,
        "buffers": buf_count,
        "registers": reg_count,
        "pipes": len(codemap.by_kind(EntityKind.PIPE)),
        "events": len(codemap.by_kind(EntityKind.EVENT)),
        "queues": len(codemap.by_kind(EntityKind.QUEUE)),
        "precedes": precedes_count,
        "reached_operations": reached_ops,
        "reached_buffers": reached_bufs,
        "unresolved_types": unresolved_types,
        "gap_count": len(gaps),
        "gap_counts": dict(gap_counts),
        "gaps": gaps[:200],
        "identity_filled": identity_filled,
        "corpus_n": len(extra_arch),
        "gated_corpus_n": len(priority),
        "arch_kernel_primitives_added": extra_added,
        "gated_fill_complete": gated_fill_complete,
        "budget_expired": budget.expired(),
        "source_api_gated": source_api_gated,
        "quality": quality,
    }
    try:
        from uo_init.perf import record_pass

        record_pass(
            "kernel_root_trace",
            source_files=len(files),
            gated_fill_complete=gated_fill_complete,
            budget_expired=budget.expired(),
            cache_walk_loads=int((walk_stats or {}).get("pickle_load") or 0),
        )
    except Exception:  # noqa: BLE001
        pass
    codemap.meta["kernel_root_trace"] = meta
    codemap.meta["kernel_backend"] = kernel_backend
    # Thin compat for older query helpers (not an execution model).
    codemap.meta["kernel_execution"] = {
        "operations": op_count,
        "buffers": buf_count,
        "registers": reg_count,
        "elapsed_s": meta["elapsed_s"],
        "root_trace": True,
        "kernel_backend": kernel_backend,
    }
    return codemap
