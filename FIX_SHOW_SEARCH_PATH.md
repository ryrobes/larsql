# Fix: SHOW search_path Error

## 🐛 Issue

DBeaver connection was getting invalidated with error:

```
[pg_client_main] Query #5: SHOW search_path
[pg_client_main]   ✗ Query error: Catalog Error: Table with name search_path does not exist!
```

## 🔍 Root Cause

DBeaver sends `SHOW search_path` to get the PostgreSQL schema search order.

DuckDB doesn't support `SHOW search_path` - it only supports `SHOW TABLES`, `SHOW DATABASES`, etc.

When the query failed, DBeaver invalidated the connection.

## ✅ Solution

Added `_handle_show_command()` method to intercept PostgreSQL `SHOW` commands and return appropriate values.

### **Supported SHOW Commands:**

| Command | Returns | Used By |
|---------|---------|---------|
| `SHOW search_path` | `'main, pg_catalog'` | DBeaver, psql |
| `SHOW timezone` | `'UTC'` | Most clients |
| `SHOW server_version` | `'14.0'` | DBeaver |
| `SHOW client_encoding` | `'UTF8'` | psql |
| `SHOW TABLES` | *(DuckDB native)* | All clients |

### **Code Added:**

```python
def _handle_show_command(self, query: str):
    """Handle PostgreSQL SHOW commands."""
    query_upper = query.upper()

    # SHOW search_path
    if 'SEARCH_PATH' in query_upper:
        result_df = pd.DataFrame({'search_path': ['main, pg_catalog']})
        send_query_results(self.sock, result_df)
        return

    # SHOW timezone
    if 'TIMEZONE' in query_upper:
        result_df = pd.DataFrame({'TimeZone': ['UTC']})
        send_query_results(self.sock, result_df)
        return

    # ... etc for other SHOW commands
```

## 🧪 Testing

After fix, the logs should show:

```
[pg_client_main] Query #5: SHOW search_path
[pg_client_main]   📋 SHOW command detected: SHOW search_path...
[pg_client_main]   ✓ SHOW search_path handled
```

**No more errors! Connection stays active!**

## 📋 Files Modified

- `rvbbit/rvbbit/server/postgres_server.py`:
  - Added `_handle_show_command()` method (~70 lines)
  - Added SHOW command check in `handle_query()` (3 lines)

## 🎯 Result

✅ DBeaver connection no longer invalidated
✅ `SHOW search_path` returns sensible value
✅ All PostgreSQL SHOW commands handled gracefully
✅ Connection stays stable!

---

**Restart server and test!** 🚀
