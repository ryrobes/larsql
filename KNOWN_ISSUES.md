# Known Issues

## sqlglot 28.x Incompatibility

**Issue:** sqlglot 28.0+ has breaking changes that cause `TypeError` on import:
```
TokenizerSettings.__new__() got an unexpected keyword argument 'escape_follow_chars'
```

**Affected versions:** sqlglot >= 28.0.0

**Fix:** Pin to sqlglot 26.x or 27.x:
```bash
pip install 'sqlglot>=26.0.0,<28.0.0'
```

**Status:**
- ✅ Fixed in `pyproject.toml` (constraint added: `sqlglot>=26.0.0,<28.0.0`)
- ✅ Error handling added to gracefully fallback if import fails
- Issue tracked: This appears to be an upstream sqlglot breaking change in their tokenizer API

**Workaround:** If you already have 28.x installed:
```bash
pip install 'sqlglot==26.0.0'  # Downgrade to known working version
```

**Impact:** SQL fingerprinting for query logging. If sqlglot unavailable, system falls back to simpler hash-based fingerprinting (no AST normalization).

---

## Date: 2026-01-04
**Reporter:** User testing
**Root Cause:** sqlglot 28.x removed/renamed `escape_follow_chars` parameter in TokenizerSettings
**Resolution:** Version constraint added to prevent issue for new installs
