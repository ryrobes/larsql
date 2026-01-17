"""
Catalog API - Unified browser for all LARS system components

Provides endpoints for browsing:
- Tools (skills) - Python functions, cascade tools, memory tools, local models
- LLM Models - OpenRouter models, Ollama local models
- Local Models - HuggingFace transformers
- MCP Servers - Model Context Protocol servers and their tools
- HuggingFace Spaces (Harbor) - Gradio tools from HF Spaces
- Memory Banks - RAG knowledge bases
- Cascades - Workflow definitions
- Signals - Cross-cascade communication events
- Sessions - Execution state
- Embeddings - Embedding configuration
"""
import os
import sys
import json
import math
from datetime import datetime
from flask import Blueprint, jsonify, request

# Add lars to path
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "../.."))
_LARS_DIR = os.path.join(_REPO_ROOT, "lars")
if _LARS_DIR not in sys.path:
    sys.path.insert(0, _LARS_DIR)

try:
    from lars.db_adapter import get_db
    from lars.config import get_config
except ImportError as e:
    print(f"Warning: Could not import lars modules: {e}")
    get_db = None
    get_config = None

# Import skills manifest for local model tools
try:
    from lars.skills_manifest import get_skill_manifest
except ImportError:
    get_skill_manifest = None

catalog_bp = Blueprint('catalog', __name__, url_prefix='/api/catalog')


def sanitize_for_json(obj):
    """Recursively sanitize an object for JSON serialization."""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    elif isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_for_json(item) for item in obj]
    elif isinstance(obj, bytes):
        return f"<binary data: {len(obj)} bytes>"
    elif hasattr(obj, 'isoformat'):
        return obj.isoformat()
    return obj


