# Implementation Plan: CHOOSE BY Pipeline Router

## Overview

Add a `CHOOSE [BY]` stage type to the pipeline system that conditionally routes data through different cascades based on semantic classification.

```sql
SELECT * FROM transactions
THEN ENRICH 'add risk scores'
THEN CHOOSE BY FRAUD_DETECTOR (
  WHEN 'fraud' THEN QUARANTINE 'fraud_review'
  WHEN 'suspicious' THEN FLAG 'needs_review'
  ELSE LOAD 'warehouse.transactions'
)
THEN VISUALIZE 'summary'
```

## Design Decisions

1. **Option A for stop behavior**: If a branch cascade returns `None`, empty data, or `{"stop": true}`, the pipeline terminates gracefully
2. **Semantic matching by default**: WHEN conditions are matched semantically against discriminator output
3. **Discriminator is optional**: Without `BY <cascade>`, uses a built-in generic discriminator
4. **Branches execute cascades**: Each WHEN branch specifies a cascade name + optional args

---

## Phase 1: Data Structures

### File: `lars/lars/sql_tools/pipeline_parser.py`

Add new dataclasses for CHOOSE stages:

```python
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
    discriminator: Optional[str]  # e.g., "FRAUD_DETECTOR" or None for generic
    branches: List[ChooseBranch]
    # Inherits: name="CHOOSE", args=[], original_text, into_table
```

Update `PipelineStage` to support polymorphism:

```python
@dataclass
class PipelineStage:
    """A single pipeline stage to execute."""
    name: str
    args: List[str]
    original_text: str
    into_table: Optional[str] = None
    stage_type: str = "standard"  # "standard" | "choose"
```

---

## Phase 2: Parser Extension

### File: `lars/lars/sql_tools/pipeline_parser.py`

Add parsing logic for CHOOSE syntax after line 290 (in the stage parsing loop):

```python
# After extracting stage_name...

if stage_name == "CHOOSE":
    # Parse CHOOSE [BY discriminator] (WHEN ... THEN ... [ELSE ...])
    choose_stage = _parse_choose_stage(tokens, i, stage_original)
    stages.append(choose_stage)
    i = choose_stage._end_index  # Track where parsing ended
    continue
```

New function `_parse_choose_stage`:

```python
def _parse_choose_stage(
    tokens: List[_Token],
    start_idx: int,
    original_text: str
) -> ChooseStage:
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
        raise ValueError(f"CHOOSE requires (...) block with WHEN clauses")
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
        if tok.text == ")":
            i += 1
            break

        # WHEN branch
        if tok.typ == "ident" and tok.text.upper() == "WHEN":
            i += 1
            branch = _parse_when_branch(tokens, i)
            branches.append(branch)
            i = branch._end_index
            continue

        # ELSE branch
        if tok.typ == "ident" and tok.text.upper() == "ELSE":
            i += 1
            branch = _parse_else_branch(tokens, i)
            branches.append(branch)
            i = branch._end_index
            continue

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
    stage._end_index = i
    return stage


def _parse_when_branch(tokens: List[_Token], start_idx: int) -> ChooseBranch:
    """Parse: WHEN 'condition' THEN CASCADE 'args'"""
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
    if i >= len(tokens) or tokens[i].text.upper() != "THEN":
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
    cascade_args = []
    while i < len(tokens) and tokens[i].typ == "ws":
        i += 1

    if i < len(tokens):
        if tokens[i].typ == "string":
            cascade_args.append(_extract_string_value(tokens[i].text))
            i += 1
        elif tokens[i].text == "(":
            # Function-style args
            i += 1
            while i < len(tokens) and tokens[i].text != ")":
                if tokens[i].typ == "string":
                    cascade_args.append(_extract_string_value(tokens[i].text))
                elif tokens[i].typ not in ("ws", "punct"):
                    cascade_args.append(tokens[i].text)
                i += 1
            i += 1  # Skip )

    branch = ChooseBranch(
        condition=condition,
        cascade_name=cascade_name,
        cascade_args=cascade_args,
        is_else=False
    )
    branch._end_index = i
    return branch


def _parse_else_branch(tokens: List[_Token], start_idx: int) -> ChooseBranch:
    """Parse: ELSE CASCADE 'args'"""
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
    cascade_args = []
    while i < len(tokens) and tokens[i].typ == "ws":
        i += 1

    if i < len(tokens) and tokens[i].typ == "string":
        cascade_args.append(_extract_string_value(tokens[i].text))
        i += 1

    branch = ChooseBranch(
        condition="",  # ELSE has no condition
        cascade_name=cascade_name,
        cascade_args=cascade_args,
        is_else=True
    )
    branch._end_index = i
    return branch


def _extract_string_value(token_text: str) -> str:
    """Extract string value from quoted token."""
    if token_text.startswith("'") and token_text.endswith("'"):
        return token_text[1:-1].replace("''", "'")
    if token_text.startswith('"') and token_text.endswith('"'):
        return token_text[1:-1].replace('""', '"')
    return token_text
```

