"""
Research Sessions - Temporal versioning for interactive research cascades

Enables saving, resuming, and branching research sessions from the Research Cockpit.
Think: Git for LLM conversations, with branch points at every checkpoint.
"""
import os
import json
from datetime import datetime
from uuid import uuid4
from .extras import simple_eddy


@simple_eddy
def save_research_session(
    title: str = None,
    description: str = None,
    tags: list = None,
    auto_generate_title: bool = True
) -> dict:
    """
    Save the current research session as a frozen snapshot.

    This creates a temporal checkpoint that can be:
    - Browsed later in the Research Cockpit sidebar
    - Resumed from the last interaction
    - Branched from any checkpoint (future feature)

    Arguments:
        title: Session title (auto-generated if not provided)
        description: Summary of what was researched (auto-generated if not provided)
        tags: Tags for categorization (e.g., ["quantum", "physics"])
        auto_generate_title: Generate title from conversation if not provided

    Returns:
        {
            "saved": true,
            "research_session_id": "research_session_abc123",
            "title": "...",
            "checkpoints_count": 5,
            "total_cost": 0.0234
        }

    Example:
        save_research_session(
            title="Quantum Computing Deep Dive",
            description="Explored quantum algorithms, hardware, and applications",
            tags=["quantum", "computing", "physics"]
        )
    """
    from ..echo import get_echo
    from ..tracing import get_current_trace
    from .state_tools import get_current_session_id, get_current_cascade_id

    session_id = get_current_session_id()
    cascade_id = get_current_cascade_id()

    if not session_id:
        return {"error": "No active session context", "saved": False}

    echo = get_echo(session_id)
    trace = get_current_trace()

    # Generate research session ID
    research_id = f"research_session_{uuid4().hex[:12]}"

    # Fetch all entries for this session
    entries = _fetch_session_entries(session_id)

    # Build context snapshot
    context_snapshot = {
        "state": dict(echo.state) if echo else {},
        "history": echo.history if echo else [],
        "lineage": echo.lineage if echo else {}
    }

    # Fetch checkpoints with responses
    checkpoints_data = _fetch_checkpoints_for_session(session_id)

    # Compute metrics
    metrics = _compute_session_metrics(entries)

    # Auto-generate title/description if needed
    if auto_generate_title and not title:
        title = _generate_title_from_checkpoints(checkpoints_data, cascade_id)

    if auto_generate_title and not description:
        description = _generate_description_from_session(entries, checkpoints_data)

    # Get mermaid graph
    mermaid_graph = _fetch_mermaid_graph(session_id)

    # Build research session record
    now = datetime.utcnow()
    created_at = entries[0]['timestamp'] if entries else now

    research_session = {
        "id": research_id,
        "original_session_id": session_id,
        "cascade_id": cascade_id or "unknown",
        "title": title or f"Research Session - {session_id[:8]}",
        "description": description or "",
        "created_at": created_at,
        "frozen_at": now,
        "status": "completed",  # Could be 'paused' if cascade still running

        # Full context for resumption
        "context_snapshot": json.dumps(context_snapshot),
        "checkpoints_data": json.dumps(checkpoints_data),
        "entries_snapshot": json.dumps(entries),

        # Visual artifacts
        "mermaid_graph": mermaid_graph or "",
        "screenshots": json.dumps([]),  # TODO: Collect screenshots from checkpoints

        # Metrics
        "total_cost": metrics['total_cost'],
        "total_turns": metrics['total_turns'],
        "total_input_tokens": metrics['total_input_tokens'],
        "total_output_tokens": metrics['total_output_tokens'],
        "duration_seconds": metrics['duration_seconds'],
        "cells_visited": json.dumps(metrics['cells_visited']),
        "tools_used": json.dumps(metrics['tools_used']),

        # Taxonomy
        "tags": json.dumps(tags) if tags else "[]",

        # Branching (future)
        "parent_session_id": None,
        "branch_point_checkpoint_id": None,

        # Timestamp
        "updated_at": now
    }

    # Save to database
    try:
        _save_to_db(research_session)
    except Exception as e:
        return {"error": f"Failed to save: {str(e)}", "saved": False}

    # Add to echo history for visibility
    if echo:
        echo.add_history(
            {
                "role": "assistant",
                "content": f"💾 **Research Session Saved**\n\n**Title:** {title}\n\n{description}\n\nCheckpoints: {len(checkpoints_data)} • Cost: ${metrics['total_cost']:.4f} • Turns: {metrics['total_turns']}\n\n[Browse Sessions](/research/sessions)",
            },
            trace_id=trace.id if trace else None,
            node_type="research_session_saved"
        )

    return {
        "saved": True,
        "research_session_id": research_id,
        "title": title or f"Session {session_id[:8]}",
        "checkpoints_count": len(checkpoints_data),
        "total_cost": metrics['total_cost'],
        "total_turns": metrics['total_turns']
    }


