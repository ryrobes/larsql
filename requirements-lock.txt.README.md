# requirements-lock.txt

## What Is This?

This file contains **exact versions** of all dependencies that are known to work together.

Generated with: `pip freeze > requirements-lock.txt`

Last updated: 2026-01-24

## When To Use

### ✅ Use requirements-lock.txt for:

- **Development setup** - Ensures all devs have identical environments
- **CI/CD pipelines** - Reproducible test runs
- **Production deployments** - Guaranteed working versions
- **Docker images** - Exact versions in containers

### ❌ Don't use for:

- **User installations** - Users should install via `pip install larsql` (uses pyproject.toml)
- **Library dependencies** - pyproject.toml handles that

## Usage

### Development Setup
```bash
# Clone repo
git clone https://github.com/ryrobes/larsql.git
cd larsql

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install exact working versions
pip install -r requirements-lock.txt

# Install lars in editable mode
pip install -e lars/
```

### CI/CD (GitHub Actions)
```yaml
- name: Install dependencies
  run: |
    pip install -r requirements-lock.txt
    pip install -e lars/
```

### Production Deployment
```bash
pip install -r requirements-lock.txt
```

## Updating This File

### When to update:
- After upgrading a dependency and testing
- Monthly maintenance (security patches)
- After fixing a dependency issue

### How to update:
```bash
# 1. Upgrade dependencies (in your dev environment)
pip install --upgrade litellm duckdb pandas  # Or specific packages

# 2. Test thoroughly
pytest
python test_explain_endpoint.py

# 3. If tests pass, update lock file
pip freeze > requirements-lock.txt

# 4. Commit
git add requirements-lock.txt
git commit -m "chore: update dependency lock file"
```

## Relationship to pyproject.toml

| File | Purpose | Constraints | Users |
|------|---------|-------------|-------|
| **pyproject.toml** | Package metadata | Flexible (`>=X,<Y`) | End users |
| **requirements-lock.txt** | Exact versions | Pinned (`==X.Y.Z`) | Developers/CI |

**Example:**
```toml
# pyproject.toml (flexible)
"pydantic>=2.10,<3.0"  # Allows 2.10.0 - 2.99.9

# requirements-lock.txt (exact)
pydantic==2.12.5       # Locked to exact version
```

## Troubleshooting

### "Package version conflict"
Your environment has different versions than the lock file.

**Solution:**
```bash
# Fresh start
pip install --force-reinstall -r requirements-lock.txt
```

### "Lock file is outdated"
A dependency has a security vulnerability.

**Solution:**
```bash
# Check for vulnerabilities
pip install pip-audit
pip-audit

# Update specific package
pip install --upgrade package-name
pip freeze > requirements-lock.txt

# Test and commit
```

## See Also

- `DEPENDENCY_PINNING_GUIDE.md` - Full strategy and rationale
- `pyproject.toml` - Main package definition with flexible constraints
