# Critical Fixes Applied - 2025-12-07

## Issues Found & Fixed

### 1. ❌ **Phase Ordering Bug** - FIXED ✅

**Problem:** Phases were displayed in **alphabetical order** instead of **execution order**.

**Root Cause:**
```python
# OLD (WRONG):
for phase_name in sorted(phases_dict.keys()):  # Alphabetical!
```

**Fix Applied:**
```python
# NEW (CORRECT):
phase_order = []  # Track first appearance (preserves timestamp order)

# When building phases_dict:
if phase_name not in phases_dict:
    phases_dict[phase_name] = {...}
    phase_order.append(phase_name)  # Track execution order

# When building output:
for phase_name in phase_order:  # Execution order!
```

**Location:** `extras/ui/backend/app.py` lines 1665, 1681, 1954

**Impact:** Phases now display in the order they were executed in the cascade.

---

### 2. ❓ **Model Tracking** - Already Working ✅

**Question:** "Are we assuming or looking at the individual message model?"

**Answer:** We ARE looking at individual message models correctly.

**How It Works:**
```python
# Line 1727-1728 (soundings):
if pd.notna(row['model']) and not sounding['model']:
    sounding['model'] = row['model']

# Line 1731-1732 (reforge refinements):
if pd.notna(row['model']) and not refinement['model']:
    refinement['model'] = row['model']
```

**Data Flow:**
1. Query includes `model` column from each message row
2. Each sounding/refinement tracks its own model
3. Takes first non-null model value encountered
4. Different soundings CAN have different models (e.g., S0 uses gemini, S1 uses claude)

**Verification:**
```sql
SELECT phase_name, sounding_index, model
FROM file('data/*.parquet', Parquet)
WHERE sounding_index IS NOT NULL
  AND model IS NOT NULL
ORDER BY timestamp
LIMIT 20
```

Shows different models per sounding index!

---

### 3. ❓ **Reforge UI Missing** - Need to Verify

**Potential Causes:**

#### A. Backend Server Not Restarted
The backend changes require restart to take effect.

**Fix:**
```bash
cd extras/ui
# Ctrl+C to stop
./start.sh
```

#### B. No Reforge Data in Test Session
Reforge UI only appears when `phase.reforge_steps.length > 0`.

**Check:**
```bash
# Test API directly:
curl http://localhost:5001/api/soundings-tree/<your_session_id> | jq '.phases[].reforge_steps'
```

Should return array of reforge steps if data exists.

#### C. Frontend Not Refreshed
React may be caching old component.

**Fix:**
```bash
cd extras/ui/frontend
# Hard refresh browser: Ctrl+Shift+R
# Or restart dev server:
npm start
```

---

## Verification Steps

### 1. Check Phase Order Fix

**Test:**
```bash
# Run a cascade with known phase order
windlass examples/sql_chart_gen_analysis_full.json \
  --input '{"question": "test"}' \
  --session phase_order_test
```

**Expected Phase Order:**
1. discover_schema
2. write_query
3. analyze_results
4. create_initial_chart

**Verify in UI:**
- Phases should appear in execution order (1→2→3→4)
- NOT alphabetical (analyze_results, create_initial_chart, discover_schema, write_query)

### 2. Check Model Tracking

**Test:**
```bash
# Query to see different models per sounding:
python3 -c "
import chdb
df = chdb.query('SELECT phase_name, sounding_index, model FROM file(\"data/*.parquet\", Parquet) WHERE session_id = \"phase_order_test\" AND sounding_index IS NOT NULL AND model IS NOT NULL ORDER BY timestamp', 'DataFrame')
print(df.to_string())
"
```

**In UI:**
- Each sounding card should show model badge
- Different soundings may show different models
- Check tooltip on hover shows full model name

### 3. Check Reforge UI

**Requirements for Reforge UI to Appear:**
1. Cascade must have `soundings` with `reforge` configured
2. Session must have completed at least one reforge step
3. Backend must have reforge data in response

**Test Cascade:**
```bash
windlass examples/reforge_feedback_chart.json \
  --input '{"data": "test"}' \
  --session reforge_test_001
```

**Expected Structure:**
```json
{
  "phases": [{
    "soundings": [...],
    "reforge_steps": [  // THIS MUST EXIST
      {
        "step": 0,
        "honing_prompt": "...",
        "refinements": [...]
      }
    ]
  }]
}
```

**In UI:**
- Look for purple "Reforge: Winner Refinement" section
- Should appear AFTER initial soundings and evaluator reasoning
- Click to expand → see refinement steps

---

## Debug Commands

### Check API Response Structure
```bash
# Get soundings tree for a session:
curl http://localhost:5001/api/soundings-tree/<session_id> | jq '.' > debug_response.json

# Check if reforge_steps exists:
jq '.phases[].reforge_steps' debug_response.json

# Count phases:
jq '.phases | length' debug_response.json

# Show phase names in order:
jq '.phases[].name' debug_response.json
```

### Check Database for Reforge Data
```bash
python3 -c "
import chdb
df = chdb.query('SELECT phase_name, reforge_step, sounding_index FROM file(\"data/*.parquet\", Parquet) WHERE session_id = \"<your_session>\" AND reforge_step IS NOT NULL ORDER BY timestamp', 'DataFrame')
print(df.to_string())
"
```

If this returns empty → No reforge data was logged.

### Check Frontend Console
```
Open browser DevTools → Console tab
Look for errors like:
- "Cannot read property 'reforge_steps' of undefined"
- "phase.reforge_steps is not iterable"
- Network errors from API call
```

---

## Files Changed

1. **extras/ui/backend/app.py**
   - Line 1665: Added `phase_order = []`
   - Line 1681: Track phase order on first appearance
   - Line 1954: Use `phase_order` instead of `sorted(phases_dict.keys())`

2. **extras/ui/frontend/src/components/SoundingsExplorer.js**
   - Lines 318-512: Reforge section component (already added earlier)

3. **extras/ui/frontend/src/components/SoundingsExplorer.css**
   - Lines 546-725: Reforge styling (already added earlier)

---

## Next Steps

1. **Restart backend server** (critical!)
   ```bash
   cd extras/ui
   ./start.sh
   ```

2. **Hard refresh browser** (Ctrl+Shift+R)

3. **Test with a session that has soundings:**
   ```bash
   windlass examples/sql_chart_gen_analysis_full.json \
     --input '{"question": "What states have bigfoot?"}' \
     --session test_fixes_001
   ```

4. **Open Soundings Explorer in UI**
   - Check phase order (should match execution order)
   - Check model badges on soundings
   - Look for reforge section (if cascade has reforge configured)

5. **If reforge UI still missing:**
   - Check API response: `curl http://localhost:5001/api/soundings-tree/test_fixes_001 | jq '.phases[0].reforge_steps'`
   - If empty → Cascade doesn't have reforge enabled
   - If non-empty → Frontend issue, check browser console for errors

---

## Current Status

✅ Phase ordering fix applied
✅ Model tracking confirmed working
❓ Reforge UI - needs verification after server restart

**Critical:** Backend server MUST be restarted for phase ordering fix to take effect!
