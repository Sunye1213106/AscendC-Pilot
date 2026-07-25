from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def write(rel: str, text: str) -> None:
    path = ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def replace_between(text: str, start: str, end: str, replacement: str, *, label: str) -> str:
    i = text.find(start)
    if i < 0:
        raise RuntimeError(f"{label}: start marker missing")
    j = text.find(end, i)
    if j < 0:
        raise RuntimeError(f"{label}: end marker missing")
    return text[:i] + replacement + text[j:]


def patch_function_body() -> None:
    rel = "engines/understand-operator/uo/scripts/function_body.py"
    text = read(rel)
    text = replace_once(
        text,
        "import re\nfrom dataclasses import asdict, dataclass\n",
        "import hashlib\nimport re\nfrom bisect import bisect_right\nfrom collections import OrderedDict\nfrom dataclasses import asdict, dataclass\n",
        label="function_body imports",
    )
    cache_helpers = '''\n\n_SOURCE_TEXT_CACHE: OrderedDict[tuple[str, int, int], str] = OrderedDict()\n_FUNCTION_DEFINITION_CACHE: OrderedDict[\n    tuple[str, int, int, str], tuple[FunctionDefinition, ...]\n] = OrderedDict()\n_CACHE_LIMIT = 128\n\n\ndef _cache_put(cache: OrderedDict, key: object, value: object) -> None:\n    cache[key] = value\n    cache.move_to_end(key)\n    while len(cache) > _CACHE_LIMIT:\n        cache.popitem(last=False)\n\n\ndef _path_version(path: Path) -> tuple[str, int, int]:\n    stat = path.stat()\n    return (path.as_posix(), int(stat.st_mtime_ns), int(stat.st_size))\n\n\ndef _read_source_text(path: Path) -> str:\n    key = _path_version(path)\n    cached = _SOURCE_TEXT_CACHE.get(key)\n    if cached is not None:\n        _SOURCE_TEXT_CACHE.move_to_end(key)\n        return cached\n    text = path.read_text(encoding="utf-8", errors="ignore")\n    _cache_put(_SOURCE_TEXT_CACHE, key, text)\n    return text\n\n\ndef _line_starts(text: str) -> list[int]:\n    starts = [0]\n    starts.extend(match.end() for match in re.finditer("\\n", text))\n    return starts\n\n\ndef _line_from_starts(starts: list[int], pos: int) -> int:\n    return bisect_right(starts, max(0, pos))\n'''
    text = replace_once(
        text,
        ")\n\n\n@dataclass\nclass FunctionDefinition:",
        ")" + cache_helpers + "\n\n@dataclass\nclass FunctionDefinition:",
        label="function_body cache helpers",
    )
    text = replace_once(
        text,
        "def _match_line(text: str, pos: int) -> int:\n    return text.count(\"\\n\", 0, pos) + 1\n",
        "def _match_line(text: str, pos: int, starts: list[int] | None = None) -> int:\n    if starts is not None:\n        return _line_from_starts(starts, pos)\n    return text.count(\"\\n\", 0, pos) + 1\n",
        label="function_body match line",
    )
    text = replace_once(
        text,
        "    qual_hint: str = \"\",\n) -> FunctionDefinition | None:\n    def_start = _match_line(text, start_pos)\n    def_end = _match_line(text, end_pos)\n",
        "    qual_hint: str = \"\",\n    line_starts: list[int] | None = None,\n) -> FunctionDefinition | None:\n    def_start = _match_line(text, start_pos, line_starts)\n    def_end = _match_line(text, end_pos, line_starts)\n",
        label="function_body build definition line index",
    )
    new_iter = '''def iter_function_definitions_from_text(\n    repo_root: Path,\n    file_path: str,\n    text: str,\n    *,\n    architecture: str = "",\n    source_hash: str = "",\n) -> list[FunctionDefinition]:\n    """Parse all definitions from already-loaded text; overload identities are preserved."""\n    path = resolve_repo_source_path(repo_root, file_path)\n    if path is None:\n        return []\n    rel = to_repo_relative(repo_root, path)\n    src_hash = source_hash or hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()\n    starts = _line_starts(text)\n    out: list[FunctionDefinition] = []\n    seen_spans: set[tuple[int, int, str]] = set()\n    captured_outer_end = 0\n\n    for match in _FN_CANDIDATE_RE.finditer(text):\n        span = _definition_span_at(text, match)\n        if span is None:\n            continue\n        start_pos, end_pos, name = span\n        start_line = _match_line(text, start_pos, starts)\n        if start_line < captured_outer_end:\n            continue\n        fn = _build_function_definition_from_span(\n            name=name,\n            text=text,\n            start_pos=start_pos,\n            end_pos=end_pos,\n            rel=rel,\n            source_hash=src_hash,\n            architecture=architecture,\n            qual_hint=(match.group("qual") or ""),\n            line_starts=starts,\n        )\n        if fn is None:\n            continue\n        key = (fn.start_line, fn.end_line, fn.stable_id)\n        if key in seen_spans:\n            continue\n        seen_spans.add(key)\n        out.append(fn)\n        captured_outer_end = max(captured_outer_end, fn.end_line)\n    out.sort(key=lambda f: (f.start_line, f.qualified_name, f.normalized_signature))\n    return out\n\n\ndef iter_function_definitions(\n    repo_root: Path,\n    file_path: str,\n    *,\n    architecture: str = "",\n) -> list[FunctionDefinition]:\n    """Return brace-bounded definitions with a stat-keyed source/parse cache."""\n    path = resolve_repo_source_path(repo_root, file_path)\n    if path is None:\n        return []\n    try:\n        version = _path_version(path)\n    except OSError:\n        return []\n    cache_key = (*version, architecture)\n    cached = _FUNCTION_DEFINITION_CACHE.get(cache_key)\n    if cached is not None:\n        _FUNCTION_DEFINITION_CACHE.move_to_end(cache_key)\n        return list(cached)\n    try:\n        source = _read_source_text(path)\n    except OSError:\n        return []\n    parsed = iter_function_definitions_from_text(\n        repo_root,\n        to_repo_relative(repo_root, path),\n        source,\n        architecture=architecture,\n        source_hash=hashlib.sha256(source.encode("utf-8", errors="ignore")).hexdigest(),\n    )\n    _cache_put(_FUNCTION_DEFINITION_CACHE, cache_key, tuple(parsed))\n    return list(parsed)\n\n\n'''
    text = replace_between(
        text,
        "def iter_function_definitions(\n",
        "def resolve_function_candidates(\n",
        new_iter,
        label="function_body iterator refactor",
    )
    text = replace_once(
        text,
        "    try:\n        lines = path.read_text(encoding=\"utf-8\", errors=\"ignore\").splitlines()\n    except OSError:\n        return \"\", start, start\n",
        "    try:\n        lines = _read_source_text(path).splitlines()\n    except OSError:\n        return \"\", start, start\n",
        label="function_body fallback cache",
    )
    text = replace_once(
        text,
        "    body = fn.body_text or \"\"\n    # Only scan inside braces when possible\n    brace = body.find(\"{\")\n    scan = body[brace + 1 :] if brace >= 0 else body\n",
        "    noise_cf = {name.casefold() for name in noise}\n    body = fn.body_text or \"\"\n    # Only scan inside braces when possible\n    brace = body.find(\"{\")\n    scan = body[brace + 1 :] if brace >= 0 else body\n    scan_starts = _line_starts(scan)\n    scan_base_line = fn.start_line + (body[: brace + 1].count(\"\\n\") if brace >= 0 else 0)\n",
        label="function_body call scan index",
    )
    text = replace_once(
        text,
        "        if not callee or callee.casefold() in {n.casefold() for n in noise}:\n",
        "        if not callee or callee.casefold() in noise_cf:\n",
        label="function_body call noise",
    )
    text = replace_once(
        text,
        "        line_in_scan = scan.count(\"\\n\", 0, match.start()) + 1\n        abs_line = fn.start_line + (body[: brace + 1 + match.start()].count(\"\\n\") if brace >= 0 else line_in_scan - 1)\n",
        "        line_in_scan = _line_from_starts(scan_starts, match.start())\n        abs_line = scan_base_line + line_in_scan - 1\n",
        label="function_body call line lookup",
    )
    write(rel, text)


