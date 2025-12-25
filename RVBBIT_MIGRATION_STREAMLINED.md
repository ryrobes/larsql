# RVBBIT Migration - Streamlined Execution Plan

**Date:** 2025-12-25
**Approach:** Clean break, no backwards compatibility, no data migration (yet)

---

## User Decisions

✅ **ClickHouse:** Create fresh `rvbbit` database (no migration, can copy data later)
✅ **API Routes:** Keep existing paths (no /phase → /cell route changes)
✅ **GitHub Repo:** User will handle manually later
✅ **UDF Names:** Clean break, no dual support
✅ **Directory Names:** Keep `cascades/`, keep `examples/`
✅ **Docker:** Rename both ClickHouse and Elasticsearch containers
✅ **Data Loss:** Not a concern, will fix YAML/scripts as needed

---

## Simplified 5-Stage Plan

### STAGE 1: Fresh Database + Docker (30 mins)
1. Create new `rvbbit` ClickHouse database with updated schema
2. Update Docker Compose with new container names
3. Test database connection

### STAGE 2: Python Package Rename (30 mins)
1. Rename `windlass/` → `rvbbit/` directory
2. Update `pyproject.toml` (package name, entry point)
3. Update all imports
4. Reinstall package

### STAGE 3: Core Python Code (2-3 hours)
1. Update Pydantic models (PhaseConfig → CellConfig, etc.)
2. Update all Python files with automated script
3. Manual review of critical files
4. Run tests, fix breakages

### STAGE 4: Dashboard Backend (1-2 hours)
1. Update database queries (new column names)
2. Update API response fields (but keep route paths)
3. Update event payloads
4. Test endpoints

### STAGE 5: Frontend + Docs (2-3 hours)
1. Rename React components
2. Update component code
3. Update documentation
4. Update example YAML files
5. Final testing

**Total Time:** 6-9 hours (can complete in one day!)

---

## Key Changes Summary

### Terminology Mapping

| Old | New |
|-----|-----|
| Windlass | RVBBIT |
| windlass | rvbbit |
| Phase | Cell |
| phase | cell |
| PhaseConfig | CellConfig |
| Tackle | Traits |
| tackle | traits |
| Soundings | Candidates |
| soundings | candidates |
| sounding_index | candidate_index |
| windlass_udf() | rvbbit() |
| windlass_cascade_udf() | rvbbit_run() |

### Environment Variables (29 total)

All `WINDLASS_*` → `RVBBIT_*`

### Database Schema (Fresh Creation)

**Table:** `unified_logs`
- `phase_name` → `cell_name`
- `phase_json` → `cell_json`
- `sounding_index` → `candidate_index`
- `winning_sounding_index` → `winning_candidate_index`

(Same for all 6 tables)

### Docker Services

- `windlass-clickhouse` → `rvbbit-clickhouse`
- `windlass-elasticsearch` → `rvbbit-elasticsearch` (if used)
- Database name: `windlass` → `rvbbit`

---

## Files We're NOT Changing

✅ **API route paths** (keep as-is)
✅ **cascades/** (directory name stays)
✅ **examples/** (directory name stays)
✅ **Repo directory** (/repos/windlass/ - user will rename later)

---

## Execution Checklist

### Pre-Flight
- [ ] Git commit current state
- [ ] Create backup branch
- [ ] Shut down old ClickHouse/Elasticsearch containers

### Stage 1: Database + Docker
- [ ] Create `migrations/create_rvbbit_db.sql` with fresh schema
- [ ] Update `docker-compose.yml` (container names, database name)
- [ ] Create new database: `rvbbit`
- [ ] Test connection

### Stage 2: Package Rename
- [ ] Rename directory: `windlass/windlass/` → `windlass/rvbbit/`
- [ ] Update `pyproject.toml`
- [ ] Run import updater script
- [ ] Reinstall: `pip install -e .`
- [ ] Test: `rvbbit --version`

### Stage 3: Core Python
- [ ] Run automated refactor script
- [ ] Manual review: `cascade.py`, `runner.py`, `config.py`, `udf.py`
- [ ] Update environment variable names
- [ ] Run tests: `pytest tests/`
- [ ] Fix any breakages

### Stage 4: Backend
- [ ] Update database queries (column names)
- [ ] Update API response fields
- [ ] Keep route paths unchanged
- [ ] Test endpoints

### Stage 5: Frontend + Docs
- [ ] Rename components (Phase* → Cell*, etc.)
- [ ] Update component code
- [ ] Update CLAUDE.md, README.md
- [ ] Update example YAMLs (phases → cells)
- [ ] Build and test

### Final
- [ ] Full integration test
- [ ] Update .env with new variable names
- [ ] Create migration guide for users

---

## Critical Files (Priority Order)

1. **Schema Creation:** `migrations/create_rvbbit_db.sql`
2. **Docker:** `docker-compose.yml`
3. **Package:** `windlass/pyproject.toml`
4. **Core Models:** `rvbbit/cascade.py` (1341 lines)
5. **Runner:** `rvbbit/runner.py`
6. **Config:** `rvbbit/config.py` (env vars)
7. **SQL UDFs:** `rvbbit/sql_tools/udf.py`
8. **Backend API:** `dashboard/backend/app.py` (266KB)
9. **Main Docs:** `CLAUDE.md`, `README.md`

---

## Quick Commands

### Start Fresh

```bash
# Commit current state
git add -A
git commit -m "Pre-RVBBIT migration checkpoint"
git checkout -b rvbbit-migration

# Shutdown old containers
docker-compose down

# Start migration
# (follow stages below)
```

### Test After Each Stage

```bash
# After Stage 2
rvbbit --version

# After Stage 3
pytest tests/ -v

# After Stage 4
curl http://localhost:5001/api/health

# After Stage 5
cd dashboard/frontend && npm run build
```

---

## Things We'll Fix As We Go

- Broken example YAML files (phases → cells)
- Test snapshots referencing old terminology
- Any hardcoded strings in UI
- Documentation references

**Approach:** Run, observe errors, fix, repeat. Fast iteration.

---

**Ready to execute when you are!** 🚀
