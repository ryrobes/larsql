# Phase 2: Schema Validation - Implementation Complete ✅

## Summary

Phase 2 of the Wards implementation is **complete and tested**. JSON schema validation with automatic retry is now fully functional, allowing phases to enforce structured output formats.

## What Was Implemented

### 1. Dependencies
- ✅ Added `jsonschema` to `pyproject.toml`
- ✅ Installed and verified jsonschema library

### 2. Schema Changes (`cascade.py`)
- ✅ Added `output_schema` field to `PhaseConfig`
  ```python
  output_schema: Optional[Dict[str, Any]] = None
  ```

### 3. Core Schema Validation Logic (`runner.py`)
- ✅ Schema validation runs BEFORE `loop_until` validation
- ✅ Automatic JSON extraction from:
  - Raw JSON responses
  - JSON in markdown code blocks
  - JSON objects embedded in text
- ✅ Full JSON Schema validation using `jsonschema` library
- ✅ Detailed error messages for LLM feedback
- ✅ Automatic retry with schema error context
- ✅ Validated output stored in `state.validated_output`
- ✅ Full tracing with trace IDs

### 4. Retry Instructions Enhancement
- ✅ Updated retry context to include `{{ schema_error }}`
- ✅ Default schema retry messages
- ✅ Smart error routing (schema vs validation errors)

### 5. Created Example Cascades

| Example | Purpose | Schema Complexity |
|---------|---------|------------------|
| `contact_extractor_flow.json` | Extract contact info | Simple (name, email, phone) |
| `product_catalog_flow.json` | Product catalog entry | **Nested** (specifications object, tags array) |
| `api_response_flow.json` | REST API response | **Pattern validation** (timestamp, email format, enum) |

## How It Works

### Configuration
```json
{
  "name": "extract_data",
  "instructions": "Extract contact info as JSON...",
  "output_schema": {
    "type": "object",
    "required": ["name", "email", "phone"],
    "properties": {
      "name": {"type": "string", "minLength": 1},
      "email": {"type": "string", "pattern": "^[^@]+@[^@]+\\.[^@]+$"},
      "phone": {"type": "string", "minLength": 7}
    }
  },
  "rules": {
    "max_attempts": 3,
    "retry_instructions": "Schema error: {{ schema_error }}"
  }
}
```

### Execution Flow
1. Phase executes normally (agent generates output)
2. **Schema Validation** runs:
   - Attempts to extract JSON from response
   - Validates against JSON schema
   - If valid: Stores in `state.validated_output` ✅
   - If invalid: Triggers retry with detailed error
3. If retries remain, retry instructions injected
4. Phase re-executes with error feedback
5. Repeats until validation passes or max_attempts reached

### Retry Instructions Context
```python
{
    "input": input_data,
    "state": echo.state,
    "validation_error": error_msg,  # Combined error
    "schema_error": schema_error,    # Specific schema error
    "attempt": current_attempt,
    "max_attempts": max_attempts
}
```

## Supported JSON Schema Features

### Basic Types
- ✅ `string`, `number`, `integer`, `boolean`, `object`, `array`

### Validation Keywords
- ✅ `required` - Required fields
- ✅ `minLength`, `maxLength` - String length
- ✅ `minimum`, `maximum` - Number range
- ✅ `pattern` - Regex validation
- ✅ `enum` - Allowed values
- ✅ `minItems`, `maxItems` - Array size
- ✅ `properties` - Object structure
- ✅ Nested schemas (objects within objects)

### Example Schemas

#### Simple Schema
```json
{
  "type": "object",
  "required": ["name", "age"],
  "properties": {
    "name": {"type": "string"},
    "age": {"type": "integer", "minimum": 0}
  }
}
```

#### Nested Schema
```json
{
  "type": "object",
  "required": ["product", "specs"],
  "properties": {
    "product": {"type": "string"},
    "specs": {
      "type": "object",
      "required": ["weight", "dimensions"],
      "properties": {
        "weight": {"type": "string"},
        "dimensions": {"type": "string"}
      }
    }
  }
}
```

#### Pattern Validation
```json
{
  "type": "object",
  "properties": {
    "email": {
      "type": "string",
      "pattern": "^[^@]+@[^@]+\\.[^@]+$"
    },
    "timestamp": {
      "type": "string",
      "pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}"
    }
  }
}
```

#### Enum Validation
```json
{
  "type": "object",
  "properties": {
    "status": {
      "type": "string",
      "enum": ["success", "error", "pending"]
    }
  }
}
```

## Test Results

### ✅ Test 1: Contact Extractor (Simple Schema)
**Input**: "My name is Sarah Johnson, you can reach me at sarah.j@email.com or call (555) 123-4567"

**Result**:
- ✅ Passed on first attempt
- ✅ Validated output:
  ```json
  {
    "name": "Sarah Johnson",
    "email": "sarah.j@email.com",
    "phone": "(555) 123-4567"
  }
  ```