def patch_function_call_graph() -> None:
    rel = "engines/understand-operator/uo/scripts/function_call_graph.py"
    text = read(rel)
    old = '''    recv = (site.receiver_type_or_object or "").strip()\n    if recv.startswith("this") or recv in {".", "->", "this->"}:\n        same = [c for c in name_hits if c.class_or_namespace == caller.class_or_namespace]\n        if same:\n            return same\n\n    if recv and ("." in recv or "->" in recv):\n        same_cls = [c for c in name_hits if c.class_or_namespace == caller.class_or_namespace]\n        if same_cls:\n            return same_cls\n\n    same_cls = [c for c in name_hits if c.class_or_namespace == caller.class_or_namespace]\n    if same_cls:\n        return same_cls\n\n    if len(name_hits) == 1:\n        return name_hits\n    return name_hits\n'''
    new = '''    recv = (site.receiver_type_or_object or "").strip()\n    if recv.startswith("this") or recv in {".", "->", "this->"}:\n        same = [c for c in name_hits if c.class_or_namespace == caller.class_or_namespace]\n        if same:\n            return _filter_by_arity(same, site.argument_count)\n\n    # An arbitrary object receiver does not prove the caller's class. Keep the\n    # cross-class candidate set unless the source carries an explicit Class:: hint.\n    if recv and ("." in recv or "->" in recv):\n        return _filter_by_arity(name_hits, site.argument_count)\n\n    same_cls = [c for c in name_hits if c.class_or_namespace == caller.class_or_namespace]\n    if same_cls:\n        return _filter_by_arity(same_cls, site.argument_count)\n\n    return _filter_by_arity(name_hits, site.argument_count)\n\n\ndef _filter_by_arity(\n    candidates: list[FunctionDefinition], argument_count: int\n) -> list[FunctionDefinition]:\n    if len(candidates) <= 1:\n        return candidates\n    hits = [fn for fn in candidates if _signature_arity(fn.normalized_signature) == argument_count]\n    return hits or candidates\n\n\ndef _signature_arity(signature: str) -> int:\n    text = str(signature or "").strip()\n    if not text.startswith("(") or not text.endswith(")"):\n        return -1\n    inner = text[1:-1].strip()\n    if not inner or inner == "void":\n        return 0\n    depth = 0\n    count = 1\n    for ch in inner:\n        if ch in "(<[{":\n            depth += 1\n        elif ch in ")>]}":\n            depth = max(0, depth - 1)\n        elif ch == "," and depth == 0:\n            count += 1\n    return count\n'''
    text = replace_once(text, old, new, label="call graph receiver resolution")
    write(rel, text)


