# Wards Implementation Plan

## Overview

**Wards** are protective barriers (nautical term) that guard phases against invalid outputs, unsafe content, or quality issues. They provide declarative guardrails in Windlass's JSON DSL.

## Design Philosophy

1. **Declarative** - Pure JSON configuration, no code
2. **Composable** - Wards are cascade tools (unified abstraction)
3. **Observable** - Full tracing of validation reasoning
4. **Flexible** - Blocking or advisory modes
5. **Ergonomic** - Simple to understand and use

## Core Concepts

### What is a Ward?

A Ward is a validator that runs at phase boundaries:
- **Pre-Wards**: Validate inputs before phase starts
- **Post-Wards**: Validate outputs after phase completes
- **Turn-Wards**: Validate each turn within a phase (optional)

### Ward Types

1. **Schema Validators**: JSON schema validation (built-in)
2. **Cascade Validators**: Complex validation via cascade tools
3. **Function Validators**: Simple Python function checks (existing tackle)

### Ward Modes

1. **Blocking**: Phase fails if ward fails (hard guardrail)
2. **Advisory**: Ward runs async, logs issues, doesn't block (soft guardrail)
3. **Retry**: Auto-retry phase if ward fails (up to max_attempts)

---

## Phase 1: Enhanced loop_until (Foundation)

Before implementing full Wards, enhance the existing `loop_until` to accept validators.

### Current State
```json
{
  "rules": {
    "loop_until": "some_condition",  // Not implemented yet
    "max_turns": 5
  }
}
```

### Enhanced loop_until
```json
{
  "rules": {
    "loop_until": "validator_tool_name",
    "max_attempts": 3,
    "retry_instructions": "The validator said: {{ validation_error }}. Please fix and try again."
  }
}
```

**Behavior:**
1. Phase executes normally
2. Output is passed to validator tool
3. Validator returns `{"valid": true/false, "reason": "..."}`
4. If invalid and attempts remain, inject retry_instructions and loop
5. If valid or max_attempts reached, continue

**Implementation:**
- Add `loop_until` to `RuleConfig` in `cascade.py`
- Add validation check in `_execute_phase_internal()` after turn loop
- Call validator tool and parse response
- Inject retry message and loop if needed
- Log validation attempts

---

## Phase 2: Schema Validation (Built-in Ward Type)

Add simple JSON schema validation as a built-in feature.

### Configuration
```json
{
  "name": "extract_data",
  "instructions": "Extract contact info as JSON: {name, email, phone}",
  "output_schema": {
    "type": "object",
    "required": ["name", "email", "phone"],
    "properties": {
      "name": {"type": "string"},
      "email": {"type": "string", "format": "email"},
      "phone": {"type": "string"}
    }
  },
  "rules": {
    "max_attempts": 3
  }
}
```

**Behavior:**
1. Phase completes
2. Output validated against schema using jsonschema library
3. If invalid, retry with error message
4. If valid or max_attempts, continue

**Implementation:**
- Add `output_schema` to `PhaseConfig`
- Use `jsonschema` library for validation
- Auto-retry with validation error in context
- Log schema validation results

**Dependencies:**
- Add `jsonschema` to `requirements`

---

## Phase 3: Full Wards System

Comprehensive ward system with pre/post validators and multiple modes.

### Configuration Schema

```json
{
  "name": "publish_content",
  "instructions": "Finalize blog post for publication...",

  "wards": {
    "pre": [
      {
        "validator": "input_sanitizer",
        "mode": "blocking"
      }
    ],
    "post": [
      {
        "validator": "grammar_check",
        "mode": "retry",
        "max_attempts": 2
      },
      {
        "validator": "content_safety",
        "mode": "blocking"
      },
      {
        "validator": "fact_check",
        "mode": "advisory"
      }
    ]
  }
}
```

### Ward Configuration Model

```python
class WardConfig(BaseModel):
    validator: str  # Name of validator tool/cascade
    mode: Literal["blocking", "advisory", "retry"] = "blocking"
    max_attempts: int = 1  # For retry mode

class WardsConfig(BaseModel):
    pre: List[WardConfig] = Field(default_factory=list)
    post: List[WardConfig] = Field(default_factory=list)
    turn: List[WardConfig] = Field(default_factory=list)  # Optional per-turn
```

Add to `PhaseConfig`:
```python
wards: Optional[WardsConfig] = None
```

### Execution Flow

```
Phase Start
    ↓
Pre-Wards (blocking/advisory)
    ↓ [blocking failures → abort phase]
    ↓
Phase Execution (normal)
    ↓
Post-Wards (blocking/retry/advisory)
    ↓ [blocking failures → abort]
    ↓ [retry failures → re-execute phase]
    ↓ [advisory → log only]
    ↓
Continue to Next Phase
```

