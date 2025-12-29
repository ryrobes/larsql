# Declarative Phase Types

Phase types are defined as YAML files that provide:
- **Metadata**: Icon, color, name prefix, description
- **Template**: Default YAML structure for new phases

## Structure

```yaml
type_id: my_custom_phase    # Unique identifier
display_name: My Phase       # Shown in UI
icon: mdi:star              # Iconify icon name
color: "#a78bfa"            # Hex color for sidebar
name_prefix: custom         # Generates: custom_1, custom_2, etc.
description: "Does X"        # Tooltip/help text
category: "tools"           # Grouping category

template:                   # YAML template for new phases
  instructions: "..."       # (or tool/inputs for data phases)
  model: "..."
  tackle: []
```

## Template Variables

Use these in your templates for dynamic substitution:
- `{{PHASE_NAME}}` - Replaced with generated phase name (e.g., `sql_3`)
- `{{CASCADE_ID}}` - Replaced with current cascade ID

## Categories

- `llm` - LLM-based phases
- `data` - Data transformation phases (SQL, Python, etc.)
- `tools` - Tool/automation phases

## Adding Custom Types

1. Create `my_type.yaml` in this directory
2. Restart backend (auto-loads on startup)
3. New type appears in sidebar immediately

## Examples

See existing files for reference:
- `llm_phase.yaml` - Basic LLM
- `sql_data.yaml` - SQL query
- `llm_soundings.yaml` - Pre-configured soundings
