# Durable Execution & ClickHouse-Native Coordination

## Overview

This document outlines the implementation plan for adding durable execution capabilities to Windlass using ClickHouse as the coordination database. This replaces the current JSON file-based state tracking with a robust, queryable, cross-process coordination system.

### Problems Solved

| Problem | Current State | Solution |
|---------|---------------|----------|
| **Zombie sessions** | Server dies → "running" forever in JSON | Heartbeat + lease expiry detection |
| **No cancellation** | Can't stop a running cascade | Cooperative cancellation via CH polling |
| **Hidden blocked state** | Blocking happens deep in tools | First-class `blocked` status in CH |
| **No cross-process visibility** | Each CLI only sees its own state | All state in queryable CH table |
| **Complex UI state derivation** | UI derives status from activity heuristics | Explicit status column in CH |
| **No crash recovery** | In-memory Echo lost on crash | Checkpoint references for resume |

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        ClickHouse                                │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐        │
│  │ session_state │  │    signals    │  │  checkpoints  │        │
│  │   (NEW)       │  │  (existing)   │  │  (existing)   │        │
│  └───────────────┘  └───────────────┘  └───────────────┘        │
└─────────────────────────────────────────────────────────────────┘
         ▲                    ▲                    ▲
         │ heartbeat          │ wait/fire          │ HITL
         │ status             │                    │
    ┌────┴────────────────────┴────────────────────┴────┐
    │                  WindlassRunner                    │
    │  - Heartbeat thread (30s)                         │
    │  - Cancellation check (between phases)            │
    │  - Blocked state surfacing                        │
    └───────────────────────────────────────────────────┘
```

### Design Principles

1. **ClickHouse is truth** - All coordination state lives in CH, survives any process death
2. **No central server required** - CLI works standalone, coordination via CH polling
3. **HTTP callbacks for acceleration** - Optional low-latency wake-up (existing pattern from signals)
4. **Polling for reliability** - Guaranteed delivery even if callbacks fail
5. **Backward compatible** - Dual-write during migration, existing cascades keep working

---

## Schema: `session_state` Table

```sql
CREATE TABLE IF NOT EXISTS session_state (
    -- Identity
    session_id String,
    cascade_id String,
    parent_session_id Nullable(String),

    -- Execution status
    status Enum8(
        'starting' = 1,
        'running' = 2,
        'blocked' = 3,
        'completed' = 4,
        'error' = 5,
        'cancelled' = 6,
        'orphaned' = 7
    ),
    current_phase Nullable(String),
    depth UInt8 DEFAULT 0,

    -- Blocked state details (populated when status = 'blocked')
    blocked_type Nullable(Enum8(
        'signal' = 1,
        'hitl' = 2,
        'sensor' = 3,
        'approval' = 4,
        'checkpoint' = 5
    )),
    blocked_on Nullable(String),           -- signal_name, checkpoint_id, etc.
    blocked_description Nullable(String),  -- Human-readable description
    blocked_timeout_at Nullable(DateTime64(3)),

    -- Heartbeat for zombie detection
    heartbeat_at DateTime64(3) DEFAULT now64(3),
    heartbeat_lease_seconds UInt16 DEFAULT 60,

    -- Cancellation
    cancel_requested Bool DEFAULT false,
    cancel_reason Nullable(String),
    cancelled_at Nullable(DateTime64(3)),

    -- Error details (populated when status = 'error')
    error_message Nullable(String),
    error_phase Nullable(String),

    -- Recovery/Resume
    last_checkpoint_id Nullable(String),
    resumable Bool DEFAULT false,

    -- Timing
    started_at DateTime64(3) DEFAULT now64(3),
    completed_at Nullable(DateTime64(3)),
    updated_at DateTime64(3) DEFAULT now64(3),

    -- Extensible metadata
    metadata String DEFAULT '{}'

) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (session_id)
PARTITION BY toYYYYMM(started_at);
```

### Status State Machine

```
                    ┌──────────────┐
                    │   starting   │
                    └──────┬───────┘
                           │
                           ▼
              ┌───────────────────────────┐
              │         running           │◀─────────┐
              └─────┬─────────┬───────────┘          │
                    │         │                      │
         ┌──────────┘         └──────────┐           │
         ▼                               ▼           │
┌─────────────────┐             ┌─────────────────┐  │
│     blocked     │─────────────│   completed     │  │
│  (signal/hitl)  │  unblocked  └─────────────────┘  │
└────────┬────────┘                                  │
         │                                           │
         └───────────────────────────────────────────┘

         Any state can transition to:
         - cancelled (user requested)
         - error (execution failed)
         - orphaned (heartbeat expired)
