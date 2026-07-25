from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "engines" / "understand-operator" / "uo" / "scripts" / "receiver_type_facts.py"
text = path.read_text(encoding="utf-8")

old = '''        for statement, offset in _iter_semicolon_statements(fn.body_text or ""):
            line = fn.start_line + (fn.body_text or "")[:offset].count("\\n")
            auto_assignment = _parse_auto_assignment(statement, fn, line)
'''
new = '''        body_text = fn.body_text or ""
        opening_brace = body_text.find("{")
        scan_offset = opening_brace + 1 if opening_brace >= 0 else 0
        scan_text = body_text[scan_offset:]
        for statement, offset in _iter_semicolon_statements(scan_text):
            line = fn.start_line + body_text[: scan_offset + offset].count("\\n")
            auto_assignment = _parse_auto_assignment(statement, fn, line)
'''
if old not in text:
    raise SystemExit("function body scope marker missing")
text = text.replace(old, new, 1)

old = '''        body = text[match.end():end]
        for statement, _offset in _iter_semicolon_statements(body, top_level_braces=True):
            declared = _parse_declaration(statement)
'''
new = '''        body = text[match.end():end]
        for statement, _offset in _iter_class_member_statements(body):
            declared = _parse_declaration(statement)
'''
if old not in text:
    raise SystemExit("class member scope marker missing")
text = text.replace(old, new, 1)

old = '''    prefix = text[:match.start()].strip()
    if not prefix:
        return None
    type_name = _normalize_declared_type(prefix)
    if not type_name or _normalize_type_name(type_name) in {"auto", "void"}:
'''
new = '''    prefix = text[:match.start()].strip()
    if not prefix or any(ch in prefix for ch in "{};"):
        return None
    type_name = _normalize_declared_type(prefix)
    if (
        not type_name
        or any(ch in type_name for ch in "{};")
        or _normalize_type_name(type_name) in {"auto", "void"}
    ):
'''
if old not in text:
    raise SystemExit("declaration validation marker missing")
text = text.replace(old, new, 1)

old = '''    prefix = header[:name_start]
    prefix = re.sub(r"template\\s*<.*?>\\s*", " ", prefix, flags=re.DOTALL)
'''
new = '''    prefix = header[:name_start]
    prefix = re.split(r"[;}]", prefix)[-1]
    prefix = re.sub(r"template\\s*<.*?>\\s*", " ", prefix, flags=re.DOTALL)
'''
if old not in text:
    raise SystemExit("return prefix marker missing")
text = text.replace(old, new, 1)

marker = '''def _iter_semicolon_statements(text: str, *, top_level_braces: bool = False):
'''
helper = '''def _iter_class_member_statements(text: str):
    """Yield only class-scope semicolon statements, skipping inline method bodies."""
    start = 0
    index = 0
    paren = bracket = 0
    quote = ""
    escape = False
    while index < len(text):
        ch = text[index]
        if quote:
            if escape:
                escape = False
            elif ch == "\\\\":
                escape = True
            elif ch == quote:
                quote = ""
            index += 1
            continue
        if ch in {'"', "'"}:
            quote = ch
            index += 1
            continue
        if ch == "(":
            paren += 1
        elif ch == ")":
            paren = max(0, paren - 1)
        elif ch == "[":
            bracket += 1
        elif ch == "]":
            bracket = max(0, bracket - 1)
        elif ch == "{" and paren == 0 and bracket == 0:
            end = _matching_brace(text, index)
            if end is None:
                return
            start = end + 1
            index = end + 1
            continue
        elif ch == ";" and paren == 0 and bracket == 0:
            yield text[start:index], start
            start = index + 1
        index += 1


'''
if helper not in text:
    if marker not in text:
        raise SystemExit("class statement helper marker missing")
    text = text.replace(marker, helper + marker, 1)

path.write_text(text, encoding="utf-8")
print("fixed scoped receiver declaration parsing")