### Validator Protocol

All validators (cascade tools or functions) must return:

```json
{
  "valid": true,  // or false
  "reason": "Validation passed" // or error description
  "details": {}   // Optional structured data
}
```

**Example Validator Cascade** (`tackle/grammar_check.json`):
```json
{
  "cascade_id": "grammar_check",
  "inputs_schema": {
    "text": "The text to check for grammar issues"
  },
  "phases": [{
    "name": "check",
    "instructions": "Review for grammar/spelling errors. Return JSON: {\"valid\": true/false, \"reason\": \"...\", \"issues\": []}",
    "rules": {"max_turns": 1}
  }]
}
```

---

## Phase 4: Manifest Integration

Allow Quartermaster to select appropriate wards based on content type.

### Configuration
```json
{
  "name": "publish_content",
  "instructions": "...",
  "wards": "manifest",  // Quartermaster selects wards
  "wards_context": "full"  // Current or full context
}
```

**How It Works:**
1. Quartermaster examines phase context and output
2. Views library of validator tools
3. Selects relevant validators (e.g., "blog post" → grammar_check, fact_check)
4. Returns ward configuration dynamically
5. Selected wards execute normally

**Example Validator Library Tags:**
```json
{
  "cascade_id": "grammar_check",
  "description": "Grammar and spelling validator",
  "tags": ["text", "quality", "writing"],
  "inputs_schema": {"text": "..."}
}
```

Quartermaster prompt includes tags to help selection.

---

## Phase 5: Advanced Features

### 5.1 Composite Validators

Wards can themselves be cascades with multiple phases:

```json
// tackle/comprehensive_safety.json
{
  "cascade_id": "comprehensive_safety",
  "phases": [
    {"name": "pii_check", "tackle": ["detect_pii"]},
    {"name": "toxicity_check", "tackle": ["toxicity_scorer"]},
    {"name": "bias_check", "tackle": ["bias_detector"]}
  ]
}
```

Single ward that runs multiple checks in sequence.

### 5.2 Ward Soundings

Run multiple validator variations, pick strictest:

```json
{
  "wards": {
    "post": [{
      "validator": "safety_check",
      "mode": "blocking",
      "soundings": {
        "factor": 3,
        "evaluator_instructions": "Select the most thorough safety assessment"
      }
    }]
  }
}
```

Meta-validators for critical safety checks.

### 5.3 Conditional Wards

Wards that only run under certain conditions:

```json
{
  "wards": {
    "post": [{
      "validator": "legal_review",
      "mode": "blocking",
      "condition": "{{ state.content_type == 'legal' }}"
    }]
  }
}
```

Uses Jinja2 templating for conditional logic.

### 5.4 Ward Pipelines

Sequential validation with early exit:

```json
{
  "wards": {
    "post": [
      {"validator": "quick_filter", "mode": "blocking"},  // Fast, fails fast
      {"validator": "deep_analysis", "mode": "blocking"}  // Slow, thorough
    ]
  }
}
```

If quick_filter fails, deep_analysis never runs (efficiency).

---

## Implementation Checklist

### Phase 1: Enhanced loop_until
- [ ] Add `loop_until` to `RuleConfig` in `cascade.py`
- [ ] Add `retry_instructions` to `RuleConfig`
- [ ] Implement validator call logic in `runner.py`
- [ ] Parse validator response for `valid` field
- [ ] Inject retry message if invalid
- [ ] Log validation attempts with trace IDs
- [ ] Create example validator cascade
- [ ] Test with simple use case
- [ ] Document in README/CLAUDE.md

### Phase 2: Schema Validation
- [ ] Add `jsonschema` dependency
- [ ] Add `output_schema` to `PhaseConfig`
- [ ] Implement schema validation in `runner.py`
- [ ] Auto-retry on schema failure
- [ ] Format schema errors for LLM
- [ ] Log schema validation results
- [ ] Create example with schema validation
- [ ] Test with complex nested schema
- [ ] Document schema validation

### Phase 3: Full Wards
- [ ] Create `WardConfig` and `WardsConfig` models
- [ ] Add `wards` to `PhaseConfig`
- [ ] Implement pre-ward execution
- [ ] Implement post-ward execution
- [ ] Implement blocking mode (abort on failure)
- [ ] Implement retry mode (re-execute phase)
- [ ] Implement advisory mode (async, log only)
- [ ] Create ward trace nodes for visualization
- [ ] Add ward styles to `visualizer.py`
- [ ] Create 3-5 example validator cascades
- [ ] Create comprehensive test cascade
- [ ] Test all three modes
- [ ] Document ward system
- [ ] Update CLAUDE.md with ward patterns