def patch_host() -> None:
    rel = "engines/understand-operator/uo/scripts/extract_host_subgraph.py"
    text = read(rel)
    text = replace_once(text, "import argparse\nimport re\n", "import argparse\nimport os\nimport re\n", label="host imports")
    helpers = '''\n\ndef _has_precise_identity(item: dict[str, Any]) -> bool:\n    if item.get("identity_key"):\n        return True\n    return bool(\n        item.get("file_path")\n        and (item.get("qualified_name") or item.get("class_or_namespace"))\n        and (\n            item.get("start_line")\n            or item.get("normalized_signature")\n            or item.get("signature")\n            or item.get("template_arity_or_signature")\n        )\n    )\n\n\ndef _writer_role_indexes(\n    plan: dict[str, Any],\n) -> tuple[dict[str, str], dict[str, str], set[str]]:\n    by_identity: dict[str, str] = {}\n    grouped: dict[str, list[dict[str, Any]]] = {}\n    for writer in plan.get("writers") or []:\n        if not isinstance(writer, dict):\n            continue\n        role = str(writer.get("role") or "")\n        if not role or role == "ignore":\n            continue\n        by_identity[_chain_item_key(writer)] = role\n        name = str(writer.get("name") or "").casefold()\n        if name:\n            grouped.setdefault(name, []).append(writer)\n    by_name: dict[str, str] = {}\n    incomplete_duplicates: set[str] = set()\n    for name, writers in grouped.items():\n        roles = {str(w.get("role") or "") for w in writers}\n        if len(roles) == 1:\n            by_name[name] = next(iter(roles))\n        if len(writers) > 1 and not all(_has_precise_identity(w) for w in writers):\n            incomplete_duplicates.add(name)\n    return by_identity, by_name, incomplete_duplicates\n\n\ndef _add_chain_item(\n    chain: list[dict[str, Any]], chain_keys: set[str], item: dict[str, Any]\n) -> bool:\n    key = _chain_item_key(item)\n    if key in chain_keys:\n        return False\n    chain_keys.add(key)\n    chain.append(item)\n    return True\n\n\ndef _env_int(name: str, default: int, minimum: int, maximum: int) -> int:\n    try:\n        value = int(os.environ.get(name, str(default)))\n    except ValueError:\n        value = default\n    return max(minimum, min(maximum, value))\n'''
    text = replace_once(
        text,
        "    return f\"{fp}|{qn}|{cls}|{sig}|{tpl}\".casefold()\n\n\nIF_RE =",
        "    return f\"{fp}|{qn}|{cls}|{sig}|{tpl}\".casefold()" + helpers + "\n\nIF_RE =",
        label="host identity helpers",
    )
    old_roles = '''    writer_roles = {\n        str(w.get("name") or "").casefold(): str(w.get("role") or "")\n        for w in (plan or {}).get("writers") or []\n        if isinstance(w, dict)\n    }\n'''
    new_roles = '''    writer_roles_by_identity, writer_roles_by_name, incomplete_duplicate_writers = (\n        _writer_role_indexes(plan or {})\n    )\n    for duplicate_name in sorted(incomplete_duplicate_writers):\n        unresolved.append(\n            {\n                "id": stable_id("UNRES_HOST_WRITER_ID_", duplicate_name),\n                "kind": "writer_identity_incomplete",\n                "severity": "blocking",\n                "message": (\n                    f"duplicate host writer {duplicate_name!r} lacks file/class/signature identity; "\n                    "short-name role assignment is disabled"\n                ),\n                "file_path": "",\n                "snippet": "",\n            }\n        )\n'''
    text = replace_once(text, old_roles, new_roles, label="host writer role indexes")
    old_chain = '''    chain: list[dict[str, Any]] = []\n    for node in seed_nodes:\n        item = _item_from_ep_node(node)\n        if not any(\n            (x.get("qualified_name") == item.get("qualified_name") and x.get("file_path") == item.get("file_path"))\n            for x in chain\n        ):\n            chain.append(item)\n'''
    new_chain = '''    chain: list[dict[str, Any]] = []\n    chain_keys: set[str] = set()\n    for node in seed_nodes:\n        _add_chain_item(chain, chain_keys, _item_from_ep_node(node))\n'''
    text = replace_once(text, old_chain, new_chain, label="host chain set")
    old_trace = '''        traced = client.bounded_trace(\n            root_sym,\n            keep_names=keep_for_trace or None,\n            max_depth=5,\n            max_nodes=60,\n        )\n        for sym in traced:\n            d = sym.as_dict()\n            if not any(item.get("qualified_name") == d.get("qualified_name") for item in chain):\n                chain.append(d)\n'''
    new_trace = '''        trace_max_depth = _env_int("UO_HOST_TRACE_MAX_DEPTH", 6, 1, 12)\n        trace_max_nodes = _env_int("UO_HOST_TRACE_MAX_NODES", 200, 20, 4000)\n        traced = client.bounded_trace(\n            root_sym,\n            keep_names=keep_for_trace or None,\n            max_depth=trace_max_depth,\n            max_nodes=trace_max_nodes,\n        )\n        for sym in traced:\n            _add_chain_item(chain, chain_keys, sym.as_dict())\n        if len(traced) >= trace_max_nodes:\n            unresolved.append(\n                {\n                    "id": "UNRES_HOST_TRACE_TRUNCATED",\n                    "kind": "host_trace_truncated",\n                    "severity": "blocking",\n                    "message": (\n                        f"CBM host trace reached max_nodes={trace_max_nodes}; "\n                        "raise UO_HOST_TRACE_MAX_NODES and rebuild"\n                    ),\n                    "file_path": str(primary.get("file_path") or ""),\n                    "snippet": "",\n                }\n            )\n'''
    text = replace_once(text, old_trace, new_trace, label="host trace budget")
    text = text.replace(
        '''            item = _item_from_ep_node(node)\n            if not any(x.get("qualified_name") == item.get("qualified_name") for x in chain):\n                chain.append(item)\n''',
        '''            _add_chain_item(chain, chain_keys, _item_from_ep_node(node))\n''',
        1,
    )
    old_seed_header = '''    # Seed helpers named in plan chain roles + entry-body CamelCase calls\n    entry_body, _, _ = resolve_helper_body(repo_root, primary, prefer_definition=True)\n    seed_names: list[str] = []\n    for item in (plan or {}).get("writers") or []:\n        if isinstance(item, dict) and str(item.get("role") or "") in {\n            "tiling_writer",\n            "key_writer",\n            "workspace_writer",\n            "provenance_helper",\n        }:\n            n = str(item.get("name") or "").strip()\n            if n:\n                seed_names.append(n)\n'''
    new_seed_header = '''    # Seed exact plan writers first. This preserves Normal/Varlen/Empty helpers\n    # that share a short name but differ by class, signature, or source location.\n    body_cache: dict[str, tuple[str, int, int]] = {}\n    entry_body, entry_start, entry_end = resolve_helper_body(\n        repo_root, primary, prefer_definition=True\n    )\n    body_cache[_chain_item_key(primary)] = (entry_body, entry_start, entry_end)\n    seed_names: list[str] = []\n    for item in (plan or {}).get("writers") or []:\n        if isinstance(item, dict) and str(item.get("role") or "") in {\n            "tiling_writer",\n            "key_writer",\n            "workspace_writer",\n            "provenance_helper",\n        }:\n            n = str(item.get("name") or "").strip()\n            if not n:\n                continue\n            _add_chain_item(chain, chain_keys, dict(item))\n            if not _has_precise_identity(item):\n                seed_names.append(n)\n'''
    text = replace_once(text, old_seed_header, new_seed_header, label="host exact writer seeds")
    old_add_child = '''        if any(_chain_item_key(item) == _chain_item_key(child) for item in chain):\n            continue\n        chain.append(child)\n'''
    text = replace_once(
        text,
        old_add_child,
        '''        _add_chain_item(chain, chain_keys, child)\n''',
        label="host child dedupe",
    )
    old_extra = '''        if any(str(item.get("name") or "") == name for item in chain):\n            continue\n        hit = None\n        if client.available:\n            hit = client.resolve_qn(name, file_contains=architecture)\n        chain.append(hit.as_dict() if hit is not None else meta)\n'''
    new_extra = '''        hit = None\n        if client.available:\n            hit = client.resolve_qn(name, file_contains=architecture)\n        _add_chain_item(chain, chain_keys, hit.as_dict() if hit is not None else meta)\n'''
    text = replace_once(text, old_extra, new_extra, label="host extra dedupe")
    old_loop = '''        file_path = str(item.get("file_path") or "")\n        name_l = str(item.get("name") or "").casefold()\n        role = writer_roles.get(name_l, "")\n        prefer_def = True  # always brace-bound when definition exists; else tight window\n        body, start, end = resolve_helper_body(repo_root, item, prefer_definition=prefer_def)\n        file_path = str(item.get("file_path") or file_path)\n'''
    new_loop = '''        file_path = str(item.get("file_path") or "")\n        name_l = str(item.get("name") or "").casefold()\n        item_key_before = _chain_item_key(item)\n        role = writer_roles_by_identity.get(\n            item_key_before, writer_roles_by_name.get(name_l, "")\n        )\n        prefer_def = True  # always brace-bound when definition exists; else tight window\n        cached_body = body_cache.get(item_key_before)\n        if cached_body is None:\n            body, start, end = resolve_helper_body(\n                repo_root, item, prefer_definition=prefer_def\n            )\n            body_cache[item_key_before] = (body, start, end)\n            body_cache[_chain_item_key(item)] = (body, start, end)\n        else:\n            body, start, end = cached_body\n        file_path = str(item.get("file_path") or file_path)\n'''
    text = replace_once(text, old_loop, new_loop, label="host role and body cache")
    text = replace_once(
        text,
        '        scan_body = "\\n".join(scan_lines)\n',
        '        scan_body = "\\n".join(scan_lines)\n        scan_body_cf = scan_body.casefold()\n',
        label="host lowercase cache",
    )
    text = replace_once(
        text,
        '''        for idx, cond in enumerate(IF_RE.findall(scan_body)):\n            cond_s = " ".join(cond.split())\n''',
        '''        for idx, match in enumerate(IF_RE.finditer(scan_body)):\n            cond = match.group(1)\n            cond_s = " ".join(cond.split())\n''',
        label="host if finditer",
    )
    text = replace_once(
        text,
        '''                    "binding_time": "compile_time"\n                    if "constexpr" in scan_body[scan_body.find(cond) : scan_body.find(cond) + 40]\n                    else "runtime",\n''',
        '''                    "binding_time": "compile_time"\n                    if "constexpr" in match.group(0).split("(", 1)[0]\n                    else "runtime",\n''',
        label="host constexpr position",
    )
    text = text.replace('"workspace" in scan_body.lower()', '"workspace" in scan_body_cf')
    text = text.replace('"blockdim" in scan_body.lower()', '"blockdim" in scan_body_cf')
    text = text.replace('"block_dim" in scan_body.lower()', '"block_dim" in scan_body_cf')
    write(rel, text)