```

---

## Implementation Phases

### Phase 1: Schema & Basic Infrastructure ✅ COMPLETE
**Goal**: Add session_state table and basic read/write functions

- [x] 1.1 Add `session_state` schema to `schema.py`
- [x] 1.2 Create `session_state.py` module with:
  - `SessionStatus` enum
  - `BlockedType` enum
  - `SessionState` dataclass
  - `SessionStateManager` class with CRUD operations
- [x] 1.3 Add table creation to DB initialization
- [x] 1.4 Write unit tests for session state operations

**Files**: `windlass/schema.py`, `windlass/session_state.py`, `tests/test_session_state.py`

---

### Phase 2: Heartbeat System ✅ COMPLETE
**Goal**: Detect zombie sessions via heartbeat expiry

- [x] 2.1 Add heartbeat thread to `WindlassRunner`
  - Start on `run()`, stop on completion
  - Heartbeat every 30 seconds
  - Update `heartbeat_at` in session_state
- [x] 2.2 Implement `cleanup_zombie_sessions()` function
  - Find sessions where `heartbeat_at + lease < now()`
  - Mark as `orphaned`
- [x] 2.3 Add CLI command: `windlass sessions cleanup`
- [x] 2.4 Add CLI command: `windlass sessions list` (shows all session states)
- [ ] 2.5 Call cleanup on UI backend startup (deferred to Phase 6)

**Files**: `windlass/runner.py`, `windlass/session_state.py`, `windlass/cli.py`

---

### Phase 3: Status Tracking in Runner ✅ COMPLETE
**Goal**: Runner writes status to ClickHouse instead of JSON files

- [x] 3.1 Update runner to write `starting` status on init
- [x] 3.2 Update runner to write `running` status with current phase
- [x] 3.3 Update runner to write `completed` status on success
- [x] 3.4 Update runner to write `error` status on failure
- [x] 3.5 Dual-write to JSON files during transition (backward compat)
- [x] 3.6 Update sub-cascade spawning to track parent_session_id

**Files**: `windlass/runner.py`, `windlass/session_state.py`

---

### Phase 4: Cancellation Support ✅ COMPLETE
**Goal**: Allow external cancellation of running cascades

- [x] 4.1 Add `request_cancellation(session_id, reason)` function
- [x] 4.2 Add cancellation check in runner between phases
- [ ] 4.3 Add cancellation check in runner between turns (optional enhancement)
- [x] 4.4 Implement graceful shutdown on cancellation
  - Set status to `cancelled`
  - Clean up resources
  - Optional: save checkpoint for resume (Phase 7)
- [x] 4.5 Add CLI command: `windlass sessions cancel <session_id>`
- [ ] 4.6 Add HTTP callback for instant cancellation (optional enhancement)

**Files**: `windlass/runner.py`, `windlass/session_state.py`, `windlass/cli.py`

---

### Phase 5: Blocked State Surfacing ✅ COMPLETE
**Goal**: Make blocked state visible at session level

- [x] 5.1 Modify `await_signal` to update session status to `blocked`
- [x] 5.2 Modify `await_signal` to restore `running` when unblocked
- [x] 5.3 Modify HITL checkpoint `wait_for_response` to update session status to `blocked`
- [x] 5.4 Add `get_blocked_sessions()` query function
- [x] 5.5 Ensure blocked sessions still send heartbeats (heartbeat runs on main thread)
- [x] 5.6 Add blocked state to CLI `sessions list` output (with color coding)

**Files**: `windlass/signals.py`, `windlass/checkpoints.py`, `windlass/session_state.py`, `windlass/cli.py`

---

### Phase 6: UI Integration & JSON Deprecation
**Goal**: UI uses ClickHouse directly, remove JSON dependency

- [ ] 6.1 Update UI backend to query `session_state` table
- [ ] 6.2 Add SSE events for session state changes
- [ ] 6.3 Create "Blocked Sessions" dashboard view
- [ ] 6.4 Create "Cancel" button in UI
- [ ] 6.5 Remove JSON file writes (after UI migration verified)
- [ ] 6.6 Clean up `state.py` (keep PhaseProgress for detailed tracking)

**Files**: UI backend, `windlass/state.py`, `windlass/runner.py`

---

### Phase 7: Recovery & Resume (Future)
**Goal**: Resume cascades from last checkpoint after crash

- [ ] 7.1 Store `last_checkpoint_id` when checkpointing phases
- [ ] 7.2 Add `resumable` flag for cascades that support resume
- [ ] 7.3 Implement `WindlassRunner.from_checkpoint(checkpoint_id)`
- [ ] 7.4 Add CLI command: `windlass sessions resume <session_id>`
- [ ] 7.5 Auto-resume orphaned sessions on startup (optional)

**Files**: `windlass/runner.py`, `windlass/checkpoints.py`, `windlass/cli.py`

---

## API Reference

### SessionStateManager

```python
class SessionStateManager:
    # Write operations
    def create_session(self, session_id: str, cascade_id: str, parent_session_id: str = None) -> SessionState
    def update_status(self, session_id: str, status: SessionStatus, **kwargs) -> None
    def set_blocked(self, session_id: str, blocked_type: BlockedType, blocked_on: str, description: str, timeout_at: datetime = None) -> None
    def set_unblocked(self, session_id: str) -> None
    def request_cancellation(self, session_id: str, reason: str = None) -> None
    def heartbeat(self, session_id: str) -> None

    # Read operations
    def get_session(self, session_id: str) -> Optional[SessionState]
    def list_sessions(self, status: SessionStatus = None, limit: int = 100) -> List[SessionState]
    def get_blocked_sessions(self) -> List[SessionState]
    def get_zombie_sessions(self) -> List[SessionState]
    def is_cancelled(self, session_id: str) -> bool

    # Maintenance
    def cleanup_zombies(self) -> int  # Returns count of sessions marked orphaned
