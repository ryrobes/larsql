"""
RVBBIT LARS CLI skill — run lars commands through RVBBIT.

Fires commands via the embedded server API, which streams output
to RVBBIT's debug console. The companion can trigger maintenance
tasks like schema crawling, health checks, etc.
"""

import os
import json
import time
import requests
from typing import Optional, List
from .base import simple_eddy
from ..skill_registry import register_skill
from ..console_style import S


def _rvbbit_url(path: str) -> str:
    port = int(os.environ.get("RVBBIT_PORT", "9876"))
    return f"http://127.0.0.1:{port}{path}"


@simple_eddy
def lars_crawl(force: bool = False) -> str:
    """
    Run `lars sql crawl` to discover and index all database schemas.
    
    This scans all configured SQL connections, discovers tables/columns,
    and builds the RAG index for semantic search. Run this after adding
    new data sources or when schema_search returns stale results.
    
    Output streams to the RVBBIT debug console in real-time.
    
    Args:
        force: If True, re-crawl even if schemas haven't changed
    
    Returns:
        Status message (command runs async — check console for output)
    """
    from rich.console import Console
    console = Console()
    
    try:
        args = ["sql", "crawl"]
        if force:
            args.append("--force")
        
        resp = requests.post(
            _rvbbit_url("/lars/run"),
            json={"args": args, "label": "SQL Crawl"},
            timeout=10,
        )
        resp.raise_for_status()
        result = resp.json()
        console.print(f"[green]{S.OK} SQL crawl started — output streaming to RVBBIT console[/green]")
        return json.dumps(result)
    except requests.exceptions.ConnectionError:
        return json.dumps({"error": "RVBBIT not reachable"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@simple_eddy
def lars_doctor() -> str:
    """
    Run `lars doctor` to check workspace health, environment, and database connectivity.
    
    Returns:
        Status message (command runs async — check console for output)
    """
    try:
        resp = requests.post(
            _rvbbit_url("/lars/run"),
            json={"args": ["doctor"], "label": "Doctor"},
            timeout=10,
        )
        resp.raise_for_status()
        return json.dumps(resp.json())
    except requests.exceptions.ConnectionError:
        return json.dumps({"error": "RVBBIT not reachable"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@simple_eddy
def lars_command(args: str, label: Optional[str] = None) -> str:
    """
    Run an arbitrary `lars` CLI command through RVBBIT.
    
    Output streams to the RVBBIT debug console. Use for any LARS operation
    not covered by a specific skill.
    
    Args:
        args: Space-separated arguments (e.g., "sql crawl --force", "config show",
              "embed build", "sql test-connection mydb")
        label: Optional human-readable label for the console
    
    Returns:
        Status message (command runs async — check console for output)
    """
    from rich.console import Console
    console = Console()
    
    try:
        arg_list = args.strip().split()
        if not arg_list:
            return json.dumps({"error": "No arguments provided"})
        
        payload = {"args": arg_list}
        if label:
            payload["label"] = label
        
        resp = requests.post(
            _rvbbit_url("/lars/run"),
            json=payload,
            timeout=10,
        )
        resp.raise_for_status()
        result = resp.json()
        console.print(f"[green]{S.OK} lars {args} — started[/green]")
        return json.dumps(result)
    except requests.exceptions.ConnectionError:
        return json.dumps({"error": "RVBBIT not reachable"})
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Registration ──

register_skill("lars_crawl", lars_crawl)
register_skill("lars_doctor", lars_doctor)
register_skill("lars_command", lars_command)