def patch_kernel() -> None:
    rel = "engines/understand-operator/uo/scripts/extract_kernel_subgraph.py"
    text = read(rel)
    text = replace_once(
        text,
        "import argparse\nimport re\n",
        "import argparse\nimport re\nfrom bisect import bisect_right\n",
        label="kernel imports",
    )
    text = replace_once(
        text,
        "    iter_function_definitions,\n    iter_function_defs,\n",
        "    iter_function_definitions,\n    iter_function_definitions_from_text,\n    iter_function_defs,\n",
        label="kernel from-text import",
    )
    helpers = '''\n\ndef _line_starts(text: str) -> list[int]:\n    starts = [0]\n    starts.extend(match.end() for match in re.finditer("\\n", text))\n    return starts\n\n\ndef _line_for(starts: list[int], pos: int) -> int:\n    return bisect_right(starts, max(0, pos))\n\n\ndef _read_source_files(paths: list[Path]) -> dict[Path, str]:\n    out: dict[Path, str] = {}\n    for path in dict.fromkeys(paths):\n        if not path.is_file():\n            continue\n        try:\n            out[path] = path.read_text(encoding="utf-8", errors="ignore")\n        except OSError:\n            continue\n    return out\n'''
    text = replace_once(
        text,
        "_DEFAULT_DERIVED_ROOTS = (\"constInfo\", \"commonConstInfo\", \"deterConstInfo\", \"runInfo\")\n",
        "_DEFAULT_DERIVED_ROOTS = (\"constInfo\", \"commonConstInfo\", \"deterConstInfo\", \"runInfo\")" + helpers + "\n",
        label="kernel line/source helpers",
    )
    old_kernel_files = '''    kernel_files = _kernel_files(repo_root, op_name, architecture, primary if primary else None, kernel_nodes)\n    if not kernel_files:\n'''
    new_kernel_files = '''    kernel_files = _kernel_files(repo_root, op_name, architecture, primary if primary else None, kernel_nodes)\n    domain_files = list(\n        dict.fromkeys(_enum_declaration_files(repo_root, op_name, architecture) + kernel_files)\n    )\n    source_texts = _read_source_files(domain_files)\n    if not kernel_files:\n'''
    text = replace_once(text, old_kernel_files, new_kernel_files, label="kernel source preload")
    text = replace_once(
        text,
        '''        tilingkey_space,\n        architecture,\n    )\n''',
        '''        tilingkey_space,\n        architecture,\n        source_texts=source_texts,\n    )\n''',
        label="kernel template source cache arg",
    )
    text = replace_once(
        text,
        '''    declared_domains = collect_declared_domains(\n        _enum_declaration_files(repo_root, op_name, architecture) + kernel_files\n    )\n''',
        '''    declared_domains = collect_declared_domains(\n        domain_files, text_by_path=source_texts\n    )\n''',
        label="kernel declared domain cache",
    )
    text = replace_once(
        text,
        '''    for path in kernel_files:\n        try:\n            seed_defines = merge_defines(\n                seed_defines,\n                valued_seed_defines(\n                    analyze_macros(path.read_text(encoding="utf-8", errors="ignore")).defines\n                ),\n            )\n        except OSError:\n            continue\n''',
        '''    for path in kernel_files:\n        source_text = source_texts.get(path, "")\n        if not source_text:\n            continue\n        seed_defines = merge_defines(\n            seed_defines, valued_seed_defines(analyze_macros(source_text).defines)\n        )\n''',
        label="kernel seed source cache",
    )
    text = replace_once(
        text,
        '''        text = path.read_text(encoding="utf-8", errors="ignore")\n        macro_info = analyze_macros(text, seed_defines=seed_defines, soft_undefined=soft_undefined)\n''',
        '''        text = source_texts.get(path, "")\n        if not text:\n            continue\n        text_line_starts = _line_starts(text)\n        macro_info = analyze_macros(text, seed_defines=seed_defines, soft_undefined=soft_undefined)\n''',
        label="kernel main source cache",
    )
    text = replace_once(
        text,
        '''        file_fns = iter_function_definitions(repo_root, rel, architecture=architecture)\n        all_functions.extend(file_fns)\n''',
        '''        file_fns = iter_function_definitions_from_text(\n            repo_root, rel, text, architecture=architecture\n        )\n        file_fn_starts = [fn.start_line for fn in file_fns]\n        all_functions.extend(file_fns)\n''',
        label="kernel parse from text",
    )
    text = text.replace('line = text.count("\\n", 0, match.start()) + 1', 'line = _line_for(text_line_starts, match.start())')
    text = replace_once(
        text,
        '''            scan = body[brace + 1 :] if brace >= 0 else body\n            base_line = fn.start_line + (body[: brace + 1].count("\\n") if brace >= 0 else 0)\n            owner_meta = _owner_meta(fn, extraction_unit_id)\n''',
        '''            scan = body[brace + 1 :] if brace >= 0 else body\n            scan_line_starts = _line_starts(scan)\n            base_line = fn.start_line + (body[: brace + 1].count("\\n") if brace >= 0 else 0)\n            owner_meta = _owner_meta(fn, extraction_unit_id)\n''',
        label="kernel function line index",
    )
    text = text.replace('line = base_line + scan.count("\\n", 0, match.start())', 'line = base_line + _line_for(scan_line_starts, match.start()) - 1')
    text = text.replace('_function_covering_line(file_fns, directive.line)', '_function_covering_line(file_fns, directive.line, file_fn_starts)')
    text = text.replace('_owning_type_at_line(file_fns, line, owning_type_default)', '_owning_type_at_line(file_fns, line, owning_type_default, file_fn_starts)')
    text = replace_once(
        text,
        '''def collect_declared_domains(files: list[Path]) -> list[DeclaredDomain]:\n    domains: list[DeclaredDomain] = []\n    seen: set[tuple[str, tuple[str, ...]]] = set()\n    for path in files:\n        if not path.is_file():\n            continue\n        text = path.read_text(encoding="utf-8", errors="ignore")\n        rel = path.as_posix()\n''',
        '''def collect_declared_domains(\n    files: list[Path], *, text_by_path: dict[Path, str] | None = None\n) -> list[DeclaredDomain]:\n    domains: list[DeclaredDomain] = []\n    seen: set[tuple[str, tuple[str, ...]]] = set()\n    cache = text_by_path or {}\n    for path in files:\n        if not path.is_file():\n            continue\n        text = cache.get(path)\n        if text is None:\n            text = path.read_text(encoding="utf-8", errors="ignore")\n        rel = path.as_posix()\n''',
        label="kernel declared domain signature",
    )
    text = text.replace('line = text.count("\\n", 0, match.start()) + 1', 'line = _line_for(_line_starts(text), match.start())')
    text = text.replace('line = text.count("\\n", 0, run[0].start()) + 1', 'line = _line_for(_line_starts(text), run[0].start())')
    text = replace_once(
        text,
        '''    tilingkey_space: dict[str, Any],\n    architecture: str,\n) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:\n''',
        '''    tilingkey_space: dict[str, Any],\n    architecture: str,\n    *,\n    source_texts: dict[Path, str] | None = None,\n) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:\n''',
        label="kernel template graph signature",
    )
    text = replace_once(
        text,
        '''    for path in kernel_files:\n        try:\n            text = path.read_text(encoding="utf-8", errors="ignore")\n        except OSError:\n            continue\n        rel = path.relative_to(repo_root).as_posix()\n''',
        '''    cached_sources = source_texts or {}\n    for path in kernel_files:\n        text = cached_sources.get(path)\n        if text is None:\n            try:\n                text = path.read_text(encoding="utf-8", errors="ignore")\n            except OSError:\n                continue\n        rel = path.relative_to(repo_root).as_posix()\n        text_line_starts = _line_starts(text)\n''',
        label="kernel template graph source cache",
    )
    text = text.replace('line = text.count("\\n", 0, match.start()) + 1', 'line = _line_for(text_line_starts, match.start())')
    old_cover = '''def _function_covering_line(fns: list[FunctionDefinition], line: int) -> FunctionDefinition | None:\n    best: FunctionDefinition | None = None\n    for fn in fns:\n        if fn.start_line <= line <= fn.end_line:\n            if best is None or fn.start_line >= best.start_line:\n                best = fn\n    return best\n\n\ndef _owning_type_at_line(fns: list[FunctionDefinition], line: int, default: str) -> str:\n    fn = _function_covering_line(fns, line)\n'''
    new_cover = '''def _function_covering_line(\n    fns: list[FunctionDefinition], line: int, starts: list[int] | None = None\n) -> FunctionDefinition | None:\n    if not fns:\n        return None\n    ordered_starts = starts if starts is not None else [fn.start_line for fn in fns]\n    idx = bisect_right(ordered_starts, line) - 1\n    while idx >= 0:\n        fn = fns[idx]\n        if fn.start_line <= line <= fn.end_line:\n            return fn\n        if fn.end_line < line:\n            break\n        idx -= 1\n    return None\n\n\ndef _owning_type_at_line(\n    fns: list[FunctionDefinition],\n    line: int,\n    default: str,\n    starts: list[int] | None = None,\n) -> str:\n    fn = _function_covering_line(fns, line, starts)\n'''
    text = replace_once(text, old_cover, new_cover, label="kernel interval lookup")
    write(rel, text)