---

## Phase 3: Executor Extension

### File: `lars/lars/sql_tools/pipeline_executor.py`

Update the main execution loop to handle CHOOSE stages:

```python
def execute_pipeline_with_into(...) -> pd.DataFrame:
    # ... existing setup ...

    for idx, stage in enumerate(stages):
        log.info(f"[pipeline] Executing stage {idx + 1}/{len(stages)}: {stage.name}")

        # Handle CHOOSE stages specially
        if isinstance(stage, ChooseStage) or getattr(stage, 'stage_type', None) == 'choose':
            result_df, should_stop = _execute_choose_stage(
                stage=stage,
                current_df=current_df,
                context=context,
                session_id=session_id,
                caller_id=caller_id,
            )

            if should_stop:
                log.info(f"[pipeline] CHOOSE branch signaled stop, ending pipeline")
                current_df = result_df
                break

            current_df = result_df

            # Handle INTO for CHOOSE stage
            if stage.into_table and duckdb_conn is not None:
                _save_to_table(duckdb_conn, current_df, stage.into_table)

            previous_stage = stage.name
            continue

        # ... existing standard stage handling ...
```

New function `_execute_choose_stage`:

```python
from typing import Tuple

def _execute_choose_stage(
    stage: ChooseStage,
    current_df: pd.DataFrame,
    context: PipelineContext,
    session_id: str,
    caller_id: Optional[str],
) -> Tuple[pd.DataFrame, bool]:
    """
    Execute a CHOOSE stage with conditional routing.

    Returns:
        Tuple of (result_df, should_stop)
        - result_df: The DataFrame after branch execution
        - should_stop: True if pipeline should terminate
    """
    from ..semantic_sql.registry import get_pipeline_cascade
    from ..runner import LARSRunner
    from .. import _register_all_skills
    from ..semantic_sql.executor import _extract_cascade_output

    _register_all_skills()

    # Step 1: Run discriminator to classify the data
    classification = _run_discriminator(
        discriminator_name=stage.discriminator,
        df=current_df,
        context=context,
        branches=stage.branches,
        session_id=session_id,
        caller_id=caller_id,
    )

    log.info(f"[pipeline] CHOOSE discriminator returned: {classification}")

    # Step 2: Match classification to branch
    matched_branch = _match_branch(classification, stage.branches)

    if matched_branch is None:
        log.warning(f"[pipeline] No branch matched classification '{classification}', passing through")
        return current_df, False

    log.info(f"[pipeline] Matched branch: {matched_branch.cascade_name}")

    # Step 3: Handle special PASS cascade (no-op)
    if matched_branch.cascade_name == "PASS":
        return current_df, False

    # Step 4: Handle special STOP cascade
    if matched_branch.cascade_name == "STOP":
        return current_df, True

    # Step 5: Execute the branch cascade
    cascade_entry = get_pipeline_cascade(matched_branch.cascade_name)
    if not cascade_entry:
        raise PipelineExecutionError(
            stage_name=f"CHOOSE->{matched_branch.cascade_name}",
            stage_index=context.stage_index,
            inner_error=ValueError(f"Unknown cascade '{matched_branch.cascade_name}'")
        )

    # Serialize and execute
    serialized = _serialize_dataframe(current_df, context)

    # Add branch args
    if matched_branch.cascade_args:
        sql_func_args = cascade_entry.sql_function.get("args", [])
        user_arg_names = [a["name"] for a in sql_func_args if not a["name"].startswith("_")]
        for i, arg_value in enumerate(matched_branch.cascade_args):
            if i < len(user_arg_names):
                serialized[user_arg_names[i]] = arg_value
            else:
                serialized[f"arg{i}"] = arg_value

    stage_session_id = f"{session_id}_choose_{context.stage_index}"
    runner = LARSRunner(
        cascade_entry.cascade_path,
        session_id=stage_session_id,
        caller_id=caller_id
    )

    result = runner.run(input_data=serialized)
    output = _extract_cascade_output(result)

    # Check for stop signal
    if output is None:
        return current_df, True

    if isinstance(output, dict):
        if output.get("stop") is True:
            return current_df, True
        if output.get("data") is not None and len(output["data"]) == 0:
            # Empty data = stop
            return pd.DataFrame(), True

    # Deserialize result
    result_df = _deserialize_result(output, current_df)

    # Empty result = stop
    if len(result_df) == 0:
        return result_df, True

    return result_df, False
```

