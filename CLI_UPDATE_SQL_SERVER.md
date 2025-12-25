# CLI Update: PostgreSQL Server Command

## 🎯 **Changes Made**

### **NEW Command Structure**

**Before:**
```bash
rvbbit server --port 5432      # Ambiguous - what kind of server?
rvbbit sql "SELECT * FROM all_data"  # Query ClickHouse
```

**After:**
```bash
rvbbit sql server --port 15432   # Clear - PostgreSQL server!
rvbbit sql query "SELECT * FROM all_data"  # Explicit - query command!
```

---

## 📋 **All SQL Commands**

### **1. Start PostgreSQL Server**

```bash
# Start PostgreSQL wire protocol server
rvbbit sql server

# Custom port
rvbbit sql server --port 5432

# Custom host
rvbbit sql server --host 127.0.0.1 --port 15432

# Custom session prefix
rvbbit sql server --session-prefix myapp
```

**Aliases:**
```bash
rvbbit sql serve  # Shorter alias
```

**Default port changed:**
- ✅ **15432** (new default - no conflict with real PostgreSQL)
- ⚠️ 5432 (standard PostgreSQL port - may require sudo)

### **2. Query ClickHouse**

```bash
# Query RVBBIT's ClickHouse logs
rvbbit sql query "SELECT * FROM all_data LIMIT 10"

# With output format
rvbbit sql query "SELECT session_id, cost FROM all_data" --format json

# With row limit
rvbbit sql query "SELECT * FROM all_evals" --limit 100
```

**Aliases:**
```bash
rvbbit sql q "SELECT..."  # Shorter alias
```

### **3. Backward Compatibility**

**Old style still works** (with deprecation warning):

```bash
rvbbit sql "SELECT * FROM all_data"
```

**Output:**
```
⚠️  DEPRECATED: Use 'rvbbit sql query "SELECT..."' instead
   (still works for backward compatibility)

<query results>
```

---

## 🎯 **Why These Changes?**

### **Problem 1: "rvbbit server" was ambiguous**

Users asked: "What kind of server? Web server? API server? Database server?"

**Solution:** `rvbbit sql server` makes it crystal clear - it's a **SQL server** (PostgreSQL wire protocol)!

### **Problem 2: Port 5432 conflicts with real PostgreSQL**

Most developers have PostgreSQL already running on 5432.

**Solution:** Default to port **15432** (no conflicts, easy to remember: 15432 = 1 + 5432)

### **Problem 3: SQL namespace fragmentation**

- `rvbbit sql` - Query ClickHouse
- `rvbbit server` - PostgreSQL server

These are related (both SQL) but in different namespaces!

**Solution:** Group under `rvbbit sql` namespace:
- `rvbbit sql query` - Query ClickHouse
- `rvbbit sql server` - PostgreSQL server

---

## 📊 **New Command Hierarchy**

```
rvbbit
├── sql
│   ├── query (q)       Query ClickHouse logs
│   └── server (serve)  Start PostgreSQL server
├── test
│   ├── freeze          Create test snapshot
│   ├── validate        Validate snapshot
│   ├── run             Run all tests
│   └── list            List snapshots
├── db
│   ├── status          Database status
│   └── init            Initialize database
├── embed
│   ├── status          Embedding status
│   ├── run             Run embedding
│   └── cleanup         Clean embeddings
├── data
│   └── compact         Compact data files
└── tools
    └── find            Find tools by query
```

**More organized! Related commands grouped together!**

---

## 🔄 **Migration Guide**

### **If you have scripts using `rvbbit server`:**

**Option 1:** Update to new command (recommended)
```bash
# OLD:
rvbbit server --port 5432

# NEW:
rvbbit sql server --port 15432
```

**Option 2:** Create an alias (temporary)
```bash
# Add to ~/.bashrc or ~/.zshrc
alias rvbbit-server='rvbbit sql server'

# Use it:
rvbbit-server --port 15432
```

### **If you have scripts using `rvbbit sql`:**

**No changes needed!** Old style still works:

