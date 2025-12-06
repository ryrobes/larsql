# Optional Dependencies in Windlass

Windlass follows a **batteries-included-but-swappable** philosophy for optional features that require external dependencies.

## Philosophy

**Core principle:** Users should be able to `pip install windlass` and immediately use core features (LLM orchestration, cascades, state management, logging) without installing external tools.

**Optional features** (Rabbitize, Docker) provide enhanced capabilities but aren't required for basic operation.

## Why NOT Bundle Everything?

### The npm Problem

Rabbitize is an npm package (Node.js ecosystem). We **intentionally don't** try to install it automatically during `pip install windlass` because:

1. **Cross-platform complexity**: npm might be installed via nvm, brew, apt, chocolatey, snap, etc.
2. **Permission issues**: Global npm installs often require sudo, which breaks in many CI/CD environments
3. **Version conflicts**: User's Node.js version might be incompatible
4. **Build system brittleness**: Running npm during Python package installation is fragile and error-prone
5. **User expectations**: Python developers don't expect `pip install` to modify their Node.js environment

### The Docker Problem

Similarly for Docker (used by `linux_shell` and `run_code` tools):

1. **Installation varies wildly**: Docker Desktop (macOS/Windows) vs docker-ce (Linux) vs Podman (alternatives)
2. **System-level daemon**: Requires root/admin privileges to install
3. **Not always needed**: Many users won't use sandboxed code execution

## Our Solution: Smart Detection + Helpful Errors

### 1. Optional Dependencies in pyproject.toml

```toml
[project.optional-dependencies]
browser = [
    # Rabbitize is npm-based, documented here
    # Install: npm install -g rabbitize
]
docker = [
    "docker",  # Python Docker client
]
all = [
    "docker",
]
```

### 2. Runtime Detection

Tools check if dependencies are available when first used:

```python
def rabbitize_start(url):
    if not _ensure_server_running():
        is_installed, msg = _check_rabbitize_installed()
        if not is_installed:
            return {"content": f"❌ Rabbitize not installed.\n\n{_get_installation_instructions()}"}
```

### 3. CLI Check Command

```bash
windlass check --feature rabbitize
windlass check --feature docker
windlass check --feature all
```

Shows:
- ✅ What's installed and working
- ❌ What's missing
- 📦 Exact installation commands
- 🚀 How to start/configure

### 4. Graceful Degradation

If Rabbitize isn't installed:
- Core Windlass features still work
- Rabbitize tools return helpful error messages with installation instructions
- Agent sees the error and can inform user
- No crashes, no confusing stack traces

## Installation Flow for Users

### Basic Install (Core Features)

```bash
pip install windlass
# ✅ Works immediately for core features
```

### Adding Rabbitize (Optional)

```bash
# Check what's needed
windlass check --feature rabbitize

# Install npm dependencies
npm install -g rabbitize
sudo npx playwright install-deps

# Verify
windlass check --feature rabbitize
# ✅ All green!
```

### Adding Docker (Optional)

```bash
# Check status
windlass check --feature docker

# Install Docker (OS-specific)
# ... follow prompts from check command ...

# Create container
docker run -d --name ubuntu-container ubuntu:latest sleep infinity
docker exec ubuntu-container bash -c "apt update && apt install -y python3 python3-pip curl wget"

# Verify
windlass check --feature docker
# ✅ Ready!
```

## Distribution Strategy

When distributing Windlass:

### For pip / PyPI

```bash
pip install windlass
# Core features work immediately
# Optional features show helpful installation guidance
```

### For Complete Setup

```bash
pip install windlass
windlass check  # Shows what's missing
# Follow prompts to install Rabbitize, Docker, etc.
```

### For CI/CD

```yaml
# .github/workflows/test.yml
- name: Install Windlass
  run: pip install windlass

- name: Install Rabbitize (if needed)
  run: |
    npm install -g rabbitize
    sudo npx playwright install-deps

- name: Verify setup
  run: windlass check
```

### For Docker Images

```dockerfile
FROM python:3.11

# Install Windlass
RUN pip install windlass

# Install Node.js + Rabbitize
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
RUN apt-get install -y nodejs
RUN npm install -g rabbitize
RUN npx playwright install-deps

# Verify
RUN windlass check
```

## Alternative Approaches (Not Chosen)

### ❌ Approach 1: Force npm install during pip install

**Why not:**
- Breaks in environments without npm
- Requires complex setuptools hooks
- Permission issues with global npm
- Users hate it when Python packages mess with their system

### ❌ Approach 2: Bundle Rabbitize as Python package

**Why not:**
- Rabbitize is actively developed npm package
- Would need to maintain Python wrapper
- Playwright dependencies are huge
- Duplicates effort unnecessarily

### ❌ Approach 3: Make Rabbitize required

**Why not:**
- Forces all users to install npm + Playwright
- Many users don't need browser automation
- Increases installation complexity for everyone
- Goes against "batteries-included-but-swappable" principle

## Best Practices for Adding New Optional Features

When adding features that require external dependencies:

1. **Check at runtime**, not import time
2. **Return helpful errors** with exact installation commands
3. **Add to `windlass check` command**
4. **Document in dedicated .md file** (like RABBITIZE_INTEGRATION.md)
5. **Add to pyproject.toml** optional-dependencies (for documentation)
6. **Test without the dependency** to ensure graceful degradation

## Summary

**Philosophy:** Make core features work immediately, make optional features discoverable and easy to add.

**User Experience:**
- `pip install windlass` → ✅ Core features work
- Try Rabbitize tool → ❌ Helpful error with installation guide
- `windlass check` → See what's missing
- Install Rabbitize → ✅ Now it works
- `windlass check` → All green!

**Result:** Happy users who install only what they need, with clear guidance when they need more.