---

## Phase 4: Discriminator Logic

### File: `lars/lars/sql_tools/pipeline_executor.py`

```python
def _run_discriminator(
    discriminator_name: Optional[str],
    df: pd.DataFrame,
    context: PipelineContext,
    branches: List[ChooseBranch],
    session_id: str,
    caller_id: Optional[str],
) -> str:
    """
    Run the discriminator cascade to classify the data.

    If discriminator_name is None, uses the built-in generic discriminator.
    """
    from ..semantic_sql.registry import get_pipeline_cascade
    from ..runner import LARSRunner
    from ..semantic_sql.executor import _extract_cascade_output

    # Build condition list for discriminator
    conditions = [b.condition for b in branches if not b.is_else]

    if discriminator_name:
        # Use named discriminator cascade
        cascade_entry = get_pipeline_cascade(discriminator_name)
        if not cascade_entry:
            # Try as SCALAR cascade (non-pipeline discriminator)
            from ..semantic_sql.registry import _registry, initialize_registry
            initialize_registry()
            cascade_entry = _registry.get(discriminator_name)

        if not cascade_entry:
            raise ValueError(f"Unknown discriminator cascade: {discriminator_name}")

        cascade_path = cascade_entry.cascade_path
    else:
        # Use built-in generic discriminator
        cascade_path = _get_generic_discriminator_path()

    # Serialize data
    serialized = _serialize_dataframe(df, context)
    serialized["_conditions"] = conditions
    serialized["_conditions_text"] = "\n".join(
        f"{i+1}. {c}" for i, c in enumerate(conditions)
    )

    # Execute discriminator
    runner = LARSRunner(
        cascade_path,
        session_id=f"{session_id}_discriminator",
        caller_id=caller_id
    )

    result = runner.run(input_data=serialized)
    output = _extract_cascade_output(result)

    # Extract classification string
    if isinstance(output, dict):
        return output.get("classification", output.get("result", str(output)))
    return str(output).strip()


def _get_generic_discriminator_path() -> str:
    """Get path to the built-in generic discriminator cascade."""
    from pathlib import Path
    import lars

    package_dir = Path(lars.__file__).parent
    return str(package_dir / "builtin_cascades" / "semantic_sql" / "generic_discriminator.cascade.yaml")
```

