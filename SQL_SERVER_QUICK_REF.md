# Quick Reference: SQL Server Commands

## 🚀 **Start PostgreSQL Server**

### **Basic**
```bash
rvbbit sql server
```
Starts on: `0.0.0.0:15432`

### **Custom Port**
```bash
rvbbit sql server --port 5432
```

### **Custom Host (localhost only)**
```bash
rvbbit sql server --host 127.0.0.1 --port 15432
```

### **Short Alias**
```bash
rvbbit sql serve  # Same as 'server'
```

---

## 🔌 **Connect from Clients**

### **DBeaver**
1. New Connection → PostgreSQL
2. Host: `localhost`, Port: `15432`, Database: `default`
3. Username: `rvbbit`
4. Test Connection → Works!

### **psql**
```bash
psql postgresql://localhost:15432/default
```

### **Python**
```python
import psycopg2
conn = psycopg2.connect("postgresql://localhost:15432/default")
```

### **DataGrip / pgAdmin**
Same as DBeaver:
- Host: `localhost`
- Port: `15432`
- Database: `default`
- User: `rvbbit`

---

## 📊 **Query RVBBIT Logs**

### **Basic Query**
```bash
rvbbit sql query "SELECT * FROM all_data LIMIT 10"
```

### **With Format**
```bash
# Table format (default)
rvbbit sql query "SELECT * FROM all_data"

# JSON output
rvbbit sql query "SELECT * FROM all_data" --format json

# CSV output
rvbbit sql query "SELECT * FROM all_data" --format csv > data.csv
```

### **Short Alias**
```bash
rvbbit sql q "SELECT COUNT(*) FROM all_data"  # Faster!
```

### **Backward Compatible (Old Style)**
```bash
# This still works but shows deprecation warning
rvbbit sql "SELECT * FROM all_data"
```

---

## 🔑 **Key Defaults**

| Setting | Default Value | Notes |
|---------|---------------|-------|
| Port | **15432** | Changed from 5432 to avoid conflicts |
| Host | `0.0.0.0` | All interfaces (accessible remotely) |
| Session prefix | `pg_client` | DuckDB files: `pg_client_<database>.duckdb` |

---

## 🎯 **Common Use Cases**

### **Development: Local server**
```bash
rvbbit sql server --host 127.0.0.1
```
Only accessible from your machine.

### **Team: Shared server**
```bash
rvbbit sql server --host 0.0.0.0 --port 15432
```
Team can connect: `postgresql://<your-ip>:15432/default`

### **Testing: Custom port**
```bash
rvbbit sql server --port 54321
```
Use weird port to avoid any conflicts.

### **Production: Standard port (requires sudo)**
```bash
sudo rvbbit sql server --port 5432
```
Looks like real PostgreSQL to clients.

---

## 💡 **Pro Tips**

### **Tip 1: Run in background**
```bash
# Start server in background
rvbbit sql server --port 15432 &

# Or use tmux/screen
tmux new -s rvbbit-server
rvbbit sql server
# Ctrl+B, D to detach
```

### **Tip 2: Different databases for different projects**
```bash
# Connect to 'default' database
psql postgresql://localhost:15432/default

# Connect to 'analytics' database
psql postgresql://localhost:15432/analytics

# Connect to 'dev' database
psql postgresql://localhost:15432/dev
```

Each database gets its own persistent DuckDB file:
- `session_dbs/pg_client_default.duckdb`
- `session_dbs/pg_client_analytics.duckdb`
- `session_dbs/pg_client_dev.duckdb`

### **Tip 3: Check what's running**
```bash
# See if server is running
lsof -i :15432

# Kill server
pkill -f "rvbbit sql server"

# Or find PID and kill
ps aux | grep "rvbbit sql server"
kill <PID>
```

---

## 🆘 **Troubleshooting**

### **"Address already in use"**

**Problem:** Port 15432 is already in use

**Solutions:**
```bash
# Option 1: Use different port
rvbbit sql server --port 15433

# Option 2: Kill process using the port
lsof -ti:15432 | xargs kill

# Option 3: Find and stop old server
ps aux | grep rvbbit
kill <PID>
```

### **"Permission denied" (port < 1024)**

**Problem:** Ports below 1024 require root

**Solutions:**
```bash
# Option 1: Use higher port (recommended)
rvbbit sql server --port 15432  # This is the default!

# Option 2: Use sudo (not recommended)
sudo rvbbit sql server --port 5432
```

### **Command not found: rvbbit**

**Problem:** RVBBIT not installed or not in PATH

**Solutions:**
```bash
# Option 1: Install/reinstall
cd /home/ryanr/repos/rvbbit
pip install -e .

# Option 2: Run as module
python3 -m rvbbit.cli sql server
```

---

## 📖 **Help Commands**

```bash
# See all commands
rvbbit --help

# See SQL commands
rvbbit sql --help

# See server options
rvbbit sql server --help

# See query options
rvbbit sql query --help
```

---

## ✅ **Summary**

**New commands:**
- `rvbbit sql server` - Start PostgreSQL server (port 15432)
- `rvbbit sql query` - Query ClickHouse logs

**Old commands (deprecated but working):**
- `rvbbit sql "SELECT..."` - Shows warning, still works
- `rvbbit server` - Removed (use `rvbbit sql server`)

**Key change:**
- Default port: **15432** (not 5432) → No conflicts!

---

**Start using `rvbbit sql server` today!** 🚀
