from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def write(rel: str, text: str) -> None:
    (ROOT / rel).write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def patch_function_body() -> None:
    rel = "engines/understand-operator/uo/scripts/function_body.py"
    text = read(rel)

    old_re = '''_CALL_RE = re.compile(
    r"(?:"
    r"(?P<recv>(?:this\\s*->|[A-Za-z_]\\w*(?:\\s*::\\s*[A-Za-z_]\\w*)*\\s*\\.\\s*|"
    r"[A-Za-z_]\\w*(?:\\s*::\\s*[A-Za-z_]\\w*)*\\s*->\\s*))?"
    r"(?P<callee>(?:[A-Za-z_]\\w*(?:\\s*::\\s*)?)+)"
    r"(?P<targs>\\s*<[^>;{]{0,120}>)?"
    r"\\s*\\("
    r")",
)
'''
    new_re = '''# Deliberately linear call-head scan. Qualified names and receivers are parsed
# with a bounded backward walk below; nesting optional repetitions here caused
# catastrophic backtracking on large AscendC kernel bodies.
_CALL_OPEN_RE = re.compile(
    r"\\b(?P<callee>[A-Za-z_]\\w*)"
    r"(?P<targs>\\s*<[^>;{}\\n]{0,120}>)?"
    r"\\s*\\("
)
'''
    text = replace_once(text, old_re, new_re, "call regex")

    old_control = '_CONTROL_NAMES = frozenset({"if", "for", "while", "switch", "catch", "else", "try"})'
    new_control = '_CONTROL_NAMES = frozenset({"if", "for", "while", "switch", "catch", "else", "try", "constexpr"})'
    text = replace_once(text, old_control, new_control, "control names")

    old_sig = '''    qual_hint: str = "",
    line_starts: list[int] | None = None,
) -> FunctionDefinition | None:
    def_start = _match_line(text, start_pos, line_starts)
    def_end = _match_line(text, end_pos, line_starts)
    lines = text.splitlines()
'''
    new_sig = '''    qual_hint: str = "",
    line_starts: list[int] | None = None,
    source_lines: list[str] | None = None,
) -> FunctionDefinition | None:
    def_start = _match_line(text, start_pos, line_starts)
    def_end = _match_line(text, end_pos, line_starts)
    lines = source_lines if source_lines is not None else text.splitlines()
'''
    text = replace_once(text, old_sig, new_sig, "definition source lines")

    old_starts = '''    starts = _line_starts(text)
    out: list[FunctionDefinition] = []
'''
    new_starts = '''    starts = _line_starts(text)
    source_lines = text.splitlines()
    out: list[FunctionDefinition] = []
'''
    text = replace_once(text, old_starts, new_starts, "precomputed source lines")

    old_call = '''            qual_hint=(match.group("qual") or ""),
            line_starts=starts,
        )
'''
    new_call = '''            qual_hint=(match.group("qual") or ""),
            line_starts=starts,
            source_lines=source_lines,
        )
'''
    text = replace_once(text, old_call, new_call, "definition source-lines call")

    marker = '''def extract_call_sites(
    fn: FunctionDefinition,
'''
    helpers = '''def _skip_ws_left(text: str, pos: int, *, floor: int) -> int:
    while pos > floor and text[pos - 1].isspace():
        pos -= 1
    return pos


def _read_ident_left(text: str, pos: int, *, floor: int) -> tuple[str, int]:
    pos = _skip_ws_left(text, pos, floor=floor)
    end = pos
    while pos > floor and (text[pos - 1].isalnum() or text[pos - 1] == "_"):
        pos -= 1
    if pos == end or not (text[pos].isalpha() or text[pos] == "_"):
        return "", end
    return text[pos:end], pos


def _call_context(text: str, name_start: int, callee: str) -> tuple[str, str, int]:
    """Return (qualified callee, receiver, expression start) with bounded work."""
    floor = max(0, name_start - 240)
    pos = _skip_ws_left(text, name_start, floor=floor)

    # Namespace/class qualification: A::B::Method(
    qual_parts: list[str] = []
    qpos = pos
    while qpos - 2 >= floor and text[qpos - 2 : qpos] == "::":
        ident, ident_start = _read_ident_left(text, qpos - 2, floor=floor)
        if not ident:
            break
        qual_parts.append(ident)
        qpos = _skip_ws_left(text, ident_start, floor=floor)
    if qual_parts:
        raw = "::".join(reversed(qual_parts)) + "::" + callee
        return raw, "", qpos

    # Object receiver: this->Method( / obj.Method( / Type::obj->Method(
    op = ""
    rpos = pos
    if rpos - 2 >= floor and text[rpos - 2 : rpos] == "->":
        op = "->"
        rpos -= 2
    elif rpos - 1 >= floor and text[rpos - 1] == ".":
        op = "."
        rpos -= 1
    if not op:
        return callee, "", name_start

    ident, ident_start = _read_ident_left(text, rpos, floor=floor)
    if not ident:
        return callee, "", name_start
    recv_parts = [ident]
    rpos = _skip_ws_left(text, ident_start, floor=floor)
    while rpos - 2 >= floor and text[rpos - 2 : rpos] == "::":
        ident, ident_start = _read_ident_left(text, rpos - 2, floor=floor)
        if not ident:
            break
        recv_parts.append(ident)
        rpos = _skip_ws_left(text, ident_start, floor=floor)
    receiver = "::".join(reversed(recv_parts)) + op
    return callee, receiver, rpos


''' + marker
    text = replace_once(text, marker, helpers, "call context helpers")

    old_loop = '''    for match in _CALL_RE.finditer(scan):
        callee_raw = (match.group("callee") or "").strip()
        callee = callee_raw.split("::")[-1].strip()
        if not callee or callee.casefold() in noise_cf:
            continue
        if callee == fn.name and not match.group("recv"):
            # Likely constructor-like / recursive — keep but mark hint
            pass
        recv = (match.group("recv") or "").strip()
        targs = (match.group("targs") or "").strip()
        # Rough argument count: commas at depth 0 until matching ')'
        arg_count = _count_args(scan, match.end() - 1)
        line_in_scan = _line_from_starts(scan_starts, match.start())
        abs_line = scan_base_line + line_in_scan - 1
        expr = match.group(0).rstrip("(").strip()
        hint = ""
        if "::" in callee_raw:
            hint = callee_raw
        elif recv:
            hint = f"{recv}{callee}"
'''
    new_loop = '''    for match in _CALL_OPEN_RE.finditer(scan):
        callee = (match.group("callee") or "").strip()
        if not callee or callee.casefold() in noise_cf:
            continue
        callee_raw, recv, expr_start = _call_context(scan, match.start("callee"), callee)
        if callee == fn.name and not recv:
            # Likely constructor-like / recursive — keep but mark hint
            pass
        targs = (match.group("targs") or "").strip()
        # Rough argument count: commas at depth 0 until matching ')'
        arg_count = _count_args(scan, match.end() - 1)
        line_in_scan = _line_from_starts(scan_starts, expr_start)
        abs_line = scan_base_line + line_in_scan - 1
        expr_head = callee_raw if "::" in callee_raw else f"{recv}{callee}"
        expr = f"{expr_head}{targs}".strip()
        hint = ""
        if "::" in callee_raw:
            hint = callee_raw
        elif recv:
            hint = f"{recv}{callee}"
'''
    text = replace_once(text, old_loop, new_loop, "linear call loop")
    write(rel, text)


