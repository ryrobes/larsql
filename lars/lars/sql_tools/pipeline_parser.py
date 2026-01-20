"""
Pipeline Parser: Token-aware parsing of THEN/INTO syntax for post-query processing.

This module parses SQL queries with pipeline syntax:
    SELECT * FROM products
    WHERE category = 'electronics'
    THEN ANALYZE 'what are the trends?'
    THEN SPEAK
    INTO quarterly_analysis;

Per-stage INTO for intermediate materialization:
    SELECT * FROM sales INTO base_data
    THEN FILTER('above average') INTO filtered_data
    THEN ANALYZE 'summarize' INTO final_analysis;

The parser is designed to:
- Never match THEN/INTO inside strings or comments
- Support both infix (`THEN STAGE 'arg'`) and function (`THEN STAGE('arg')`) styles
- Extract the base SQL, pipeline stages, and optional INTO tables (per-stage or final)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, List
import re


@dataclass
class PipelineStage:
    """A single pipeline stage to execute."""
    name: str                    # e.g., "ANALYZE"
    args: List[str]              # Arguments (strings from 'arg' or function args)
    original_text: str           # For error messages
    into_table: Optional[str] = None  # Optional per-stage INTO table
    stage_type: str = "standard"  # "standard" | "choose"


@dataclass
class ChooseBranch:
    """A single branch in a CHOOSE statement."""
    condition: str              # e.g., "fraud", "suspicious"
    cascade_name: str           # e.g., "QUARANTINE", "FLAG"
    cascade_args: List[str]     # e.g., ["fraud_review"]
    is_else: bool = False       # True for ELSE branch


@dataclass
class ChooseStage(PipelineStage):
    """A CHOOSE stage with conditional routing."""
    discriminator: Optional[str] = None  # e.g., "FRAUD_DETECTOR" or None for generic
    branches: List[ChooseBranch] = None  # type: ignore

    def __post_init__(self):
        if self.branches is None:
            self.branches = []
        self.stage_type = "choose"


@dataclass
class ParsedPipeline:
    """Result of parsing a query with pipeline syntax."""
    base_sql: str                # SQL before first THEN
    stages: List[PipelineStage]  # Pipeline stages in order
    into_table: Optional[str]    # Final INTO table (after last stage) - DEPRECATED, use stage.into_table
    base_into_table: Optional[str] = None  # INTO table for base SQL (before first THEN)


@dataclass(frozen=True)
class _Token:
    """A token from SQL tokenization."""
    typ: str  # ws, ident, punct, string, comment_line, comment_block, other
    text: str


def _tokenize(sql: str) -> List[_Token]:
    """
    Tokenize SQL into safe units for parsing.

    Reuses the tokenizer pattern from semantic_rewriter_v2.py to ensure
    consistent handling of strings, comments, and identifiers.
    """
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
            while i < n and sql[i].isspace():
                i += 1
            emit("ws", start, i)
            continue

        # Identifiers
        if ch.isalpha() or ch == "_":
            start = i
            i += 1
            while i < n and (sql[i].isalnum() or sql[i] == "_" or sql[i] == "$"):
                i += 1
            emit("ident", start, i)
            continue

        # Numbers (for completeness)
        if ch.isdigit():
            start = i
            i += 1
            while i < n and (sql[i].isdigit() or sql[i] == '.'):
                i += 1
            emit("number", start, i)
            continue

        # Punctuation / operators
        emit("punct", i, i + 1)
        i += 1

    return tokens


def has_pipeline_syntax(sql: str) -> bool:
    """
    Quick check for THEN keyword at statement level (not inside CASE expressions).

    Used as a fast-path to avoid full parsing when no pipeline syntax is present.
    Returns True if the query might have pipeline syntax (needs full parse).

    IMPORTANT: Must distinguish between:
    - LARS pipeline: SELECT * FROM t THEN DEDUPE INTO result
    - SQL CASE: SELECT CASE WHEN x THEN y ELSE z END FROM t

    In CASE expressions, THEN always follows WHEN (possibly with expressions between).
    In LARS pipelines, THEN follows a complete statement or closing paren.
    """
    # Quick regex check first
    if not re.search(r'\bTHEN\b', sql, re.IGNORECASE):
        return False

    # Tokenize to confirm THEN is at statement level and not part of CASE..WHEN..THEN
    tokens = _tokenize(sql)

    # Track CASE/WHEN depth to identify CASE expression THEN vs pipeline THEN
    case_depth = 0

    for i, tok in enumerate(tokens):
        if tok.typ == "ident":
            upper = tok.text.upper()
            if upper == "CASE":
                case_depth += 1
            elif upper == "END" and case_depth > 0:
                case_depth -= 1
            elif upper == "THEN":
                # THEN inside a CASE expression is SQL, not pipeline
                if case_depth > 0:
                    continue
                # THEN outside CASE is pipeline syntax
                return True

    return False


def parse_pipeline_syntax(sql: str) -> Optional[ParsedPipeline]:
    """
    Parse THEN/INTO syntax from SQL query.

    Returns None if no pipeline syntax is found.
    Returns ParsedPipeline with base SQL, stages, and optional INTO tables.

    Syntax patterns:
        THEN STAGE 'arg'          - Infix style with string arg
        THEN STAGE('arg', 'arg2') - Function style with multiple args
        THEN STAGE                - No args
        INTO table_name           - Save result to table (per-stage or final)

    Per-stage INTO:
        SELECT * FROM t INTO base
        THEN FILTER('x') INTO filtered
        THEN ANALYZE 'y' INTO final;
    """
    tokens = _tokenize(sql)

    # Find first THEN at statement level
    first_then_idx = None
    paren_depth = 0

    for i, tok in enumerate(tokens):
        if tok.typ == "punct":
            if tok.text == "(":
                paren_depth += 1
            elif tok.text == ")":
                paren_depth -= 1
        elif tok.typ == "ident" and tok.text.upper() == "THEN" and paren_depth == 0:
            first_then_idx = i
            break

    if first_then_idx is None:
        return None

    # Check for INTO between base SQL and first THEN
    # Look backwards from first_then_idx to find INTO
    base_into_table: Optional[str] = None
    base_end_idx = first_then_idx

    # Scan tokens before THEN for INTO pattern
    j = first_then_idx - 1
    while j >= 0 and tokens[j].typ == "ws":
        j -= 1

    # Check if we have: ... INTO table_name [ws] THEN
    if j >= 1 and tokens[j].typ == "ident":
        # Could be table_name
        potential_table = tokens[j].text
        k = j - 1
        while k >= 0 and tokens[k].typ == "ws":
            k -= 1
        if k >= 0 and tokens[k].typ == "ident" and tokens[k].text.upper() == "INTO":
            # Found INTO table_name before THEN
            base_into_table = potential_table
            base_end_idx = k  # End base SQL before INTO

    # Extract base SQL (everything before INTO or THEN)
    base_sql = "".join(t.text for t in tokens[:base_end_idx]).strip()

    # Remove trailing semicolon from base SQL if present
    if base_sql.endswith(";"):
        base_sql = base_sql[:-1].strip()

    # Parse stages from THEN markers
    stages: List[PipelineStage] = []
    final_into_table: Optional[str] = None  # Legacy: INTO after all stages

    i = first_then_idx
    while i < len(tokens):
        tok = tokens[i]

        # Skip whitespace
        if tok.typ == "ws":
            i += 1
            continue

        # Handle standalone INTO (after all stages, for backwards compat)
        if tok.typ == "ident" and tok.text.upper() == "INTO":
            # Find the table name
            i += 1
            while i < len(tokens) and tokens[i].typ == "ws":
                i += 1
            if i < len(tokens) and tokens[i].typ == "ident":
                table_name = tokens[i].text
                # If we have stages, attach to last stage; otherwise it's final
                if stages:
                    stages[-1] = PipelineStage(
                        name=stages[-1].name,
                        args=stages[-1].args,
                        original_text=stages[-1].original_text,
                        into_table=table_name
                    )
                else:
                    final_into_table = table_name
            break

        # Handle THEN
        if tok.typ == "ident" and tok.text.upper() == "THEN":
            i += 1

            # Skip whitespace
            while i < len(tokens) and tokens[i].typ == "ws":
                i += 1

            if i >= len(tokens):
                break

            # Get stage name (should be an identifier)
            if tokens[i].typ != "ident":
                i += 1
                continue

            stage_name = tokens[i].text.upper()
            stage_original = tokens[i].text
            i += 1

            # Special handling for CHOOSE stage
            if stage_name == "CHOOSE":
                choose_stage, i = _parse_choose_stage(tokens, i, stage_original)

                # Check for INTO after CHOOSE block
                while i < len(tokens) and tokens[i].typ == "ws":
                    i += 1
                if i < len(tokens) and tokens[i].typ == "ident" and tokens[i].text.upper() == "INTO":
                    i += 1
                    while i < len(tokens) and tokens[i].typ == "ws":
                        i += 1
                    if i < len(tokens) and tokens[i].typ == "ident":
                        choose_stage.into_table = tokens[i].text
                        i += 1

                stages.append(choose_stage)
                continue

            # Skip whitespace
            while i < len(tokens) and tokens[i].typ == "ws":
                i += 1

            # Check for arguments
            args: List[str] = []

            if i < len(tokens):
                next_tok = tokens[i]

                # Function style: STAGE('arg1', 'arg2')
                if next_tok.typ == "punct" and next_tok.text == "(":
                    i += 1  # Skip (
                    paren_depth = 1

                    while i < len(tokens) and paren_depth > 0:
                        tok = tokens[i]
                        if tok.typ == "punct":
                            if tok.text == "(":
                                paren_depth += 1
                            elif tok.text == ")":
                                paren_depth -= 1
                                if paren_depth == 0:
                                    i += 1
                                    break
                            elif tok.text == "," and paren_depth == 1:
                                i += 1
                                continue
                        elif tok.typ == "string":
                            # Extract string content (remove quotes)
                            arg_text = tok.text
                            if arg_text.startswith("'") and arg_text.endswith("'"):
                                arg_text = arg_text[1:-1].replace("''", "'")
                            elif arg_text.startswith('"') and arg_text.endswith('"'):
                                arg_text = arg_text[1:-1].replace('""', '"')
                            args.append(arg_text)
                        elif tok.typ == "number":
                            # Numeric argument (e.g., SAMPLE(3), TOP('sales', 5))
                            args.append(tok.text)
                        elif tok.typ == "ident":
                            # Identifier argument (e.g., column names without quotes)
                            args.append(tok.text)
                        i += 1

                # Infix style: STAGE 'arg'
                elif next_tok.typ == "string":
                    arg_text = next_tok.text
                    if arg_text.startswith("'") and arg_text.endswith("'"):
                        arg_text = arg_text[1:-1].replace("''", "'")
                    elif arg_text.startswith('"') and arg_text.endswith('"'):
                        arg_text = arg_text[1:-1].replace('""', '"')
                    args.append(arg_text)
                    i += 1

            # Skip whitespace after args
            while i < len(tokens) and tokens[i].typ == "ws":
                i += 1

            # Check for INTO after this stage's args
            stage_into_table: Optional[str] = None
            if i < len(tokens) and tokens[i].typ == "ident" and tokens[i].text.upper() == "INTO":
                i += 1  # Skip INTO
                while i < len(tokens) and tokens[i].typ == "ws":
                    i += 1
                if i < len(tokens) and tokens[i].typ == "ident":
                    stage_into_table = tokens[i].text
                    i += 1

            stages.append(PipelineStage(
                name=stage_name,
                args=args,
                original_text=stage_original,
                into_table=stage_into_table
            ))
            continue

        # Handle semicolon (end of statement)
        if tok.typ == "punct" and tok.text == ";":
            break

        i += 1

    if not stages:
        return None

    # For backwards compatibility, also set into_table to last stage's into_table
    final_into = final_into_table or (stages[-1].into_table if stages else None)

    return ParsedPipeline(
        base_sql=base_sql,
        stages=stages,
        into_table=final_into,
        base_into_table=base_into_table
    )


def _extract_string_value(token_text: str) -> str:
    """Extract string value from quoted token."""
    if token_text.startswith("'") and token_text.endswith("'"):
        return token_text[1:-1].replace("''", "'")
    if token_text.startswith('"') and token_text.endswith('"'):
        return token_text[1:-1].replace('""', '"')
    return token_text


def _parse_when_branch(tokens: List[_Token], start_idx: int) -> tuple:
    """
    Parse: WHEN 'condition' THEN CASCADE 'args'

    Returns:
        Tuple of (ChooseBranch, end_index)
    """
    i = start_idx

    # Skip whitespace
    while i < len(tokens) and tokens[i].typ == "ws":
        i += 1

    # Get condition (string)
    if i >= len(tokens) or tokens[i].typ != "string":
        raise ValueError("WHEN requires a condition string")
    condition = _extract_string_value(tokens[i].text)
    i += 1

    # Skip whitespace
    while i < len(tokens) and tokens[i].typ == "ws":
        i += 1

    # Expect THEN
    if i >= len(tokens) or tokens[i].typ != "ident" or tokens[i].text.upper() != "THEN":
        raise ValueError("WHEN requires THEN keyword")
    i += 1

    # Skip whitespace
    while i < len(tokens) and tokens[i].typ == "ws":
        i += 1

    # Get cascade name
    if i >= len(tokens) or tokens[i].typ != "ident":
        raise ValueError("WHEN THEN requires a cascade name")
    cascade_name = tokens[i].text.upper()
    i += 1

    # Parse optional args (string or function-style)
    cascade_args: List[str] = []
    while i < len(tokens) and tokens[i].typ == "ws":
        i += 1

    if i < len(tokens):
        # Function-style args: CASCADE('arg1', 'arg2')
        if tokens[i].typ == "punct" and tokens[i].text == "(":
            i += 1  # Skip (
            paren_depth = 1

            while i < len(tokens) and paren_depth > 0:
                tok = tokens[i]
                if tok.typ == "punct":
                    if tok.text == "(":
                        paren_depth += 1
                    elif tok.text == ")":
                        paren_depth -= 1
                        if paren_depth == 0:
                            i += 1
                            break
                    elif tok.text == "," and paren_depth == 1:
                        i += 1
                        continue
                elif tok.typ == "string":
                    cascade_args.append(_extract_string_value(tok.text))
                elif tok.typ == "number":
                    cascade_args.append(tok.text)
                elif tok.typ == "ident":
                    cascade_args.append(tok.text)
                i += 1

        # Infix-style arg: CASCADE 'arg'
        elif tokens[i].typ == "string":
            cascade_args.append(_extract_string_value(tokens[i].text))
            i += 1

    branch = ChooseBranch(
        condition=condition,
        cascade_name=cascade_name,
        cascade_args=cascade_args,
        is_else=False
    )
    return branch, i


def _parse_else_branch(tokens: List[_Token], start_idx: int) -> tuple:
    """
    Parse: ELSE CASCADE 'args'

    Returns:
        Tuple of (ChooseBranch, end_index)
    """
    i = start_idx

    # Skip whitespace
    while i < len(tokens) and tokens[i].typ == "ws":
        i += 1

    # Get cascade name
    if i >= len(tokens) or tokens[i].typ != "ident":
        raise ValueError("ELSE requires a cascade name")
    cascade_name = tokens[i].text.upper()
    i += 1

    # Parse optional args
    cascade_args: List[str] = []
    while i < len(tokens) and tokens[i].typ == "ws":
        i += 1

    if i < len(tokens):
        # Function-style args
        if tokens[i].typ == "punct" and tokens[i].text == "(":
            i += 1
            paren_depth = 1
            while i < len(tokens) and paren_depth > 0:
                tok = tokens[i]
                if tok.typ == "punct":
                    if tok.text == "(":
                        paren_depth += 1
                    elif tok.text == ")":
                        paren_depth -= 1
                        if paren_depth == 0:
                            i += 1
                            break
                    elif tok.text == "," and paren_depth == 1:
                        i += 1
                        continue
                elif tok.typ == "string":
                    cascade_args.append(_extract_string_value(tok.text))
                elif tok.typ == "number":
                    cascade_args.append(tok.text)
                elif tok.typ == "ident":
                    cascade_args.append(tok.text)
                i += 1

        # Infix-style arg
        elif tokens[i].typ == "string":
            cascade_args.append(_extract_string_value(tokens[i].text))
            i += 1

    branch = ChooseBranch(
        condition="",  # ELSE has no condition
        cascade_name=cascade_name,
        cascade_args=cascade_args,
        is_else=True
    )
    return branch, i


def _parse_choose_stage(
    tokens: List[_Token],
    start_idx: int,
    original_text: str
) -> tuple:
    """
    Parse CHOOSE [BY discriminator] (WHEN ... THEN ... [ELSE ...])

    Syntax:
        CHOOSE BY FRAUD_DETECTOR (
            WHEN 'fraud' THEN QUARANTINE 'review'
            WHEN 'suspicious' THEN FLAG 'uncertain'
            ELSE PASS
        )

        CHOOSE (
            WHEN 'positive' THEN CELEBRATE
            WHEN 'negative' THEN ESCALATE
        )

    Returns:
        Tuple of (ChooseStage, end_index)
    """
    i = start_idx
    discriminator: Optional[str] = None
    branches: List[ChooseBranch] = []

    # Skip whitespace
    while i < len(tokens) and tokens[i].typ == "ws":
        i += 1

    # Check for BY keyword
    if i < len(tokens) and tokens[i].typ == "ident" and tokens[i].text.upper() == "BY":
        i += 1
        # Skip whitespace
        while i < len(tokens) and tokens[i].typ == "ws":
            i += 1
        # Get discriminator name
        if i < len(tokens) and tokens[i].typ == "ident":
            discriminator = tokens[i].text.upper()
            i += 1

    # Skip whitespace
    while i < len(tokens) and tokens[i].typ == "ws":
        i += 1

    # Expect opening paren
    if i >= len(tokens) or tokens[i].text != "(":
        raise ValueError("CHOOSE requires (...) block with WHEN clauses")
    i += 1

    # Parse WHEN/ELSE branches until closing paren
    while i < len(tokens):
        # Skip whitespace
        while i < len(tokens) and tokens[i].typ == "ws":
            i += 1

        if i >= len(tokens):
            break

        tok = tokens[i]

        # Closing paren - done
        if tok.typ == "punct" and tok.text == ")":
            i += 1
            break

        # WHEN branch
        if tok.typ == "ident" and tok.text.upper() == "WHEN":
            i += 1
            branch, i = _parse_when_branch(tokens, i)
            branches.append(branch)
            continue

        # ELSE branch
        if tok.typ == "ident" and tok.text.upper() == "ELSE":
            i += 1
            branch, i = _parse_else_branch(tokens, i)
            branches.append(branch)
            continue

        # Skip unknown tokens (shouldn't happen in well-formed SQL)
        i += 1

    if not branches:
        raise ValueError("CHOOSE requires at least one WHEN or ELSE branch")

    stage = ChooseStage(
        name="CHOOSE",
        args=[],
        original_text=original_text,
        into_table=None,
        stage_type="choose",
        discriminator=discriminator,
        branches=branches
    )
    return stage, i


def reconstruct_pipeline_sql(pipeline: ParsedPipeline) -> str:
    """
    Reconstruct the original SQL from a parsed pipeline.

    Useful for debugging and error messages.
    """
    parts = [pipeline.base_sql]

    for stage in pipeline.stages:
        if stage.args:
            args_str = ", ".join(f"'{arg}'" for arg in stage.args)
            parts.append(f"THEN {stage.name}({args_str})")
        else:
            parts.append(f"THEN {stage.name}")

    if pipeline.into_table:
        parts.append(f"INTO {pipeline.into_table}")

    return " ".join(parts) + ";"


# ============================================================================
# CTE Pipeline Preprocessing
# ============================================================================

@dataclass
class CTEDefinition:
    """A parsed CTE definition."""
    name: str           # CTE name
    body: str           # CTE body (the query inside AS (...))
    start_pos: int      # Position in original SQL where CTE name starts
    end_pos: int        # Position in original SQL after closing paren
    has_pipeline: bool  # True if body contains THEN at statement level


def _find_cte_with_pipeline(sql: str) -> List[CTEDefinition]:
    """
    Find CTEs that contain THEN pipeline syntax.

    Parses the WITH clause to find CTEs whose body contains THEN at the
    CTE's internal statement level (not inside nested subqueries).

    Args:
        sql: Full SQL query with potential WITH clause

    Returns:
        List of CTEDefinition for CTEs that have pipeline syntax
    """
    tokens = _tokenize(sql)
    ctes: List[CTEDefinition] = []

    i = 0
    n = len(tokens)

    # Skip leading whitespace
    while i < n and tokens[i].typ == "ws":
        i += 1

    # Check for WITH keyword
    if i >= n or tokens[i].typ != "ident" or tokens[i].text.upper() != "WITH":
        return []

    i += 1  # Skip WITH

    # Skip RECURSIVE if present
    while i < n and tokens[i].typ == "ws":
        i += 1
    if i < n and tokens[i].typ == "ident" and tokens[i].text.upper() == "RECURSIVE":
        i += 1

    # Parse CTE definitions
    while i < n:
        # Skip whitespace
        while i < n and tokens[i].typ == "ws":
            i += 1

        if i >= n:
            break

        # Check if we've hit the main query (SELECT, INSERT, etc.)
        if tokens[i].typ == "ident" and tokens[i].text.upper() in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            break

        # Get CTE name
        if tokens[i].typ != "ident":
            break

        cte_name = tokens[i].text
        cte_start = sum(len(t.text) for t in tokens[:i])
        i += 1

        # Skip whitespace
        while i < n and tokens[i].typ == "ws":
            i += 1

        # Skip optional column list AS (col1, col2, ...)
        # Look for AS keyword
        if i >= n or tokens[i].typ != "ident" or tokens[i].text.upper() != "AS":
            break
        i += 1  # Skip AS

        # Skip whitespace
        while i < n and tokens[i].typ == "ws":
            i += 1

        # Find opening paren
        if i >= n or tokens[i].typ != "punct" or tokens[i].text != "(":
            break

        body_start_idx = i + 1
        i += 1  # Skip (

        # Find matching closing paren, tracking depth
        paren_depth = 1
        while i < n and paren_depth > 0:
            if tokens[i].typ == "punct":
                if tokens[i].text == "(":
                    paren_depth += 1
                elif tokens[i].text == ")":
                    paren_depth -= 1
            i += 1

        body_end_idx = i - 1  # Points to closing paren
        cte_end = sum(len(t.text) for t in tokens[:i])

        # Extract body tokens (between parens)
        body_tokens = tokens[body_start_idx:body_end_idx]
        body_text = "".join(t.text for t in body_tokens)

        # Check if body has THEN at statement level (not in CASE or nested subquery)
        has_pipeline = _cte_body_has_pipeline(body_tokens)

        if has_pipeline:
            ctes.append(CTEDefinition(
                name=cte_name,
                body=body_text,
                start_pos=cte_start,
                end_pos=cte_end,
                has_pipeline=True
            ))

        # Skip whitespace
        while i < n and tokens[i].typ == "ws":
            i += 1

        # Check for comma (more CTEs) or end of WITH clause
        if i < n and tokens[i].typ == "punct" and tokens[i].text == ",":
            i += 1  # Skip comma, continue to next CTE
        else:
            break  # End of WITH clause

    return ctes


def _cte_body_has_pipeline(tokens: List[_Token]) -> bool:
    """
    Check if CTE body contains THEN at statement level.

    Distinguishes between:
    - LARS pipeline: SELECT * FROM t THEN DEDUPE
    - SQL CASE: SELECT CASE WHEN x THEN y END FROM t

    Returns True only for LARS pipeline THEN.
    """
    case_depth = 0
    paren_depth = 0

    for tok in tokens:
        if tok.typ == "punct":
            if tok.text == "(":
                paren_depth += 1
            elif tok.text == ")":
                paren_depth -= 1
        elif tok.typ == "ident":
            upper = tok.text.upper()
            if upper == "CASE":
                case_depth += 1
            elif upper == "END" and case_depth > 0:
                case_depth -= 1
            elif upper == "THEN":
                # THEN inside CASE or nested subquery is not a pipeline
                if case_depth == 0 and paren_depth == 0:
                    return True

    return False


def preprocess_cte_pipelines(
    sql: str,
    duckdb_conn,
    session_id: str,
    caller_id: Optional[str] = None,
) -> str:
    """
    Preprocess CTEs containing THEN pipeline syntax.

    For each CTE with pipeline syntax:
    1. Parse the CTE body to extract base SQL and pipeline stages
    2. Include all preceding CTEs (for dependency resolution)
    3. Execute the base SQL to get initial DataFrame
    4. Execute pipeline stages on the DataFrame
    5. Replace CTE body with SELECT from VALUES containing the result

    Args:
        sql: Full SQL query with potential CTE pipelines
        duckdb_conn: DuckDB connection for executing queries
        session_id: Session ID for cascade execution
        caller_id: Optional caller ID for tracking

    Returns:
        SQL with CTE pipelines materialized
    """
    import logging
    import pandas as pd

    log = logging.getLogger(__name__)

    # Find CTEs with pipeline syntax
    pipeline_ctes = _find_cte_with_pipeline(sql)

    if not pipeline_ctes:
        return sql

    log.info(f"[pipeline] Found {len(pipeline_ctes)} CTE(s) with pipeline syntax")

    # Parse ALL CTEs to build dependency graph
    all_ctes = _parse_all_ctes(sql)

    # Process pipeline CTEs (in order, updating sql as we go)
    result = sql

    for pipeline_cte in pipeline_ctes:
        log.info(f"[pipeline] Processing CTE '{pipeline_cte.name}' with pipeline syntax")

        # Parse the CTE body as a pipeline query
        pipeline = parse_pipeline_syntax(pipeline_cte.body)

        if not pipeline or not pipeline.stages:
            log.warning(f"[pipeline] CTE '{pipeline_cte.name}' body didn't parse as pipeline")
            continue

        try:
            # Execute the pipeline using existing infrastructure
            from ..sql_rewriter import rewrite_lars_syntax
            from .pipeline_executor import execute_pipeline_stages

            # Build a query that includes all preceding CTEs as context
            # This ensures the base SQL can reference other CTEs
            preceding_ctes = _get_preceding_ctes(all_ctes, pipeline_cte.name, result)
            base_sql = pipeline.base_sql

            if preceding_ctes:
                # Wrap base SQL with WITH clause containing preceding CTEs
                base_sql = f"WITH {preceding_ctes} {base_sql}"

            # Rewrite base SQL (handles dimension functions, semantic operators, etc.)
            base_sql = rewrite_lars_syntax(base_sql, duckdb_conn=duckdb_conn)

            log.info(f"[pipeline] CTE '{pipeline_cte.name}' base SQL: {base_sql[:100]}...")

            # Execute base query
            base_result = duckdb_conn.execute(base_sql)
            columns = [desc[0] for desc in base_result.description]
            rows = base_result.fetchall()
            initial_df = pd.DataFrame(rows, columns=columns)

            log.info(f"[pipeline] CTE '{pipeline_cte.name}' base returned {len(initial_df)} rows")

            # Execute pipeline stages
            final_df = execute_pipeline_stages(
                stages=pipeline.stages,
                initial_df=initial_df,
                session_id=f"{session_id}_cte_{pipeline_cte.name}",
                caller_id=caller_id,
                original_query=pipeline_cte.body,
            )

            log.info(f"[pipeline] CTE '{pipeline_cte.name}' pipeline returned {len(final_df)} rows, {len(final_df.columns)} columns")

            # Generate replacement CTE body
            replacement_body = _dataframe_to_cte_body(final_df)

            # Replace the CTE definition in the SQL
            result = _replace_cte_body(result, pipeline_cte.name, replacement_body)

            # Also update all_ctes to reflect the change for subsequent iterations
            for i, cte_info in enumerate(all_ctes):
                if cte_info[0] == pipeline_cte.name:
                    all_ctes[i] = (cte_info[0], replacement_body)
                    break

            log.info(f"[pipeline] CTE '{pipeline_cte.name}' replaced with materialized result")

        except Exception as e:
            log.error(f"[pipeline] Failed to execute CTE '{pipeline_cte.name}' pipeline: {e}")
            raise

    return result


def _parse_all_ctes(sql: str) -> List[tuple]:
    """
    Parse all CTEs from a SQL query (including those without pipelines).

    Returns list of (name, body) tuples in order of definition.
    """
    tokens = _tokenize(sql)
    ctes: List[tuple] = []

    i = 0
    n = len(tokens)

    # Skip leading whitespace
    while i < n and tokens[i].typ == "ws":
        i += 1

    # Check for WITH keyword
    if i >= n or tokens[i].typ != "ident" or tokens[i].text.upper() != "WITH":
        return []

    i += 1  # Skip WITH

    # Skip RECURSIVE if present
    while i < n and tokens[i].typ == "ws":
        i += 1
    if i < n and tokens[i].typ == "ident" and tokens[i].text.upper() == "RECURSIVE":
        i += 1

    # Parse CTE definitions
    while i < n:
        # Skip whitespace
        while i < n and tokens[i].typ == "ws":
            i += 1

        if i >= n:
            break

        # Check if we've hit the main query (SELECT, INSERT, etc.)
        if tokens[i].typ == "ident" and tokens[i].text.upper() in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            break

        # Get CTE name
        if tokens[i].typ != "ident":
            break

        cte_name = tokens[i].text
        i += 1

        # Skip whitespace
        while i < n and tokens[i].typ == "ws":
            i += 1

        # Look for AS keyword
        if i >= n or tokens[i].typ != "ident" or tokens[i].text.upper() != "AS":
            break
        i += 1  # Skip AS

        # Skip whitespace
        while i < n and tokens[i].typ == "ws":
            i += 1

        # Find opening paren
        if i >= n or tokens[i].typ != "punct" or tokens[i].text != "(":
            break

        body_start_idx = i + 1
        i += 1  # Skip (

        # Find matching closing paren
        paren_depth = 1
        while i < n and paren_depth > 0:
            if tokens[i].typ == "punct":
                if tokens[i].text == "(":
                    paren_depth += 1
                elif tokens[i].text == ")":
                    paren_depth -= 1
            i += 1

        body_end_idx = i - 1
        body_text = "".join(t.text for t in tokens[body_start_idx:body_end_idx])

        ctes.append((cte_name, body_text))

        # Skip whitespace
        while i < n and tokens[i].typ == "ws":
            i += 1

        # Check for comma (more CTEs) or end of WITH clause
        if i < n and tokens[i].typ == "punct" and tokens[i].text == ",":
            i += 1  # Skip comma, continue to next CTE
        else:
            break

    return ctes


def _get_preceding_ctes(_all_ctes: List[tuple], target_name: str, current_sql: str) -> str:
    """
    Get all CTEs that precede the target CTE.

    Returns a string like "cte1 AS (...), cte2 AS (...)" suitable for a WITH clause.
    Uses the current (possibly modified) SQL to get updated CTE bodies.

    Args:
        _all_ctes: Original CTE list (unused, kept for API compatibility)
        target_name: Name of the target CTE to find predecessors for
        current_sql: Current SQL with potentially modified CTE bodies
    """
    # Re-parse CTEs from current SQL to get updated bodies
    current_ctes = _parse_all_ctes(current_sql)

    preceding = []
    for name, body in current_ctes:
        if name.lower() == target_name.lower():
            break
        preceding.append(f"{name} AS ({body})")

    return ", ".join(preceding)


def _dataframe_to_cte_body(df) -> str:
    """
    Convert a DataFrame to a CTE body using SELECT with VALUES or literals.

    For empty DataFrame: Returns SELECT with LIMIT 0 to preserve column schema.
    For data: Returns SELECT from VALUES(...) with proper typing.
    """
    import json

    if len(df) == 0:
        # Empty result - create empty select with column names
        cols = ", ".join(f"NULL AS {col}" for col in df.columns)
        return f"SELECT {cols} WHERE FALSE"

    # Build VALUES clause
    rows = []
    for _, row in df.iterrows():  # noqa: B007
        values = []
        for col in df.columns:
            val = row[col]
            if val is None:
                values.append("NULL")
            elif isinstance(val, bool):
                values.append("TRUE" if val else "FALSE")
            elif isinstance(val, (int, float)):
                values.append(str(val))
            elif isinstance(val, str):
                # Escape single quotes
                escaped = val.replace("'", "''")
                values.append(f"'{escaped}'")
            elif isinstance(val, dict):
                # JSON object
                escaped = json.dumps(val).replace("'", "''")
                values.append(f"'{escaped}'")
            elif isinstance(val, list):
                # JSON array
                escaped = json.dumps(val).replace("'", "''")
                values.append(f"'{escaped}'")
            else:
                # Fallback: convert to string
                escaped = str(val).replace("'", "''")
                values.append(f"'{escaped}'")

        rows.append(f"({', '.join(values)})")

    # Column names for VALUES
    col_names = ", ".join(df.columns)

    # DuckDB VALUES syntax: SELECT * FROM (VALUES (...), (...)) AS t(col1, col2, ...)
    return f"SELECT * FROM (VALUES {', '.join(rows)}) AS _t({col_names})"


def _replace_cte_body(sql: str, cte_name: str, new_body: str) -> str:
    """
    Replace a CTE's body with new content.

    Finds: cte_name AS (...)
    Replaces the (...) content with new_body.
    """
    import re

    # Pattern to match CTE definition: name AS (...)
    # We need to handle nested parens in the original body
    pattern = rf'\b{re.escape(cte_name)}\s+AS\s*\('

    match = re.search(pattern, sql, re.IGNORECASE)
    if not match:
        return sql

    # Find the matching closing paren
    start = match.end()  # Position after opening paren
    depth = 1
    i = start

    while i < len(sql) and depth > 0:
        ch = sql[i]
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        elif ch == "'":
            # Skip string literal
            i += 1
            while i < len(sql) and sql[i] != "'":
                if sql[i] == "'" and i + 1 < len(sql) and sql[i + 1] == "'":
                    i += 2  # Skip escaped quote
                else:
                    i += 1
        i += 1

    # Replace the body (between start-1 and i)
    # The opening paren is at start-1, closing paren is at i-1
    return sql[:start] + new_body + sql[i-1:]
