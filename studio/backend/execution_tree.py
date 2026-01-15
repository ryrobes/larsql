"""
Execution Tree Builder - Constructs a structured representation of cascade execution
including takes, reforges, retries, and nested cascades.

Uses similar semantics as visualizer.py - builds hierarchy from trace_id/parent_id
relationships and collects all messages with content previews.
"""
import duckdb
import glob
import json
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime


def sanitize_label(content: Any, max_length: int = 50) -> str:
    """Sanitize content for labels - matches visualizer.py behavior."""
    if isinstance(content, (list, dict)):
        try:
            if isinstance(content, list):
                return f"[{len(content)} items]"
            return f"{{{len(content)} keys}}"
        except:
            pass

    s = str(content)
    # Remove newlines and collapse whitespace
    s = ' '.join(s.split())
    # Truncate
    if len(s) > max_length:
        s = s[:max_length] + "..."
    return s


def extract_metadata(metadata_str: Optional[str]) -> Dict:
    """Extract and parse metadata from JSON string."""
    if not metadata_str:
        return {}
    try:
        meta = json.loads(metadata_str) if isinstance(metadata_str, str) else metadata_str
    except:
        meta = {}
    return {
        'take_index': meta.get('take_index'),
        'is_winner': meta.get('is_winner'),
        'reforge_step': meta.get('reforge_step'),
        'cell_name': meta.get('cell_name'),
        'cascade_id': meta.get('cascade_id'),
        'factor': meta.get('factor'),
        'has_takes': meta.get('has_takes'),
        'has_wards': meta.get('has_wards'),
        'handoffs': meta.get('handoffs', []),
        'winner_index': meta.get('winner_index'),
        'depth': meta.get('depth', 0),
        'ward_type': meta.get('ward_type'),
        'validator': meta.get('validator'),
        'mode': meta.get('mode'),
        'valid': meta.get('valid'),
        'reason': meta.get('reason'),
        'turn_number': meta.get('turn_number'),
        'max_turns': meta.get('max_turns'),
        'node_type': meta.get('node_type'),
        # Cascade takes specific
        'sub_session_id': meta.get('sub_session_id'),
        'winner_session_id': meta.get('winner_session_id'),
        'evaluation': meta.get('evaluation'),
        'selected_skills': meta.get('selected_skills', []),
        'reasoning': meta.get('reasoning'),
    }


@dataclass
class ExecutionNode:
    """Represents a single execution unit (cell attempt, take, etc.)"""
    node_id: str
    node_type: str  # 'cascade', 'cell', 'turn', 'message', 'take', 'reforge', 'sub_cascade'
    name: str  # Display name or content preview
    session_id: str
    parent_id: Optional[str] = None
    content: str = ""  # Full content for messages
    role: str = ""  # Message role (system, user, assistant, tool)

    # Sounding metadata
    take_index: Optional[int] = None
    is_winner: Optional[bool] = None

    # Reforge metadata
    reforge_step: Optional[int] = None

    # Timing
    timestamp: Optional[float] = None

    # Children for nesting
    children: List['ExecutionNode'] = field(default_factory=list)

    # Raw metadata
    metadata: Dict = field(default_factory=dict)

    def to_dict(self):
        """Convert to dict for JSON serialization"""
        return {
            'id': self.node_id,
            'type': self.node_type,
            'name': self.name,
            'session_id': self.session_id,
            'parent_id': self.parent_id,
            'content': self.content,
            'role': self.role,
            'take_index': self.take_index,
            'is_winner': self.is_winner,
            'reforge_step': self.reforge_step,
            'timestamp': self.timestamp,
            'children': [c.to_dict() for c in self.children],
            'child_count': len(self.children),
            'metadata': self.metadata
        }


