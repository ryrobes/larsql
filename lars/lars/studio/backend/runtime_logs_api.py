"""
Runtime Logs API - Browse runtime_event_log (append-only operational logs).

This is separate from `unified_logs` (which is cascade/message execution data).
"""

from flask import Blueprint, jsonify, request


runtime_logs_bp = Blueprint("runtime_logs", __name__)


def _get_db():
    """Get DuckDB database adapter."""
    try:
        from lars.db_adapter import get_db as lars_get_db
        return lars_get_db()
    except Exception as e:
        print(f"[runtime_logs_api] Failed to get DB: {e}")
        return None


def _format_timestamp_utc(ts):
    """
    Format a timestamp as ISO string with UTC timezone indicator.

    DuckDB returns naive datetime objects. Adding 'Z' tells the browser
    to interpret it as UTC and convert to local time for display.
    """
    if ts is None:
        return None
    if hasattr(ts, "isoformat"):
        iso = ts.isoformat()
        if not iso.endswith("Z") and "+" not in iso and "-" not in iso[-6:]:
            return iso + "Z"
        return iso
    return str(ts)


def _parse_list_args(name: str) -> list[str]:
    """
    Accept repeated query params (?level=INFO&level=ERROR) and/or comma-separated (?level=INFO,ERROR).
    """
    values = []
    for raw in request.args.getlist(name):
        if not raw:
            continue
        parts = [p.strip() for p in str(raw).split(",")]
        values.extend([p for p in parts if p])
    # De-dupe while preserving order
    seen = set()
    out = []
    for v in values:
        if v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


def _add_in_filter(where_clauses: list[str], params: dict, *, col: str, values: list[str], prefix: str) -> None:
    if not values:
        return
    placeholders = []
    for i, value in enumerate(values[:200]):  # cap to avoid pathological queries
        key = f"{prefix}{i}"
        placeholders.append(f"%({key})s")
        params[key] = value
    where_clauses.append(f"{col} IN ({', '.join(placeholders)})")


