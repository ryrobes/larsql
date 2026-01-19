# Validation (Wards)


Wards are protective validation barriers that ensure cell inputs and outputs meet
  your requirements. They can block execution, trigger retries, or provide advisory feedback.
On This Page
- [Ward Overview](#overview)
- [Validation Modes](#modes)
- [Polyglot Validators](#polyglot)
- [Loop Until](#loop-until)
- [Output Schema](#output-schema)


## Ward Overview


Wards validate data at three points in the cell lifecycle:
- **Pre-execution**: Validate inputs before the cell runs
- **Per-turn**: Validate after each conversation turn
- **Post-execution**: Validate final outputs


```basic ward configuration
- name: generate_report
  instructions: "Generate a financial report..."
  wards:
    - mode: retry
      max_attempts: 3
      validator:
        python: |
          return {
            "valid": len(output) > 500,
            "reason": "Report must be >500 chars"
          }
        

    - mode: blocking
      validator:
        sql: |
          SELECT
            (SELECT COUNT(*) FROM parse_json(output)
             WHERE section IS NOT NULL) >= 3 as valid,
            'Must have at least 3 sections' as reason
```

## Validation Modes


| Mode       | Behavior                        | Use Case              |
|------------|---------------------------------|-----------------------|
| `blocking` | Fails cell if validation fails  | Critical requirements |
| `retry`    | Re-runs cell up to max_attempts | Recoverable issues    |
| `advisory` | Logs warning but continues      | Quality suggestions   |


## Polyglot Validators


Validators can be written in Python, SQL, JavaScript, or Clojure:

```polyglot validators
wards:
  # Python validator
  - mode: retry
    validator:
      python: |
        import json
        try:
            data = json.loads(output)
            valid = 'summary' in data and len(data['summary']) > 100
            return {"valid": valid, "reason": "Missing or short summary"}
        except:
            return {"valid": False, "reason": "Invalid JSON"}
      

  # SQL validator
  - mode: blocking
    validator:
      sql: |
        SELECT
          CASE WHEN output LIKE '%conclusion%' THEN true ELSE false END as valid,
          'Must include a conclusion' as reason
      

  # JavaScript validator
  - mode: advisory
    validator:
      javascript: |
        const words = output.split(/\s+/).length;
        return { valid: words >= 200, reason: `Only ${words} words` };
```


> **NOTE: Validator Protocol**
>
> 
> All validators must return an object with `valid` (boolean) and
>     `reason` (string) properties.
> 


## Loop Until


The `loop_until` rule repeats a cell until a condition is met:

```loop until example
- name: refine_output
  instructions: "Improve the draft based on feedback..."
  rules:
    max_turns: 3
    loop_until: |
      {{ outputs.refine_output.quality_score | default(0) }} >= 8
    
    turn_prompt: |
      Previous score: {{ outputs.refine_output.quality_score }}
      Feedback: {{ outputs.refine_output.feedback }}
      Please address the issues and try again.
```

## Output Schema


Force structured JSON output matching a schema:

```output schema
- name: extract_entities
  instructions: "Extract entities from the text..."
  output_schema:
    type: object
    properties:
      people:
        type: array
        items:
          type: object
          properties:
            name: {type: string}
            role: {type: string}
      organizations:
        type: array
        items: {type: string}
      confidence:
        type: number
        minimum: 0
        maximum: 1
    required: [people, organizations, confidence]
```

## Next: Context Management


Learn how to control information flow with [Context Management](#context).