class ExecutionTreeBuilder:
    """
    Builds execution trees from parquet logs.

    Uses similar semantics as visualizer.py - builds hierarchy from trace_id/parent_id
    relationships and collects all messages with content previews.
    """

    def __init__(self, log_dir: str):
        self.log_dir = log_dir
        self.conn = None

    def _get_connection(self):
        """Create DuckDB connection with all parquet files"""
        if self.conn:
            return self.conn

        self.conn = duckdb.connect(database=':memory:')
        parquet_files = glob.glob(f"{self.log_dir}/**/*.parquet", recursive=True)

        if parquet_files:
            files_str = "', '".join(parquet_files)
            self.conn.execute(f"CREATE VIEW logs AS SELECT * FROM read_parquet(['{files_str}'])")

        return self.conn

    def _build_nodes_map(self, events: List[Tuple]) -> Dict[str, ExecutionNode]:
        """Build a map of all nodes from events."""
        nodes_map: Dict[str, ExecutionNode] = {}

        for row in events:
            timestamp, trace_id, parent_id, role, content, metadata_str, session_id = row

            if not trace_id or trace_id in nodes_map:
                continue

            meta = extract_metadata(metadata_str)
            node_type = meta.get('node_type') or role or 'msg'

            # Determine display name based on type
            if node_type == 'cascade':
                name = content.replace("Cascade: ", "") if content and content.startswith("Cascade: ") else content or "Cascade"
            elif node_type == 'cell':
                name = content.replace("Cell: ", "") if content and content.startswith("Cell: ") else content or "Cell"
            elif node_type == 'turn':
                name = f"Turn {meta.get('turn_number', '?')}"
            elif node_type in ('system', 'user', 'turn_input', 'turn_output', 'tool_result', 'injection', 'follow_up'):
                name = sanitize_label(content, 40) if content else node_type
            else:
                name = sanitize_label(content, 40) if content else node_type

            node = ExecutionNode(
                node_id=trace_id,
                node_type=node_type,
                name=name,
                session_id=session_id,
                parent_id=parent_id,
                content=content or "",
                role=role or "",
                take_index=meta.get('take_index'),
                is_winner=meta.get('is_winner'),
                reforge_step=meta.get('reforge_step'),
                timestamp=timestamp,
                metadata=meta
            )
            nodes_map[trace_id] = node

        return nodes_map

    def _build_hierarchy(self, nodes_map: Dict[str, ExecutionNode]) -> List[ExecutionNode]:
        """Build parent-child relationships and return root nodes."""
        root_nodes = []

        for node in nodes_map.values():
            if node.parent_id and node.parent_id in nodes_map:
                nodes_map[node.parent_id].children.append(node)
            else:
                root_nodes.append(node)

        # Sort children by timestamp
        for node in nodes_map.values():
            node.children.sort(key=lambda n: n.timestamp or 0)

        return root_nodes

    def build_tree(self, session_id: str) -> Dict:
        """
        Build complete execution tree for a session.

        Uses similar semantics as visualizer.py:
        - Builds hierarchy from trace_id/parent_id relationships
        - Collects cascades, cells, turns, and all messages
        - Shows content previews for all message types
        - Properly groups messages under their cells

        Returns a hierarchical structure with cells containing their messages.
        """
        conn = self._get_connection()

        # Get all events for this session with trace hierarchy
        query = """
            SELECT
                timestamp,
                trace_id,
                parent_id,
                role,
                content,
                metadata,
                session_id
            FROM logs
            WHERE session_id = ?
            ORDER BY timestamp ASC
        """

        try:
            events = conn.execute(query, [session_id]).fetchall()
        except Exception as e:
            return {'error': f'Query failed: {str(e)}', 'session_id': session_id}

        if not events:
            return {'error': 'No events found for session', 'session_id': session_id}

        # Build nodes map and hierarchy
        nodes_map = self._build_nodes_map(events)
        root_nodes = self._build_hierarchy(nodes_map)

        # Find cascade and cells
        cascade_node = None
        for node in root_nodes:
            if node.node_type == 'cascade':
                cascade_node = node
                break

        # Build structured tree response
        tree = {
            'session_id': session_id,
            'cascade': None,
            'cells': [],
            'sub_cascades': []
        }

        if cascade_node:
            tree['cascade'] = {
                'id': cascade_node.node_id,
                'name': cascade_node.name,
                'child_count': len(cascade_node.children)
            }

        # Collect cells with their messages
        cell_nodes = [n for n in nodes_map.values() if n.node_type == 'cell']
        cell_nodes.sort(key=lambda n: n.timestamp or 0)

        for cell_node in cell_nodes:
            cell_data = self._build_cell_data(cell_node, nodes_map)
            tree['cells'].append(cell_data)

        return tree

    def _build_cell_data(self, cell_node: ExecutionNode, nodes_map: Dict[str, ExecutionNode]) -> Dict:
        """Build structured data for a cell including all its messages and sub-cascades."""
        # Collect all turn traces under this cell
        turn_traces = set()
        for child in cell_node.children:
            if child.node_type == 'turn':
                turn_traces.add(child.node_id)

        # Collect tool traces under turn traces
        tool_traces = set()
        for turn_id in turn_traces:
            turn_node = nodes_map.get(turn_id)
            if turn_node:
                for child in turn_node.children:
                    if child.node_type == 'tool':
                        tool_traces.add(child.node_id)

        # Collect messages belonging to this cell
        messages = []

        # Direct children of cell (system, user, injection, validation, validation_retry)
        for child in cell_node.children:
            if child.node_type in ('system', 'user', 'injection', 'validation', 'schema_validation', 'validation_retry'):
                messages.append(self._build_message_data(child))

        # Children of turn traces (turn_output, turn_input, follow_up)
        for turn_id in turn_traces:
            turn_node = nodes_map.get(turn_id)
            if turn_node:
                for child in turn_node.children:
                    if child.node_type == 'turn_output':
                        # Skip empty turn_output (tool call without text response)
                        if child.content and child.content.strip():
                            messages.append(self._build_message_data(child))
                    elif child.node_type in ('turn_input', 'follow_up'):
                        messages.append(self._build_message_data(child))
                    elif child.node_type == 'tool':
                        # Check for tool_result under tool trace
                        for grandchild in child.children:
                            if grandchild.node_type == 'tool_result':
                                messages.append(self._build_message_data(grandchild))
                            elif grandchild.node_type == 'injection':
                                messages.append(self._build_message_data(grandchild))

        # Sort messages by timestamp
        messages.sort(key=lambda m: m.get('timestamp') or 0)

        # Check for sub-cascades (cascade nodes that are children of this cell)
        sub_cascades = []
        for child in cell_node.children:
            if child.node_type == 'cascade':
                sub_cascade_data = self._build_sub_cascade_data(child, nodes_map)
                sub_cascades.append(sub_cascade_data)

        # Also check for sub-cascades via sub_cascade node type
        for child in cell_node.children:
            if child.node_type == 'sub_cascade':
                # Find the actual cascade node under this
                for grandchild in child.children:
                    if grandchild.node_type == 'cascade':
                        sub_cascade_data = self._build_sub_cascade_data(grandchild, nodes_map)
                        sub_cascades.append(sub_cascade_data)

        # Check for takes
        takes = []
        take_attempts = [n for n in nodes_map.values()
                           if n.node_type == 'take_attempt'
                           and n.metadata.get('cell_name') == cell_node.name]

        if take_attempts:
            for attempt in take_attempts:
                takes.append({
                    'index': attempt.take_index,
                    'is_winner': attempt.is_winner,
                    'content': attempt.content,
                    'preview': sanitize_label(attempt.content, 25) if attempt.content else ''
                })
            takes.sort(key=lambda s: s.get('index') or 0)

        # Check for evaluator entry for takes
        evaluator_content = ""
        evaluator_entries = [n for n in nodes_map.values()
                           if n.node_type in ('evaluator', 'evaluation')
                           and n.metadata.get('cell_name') == cell_node.name]
        if evaluator_entries:
            evaluator_content = evaluator_entries[0].content or ""

        # Check for quartermaster entry (manifest tool selection)
        quartermaster_entry = None
        qm_entries = [n for n in nodes_map.values()
                     if n.node_type == 'quartermaster_result'
                     and n.metadata.get('cell_name') == cell_node.name]
        if qm_entries:
            quartermaster_entry = {
                'content': qm_entries[0].content or "",
                'selected_skills': qm_entries[0].metadata.get('selected_skills', []),
                'reasoning': qm_entries[0].metadata.get('reasoning', '')
            }

        # Check for wards
        wards = {'pre': [], 'post': []}
        for child in cell_node.children:
            if child.node_type == 'pre_ward':
                wards['pre'].append({
                    'validator': child.metadata.get('validator', 'validator'),
                    'mode': child.metadata.get('mode', 'blocking'),
                    'valid': child.metadata.get('valid', True),
                    'reason': child.metadata.get('reason', '')
                })
            elif child.node_type == 'post_ward':
                wards['post'].append({
                    'validator': child.metadata.get('validator', 'validator'),
                    'mode': child.metadata.get('mode', 'blocking'),
                    'valid': child.metadata.get('valid', True),
                    'reason': child.metadata.get('reason', '')
                })

        # Determine cell type
        cell_type = 'simple'
        if takes:
            cell_type = 'takes'
        elif cell_node.metadata.get('has_takes'):
            cell_type = 'takes'
        elif wards['pre'] or wards['post']:
            cell_type = 'wards'
        elif sub_cascades:
            cell_type = 'sub_cascade'

        # Check for winner
        winner_index = None
        for s in takes:
            if s.get('is_winner'):
                winner_index = s.get('index')
                break

        return {
            'name': cell_node.name,
            'id': cell_node.node_id,
            'type': cell_type,
            'messages': messages,
            'message_count': len(messages),
            'takes': takes if takes else None,
            'winner_index': winner_index,
            'evaluator_content': evaluator_content if takes else None,
            'quartermaster': quartermaster_entry,
            'wards': wards if (wards['pre'] or wards['post']) else None,
            'sub_cascades': sub_cascades if sub_cascades else None,
            'handoffs': cell_node.metadata.get('handoffs', []),
            'timestamp': cell_node.timestamp
        }

    def _build_sub_cascade_data(self, cascade_node: ExecutionNode, nodes_map: Dict[str, ExecutionNode]) -> Dict:
        """Build structured data for a sub-cascade including all its cells."""
        # Find all cells under this cascade
        sub_cells = []
        for child in cascade_node.children:
            if child.node_type == 'cell':
                cell_data = self._build_cell_data(child, nodes_map)
                sub_cells.append(cell_data)

        # Sort by timestamp
        sub_cells.sort(key=lambda p: p.get('timestamp') or 0)

        return {
            'id': cascade_node.node_id,
            'name': cascade_node.name,
            'cells': sub_cells,
            'cell_count': len(sub_cells),
            'timestamp': cascade_node.timestamp
        }

    def _build_message_data(self, node: ExecutionNode) -> Dict:
        """Build structured data for a message node with icon and preview."""
        node_type = node.node_type
        role = node.role
        content = node.content

        # Determine icon and label based on type (matching visualizer.py)
        if node_type == 'system' or role == 'system':
            icon = 'SYS'
            style = 'system'
            preview = sanitize_label(content, 30)
            label = f"{icon}: {preview}" if preview else icon
        elif node_type in ('user', 'turn_input') or role == 'user':
            icon = 'USE'
            style = 'user'
            preview = sanitize_label(content, 30)
            label = f"{icon}: {preview}" if preview else icon
        elif node_type in ('turn_output', 'follow_up') or role == 'assistant':
            icon = '💬'
            style = 'agent'
            preview = sanitize_label(content, 35)
            label = f"{icon} {preview}"
        elif node_type == 'tool_result':
            icon = '🔧'
            style = 'tool'
            preview = sanitize_label(content, 25)
            label = f"{icon} {preview}" if preview else f"{icon} Tool"
        elif node_type == 'injection':
            icon = '⚡'
            style = 'user'
            preview = sanitize_label(content, 25)
            label = f"{icon} {preview}" if preview else f"{icon} Inject"
        elif node_type in ('validation', 'schema_validation'):
            # Validation result
            is_valid = node.metadata.get('valid', False)
            icon = '✓' if is_valid else '✗'
            style = 'validation_pass' if is_valid else 'validation_fail'
            preview = sanitize_label(content, 30)
            label = f"🛡️ {preview}"
        elif node_type == 'validation_retry':
            icon = '🔄'
            style = 'user'
            preview = sanitize_label(content, 30)
            label = f"{icon} Retry: {preview}" if preview else f"{icon} Retry"
        else:
            icon = '•'
            style = 'default'
            label = f"{icon} {node_type}"

        return {
            'id': node.node_id,
            'type': node_type,
            'role': role,
            'icon': icon,
            'style': style,
            'label': label,
            'content': content,
            'preview': sanitize_label(content, 50),
            'timestamp': node.timestamp,
            'parent_id': node.parent_id
        }


