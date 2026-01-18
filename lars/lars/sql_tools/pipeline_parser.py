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
    Quick check for THEN keyword at statement level.

    Used as a fast-path to avoid full parsing when no pipeline syntax is present.
    Returns True if the query might have pipeline syntax (needs full parse).
    """
    # Quick regex check first
    if not re.search(r'\bTHEN\b', sql, re.IGNORECASE):
        return False

    # Tokenize to confirm THEN is at statement level (not in string/comment)
    tokens = _tokenize(sql)
    for tok in tokens:
        if tok.typ == "ident" and tok.text.upper() == "THEN":
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