```

### CLI Commands

```bash
# List all sessions
windlass sessions list
windlass sessions list --status running
windlass sessions list --status blocked

# Cancel a session
windlass sessions cancel abc123
windlass sessions cancel abc123 --reason "User requested"

# Cleanup zombies
windlass sessions cleanup
windlass sessions cleanup --dry-run

# Show session details
windlass sessions show abc123
```

### SQL Queries (for UI/debugging)

```sql
-- All running/blocked sessions
SELECT * FROM session_state FINAL
WHERE status IN ('running', 'blocked')
ORDER BY updated_at DESC;

-- Blocked sessions with details
SELECT
    session_id,
    cascade_id,
    blocked_type,
    blocked_on,
    blocked_description,
    dateDiff('second', heartbeat_at, now()) as seconds_waiting
FROM session_state FINAL
WHERE status = 'blocked'
ORDER BY heartbeat_at ASC;

-- Zombie candidates (expired heartbeat)
SELECT *
FROM session_state FINAL
WHERE status IN ('running', 'blocked')
AND heartbeat_at + INTERVAL heartbeat_lease_seconds SECOND < now();

-- Session history (all status changes)
SELECT *
FROM session_state
WHERE session_id = 'abc123'
ORDER BY updated_at ASC;
```

---

## Migration Strategy

### Phase A: Dual-Write (Safe)
1. Deploy new code that writes to BOTH JSON files AND ClickHouse
2. UI continues reading from JSON files
3. Verify ClickHouse data matches expectations

### Phase B: Dual-Read (Validation)
1. UI reads from ClickHouse but falls back to JSON if missing
2. Compare results, log discrepancies
3. Build confidence in CH data

### Phase C: CH-Primary (Cutover)
1. UI reads exclusively from ClickHouse
2. JSON writes continue as backup
3. Monitor for issues

### Phase D: JSON Removal (Cleanup)
1. Remove JSON file writes from runner
2. Remove JSON file reads from state.py
3. Clean up old JSON files

---

## Success Metrics

- [ ] No more "running forever" zombie sessions
- [ ] UI can show all blocked cascades with one SQL query
- [ ] Cascades can be cancelled from UI within 30 seconds
- [ ] Server restart doesn't lose session state
- [ ] Cross-process visibility works (CLI A can see CLI B's session)

---

## Timeline Estimate

| Phase | Complexity | Dependencies |
|-------|------------|--------------|
| Phase 1 | Low | None |
| Phase 2 | Low | Phase 1 |
| Phase 3 | Medium | Phase 1, 2 |
| Phase 4 | Medium | Phase 3 |
| Phase 5 | Low | Phase 3 |
| Phase 6 | Medium | Phase 3, 4, 5 |
| Phase 7 | High | Phase 3, 4 |

Phases 1-5 can be done incrementally with value at each step.
Phase 6 requires UI changes.
Phase 7 is optional/future enhancement.