def patch_proposal() -> None:
    rel = "engines/understand-operator/uo/scripts/propose_extract_plan.py"
    text = read(rel)
    text = replace_once(text, "import argparse\nimport re\n", "import argparse\nimport os\nimport re\n", label="proposal imports")
    old_limits = '''MAX_WRITERS = 40\nMAX_RECEIVERS = 40\nMAX_ALIASES = 60\nMAX_NON_SINK = 30\nMAX_EXTRA = 20\nMAX_ONE_HOP = 30\nMAX_SINK_SCAN_FILES = 12\nMAX_KERNEL_ALIAS_FILES = 80\n'''
    new_limits = '''def _env_limit(name: str, default: int, maximum: int = 5000) -> int:\n    try:\n        value = int(os.environ.get(name, str(default)))\n    except ValueError:\n        value = default\n    return max(1, min(maximum, value))\n\n\nMAX_WRITERS = _env_limit("UO_EXTRACT_MAX_WRITERS", 200)\nMAX_RECEIVERS = _env_limit("UO_EXTRACT_MAX_RECEIVERS", 200)\nMAX_ALIASES = _env_limit("UO_EXTRACT_MAX_ALIASES", 300)\nMAX_NON_SINK = _env_limit("UO_EXTRACT_MAX_NON_SINK", 120)\nMAX_EXTRA = _env_limit("UO_EXTRACT_MAX_EXTRA", 100)\nMAX_ONE_HOP = _env_limit("UO_EXTRACT_MAX_ONE_HOP", 240)\nMAX_SINK_SCAN_FILES = _env_limit("UO_EXTRACT_MAX_SINK_SCAN_FILES", 64)\nMAX_KERNEL_ALIAS_FILES = _env_limit("UO_EXTRACT_MAX_KERNEL_ALIAS_FILES", 320)\n'''
    text = replace_once(text, old_limits, new_limits, label="proposal configurable limits")
    text = replace_once(
        text,
        '                traced = client.bounded_trace(root, keep_names=keep or None, max_depth=4, max_nodes=40)\n',
        '                traced = client.bounded_trace(\n                    root, keep_names=keep or None,\n                    max_depth=_env_limit("UO_EXTRACT_TRACE_MAX_DEPTH", 6, 12),\n                    max_nodes=_env_limit("UO_EXTRACT_TRACE_MAX_NODES", 240),\n                )\n',
        label="proposal trace limits",
    )
    old_return = '''    writer_list = _top_scored(list(writers.values()), MAX_WRITERS)\n    receiver_list = _top_scored(list(receivers.values()), MAX_RECEIVERS)\n    alias_list = list(aliases.values())[:MAX_ALIASES]\n    return {\n        "version": 1,\n        "op_name": op_name,\n        "architecture": architecture,\n        "status": "candidates",\n        "ok": True,\n        "writer_candidates": writer_list,\n        "receiver_candidates": receiver_list,\n        "alias_candidates": alias_list,\n        "non_sink_root_candidates": non_sink[:MAX_NON_SINK],\n        "extra_entry_candidates": extra[:MAX_EXTRA],\n        "counts": {\n            "writers": len(writer_list),\n            "receivers": len(receiver_list),\n            "aliases": len(alias_list),\n            "non_sink_roots": min(len(non_sink), MAX_NON_SINK),\n            "extra_entries": min(len(extra), MAX_EXTRA),\n        },\n    }\n'''
    new_return = '''    raw_counts = {\n        "writers": len(writers),\n        "receivers": len(receivers),\n        "aliases": len(aliases),\n        "non_sink_roots": len(non_sink),\n        "extra_entries": len(extra),\n    }\n    limits = {\n        "writers": MAX_WRITERS,\n        "receivers": MAX_RECEIVERS,\n        "aliases": MAX_ALIASES,\n        "non_sink_roots": MAX_NON_SINK,\n        "extra_entries": MAX_EXTRA,\n    }\n    truncated = {name: raw_counts[name] - limit for name, limit in limits.items() if raw_counts[name] > limit}\n    writer_list = _top_scored(list(writers.values()), MAX_WRITERS)\n    receiver_list = _top_scored(list(receivers.values()), MAX_RECEIVERS)\n    alias_list = list(aliases.values())[:MAX_ALIASES]\n    return {\n        "version": 1,\n        "op_name": op_name,\n        "architecture": architecture,\n        "status": "blocked" if truncated else "candidates",\n        "ok": not bool(truncated),\n        "reason": "candidate_budget_exhausted" if truncated else "",\n        "writer_candidates": writer_list,\n        "receiver_candidates": receiver_list,\n        "alias_candidates": alias_list,\n        "non_sink_root_candidates": non_sink[:MAX_NON_SINK],\n        "extra_entry_candidates": extra[:MAX_EXTRA],\n        "counts": {\n            "writers": len(writer_list),\n            "receivers": len(receiver_list),\n            "aliases": len(alias_list),\n            "non_sink_roots": min(len(non_sink), MAX_NON_SINK),\n            "extra_entries": min(len(extra), MAX_EXTRA),\n        },\n        "raw_counts": raw_counts,\n        "candidate_limits": limits,\n        "truncated": truncated,\n        "recovery": (\n            "raise the matching UO_EXTRACT_MAX_* environment limit and rebuild; "\n            "candidate truncation is never treated as a complete FAG graph"\n            if truncated else ""\n        ),\n    }\n'''
    text = replace_once(text, old_return, new_return, label="proposal truncation diagnostics")
    write(rel, text)


