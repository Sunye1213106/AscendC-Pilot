from pathlib import Path

path = Path(__file__).resolve().parents[1] / "engines/understand-operator/uo/scripts/receiver_type_facts.py"
text = path.read_text(encoding="utf-8")
old = '''    for owner in owner_candidates:
        candidates.update(facts.return_types_by_method.get((owner, method, argument_count), set()))
    elif method:
        candidates.update(facts.return_types_by_name.get((method, argument_count), set()))
'''
new = '''    for owner in owner_candidates:
        candidates.update(facts.return_types_by_method.get((owner, method, argument_count), set()))
    if not owner_candidates and method:
        candidates.update(facts.return_types_by_name.get((method, argument_count), set()))
'''
if old not in text:
    raise SystemExit("invalid owner fallback block not found")
path.write_text(text.replace(old, new), encoding="utf-8")