@runtime_logs_bp.route("/api/runtime-logs", methods=["GET"])
def list_runtime_logs():
    """
    List runtime log rows from DuckDB.

    Query params:
      - hours: lookback window (default 24, max 720)
      - limit: max rows (default 500, max 2000)
      - offset: pagination offset
      - search: substring search across message/event/ids/json
      - level/source/event: multi-select filters (repeatable and/or comma-separated)
      - connection_id/session_id/query_id/caller_id/database_name/auth_user_id: exact match filters
      - include_facets: "0" to disable facet counts (default enabled)
    """
    try:
        # Clear cached connection to ensure fresh view of parquet files
        try:
            from lars.lars_db import get_lars_db
            get_lars_db().clear_cached_connection()
        except Exception:
            pass
        
        db = _get_db()
        if db is None:
            return jsonify({"error": "Database not available"}), 500

        hours = int(request.args.get("hours", 24))
        hours = max(1, min(hours, 24 * 30))  # table TTL is 30d

        limit = int(request.args.get("limit", 500))
        limit = max(1, min(limit, 2000))

        offset = int(request.args.get("offset", 0))
        offset = max(0, offset)

        include_facets = str(request.args.get("include_facets", "1")).strip() not in ("0", "false", "no", "off")

        search = (request.args.get("search") or "").strip()
        connection_id = (request.args.get("connection_id") or "").strip() or None
        session_id = (request.args.get("session_id") or "").strip() or None
        query_id = (request.args.get("query_id") or "").strip() or None
        caller_id = (request.args.get("caller_id") or "").strip() or None
        database_name = (request.args.get("database_name") or "").strip() or None
        auth_user_id = (request.args.get("auth_user_id") or "").strip() or None

        levels = [v.strip().upper() for v in _parse_list_args("level")]
        sources = [v.strip() for v in _parse_list_args("source")]
        events = [v.strip() for v in _parse_list_args("event")]

        base_where = ["timestamp >= now() - INTERVAL %(hours)s HOUR"]
        base_params: dict = {"hours": hours}

        # Search (case-insensitive). Use ILIKE for simplicity.
        if search:
            base_where.append(
                "("
                "message ILIKE %(search)s OR "
                "extra_json ILIKE %(search)s OR "
                "event ILIKE %(search)s OR "
                "source ILIKE %(search)s OR "
                "level ILIKE %(search)s OR "
                "connection_id ILIKE %(search)s OR "
                "ifNull(session_id, '') ILIKE %(search)s OR "
                "ifNull(query_id, '') ILIKE %(search)s OR "
                "ifNull(caller_id, '') ILIKE %(search)s OR "
                "ifNull(database_name, '') ILIKE %(search)s OR "
                "ifNull(application_name, '') ILIKE %(search)s OR "
                "ifNull(client_addr, '') ILIKE %(search)s"
                ")"
            )
            base_params["search"] = f"%{search}%"

        # Exact match filters
        if connection_id:
            base_where.append("connection_id = %(connection_id)s")
            base_params["connection_id"] = connection_id
        if session_id:
            base_where.append("session_id = %(session_id)s")
            base_params["session_id"] = session_id
        if query_id:
            base_where.append("query_id = %(query_id)s")
            base_params["query_id"] = query_id
        if caller_id:
            base_where.append("caller_id = %(caller_id)s")
            base_params["caller_id"] = caller_id
        if database_name:
            base_where.append("database_name = %(database_name)s")
            base_params["database_name"] = database_name
        if auth_user_id:
            base_where.append("auth_user_id = %(auth_user_id)s")
            base_params["auth_user_id"] = auth_user_id

        base_where_sql = " AND ".join(base_where) if base_where else "1=1"

        # Apply multi-select filters on top
        where = list(base_where)
        params = dict(base_params)
        _add_in_filter(where, params, col="level", values=levels, prefix="level_")
        _add_in_filter(where, params, col="source", values=sources, prefix="source_")
        _add_in_filter(where, params, col="event", values=events, prefix="event_")
        where_sql = " AND ".join(where) if where else "1=1"

        # Total count (filtered)
        total_row = db.query(f"SELECT count() as cnt FROM runtime_event_log WHERE {where_sql}", params)
        total = int(total_row[0]["cnt"]) if total_row else 0

        # Rows
        query = f"""
            SELECT
                CAST(event_id AS VARCHAR) as event_id,
                timestamp,
                timestamp_iso,
                connection_id,
                source,
                level,
                event,
                message,
                extra_json,
                session_id,
                query_id,
                caller_id,
                user_name,
                auth_user_id,
                database_name,
                results_db,
                application_name,
                client_addr,
                thread_id
            FROM runtime_event_log
            WHERE {where_sql}
            ORDER BY timestamp DESC
            LIMIT %(limit)s OFFSET %(offset)s
        """
        params["limit"] = limit
        params["offset"] = offset
        rows = db.query(query, params)

        logs = []
        for row in rows:
            logs.append(
                {
                    "event_id": row.get("event_id"),
                    "timestamp": _format_timestamp_utc(row.get("timestamp")),
                    "timestamp_iso": row.get("timestamp_iso"),
                    "connection_id": row.get("connection_id") or "",
                    "source": row.get("source") or "",
                    "level": row.get("level") or "",
                    "event": row.get("event") or "",
                    "message": row.get("message") or "",
                    "extra_json": row.get("extra_json") or "{}",
                    "session_id": row.get("session_id"),
                    "query_id": row.get("query_id"),
                    "caller_id": row.get("caller_id"),
                    "user_name": row.get("user_name"),
                    "auth_user_id": row.get("auth_user_id"),
                    "database_name": row.get("database_name"),
                    "results_db": row.get("results_db"),
                    "application_name": row.get("application_name"),
                    "client_addr": row.get("client_addr"),
                    "thread_id": row.get("thread_id"),
                }
            )

        facets = {}
        if include_facets:
            # Small helper to run a facet query and return [{value, count}]
            def run_facet(sql: str, value_key: str) -> list[dict]:
                out = []
                for r in db.query(sql, base_params):
                    out.append({"value": r.get(value_key) or "", "count": int(r.get("cnt") or 0)})
                return out

            facets["levels"] = run_facet(
                f"""
                    SELECT level, count() as cnt
                    FROM runtime_event_log
                    WHERE {base_where_sql}
                    GROUP BY level
                    ORDER BY cnt DESC
                """,
                "level",
            )
            facets["sources"] = run_facet(
                f"""
                    SELECT source, count() as cnt
                    FROM runtime_event_log
                    WHERE {base_where_sql}
                    GROUP BY source
                    ORDER BY cnt DESC
                    LIMIT 50
                """,
                "source",
            )
            facets["events"] = run_facet(
                f"""
                    SELECT event, count() as cnt
                    FROM runtime_event_log
                    WHERE {base_where_sql}
                    GROUP BY event
                    ORDER BY cnt DESC
                    LIMIT 200
                """,
                "event",
            )

        return jsonify(
            {
                "logs": logs,
                "total": total,
                "limit": limit,
                "offset": offset,
                "hours": hours,
                "filters": {
                    "search": search,
                    "connection_id": connection_id,
                    "session_id": session_id,
                    "query_id": query_id,
                    "caller_id": caller_id,
                    "database_name": database_name,
                    "auth_user_id": auth_user_id,
                    "level": levels,
                    "source": sources,
                    "event": events,
                },
                "facets": facets,
            }
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500
