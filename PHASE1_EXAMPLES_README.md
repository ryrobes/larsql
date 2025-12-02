# Phase 1 Validation Examples 🧪

This directory contains comprehensive test cascades demonstrating **Phase 1: Enhanced loop_until** validation features.

## Quick Start

### Run Individual Tests

```bash
# Blog post with grammar validation
python -m windlass.cli examples/blog_post_quality_flow.json \
  --input '{"topic": "AI Ethics", "target_audience": "general public"}'

# Code generation with documentation enforcement
python -m windlass.cli examples/code_generation_flow.json \
  --input '{"function_name": "merge_sort", "description": "Sort a list using merge sort"}'

# Creative story with multi-stage validation
python -m windlass.cli examples/story_writer_flow.json \
  --input '{"genre": "mystery", "protagonist": "Detective Moore", "setting": "Victorian London"}'

# Simple keyword validation with retry
python -m windlass.cli examples/keyword_retry_test.json \
  --input '{"topic": "quantum computing"}'
```

### Run All Tests

```bash
python test_phase1_flows.py
```

---

## Example Cascades

### 📝 Blog Post Quality Flow
**File**: `examples/blog_post_quality_flow.json`

Multi-phase content creation with quality gates:
1. Draft post → Grammar validation
2. Add conclusion → Keyword validation (must include "important")
3. Finalize → Summary

**Demonstrates**:
- Multi-phase validation pipeline
- Different validators for different quality aspects
- Custom retry messages with emojis
- Professional content workflow

**Try it**:
```bash
python -m windlass.cli examples/blog_post_quality_flow.json \
  --input '{"topic": "Future of Work", "target_audience": "business leaders"}'
```

---

### 💻 Code Generation Flow
**File**: `examples/code_generation_flow.json`

Generate Python code with enforced documentation standards:
1. Generate code → Length validation
2. Add docstring → Keyword validation (must include "important")
3. Summary → Reflection

**Demonstrates**:
- Code quality enforcement
- Documentation standards as validators
- Natural keyword incorporation
- Clean separation of generation and documentation

**Try it**:
```bash
python -m windlass.cli examples/code_generation_flow.json \
  --input '{"function_name": "binary_search", "description": "Search for element in sorted array"}'
```

---

### 📖 Story Writer Flow
**File**: `examples/story_writer_flow.json`

Interactive story writing with quality gates at each stage:
1. Opening → Grammar check
2. Rising action → Keyword validation ("important")
3. Climax → Length check
4. Resolution → Grammar check
5. Reflect → Writer's commentary

**Demonstrates**:
- Creative writing workflow
- Multiple validation stages
- Different validators for different story sections
- Meta-reflection on validation process

**Try it**:
```bash
python -m windlass.cli examples/story_writer_flow.json \
  --input '{"genre": "fantasy", "protagonist": "Aria the Mage", "setting": "Enchanted Forest"}'
```

---

### 🛡️ Safe Content Flow
**File**: `examples/safe_content_flow.json`

Content creation with safety and quality validation:
1. Draft content → Safety check
2. Polish grammar → Grammar check
3. Finalize → Meta-summary

**Demonstrates**:
- Safety-first validation
- Dual validation (safety + quality)
- Different retry messages for different concerns
- Production-ready content workflow

**Try it**:
```bash
python -m windlass.cli examples/safe_content_flow.json \
  --input '{"topic": "Digital Privacy", "tone": "educational"}'
```

---

### 📏 Strict Length Flow
**File**: `examples/strict_length_flow.json`

Writing with precise character constraints:
1. Constrained writing → Length validation (configurable min/max)
2. Reflect → Agent reflection on challenge

**Demonstrates**:
- Parameterized validators (length_check)
- High retry attempts (4 max)
- Constraint-based writing
- Agent adaptation to strict requirements

**Try it**:
```bash
python -m windlass.cli examples/strict_length_flow.json \
  --input '{"topic": "Python", "min_length": "150", "max_length": "300"}'
```

---

### ⚡ Simple Tests