@catalog_bp.route('', methods=['GET'])
def get_catalog():
    """
    Get unified catalog of all system components.

    Query params:
        - category: Filter by category (tools, models, mcp, harbor, memory, cascades, signals, sessions)
        - type: Filter by type within category (e.g., 'function', 'cascade', 'local_model' for tools)
        - search: Text search across name and description
        - limit: Max items to return (default 500)
        - offset: Pagination offset (default 0)

    Returns:
        {
            "items": [...],
            "total": count,
            "categories": { category: count, ... }
        }
    """
    try:
        db = get_db()

        category_filter = request.args.get('category')
        type_filter = request.args.get('type')
        search = request.args.get('search', '').strip().lower()
        limit = int(request.args.get('limit', 500))
        offset = int(request.args.get('offset', 0))

        all_items = []
        category_counts = {}

        # ==================================
        # 1. TOOLS from tool_manifest_vectors
        # ==================================
        try:
            tools_query = """
                SELECT
                    tool_name,
                    tool_type,
                    tool_description,
                    source_path,
                    last_updated
                FROM tool_manifest_vectors
                ORDER BY tool_name
            """
            tools_rows = db.query(tools_query)

            # Deduplicate tools (keep first occurrence which is usually the best type)
            seen_tools = set()
            for row in tools_rows:
                tool_name = row.get('tool_name', '')
                if tool_name in seen_tools:
                    continue
                seen_tools.add(tool_name)

                all_items.append({
                    'id': f"tool:{tool_name}",
                    'name': tool_name,
                    'category': 'tools',
                    'type': row.get('tool_type', 'unknown'),
                    'description': row.get('tool_description', ''),
                    'source': row.get('source_path', ''),
                    'updated_at': row.get('last_updated'),
                    'metadata': {}
                })

            category_counts['tools'] = len(seen_tools)
        except Exception as e:
            print(f"[Catalog] Error fetching tools: {e}")
            category_counts['tools'] = 0

        # ==================================
        # 2. LLM MODELS from openrouter_models
        # ==================================
        try:
            models_query = """
                SELECT
                    model_id,
                    model_name,
                    description,
                    provider,
                    tier,
                    model_type,
                    context_length,
                    prompt_price,
                    completion_price,
                    is_active,
                    input_modalities,
                    output_modalities,
                    updated_at
                FROM openrouter_models
                WHERE is_active = 1
                ORDER BY provider, model_name
            """
            models_rows = db.query(models_query)

            cloud_models_count = 0
            ollama_count = 0

            for row in models_rows:
                model_id = row.get('model_id', '')
                provider = row.get('provider', '')
                # Detect Ollama models by provider
                is_ollama = provider.lower() in ('ollama', 'local')
                # Check image capabilities from modalities
                input_mods = row.get('input_modalities', []) or []
                output_mods = row.get('output_modalities', []) or []
                can_input_images = 'image' in input_mods
                can_output_images = 'image' in output_mods

                # Separate Ollama into its own category
                if is_ollama:
                    category = 'ollama'
                    ollama_count += 1
                else:
                    category = 'models'
                    cloud_models_count += 1

                all_items.append({
                    'id': f"model:{model_id}",
                    'name': row.get('model_name', model_id),
                    'category': category,
                    'type': row.get('tier', 'standard') if not is_ollama else 'local',
                    'description': row.get('description', ''),
                    'source': provider,
                    'updated_at': row.get('updated_at'),
                    'metadata': {
                        'model_id': model_id,
                        'provider': provider,
                        'tier': row.get('tier'),
                        'model_type': row.get('model_type'),
                        'context_length': row.get('context_length'),
                        'prompt_price': row.get('prompt_price'),
                        'completion_price': row.get('completion_price'),
                        'can_output_images': can_output_images,
                        'can_input_images': can_input_images,
                        'is_ollama': is_ollama
                    }
                })

            category_counts['models'] = cloud_models_count
            category_counts['ollama'] = ollama_count
        except Exception as e:
            print(f"[Catalog] Error fetching models: {e}")
            category_counts['models'] = 0
            category_counts['ollama'] = 0

        # ==================================
        # 2.5. LOCAL MODELS from skill manifest (HuggingFace Transformers)
        # ==================================
        try:
            if get_skill_manifest:
                import yaml
                manifest = get_skill_manifest(refresh=False)
                local_tools = {k: v for k, v in manifest.items() if 'local_model' in v.get('type', '')}

                for tool_id, tool_def in local_tools.items():
                    # Read the source YAML to get model_id, task, device
                    source_path = tool_def.get('path', '')
                    model_id = ''
                    task = ''
                    device = 'auto'
                    inputs_schema = {}

                    if source_path and os.path.exists(source_path):
                        try:
                            with open(source_path, 'r') as f:
                                yaml_content = yaml.safe_load(f) or {}
                                model_id = yaml_content.get('model_id', '')
                                task = yaml_content.get('task', '')
                                device = yaml_content.get('device', 'auto')
                                inputs_schema = yaml_content.get('inputs_schema', {})
                        except Exception as e:
                            print(f"[Catalog] Error reading local model YAML {source_path}: {e}")

                    all_items.append({
                        'id': f"local_model:{tool_id}",
                        'name': tool_id,
                        'category': 'local_models',
                        'type': 'transformer',
                        'description': tool_def.get('description', ''),
                        'source': source_path,
                        'updated_at': None,
                        'metadata': {
                            'model_id': model_id,
                            'task': task,
                            'device': device,
                            'type': tool_def.get('type', ''),
                            'inputs_schema': inputs_schema
                        }
                    })

                category_counts['local_models'] = len(local_tools)
            else:
                category_counts['local_models'] = 0
        except Exception as e:
            print(f"[Catalog] Error fetching local models: {e}")
            category_counts['local_models'] = 0

        # ==================================
        # 3. HUGGINGFACE SPACES from hf_spaces
        # ==================================
        try:
            harbor_query = """
                SELECT
                    space_id,
                    author,
                    space_name,
                    sdk,
                    status,
                    hardware,
                    hourly_cost,
                    is_callable,
                    private,
                    total_invocations,
                    last_refreshed
                FROM hf_spaces
                ORDER BY author, space_name
            """
            harbor_rows = db.query(harbor_query)

            for row in harbor_rows:
                space_id = row.get('space_id', '')
                status = row.get('status', 'UNKNOWN')

                all_items.append({
                    'id': f"harbor:{space_id}",
                    'name': row.get('space_name', space_id),
                    'category': 'harbor',
                    'type': row.get('sdk', 'unknown'),
                    'description': f"HuggingFace Space by {row.get('author', 'unknown')}",
                    'source': row.get('author', ''),
                    'updated_at': row.get('last_refreshed'),
                    'metadata': {
                        'space_id': space_id,
                        'author': row.get('author'),
                        'sdk': row.get('sdk'),
                        'status': status,
                        'hardware': row.get('hardware'),
                        'hourly_cost': row.get('hourly_cost'),
                        'is_callable': row.get('is_callable'),
                        'private': row.get('private'),
                        'total_invocations': row.get('total_invocations')
                    }
                })

            category_counts['harbor'] = len(harbor_rows)
        except Exception as e:
            print(f"[Catalog] Error fetching harbor spaces: {e}")
            category_counts['harbor'] = 0

        # ==================================
        # 4. SIGNALS from signals table
        # ==================================
        try:
            signals_query = """
                SELECT
                    signal_id,
                    signal_name,
                    status,
                    cascade_id,
                    cell_name,
                    description,
                    source,
                    created_at,
                    fired_at
                FROM signals
                ORDER BY created_at DESC
                LIMIT 200
            """
            signals_rows = db.query(signals_query)

            for row in signals_rows:
                signal_id = row.get('signal_id', '')
                signal_name = row.get('signal_name', '')

                all_items.append({
                    'id': f"signal:{signal_id}",
                    'name': signal_name,
                    'category': 'signals',
                    'type': row.get('status', 'unknown'),
                    'description': row.get('description', ''),
                    'source': row.get('source', ''),
                    'updated_at': row.get('fired_at') or row.get('created_at'),
                    'metadata': {
                        'signal_id': signal_id,
                        'status': row.get('status'),
                        'cascade_id': row.get('cascade_id'),
                        'cell_name': row.get('cell_name'),
                        'created_at': row.get('created_at'),
                        'fired_at': row.get('fired_at')
                    }
                })

            category_counts['signals'] = len(signals_rows)
        except Exception as e:
            print(f"[Catalog] Error fetching signals: {e}")
            category_counts['signals'] = 0

        # ==================================
        # 5. CASCADES from cascade_template_vectors
        # ==================================
        try:
            cascades_query = """
                SELECT
                    cascade_id,
                    cascade_file,
                    description,
                    cell_count,
                    run_count,
                    avg_cost,
                    avg_duration_seconds,
                    success_rate,
                    last_updated
                FROM cascade_template_vectors
                ORDER BY cascade_id
            """
            cascades_rows = db.query(cascades_query)

            for row in cascades_rows:
                cascade_id = row.get('cascade_id', '')

                all_items.append({
                    'id': f"cascade:{cascade_id}",
                    'name': cascade_id,
                    'category': 'cascades',
                    'type': 'workflow',
                    'description': row.get('description', ''),
                    'source': row.get('cascade_file', ''),
                    'updated_at': row.get('last_updated'),
                    'metadata': {
                        'cascade_file': row.get('cascade_file'),
                        'cell_count': row.get('cell_count'),
                        'run_count': row.get('run_count'),
                        'avg_cost': row.get('avg_cost'),
                        'avg_duration_seconds': row.get('avg_duration_seconds'),
                        'success_rate': row.get('success_rate')
                    }
                })

            category_counts['cascades'] = len(cascades_rows)
        except Exception as e:
            print(f"[Catalog] Error fetching cascades: {e}")
            category_counts['cascades'] = 0

        # ==================================
        # 6. MEMORY BANKS from rag_manifests
        # ==================================
        try:
            memory_query = """
                SELECT
                    rag_id,
                    rel_path,
                    chunk_count,
                    file_hash,
                    updated_at
                FROM rag_manifests
                ORDER BY rag_id
            """
            memory_rows = db.query(memory_query)

            # Group by rag_id to get memory bank level
            memory_banks = {}
            for row in memory_rows:
                rag_id = row.get('rag_id', '')
                if rag_id not in memory_banks:
                    memory_banks[rag_id] = {
                        'doc_count': 0,
                        'total_chunks': 0,
                        'last_indexed': None
                    }
                memory_banks[rag_id]['doc_count'] += 1
                memory_banks[rag_id]['total_chunks'] += row.get('chunk_count', 0)
                updated_at = row.get('updated_at')
                if updated_at:
                    if memory_banks[rag_id]['last_indexed'] is None or updated_at > memory_banks[rag_id]['last_indexed']:
                        memory_banks[rag_id]['last_indexed'] = updated_at

            for rag_id, stats in memory_banks.items():
                # Extract memory name from rag_id (format: memory_{name})
                name = rag_id.replace('memory_', '') if rag_id.startswith('memory_') else rag_id

                all_items.append({
                    'id': f"memory:{rag_id}",
                    'name': name,
                    'category': 'memory',
                    'type': 'knowledge_base',
                    'description': f"{stats['doc_count']} documents, {stats['total_chunks']} chunks",
                    'source': rag_id,
                    'updated_at': stats['last_indexed'],
                    'metadata': {
                        'rag_id': rag_id,
                        'doc_count': stats['doc_count'],
                        'total_chunks': stats['total_chunks']
                    }
                })

            category_counts['memory'] = len(memory_banks)
        except Exception as e:
            print(f"[Catalog] Error fetching memory banks: {e}")
            category_counts['memory'] = 0

        # ==================================
        # 7. MCP SERVERS from config file
        # ==================================
        try:
            mcp_count = 0
            config = get_config() if get_config else {}
            mcp_servers_path = os.path.join(os.environ.get('LARS_ROOT', '.'), 'config', 'mcp_servers.yaml')

            if os.path.exists(mcp_servers_path):
                import yaml
                with open(mcp_servers_path, 'r') as f:
                    mcp_servers = yaml.safe_load(f) or []

                for server in mcp_servers:
                    if isinstance(server, dict):
                        name = server.get('name', 'unknown')
                        enabled = server.get('enabled', True)

                        all_items.append({
                            'id': f"mcp:{name}",
                            'name': name,
                            'category': 'mcp',
                            'type': server.get('transport', 'stdio'),
                            'description': f"MCP Server ({server.get('transport', 'stdio')})",
                            'source': server.get('command', server.get('url', '')),
                            'updated_at': None,
                            'metadata': {
                                'transport': server.get('transport'),
                                'command': server.get('command'),
                                'args': server.get('args'),
                                'url': server.get('url'),
                                'enabled': enabled
                            }
                        })
                        mcp_count += 1

            category_counts['mcp'] = mcp_count
        except Exception as e:
            print(f"[Catalog] Error fetching MCP servers: {e}")
            category_counts['mcp'] = 0

        # ==================================
        # 8. SESSIONS (recent) from session_state
        # ==================================
        try:
            sessions_query = """
                SELECT
                    session_id,
                    cascade_id,
                    status,
                    current_cell,
                    blocked_type,
                    blocked_on,
                    started_at,
                    completed_at,
                    error_message
                FROM session_state
                ORDER BY started_at DESC
                LIMIT 100
            """
            sessions_rows = db.query(sessions_query)

            for row in sessions_rows:
                session_id = row.get('session_id', '')
                cascade_id = row.get('cascade_id', '')
                status = row.get('status', 'unknown')

                all_items.append({
                    'id': f"session:{session_id}",
                    'name': session_id,
                    'category': 'sessions',
                    'type': status,
                    'description': f"Cascade: {cascade_id}",
                    'source': cascade_id,
                    'updated_at': row.get('completed_at') or row.get('started_at'),
                    'metadata': {
                        'cascade_id': cascade_id,
                        'status': status,
                        'current_cell': row.get('current_cell'),
                        'blocked_type': row.get('blocked_type'),
                        'blocked_on': row.get('blocked_on'),
                        'started_at': row.get('started_at'),
                        'completed_at': row.get('completed_at'),
                        'error_message': row.get('error_message')
                    }
                })

            category_counts['sessions'] = len(sessions_rows)
        except Exception as e:
            print(f"[Catalog] Error fetching sessions: {e}")
            category_counts['sessions'] = 0

        # ==================================
        # 9. SQL CONNECTIONS from sql_connections/*.json
        # ==================================
        try:
            import yaml
            from pathlib import Path

            sql_connections_count = 0
            sql_tables_count = 0
            cfg = get_config() if get_config else {}
            root_dir = os.environ.get('LARS_ROOT', '.')
            sql_dir = os.path.join(root_dir, 'sql_connections')

            # Load discovery metadata for summary
            discovery_meta = None
            discovery_meta_path = os.path.join(sql_dir, 'discovery_metadata.json')
            if os.path.exists(discovery_meta_path):
                try:
                    with open(discovery_meta_path, 'r') as f:
                        discovery_meta = json.load(f)
                except Exception as e:
                    print(f"[Catalog] Error reading discovery metadata: {e}")

            # Load SQL connection configs
            if os.path.exists(sql_dir):
                for file in Path(sql_dir).glob("*.json"):
                    if file.name == "discovery_metadata.json":
                        continue

                    try:
                        with open(file, 'r') as f:
                            conn_config = json.load(f)

                        conn_name = conn_config.get('connection_name', file.stem)
                        conn_type = conn_config.get('type', 'unknown')
                        enabled = conn_config.get('enabled', True)

                        # Count tables for this connection from samples
                        table_count = 0
                        samples_dir = os.path.join(sql_dir, 'samples', conn_name)
                        if os.path.exists(samples_dir):
                            table_count = len(list(Path(samples_dir).rglob("*.json")))

                        all_items.append({
                            'id': f"sql_connection:{conn_name}",
                            'name': conn_name,
                            'category': 'sql',
                            'type': conn_type,
                            'description': f"{conn_type.upper()} connection to {conn_config.get('database', conn_config.get('folder_path', 'unknown'))}",
                            'source': file.name,
                            'updated_at': discovery_meta.get('last_discovery') if discovery_meta else None,
                            'metadata': {
                                'host': conn_config.get('host'),
                                'port': conn_config.get('port'),
                                'database': conn_config.get('database'),
                                'folder_path': conn_config.get('folder_path'),
                                'enabled': enabled,
                                'table_count': table_count
                            }
                        })
                        sql_connections_count += 1

                    except Exception as e:
                        print(f"[Catalog] Error reading SQL connection {file.name}: {e}")

            # Load discovered SQL tables from samples
            samples_dir = os.path.join(sql_dir, 'samples')
            if os.path.exists(samples_dir):
                for table_file in Path(samples_dir).rglob("*.json"):
                    try:
                        with open(table_file, 'r') as f:
                            table_meta = json.load(f)

                        table_name = table_meta.get('table_name', table_file.stem)
                        schema_name = table_meta.get('schema', '')
                        db_name = table_meta.get('database', '')
                        row_count = table_meta.get('row_count', 0)
                        columns = table_meta.get('columns', [])

                        # Build qualified name
                        if schema_name and schema_name != db_name:
                            qualified_name = f"{db_name}.{schema_name}.{table_name}"
                        else:
                            qualified_name = f"{db_name}.{table_name}"

                        all_items.append({
                            'id': f"sql_table:{qualified_name}",
                            'name': qualified_name,
                            'category': 'sql',
                            'type': 'table',
                            'description': f"{len(columns)} columns, {row_count:,} rows",
                            'source': db_name,
                            'updated_at': discovery_meta.get('last_discovery') if discovery_meta else None,
                            'metadata': {
                                'table_name': table_name,
                                'schema': schema_name,
                                'database': db_name,
                                'row_count': row_count,
                                'column_count': len(columns),
                                'columns': [c.get('name') for c in columns[:20]]  # First 20 column names
                            }
                        })
                        sql_tables_count += 1

                    except Exception as e:
                        print(f"[Catalog] Error reading SQL table {table_file}: {e}")

            category_counts['sql'] = sql_connections_count + sql_tables_count
        except Exception as e:
            print(f"[Catalog] Error fetching SQL connections: {e}")
            category_counts['sql'] = 0

        # ==================================
        # Apply filters
        # ==================================
        filtered_items = all_items

        # Category filter
        if category_filter:
            filtered_items = [i for i in filtered_items if i['category'] == category_filter]

        # Type filter
        if type_filter:
            filtered_items = [i for i in filtered_items if i['type'] == type_filter]

        # Search filter
        if search:
            filtered_items = [
                i for i in filtered_items
                if search in i['name'].lower()
                or search in (i['description'] or '').lower()
                or search in (i['source'] or '').lower()
            ]

        # Get total before pagination
        total = len(filtered_items)

        # Apply pagination
        paginated_items = filtered_items[offset:offset + limit]

        return jsonify(sanitize_for_json({
            'items': paginated_items,
            'total': total,
            'categories': category_counts,
            'offset': offset,
            'limit': limit
        }))

    except Exception as e:
        import traceback
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc(),
            'items': [],
            'total': 0,
            'categories': {}
        }), 500