### Phase 4: Manifest Integration
- [ ] Add `wards: "manifest"` support to schema
- [ ] Add `wards_context` to `PhaseConfig`
- [ ] Extend `tackle_manifest.py` to include tags
- [ ] Create Quartermaster ward selection prompt
- [ ] Implement ward selection logic
- [ ] Parse and apply selected wards
- [ ] Log ward selection reasoning
- [ ] Create test with manifest wards
- [ ] Document manifest ward pattern

### Phase 5: Advanced Features (Future)
- [ ] Composite validators
- [ ] Ward soundings
- [ ] Conditional wards
- [ ] Ward pipelines
- [ ] Performance optimizations
- [ ] Caching validated outputs

---

## Example Validator Cascades to Create

### 1. Grammar Check (`tackle/grammar_check.json`)
```json
{
  "cascade_id": "grammar_check",
  "description": "Validates grammar and spelling",
  "tags": ["text", "quality", "writing"],
  "inputs_schema": {
    "text": "The text to validate"
  },
  "phases": [{
    "name": "check",
    "instructions": "Review for grammar/spelling. Return: {\"valid\": true/false, \"reason\": \"...\", \"issues\": []}",
    "rules": {"max_turns": 1}
  }]
}
```

### 2. Content Safety (`tackle/content_safety.json`)
```json
{
  "cascade_id": "content_safety",
  "description": "Checks for harmful or inappropriate content",
  "tags": ["safety", "moderation"],
  "inputs_schema": {
    "content": "The content to check"
  },
  "phases": [{
    "name": "safety_check",
    "instructions": "Check for: hate speech, violence, explicit content. Return: {\"valid\": true/false, \"reason\": \"...\"}",
    "rules": {"max_turns": 1}
  }]
}
```

### 3. Schema Validator (`tackle/json_schema_validator.json`)
```json
{
  "cascade_id": "json_schema_validator",
  "description": "Validates JSON against a schema",
  "inputs_schema": {
    "data": "JSON data to validate",
    "schema": "JSON schema to validate against"
  },
  "phases": [{
    "name": "validate",
    "instructions": "Validate data against schema. Return: {\"valid\": true/false, \"reason\": \"...\"}",
    "tackle": ["run_code"],
    "rules": {"max_turns": 2}
  }]
}
```

### 4. Fact Check (`tackle/fact_check_validator.json`)
```json
{
  "cascade_id": "fact_check_validator",
  "description": "Validates factual claims in content",
  "tags": ["accuracy", "verification"],
  "inputs_schema": {
    "content": "Content containing claims to verify",
    "domain": "Domain/topic for context"
  },
  "phases": [{
    "name": "verify",
    "instructions": "Identify claims and assess verifiability. Return: {\"valid\": true/false, \"reason\": \"...\", \"claims\": []}",
    "rules": {"max_turns": 2}
  }]
}
```

### 5. Length Validator (`tackle/length_check.json`)
```json
{
  "cascade_id": "length_check",
  "description": "Validates content length constraints",
  "inputs_schema": {
    "content": "Content to check",
    "min_length": "Minimum character count",
    "max_length": "Maximum character count"
  },
  "phases": [{
    "name": "check_length",
    "instructions": "Check if content length is between {{ input.min_length }} and {{ input.max_length }}. Return: {\"valid\": true/false, \"reason\": \"...\", \"actual_length\": N}",
    "rules": {"max_turns": 1}
  }]
}
```

---

## Testing Strategy

### Unit Tests
- Test each ward mode independently
- Test validator protocol compliance
- Test schema validation edge cases
- Test ward selection logic

### Integration Tests
- Full cascade with blocking wards
- Full cascade with retry wards
- Full cascade with advisory wards
- Mixed mode wards in single phase
- Manifest ward selection
- Nested validators (cascades as validators)

### Test Cascades
- `examples/ward_blocking_flow.json` - Demonstrates blocking mode
- `examples/ward_retry_flow.json` - Demonstrates retry mode
- `examples/ward_advisory_flow.json` - Demonstrates advisory mode
- `examples/ward_manifest_flow.json` - Demonstrates manifest selection
- `examples/ward_comprehensive_flow.json` - All modes together

---

## Visualization Strategy

### Graph Representation

**Ward nodes in Mermaid:**
```
Phase → Pre-Ward (diamond shape) → Phase Execution → Post-Ward (diamond shape) → Next Phase
                ↓ failure                                       ↓ retry
              Abort                                         Re-execute
```