#### Validation Test Flow
**File**: `examples/validation_test_flow.json`

Basic validation with simple_validator (10+ chars).

```bash
python -m windlass.cli examples/validation_test_flow.json \
  --input '{"topic": "blockchain"}'
```

#### Grammar Validation Flow
**File**: `examples/grammar_validation_flow.json`

Two-phase flow with grammar validation and finalization.

```bash
python -m windlass.cli examples/grammar_validation_flow.json \
  --input '{"topic": "renewable energy", "style": "technical"}'
```

#### Keyword Retry Test
**File**: `examples/keyword_retry_test.json`

Demonstrates retry mechanism when keyword is missing.

```bash
python -m windlass.cli examples/keyword_retry_test.json \
  --input '{"topic": "coffee"}'
```

---

## Available Validators

All cascades use these validators from `tackle/`:

| Validator | Purpose | Returns Invalid If... |
|-----------|---------|----------------------|
| `simple_validator` | Basic length check | Content < 10 characters |
| `grammar_check` | Grammar & spelling | 3+ significant errors found |
| `keyword_validator` | Keyword presence | Missing word "important" |
| `length_check` | Configurable constraints | Outside min/max range |
| `content_safety` | Safety check | Inappropriate content detected |

---

## Validation Features Showcased

### ✅ Retry Mechanism
- Automatic retry when validation fails
- Custom retry instructions per phase
- Attempt counter (1/3, 2/3, etc.)
- Max attempts limit

### ✅ Jinja2 Templating
```json
"retry_instructions": "Error: {{ validation_error }}\n\nAttempt {{ attempt }}/{{ max_attempts }}"
```

Variables available:
- `{{ validation_error }}` - Reason from validator
- `{{ attempt }}` - Current attempt number
- `{{ max_attempts }}` - Maximum retries
- `{{ input.* }}` - Original cascade inputs
- `{{ state.* }}` - Current state values

### ✅ Multi-Phase Validation
Each phase can have different:
- Validator
- Max attempts
- Retry instructions
- Success criteria

### ✅ Cascade Validators
Validators can be complex multi-phase cascades themselves, enabling sophisticated validation logic.

---

## Expected Outputs

### Successful Validation
```
🛡️  Running Validator: grammar_check
  ✓ Validation Passed: The text is well-written with no significant errors
```

### Validation Retry
```
🛡️  Running Validator: keyword_validator
  ✗ Validation Failed: Content must include the word 'important'
🔄 Validation Retry Attempt 2/3
  ❌ Editorial requirement not met: Content must include the word 'important'

[Agent revises response]

🛡️  Running Validator: keyword_validator
  ✓ Validation Passed: Content contains required keyword
```

### Max Attempts Reached
```
⚠️  Max validation attempts reached (3)
```

---

## Tips for Creating Your Own Validators

### Validator Return Format
All validators must return:
```json
{
  "valid": true,  // or false
  "reason": "Explanation of result"
}
```

### Example Validator Cascade
```json
{
  "cascade_id": "my_validator",
  "inputs_schema": {
    "content": "The content to validate"
  },
  "phases": [{
    "name": "validate",
    "instructions": "Check the content...\n\nReturn: {\"valid\": true/false, \"reason\": \"...\"}",
    "rules": {"max_turns": 1}
  }]
}
```

---

## Next Steps

**Phase 2**: Schema Validation (`output_schema`)
- Automatic JSON schema validation
- Structured output enforcement
- Type checking

**Phase 3**: Full Wards System
- Pre-wards (input validation)
- Post-wards (output validation)
- Turn-wards (per-turn validation)
- Multiple validation modes (blocking, retry, advisory)

---

## Need Help?

- Check `PHASE1_VALIDATION_COMPLETE.md` for implementation details
- Check `PHASE1_TEST_RESULTS.md` for test results
- Check `WARDS_IMPLEMENTATION_PLAN.md` for full roadmap

**Status**: ✅ Phase 1 Complete and Production-Ready

---

**Created**: 2025-12-01
**Windlass Version**: Phase 1 Implementation
