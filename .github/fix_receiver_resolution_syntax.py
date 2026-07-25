from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "engines" / "understand-operator" / "uo" / "scripts" / "function_call_graph.py"
text = path.read_text(encoding="utf-8")
broken = 'line_prefix = "\n".join(full.splitlines()[: max(0, site.line)])'
fixed = 'line_prefix = "\\n".join(full.splitlines()[: max(0, site.line)])'
if broken not in text:
    raise SystemExit("receiver fallback newline marker missing")
path.write_text(text.replace(broken, fixed, 1), encoding="utf-8")
print("fixed receiver fallback newline escaping")
