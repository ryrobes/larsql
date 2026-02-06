"""SQL connection utilities for TUI apps.

Shared between lars_control_panel.py and lars_bootstrap_tui.py.
"""

import os
import json
import subprocess
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple
import yaml


# =============================================================================
# CONNECTION TYPE DEFINITIONS
# =============================================================================

CONNECTION_TYPES = {
    "postgres": {
        "icon": "🐘",
        "label": "PostgreSQL",
        "fields": [
            ("host", "Host", "localhost", True),
            ("port", "Port", "5432", True),
            ("database", "Database", "", True),
            ("user", "User", "postgres", True),
            ("password_env", "Password Env Var", "", False),
        ]
    },
    "mysql": {
        "icon": "🐬",
        "label": "MySQL",
        "fields": [
            ("host", "Host", "localhost", True),
            ("port", "Port", "3306", True),
            ("database", "Database", "", True),
            ("user", "User", "root", True),
            ("password_env", "Password Env Var", "", False),
        ]
    },
    "sqlite": {
        "icon": "📦",
        "label": "SQLite",
        "fields": [
            ("database", "Database Path", "", True),
        ]
    },
    "duckdb": {
        "icon": "🦆",
        "label": "DuckDB",
        "fields": [
            ("database", "Database Path", "", True),
        ]
    },
    "bigquery": {
        "icon": "☁️",
        "label": "BigQuery",
        "fields": [
            ("project_id", "GCP Project ID", "", True),
            ("credentials_env", "Credentials Env Var", "GOOGLE_APPLICATION_CREDENTIALS", False),
        ]
    },
    "snowflake": {
        "icon": "❄️",
        "label": "Snowflake",
        "fields": [
            ("account", "Account", "", True),
            ("user", "User", "", True),
            ("database", "Database", "", False),
            ("warehouse", "Warehouse", "", False),
            ("role", "Role", "", False),
        ]
    },
    "motherduck": {
        "icon": "🦆",
        "label": "MotherDuck",
        "fields": [
            ("database", "Database", "my_db", True),
            ("motherduck_token_env", "Token Env Var", "MOTHERDUCK_TOKEN", False),
        ]
    },
    "clickhouse": {
        "icon": "🏠",
        "label": "ClickHouse",
        "fields": [
            ("host", "Host", "localhost", True),
            ("port", "Port", "8123", True),
            ("database", "Database", "default", True),
            ("user", "User", "default", False),
            ("password_env", "Password Env Var", "", False),
        ]
    },
    "csv_folder": {
        "icon": "📂",
        "label": "CSV Folder",
        "fields": [
            ("folder_path", "Folder Path", "", True),
            ("file_pattern", "File Pattern", "*.csv", False),
        ]
    },
    "jsonl_folder": {
        "icon": "📄",
        "label": "JSONL Folder",
        "fields": [
            ("folder_path", "Folder Path", "", True),
            ("file_pattern", "File Pattern", "*.jsonl", False),
        ]
    },
    "markdown_folder": {
        "icon": "📝",
        "label": "Markdown Folder",
        "fields": [
            ("folder_path", "Folder Path", "", True),
        ]
    },
    "s3": {
        "icon": "☁️",
        "label": "S3 / MinIO",
        "fields": [
            ("bucket", "Bucket", "", True),
            ("prefix", "Prefix", "", False),
            ("region", "Region", "us-east-1", False),
            ("endpoint_url", "Endpoint URL (MinIO)", "", False),
            ("access_key_env", "Access Key Env Var", "AWS_ACCESS_KEY_ID", False),
            ("secret_key_env", "Secret Key Env Var", "AWS_SECRET_ACCESS_KEY", False),
        ]
    },
    "mongodb": {
        "icon": "🍃",
        "label": "MongoDB",
        "fields": [
            ("mongodb_uri_env", "URI Env Var", "MONGODB_URI", True),
        ]
    },
}

# Quick lookup for icons
CONNECTION_ICONS = {k: v["icon"] for k, v in CONNECTION_TYPES.items()}


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class ConnectionField:
    """A field in a connection configuration form."""
    name: str
    label: str
    default: str
    required: bool
    value: str = ""