**Styles:**
- `classDef ward_blocking fill:#ffcccc,stroke:#cc0000`
- `classDef ward_advisory fill:#ccffcc,stroke:#00cc00`
- `classDef ward_retry fill:#ffffcc,stroke:#cccc00`

**Node Labels:**
- `[Pre-Ward: validator_name]`
- `[Post-Ward: validator_name (FAILED)]`
- `[Advisory: validator_name (PASSED)]`

---

## Documentation Updates

### CLAUDE.md
- Add Wards section to Phase Configuration
- Document all three modes with examples
- Explain validator protocol
- Show manifest integration

### README.md
- Add Wards to Core Concepts
- Provide simple example
- Link to validator cascades
- Show common patterns

### New Docs
- `WARDS_GUIDE.md` - Comprehensive guide
  - When to use each mode
  - Creating validators
  - Common patterns
  - Best practices
  - Troubleshooting

---

## Migration Path

### Existing Features → Wards

**Sub-cascades for validation:**
```json
// Old way
{
  "sub_cascades": [{
    "ref": "validator.json",
    "context_in": true
  }]
}

// New way
{
  "wards": {
    "post": [{"validator": "validator", "mode": "blocking"}]
  }
}
```

**Async for monitoring:**
```json
// Old way
{
  "async_cascades": [{
    "ref": "monitor.json",
    "trigger": "on_end"
  }]
}

// New way
{
  "wards": {
    "post": [{"validator": "monitor", "mode": "advisory"}]
  }
}
```

Both patterns still work, but Wards is more explicit and traceable.

---

## Performance Considerations

### Optimization Strategies

1. **Lazy Validation**: Only run validators when output changes
2. **Cached Results**: Cache validator results by content hash
3. **Parallel Advisory**: Run all advisory wards in parallel
4. **Fast-Fail Blocking**: Exit on first blocking failure
5. **Incremental Schema**: Validate parts as they're generated

### Cost Management

- Advisory wards don't block, but still cost tokens
- Manifest selection adds one LLM call
- Consider validator complexity vs value
- Cache expensive validators aggressively

---

## Future Possibilities

### Self-Improving Cascades

Cascades can rewrite themselves using wards:

```json
{
  "name": "meta_optimizer",
  "instructions": "Analyze this cascade JSON and suggest improvements...",
  "tackle": ["run_code"],
  "wards": {
    "post": [{
      "validator": "cascade_validator",  // Ensures valid JSON
      "mode": "retry"
    }]
  }
}
```

Feed cascade JSON as input, get improved cascade as output, validated ward ensures it's syntactically correct.

### Learning from Failures

Log all ward failures to train better validators:
```python
# Query DuckDB logs
SELECT validator, reason, COUNT(*) as failures
FROM './logs/*.parquet'
WHERE node_type = 'ward_failure'
GROUP BY validator, reason
ORDER BY failures DESC
```

Use failure patterns to improve evaluator instructions.

### A/B Testing Validators

Use soundings to test validator variations:
```json
{
  "wards": {
    "post": [{
      "validator": "safety_check",
      "soundings": {
        "factor": 2,
        "evaluator_instructions": "Compare validator V1 vs V2 strictness"
      }
    }]
  }
}
```

Find optimal validator configuration empirically.

---

## Success Metrics

### Implementation Complete When:
- [ ] All three ward modes work
- [ ] At least 5 validator cascades created
- [ ] Schema validation working
- [ ] Manifest integration working
- [ ] Visualization shows wards clearly
- [ ] Full test coverage
- [ ] Documentation complete
- [ ] Example cascades for each pattern

### Quality Metrics:
- [ ] Ward failures are clear and actionable
- [ ] Retry mode actually improves outputs
- [ ] Advisory mode provides useful insights
- [ ] Performance overhead acceptable (<10%)
- [ ] Easy for new users to understand

---

## Nautical Theme Consistency

**Ward** - A ship's defensive barrier or protective measure. Perfect for guardrails!

**Related Terms:**
- **Watch** - Monitoring/observation (advisory mode)
- **Bulkhead** - Compartment barrier (blocking mode)
- **Bilge Pump** - Removes unwanted water (retry mode removes errors)

**Stick with "Wards"** - Clear, thematic, memorable.

---

## Conclusion

Wards complete Windlass's guardrail story:
- **Soundings** - Quality through parallel exploration
- **Manifest** - Relevance through dynamic selection
- **Wards** - Safety through validation gates

All three are:
- Declarative (JSON config)
- Composable (cascades all the way down)
- Observable (full tracing)
- Ergonomic (easy to use)

The combination creates a production-ready framework that's both powerful and approachable.

**Next session: Let's build it!** 🌊⚓🛡️
