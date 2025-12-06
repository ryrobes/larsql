# Cascade Soundings Bug Analysis

## Problem

Cascade-level soundings create child cascades with unique session IDs (e.g., `parent_sounding_0`, `parent_sounding_1`), but when querying the database, ALL records from those child cascades have `parent_session_id = None` instead of `parent_session_id = 'parent'`.

This breaks the UI's ability to find and display sub-cascades because the UI queries for records with `parent_session_id = 'parent_id'` and finds nothing.

## Root Cause

**Bug Location:** `windlass/echo.py` - `SessionManager.get_session()` method

**Current Code (lines 188-191):**
```python
def get_session(self, session_id: str, parent_session_id: str = None) -> Echo:
    if session_id not in self.sessions:
        self.sessions[session_id] = Echo(session_id, parent_session_id=parent_session_id)
    return self.sessions[session_id]
```

**The Problem:**
If `get_echo(session_id, parent_session_id=X)` is called multiple times, only the FIRST call's `parent_session_id` value is preserved. Subsequent calls with different `parent_session_id` values are ignored because the method just returns the existing session without updating it.

**Test Case That Reproduces The Bug:**
```python
from windlass.echo import get_echo, _session_manager

_session_manager.sessions.clear()

# First call with parent_session_id=None
echo1 = get_echo("child_session", parent_session_id=None)
print(f"echo1.parent_session_id = {echo1.parent_session_id}")  # None

# Second call with parent_session_id='parent'
echo2 = get_echo("child_session", parent_session_id='parent')
print(f"echo2.parent_session_id = {echo2.parent_session_id}")  # Still None!
print(f"Same object? {echo1 is echo2}")  # True
```

Output:
```
echo1.parent_session_id = None
echo2.parent_session_id = None  # BUG: Should be 'parent'!
Same object? True
```

## Why Cascade Soundings Are Affected

In `runner.py` `_run_with_cascade_soundings()` (line 269+):

1. **Line 305-307:** Creates `sounding_echo = Echo(sounding_session_id, parent_session_id=self.session_id)` directly (doesn't register it)
2. **Line 311-320:** Creates `WindlassRunner(session_id=sounding_session_id, parent_session_id=self.session_id)`
3. **Runner.__init__ line 89:** Calls `self.echo = get_echo(session_id, parent_session_id=parent_session_id)`

The flow SHOULD work correctly, but somewhere in the execution, `get_echo(sounding_session_id)` is being called WITHOUT `parent_session_id`, and this happens BEFORE the runner initializes. This creates the echo with `parent_session_id=None`, and then when the runner tries to set it correctly, it's too late - the session already exists with None.

## Solution

Update `SessionManager.get_session()` to handle `parent_session_id` updates:

```python
def get_session(self, session_id: str, parent_session_id: str = None) -> Echo:
    if session_id not in self.sessions:
        # New session - create with parent_session_id
        self.sessions[session_id] = Echo(session_id, parent_session_id=parent_session_id)
    elif parent_session_id is not None and self.sessions[session_id].parent_session_id is None:
        # Session exists but has no parent_session_id set - update it
        self.sessions[session_id].parent_session_id = parent_session_id
    return self.sessions[session_id]
```

**Logic:**
- If session doesn't exist: create it with the provided `parent_session_id`
- If session exists AND we're providing a non-None `parent_session_id` AND the session currently has None: update it
- Otherwise: return existing session unchanged

This ensures that if a session is accidentally created with `parent_session_id=None` first, a subsequent call with the correct parent_session_id will fix it.

## Verification

After applying the fix, run:
```bash
cd windlass
python3 test_cascade_soundings_bug.py
```

Expected output after fix:
```
echo1.parent_session_id = None
echo2.parent_session_id = parent  # FIXED!
Same object? True
```

Then test with actual cascade soundings:
```bash
windlass examples/cascade_soundings_test.json --input '{"problem": "Test"}' --session test_fix_verify
```

Query database to verify parent_session_id is set:
```python
from windlass.unified_logs import query_unified
df = query_unified("session_id = 'test_fix_verify_sounding_0'")
print(df['parent_session_id'].unique())  # Should show ['test_fix_verify'], not [None]
```

## Impact

This fix will:
- ✅ Allow cascade-level soundings to appear as nested sub-cascades in the UI
- ✅ Enable proper parent-child session queries
- ✅ Not break existing functionality (defensive - only updates None to a value, never overwrites existing non-None values)
- ✅ Fix validators and other sub-cascades if they had the same issue

## Files To Modify

1. `windlass/windlass/echo.py` - Fix `SessionManager.get_session()` method
2. (Optional) Remove line 307 in `windlass/windlass/runner.py` - the unused `sounding_echo` creation
