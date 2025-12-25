# Session Database Discovery via PostgreSQL

## 🎯 **The Opportunity**

RVBBIT creates **206 session databases** in `session_dbs/` containing:
- Cascade execution temp tables (`_phase_name`)
- Intermediate data between phases
- Debug artifacts

**Current state:** These are invisible from PostgreSQL server!

**Vision:** Make them discoverable and queryable in DBeaver!

---

## 💡 **Proposed Solutions**

### **Option 1: Auto-ATTACH Recent Sessions (Recommended)**

**Idea:** Automatically ATTACH sessions from last 7 days on server startup

**Implementation:**
```python
def setup_session(self):
    # ... existing setup ...

    # Auto-ATTACH recent cascade sessions
    self._attach_recent_sessions(max_age_days=7, max_count=50)

def _attach_recent_sessions(self, max_age_days=7, max_count=50):
    """ATTACH recent cascade session databases as schemas."""
    import os
    from pathlib import Path
    import time

    session_db_dir = Path(config.root_dir) / 'session_dbs'
    now = time.time()
    age_cutoff = now - (max_age_days * 86400)

    # Find recent session DBs
    recent_sessions = []
    for db_file in session_db_dir.glob('*.duckdb'):
        if db_file.stat().st_mtime > age_cutoff:
            recent_sessions.append(db_file)

    # Limit to max_count most recent
    recent_sessions.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    recent_sessions = recent_sessions[:max_count]

    # ATTACH each one
    for db_file in recent_sessions:
        session_name = db_file.stem  # e.g., 'agile-cardinal-490cb1'
        try:
            self.duckdb_conn.execute(f"ATTACH '{db_file}' AS {session_name}")
            print(f"[{self.session_id}]      ✓ Attached session: {session_name}")
        except:
            pass  # Skip if already attached or error
```

**Result in DBeaver:**
```
📁 Schemas
  ├── 📁 main
  ├── 📁 agile-cardinal-490cb1    ← Recent cascade session!
  │   └── 📁 Tables
  │       ├── _extract_data
  │       ├── _transform
  │       └── _output
  ├── 📁 cascade_udf_2f199f63
  └── ...50 recent sessions
```

**Pros:**
- ✅ Automatic discovery
- ✅ Recent sessions (debugging current work)
- ✅ Limited count (50 schemas, manageable)

**Cons:**
- ⚠️ Still a lot of schemas
- ⚠️ Older sessions invisible

---

### **Option 2: Session Browser Table (Clean & Scalable)**

**Idea:** Create a special table `rvbbit_sessions` that lists ALL sessions, then ATTACH on-demand

**Implementation:**
```python
def setup_session(self):
    # ... existing setup ...

    # Create session browser table
    self._create_session_browser_table()

def _create_session_browser_table(self):
    """Create a table listing all available session databases."""
    import os
    from pathlib import Path
    import pandas as pd

    session_db_dir = Path(config.root_dir) / 'session_dbs'

    # Scan all session DB files
    sessions = []
    for db_file in session_db_dir.glob('*.duckdb'):
        stat = db_file.stat()
        sessions.append({
            'session_id': db_file.stem,
            'file_path': str(db_file),
            'size_mb': stat.st_size / 1024 / 1024,
            'created_at': pd.Timestamp.fromtimestamp(stat.st_ctime),
            'modified_at': pd.Timestamp.fromtimestamp(stat.st_mtime),
            'is_attached': False  # Initially not attached
        })

    # Create temp table
    sessions_df = pd.DataFrame(sessions)
    self.duckdb_conn.execute("CREATE OR REPLACE TABLE _rvbbit_sessions AS SELECT * FROM sessions_df")

    print(f"[{self.session_id}]   ✓ Session browser created ({len(sessions)} sessions)")
```

**Usage in DBeaver:**

```sql
-- 1. Browse all sessions
SELECT session_id, size_mb, modified_at
FROM _rvbbit_sessions
ORDER BY modified_at DESC
LIMIT 20;

-- 2. Find sessions with specific data
SELECT session_id
FROM _rvbbit_sessions
WHERE session_id LIKE '%cascade%'
ORDER BY modified_at DESC;

-- 3. ATTACH a specific session
ATTACH 'session_dbs/agile-cardinal-490cb1.duckdb' AS my_debug_session;

-- 4. Now browse it!
SELECT * FROM my_debug_session.main._extract_data;
```

**Result in DBeaver:**

