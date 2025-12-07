# Soundings Explorer Integration Guide

## Overview

The **Soundings Explorer** is a full-screen modal that visualizes all soundings across all phases in a cascade execution. It shows the decision tree, winner path, eval reasoning, and allows drill-down into individual attempts.

## Features

✅ **Vertical phase timeline** - All phases stacked
✅ **Horizontal sounding spread** - Side-by-side comparison
✅ **Visual winner highlighting** - Green borders, trophy icons
✅ **Failed attempt markers** - Red borders, strikethrough
✅ **Click-to-expand** - Drill into messages, tools, output
✅ **Eval reasoning display** - Shows why winner was chosen
✅ **Winner path summary** - End-to-end decision trail

## Frontend Integration

### 1. Add Button to InstancesView

Update `InstancesView.js` to add a "Explore Soundings" button:

```javascript
// At top of file
import SoundingsExplorer from './SoundingsExplorer';

// Add state
const [soundingsExplorerSession, setSoundingsExplorerSession] = useState(null);

// Add button in instance-actions-row (around line 292)
<div className="instance-actions-row">
  {instance.models_used?.length > 0 && (
    <div className="models-used">
      {/* ... existing code ... */}
    </div>
  )}

  {/* NEW: Soundings Explorer Button */}
  {instance.has_soundings && (
    <button
      className="soundings-explorer-button"
      onClick={(e) => {
        e.stopPropagation();
        setSoundingsExplorerSession(instance.session_id);
      }}
      title="Explore soundings decision tree"
    >
      <Icon icon="mdi:sign-direction" width="14" />
      Soundings
    </button>
  )}

  <button className="rerun-button-small" /* ... existing ... */>
    {/* ... */}
  </button>
</div>

// Add modal at bottom of render (around line 560)
{soundingsExplorerSession && (
  <SoundingsExplorer
    sessionId={soundingsExplorerSession}
    onClose={() => setSoundingsExplorerSession(null)}
  />
)}
```

### 2. Add CSS for Button

In `InstancesView.css`:

```css
.soundings-explorer-button {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  background: rgba(78, 201, 176, 0.1);
  border: 1px solid rgba(78, 201, 176, 0.3);
  border-radius: 5px;
  color: #4ec9b0;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.soundings-explorer-button:hover {
  background: rgba(78, 201, 176, 0.2);
  border-color: #4ec9b0;
  transform: translateY(-1px);
}
```

## Backend Implementation

### 1. Add Endpoint: `/api/soundings-tree/<session_id>`

Create in `extras/ui/backend/app.py`:

```python
@app.route('/api/soundings-tree/<session_id>', methods=['GET'])
def get_soundings_tree(session_id):
    """
    Returns hierarchical soundings data for visualization.

    Response format:
    {
      "phases": [
        {
          "name": "discover_schema",
          "soundings": [
            {
              "index": 0,
              "cost": 0.0012,
              "turns": [...],
              "is_winner": false,
              "failed": false,
              "output": "...",
              "tool_calls": ["sql_search", "list_sql_connections"],
              "error": null
            },
            {
              "index": 1,
              "cost": 0.0015,
              "turns": [...],
              "is_winner": false,
              "failed": false,
              "output": "...",
              "tool_calls": ["sql_search"],
              "error": null
            },
            {
              "index": 2,
              "cost": 0.0011,
              "turns": [...],
              "is_winner": true,  // <- Winner!
              "failed": false,
              "output": "...",
              "tool_calls": ["sql_search", "sql_rag_search"],
              "error": null
            }
          ],
          "eval_reasoning": "S2 found the most relevant tables by using sql_rag_search to understand data distributions. It identified bigfoot_sightings as the primary table with 4,586 rows covering all US states..."
        },
        {
          "name": "write_query",
          "soundings": [...]
        }
      ],
      "winner_path": [
        {"phase_name": "discover_schema", "sounding_index": 2},
        {"phase_name": "write_query", "sounding_index": 1},
        {"phase_name": "analyze_results", "sounding_index": 3}
      ]
    }
    """
    try:
        # Query unified logs for soundings data
        query = f"""
        SELECT
            phase_name,
            sounding_index,
            is_winner,
            content_json,
            cost,
            tool_calls_json,
            turn_number,
            metadata_json
        FROM unified_logs
        WHERE session_id = '{session_id}'
          AND node_type = 'phase'
          AND sounding_index IS NOT NULL
        ORDER BY phase_name, sounding_index, turn_number
        """

        from windlass.unified_logs import query_unified
        df = query_unified(query)

        if df.empty:
            return jsonify({"phases": [], "winner_path": []})

        # Group by phase
        phases_dict = {}
        winner_path = []

        for _, row in df.iterrows():
            phase_name = row['phase_name']
            sounding_idx = row['sounding_index']

            if phase_name not in phases_dict:
                phases_dict[phase_name] = {
                    'name': phase_name,
                    'soundings': {},
                    'eval_reasoning': None
                }

            if sounding_idx not in phases_dict[phase_name]['soundings']:
                phases_dict[phase_name]['soundings'][sounding_idx] = {
                    'index': sounding_idx,
                    'cost': 0,
                    'turns': [],
                    'is_winner': row['is_winner'],
                    'failed': False,
                    'output': '',
                    'tool_calls': [],
                    'error': None
                }

            sounding = phases_dict[phase_name]['soundings'][sounding_idx]

            # Accumulate data
            sounding['cost'] += row.get('cost', 0)
            sounding['turns'].append({
                'turn': row.get('turn_number', 0),
                'cost': row.get('cost', 0)
            })

            # Parse content
            try:
                content = json.loads(row['content_json']) if row['content_json'] else {}
                if isinstance(content, str):
                    sounding['output'] += content + '\n'
                elif isinstance(content, dict) and 'content' in content:
                    sounding['output'] += content['content'] + '\n'
            except:
                pass

            # Parse tool calls
            try:
                tool_calls = json.loads(row['tool_calls_json']) if row['tool_calls_json'] else []
                for tool_call in tool_calls:
                    if isinstance(tool_call, dict) and 'tool' in tool_call:
                        if tool_call['tool'] not in sounding['tool_calls']:
                            sounding['tool_calls'].append(tool_call['tool'])
            except:
                pass

            # Track winner path
            if row['is_winner'] and phase_name not in [w['phase_name'] for w in winner_path]:
                winner_path.append({
                    'phase_name': phase_name,
                    'sounding_index': sounding_idx
                })

        # Query for eval reasoning (evaluator agent messages)
        eval_query = f"""
        SELECT
            phase_name,
            content_json
        FROM unified_logs
        WHERE session_id = '{session_id}'
          AND node_type = 'evaluator'
        ORDER BY timestamp
        """

        eval_df = query_unified(eval_query)

        for _, row in eval_df.iterrows():
            phase_name = row['phase_name']
            if phase_name in phases_dict:
                try:
                    content = json.loads(row['content_json']) if row['content_json'] else {}
                    if isinstance(content, str):
                        phases_dict[phase_name]['eval_reasoning'] = content
                    elif isinstance(content, dict) and 'content' in content:
                        phases_dict[phase_name]['eval_reasoning'] = content['content']
                except:
                    pass

        # Convert dicts to lists
        phases = []
        for phase_name in sorted(phases_dict.keys()):
            phase = phases_dict[phase_name]
            phase['soundings'] = sorted(
                phase['soundings'].values(),
                key=lambda s: s['index']
            )
            phases.append(phase)

        return jsonify({
            'phases': phases,
            'winner_path': winner_path
        })

    except Exception as e:
        print(f"[ERROR] Failed to get soundings tree: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
```