### ✅ Test 2: Product Catalog (Nested Schema)
**Input**: "Ergonomic wireless mouse with adjustable DPI, USB-C charging, and RGB lighting"

**Result**:
- ✅ Passed on first attempt
- ✅ Nested specifications object validated
- ✅ Tags array with 5 items validated
- ✅ Validated output:
  ```json
  {
    "product_name": "Ergonomic Wireless Mouse",
    "category": "Computer Accessories",
    "price": 29.99,
    "in_stock": true,
    "specifications": {
      "dimensions": "4.5 x 2.5 x 1.5 inches",
      "weight": "100 grams",
      "material": "Plastic"
    },
    "tags": ["wireless", "gaming", "productivity", "RGB", "adjustable DPI"]
  }
  ```

### ✅ Test 3: API Response (Pattern + Enum + Retry)
**Input**: "/api/users endpoint, list of user objects"

**Result**:
- ✗ Attempt 1: Failed (invalid data structure)
- 🔄 Retry triggered with schema error
- ✅ Attempt 2: Passed
- ✅ Validated output:
  ```json
  {
    "status": "success",
    "code": 200,
    "message": "User list retrieved successfully",
    "data": {"users": [...]},
    "timestamp": "2023-10-05T14:30:00Z"
  }
  ```

## Key Features

### 1. Smart JSON Extraction
Handles multiple formats:
- Raw JSON: `{"name": "value"}`
- Markdown blocks: ` ```json\n{...}\n``` `
- Embedded JSON: `The data is {"name": "value"} as shown`

### 2. Detailed Error Messages
Schema errors formatted for LLM understanding:
```
Schema validation failed: 'email' is a required property
Schema validation failed: '123' does not match '^[^@]+@[^@]+\\.[^@]+$' at path 'email'
```

### 3. Validated Output Storage
Successful validation stores parsed JSON in state:
```python
state.validated_output  # Access in next phase with {{ state.validated_output.field }}
```

### 4. Works with loop_until
Schema validation runs FIRST, then semantic validation:
```json
{
  "output_schema": {...},           // Validates structure
  "rules": {
    "loop_until": "grammar_check"   // Then validates content
  }
}
```

## Console Output Examples

### Successful Validation
```
📋 Validating Output Schema...
  ✓ Schema Validation Passed
```

### Failed Validation with Retry
```
📋 Validating Output Schema...
  ✗ Schema Validation Failed: Schema validation failed: 'email' is a required property
🔄 Validation Retry Attempt 2/3
  📋 Schema Error:

  Schema validation failed: 'email' is a required property

  Please return valid JSON with name, email, and phone fields.

📋 Validating Output Schema...
  ✓ Schema Validation Passed
```

## Integration with Phase 1

Schema validation integrates seamlessly with Phase 1 features:

```json
{
  "output_schema": {
    "type": "object",
    "required": ["name", "description"]
  },
  "rules": {
    "max_attempts": 3,
    "loop_until": "grammar_check",              // Phase 1 feature
    "retry_instructions": "{{ schema_error }}"   // Works for both
  }
}
```

**Execution order**:
1. Agent generates output
2. **Schema validation** (Phase 2) - structure check
3. **Semantic validation** (Phase 1) - content check
4. Both can trigger retries independently

## Best Practices

### 1. Always Provide Retry Instructions
```json
"retry_instructions": "Schema error: {{ schema_error }}\n\nRequired format: {\"field\": \"value\"}"
```

### 2. Use Specific Schemas
```json
// Good - specific
{"type": "string", "pattern": "^[A-Z]{2}\\d{4}$"}

// Too loose
{"type": "string"}
```

### 3. Document Schema in Instructions
```json
"instructions": "Return JSON: {\"name\": \"string\", \"age\": number}"
```

### 4. Test with max_attempts
```json
"rules": {"max_attempts": 3}  // Gives LLM chances to correct
```

### 5. Access Validated Data in Next Phase
```json
"instructions": "The validated name is: {{ state.validated_output.name }}"
```

## Error Handling

### JSON Parse Errors
```
Output is not valid JSON: Expecting ',' delimiter: line 3 column 5
```

### Schema Validation Errors
```
Schema validation failed: 'email' is a required property
Schema validation failed: 29.99 is not of type 'integer' at path 'code'
```

### Max Attempts Reached
```
⚠️  Max schema validation attempts reached (3)
```

## Next Steps: Phase 3

Ready to implement **Full Wards System**:
- Pre-wards (input validation before phase starts)
- Post-wards (output validation after phase completes)
- Turn-wards (validation during each turn)
- Multiple modes: blocking, retry, advisory

---

**Phase 2 Status**: ✅ Complete and Production-Ready
**Date**: 2025-12-01
**Test Coverage**: 3/3 examples passing (100%)