@simple_eddy
def list_research_sessions(
    cascade_id: str = None,
    tags: list = None,
    limit: int = 20
) -> dict:
    """
    List saved research sessions with optional filtering.

    Arguments:
        cascade_id: Filter by cascade (optional)
        tags: Filter by tags (optional)
        limit: Maximum results (default 20)

    Returns:
        {"sessions": [...], "count": N}
    """
    from ..db_adapter import get_db
    import json

    try:
        db = get_db()

        # Build query
        filters = []
        if cascade_id:
            filters.append(f"cascade_id = '{cascade_id}'")

        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""

        result = db.query(f"""
            SELECT
                id, original_session_id, cascade_id, title, description,
                created_at, frozen_at, status,
                total_cost, total_turns, total_input_tokens, total_output_tokens,
                duration_seconds, tags
            FROM research_sessions
            {where_clause}
            ORDER BY frozen_at DESC
            LIMIT {limit}
        """)

        # Convert to list of dicts
        sessions = list(result) if result else []

        # Parse tags field
        for session in sessions:
            if session.get('tags') and isinstance(session['tags'], str):
                try:
                    session['tags'] = json.loads(session['tags'])
                except:
                    session['tags'] = []

        return {
            "sessions": sessions,
            "count": len(sessions)
        }

    except Exception as e:
        print(f"[ResearchSessions] Failed to list sessions: {e}")
        return {"sessions": [], "count": 0}


@simple_eddy
def get_research_session(research_session_id: str) -> dict:
    """
    Get a specific research session by ID with full context.

    Returns all data needed to display or resume the session.
    """
    from ..db_adapter import get_db
    import json

    try:
        db = get_db()

        # Query using unified adapter
        result = db.query(f"""
            SELECT * FROM research_sessions WHERE id = '{research_session_id}'
        """)

        # Convert to list
        sessions = list(result) if result else []

        if not sessions:
            return {"error": "Research session not found"}

        session = sessions[0]

        # Parse JSON fields
        json_fields = ['context_snapshot', 'checkpoints_data', 'entries_snapshot',
                      'screenshots', 'cells_visited', 'tools_used', 'tags']

        for field in json_fields:
            value = session.get(field)
            if value and isinstance(value, str):
                try:
                    session[field] = json.loads(value)
                except:
                    session[field] = [] if field.endswith('s') or field == 'checkpoints_data' else {}
            elif not value:
                session[field] = [] if field.endswith('s') or field == 'checkpoints_data' else {}

        return session

    except Exception as e:
        print(f"[ResearchSessions] Failed to get session: {e}")
        import traceback
        traceback.print_exc()
        return {"error": str(e)}


# =============================================================================
# Helper Functions
# =============================================================================

def _fetch_session_entries(session_id: str) -> list:
    """Fetch all unified_logs entries for a session using the unified DB adapter."""
    from ..db_adapter import get_db

    try:
        db = get_db()

        # Query using the unified adapter (works with both ClickHouse and DuckDB)
        result = db.query(f"""
            SELECT * FROM unified_logs
            WHERE session_id = '{session_id}'
            ORDER BY timestamp
        """)

        # Convert to list of dicts
        if hasattr(result, 'to_dict'):
            # DuckDB/chDB result
            entries = result.to_dict('records')
        elif isinstance(result, list):
            # Already a list
            entries = result
        else:
            # Fallback
            entries = []

        return entries

    except Exception as e:
        print(f"[ResearchSessions] Failed to fetch entries: {e}")
        return []


def _fetch_checkpoints_for_session(session_id: str) -> list:
    """
    Fetch all checkpoints for a session with response data.

    Each checkpoint is a potential branch point for future exploration.
    """
    from ..db_adapter import get_db

    try:
        db = get_db()

        result = db.query(f"""
            SELECT
                id, cell_name, checkpoint_type,
                cell_output, ui_spec,
                response, responded_at,
                created_at, status
            FROM checkpoints
            WHERE session_id = '{session_id}'
            ORDER BY created_at
        """)

        checkpoints = []

        # Handle different result formats
        if hasattr(result, 'to_dict'):
            # DuckDB/chDB
            checkpoints = result.to_dict('records')
        elif isinstance(result, list):
            checkpoints = result
        else:
            # Try converting to list
            try:
                checkpoints = list(result)
            except:
                checkpoints = []

        print(f"[ResearchSessions] Fetched {len(checkpoints)} checkpoints for session {session_id}")

        # Mark branch points
        for cp in checkpoints:
            cp['can_branch_from'] = cp.get('status') == 'responded'

        return checkpoints

    except Exception as e:
        print(f"[ResearchSessions] Failed to fetch checkpoints for {session_id}: {e}")
        import traceback
        traceback.print_exc()
        return []


