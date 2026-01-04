"""
Semantic SQL Rewriter v2 (partial): token-aware infix desugaring.

This module is intentionally scoped for a safe v0 rollout:
- Rewrite only infix-style semantic operators (including multi-word phrases) in a token-aware way.
- Preserve `-- @ ...` hint comments in-place and apply them to the next semantic operator occurrence
  (comment removal is handled by the legacy rewriter during rollout).
- Never rewrite inside string literals or comments.
- Return a structured result so callers can fall back to the legacy regex-based rewriter.

Structural/scope-sensitive rewrites (VECTOR_SEARCH CTE injection, EMBED context injection,
GROUP BY MEANING, SEMANTIC JOIN, etc.) are intentionally left to the legacy rewriter for now.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Optional, List, Dict, Tuple


@dataclass
class RewriteResult:
    sql_out: str
    changed: bool
    applied: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class _Token:
    typ: str  # ws, ident, punct, string, comment_line, comment_block, other
    text: str


@dataclass
class _Annotation:
    prompt_prefix: str = ""
    threshold: Optional[float] = None


@dataclass(frozen=True)
class _InfixSpec:
    phrase_upper: str                 # e.g. "ALIGNS WITH"
    phrase_words_upper: Tuple[str, ...]
    symbol_chars: Tuple[str, ...]
    function_name: str                # e.g. "semantic_aligns"
    returns_upper: str                # e.g. "BOOLEAN"


def rewrite_semantic_sql_v2(sql: str) -> RewriteResult:
    """
    Token-aware infix desugaring pass.

    Returns:
        RewriteResult. If errors is non-empty, callers should fall back to legacy.
    """
    try:
        tokens = _tokenize(sql)
    except Exception as e:
        return RewriteResult(sql_out=sql, changed=False, errors=[f"tokenize_failed: {e}"])

    try:
        specs = _load_infix_specs()
    except Exception as e:
        return RewriteResult(sql_out=sql, changed=False, errors=[f"registry_failed: {e}"])

    out_tokens: List[_Token] = []
    applied: List[str] = []
    changed = False

    i = 0
    # v0 annotation model: apply `-- @ ...` hints to the next semantic rewrite we perform.
    # Keep comments in-place (do not relocate) and rely on the legacy rewriter to remove them.
    pending_annotation_prefix = ""
    pending_threshold: Optional[float] = None

    while i < len(tokens):
        tok = tokens[i]

        # Never rewrite within strings/comments.
        if tok.typ in ("string", "comment_line", "comment_block"):
            if tok.typ == "comment_line":
                ann = _parse_annotation(tok.text)
                if ann is not None:
                    if ann.prompt_prefix:
                        pending_annotation_prefix += ann.prompt_prefix
                    if ann.threshold is not None:
                        pending_threshold = ann.threshold
            out_tokens.append(tok)
            i += 1
            continue

        # 0) ORDER BY ... (NOT) RELEVANCE TO ... (clause-level rewrite)
        relevance_match = _find_order_by_relevance_match(tokens, i, pending_annotation_prefix)
        if relevance_match:
            (span_start, span_end, rewritten_sql, tag, consumed_prefix) = relevance_match
            if span_start > i:
                out_tokens.extend(tokens[i:span_start])

            out_tokens.append(_Token("other", rewritten_sql))
            applied.append(tag.replace(":used_annotation", ""))
            changed = True
            if consumed_prefix:
                pending_annotation_prefix = ""
            i = span_end
            continue

        # 1) ABOUT / NOT ABOUT (expression-level with optional threshold; default comparator)
        about_match = _find_about_match(tokens, i, pending_annotation_prefix, pending_threshold)
        if about_match:
            (span_start, span_end, rewritten_sql, tag, consumed_prefix, consumed_threshold) = about_match
            if span_start > i:
                out_tokens.extend(tokens[i:span_start])

            out_tokens.append(_Token("other", rewritten_sql))
            applied.append(tag)
            changed = True
            if consumed_prefix:
                pending_annotation_prefix = ""
            if consumed_threshold:
                pending_threshold = None
            i = span_end
            continue

        # Attempt to match any infix operator phrase at/after i (skipping leading whitespace).
        # v0 limitation: only rewrite patterns of form:
        #   <dotted_ident> <op phrase> <string|dotted_ident>
        match = _find_infix_match(tokens, i, specs)
        if not match:
            # No semantic rewrite at this position; if we buffered annotations, keep them for now.
            out_tokens.append(tok)
            i += 1
            continue

        (lhs_start, lhs_end, op_start, op_end, rhs_start, rhs_end, spec, not_present) = match

        # If we matched starting from whitespace (or other tokens) before the LHS,
        # preserve those tokens in the output before emitting the rewritten expression.
        if lhs_start > i:
            out_tokens.extend(tokens[i:lhs_start])

        lhs_text = _join_tokens(tokens[lhs_start:lhs_end])
        rhs_text = _join_tokens(tokens[rhs_start:rhs_end])

        rhs_text_injected = rhs_text
        consumed_annotation = False
        if pending_annotation_prefix and _is_string_literal_span(tokens[rhs_start:rhs_end]):
            rhs_text_injected = _inject_prefix_into_string_literal(rhs_text, pending_annotation_prefix)
            consumed_annotation = True

        call_expr = f"{spec.function_name}({lhs_text.strip()}, {rhs_text_injected.strip()})"
        rewritten = f"NOT {call_expr}" if not_present else call_expr

        out_tokens.append(_Token("other", rewritten))
        applied.append(f"infix:{spec.phrase_upper}->{spec.function_name}")
        changed = True

        if consumed_annotation:
            pending_annotation_prefix = ""

        # Skip original span
        i = rhs_end

    sql_out = "".join(t.text for t in out_tokens)
    return RewriteResult(sql_out=sql_out, changed=changed, applied=applied, errors=[])


def _tokenize(sql: str) -> List[_Token]:
    tokens: List[_Token] = []
    i = 0
    n = len(sql)

    def emit(typ: str, start: int, end: int) -> None:
        if end > start:
            tokens.append(_Token(typ, sql[start:end]))

    while i < n:
        ch = sql[i]

        # Line comment
        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            start = i
            i += 2
            while i < n and sql[i] != "\n":
                i += 1
            emit("comment_line", start, i)
            continue

        # Block comment
        if ch == "/" and i + 1 < n and sql[i + 1] == "*":
            start = i
            i += 2
            while i + 1 < n and not (sql[i] == "*" and sql[i + 1] == "/"):
                i += 1
            i = min(n, i + 2)
            emit("comment_block", start, i)
            continue

        # Single-quoted string
        if ch == "'":
            start = i
            i += 1
            while i < n:
                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":  # escaped ''
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            emit("string", start, i)
            continue

        # Double-quoted string / identifier
        if ch == '"':
            start = i
            i += 1
            while i < n:
                if sql[i] == '"':
                    if i + 1 < n and sql[i + 1] == '"':
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            emit("string", start, i)
            continue

        # Whitespace
        if ch.isspace():
            start = i
            i += 1
            while i < n and sql[i].isspace() and not (sql[i] == "-" and i + 1 < n and sql[i + 1] == "-"):
                i += 1
            emit("ws", start, i)
            continue

        # Identifiers (simple)
        if ch.isalpha() or ch == "_" or ch.isdigit():
            start = i
            i += 1
            while i < n and (sql[i].isalnum() or sql[i] == "_" or sql[i] == "$"):
                i += 1
            emit("ident", start, i)
            continue

        # Punctuation / operators
        emit("punct", i, i + 1)
        i += 1

    return tokens


def _parse_annotation(comment_text: str) -> Optional[_Annotation]:
    """
    Parse a single `-- @ ...` comment line.

    v0: support a prompt prefix (free-form, prompt:, model:) and a threshold override.

    Non-prompt keys like parallel/batch_size are intentionally ignored here so they can
    be handled by the legacy rewriter (e.g. UNION ALL splitting).
    """
    stripped = comment_text.strip()
    if not stripped.startswith("-- @"):
        return None

    content = stripped[4:].strip()
    if not content:
        return _Annotation(prompt_prefix="")

    if ":" in content and not content.startswith("http"):
        key, _, value = content.partition(":")
        key = key.strip().lower()
        value = value.strip()

        if key in ("parallel", "batch_size", "parallel_scope"):
            return _Annotation(prompt_prefix="")

        if key == "threshold":
            try:
                return _Annotation(prompt_prefix="", threshold=float(value))
            except ValueError:
                return _Annotation(prompt_prefix="")

        if key == "model" and value:
            return _Annotation(prompt_prefix=f"Use {value} - ")

        if key == "prompt" and value:
            return _Annotation(prompt_prefix=f"{value} - ")

        # Unknown key or natural language with colon: treat as prompt text.
        if value:
            return _Annotation(prompt_prefix=f"{content} - ")
        return _Annotation(prompt_prefix="")

    # Default: treat as prompt text
    return _Annotation(prompt_prefix=f"{content} - ")


def _load_infix_specs() -> List[_InfixSpec]:
    """
    Load infix operator phrase specs from the SQL function cascade registry.

    v0: only operators that look like infix patterns with a phrase between }} and {{.
    Excludes clause-level operators that require context-sensitive handling in v0:
      - RELEVANCE TO
    """
    from rvbbit.semantic_sql.registry import get_sql_function_registry

    registry = get_sql_function_registry()
    specs: Dict[str, _InfixSpec] = {}

    for fn_name, entry in registry.items():
        for operator_pattern in getattr(entry, "operators", []) or []:
            phrase = _extract_infix_phrase(operator_pattern)
            if not phrase:
                continue

            phrase_upper = phrase.upper()
            returns_upper = str(getattr(entry, "returns", "") or "").upper()

            # Exclude clause-level patterns that require structural/context-sensitive handling.
            # These are handled by legacy rewriter's special-case code.
            # Note: ABOUT/NOT ABOUT are now handled here (token-aware) to prevent
            # legacy regex from matching inside string literals (e.g., in LLM_CASE conditions).
            if phrase_upper in ("RELEVANCE TO", "NOT RELEVANCE TO", "SEMANTIC JOIN", "SEMANTIC DISTINCT"):
                continue

            is_word_phrase = re.fullmatch(r"[A-Z_]+(?:\s+[A-Z_]+)*", phrase_upper) is not None
            words = tuple(phrase_upper.split()) if is_word_phrase else tuple()
            symbol_chars = tuple(ch for ch in phrase if not ch.isspace()) if not words else tuple()
            specs_key = phrase_upper
            if specs_key not in specs:
                specs[specs_key] = _InfixSpec(
                    phrase_upper=phrase_upper,
                    phrase_words_upper=words,
                    symbol_chars=symbol_chars,
                    function_name=str(fn_name),
                    returns_upper=returns_upper,
                )

    # Sort by phrase length (multi-word first)
    return sorted(specs.values(), key=lambda s: (len(s.phrase_words_upper), len(s.symbol_chars)), reverse=True)


def _extract_infix_phrase(operator_pattern: str) -> Optional[str]:
    """
    Extract the infix operator phrase between the first }} and the next {{ or quote.
    """
    if "}}" not in operator_pattern:
        return None
    after = operator_pattern.split("}}", 1)[1].lstrip()
    if not after:
        return None

    stop_candidates = []
    for stop in ("{{", "'", '"', "(", ")", ","):
        idx = after.find(stop)
        if idx != -1:
            stop_candidates.append(idx)
    end = min(stop_candidates) if stop_candidates else len(after)

    segment = after[:end].strip()
    if not segment:
        return None

    # Normalize whitespace
    segment = " ".join(segment.split())
    return segment


def _find_order_by_relevance_match(
    tokens: List[_Token],
    start: int,
    annotation_prefix: str,
) -> Optional[Tuple[int, int, str, str, bool]]:
    """
    Match and rewrite:
      ORDER BY <dotted_ident> RELEVANCE TO <string> [ASC|DESC]
      ORDER BY <dotted_ident> NOT RELEVANCE TO <string> [ASC|DESC]

    v0 limitations:
    - expression must be a dotted identifier
    - criterion must be a string literal
    """
    # Skip whitespace
    i = start
    while i < len(tokens) and tokens[i].typ == "ws":
        i += 1
    if i >= len(tokens):
        return None

    if tokens[i].typ != "ident" or tokens[i].text.upper() != "ORDER":
        return None

    j = i + 1
    while j < len(tokens) and tokens[j].typ == "ws":
        j += 1
    if j >= len(tokens) or tokens[j].typ != "ident" or tokens[j].text.upper() != "BY":
        return None

    k = j + 1
    while k < len(tokens) and tokens[k].typ == "ws":
        k += 1

    expr_span = _parse_dotted_ident_span(tokens, k)
    if not expr_span:
        return None
    expr_start, expr_end = expr_span

    m = expr_end
    while m < len(tokens) and tokens[m].typ == "ws":
        m += 1

    # Optional NOT
    not_present = False
    if m < len(tokens) and tokens[m].typ == "ident" and tokens[m].text.upper() == "NOT":
        not_present = True
        m += 1
        while m < len(tokens) and tokens[m].typ == "ws":
            m += 1

    phrase_span = _match_phrase(tokens, m, ("RELEVANCE", "TO"))
    if not phrase_span:
        return None
    phrase_start, phrase_end = phrase_span

    n = phrase_end
    while n < len(tokens) and tokens[n].typ == "ws":
        n += 1

    rhs_span = _parse_rhs_span(tokens, n)
    if not rhs_span:
        return None
    rhs_start, rhs_end = rhs_span
    if not _is_string_literal_span(tokens[rhs_start:rhs_end]):
        return None

    rhs_text = _join_tokens(tokens[rhs_start:rhs_end]).strip()
    consumed_prefix = False
    if annotation_prefix:
        rhs_text = _inject_prefix_into_string_literal(rhs_text, annotation_prefix)
        consumed_prefix = True

    # Optional direction (parse via a scan cursor, but do not consume trailing whitespace).
    scan = rhs_end
    while scan < len(tokens) and tokens[scan].typ == "ws":
        scan += 1

    direction = None
    end = rhs_end
    if scan < len(tokens) and tokens[scan].typ == "ident" and tokens[scan].text.upper() in ("ASC", "DESC"):
        direction = tokens[scan].text.upper()
        end = scan + 1

    # Defaults match legacy behavior: RELEVANCE TO -> DESC, NOT RELEVANCE TO -> ASC
    if direction is None:
        direction = "ASC" if not_present else "DESC"

    expr_text = _join_tokens(tokens[expr_start:expr_end]).strip()
    rewritten = f"ORDER BY semantic_score({expr_text}, {rhs_text}) {direction}"
    tag = "order_by:NOT RELEVANCE TO->semantic_score" if not_present else "order_by:RELEVANCE TO->semantic_score"
    return (i, end, rewritten, tag, consumed_prefix)


def _find_about_match(
    tokens: List[_Token],
    start: int,
    annotation_prefix: str,
    threshold_override: Optional[float],
):
    """
    Match and rewrite:
      <lhs> ABOUT <string> [<cmp> <number>]
      <lhs> NOT ABOUT <string> [<cmp> <number>]

    Defaults:
      ABOUT -> > 0.5
      NOT ABOUT -> <= 0.5
    """
    i = start
    while i < len(tokens) and tokens[i].typ == "ws":
        i += 1
    if i >= len(tokens):
        return None

    lhs_span = _parse_dotted_ident_span(tokens, i)
    if not lhs_span:
        return None
    lhs_start, lhs_end = lhs_span

    j = lhs_end
    while j < len(tokens) and tokens[j].typ == "ws":
        j += 1

    not_present = False
    if j < len(tokens) and tokens[j].typ == "ident" and tokens[j].text.upper() == "NOT":
        not_present = True
        j += 1
        while j < len(tokens) and tokens[j].typ == "ws":
            j += 1

    if j >= len(tokens) or tokens[j].typ != "ident" or tokens[j].text.upper() != "ABOUT":
        return None

    about_tok_idx = j
    j += 1

    while j < len(tokens) and tokens[j].typ == "ws":
        j += 1

    rhs_span = _parse_rhs_span(tokens, j)
    if not rhs_span:
        return None
    rhs_start, rhs_end = rhs_span
    if not _is_string_literal_span(tokens[rhs_start:rhs_end]):
        return None

    rhs_text = _join_tokens(tokens[rhs_start:rhs_end])
    consumed_prefix = False
    if annotation_prefix and _is_string_literal_span(tokens[rhs_start:rhs_end]):
        rhs_text = _inject_prefix_into_string_literal(rhs_text, annotation_prefix)
        consumed_prefix = True

    # Optional comparator + threshold
    scan = rhs_end
    while scan < len(tokens) and tokens[scan].typ == "ws":
        scan += 1

    cmp_span = _parse_comparator(tokens, scan)
    threshold_span = None
    if cmp_span:
        cmp_start, cmp_end = cmp_span
        t = cmp_end
        while t < len(tokens) and tokens[t].typ == "ws":
            t += 1
        threshold_span = _parse_numberish_span(tokens, t)
        if threshold_span:
            end = threshold_span[1]
        else:
            # Comparator without threshold: treat as no comparator.
            cmp_span = None
            end = rhs_end
    else:
        end = rhs_end

    lhs_text = _join_tokens(tokens[lhs_start:lhs_end]).strip()
    fn_name = "semantic_score"
    score_expr = f"{fn_name}({lhs_text}, {rhs_text.strip()})"

    if cmp_span and threshold_span:
        cmp_text = _join_tokens(tokens[cmp_span[0]:cmp_span[1]]).strip()
        threshold_text = _join_tokens(tokens[threshold_span[0]:threshold_span[1]]).strip()

        # Invert comparator for NOT ABOUT for > and < only (match legacy behavior).
        if not_present:
            if cmp_text == ">":
                cmp_text = "<="
            elif cmp_text == "<":
                cmp_text = ">="
        rewritten = f"{score_expr} {cmp_text} {threshold_text}"
        consumed_threshold = False
    else:
        # Default comparator
        default_threshold = threshold_override if threshold_override is not None else 0.5
        rewritten = f"{score_expr} {'<=' if not_present else '>'} {default_threshold}"
        consumed_threshold = threshold_override is not None

    tag = "infix:NOT ABOUT->semantic_score" if not_present else "infix:ABOUT->semantic_score"
    return (lhs_start, end, rewritten, tag, consumed_prefix, consumed_threshold)


def _parse_comparator(tokens: List[_Token], start: int) -> Optional[Tuple[int, int]]:
    if start >= len(tokens):
        return None
    tok = tokens[start]
    if tok.typ != "punct":
        return None
    if tok.text not in ("<", ">", "=", "!"):
        return None

    end = start + 1
    # Support <=, >=, !=
    if end < len(tokens) and tokens[end].typ == "punct" and tokens[end].text == "=":
        end += 1
    return (start, end)


def _parse_numberish_span(tokens: List[_Token], start: int) -> Optional[Tuple[int, int]]:
    """
    Parse a numeric-ish span such as 0.7, 10, 1e-3 in a tokenization-tolerant way.
    """
    if start >= len(tokens):
        return None

    i = start
    # Accept an ident/punct sequence until we hit a boundary.
    seen_any = False
    while i < len(tokens):
        t = tokens[i]
        if t.typ == "ident":
            seen_any = True
            i += 1
            continue
        if t.typ == "punct" and t.text in (".", "+", "-"):
            seen_any = True
            i += 1
            continue
        break

    return (start, i) if seen_any else None


def _find_infix_match(tokens: List[_Token], start: int, specs: List[_InfixSpec]):
    # Skip whitespace and comments/strings at the matching cursor.
    i = start
    while i < len(tokens) and tokens[i].typ in ("ws",):
        i += 1
    if i >= len(tokens):
        return None

    # v0: LHS must end at i if i is within lhs span, so only attempt when cursor is at lhs start.
    lhs_span = _parse_dotted_ident_span(tokens, i)
    if not lhs_span:
        return None

    lhs_start, lhs_end = lhs_span
    j = lhs_end

    # Skip whitespace
    while j < len(tokens) and tokens[j].typ == "ws":
        j += 1

    # Optional infix NOT (e.g. "col NOT MEANS 'x'") for boolean-returning operators.
    not_present = False
    if j < len(tokens) and tokens[j].typ == "ident" and tokens[j].text.upper() == "NOT":
        not_present = True
        j += 1
        while j < len(tokens) and tokens[j].typ == "ws":
            j += 1

    for spec in specs:
        if spec.phrase_words_upper:
            op_span = _match_phrase(tokens, j, spec.phrase_words_upper)
            if not op_span:
                continue
        elif spec.symbol_chars:
            op_span = _match_symbol(tokens, j, spec.symbol_chars)
            if not op_span:
                # Synthetic negation for symbol operators: "!<op>" becomes NOT <op>.
                if not_present:
                    continue
                op_span = _match_bang_symbol(tokens, j, spec.symbol_chars)
                if not op_span:
                    continue
                not_present = True
        else:
            continue

        op_start, op_end = op_span

        if not_present and spec.returns_upper != "BOOLEAN":
            continue

        k = op_end
        while k < len(tokens) and tokens[k].typ == "ws":
            k += 1

        rhs_span = _parse_rhs_span(tokens, k)
        if not rhs_span:
            continue

        rhs_start, rhs_end = rhs_span

        return (lhs_start, lhs_end, op_start, op_end, rhs_start, rhs_end, spec, not_present)

    return None


def _match_phrase(tokens: List[_Token], start: int, phrase_words_upper: Tuple[str, ...]) -> Optional[Tuple[int, int]]:
    """
    Match a phrase like ("ALIGNS","WITH") across IDENT tokens with optional whitespace.
    Returns (op_start, op_end).
    """
    i = start
    if i >= len(tokens):
        return None

    op_start = i
    for word in phrase_words_upper:
        # Skip whitespace
        while i < len(tokens) and tokens[i].typ == "ws":
            i += 1
        if i >= len(tokens):
            return None
        tok = tokens[i]
        if tok.typ != "ident" or tok.text.upper() != word:
            return None
        i += 1

    op_end = i
    return (op_start, op_end)

def _match_symbol(tokens: List[_Token], start: int, symbol_chars: Tuple[str, ...]) -> Optional[Tuple[int, int]]:
    """
    Match a symbol operator across PUNCT tokens with optional whitespace.
    Example: ("!","~") can match "!~" (with optional spaces).
    """
    i = start
    op_start = i
    for ch in symbol_chars:
        while i < len(tokens) and tokens[i].typ == "ws":
            i += 1
        if i >= len(tokens) or tokens[i].typ != "punct" or tokens[i].text != ch:
            return None
        i += 1
    return (op_start, i)


def _match_bang_symbol(tokens: List[_Token], start: int, symbol_chars: Tuple[str, ...]) -> Optional[Tuple[int, int]]:
    """
    Match a synthetic negated symbol operator: "!" + <symbol>.
    This allows "!~" to work even if only "~" is defined in the registry.
    """
    i = start
    while i < len(tokens) and tokens[i].typ == "ws":
        i += 1
    if i >= len(tokens) or tokens[i].typ != "punct" or tokens[i].text != "!":
        return None
    bang_idx = i
    i += 1
    rest = _match_symbol(tokens, i, symbol_chars)
    if not rest:
        return None
    return (bang_idx, rest[1])

def _parse_dotted_ident_span(tokens: List[_Token], start: int) -> Optional[Tuple[int, int]]:
    """
    Parse a dotted identifier span: ident(.ident)*.
    """
    if start >= len(tokens) or tokens[start].typ != "ident":
        return None

    i = start + 1
    while i + 1 < len(tokens):
        if tokens[i].typ == "punct" and tokens[i].text == "." and tokens[i + 1].typ == "ident":
            i += 2
            continue
        break

    return (start, i)


def _parse_rhs_span(tokens: List[_Token], start: int) -> Optional[Tuple[int, int]]:
    """
    RHS can be a string literal token or dotted identifier span.
    """
    if start >= len(tokens):
        return None

    tok = tokens[start]
    if tok.typ == "string":
        return (start, start + 1)

    return _parse_dotted_ident_span(tokens, start)


def _join_tokens(tokens: List[_Token]) -> str:
    return "".join(t.text for t in tokens)


def _is_string_literal_span(tokens: List[_Token]) -> bool:
    return len(tokens) == 1 and tokens[0].typ == "string"


def _inject_prefix_into_string_literal(literal: str, prefix: str) -> str:
    """
    Inject a prefix into a SQL string literal. Supports single-quoted and double-quoted tokens.
    v0: treat both as string-like and keep the original quote.
    """
    lit = literal.strip()
    if len(lit) < 2:
        return literal

    quote = lit[0]
    if quote not in ("'", '"') or lit[-1] != quote:
        return literal

    inner = lit[1:-1]
    # Escape single quotes by doubling for single-quoted literals.
    injected = prefix + inner
    if quote == "'":
        injected = injected.replace("'", "''")
    else:
        injected = injected.replace('"', '""')

    return f"{quote}{injected}{quote}"