@catalog_bp.route('/<item_id>', methods=['GET'])
def get_catalog_item(item_id: str):
    """
    Get detailed information about a specific catalog item.

    Args:
        item_id: Format "category:id" (e.g., "tool:linux_shell", "model:openai/gpt-4o")

    Returns:
        Detailed item information based on category.
    """
    try:
        if ':' not in item_id:
            return jsonify({'error': 'Invalid item_id format. Expected category:id'}), 400

        category, raw_id = item_id.split(':', 1)
        db = get_db()

        if category == 'tool':
            # Get tool details including schema
            query = """
                SELECT
                    tool_name,
                    tool_type,
                    tool_description,
                    schema_json,
                    source_path,
                    last_updated
                FROM tool_manifest_vectors
                WHERE tool_name = %(tool_name)s
                LIMIT 1
            """
            rows = db.query(query, {'tool_name': raw_id})
            if not rows:
                return jsonify({'error': 'Tool not found'}), 404

            row = rows[0]
            schema = None
            if row.get('schema_json'):
                try:
                    schema = json.loads(row['schema_json'])
                except:
                    schema = row['schema_json']

            return jsonify(sanitize_for_json({
                'id': item_id,
                'name': row.get('tool_name'),
                'category': 'tools',
                'type': row.get('tool_type'),
                'description': row.get('tool_description'),
                'source': row.get('source_path'),
                'updated_at': row.get('last_updated'),
                'schema': schema
            }))

        elif category == 'local_model':
            # Get local model (HuggingFace transformer) details from skill manifest
            if not get_skill_manifest:
                return jsonify({'error': 'Skill manifest not available'}), 500

            import yaml
            manifest = get_skill_manifest(refresh=False)
            local_tools = {k: v for k, v in manifest.items() if 'local_model' in v.get('type', '')}

            if raw_id not in local_tools:
                return jsonify({'error': 'Local model not found'}), 404

            tool_def = local_tools[raw_id]
            source_path = tool_def.get('path', '')

            # Read from YAML to get full details
            model_id = ''
            task = ''
            device = 'auto'
            inputs_schema = {}

            if source_path and os.path.exists(source_path):
                try:
                    with open(source_path, 'r') as f:
                        yaml_content = yaml.safe_load(f) or {}
                        model_id = yaml_content.get('model_id', '')
                        task = yaml_content.get('task', '')
                        device = yaml_content.get('device', 'auto')
                        inputs_schema = yaml_content.get('inputs_schema', {})
                except Exception as e:
                    print(f"[Catalog] Error reading local model YAML: {e}")

            # Build input schema
            schema = None
            if inputs_schema:
                schema = {
                    'type': 'object',
                    'properties': {
                        k: {'type': 'string', 'description': v}
                        for k, v in inputs_schema.items()
                    }
                }

            return jsonify(sanitize_for_json({
                'id': item_id,
                'name': raw_id,
                'category': 'local_models',
                'type': 'transformer',
                'description': tool_def.get('description', ''),
                'source': source_path,
                'updated_at': None,
                'schema': schema,
                'details': {
                    'model_id': model_id,
                    'task': task,
                    'device': device,
                    'type': tool_def.get('type', ''),
                }
            }))

        elif category == 'model':
            query = """
                SELECT *
                FROM openrouter_models
                WHERE model_id = %(model_id)s
                LIMIT 1
            """
            rows = db.query(query, {'model_id': raw_id})
            if not rows:
                return jsonify({'error': 'Model not found'}), 404

            row = rows[0]
            provider = row.get('provider', '')
            is_local = provider.lower() in ('ollama', 'local')
            return jsonify(sanitize_for_json({
                'id': item_id,
                'name': row.get('model_name', raw_id),
                'category': 'models',
                'type': 'local' if is_local else row.get('tier', 'standard'),
                'description': row.get('description'),
                'details': dict(row)
            }))

        elif category == 'harbor':
            query = """
                SELECT *
                FROM hf_spaces
                WHERE space_id = %(space_id)s
                LIMIT 1
            """
            rows = db.query(query, {'space_id': raw_id})
            if not rows:
                return jsonify({'error': 'HuggingFace Space not found'}), 404

            row = rows[0]
            endpoints = None
            if row.get('endpoints_json'):
                try:
                    endpoints = json.loads(row['endpoints_json'])
                except:
                    endpoints = None

            return jsonify(sanitize_for_json({
                'id': item_id,
                'name': row.get('space_name', raw_id),
                'category': 'harbor',
                'type': row.get('sdk'),
                'description': f"HuggingFace Space by {row.get('author', 'unknown')}",
                'details': dict(row),
                'endpoints': endpoints
            }))

        elif category == 'signal':
            query = """
                SELECT *
                FROM signals
                WHERE signal_id = %(signal_id)s
                LIMIT 1
            """
            rows = db.query(query, {'signal_id': raw_id})
            if not rows:
                return jsonify({'error': 'Signal not found'}), 404

            row = rows[0]
            payload = None
            if row.get('payload_json'):
                try:
                    payload = json.loads(row['payload_json'])
                except:
                    payload = row['payload_json']

            return jsonify(sanitize_for_json({
                'id': item_id,
                'name': row.get('signal_name'),
                'category': 'signals',
                'type': row.get('status'),
                'description': row.get('description'),
                'details': dict(row),
                'payload': payload
            }))

        elif category == 'cascade':
            query = """
                SELECT *
                FROM cascade_template_vectors
                WHERE cascade_id = %(cascade_id)s
                LIMIT 1
            """
            rows = db.query(query, {'cascade_id': raw_id})
            if not rows:
                return jsonify({'error': 'Cascade not found'}), 404

            row = rows[0]

            # Try to load the cascade file for full definition
            cascade_def = None
            cascade_file = row.get('cascade_file')
            if cascade_file and os.path.exists(cascade_file):
                try:
                    from lars.loaders import load_config_file
                    cascade_def = load_config_file(cascade_file)
                except:
                    pass

            return jsonify(sanitize_for_json({
                'id': item_id,
                'name': raw_id,
                'category': 'cascades',
                'type': 'workflow',
                'description': row.get('description'),
                'details': dict(row),
                'definition': cascade_def
            }))

        elif category == 'memory':
            # Get all documents in this memory bank
            query = """
                SELECT
                    rag_id,
                    doc_id,
                    rel_path,
                    chunk_count,
                    file_hash,
                    updated_at
                FROM rag_manifests
                WHERE rag_id = %(rag_id)s
                ORDER BY rel_path
            """
            rows = db.query(query, {'rag_id': raw_id})
            if not rows:
                return jsonify({'error': 'Memory bank not found'}), 404

            documents = [dict(r) for r in rows]
            total_chunks = sum(d.get('chunk_count', 0) for d in documents)

            return jsonify(sanitize_for_json({
                'id': item_id,
                'name': raw_id.replace('memory_', '') if raw_id.startswith('memory_') else raw_id,
                'category': 'memory',
                'type': 'knowledge_base',
                'description': f"{len(documents)} documents, {total_chunks} chunks",
                'documents': documents,
                'total_chunks': total_chunks
            }))

        elif category == 'mcp':
            # Read from config file
            mcp_servers_path = os.path.join(os.environ.get('LARS_ROOT', '.'), 'config', 'mcp_servers.yaml')
            if not os.path.exists(mcp_servers_path):
                return jsonify({'error': 'MCP configuration not found'}), 404

            import yaml
            with open(mcp_servers_path, 'r') as f:
                mcp_servers = yaml.safe_load(f) or []

            for server in mcp_servers:
                if isinstance(server, dict) and server.get('name') == raw_id:
                    return jsonify(sanitize_for_json({
                        'id': item_id,
                        'name': raw_id,
                        'category': 'mcp',
                        'type': server.get('transport', 'stdio'),
                        'description': f"MCP Server ({server.get('transport', 'stdio')})",
                        'config': server
                    }))

            return jsonify({'error': 'MCP server not found'}), 404

        elif category == 'session':
            query = """
                SELECT *
                FROM session_state
                WHERE session_id = %(session_id)s
                LIMIT 1
            """
            rows = db.query(query, {'session_id': raw_id})
            if not rows:
                return jsonify({'error': 'Session not found'}), 404

            row = rows[0]
            metadata = None
            if row.get('metadata_json'):
                try:
                    metadata = json.loads(row['metadata_json'])
                except:
                    metadata = None

            return jsonify(sanitize_for_json({
                'id': item_id,
                'name': raw_id,
                'category': 'sessions',
                'type': row.get('status'),
                'description': f"Cascade: {row.get('cascade_id')}",
                'details': dict(row),
                'metadata': metadata
            }))

        elif category == 'sql_connection':
            # Get SQL connection config from file
            from pathlib import Path

            root_dir = os.environ.get('LARS_ROOT', '.')
            sql_dir = os.path.join(root_dir, 'sql_connections')

            # Find the connection config file
            conn_file = os.path.join(sql_dir, f"{raw_id}.json")
            if not os.path.exists(conn_file):
                # Try to find by connection_name in any json file
                for file in Path(sql_dir).glob("*.json"):
                    if file.name == "discovery_metadata.json":
                        continue
                    try:
                        with open(file, 'r') as f:
                            cfg = json.load(f)
                        if cfg.get('connection_name') == raw_id:
                            conn_file = str(file)
                            break
                    except:
                        pass

            if not os.path.exists(conn_file):
                return jsonify({'error': 'SQL connection not found'}), 404

            with open(conn_file, 'r') as f:
                conn_config = json.load(f)

            # Count tables
            table_count = 0
            samples_dir = os.path.join(sql_dir, 'samples', raw_id)
            if os.path.exists(samples_dir):
                table_count = len(list(Path(samples_dir).rglob("*.json")))

            # Get discovery metadata
            discovery_meta = None
            discovery_meta_path = os.path.join(sql_dir, 'discovery_metadata.json')
            if os.path.exists(discovery_meta_path):
                try:
                    with open(discovery_meta_path, 'r') as f:
                        discovery_meta = json.load(f)
                except:
                    pass

            return jsonify(sanitize_for_json({
                'id': item_id,
                'name': raw_id,
                'category': 'sql',
                'type': conn_config.get('type', 'unknown'),
                'description': f"SQL connection to {conn_config.get('database', conn_config.get('folder_path', 'unknown'))}",
                'config': conn_config,
                'details': {
                    'table_count': table_count,
                    'last_crawl': discovery_meta.get('last_discovery') if discovery_meta else None,
                    'rag_id': discovery_meta.get('rag_id') if discovery_meta else None
                }
            }))

        elif category == 'sql_table':
            # Get SQL table metadata from samples
            from pathlib import Path

            root_dir = os.environ.get('LARS_ROOT', '.')
            samples_dir = os.path.join(root_dir, 'sql_connections', 'samples')

            # Parse qualified name: db.schema.table or db.table
            parts = raw_id.split('.')
            if len(parts) == 3:
                db_name, schema_name, table_name = parts
            elif len(parts) == 2:
                db_name, table_name = parts
                schema_name = None
            else:
                return jsonify({'error': 'Invalid table name format'}), 400

            # Find the table file
            table_file = None
            if schema_name:
                table_file = os.path.join(samples_dir, db_name, schema_name, f"{table_name}.json")
            if not table_file or not os.path.exists(table_file):
                table_file = os.path.join(samples_dir, db_name, f"{table_name}.json")
            if not os.path.exists(table_file):
                # Search for it
                for tf in Path(samples_dir).rglob(f"{table_name}.json"):
                    table_file = str(tf)
                    break

            if not table_file or not os.path.exists(table_file):
                return jsonify({'error': 'SQL table not found'}), 404

            with open(table_file, 'r') as f:
                table_meta = json.load(f)

            return jsonify(sanitize_for_json({
                'id': item_id,
                'name': raw_id,
                'category': 'sql',
                'type': 'table',
                'description': f"{len(table_meta.get('columns', []))} columns, {table_meta.get('row_count', 0):,} rows",
                'details': {
                    'table_name': table_meta.get('table_name'),
                    'schema': table_meta.get('schema'),
                    'database': table_meta.get('database'),
                    'row_count': table_meta.get('row_count', 0)
                },
                'columns': table_meta.get('columns', []),
                'sample_data': table_meta.get('sample_data', [])
            }))

        else:
            return jsonify({'error': f'Unknown category: {category}'}), 400

    except Exception as e:
        import traceback
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


