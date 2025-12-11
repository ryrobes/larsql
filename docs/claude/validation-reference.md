# Validation Reference

This document covers Windlass's validation features: Wards, loop_until, turn_prompt, and output_schema.

## Overview

Windlass provides multiple validation mechanisms:

| Feature | Purpose | Enforcement | Cost |
|---------|---------|-------------|------|
| `wards` | Pre/post phase validation | Configurable (blocking/retry/advisory) | LLM call per validator |
| `loop_until` | Retry until validator passes | Hard | LLM call per attempt |
| `output_schema` | JSON schema validation | Hard | Free (no LLM) |
| `turn_prompt` | Soft guidance for iteration | None (self-check) | Free |

---

## Wards - Validation & Guardrails

Wards are protective barriers that validate inputs and outputs at the phase level.

### Configuration

```json
{
  "wards": {
    "pre": [{"validator": "input_sanitizer", "mode": "blocking"}],
    "post": [
      {"validator": "content_safety", "mode": "blocking"},
      {"validator": "grammar_check", "mode": "retry", "max_attempts": 3},
      {"validator": "style_check", "mode": "advisory"}
    ]
  }
}
```

### Ward Types

- **Pre-wards**: Run BEFORE phase execution to validate inputs
- **Post-wards**: Run AFTER phase execution to validate outputs
- **Turn-wards**: Run after each turn within a phase (optional)

### Ward Modes

| Mode | Behavior | Use Case |
|------|----------|----------|
| **Blocking** | Aborts phase immediately on failure | Critical safety/compliance |
| **Retry** | Re-executes phase with error feedback | Quality checks (grammar, format) |
| **Advisory** | Logs warning, continues execution | Optional checks, monitoring |

### Execution Flow

```
Phase Start
    ↓
🛡️  PRE-WARDS (Input Validation)
    ↓ [blocking failure → abort]
    ↓ [advisory → warn & continue]
    ↓
Phase Execution (normal turn loop)
    ↓
🛡️  POST-WARDS (Output Validation)
    ↓ [blocking failure → abort]
    ↓ [retry failure → re-execute with feedback]
    ↓ [advisory → warn & continue]
    ↓
Next Phase
```

### Validator Protocol

All validators must return:
```json
{
  "valid": true,
  "reason": "Explanation of validation result"
}
```

Can be Python function or cascade tool.

### Implementation Details

- `_run_ward()` method in `runner.py` handles both function and cascade validators
- Ward execution creates child trace nodes for observability
- Retry mode injects `{{ validation_error }}` into retry instructions
- All ward results logged with validator name, mode, and pass/fail status

### Best Practices

- Layer wards by severity: blocking → retry → advisory
- Use pre-wards for early exit before expensive phase execution
- Combine wards with `output_schema` for structure + content validation
- Set appropriate `max_attempts` for retry wards (typically 2-3)

### Example Cascades

- `ward_blocking_flow.json`: Blocking mode demonstration
- `ward_retry_flow.json`: Retry mode with automatic improvement
- `ward_comprehensive_flow.json`: All three modes together

---

## Loop Until Validation

Retry phase execution until a validator passes.

### Basic Configuration

```json
{
  "name": "generate_content",
  "instructions": "Write a blog post about {{ input.topic }}",
  "rules": {
    "max_attempts": 3,
    "loop_until": "grammar_check"
  }
}
```

### Auto-Injection Behavior

The system automatically appends to instructions:
```
---
VALIDATION REQUIREMENT:
Your output will be validated using 'grammar_check' which checks: Validates grammar and spelling in text
You have 3 attempt(s) to satisfy this validator.
---
```

### Custom Validation Prompt

Override the auto-generated prompt:
```json
{
  "rules": {
    "loop_until": "grammar_check",
    "loop_until_prompt": "Custom instruction about what makes valid output"
  }
}
```

### Silent Mode - Impartial Validation

For subjective quality checks where you need an impartial third party:

```json
{
  "name": "write_report",
  "instructions": "Write a report on the findings.",
  "rules": {
    "loop_until": "quality_check",
    "loop_until_silent": true
  }
}
```

**Why Silent Mode?**
- Auto-injection works for **objective validators** (grammar, code execution)
- Creates gaming risk for **subjective validators** (quality, satisfaction)
- Silent mode prevents the agent from gaming the evaluation

| Mode | Validator Type | Gaming Risk |
|------|---------------|-------------|
| Auto-Injection (default) | Objective checks | Low |
| Silent (`loop_until_silent: true`) | Subjective judgments | Prevented |

### How It Works

1. If `loop_until_silent: true` → skip auto-injection
2. If `loop_until_prompt` provided → use custom prompt
3. Otherwise → auto-generate from validator description
4. Validation prompt injected BEFORE phase execution (proactive)
5. Agent knows criteria upfront (unless silent)

### Per-Turn Early Exit (Automatic)

When `loop_until` is configured with `max_turns > 1`, the validator runs **after each turn** (not just at the end). If validation passes early, the turn loop exits immediately:

```
Turn 1: Agent works → Validator check → PASS? → Exit early ✓
Turn 2: (skipped - task complete)
Turn 3: (skipped - task complete)
```