def write_tests() -> None:
    rel = "engines/understand-operator/tests/test_fag_graph_identity_and_perf.py"
    content = '''from __future__ import annotations\n\nfrom pathlib import Path\n\nfrom uo.scripts.extract_host_subgraph import _chain_item_key, _writer_role_indexes\nfrom uo.scripts.function_body import (\n    CallSite,\n    FunctionDefinition,\n    iter_function_definitions,\n)\nfrom uo.scripts.function_call_graph import resolve_call_site\n\n\ndef _fn(name: str, cls: str, sig: str, stable_id: str) -> FunctionDefinition:\n    return FunctionDefinition(\n        name=name, qualified_name=f"{cls}::{name}", class_or_namespace=cls,\n        normalized_signature=sig, template_arity_or_signature="",\n        specialization_kind="none", file_path="op_kernel/test.cpp",\n        start_line=1, end_line=3, header_text=f"void {name}{sig}",\n        body_text=f"void {name}{sig} {{}}", source_hash="s", snippet_hash="h",\n        identity_key=f"IK_{stable_id}", stable_id=stable_id,\n    )\n\n\ndef test_host_writer_roles_preserve_same_name_identity() -> None:\n    normal = {\n        "name": "SetTilingData", "qualified_name": "NormalTiling::SetTilingData",\n        "class_or_namespace": "NormalTiling", "file_path": "normal.cpp",\n        "start_line": 10, "role": "tiling_writer",\n    }\n    varlen = {\n        "name": "SetTilingData", "qualified_name": "VarlenTiling::SetTilingData",\n        "class_or_namespace": "VarlenTiling", "file_path": "varlen.cpp",\n        "start_line": 20, "role": "workspace_writer",\n    }\n    by_identity, by_name, incomplete = _writer_role_indexes({"writers": [normal, varlen]})\n    assert by_identity[_chain_item_key(normal)] == "tiling_writer"\n    assert by_identity[_chain_item_key(varlen)] == "workspace_writer"\n    assert "settlingdata" not in by_name\n    assert not incomplete\n\n\ndef test_incomplete_duplicate_writer_fails_closed() -> None:\n    a = {"name": "SetTilingData", "role": "tiling_writer"}\n    b = {"name": "SetTilingData", "role": "workspace_writer"}\n    _by_identity, by_name, incomplete = _writer_role_indexes({"writers": [a, b]})\n    assert "settlingdata" not in by_name\n    assert "settlingdata" in incomplete\n\n\ndef test_unknown_object_receiver_keeps_cross_class_candidates() -> None:\n    caller = _fn("Run", "Driver", "()", "CALLER")\n    a = _fn("Process", "NormalKernel", "(int)", "A")\n    b = _fn("Process", "VarlenKernel", "(int)", "B")\n    site = CallSite(\n        caller_function_id=caller.stable_id, callee_name="Process",\n        callee_qualified_hint="obj->Process", call_expression="obj->Process",\n        file_path=caller.file_path, line=2, receiver_type_or_object="obj->",\n        template_args="", argument_count=1, ordinal_in_function=1, snippet_hash="x",\n    )\n    edge, _node, unresolved = resolve_call_site(\n        site, caller, by_name={"Process": [a, b]},\n        by_qn={a.qualified_name: [a], b.qualified_name: [b]},\n        by_id={a.stable_id: a, b.stable_id: b},\n    )\n    assert edge and edge["target_status"] == "candidate_set"\n    assert set(edge["candidate_ids"]) == {"A", "B"}\n    assert unresolved and unresolved["kind"] == "call_target_ambiguous"\n\n\ndef test_function_definition_cache_avoids_second_read(tmp_path: Path, monkeypatch) -> None:\n    source = tmp_path / "sample.cpp"\n    source.write_text("class A { public: void Run() { Helper(); } void Helper() {} };", encoding="utf-8")\n    reads = 0\n    original = Path.read_text\n\n    def counted(self: Path, *args, **kwargs):\n        nonlocal reads\n        if self == source:\n            reads += 1\n        return original(self, *args, **kwargs)\n\n    monkeypatch.setattr(Path, "read_text", counted)\n    first = iter_function_definitions(tmp_path, "sample.cpp", architecture="arch35")\n    second = iter_function_definitions(tmp_path, "sample.cpp", architecture="arch35")\n    assert first and second\n    assert reads == 1\n'''
    write(rel, content)


def main() -> None:
    patch_function_body()
    patch_function_call_graph()
    patch_host()
    patch_kernel()
    patch_proposal()
    write_tests()
    print("FAG graph refactor applied")


if __name__ == "__main__":
    main()