def patch_tests() -> None:
    rel = "engines/understand-operator/tests/test_fag_graph_identity_and_perf.py"
    text = read(rel)
    if "extract_call_sites" not in text:
        text = text.replace(
            "    iter_function_definitions,\n",
            "    iter_function_definitions,\n    extract_call_sites,\n",
            1,
        )
    if "test_call_scan_is_linear_on_long_qualified_noise" not in text:
        text += '''


def test_call_scan_is_linear_on_long_qualified_noise() -> None:
    noise = "A::" * 20000 + "not_a_call;"
    body = (
        "void Run() {\\n" + noise +
        "\\nobj->Process(x);\\nKernel::Compute<Mode>(a, b);\\n}"
    )
    fn = FunctionDefinition(
        name="Run", qualified_name="Driver::Run", class_or_namespace="Driver",
        normalized_signature="()", template_arity_or_signature="",
        specialization_kind="none", file_path="op_kernel/long.cpp",
        start_line=1, end_line=4, header_text="void Run()",
        body_text=body, source_hash="s", snippet_hash="h",
        identity_key="IK_LONG", stable_id="FN_LONG",
    )
    sites = extract_call_sites(fn)
    assert [site.callee_name for site in sites] == ["Process", "Compute"]
    assert sites[0].receiver_type_or_object == "obj->"
    assert sites[1].callee_qualified_hint == "Kernel::Compute"
    assert sites[1].argument_count == 2
'''
    write(rel, text)


def main() -> None:
    patch_function_body()
    patch_tests()
    print("linear call scanner fix applied")


if __name__ == "__main__":
    main()
