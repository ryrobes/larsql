"""
Bash as a first-class data transformation substrate.

Bash scripts can read from previous cells (via stdin as CSV) and write
structured output (via stdout as CSV/JSON/JSONL) that gets materialized
as temp tables for downstream cells.
"""

import subprocess
import time
import os
import io
import pandas as pd
from typing import Optional, Dict, Any

from .base import simple_eddy
from ..sql_tools.session_db import get_session_db
from ..config import get_config


@simple_eddy
def bash_data(
    script: str,
    input_table: Optional[str] = None,
    output_format: str = "csv",
    timeout: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    persist_session: bool = True,
    _cell_name: str | None = None,
    _session_id: str | None = None,
    _outputs: Dict[str, Any] | None = None,
    _state: Dict[str, Any] | None = None,
    _input: Dict[str, Any] | None = None,
    _caller_id: str | None = None,
    _cascade_id: str | None = None
) -> Dict[str, Any]:
    """
    Execute bash script as a data transformation cell.

    Data Flow:
    - Input: Previous cell's temp table as CSV on stdin
    - Output: Structured data (CSV/JSON/JSONL) on stdout → new temp table

    Persistence:
    - By default (persist_session=True), uses a persistent bash process
    - Environment variables, working directory, and shell functions persist
    - Each cascade session gets its own bash REPL

    Args:
        script: Bash script to execute
        input_table: Temp table name to read (default: previous cell = _{prev_cell})
        output_format: Format of stdout (csv, json, jsonl, auto)
        timeout: Execution timeout (e.g., "30s", "5m", default: "5m")
        env: Additional environment variables (only for first cell if persist_session=True)
        persist_session: Use persistent bash process (default: True)
        _cell_name: Injected by runner - current cell name
        _session_id: Injected by runner - session ID
        _outputs: Injected by runner - prior cell outputs

    Environment variables provided to script:
        $SESSION_DB: Path to session DuckDB file
        $SESSION_DIR: Path to session temp directory
        $SESSION_ID: Current session ID
        $CELL_NAME: Current cell name

    Returns:
        {
            "rows": List[Dict],  # Output data as records
            "columns": List[str],
            "row_count": int,
            "_route": "success" | "error"
        }

    Example - Persistent environment:
        # Cell 1: Setup
        - name: setup
          tool: bash_data
          inputs:
            script: |
              export API_KEY=secret123
              cd /workspace/project
              function fetch() { curl -s "$1"; }

        # Cell 2: Use persistent state
        - name: fetch_data
          tool: bash_data
          inputs:
            script: |
              # Has API_KEY, cwd, and fetch() function!
              fetch "https://api.com/data?key=$API_KEY" | jq -c '.items[]'
            output_format: jsonl
    """
    try:
        # Get session context
        session_db = get_session_db(_session_id) if _session_id else None
        config = get_config()

        # Convert to Path object if it's a string
        from pathlib import Path
        state_dir = Path(config.state_dir) if isinstance(config.state_dir, str) else config.state_dir
        session_dir = state_dir / _session_id if _session_id else state_dir
        session_dir.mkdir(parents=True, exist_ok=True)

        # Determine input table - try to find previous cell
        if input_table is None and _outputs:
            # Get the last cell with data output
            for item in reversed(list(_outputs.items())):
                cell_name, output = item
                if isinstance(output, dict) and ('rows' in output or 'row_count' in output):
                    input_table = f"_{cell_name}"
                    break

        # Prepare input CSV from temp table
        input_csv = None
        if input_table and session_db:
            try:
                df = session_db.execute(f"SELECT * FROM {input_table}").fetchdf()
                input_csv = df.to_csv(index=False)
            except Exception:
                # Table doesn't exist - that's ok, script might not need input
                pass

        # Compute SESSION_DB path (same logic as get_session_db)
        session_db_path = ""
        if _session_id:
            session_db_dir = os.path.join(config.root_dir, 'session_dbs')
            safe_session_id = _session_id.replace("/", "_").replace("\\", "_")
            session_db_path = os.path.join(session_db_dir, f"{safe_session_id}.duckdb")

        # Build environment
        bash_env = {
            "SESSION_DB": session_db_path,
            "SESSION_DIR": str(session_dir),
            "SESSION_ID": _session_id or "",
            "CELL_NAME": _cell_name or "",
            "PATH": os.environ.get("PATH", ""),
            **os.environ,
            **(env or {})
        }

        # Parse timeout (default 5 minutes)
        timeout_seconds = _parse_timeout(timeout) if timeout else 300

        # Execute script
        start = time.time()

        if persist_session and _session_id:
            # Use persistent bash session (REPL mode)
            from .bash_session import get_bash_session

            # Get or create the session
            # env is only used on first call (when session is created)
            session = get_bash_session(_session_id, session_dir, env)

            # Update SESSION_DB and CELL_NAME for each execution
            # These change per cell, so we inject them as shell variables
            setup_script = f"""
export SESSION_DB='{session_db_path}'
export CELL_NAME='{_cell_name or ""}'
"""

            # Execute setup + user script
            result = session.execute(setup_script + script, timeout=timeout_seconds, input_data=input_csv)
            duration = result.duration

            # Check exit code
            if result.exit_code != 0:
                return {
                    "_route": "error",
                    "error": f"Bash script failed with exit code {result.exit_code}",
                    "stderr": result.stderr,
                    "stdout": result.stdout[:500] if result.stdout else "",
                    "exit_code": result.exit_code
                }

            stdout = result.stdout
            stderr = result.stderr

        else:
            # One-shot execution (original behavior)
            result = subprocess.run(
                ["bash", "-c", script],
                input=input_csv,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=bash_env,
                cwd=str(session_dir)
            )
            duration = time.time() - start

            # Check exit code
            if result.returncode != 0:
                return {
                    "_route": "error",
                    "error": f"Bash script failed with exit code {result.returncode}",
                    "stderr": result.stderr,
                    "stdout": result.stdout[:500] if result.stdout else "",
                    "exit_code": result.returncode
                }

            stdout = result.stdout
            stderr = result.stderr

        # Parse output
        stdout = stdout.strip()
        if not stdout:
            # Empty output - create empty DataFrame
            df = pd.DataFrame()
        else:
            # Detect format if auto
            if output_format == "auto":
                output_format = _detect_format(stdout)

            # Parse based on format
            df = _parse_output(stdout, output_format)

        # Materialize as temp table (following sql_data pattern)
        if _cell_name and session_db and len(df) > 0:
            table_name = f"_{_cell_name}"
            session_db.register("_temp_df", df)
            session_db.execute(f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM _temp_df")
            session_db.unregister("_temp_df")

        # Return structured result (matching data_tools pattern)
        return {
            "rows": df.to_dict('records') if len(df) > 0 else [],
            "columns": list(df.columns) if len(df) > 0 else [],
            "row_count": len(df),
            "duration": duration,
            "stderr": result.stderr if result.stderr else None,
            "_route": "success"
        }

    except subprocess.TimeoutExpired:
        return {
            "_route": "error",
            "error": f"Bash script timed out after {timeout_seconds}s"
        }
    except Exception as e:
        import traceback
        return {
            "_route": "error",
            "error": str(e),
            "traceback": traceback.format_exc()
        }


def _parse_timeout(timeout_str: str) -> int:
    """Parse timeout string (e.g., '30s', '5m') to seconds."""
    import re
    match = re.match(r'^(\d+)(s|m|h)?$', timeout_str.strip())
    if not match:
        raise ValueError(f"Invalid timeout format: {timeout_str}")

    value = int(match.group(1))
    unit = match.group(2) or 's'

    multipliers = {'s': 1, 'm': 60, 'h': 3600}
    return value * multipliers[unit]


def _detect_format(data: str) -> str:
    """Auto-detect if output is CSV, JSON, or JSONL."""
    data = data.strip()

    if not data:
        return "csv"

    # Check first character
    first_char = data[0]

    # JSON array or object
    if first_char in '[{':
        try:
            import json
            json.loads(data)
            return "json"
        except:
            pass

    # Check if all non-empty lines are JSON objects (JSONL)
    lines = [l.strip() for l in data.split('\n') if l.strip()]
    if lines and all(l.startswith('{') and l.endswith('}') for l in lines):
        try:
            import json
            for line in lines[:5]:  # Check first 5 lines
                json.loads(line)
            return "jsonl"
        except:
            pass

    # Default to CSV
    return "csv"


def _parse_output(data: str, format: str) -> pd.DataFrame:
    """Parse bash stdout into DataFrame."""
    data = data.strip()

    if not data:
        return pd.DataFrame()

    try:
        if format == "csv":
            return pd.read_csv(io.StringIO(data))
        elif format == "json":
            return pd.read_json(io.StringIO(data))
        elif format == "jsonl":
            return pd.read_json(io.StringIO(data), lines=True)
        else:
            raise ValueError(f"Unsupported format: {format}")
    except Exception as e:
        raise ValueError(
            f"Failed to parse output as {format}: {e}\n\n"
            f"Output preview:\n{data[:500]}\n\n"
            f"Hint: Verify output format or set output_format explicitly"
        )