**Benefits:**
- Prevents unnecessary context snowballing
- Fast models can one-shot, slow models get extra turns if needed
- Works inside soundings - each sounding can exit independently
- No configuration needed - automatic when `loop_until` is set

**Example:**
```yaml
- name: discover_question
  rules:
    max_turns: 3          # Up to 3 turns
    loop_until: question_check  # Validator runs after each turn
    loop_until_silent: true     # Don't tell agent about validation
```

If the agent formulates a valid question on turn 1, turns 2-3 are skipped entirely.

### Example Cascades

- `loop_until_auto_inject.json`: Auto-injection demonstration
- `loop_until_silent_demo.json`: Silent mode for impartial validation

---

## Turn Prompt - Guided Iteration

Provide custom guidance for subsequent turns in `max_turns` loops.

### The Problem

By default, `max_turns` loops with a vague continuation prompt. The agent doesn't know what to focus on during iteration.

### The Solution

`turn_prompt` gives specific guidance for turns 1+ (after the initial turn).

### Configuration

```json
{
  "name": "solve_problem",
  "instructions": "Solve the coding problem: {{ input.problem }}",
  "tackle": ["run_code"],
  "rules": {
    "max_turns": 3,
    "turn_prompt": "Review your solution. Does it handle edge cases correctly? Test it and refine if needed."
  }
}
```

### How It Works

1. **Turn 0**: Uses the phase `instructions`
2. **Turn 1+**: Uses `turn_prompt` for refinement guidance
3. **Jinja2 Support**: Full access to context variables

### Available Template Variables

```json
{
  "input": {...},           // Original cascade input
  "state": {...},           // Current session state
  "outputs": {...},         // Previous phase outputs
  "lineage": [...],         // Execution history
  "history": [...],         // Message history
  "turn": 2,               // Current turn number (1-indexed)
  "max_turns": 3           // Total turns configured
}
```

### Use Cases

**Code Generation with Self-Review:**
```json
{
  "rules": {
    "max_turns": 3,
    "turn_prompt": "Review your code:\n- Does it handle {{ input.edge_case }}?\n- Is it readable?\n- Are there any bugs?"
  }
}
```

**Content Writing with Quality Check:**
```json
{
  "rules": {
    "max_turns": 2,
    "turn_prompt": "Re-read your draft. Is it engaging? Does it address: {{ input.goal }}?"
  }
}
```

**Dynamic Turn-Specific Prompts:**
```json
{
  "rules": {
    "max_turns": 3,
    "turn_prompt": "{% if turn == 1 %}First review: Check for major issues{% elif turn == 2 %}Polish and refine{% else %}Final review: Make it perfect{% endif %}"
  }
}
```

**Combo with Validation (Soft + Hard):**
```json
{
  "rules": {
    "max_turns": 3,
    "turn_prompt": "Check your grammar and clarity.",
    "loop_until": "grammar_check",
    "max_attempts": 2
  }
}
```

### Benefits

- Makes `max_turns` actually useful (not just generic looping)
- Zero cost (no extra LLM calls)
- Context-aware with Jinja2 templating
- Complements validation features

**turn_prompt is "low-rent validation"** - lighter than full validation, better than blind iteration.

### Example Cascade

- `turn_prompt_demo.json`: Guided iteration demonstration

---

## Output Schema

Validate phase output against a JSON schema with automatic retry on failure.

### Configuration

```json
{
  "name": "generate_data",
  "instructions": "Generate user data",
  "output_schema": {
    "type": "object",
    "required": ["name", "email"],
    "properties": {
      "name": {"type": "string"},
      "email": {"type": "string", "format": "email"},
      "age": {"type": "integer", "minimum": 0}
    }
  }
}
```

### How It Works

1. Phase executes normally
2. Framework extracts JSON from response
3. Validates against schema
4. If invalid: re-executes with error feedback
5. Continues until valid or max_attempts reached

### Benefits

- Free validation (no LLM call for schema check)
- Hard enforcement of structure
- Automatic retry with helpful error messages
- Works with existing JSON Schema tooling

---

## Validation Comparison

| Feature | When to Use | Enforcement | Cost |
|---------|-------------|-------------|------|
| **Wards (blocking)** | Critical safety checks | Hard stop | 1 LLM call |
| **Wards (retry)** | Quality that can improve | Retry loop | N LLM calls |
| **Wards (advisory)** | Monitoring, optional checks | None (log only) | 1 LLM call |
| **loop_until** | Must satisfy validator | Retry loop | N LLM calls |
| **output_schema** | Structural requirements | Retry loop | Free |
| **turn_prompt** | Self-guided refinement | None | Free |

### Recommended Layering

```json
{
  "name": "generate_report",
  "instructions": "Create a detailed report",
  "output_schema": {"type": "object", "required": ["summary", "details"]},
  "rules": {
    "max_turns": 3,
    "turn_prompt": "Review for completeness and clarity"
  },
  "wards": {
    "pre": [{"validator": "input_sanitizer", "mode": "blocking"}],
    "post": [
      {"validator": "content_safety", "mode": "blocking"},
      {"validator": "grammar_check", "mode": "retry", "max_attempts": 2}
    ]
  }
}
```

This combines:
- Structural validation (output_schema) - free
- Self-refinement (turn_prompt) - free
- Safety gates (wards blocking) - 1 call
- Quality improvement (wards retry) - up to 2 calls