---

## Phase 5: Branch Matching

### File: `lars/lars/sql_tools/pipeline_executor.py`

```python
def _match_branch(
    classification: str,
    branches: List[ChooseBranch]
) -> Optional[ChooseBranch]:
    """
    Match discriminator output to a branch.

    Uses semantic similarity for matching, falling back to substring/exact match.
    """
    classification_lower = classification.lower().strip()

    # First pass: exact match
    for branch in branches:
        if branch.is_else:
            continue
        if branch.condition.lower().strip() == classification_lower:
            return branch

    # Second pass: classification contains condition or vice versa
    for branch in branches:
        if branch.is_else:
            continue
        cond_lower = branch.condition.lower().strip()
        if cond_lower in classification_lower or classification_lower in cond_lower:
            return branch

    # Third pass: word overlap scoring
    classification_words = set(classification_lower.split())
    best_match = None
    best_score = 0

    for branch in branches:
        if branch.is_else:
            continue
        cond_words = set(branch.condition.lower().split())
        overlap = len(classification_words & cond_words)
        if overlap > best_score:
            best_score = overlap
            best_match = branch

    if best_match and best_score > 0:
        return best_match

    # Fall back to ELSE if present
    for branch in branches:
        if branch.is_else:
            return branch

    return None
```

---

## Phase 6: Generic Discriminator Cascade

### File: `lars/lars/builtin_cascades/semantic_sql/generic_discriminator.cascade.yaml`

```yaml
cascade_id: generic_discriminator
internal: true
description: |
  Built-in discriminator for CHOOSE stages without explicit BY clause.
  Classifies data against provided conditions.

inputs_schema:
  _table: Data to classify
  _table_columns: Column names
  _table_row_count: Row count
  _conditions: List of condition strings
  _conditions_text: Formatted conditions for prompt

sql_function:
  name: GENERIC_DISCRIMINATOR
  shape: DISCRIMINATOR
  args:
    - name: _table
      type: TABLE
    - name: _conditions
      type: JSON
  returns: VARCHAR
  cache: false

cells:
  - name: classify
    model: google/gemini-2.5-flash-lite
    instructions: |
      You are a classifier. Analyze the provided data and determine which condition best matches.

      DATA SUMMARY:
      - Rows: {{ input._table_row_count }}
      - Columns: {{ input._table_columns | join(', ') }}

      SAMPLE DATA:
      {{ input._table | tojson | truncate(2000) }}

      POSSIBLE CONDITIONS:
      {{ input._conditions_text }}

      Analyze the data and determine which numbered condition (1, 2, 3, etc.) best describes it.

      Respond with ONLY the condition text that matches (copy it exactly), or "none" if no condition matches.

    rules:
      max_turns: 1

    output_schema:
      type: string
```

---

## Phase 7: Special PASS Cascade

### File: `lars/lars/builtin_cascades/semantic_sql/pass_pipeline.cascade.yaml`

```yaml
cascade_id: pipeline_pass
internal: true
description: |
  No-op pipeline stage that passes data through unchanged.
  Used in CHOOSE ELSE branches when no action is needed.

inputs_schema:
  _table: Data to pass through

sql_function:
  name: PASS
  shape: PIPELINE
  args:
    - name: _table
      type: TABLE
  returns: TABLE
  cache: false

cells:
  - name: passthrough
    deterministic: true
    tool: python:lars.pipeline_tools.passthrough
    inputs:
      _table: "{{ input._table }}"
```

### File: `lars/lars/pipeline_tools.py` (add function)

```python
def passthrough(_table: List[Dict[str, Any]], **kwargs) -> Dict[str, Any]:
    """Pass data through unchanged."""
    return {"data": _table}
```

---

## Phase 8: Tests

### File: `tests/test_pipeline_choose.py`

