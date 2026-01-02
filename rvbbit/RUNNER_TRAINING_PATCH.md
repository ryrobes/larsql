# Runner.py Training System Integration

## Modification Location

**File:** `rvbbit/runner.py`
**Line:** After 9956 (after `rendered_instructions = render_instruction(cell_instructions, render_context)`)

## Code to Add

Insert this code block immediately after line 9956:

```python
        rendered_instructions = render_instruction(cell_instructions, render_context)

        # ========== TRAINING SYSTEM: Inject examples if enabled ==========
        if hasattr(cell, 'use_training') and cell.use_training:
            try:
                from .training_system import get_training_examples, inject_training_examples_into_instructions

                # Get training configuration from cell
                training_limit = getattr(cell, 'training_limit', 5)
                training_strategy = getattr(cell, 'training_strategy', 'recent')
                training_min_confidence = getattr(cell, 'training_min_confidence', 0.8)
                training_verified_only = getattr(cell, 'training_verified_only', False)
                training_format = getattr(cell, 'training_format', 'xml')

                # Fetch training examples
                examples = get_training_examples(
                    cascade_id=self.config.cascade_id,
                    cell_name=cell.name,
                    strategy=training_strategy,
                    limit=training_limit,
                    min_confidence=training_min_confidence,
                    verified_only=training_verified_only
                )

                if examples:
                    # Inject examples into instructions
                    rendered_instructions = inject_training_examples_into_instructions(
                        original_instructions=rendered_instructions,
                        examples=examples,
                        format=training_format
                    )
                    console.print(f"{indent}[dim green]📚 Injected {len(examples)} training examples ({training_strategy} strategy)[/dim green]")
                else:
                    console.print(f"{indent}[dim yellow]📚 No training examples available yet[/dim yellow]")

            except Exception as e:
                # Non-blocking: Don't crash if training fails
                console.print(f"{indent}[yellow]⚠️  Training example injection failed: {e}[/yellow]")
                log.warning(f"[training] Failed to inject examples for {cell.name}: {e}")

        # Apply mutation if provided (for candidate variations)
        if mutation:
            ...
```

## Cascade Model Definition (cascade.py)

Add these fields to the `CellConfig` class in `rvbbit/cascade.py`:

```python
class CellConfig(BaseModel):
    # ... existing fields ...

    # Training System (Universal Few-Shot Learning)
    use_training: bool = False                    # Enable training example injection
    training_limit: int = 5                       # Max number of examples
    training_strategy: str = 'recent'             # 'recent', 'high_confidence', 'random', 'semantic'
    training_min_confidence: float = 0.8          # Minimum confidence threshold
    training_verified_only: bool = False          # Only use human-verified examples
    training_format: str = 'xml'                  # Format: 'xml', 'markdown', 'few_shot'
```

## Testing

Test with a simple cascade:

```yaml
cascade_id: test_training

cells:
  - name: classifier
    model: google/gemini-2.5-flash-lite
    use_training: true              # Enable training
    training_limit: 3
    training_strategy: recent
    instructions: |
      Classify the following text into one of these categories: positive, negative, neutral

      Text: {{ input.text }}

      Return ONLY the category name.
```

Run twice:
1. First run: No examples (creates first execution log)
2. Mark first execution as trainable: `mark_as_trainable(['trace-id'], trainable=True)`
3. Second run: Uses first execution as training example!