def get_fields_for_type(conn_type: str) -> List[ConnectionField]:
    """Get form fields for a connection type.
    
    Args:
        conn_type: Connection type key (e.g. "postgres", "mysql")
    
    Returns:
        List of ConnectionField objects
    """
    type_def = CONNECTION_TYPES.get(conn_type)
    if not type_def:
        return []
    
    return [
        ConnectionField(
            name=field[0],
            label=field[1],
            default=field[2],
            required=field[3],
        )
        for field in type_def.get("fields", [])
    ]


# =============================================================================
# CONNECTION TESTING
# =============================================================================

def test_connection(
    conn_name: str,
    lars_root: Optional[str] = None,
    timeout: int = 60,
) -> Dict[str, Any]:
    """Test a connection using lars CLI.
    
    Args:
        conn_name: Name of the connection to test
        lars_root: LARS_ROOT directory (uses env var if not provided)
        timeout: Timeout in seconds
    
    Returns:
        Dict with 'success', 'message', and optionally other fields
    """
    env = os.environ.copy()
    if lars_root:
        env['LARS_ROOT'] = lars_root
    
    try:
        result = subprocess.run(
            ["lars", "sql", "tc", conn_name, "--json"],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        
        if result.returncode == 0:
            try:
                data = json.loads(result.stdout.strip())
                if data and isinstance(data, list):
                    return data[0]
                elif data:
                    return data
            except json.JSONDecodeError:
                pass
            return {"success": True, "message": "Connection successful"}
        
        return {"success": False, "message": result.stderr.strip() or "Test failed"}
    
    except subprocess.TimeoutExpired:
        return {"success": False, "message": f"Connection test timed out ({timeout}s)"}
    except FileNotFoundError:
        return {"success": False, "message": "lars CLI not found"}
    except Exception as e:
        return {"success": False, "message": str(e)}


# =============================================================================
# CONNECTION BUILDING & SAVING
# =============================================================================

def build_connection_yaml(
    conn_type: str,
    conn_name: str,
    fields: List[ConnectionField],
) -> Dict[str, Any]:
    """Build a connection YAML config from form fields.
    
    Args:
        conn_type: Connection type (e.g. "postgres")
        conn_name: Connection name
        fields: List of ConnectionField with values set
    
    Returns:
        Dict suitable for YAML serialization
    """
    config = {
        "name": conn_name,
        "type": conn_type,
        "enabled": True,
    }
    
    for field in fields:
        value = field.value.strip() if field.value else field.default
        if value:
            # Handle special cases
            if field.name == "port":
                try:
                    config[field.name] = int(value)
                except ValueError:
                    config[field.name] = value
            else:
                config[field.name] = value
    
    return config


def save_connection(
    config: Dict[str, Any],
    lars_root: Optional[str] = None,
) -> Tuple[bool, str]:
    """Save a connection configuration to the sql_connections directory.
    
    Args:
        config: Connection config dict (from build_connection_yaml)
        lars_root: LARS_ROOT directory (uses env var if not provided)
    
    Returns:
        Tuple of (success, message/path)
    """
    if not lars_root:
        lars_root = os.environ.get('LARS_ROOT', os.path.expanduser('~/.lars'))
    
    conn_dir = os.path.join(lars_root, 'sql_connections')
    os.makedirs(conn_dir, exist_ok=True)
    
    conn_name = config.get('name', 'unnamed')
    # Sanitize filename
    safe_name = "".join(c if c.isalnum() or c in ('_', '-') else '_' for c in conn_name)
    file_path = os.path.join(conn_dir, f"{safe_name}.yaml")
    
    try:
        with open(file_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)
        return True, file_path
    except Exception as e:
        return False, str(e)


def list_connection_types() -> List[Dict[str, str]]:
    """Get list of connection types for display.
    
    Returns:
        List of dicts with 'key', 'icon', 'label'
    """
    return [
        {"key": k, "icon": v["icon"], "label": v["label"]}
        for k, v in CONNECTION_TYPES.items()
    ]