```python
"""Tests for CHOOSE BY pipeline routing."""

import pytest
import pandas as pd
from lars.sql_tools.pipeline_parser import (
    parse_pipeline_syntax,
    ChooseStage,
    ChooseBranch,
)
from lars.sql_tools.pipeline_executor import (
    _match_branch,
)


class TestChooseParser:
    """Test CHOOSE syntax parsing."""

    def test_choose_with_discriminator(self):
        sql = """
        SELECT * FROM data
        THEN CHOOSE BY CLASSIFIER (
            WHEN 'positive' THEN CELEBRATE
            WHEN 'negative' THEN ESCALATE
            ELSE PASS
        )
        """
        result = parse_pipeline_syntax(sql)
        assert result is not None
        assert len(result.stages) == 1

        stage = result.stages[0]
        assert isinstance(stage, ChooseStage)
        assert stage.discriminator == "CLASSIFIER"
        assert len(stage.branches) == 3

        assert stage.branches[0].condition == "positive"
        assert stage.branches[0].cascade_name == "CELEBRATE"
        assert stage.branches[1].condition == "negative"
        assert stage.branches[1].cascade_name == "ESCALATE"
        assert stage.branches[2].is_else
        assert stage.branches[2].cascade_name == "PASS"

    def test_choose_without_discriminator(self):
        sql = """
        SELECT * FROM data
        THEN CHOOSE (
            WHEN 'error' THEN ALERT 'ops-channel'
            ELSE LOG
        )
        """
        result = parse_pipeline_syntax(sql)
        assert result is not None

        stage = result.stages[0]
        assert isinstance(stage, ChooseStage)
        assert stage.discriminator is None
        assert len(stage.branches) == 2

        assert stage.branches[0].cascade_args == ["ops-channel"]

    def test_choose_with_function_args(self):
        sql = """
        SELECT * FROM data
        THEN CHOOSE BY DETECTOR (
            WHEN 'fraud' THEN QUARANTINE('review', 'high')
        )
        """
        result = parse_pipeline_syntax(sql)
        stage = result.stages[0]

        assert stage.branches[0].cascade_name == "QUARANTINE"
        assert stage.branches[0].cascade_args == ["review", "high"]

    def test_choose_in_pipeline_chain(self):
        sql = """
        SELECT * FROM data
        THEN ENRICH 'add scores'
        THEN CHOOSE BY RISK (
            WHEN 'high' THEN BLOCK
            ELSE ALLOW
        )
        THEN LOG 'completed'
        """
        result = parse_pipeline_syntax(sql)
        assert len(result.stages) == 3

        assert result.stages[0].name == "ENRICH"
        assert isinstance(result.stages[1], ChooseStage)
        assert result.stages[2].name == "LOG"


class TestBranchMatching:
    """Test branch matching logic."""

    def test_exact_match(self):
        branches = [
            ChooseBranch("fraud", "BLOCK", [], False),
            ChooseBranch("clean", "ALLOW", [], False),
        ]

        assert _match_branch("fraud", branches).cascade_name == "BLOCK"
        assert _match_branch("clean", branches).cascade_name == "ALLOW"

    def test_case_insensitive(self):
        branches = [
            ChooseBranch("Fraud Detected", "BLOCK", [], False),
        ]

        assert _match_branch("fraud detected", branches).cascade_name == "BLOCK"
        assert _match_branch("FRAUD DETECTED", branches).cascade_name == "BLOCK"

    def test_substring_match(self):
        branches = [
            ChooseBranch("fraud", "BLOCK", [], False),
        ]

        result = _match_branch("This looks like fraud to me", branches)
        assert result.cascade_name == "BLOCK"

    def test_else_fallback(self):
        branches = [
            ChooseBranch("fraud", "BLOCK", [], False),
            ChooseBranch("", "ALLOW", [], True),  # ELSE
        ]

        result = _match_branch("completely unknown", branches)
        assert result.cascade_name == "ALLOW"
        assert result.is_else

    def test_no_match_no_else(self):
        branches = [
            ChooseBranch("fraud", "BLOCK", [], False),
        ]

        result = _match_branch("completely unknown", branches)
        assert result is None


class TestChooseExecution:
    """Integration tests for CHOOSE execution."""

    @pytest.mark.requires_llm
    def test_choose_routes_correctly(self):
        # Would need actual cascade execution
        pass

    def test_choose_stop_on_empty(self):
        # Test that empty result stops pipeline
        pass

    def test_choose_pass_continues(self):
        # Test that PASS branch continues pipeline
        pass
```