@catalog_bp.route('/stats', methods=['GET'])
def get_catalog_stats():
    """
    Get aggregate statistics for the catalog.

    Returns:
        {
            "total_items": count,
            "by_category": { category: count, ... },
            "by_type": { type: count, ... }
        }
    """
    try:
        db = get_db()
        stats = {
            'total_items': 0,
            'by_category': {},
            'by_type': {}
        }

        # Tools count by type
        try:
            tools_query = """
                SELECT tool_type, COUNT(DISTINCT tool_name) as cnt
                FROM tool_manifest_vectors
                GROUP BY tool_type
            """
            tools_rows = db.query(tools_query)
            tools_total = 0
            for row in tools_rows:
                cnt = row.get('cnt', 0)
                stats['by_type'][f"tool:{row.get('tool_type', 'unknown')}"] = cnt
                tools_total += cnt
            stats['by_category']['tools'] = tools_total
            stats['total_items'] += tools_total
        except Exception as e:
            print(f"[Catalog Stats] Error counting tools: {e}")

        # Models count
        try:
            models_query = "SELECT COUNT(*) as cnt FROM openrouter_models WHERE is_active = 1"
            models_rows = db.query(models_query)
            cnt = models_rows[0].get('cnt', 0) if models_rows else 0
            stats['by_category']['models'] = cnt
            stats['total_items'] += cnt
        except Exception as e:
            print(f"[Catalog Stats] Error counting models: {e}")

        # Harbor spaces count
        try:
            harbor_query = "SELECT COUNT(*) as cnt FROM hf_spaces"
            harbor_rows = db.query(harbor_query)
            cnt = harbor_rows[0].get('cnt', 0) if harbor_rows else 0
            stats['by_category']['harbor'] = cnt
            stats['total_items'] += cnt
        except Exception as e:
            print(f"[Catalog Stats] Error counting harbor spaces: {e}")

        # Cascades count
        try:
            cascades_query = "SELECT COUNT(*) as cnt FROM cascade_template_vectors"
            cascades_rows = db.query(cascades_query)
            cnt = cascades_rows[0].get('cnt', 0) if cascades_rows else 0
            stats['by_category']['cascades'] = cnt
            stats['total_items'] += cnt
        except Exception as e:
            print(f"[Catalog Stats] Error counting cascades: {e}")

        # Memory banks count
        try:
            memory_query = "SELECT COUNT(DISTINCT rag_id) as cnt FROM rag_manifests"
            memory_rows = db.query(memory_query)
            cnt = memory_rows[0].get('cnt', 0) if memory_rows else 0
            stats['by_category']['memory'] = cnt
            stats['total_items'] += cnt
        except Exception as e:
            print(f"[Catalog Stats] Error counting memory banks: {e}")

        # Signals count
        try:
            signals_query = "SELECT COUNT(*) as cnt FROM signals"
            signals_rows = db.query(signals_query)
            cnt = signals_rows[0].get('cnt', 0) if signals_rows else 0
            stats['by_category']['signals'] = cnt
            stats['total_items'] += cnt
        except Exception as e:
            print(f"[Catalog Stats] Error counting signals: {e}")

        return jsonify(sanitize_for_json(stats))

    except Exception as e:
        import traceback
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500
