# Eject Command


Copy built-in cascades, skills, and cell types to your workspace for customization.
  Your local versions override the built-ins, enabling full control without modifying the package.
On This Page
- [Overview](#overview)
- [Why Eject?](#why-eject)
- [Command Reference](#command-reference)
- [Resource Types](#resource-types)
- [Common Targets](#common-targets)
- [Override Mechanism](#override-mechanism)
- [Examples](#examples)


## Overview


LARS ships with ~100 semantic SQL operators, example cascades, skills, and cell type definitions
  bundled inside the Python package. The `lars eject` command copies these built-in
  resources to your project workspace where you can modify them.

```basic usage
lars eject <target> [OPTIONS]
```


> **NOTE: Non-Destructive**
>
> 
> Ejecting never modifies the built-in package files. It only copies files to your workspace.
>     By default, existing files are skipped unless you use `--force`.
> 


## Why Eject?


#### Customize Operators


Modify semantic SQL operator prompts, models, or behavior for your domain

#### Optimize Performance


Swap models (e.g., use a faster model for simple operators)

#### Use as Templates


Start from working examples instead of writing from scratch

#### Version Control


Track your customizations in git alongside your project code

## Command Reference


```syntax
lars eject <target> [--type TYPE] [--force] [--list]
```

### Arguments


| Argument | Description                                                                          |
|----------|--------------------------------------------------------------------------------------|
| `target` | What to eject: `all`, `semantic_sql`, `examples`, a specific name, or a glob pattern |


### Options


| Option          | Description                                                                     |
|-----------------|---------------------------------------------------------------------------------|
| `--list`, `-l`  | List all available built-in resources without ejecting                          |
| `--type`, `-t`  | Filter by resource type: `cascades`, `skills`, `cell_types`, or `all` (default) |
| `--force`, `-f` | Overwrite existing files in workspace (default: skip existing)                  |


## Resource Types


LARS organizes built-in resources into three categories, each with its own source and destination:


| Type         | Count | Destination     | Contents                                                     |
|--------------|-------|-----------------|--------------------------------------------------------------|
| `cascades`   | ~280  | `./cascades/`   | Semantic SQL operators, examples, assistant workflows        |
| `skills`     | ~40   | `./skills/`     | Cascade-based tools, declarative tools, validators           |
| `cell_types` | ~26   | `./cell_types/` | Cell type definitions (llm_cell, hitl_screen, browser, etc.) |


### Cascades Subdirectories


The cascades directory contains several important subdirectories:


| Directory       | Contents                                                            |
|-----------------|---------------------------------------------------------------------|
| `semantic_sql/` | ~100 semantic SQL operator cascades (MEANS, ABOUT, SUMMARIZE, etc.) |
| `examples/`     | Example cascades for learning and templates                         |
| `internal/`     | Internal helper cascades used by the framework                      |
| `smart_search/` | Intelligent search cascades                                         |


## Common Targets


### all


Eject everything — all cascades, skills, and cell types.

```bash
lars eject all
```

### semantic_sql


Eject all ~100 semantic SQL operator cascades. This is the most common use case.

```bash
lars eject semantic_sql
```


Operators are copied to `./cascades/semantic_sql/`:

```output
Ejecting semantic SQL operators...
  Ejected: cascades/semantic_sql/semantic_matches.cascade.yaml
  Ejected: cascades/semantic_sql/sentiment.cascade.yaml
  Ejected: cascades/semantic_sql/summarize.cascade.yaml
  ...

==================================================
Ejected 100 files
```

### examples


Eject example cascades to learn from or use as templates.

```bash
lars eject examples
```

### Specific Operator


Eject a single operator by name (without the `.cascade.yaml` extension).

```bash
# Eject just the MEANS operator
lars eject semantic_matches

# Eject the SUMMARIZE aggregate
lars eject summarize
```

### Pattern Matching


Use glob patterns to eject multiple related files.

```bash
# Eject all dimension operators
lars eject "dimension_*"

# Eject all sentiment-related operators
lars eject "sentiment*"

# Eject all cluster/clustering operators
lars eject "cluster*"
```

## Override Mechanism


When LARS loads resources, it searches directories in a specific order. The first match wins:

```search order
1. ./cascades/          # User workspace (highest priority)
2. $LARS_ROOT/cascades/ # Project root if different
3. builtin_cascades/    # Package built-ins (lowest priority)
```


> **TIP: Selective Override**
>
> 
> You don't need to eject everything. Eject only the operators you want to customize.
>     LARS will use your local version for those and the built-in version for the rest.
> 


### Example: Customizing MEANS


```bash
# Eject the MEANS operator
lars eject semantic_matches

# Now edit your local copy
vim cascades/semantic_sql/semantic_matches.cascade.yaml
```


Common customizations:

```cascades/semantic_sql/semantic_matches.cascade.yaml
cascade_id: semantic_matches
sql_function:
  name: semantic_matches
  shape: SCALAR
  returns: BOOLEAN

cells:
  - name: evaluate
    # Change the model for faster/cheaper evaluation
    model: google/gemini-2.5-flash-lite  # Was: anthropic/claude-sonnet

    # Customize the prompt for your domain
    instructions: |
      You are evaluating product descriptions for an e-commerce site.
      Does the text semantically match the given criterion?

      TEXT: {{ input.text }}
      CRITERION: {{ input.criterion }}

      Consider industry terminology and common variations.
      Respond with ONLY "true" or "false".
```

## Examples


### List Available Resources


```bash
lars eject --list
```

```output
Available builtin resources:

CASCADES:
--------------------------------------------------
  semantic_sql/ (100 files)
  examples/ (15 files)
  internal/ (3 files)
  smart_search/ (4 files)
  (root) (12 files)

  Total: 134 files

SKILLS:
--------------------------------------------------
  (root) (39 files)

  Total: 39 files

CELL_TYPES:
--------------------------------------------------
  (root) (26 files)

  Total: 26 files

Usage examples:
  lars eject all                    # Eject everything
  lars eject semantic_sql           # Eject all semantic SQL operators
  lars eject semantic_matches       # Eject a specific operator
  lars eject examples               # Eject example cascades
  lars eject --type skills          # Eject only skills
```

### Eject Only Skills


```bash
lars eject all --type skills
```

### Force Overwrite


```bash
# Reset to built-in versions, overwriting your changes
lars eject semantic_sql --force
```

### Eject Cell Types for Customization


```bash
# Eject the LLM cell type to customize default behavior
lars eject llm_cell --type cell_types

# Eject browser cell type to modify automation settings
lars eject browser --type cell_types
```

### Workflow: Customize an Operator


```complete workflow
# 1. See what's available
lars eject --list

# 2. Eject the operator you want to customize
lars eject summarize

# 3. Edit the local copy
vim cascades/semantic_sql/summarize.cascade.yaml

# 4. Test your changes
psql -h localhost -p 15432 -d default -c "
  SELECT SUMMARIZE(description) FROM products GROUP BY category
"

# 5. Commit to version control
git add cascades/semantic_sql/summarize.cascade.yaml
git commit -m "Customize SUMMARIZE for product descriptions"
```


> **WARNING: Upgrade Considerations**
>
> 
> When you upgrade LARS, your ejected files remain unchanged. This means you keep your
>     customizations, but you also won't get improvements to built-in operators automatically.
>     Use `lars eject <target> --force` to reset specific operators to the new
>     built-in versions if needed.
> 


## Related
- [Semantic SQL](#semantic-sql) — How semantic operators work
- [Built-in Operators](#operators) — Reference for all 100+ operators
- [Tools (Skills)](#tools) — The skill/tool system
- [Cell Types](#cell-types) — Cell type definitions