---

## Implementation Order

### Step 1: Data Structures (1 hour)
- [ ] Add `ChooseBranch` dataclass to `pipeline_parser.py`
- [ ] Add `ChooseStage` dataclass to `pipeline_parser.py`
- [ ] Add `stage_type` field to `PipelineStage`

### Step 2: Parser (2-3 hours)
- [ ] Implement `_parse_choose_stage()`
- [ ] Implement `_parse_when_branch()`
- [ ] Implement `_parse_else_branch()`
- [ ] Add CHOOSE handling in main parse loop
- [ ] Write parser unit tests

### Step 3: Branch Matching (1 hour)
- [ ] Implement `_match_branch()` with exact/substring/word-overlap matching
- [ ] Write matching unit tests

### Step 4: Executor Core (2-3 hours)
- [ ] Implement `_execute_choose_stage()`
- [ ] Implement `_run_discriminator()`
- [ ] Add CHOOSE handling in `execute_pipeline_with_into()`
- [ ] Handle stop signals (None, empty, {"stop": true})

### Step 5: Built-in Cascades (1 hour)
- [ ] Create `generic_discriminator.cascade.yaml`
- [ ] Create `pass_pipeline.cascade.yaml`
- [ ] Add `passthrough()` to `pipeline_tools.py`

### Step 6: Integration Tests (2 hours)
- [ ] Test CHOOSE with explicit discriminator
- [ ] Test CHOOSE with generic discriminator
- [ ] Test pipeline stop behavior
- [ ] Test CHOOSE in middle of pipeline chain

### Step 7: Documentation (1 hour)
- [ ] Add CHOOSE syntax to docstrings
- [ ] Update CLAUDE.md with CHOOSE examples
- [ ] Add examples to `cascades/examples/`

---

## Future Enhancements (Out of Scope)

1. **Semantic matching via LLM**: Use an LLM to match classification to conditions instead of string matching
2. **Multiple branch execution**: `WHEN ... ALSO WHEN ...` for non-exclusive branches
3. **FORK/MERGE**: Parallel branch execution with merge
4. **Branch chaining with `|`**: `WHEN 'x' THEN A | B | C`
5. **TAKES on discriminator**: Run discriminator N times, pick best classification

---

## Example Usage After Implementation

```sql
-- Basic routing
SELECT * FROM feedback
THEN CHOOSE (
    WHEN 'positive sentiment' THEN ARCHIVE 'testimonials'
    WHEN 'negative sentiment' THEN ESCALATE 'support'
    ELSE PASS
)

-- With custom discriminator
SELECT * FROM transactions
THEN CHOOSE BY FRAUD_MODEL (
    WHEN 'high_risk' THEN BLOCK 'fraud_queue'
    WHEN 'medium_risk' THEN FLAG 'review'
    ELSE LOAD 'transactions_clean'
)
THEN AGGREGATE 'daily summary'

-- Chained routing
SELECT * FROM events
THEN ENRICH 'add user context'
THEN CHOOSE BY EVENT_CLASSIFIER (
    WHEN 'purchase' THEN TRACK 'conversions'
    WHEN 'error' THEN ALERT 'engineering'
    ELSE PASS
)
THEN VISUALIZE 'event dashboard'
```