def build_react_flow_nodes(tree: Dict) -> Dict:
    """
    Convert execution tree to react-flow compatible node/edge structure.

    Uses similar semantics as visualizer.py:
    - Cascade as outer container
    - Cells as subgraphs containing message nodes
    - Messages connected sequentially (SYS → USE → 💬 → ...)
    - Takes with parallel attempts and winner highlighting
    - Wards as checkpoints

    Returns:
    {
        'nodes': [
            {
                'id': 'cell_0',
                'type': 'cellGroup',
                'position': {'x': 0, 'y': 0},
                'data': {'label': 'Cell 1', 'messages': [...]}
            },
            {
                'id': 'cell_0_msg_0',
                'type': 'messageNode',
                'parentNode': 'cell_0',
                'data': {'label': 'SYS: ...', 'style': 'system'}
            },
            ...
        ],
        'edges': [
            {'id': 'e_msg_0_1', 'source': 'cell_0_msg_0', 'target': 'cell_0_msg_1'},
            ...
        ]
    }
    """
    nodes = []
    edges = []

    # Check for errors
    if 'error' in tree:
        return {'nodes': [], 'edges': [], 'error': tree['error']}

    cells = tree.get('cells', [])
    if not cells:
        return {'nodes': [], 'edges': [], 'error': 'No cells found'}

    # Layout constants
    x_spacing = 400  # Horizontal spacing between cells
    y_spacing = 60   # Vertical spacing between messages
    msg_height = 40  # Height of each message node

    cell_ids = []
    prev_cell_last_node = None

    for cell_idx, cell in enumerate(cells):
        cell_id = f"cell_{cell_idx}"
        cell_ids.append(cell_id)
        x_offset = cell_idx * x_spacing

        cell_type = cell.get('type', 'simple')
        messages = cell.get('messages', [])
        takes = cell.get('takes') or []
        wards = cell.get('wards')

        if cell_type == 'takes' and takes:
            # === TAKES CELL ===
            # Create group node for takes
            group_id = f"{cell_id}_takes_group"
            nodes.append({
                'id': group_id,
                'type': 'takesGroup',
                'position': {'x': x_offset, 'y': 0},
                'data': {
                    'label': f"🔱 {cell['name']}",
                    'cell_name': cell['name'],
                    'take_count': len(takes),
                    'winner_index': cell.get('winner_index'),
                    'type': 'takes'
                },
                'style': {'backgroundColor': '#fff3bf', 'border': '2px solid #fab005'}
            })

            # Create individual take attempt nodes
            attempt_ids = []
            for take in takes:
                idx = take.get('index', 0)
                is_winner = take.get('is_winner', False)
                content_preview = take.get('preview', '')
                take_id = f"{cell_id}_take_{idx}"
                attempt_ids.append(take_id)
                y_pos = idx * y_spacing

                # Build label with content preview
                if is_winner:
                    label = f"#{idx + 1} ✓"
                    if content_preview:
                        label = f"#{idx + 1} ✓: {content_preview}"
                else:
                    label = f"#{idx + 1}"
                    if content_preview:
                        label = f"#{idx + 1}: {content_preview}"

                nodes.append({
                    'id': take_id,
                    'type': 'takeNode',
                    'position': {'x': 20, 'y': 40 + y_pos},
                    'parentNode': group_id,
                    'extent': 'parent',
                    'data': {
                        'label': label,
                        'index': idx,
                        'is_winner': is_winner,
                        'content': take.get('content', ''),
                        'preview': content_preview
                    },
                    'style': {
                        'backgroundColor': '#d3f9d8' if is_winner else '#f1f3f5',
                        'border': '3px solid #37b24d' if is_winner else '2px dashed #adb5bd'
                    }
                })

            # Add evaluator node with content preview
            eval_id = f"{cell_id}_evaluator"
            eval_y = len(takes) * y_spacing + 60
            evaluator_content = cell.get('evaluator_content', '')
            if evaluator_content:
                eval_preview = sanitize_label(evaluator_content, 35)
                eval_label = f"⚖️ {eval_preview}"
            else:
                eval_label = '⚖️ Evaluate'
            nodes.append({
                'id': eval_id,
                'type': 'evaluatorNode',
                'position': {'x': 20, 'y': eval_y},
                'parentNode': group_id,
                'extent': 'parent',
                'data': {
                    'label': eval_label,
                    'content': evaluator_content
                },
                'style': {'backgroundColor': '#f3f0ff', 'border': '2px solid #7950f2'}
            })

            # Connect attempts to evaluator
            for aid in attempt_ids:
                edges.append({
                    'id': f"e_{aid}_to_eval",
                    'source': aid,
                    'target': eval_id
                })

            # Add winner output node if there's a winner
            winner_index = cell.get('winner_index')
            if winner_index is not None:
                winner_id = f"{cell_id}_winner"
                # Find the winner's content
                winner_content = ""
                for s in takes:
                    if s.get('index') == winner_index:
                        winner_content = s.get('content', '')
                        break
                winner_preview = sanitize_label(winner_content, 30) if winner_content else ""
                winner_label = f"🏆 #{winner_index + 1}: {winner_preview}" if winner_preview else f"🏆 Winner #{winner_index + 1}"
                nodes.append({
                    'id': winner_id,
                    'type': 'winnerNode',
                    'position': {'x': 20, 'y': eval_y + 60},
                    'parentNode': group_id,
                    'extent': 'parent',
                    'data': {
                        'label': winner_label,
                        'content': winner_content
                    },
                    'style': {'backgroundColor': '#d3f9d8', 'border': '3px solid #37b24d'}
                })
                edges.append({
                    'id': f"e_eval_to_winner",
                    'source': eval_id,
                    'target': winner_id,
                    'animated': True,
                    'style': {'stroke': '#37b24d', 'strokeWidth': 3}
                })
                prev_cell_last_node = winner_id
            else:
                prev_cell_last_node = eval_id

        elif wards and (wards.get('pre') or wards.get('post')):
            # === WARDS CELL ===
            group_id = f"{cell_id}_wards_group"
            nodes.append({
                'id': group_id,
                'type': 'wardsGroup',
                'position': {'x': x_offset, 'y': 0},
                'data': {
                    'label': f"🛡️ {cell['name']}",
                    'cell_name': cell['name'],
                    'type': 'wards'
                },
                'style': {'backgroundColor': '#e3fafc', 'border': '2px solid #15aabf'}
            })

            y_pos = 40
            internal_ids = []

            # Pre-wards
            for j, ward in enumerate(wards.get('pre', [])):
                ward_id = f"{cell_id}_pre_ward_{j}"
                internal_ids.append(ward_id)

                validator = ward.get('validator', 'validator')
                valid = ward.get('valid', True)
                mode = ward.get('mode', 'blocking')

                mode_icon = "🛡️" if mode == "blocking" else ("🔄" if mode == "retry" else "ℹ️")
                status_icon = "✓" if valid else "✗"
                label = f"{mode_icon} {validator} {status_icon}"

                nodes.append({
                    'id': ward_id,
                    'type': 'wardNode',
                    'position': {'x': 20, 'y': y_pos},
                    'parentNode': group_id,
                    'extent': 'parent',
                    'data': {'label': label, 'valid': valid, 'mode': mode},
                    'style': {
                        'backgroundColor': '#e3fafc' if valid else '#ffe3e3',
                        'border': '2px solid #15aabf' if valid else '3px solid #fa5252'
                    }
                })
                y_pos += y_spacing

            # Main execution node
            exec_id = f"{cell_id}_exec"
            internal_ids.append(exec_id)
            nodes.append({
                'id': exec_id,
                'type': 'cellExecNode',
                'position': {'x': 20, 'y': y_pos},
                'parentNode': group_id,
                'extent': 'parent',
                'data': {'label': cell['name']},
                'style': {'backgroundColor': '#e7f5ff', 'border': '2px solid #1c7ed6'}
            })
            y_pos += y_spacing

            # Post-wards
            for j, ward in enumerate(wards.get('post', [])):
                ward_id = f"{cell_id}_post_ward_{j}"
                internal_ids.append(ward_id)

                validator = ward.get('validator', 'validator')
                valid = ward.get('valid', True)
                mode = ward.get('mode', 'blocking')

                mode_icon = "🛡️" if mode == "blocking" else ("🔄" if mode == "retry" else "ℹ️")
                status_icon = "✓" if valid else "✗"
                label = f"{mode_icon} {validator} {status_icon}"

                nodes.append({
                    'id': ward_id,
                    'type': 'wardNode',
                    'position': {'x': 20, 'y': y_pos},
                    'parentNode': group_id,
                    'extent': 'parent',
                    'data': {'label': label, 'valid': valid, 'mode': mode},
                    'style': {
                        'backgroundColor': '#fff5f5' if valid else '#ffe3e3',
                        'border': '2px solid #fa5252' if valid else '3px solid #fa5252'
                    }
                })
                y_pos += y_spacing

            # Connect internal nodes sequentially
            for k in range(len(internal_ids) - 1):
                edges.append({
                    'id': f"e_{internal_ids[k]}_to_{internal_ids[k+1]}",
                    'source': internal_ids[k],
                    'target': internal_ids[k + 1]
                })

            prev_cell_last_node = internal_ids[-1] if internal_ids else group_id

        elif cell_type == 'sub_cascade' and cell.get('sub_cascades'):
            # === CELL WITH SUB-CASCADE ===
            # Render the cell with nested sub-cascade(s)
            sub_cascades = cell.get('sub_cascades', [])

            # Calculate total height needed
            total_sub_height = 0
            for sc in sub_cascades:
                sc_cells = sc.get('cells', [])
                for sp in sc_cells:
                    sp_msgs = sp.get('messages', [])
                    total_sub_height += max(100, len(sp_msgs) * y_spacing + 60)

            # Add space for cell messages too
            cell_msgs_height = len(messages) * y_spacing if messages else 0
            group_height = max(200, cell_msgs_height + total_sub_height + 120)

            group_id = f"{cell_id}_group"
            nodes.append({
                'id': group_id,
                'type': 'subCascadeCellGroup',
                'position': {'x': x_offset, 'y': 0},
                'data': {
                    'label': cell['name'],
                    'cell_name': cell['name'],
                    'message_count': len(messages),
                    'sub_cascade_count': len(sub_cascades),
                    'type': 'sub_cascade'
                },
                'style': {
                    'backgroundColor': '#e7f5ff',
                    'border': '2px solid #1c7ed6',
                    'width': 320,
                    'height': group_height
                }
            })

            y_pos = 40
            all_node_ids = []

            # Render cell messages first (before sub-cascade)
            for j, msg in enumerate(messages):
                msg_id = f"{cell_id}_msg_{j}"
                all_node_ids.append(msg_id)

                style = msg.get('style', 'default')
                bg_colors = {
                    'system': '#e1f5fe',
                    'user': '#fff9c4',
                    'agent': '#d3f9d8',
                    'tool': '#ffccbc',
                    'default': '#f8f9fa'
                }
                border_colors = {
                    'system': '#0288d1',
                    'user': '#f9a825',
                    'agent': '#40c057',
                    'tool': '#e64a19',
                    'default': '#343a40'
                }

                nodes.append({
                    'id': msg_id,
                    'type': 'messageNode',
                    'position': {'x': 20, 'y': y_pos},
                    'parentNode': group_id,
                    'extent': 'parent',
                    'data': {
                        'label': msg.get('label', ''),
                        'icon': msg.get('icon', ''),
                        'style': style,
                        'preview': msg.get('preview', ''),
                        'content': msg.get('content', ''),
                        'type': msg.get('type', '')
                    },
                    'style': {
                        'backgroundColor': bg_colors.get(style, bg_colors['default']),
                        'border': f"2px solid {border_colors.get(style, border_colors['default'])}",
                        'width': 260
                    }
                })
                y_pos += y_spacing

            # Render each sub-cascade as a nested container
            for sc_idx, sub_cascade in enumerate(sub_cascades):
                sc_id = f"{cell_id}_subcascade_{sc_idx}"
                sc_cells = sub_cascade.get('cells', [])

                # Calculate sub-cascade height
                sc_height = 60  # Header
                for sp in sc_cells:
                    sp_msgs = sp.get('messages', [])
                    sc_height += max(80, len(sp_msgs) * y_spacing + 50)

                # Sub-cascade container (nested inside cell)
                nodes.append({
                    'id': sc_id,
                    'type': 'subCascadeGroup',
                    'position': {'x': 10, 'y': y_pos},
                    'parentNode': group_id,
                    'extent': 'parent',
                    'data': {
                        'label': f"📦 {sub_cascade.get('name', 'Sub-Cascade')}",
                        'cascade_name': sub_cascade.get('name', ''),
                        'cell_count': len(sc_cells)
                    },
                    'style': {
                        'backgroundColor': '#f8f0fc',
                        'border': '2px solid #be4bdb',
                        'width': 290,
                        'height': sc_height,
                        'borderRadius': '8px'
                    }
                })
                all_node_ids.append(sc_id)

                # Render sub-cascade cells inside the sub-cascade container
                sc_y_pos = 40
                sc_cell_ids = []
                for sp_idx, sub_cell in enumerate(sc_cells):
                    sp_id = f"{sc_id}_cell_{sp_idx}"
                    sc_cell_ids.append(sp_id)
                    sp_msgs = sub_cell.get('messages', [])
                    sp_height = max(60, len(sp_msgs) * (y_spacing - 10) + 40)

                    # Sub-cell container
                    nodes.append({
                        'id': sp_id,
                        'type': 'nestedCellGroup',
                        'position': {'x': 10, 'y': sc_y_pos},
                        'parentNode': sc_id,
                        'extent': 'parent',
                        'data': {
                            'label': sub_cell.get('name', ''),
                            'message_count': len(sp_msgs)
                        },
                        'style': {
                            'backgroundColor': '#e7f5ff',
                            'border': '2px solid #1c7ed6',
                            'width': 260,
                            'height': sp_height
                        }
                    })

                    # Render messages inside sub-cell
                    sp_msg_y = 30
                    sp_msg_ids = []
                    for m_idx, sp_msg in enumerate(sp_msgs):
                        sp_msg_id = f"{sp_id}_msg_{m_idx}"
                        sp_msg_ids.append(sp_msg_id)

                        style = sp_msg.get('style', 'default')
                        bg_colors = {
                            'system': '#e1f5fe',
                            'user': '#fff9c4',
                            'agent': '#d3f9d8',
                            'tool': '#ffccbc',
                            'default': '#f8f9fa'
                        }
                        border_colors = {
                            'system': '#0288d1',
                            'user': '#f9a825',
                            'agent': '#40c057',
                            'tool': '#e64a19',
                            'default': '#343a40'
                        }

                        nodes.append({
                            'id': sp_msg_id,
                            'type': 'messageNode',
                            'position': {'x': 10, 'y': sp_msg_y},
                            'parentNode': sp_id,
                            'extent': 'parent',
                            'data': {
                                'label': sp_msg.get('label', ''),
                                'icon': sp_msg.get('icon', ''),
                                'style': style,
                                'preview': sp_msg.get('preview', ''),
                                'content': sp_msg.get('content', ''),
                                'type': sp_msg.get('type', '')
                            },
                            'style': {
                                'backgroundColor': bg_colors.get(style, bg_colors['default']),
                                'border': f"1px solid {border_colors.get(style, border_colors['default'])}",
                                'width': 230,
                                'fontSize': '11px'
                            }
                        })
                        sp_msg_y += y_spacing - 10

                    # Connect messages in sub-cell
                    for k in range(len(sp_msg_ids) - 1):
                        edges.append({
                            'id': f"e_{sp_msg_ids[k]}_to_{sp_msg_ids[k+1]}",
                            'source': sp_msg_ids[k],
                            'target': sp_msg_ids[k + 1]
                        })

                    sc_y_pos += sp_height + 10

                # Connect sub-cells within sub-cascade
                for k in range(len(sc_cell_ids) - 1):
                    edges.append({
                        'id': f"e_{sc_cell_ids[k]}_to_{sc_cell_ids[k+1]}",
                        'source': sc_cell_ids[k],
                        'target': sc_cell_ids[k + 1],
                        'style': {'stroke': '#be4bdb'}
                    })

                y_pos += sc_height + 20

            # Connect nodes sequentially
            for k in range(len(all_node_ids) - 1):
                edges.append({
                    'id': f"e_{all_node_ids[k]}_to_{all_node_ids[k+1]}",
                    'source': all_node_ids[k],
                    'target': all_node_ids[k + 1]
                })

            prev_cell_last_node = all_node_ids[-1] if all_node_ids else group_id

        else:
            # === SIMPLE CELL WITH MESSAGES ===
            # Create cell group containing messages
            group_id = f"{cell_id}_group"

            # Check for quartermaster entry
            quartermaster = cell.get('quartermaster')

            # Calculate group height based on message count + quartermaster
            extra_height = y_spacing if quartermaster else 0
            group_height = max(100, len(messages) * y_spacing + 60 + extra_height)

            nodes.append({
                'id': group_id,
                'type': 'cellGroup',
                'position': {'x': x_offset, 'y': 0},
                'data': {
                    'label': cell['name'],
                    'cell_name': cell['name'],
                    'message_count': len(messages),
                    'has_quartermaster': quartermaster is not None,
                    'type': 'simple'
                },
                'style': {
                    'backgroundColor': '#e7f5ff',
                    'border': '2px solid #1c7ed6',
                    'width': 280,
                    'height': group_height
                }
            })

            # Track all node ids for sequential connections
            all_node_ids = []
            msg_ids = []  # Track message IDs separately
            y_pos = 40

            # Add quartermaster decision node first (if present)
            if quartermaster:
                qm_id = f"{cell_id}_qm"
                all_node_ids.append(qm_id)
                selected_skills = quartermaster.get('selected_skills', [])
                if selected_skills:
                    tools_preview = ", ".join(selected_skills[:3])
                    if len(selected_skills) > 3:
                        tools_preview += f" +{len(selected_skills) - 3}"
                    qm_label = f"🎯 {tools_preview}"
                else:
                    qm_label = "🎯 No tools"

                nodes.append({
                    'id': qm_id,
                    'type': 'quartermasterNode',
                    'position': {'x': 20, 'y': y_pos},
                    'parentNode': group_id,
                    'extent': 'parent',
                    'data': {
                        'label': qm_label,
                        'selected_skills': selected_skills,
                        'reasoning': quartermaster.get('reasoning', '')
                    },
                    'style': {
                        'backgroundColor': '#f3f0ff',
                        'border': '2px solid #7950f2',
                        'width': 240
                    }
                })
                y_pos += y_spacing

            # Create message nodes inside cell group
            for j, msg in enumerate(messages):
                msg_id = f"{cell_id}_msg_{j}"
                msg_ids.append(msg_id)
                all_node_ids.append(msg_id)

                # Get style colors based on message type
                style = msg.get('style', 'default')
                bg_colors = {
                    'system': '#e1f5fe',
                    'user': '#fff9c4',
                    'agent': '#d3f9d8',
                    'tool': '#ffccbc',
                    'validation_pass': '#d3f9d8',  # Green for pass
                    'validation_fail': '#ffe3e3',  # Red for fail
                    'default': '#f8f9fa'
                }
                border_colors = {
                    'system': '#0288d1',
                    'user': '#f9a825',
                    'agent': '#40c057',
                    'tool': '#e64a19',
                    'validation_pass': '#37b24d',  # Green border
                    'validation_fail': '#fa5252',  # Red border
                    'default': '#343a40'
                }

                nodes.append({
                    'id': msg_id,
                    'type': 'messageNode',
                    'position': {'x': 20, 'y': y_pos},
                    'parentNode': group_id,
                    'extent': 'parent',
                    'data': {
                        'label': msg.get('label', ''),
                        'icon': msg.get('icon', ''),
                        'style': style,
                        'preview': msg.get('preview', ''),
                        'content': msg.get('content', ''),
                        'type': msg.get('type', '')
                    },
                    'style': {
                        'backgroundColor': bg_colors.get(style, bg_colors['default']),
                        'border': f"2px solid {border_colors.get(style, border_colors['default'])}",
                        'width': 240
                    }
                })
                y_pos += y_spacing

            # Connect all nodes sequentially (quartermaster -> messages)
            for k in range(len(all_node_ids) - 1):
                edges.append({
                    'id': f"e_{all_node_ids[k]}_to_{all_node_ids[k+1]}",
                    'source': all_node_ids[k],
                    'target': all_node_ids[k + 1]
                })

            prev_cell_last_node = all_node_ids[-1] if all_node_ids else group_id

    # Connect cells - need to find the correct group IDs
    cell_group_ids = []
    for cell_idx, cell in enumerate(cells):
        cell_id = f"cell_{cell_idx}"
        cell_type = cell.get('type', 'simple')
        takes = cell.get('takes') or []
        wards = cell.get('wards')
        sub_cascades = cell.get('sub_cascades') or []

        if cell_type == 'takes' and takes:
            cell_group_ids.append(f"{cell_id}_takes_group")
        elif wards and (wards.get('pre') or wards.get('post')):
            cell_group_ids.append(f"{cell_id}_wards_group")
        elif cell_type == 'sub_cascade' and sub_cascades:
            cell_group_ids.append(f"{cell_id}_group")
        else:
            cell_group_ids.append(f"{cell_id}_group")

    # Create edges between consecutive cells
    for i in range(len(cell_group_ids) - 1):
        edges.append({
            'id': f"e_cell_{i}_to_{i+1}",
            'source': cell_group_ids[i],
            'target': cell_group_ids[i + 1],
            'animated': True,
            'style': {'stroke': '#1c7ed6', 'strokeWidth': 2}
        })

    return {
        'nodes': nodes,
        'edges': edges,
        'session_id': tree.get('session_id'),
        'cascade': tree.get('cascade')
    }
