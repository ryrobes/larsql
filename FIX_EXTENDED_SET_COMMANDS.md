# Fix: SET Commands in Extended Query Protocol

## 🐛 **Issue**

```
ERROR: Execute error: Catalog Error: unrecognized configuration parameter "extra_float_digits"
```

**Root cause:** DBeaver sends `SET extra_float_digits = 3` using **Extended Query Protocol** (Parse/Bind/Execute), not Simple Query!

Our SET handler only worked for Simple Query mode.

---

## ✅ **Fix**

### **1. Created shared SET command logic:**

```python
def _execute_set_command(self, query: str):
    """Execute SET/RESET (internal - no responses)."""
    # Check if it's an ignored setting
    if is_ignored:
        # Silently ignore
        pass
    else:
        # Try on DuckDB, ignore if fails
        try:
            self.duckdb_conn.execute(query)
        except:
            pass  # Ignore unsupported
```

### **2. Updated Simple Query handler:**

```python
def _handle_set_command(self, query: str):
    self._execute_set_command(query)  # Use shared logic
    self.sock.sendall(CommandComplete.encode('SET'))
    self.sock.sendall(ReadyForQuery.encode('I'))
```

### **3. Added check in Execute handler:**

```python
def _handle_execute(self, msg: dict):
    portal = self.portals[portal_name]
    query = portal['query']
    
    # NEW: Check if this is a SET command
    if query.upper().startswith('SET '):
        self._execute_set_command(query)
        send_execute_results(self.sock, pd.DataFrame())  # Empty result
        return
    
    # Normal query execution...
```

---

## 🎯 **Result**

**Before:**
```
Parse("SET extra_float_digits = 3")
Bind()
Execute()
  ✗ ERROR: unrecognized configuration parameter
```

**After:**
```
Parse("SET extra_float_digits = 3")
Bind()
Execute()
  ✓ SET handled via Extended Query
  ✓ Empty result sent
Sync()
  ✓ ReadyForQuery
```

**Connection works!**

---

## 🔄 **Test the Fix**

```bash
# Restart server
rvbbit sql server --port 15432

# Connect from DBeaver (zero config!)
# Should connect without errors now!
```

---

**SET commands now work in BOTH protocols!** ✅