```bash
rvbbit sql "SELECT * FROM all_data"  # Still works (with warning)
```

**Recommended:** Update to explicit command:
```bash
rvbbit sql query "SELECT * FROM all_data"  # New, clearer
```

---

## 💡 **Usage Examples**

### **Start Server for DBeaver**

```bash
# Start on default port (15432)
rvbbit sql server

# Start on custom port
rvbbit sql server --port 5432

# Connect from DBeaver:
postgresql://localhost:15432/default
```

### **Query RVBBIT Logs**

```bash
# Quick query
rvbbit sql query "SELECT COUNT(*) FROM all_data"

# With formatting
rvbbit sql query "SELECT session_id, phase_name, cost FROM all_data WHERE cost > 0" --format json

# Export to file
rvbbit sql query "SELECT * FROM all_evals" --format csv > evals.csv
```

### **Shorter Aliases**

```bash
# Use short aliases
rvbbit sql q "SELECT * FROM all_data"  # query → q
rvbbit sql serve --port 15432          # server → serve
```

---

## 🎓 **Learning the New Commands**

### **Discoverability**

```bash
# See all SQL commands
rvbbit sql --help

# See server options
rvbbit sql server --help

# See query options
rvbbit sql query --help
```

### **Tab Completion** (if you have it configured)

```bash
rvbbit sql <TAB>
  → query  server

rvbbit sql server --<TAB>
  → --host  --port  --session-prefix
```

---

## 📚 **Updated Documentation**

### **Quick Reference**

| Old Command | New Command | Notes |
|-------------|-------------|-------|
| `rvbbit server` | `rvbbit sql server` | Clearer! |
| `rvbbit server --port 5432` | `rvbbit sql server --port 15432` | New default port! |
| `rvbbit sql "SELECT..."` | `rvbbit sql query "SELECT..."` | Explicit (old still works) |

### **Connection Strings**

| Port | Command | Connection String |
|------|---------|-------------------|
| **15432** (default) | `rvbbit sql server` | `postgresql://localhost:15432/default` |
| 5432 (custom) | `rvbbit sql server --port 5432` | `postgresql://localhost:5432/default` |
| 5433 (custom) | `rvbbit sql server --port 5433` | `postgresql://localhost:5433/default` |

---

## 🎊 **Benefits**

### **Clarity**

**Before:**
```bash
rvbbit server  # What kind of server? 🤔
```

**After:**
```bash
rvbbit sql server  # PostgreSQL SQL server! Clear! ✅
```

### **Namespace Organization**

All SQL-related commands under `rvbbit sql`:
- ✅ `rvbbit sql query` - Query logs
- ✅ `rvbbit sql server` - Run SQL server
- 🔮 Future: `rvbbit sql console` - Interactive SQL REPL?

### **Port Conflict Prevention**

**Default 15432** instead of 5432 means:
- ✅ No conflict with real PostgreSQL
- ✅ No sudo required
- ✅ Can run both side-by-side

---

## 🚀 **Try It Now**

```bash
# Start server on new default port
rvbbit sql server

# You'll see:
🚀 Starting RVBBIT PostgreSQL server...
   Host: 0.0.0.0
   Port: 15432
   Session prefix: pg_client

💡 TIP: Connect with:
   psql postgresql://localhost:15432/default
   DBeaver: New Connection → PostgreSQL → localhost:15432

🌊 WINDLASS POSTGRESQL SERVER
📡 Listening on: 0.0.0.0:15432
...
```

---

## 📝 **Summary**

**Changes:**
- ✅ `rvbbit server` → `rvbbit sql server` (clearer namespace)
- ✅ Default port: 5432 → 15432 (no conflicts)
- ✅ Added `rvbbit sql query` for explicit querying
- ✅ Backward compatibility maintained
- ✅ Helpful tip output on server start

**Benefits:**
- Clear command structure
- No port conflicts
- Better discoverability
- Backward compatible

**Files modified:**
- `rvbbit/rvbbit/cli.py` (~40 lines changed)

---

**Start using the new commands today!** 🎉