```
📁 Schemas
  ├── 📁 main
  │   ├── test_demo
  │   ├── my_test
  │   └── _rvbbit_sessions  ← Browse ALL sessions!
  └── 📁 my_debug_session   ← On-demand ATTACH
      └── 📁 Tables
          ├── _extract_data
          └── _transform
```

**Pros:**
- ✅ Clean (only 1 extra table by default)
- ✅ Scalable (browse 206 sessions easily)
- ✅ On-demand (ATTACH only what you need)
- ✅ Search/filter sessions by date, size, name

**Cons:**
- ⚠️ Two-step process (browse, then ATTACH)

---

### **Option 3: Smart Auto-ATTACH (Hybrid)**

**Idea:** Combine both approaches!

**Rules:**
1. Auto-ATTACH **named sessions** (e.g., `cascade_test`, `my_debug_session`)
2. Auto-ATTACH **recent unnamed sessions** (last 24 hours, max 10)
3. List **all sessions** in `_rvbbit_sessions` table
4. User can ATTACH any session manually

**Implementation:**

```python
def _attach_sessions_smart(self):
    """Smart session ATTACH: named + recent, plus browser table."""
    import os
    from pathlib import Path
    import time
    import pandas as pd

    session_db_dir = Path(config.root_dir) / 'session_dbs'
    now = time.time()

    all_sessions = []
    auto_attach_sessions = []

    for db_file in session_db_dir.glob('*.duckdb'):
        session_id = db_file.stem
        stat = db_file.stat()
        age_hours = (now - stat.st_mtime) / 3600

        # Skip PostgreSQL client sessions
        if session_id.startswith('pg_client_'):
            continue

        all_sessions.append({
            'session_id': session_id,
            'file_path': str(db_file),
            'size_mb': round(stat.st_size / 1024 / 1024, 2),
            'age_hours': round(age_hours, 1),
            'is_named': not any(c in session_id for c in ['-', '_', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9'])
        })

        # Auto-ATTACH if:
        # 1. Named session (e.g., cascade_test, my_experiment)
        # 2. Recent unnamed session (< 24 hours old, max 10)
        is_named = '_' in session_id and '-' not in session_id  # cascade_test, not agile-cardinal-490cb1
        is_recent = age_hours < 24

        if is_named or (is_recent and len([s for s in auto_attach_sessions if not s['is_named']]) < 10):
            auto_attach_sessions.append({
                'session_id': session_id,
                'file_path': str(db_file),
                'is_named': is_named
            })

    # Auto-ATTACH selected sessions
    for session in auto_attach_sessions:
        try:
            self.duckdb_conn.execute(f"ATTACH '{session['file_path']}' AS {session['session_id']}")
            print(f"[{self.session_id}]      ✓ Auto-attached: {session['session_id']} ({'named' if session['is_named'] else 'recent'})")
        except Exception as e:
            print(f"[{self.session_id}]      ⚠️ Could not attach {session['session_id']}: {e}")

    # Create browser table for ALL sessions
    sessions_df = pd.DataFrame(all_sessions)
    self.duckdb_conn.execute("CREATE OR REPLACE TABLE _rvbbit_sessions AS SELECT * FROM sessions_df")

    print(f"[{self.session_id}]   ✓ Session discovery: {len(auto_attach_sessions)} auto-attached, {len(all_sessions)} browsable")
```

**Result in DBeaver:**

```
📁 Schemas
  ├── 📁 main
  │   ├── test_demo
  │   ├── my_test
  │   └── _rvbbit_sessions        ← Browse ALL 206 sessions!
  ├── 📁 cascade_test             ← Named session (auto-attached)
  │   └── _test_data
  ├── 📁 my_experiment            ← Named session (auto-attached)
  │   └── _results
  ├── 📁 alert-skunk-55e63e       ← Recent session (auto-attached)
  │   ├── _extract
  │   └── _transform
  └── ... (up to 10 recent unnamed sessions)
```

**Pros:**
- ✅ Named sessions always visible (for debugging specific cascades)
- ✅ Recent sessions visible (for current work)
- ✅ All sessions browsable via table
- ✅ Limited schema bloat (~20 schemas max)

---

### **Option 4: UDF for On-Demand ATTACH**

**Idea:** Create `rvbbit_attach_session()` function

**Implementation:**

```python
def register_session_attach_udf(conn):
    """Register UDF to ATTACH sessions on-demand."""
    def attach_session(session_id: str) -> str:
        """ATTACH a cascade session database."""
        from pathlib import Path
        from rvbbit.config import get_config

        config = get_config()
        session_file = Path(config.root_dir) / 'session_dbs' / f'{session_id}.duckdb'

        if not session_file.exists():
            return f"ERROR: Session '{session_id}' not found"

        try:
            conn.execute(f"ATTACH '{session_file}' AS {session_id}")
            return f"SUCCESS: Attached '{session_id}'"
        except Exception as e:
            return f"ERROR: {str(e)}"

    conn.create_function('rvbbit_attach_session', attach_session)
```

