"""
SQL Inspector for Semantic SQL / RVBBIT SQL.

Purpose
-------
Provide a pure (no-execution) inspection pass that finds "interesting" spans
inside a SQL string so a UI can highlight / drill into semantic cascades and
LLM calls without being smart about SQL.

Key requirements:
- Works on raw user SQL (pre-rewrite), so returned offsets match the original.
- Uses the dynamic cascade registry so new semantic SQL functions/operators
  become highlightable automatically.
- Never parses/executess SQL; no network, no LLM calls.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List, Optional, Tuple
import re


def inspect_sql_query(sql: str) -> Dict[str, Any]:
    """
    Inspect a SQL query and return highlightable spans + metadata.

    Returns:
        {
          "sql": "...",
          "calls": [
             {
               "start": 12, "end": 34,
               "line": 1, "col": 13,
               "kind": "semantic_infix" | "semantic_function" | "llm_aggregate" | "llm_case",
               "display": "MEANS" | "semantic_matches" | "SUMMARIZE" | "LLM_CASE",
               "operator": "MEANS" | "ABOUT" | ...,
               "function": "semantic_matches" | "semantic_sentiment" | ...,
               "shape": "SCALAR" | "AGGREGATE" | "TABLE" | null,
               "returns": "BOOLEAN" | "DOUBLE" | ... | null,
               "cascade_id": "...",
               "cascade_path": "...",
               "annotation": { ... } | null,
             }
          ],
          "annotations": [
             { "start": ..., "end": ..., "line_start": ..., "line_end": ..., "prompt": ..., ... }
          ],
          "errors": []
        }
    """
    if not isinstance(sql, str):
        raise TypeError("sql must be a string")

    sql_text = sql
    newline_positions = _compute_newline_positions(sql_text)

    registry, alias_to_canonical, canonical_meta = _load_registry_metadata()

    annotations = _parse_semantic_annotations_safe(sql_text)

    calls: List[Dict[str, Any]] = []
    errors: List[str] = []

    # --- Structural semantic SQL constructs (best-effort, token-aware) ---
    try:
        from rvbbit.sql_tools import semantic_rewriter_v2 as v2

        tokens = v2._tokenize(sql_text)
        token_starts = _token_start_offsets(tokens)
        for start, end, structural_kind in _scan_structural_constructs(tokens, token_starts):
            line, col = _line_col_from_offset(newline_positions, start)
            calls.append(
                {
                    "start": start,
                    "end": end,
                    "line": line,
                    "col": col,
                    "kind": "structural",
                    "display": structural_kind,
                    "operator": structural_kind,
                    "function": None,
                    "shape": None,
                    "returns": None,
                    "cascade_id": None,
                    "cascade_path": None,
                    "annotation": None,
                }
            )
    except Exception as e:
        errors.append(f"structural_scan_failed:{e}")

    # --- LLM_CASE blocks (regex-based; best-effort) ---
    try:
        for start, end in _find_llm_case_blocks(sql_text):
            line, col = _line_col_from_offset(newline_positions, start)
            calls.append(
                {
                    "start": start,
                    "end": end,
                    "line": line,
                    "col": col,
                    "kind": "llm_case",
                    "display": "LLM_CASE",
                    "operator": "LLM_CASE",
                    "function": None,
                    "shape": None,
                    "returns": None,
                    "cascade_id": None,
                    "cascade_path": None,
                    "annotation": None,
                }
            )
    except Exception as e:
        errors.append(f"llm_case_scan_failed:{e}")

    # --- Token-aware scanning for semantic operators/function calls ---
    try:
        from rvbbit.sql_tools import semantic_rewriter_v2 as v2
        from rvbbit.sql_tools.llm_agg_rewriter import has_llm_aggregates, _find_llm_agg_calls
        from rvbbit.sql_tools.llm_agg_rewriter import LLM_AGG_ALIASES, LLM_AGG_FUNCTIONS

        tokens = v2._tokenize(sql_text)
        token_starts = _token_start_offsets(tokens)

        # Precompute: attach annotations by line number (same rule as semantic_operators)
        annotations_by_target_line = _index_annotations_by_target_line(annotations)

        # 1) Infix operators (dynamic registry-driven via v2 specs)
        pending_annotation_prefix = ""
        pending_threshold = None
        i = 0
        specs = v2._load_infix_specs()

        while i < len(tokens):
            tok = tokens[i]

            if tok.typ in ("string", "comment_line", "comment_block"):
                # v2-style: only line comments carry `-- @` hints
                if tok.typ == "comment_line":
                    ann = v2._parse_annotation(tok.text)
                    if ann is not None:
                        if ann.prompt_prefix:
                            pending_annotation_prefix += ann.prompt_prefix
                        if ann.threshold is not None:
                            pending_threshold = ann.threshold
                i += 1
                continue

            relevance_match = v2._find_order_by_relevance_match(tokens, i, "")
            if relevance_match:
                span_start_tok, span_end_tok, _rewritten, tag, _consumed_prefix = relevance_match
                start = token_starts[span_start_tok]
                end = token_starts[span_end_tok] if span_end_tok < len(token_starts) else len(sql_text)
                line, col = _line_col_from_offset(newline_positions, start)
                operator = "NOT RELEVANCE TO" if "NOT RELEVANCE TO" in tag else "RELEVANCE TO"
                function = "semantic_score"
                meta = canonical_meta.get(function.lower())
                calls.append(
                    _make_call_dict(
                        start=start,
                        end=end,
                        line=line,
                        col=col,
                        kind="semantic_infix",
                        display=operator,
                        operator=operator,
                        function=function,
                        meta=meta,
                        annotation=_annotation_for_line(annotations_by_target_line, line),
                    )
                )
                i = span_end_tok
                continue

            about_match = v2._find_about_match(tokens, i, "", pending_threshold)
            if about_match:
                span_start_tok, span_end_tok, _rewritten, tag, _consumed_prefix, consumed_threshold = about_match
                start = token_starts[span_start_tok]
                end = token_starts[span_end_tok] if span_end_tok < len(token_starts) else len(sql_text)
                line, col = _line_col_from_offset(newline_positions, start)
                operator = "NOT ABOUT" if "NOT ABOUT" in tag else "ABOUT"
                function = "semantic_score"
                meta = canonical_meta.get(function.lower())
                calls.append(
                    _make_call_dict(
                        start=start,
                        end=end,
                        line=line,
                        col=col,
                        kind="semantic_infix",
                        display=operator,
                        operator=operator,
                        function=function,
                        meta=meta,
                        annotation=_annotation_for_line(annotations_by_target_line, line),
                    )
                )
                if consumed_threshold:
                    pending_threshold = None
                i = span_end_tok
                continue

            infix_match = v2._find_infix_match(tokens, i, specs)
            if infix_match:
                lhs_start, _lhs_end, _op_start, _op_end, _rhs_start, rhs_end, spec, not_present = infix_match
                start = token_starts[lhs_start]
                end = token_starts[rhs_end] if rhs_end < len(token_starts) else len(sql_text)
                line, col = _line_col_from_offset(newline_positions, start)
                operator = f"NOT {spec.phrase_upper}" if not_present else spec.phrase_upper
                function = spec.function_name
                meta = canonical_meta.get(str(function).lower())
                calls.append(
                    _make_call_dict(
                        start=start,
                        end=end,
                        line=line,
                        col=col,
                        kind="semantic_infix",
                        display=operator,
                        operator=operator,
                        function=function,
                        meta=meta,
                        annotation=_annotation_for_line(annotations_by_target_line, line),
                    )
                )
                i = rhs_end
                pending_annotation_prefix = ""  # if present, v2 would consume only when it injects; for UI, clear after any semantic op.
                continue

            i += 1

        # 2) Function calls (semantic_* and aliases) + LLM aggregate sugar calls
        func_calls = _scan_function_calls(tokens, token_starts)
        llm_aliases_upper = {k.upper() for k in LLM_AGG_ALIASES.keys()}
        llm_canon_upper = {k.upper() for k in LLM_AGG_FUNCTIONS.keys()}

        for fn_name, start, end in func_calls:
            fn_upper = fn_name.upper()

            # Skip if this is within a span already captured (avoid noisy duplicates)
            if any(start >= c["start"] and end <= c["end"] for c in calls):
                continue

            # LLM aggregates (SUMMARIZE, THEMES, etc.) are best highlighted as "llm_aggregate"
            if fn_upper in llm_aliases_upper or fn_upper in llm_canon_upper:
                line, col = _line_col_from_offset(newline_positions, start)
                calls.append(
                    {
                        "start": start,
                        "end": end,
                        "line": line,
                        "col": col,
                        "kind": "llm_aggregate",
                        "display": fn_name,
                        "operator": fn_name,
                        "function": None,
                        "shape": "AGGREGATE",
                        "returns": None,
                        "cascade_id": None,
                        "cascade_path": None,
                        "annotation": None,
                    }
                )
                continue

            # Registry-based semantic function calls / aliases
            canonical = alias_to_canonical.get(fn_upper.lower()) or alias_to_canonical.get(fn_name.lower())
            if canonical:
                meta = canonical_meta.get(str(canonical).lower())
                line, col = _line_col_from_offset(newline_positions, start)
                calls.append(
                    _make_call_dict(
                        start=start,
                        end=end,
                        line=line,
                        col=col,
                        kind="semantic_function",
                        display=fn_name,
                        operator=None,
                        function=canonical,
                        meta=meta,
                        annotation=_annotation_for_line(annotations_by_target_line, line),
                    )
                )

        # 3) LLM aggregate call spans (more accurate than a simple function scan)
        # This keeps parity with the actual aggregate rewrite pipeline.
        if has_llm_aggregates(sql_text):
            for start_pos, end_pos, canonical_name, _args in _find_llm_agg_calls(sql_text):
                line, col = _line_col_from_offset(newline_positions, start_pos)
                calls.append(
                    {
                        "start": start_pos,
                        "end": end_pos,
                        "line": line,
                        "col": col,
                        "kind": "llm_aggregate",
                        "display": canonical_name,
                        "operator": canonical_name,
                        "function": None,
                        "shape": "AGGREGATE",
                        "returns": None,
                        "cascade_id": None,
                        "cascade_path": None,
                        "annotation": None,
                    }
                )

    except Exception as e:
        errors.append(f"token_scan_failed:{e}")

    # Normalize: sort by start offset and de-dupe exact duplicates
    calls = _dedupe_calls(sorted(calls, key=lambda x: (x["start"], x["end"], x["kind"])))

    return {
        "sql": sql_text,
        "calls": calls,
        "annotations": [a for a in annotations],
        "registry_functions": sorted(registry) if registry else [],
        "errors": errors,
    }


def _compute_newline_positions(s: str) -> List[int]:
    return [i for i, ch in enumerate(s) if ch == "\n"]


def _line_col_from_offset(newlines: List[int], offset: int) -> Tuple[int, int]:
    # 1-based line/col
    if not newlines:
        return 1, offset + 1
    lo, hi = 0, len(newlines)
    while lo < hi:
        mid = (lo + hi) // 2
        if newlines[mid] < offset:
            lo = mid + 1
        else:
            hi = mid
    line = lo + 1
    line_start = 0 if lo == 0 else newlines[lo - 1] + 1
    col = offset - line_start + 1
    return line, col


def _parse_semantic_annotations_safe(sql: str) -> List[Dict[str, Any]]:
    try:
        from rvbbit.sql_tools.semantic_operators import _parse_annotations as _parse
        parsed = _parse(sql)
        out: List[Dict[str, Any]] = []
        for _end_line, _end_pos, ann in parsed:
            d = asdict(ann)
            out.append(d)
        return out
    except Exception:
        return []


def _index_annotations_by_target_line(ann_dicts: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    # semantic_operators rule: annotation applies to the next line (end_line == target_line)
    by_line: Dict[int, Dict[str, Any]] = {}
    for a in ann_dicts:
        line_end = a.get("line_end")
        if isinstance(line_end, int):
            by_line[line_end + 1] = a
    return by_line


def _annotation_for_line(by_line: Dict[int, Dict[str, Any]], line_1_based: int) -> Optional[Dict[str, Any]]:
    return by_line.get(line_1_based)


def _load_registry_metadata() -> Tuple[List[str], Dict[str, str], Dict[str, Dict[str, Any]]]:
    registry_names: List[str] = []
    alias_to_canonical: Dict[str, str] = {}
    canonical_meta: Dict[str, Dict[str, Any]] = {}

    try:
        from rvbbit.semantic_sql.registry import initialize_registry, get_sql_function_registry
        initialize_registry(force=False)
        reg = get_sql_function_registry()
    except Exception:
        reg = {}

    for fn_name, entry in (reg or {}).items():
        canonical = str(fn_name)
        registry_names.append(canonical)

        fn_lower = canonical.lower()
        alias_to_canonical[fn_lower] = canonical
        if fn_lower.startswith("semantic_"):
            alias_to_canonical[fn_lower.replace("semantic_", "", 1)] = canonical

        for op in getattr(entry, "operators", []) or []:
            m = re.match(r"^([A-Z_]+)\s*\(", str(op))
            if m:
                alias_to_canonical[m.group(1).lower()] = canonical

        canonical_meta[fn_lower] = {
            "function": canonical,
            "cascade_id": getattr(entry, "cascade_id", None),
            "cascade_path": getattr(entry, "cascade_path", None),
            "shape": getattr(entry, "shape", None),
            "returns": getattr(entry, "returns", None),
        }

    return registry_names, alias_to_canonical, canonical_meta


def _token_start_offsets(tokens: List[Any]) -> List[int]:
    offsets: List[int] = []
    pos = 0
    for t in tokens:
        offsets.append(pos)
        pos += len(getattr(t, "text", ""))
    offsets.append(pos)
    return offsets


def _scan_function_calls(tokens: List[Any], token_starts: List[int]) -> List[Tuple[str, int, int]]:
    """
    Find IDENT( ... ) function-like spans in token stream.
    Returns (function_name, start_offset, end_offset).
    """
    out: List[Tuple[str, int, int]] = []

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.typ in ("string", "comment_line", "comment_block"):
            i += 1
            continue

        if tok.typ == "ident":
            fn_name = tok.text
            j = i + 1
            while j < len(tokens) and tokens[j].typ == "ws":
                j += 1
            if j < len(tokens) and tokens[j].typ == "punct" and tokens[j].text == "(":
                # Find matching closing paren
                depth = 0
                k = j
                while k < len(tokens):
                    t = tokens[k]
                    if t.typ in ("string", "comment_line", "comment_block"):
                        k += 1
                        continue
                    if t.typ == "punct" and t.text == "(":
                        depth += 1
                    elif t.typ == "punct" and t.text == ")":
                        depth -= 1
                        if depth == 0:
                            start = token_starts[i]
                            end = token_starts[k + 1] if (k + 1) < len(token_starts) else token_starts[-1]
                            out.append((fn_name, start, end))
                            i = k + 1
                            break
                    k += 1
        i += 1

    return out


def _scan_structural_constructs(tokens: List[Any], token_starts: List[int]) -> List[Tuple[int, int, str]]:
    """
    Find structural Semantic SQL constructs that are not simple infix/function calls.

    Best-effort highlights:
      - SEMANTIC JOIN
      - SEMANTIC DISTINCT
      - GROUP BY MEANING
      - GROUP BY TOPICS
    """
    out: List[Tuple[int, int, str]] = []

    def is_ident(idx: int, word_upper: str) -> bool:
        if idx < 0 or idx >= len(tokens):
            return False
        t = tokens[idx]
        return t.typ == "ident" and t.text.upper() == word_upper

    def skip_ws(idx: int) -> int:
        while idx < len(tokens) and tokens[idx].typ == "ws":
            idx += 1
        return idx

    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t.typ in ("string", "comment_line", "comment_block"):
            i += 1
            continue

        # SEMANTIC JOIN / SEMANTIC DISTINCT
        if t.typ == "ident" and t.text.upper() == "SEMANTIC":
            j = skip_ws(i + 1)
            if is_ident(j, "JOIN"):
                start = token_starts[i]
                end = token_starts[j + 1] if (j + 1) < len(token_starts) else token_starts[-1]
                out.append((start, end, "SEMANTIC JOIN"))
                i = j + 1
                continue
            if is_ident(j, "DISTINCT"):
                start = token_starts[i]
                end = token_starts[j + 1] if (j + 1) < len(token_starts) else token_starts[-1]
                out.append((start, end, "SEMANTIC DISTINCT"))
                i = j + 1
                continue

        # GROUP BY MEANING / GROUP BY TOPICS
        if t.typ == "ident" and t.text.upper() == "GROUP":
            j = skip_ws(i + 1)
            if not is_ident(j, "BY"):
                i += 1
                continue
            k = skip_ws(j + 1)
            if is_ident(k, "MEANING"):
                start = token_starts[i]
                end = token_starts[k + 1] if (k + 1) < len(token_starts) else token_starts[-1]
                out.append((start, end, "GROUP BY MEANING"))
                i = k + 1
                continue
            if is_ident(k, "TOPICS"):
                start = token_starts[i]
                end = token_starts[k + 1] if (k + 1) < len(token_starts) else token_starts[-1]
                out.append((start, end, "GROUP BY TOPICS"))
                i = k + 1
                continue

        i += 1

    return out


def _find_llm_case_blocks(sql: str) -> List[Tuple[int, int]]:
    """
    Best-effort: find spans from LLM_CASE to matching END.
    Avoid matching inside string literals by first stripping them.
    """
    # Replace string literal contents with placeholders but keep length stable.
    def _mask_strings(s: str) -> str:
        s = re.sub(r"\'(?:\'\'|[^'])*\'", lambda m: "'" + (" " * (len(m.group(0)) - 2)) + "'", s)
        s = re.sub(r"\"(?:\"\"|[^\"])*\"", lambda m: '"' + (" " * (len(m.group(0)) - 2)) + '"', s)
        return s

    masked = _mask_strings(sql)
    spans: List[Tuple[int, int]] = []
    for m in re.finditer(r"\bLLM_CASE\b", masked, flags=re.IGNORECASE):
        start = m.start()
        end_m = re.search(r"\bEND\b", masked[m.end():], flags=re.IGNORECASE)
        if not end_m:
            continue
        end = m.end() + end_m.end()
        spans.append((start, end))
    return spans


def _make_call_dict(
    *,
    start: int,
    end: int,
    line: int,
    col: int,
    kind: str,
    display: str,
    operator: Optional[str],
    function: Optional[str],
    meta: Optional[Dict[str, Any]],
    annotation: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    out = {
        "start": start,
        "end": end,
        "line": line,
        "col": col,
        "kind": kind,
        "display": display,
        "operator": operator,
        "function": function,
        "shape": None,
        "returns": None,
        "cascade_id": None,
        "cascade_path": None,
        "annotation": annotation,
    }
    if meta:
        out["shape"] = meta.get("shape")
        out["returns"] = meta.get("returns")
        out["cascade_id"] = meta.get("cascade_id")
        out["cascade_path"] = meta.get("cascade_path")
    return out


def _dedupe_calls(calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for c in calls:
        key = (c.get("start"), c.get("end"), c.get("kind"), c.get("function"), c.get("operator"), c.get("display"))
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out