def _compute_session_metrics(entries: list) -> dict:
    """Compute aggregate metrics from session entries."""
    if not entries:
        return {
            'total_cost': 0.0,
            'total_turns': 0,
            'total_input_tokens': 0,
            'total_output_tokens': 0,
            'duration_seconds': 0.0,
            'cells_visited': [],
            'tools_used': []
        }

    # Cost
    total_cost = sum(e.get('cost', 0) for e in entries if e.get('cost'))

    # Turns (assistant messages)
    total_turns = len([e for e in entries if e.get('role') == 'assistant'])

    # Tokens
    total_input_tokens = sum(e.get('input_tokens', 0) for e in entries)
    total_output_tokens = sum(e.get('output_tokens', 0) for e in entries)

    # Duration
    first_ts = entries[0].get('timestamp')
    last_ts = entries[-1].get('timestamp')
    duration_seconds = 0.0

    if first_ts and last_ts:
        from datetime import datetime
        first_dt = datetime.fromisoformat(str(first_ts).replace('Z', '+00:00'))
        last_dt = datetime.fromisoformat(str(last_ts).replace('Z', '+00:00'))
        duration_seconds = (last_dt - first_dt).total_seconds()

    # Cells visited
    cells_visited = list(dict.fromkeys([
        e.get('cell_name') for e in entries
        if e.get('cell_name')
    ]))

    # Tools used
    tools_used = []
    for e in entries:
        if e.get('tool_calls_json'):
            try:
                tool_calls = json.loads(e['tool_calls_json']) if isinstance(e['tool_calls_json'], str) else e['tool_calls_json']
                if isinstance(tool_calls, list):
                    for tc in tool_calls:
                        tool_name = tc.get('function', {}).get('name')
                        if tool_name and tool_name not in tools_used:
                            tools_used.append(tool_name)
            except:
                pass

    return {
        'total_cost': total_cost,
        'total_turns': total_turns,
        'total_input_tokens': total_input_tokens,
        'total_output_tokens': total_output_tokens,
        'duration_seconds': duration_seconds,
        'cells_visited': cells_visited,
        'tools_used': tools_used
    }


def _fetch_mermaid_graph(session_id: str) -> str:
    """Fetch the mermaid graph for a session."""
    from ..config import get_config

    cfg = get_config()

    # Check if graph file exists
    graph_path = os.path.join(cfg.graph_dir, f"{session_id}.mmd")

    if os.path.exists(graph_path):
        with open(graph_path, 'r') as f:
            return f.read()

    return ""


def _generate_title_from_checkpoints(checkpoints: list, cascade_id: str) -> str:
    """Auto-generate a title from checkpoint questions."""
    if not checkpoints:
        return f"Research Session - {cascade_id}"

    # Get first checkpoint question as title basis
    first_checkpoint = checkpoints[0]
    question = first_checkpoint.get('cell_output', '')

    if question:
        # Truncate to reasonable length
        title = question[:80]
        if len(question) > 80:
            title += "..."
        return title

    return f"Research Session - {cascade_id}"


def _generate_description_from_session(entries: list, checkpoints: list) -> str:
    """Auto-generate description summarizing the session."""
    if not entries and not checkpoints:
        return "Interactive research session"

    # Count key activities
    checkpoint_count = len(checkpoints)
    tool_calls = len([e for e in entries if e.get('node_type') == 'tool_call'])

    parts = []

    if checkpoint_count > 0:
        parts.append(f"{checkpoint_count} interactions")

    if tool_calls > 0:
        parts.append(f"{tool_calls} tool calls")

    if parts:
        return f"Research session with {', '.join(parts)}"

    return "Interactive research session"


def _save_to_db(research_session: dict):
    """Save research session to database."""
    from ..config import get_config
    from ..db_adapter import get_db

    cfg = get_config()
    db = get_db()

    try:
        if cfg.use_clickhouse_server:
            # ClickHouse server
            db.insert_rows('research_sessions', [research_session], columns=list(research_session.keys()))
            print(f"[ResearchSessions] Saved to ClickHouse: {research_session['id']}")

        else:
            # chDB mode - save to Parquet
            _save_to_parquet(research_session, cfg)

    except Exception as e:
        print(f"[ResearchSessions] Save failed: {e}")
        import traceback
        traceback.print_exc()
        # Try Parquet fallback
        try:
            _save_to_parquet(research_session, cfg)
            print(f"[ResearchSessions] Fell back to Parquet successfully")
        except Exception as e2:
            print(f"[ResearchSessions] Parquet fallback also failed: {e2}")
            raise


def _save_to_parquet(research_session: dict, cfg):
    """Save to Parquet file (chDB mode)."""
    data_dir = cfg.data_dir
    os.makedirs(data_dir, exist_ok=True)

    sessions_file = os.path.join(data_dir, "research_sessions.parquet")

    if os.path.exists(sessions_file):
        # Append to existing
        try:
            import chdb
            import pandas as pd
            existing_df = chdb.query(f"SELECT * FROM file('{sessions_file}', Parquet)").to_df()
            new_df = pd.concat([existing_df, pd.DataFrame([research_session])], ignore_index=True)
            new_df.to_parquet(sessions_file, index=False)
        except Exception as e:
            print(f"[ResearchSessions] Failed to append: {e}")
            # Fallback: overwrite
            import pandas as pd
            pd.DataFrame([research_session]).to_parquet(sessions_file, index=False)
    else:
        # Create new file
        import pandas as pd
        pd.DataFrame([research_session]).to_parquet(sessions_file, index=False)