**Usage:**

```sql
-- Browse available sessions
SELECT * FROM _rvbbit_sessions ORDER BY modified_at DESC LIMIT 20;

-- ATTACH specific session
SELECT rvbbit_attach_session('agile-cardinal-490cb1');
-- Returns: "SUCCESS: Attached 'agile-cardinal-490cb1'"

-- Now query it!
SELECT * FROM "agile-cardinal-490cb1".main._extract_data;
```

**Pros:**
- ✅ Zero schema bloat
- ✅ Full control over what's attached
- ✅ Simple SQL interface

**Cons:**
- ⚠️ Need to know session ID first

---

## 🎯 **My Recommendation: Option 3 (Smart Hybrid)**

**Why:**
1. **Named sessions auto-attached** - These are deliberate (cascade_test, my_experiment)
2. **Recent 10 sessions auto-attached** - For active debugging
3. **All 206 browsable** via `_rvbbit_sessions` table
4. **On-demand ATTACH** for anything else

**Balance between:**
- Discovery (browse in tree)
- Performance (limited auto-ATTACH)
- Flexibility (manual ATTACH anything)

---

## 📊 **Implementation Complexity**

| Option | Lines of Code | Complexity | Schema Bloat |
|--------|---------------|------------|--------------|
| 1. Auto-ATTACH all | ~50 | Low | ❌ High (206 schemas!) |
| 2. Browser table only | ~70 | Low | ✅ Low (1 table) |
| 3. Smart hybrid | ~120 | Medium | ✅ Medium (~20 schemas) |
| 4. UDF only | ~50 | Low | ✅ None |

---

## 🚀 **Quick Win: Test if Manual ATTACH Works**

In DBeaver SQL Console right now:

```sql
-- ATTACH a cascade session manually
ATTACH 'session_dbs/cascade_test.duckdb' AS cascade_test;

-- List tables in it
SELECT table_name FROM information_schema.tables
WHERE table_catalog = 'cascade_test';

-- Query temp table
SELECT * FROM cascade_test.main._extract_data LIMIT 10;
```

**Then:**
1. Right-click connection → **Invalidate/Reconnect**
2. Expand Schemas → **Look for `cascade_test`!**

**If you see it** → ATTACH discovery already works, we just need to automate it!

---

## 🎁 **Use Cases**

### **Debugging Cascades:**

```sql
-- Browse all cascade sessions
SELECT * FROM _rvbbit_sessions
WHERE session_id LIKE '%cascade%'
ORDER BY modified_at DESC;

-- ATTACH specific cascade
ATTACH 'session_dbs/my_cascade_run_123.duckdb' AS debug;

-- Inspect intermediate data
SELECT * FROM debug.main._step1_extract;
SELECT * FROM debug.main._step2_transform;
SELECT * FROM debug.main._step3_output;
```

### **Cross-Session Analysis:**

```sql
-- Compare results across multiple cascade runs
SELECT 'run1' as run, * FROM session_run1.main._output
UNION ALL
SELECT 'run2' as run, * FROM session_run2.main._output
UNION ALL
SELECT 'run3' as run, * FROM session_run3.main._output;
```

### **Historical Data Access:**

```sql
-- Query data from an old cascade execution
ATTACH 'session_dbs/production_etl_2024_12_20.duckdb' AS historical;

SELECT * FROM historical.main._daily_metrics
WHERE date = '2024-12-20';
```

---

## 🔧 **Implementation Decision**

**Which option do you want?**

**A. Smart Hybrid (Recommended)**
- Named + recent 10 sessions auto-attached
- All 206 browsable via table
- ~120 lines of code

**B. Browser Table Only**
- No auto-attach
- User manually ATTACHes what they need
- ~70 lines, cleanest

**C. Recent Only**
- Auto-attach last 24 hours (maybe 10-20 schemas)
- Simple, focused on current work
- ~80 lines

**D. Test First**
- Test if manual ATTACH shows up in DBeaver
- Then decide based on results

---

**Try the manual ATTACH test above and tell me:**
1. Does the ATTACH work in SQL?
2. Does `cascade_test` schema appear in DBeaver tree after refresh?
3. Can you expand it to see tables?

This will tell us if we need any special handling or if it just works! 🎯