### 2. Update Instance Query to Include `has_soundings` Flag

In your existing cascade instances endpoint, add:

```python
# Check if instance has soundings
has_soundings = df[df['sounding_index'].notna()].shape[0] > 0

instance_data['has_soundings'] = has_soundings
```

## Usage

1. **Run a cascade with soundings** (like the updated `sql_chart_gen_analysis_full.json`)
2. **Open InstancesView** for that cascade
3. **Click "Soundings" button** on an instance row
4. **Modal opens** showing full decision tree
5. **Click any sounding card** to expand and see details
6. **View eval reasoning** to understand why winner was chosen
7. **Winner path** shown at bottom with total cost

## Visual Features

### Color Coding
- **Green border + 🏆**: Winner
- **Gray**: Not selected (valid but lost)
- **Red border + strikethrough**: Failed (syntax error, exception)

### Layout
- **Horizontal**: Soundings within a phase (compare side-by-side)
- **Vertical**: Phases (timeline top-to-bottom)
- **Expandable cards**: Click to see full output, tool calls, errors

### Hover States
- Cards lift up on hover
- Border glows
- Clear visual feedback

## Enterprise Value

This visualization provides:

1. **Explainability** - "Why did the system choose this path?"
2. **Debugging** - "Which sounding failed and why?"
3. **Cost analysis** - "Which attempts were expensive?"
4. **Quality assessment** - "Did the evaluator pick correctly?"
5. **Training data** - "What patterns lead to winning soundings?"

## Example Query Result

For a cascade with 4→5→4 soundings:

```
Phase 1: discover_schema (4 soundings)
  S0: $0.0012 (not selected) - Found wrong table
  S1: $0.0015 (not selected) - Good but verbose
  S2: $0.0011 (WINNER 🏆) - Found best table, concise
  S3: $0.0018 (not selected) - Missed key columns

Phase 2: write_query (5 soundings)
  S0: $0.0030 (not selected) - Works but slow
  S1: $0.0040 (WINNER 🏆) - Fast, correct syntax
  S2: FAILED ✗ - Syntax error
  S3: $0.0050 (not selected) - Correct but inefficient
  S4: $0.0030 (not selected) - Missing filters

Phase 3: analyze_results (4 soundings)
  ...

Winner Path: S2 → S1 → S3 → S1  (Total: $0.0234)
```

## Future Enhancements

- **Sankey diagram** view (flow visualization)
- **Eval score breakdown** (if structured scoring)
- **Cost comparison charts** (bar chart of all attempts)
- **Export to JSON** (for analysis)
- **Search/filter** (find specific tool calls or errors)
- **Diff view** (compare two soundings side-by-side)
