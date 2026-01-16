# Cost Handling Fixed - Confidence Worker Now Waits for OpenRouter

**Date:** 2026-01-02
**Status:** ✅ FIXED - Cost data now consistent!

---

## The Issue

**Problem:** Cost shows as NULL/0.0 for first 3-5 seconds after execution

**Root Cause:**
1. OpenRouter API has 3-5 second delay before cost data available
2. Confidence worker was querying unified_logs immediately
3. Cost field not yet updated → shows as NULL
4. API was converting NULL → 0.0 → misleading "$0.0000"

---

## The Fix

### 1. Confidence Worker: Wait for Cost Data

**File:** `lars/confidence_worker.py`

**Added cost polling logic** (same as analytics_worker):

```python
# Poll for up to 10 seconds until cost > 0
for poll_count in range(20):  # 20 × 0.5s = 10s
    cost_check = db.query("""
        SELECT SUM(cost) as total_cost
        FROM unified_logs
        WHERE session_id = '{session_id}'
          AND role = 'assistant'
    """)

    if cost > 0:
        logger.info(f"Cost ready after {poll_count * 0.5:.1f}s: ${cost:.6f}")
        break

    time.sleep(0.5)
```

**Result:**
- Confidence worker waits for cost before querying unified_logs
- When it retrieves messages, cost is already populated
- Consistent cost data in training_annotations!

---

### 2. API: Return NULL Instead of 0.0

**File:** `studio/backend/training_api.py`

**Before:**
```python
'cost': safe_float(row.get('cost'), 0.0)  # Shows $0.0000 (misleading!)
```

**After:**
```python
'cost': safe_float(row.get('cost'), None)  # Shows null (accurate!)
```

**Result:**
- API returns `null` for cost if not available
- UI shows "—" or blank instead of "$0.0000"
- Clear distinction: null = not ready, 0.0 = actually free

---

## Timing Flow

```
1. Cascade completes
   ↓
2. runner.py triggers analytics_worker (background thread)
   ↓
3. analytics_worker._wait_for_cost_data()
   ├─ Polls every 0.5s for up to 10s
   ├─ Waits until cost > 0
   └─ Cost data ready! (typically 3-5s)
   ↓
4. analytics_worker queues confidence_worker
   ↓
5. confidence_worker._wait_for_cost_data()  ← NEW!
   ├─ Polls every 0.5s for up to 10s
   ├─ Cost already populated (from step 3)
   └─ Returns immediately (cost ready)
   ↓
6. confidence_worker queries unified_logs
   ├─ Cost field populated ✅
   ├─ Runs confidence assessment
   └─ Inserts with accurate cost context
   ↓
7. Training UI shows accurate cost data!
```

---

## Benefits

### Consistent Cost Data
- ✅ Confidence worker sees actual costs (not NULL/0)
- ✅ Can factor cost into quality assessment
- ✅ Training examples have accurate cost metadata

### Clear UI Semantics
- `null` → Data not available yet (wait a few seconds)
- `$0.0000` → Actually free (free model or cached)
- `$0.0123` → Actual cost

### No Race Conditions
- Analytics waits for cost
- Confidence waits for cost
- Both see consistent data
- No "cost available later" issues

---

## Testing

### Verify Cost Wait Works

```bash
# Run cascade and watch logs
python -c "
import logging
logging.basicConfig(level=logging.INFO)

from lars.confidence_worker import assess_training_confidence

result = assess_training_confidence('live_conf_test_001')
print(f'Result: {result}')
" 2>&1 | grep "Cost ready"

# Should see: "Cost ready after 3.5s: $0.00123"
```

### Check Training UI

```bash
# Refresh: http://localhost:5050/training

# Cost column should show:
# - null (for very recent messages, <5s old)
# - $0.0012 (for messages >5s old with cost)
# - Not "$0.0000" for everything!
```

---

## Performance Impact

**Added Wait Time:**
- Polls: 20 iterations × 0.5s = 10s max
- Typical: Exits after 3-5s (when cost ready)
- If already available: Exits immediately (1 poll)

**Total Delay:**
- Analytics already waits 3-5s for cost
- Confidence starts after analytics queues it
- By then, cost is usually ready → exits immediately!
- **No additional delay in practice**

**Cost:**
- No change - same gemini-flash-lite calls
- Just ensures we see accurate cost metadata

---

## Code Changes

**1. confidence_worker.py** (+40 lines)
- Added cost polling loop
- Logs cost ready time
- Handles deterministic cascades (cost=0 expected)

**2. training_api.py** (2 changes)
- Cost default: 0.0 → None (both endpoints)
- Shows null instead of $0.0000 for unavailable data

---

## Summary

**What we fixed:**
1. ✅ Confidence worker now waits for cost data (polls up to 10s)
2. ✅ API returns null instead of 0.0 for missing cost
3. ✅ Consistent cost data in training examples
4. ✅ Clear UI semantics (null vs 0.0)

**Result:**
- Training examples have accurate cost metadata
- No more misleading "$0.0000" for recent messages
- Confidence worker sees complete data before assessment

**This ensures high-quality training data with accurate metadata!** ✅

---

**Date:** 2026-01-02
**Status:** ✅ FIXED - Restart backend to see changes!
