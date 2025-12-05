"""
Windlass Mermaid Visualizer

Generates execution flow diagrams from Echo history showing:
- Cascade structure with nested phases
- Phase-to-phase handoffs
- Soundings (Tree of Thought) with parallel attempts and winner selection
- Reforge (iterative refinement) with sequential steps
- Sub-cascades as nested containers
- Wards as validation checkpoints
"""
import json
import re
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from .echo import Echo


@dataclass
class ExecutionNode:
    """Represents a node in the execution tree."""
    id: str
    node_type: str  # cascade, phase, turn, tool, soundings, reforge, etc.
    name: str
    role: str = ""
    content: str = ""
    parent_id: Optional[str] = None
    children: List['ExecutionNode'] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    # Sounding/Reforge specific
    sounding_index: Optional[int] = None
    is_winner: bool = False
    reforge_step: Optional[int] = None


def sanitize_label(content: Any, max_length: int = 50) -> str:
    """Sanitize content for Mermaid labels."""
    if isinstance(content, (list, dict)):
        try:
            if isinstance(content, list):
                return f"[{len(content)} items]"
            return f"{{{len(content)} keys}}"
        except:
            pass

    s = str(content)
    # Escape special Mermaid characters
    s = s.replace('"', "'")
    s = s.replace('\n', ' ')
    s = s.replace('#', '')
    s = s.replace('<', '‹')
    s = s.replace('>', '›')
    # Collapse whitespace
    s = ' '.join(s.split())
    # Truncate
    if len(s) > max_length:
        s = s[:max_length] + "..."
    return s


def safe_id(trace_id: str) -> str:
    """Create a safe Mermaid node ID from trace ID."""
    return "n_" + trace_id.replace("-", "")[:12]


def extract_metadata(entry: Dict) -> Dict:
    """Extract and parse metadata from history entry."""
    meta = entry.get("metadata", {})
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except:
            meta = {}
    return {
        'sounding_index': meta.get('sounding_index'),
        'is_winner': meta.get('is_winner'),
        'reforge_step': meta.get('reforge_step'),
        'phase_name': meta.get('phase_name'),
        'cascade_id': meta.get('cascade_id'),
        'factor': meta.get('factor'),
        'has_soundings': meta.get('has_soundings'),
        'has_wards': meta.get('has_wards'),
        'has_sub_cascades': meta.get('has_sub_cascades'),
        'handoffs': meta.get('handoffs', []),
        'winner_index': meta.get('winner_index'),
        'depth': meta.get('depth', 0),
        # Ward-specific
        'ward_type': meta.get('ward_type'),
        'validator': meta.get('validator'),
        'mode': meta.get('mode'),
        'valid': meta.get('valid'),
        'reason': meta.get('reason'),
        # Quartermaster-specific
        'selected_tackle': meta.get('selected_tackle', []),
        'reasoning': meta.get('reasoning'),
        # Reforge-specific
        'reforge_step': meta.get('reforge_step'),
        'total_steps': meta.get('total_steps'),
        'factor_per_step': meta.get('factor_per_step'),
        'attempt_index': meta.get('attempt_index'),
        'has_mutation': meta.get('has_mutation'),
        # Retry/validation-specific
        'attempt': meta.get('attempt'),
        'max_attempts': meta.get('max_attempts'),
        # Mutation-specific (for soundings)
        'mutation_applied': meta.get('mutation_applied'),
        'mutation_type': meta.get('mutation_type'),
        'mutation_template': meta.get('mutation_template'),
        # Tool-specific
        'tool_name': meta.get('tool_name'),
        # Turn-specific
        'turn_number': meta.get('turn_number'),
        'max_turns': meta.get('max_turns'),
    }


def extract_routing_choices(lineage: List[Dict]) -> Dict[str, str]:
    """
    Extract which phase dynamically routed to which target.

    Parses lineage entries like "Dynamically routed to: target_phase"

    Returns:
        Dict mapping source_phase -> target_phase for dynamic routing decisions
    """
    routing_choices = {}
    for item in lineage:
        phase = item.get("phase")
        output = item.get("output", "")
        if isinstance(output, str) and output.startswith("Dynamically routed to: "):
            target = output.replace("Dynamically routed to: ", "")
            routing_choices[phase] = target
    return routing_choices


def extract_ward_retries(history: List[Dict]) -> Dict[str, Dict]:
    """
    Extract ward retry information per phase.

    Identifies phases where retry-mode wards failed and triggered re-execution.

    Returns:
        Dict: phase_name -> {
            'has_retry': bool,
            'retry_count': int,
            'validators': [list of validator names that failed]
        }
    """
    retry_info = {}

    for entry in history:
        node_type = entry.get("node_type", "")
        if node_type in ("pre_ward", "post_ward"):
            meta = extract_metadata(entry)
            phase_name = meta.get("phase_name", "unknown")
            mode = meta.get("mode")
            valid = meta.get("valid")
            validator = meta.get("validator", "validator")

            # Track retry wards that failed
            if mode == "retry" and valid is False:
                if phase_name not in retry_info:
                    retry_info[phase_name] = {
                        'has_retry': True,
                        'retry_count': 0,
                        'validators': []
                    }
                retry_info[phase_name]['retry_count'] += 1
                if validator not in retry_info[phase_name]['validators']:
                    retry_info[phase_name]['validators'].append(validator)

        elif node_type == "validation_retry":
            meta = extract_metadata(entry)
            phase_name = meta.get("phase_name", "unknown")
            if phase_name not in retry_info:
                retry_info[phase_name] = {
                    'has_retry': True,
                    'retry_count': 1,
                    'validators': []
                }
            else:
                retry_info[phase_name]['retry_count'] += 1

    return retry_info


def extract_validation_retries(history: List[Dict]) -> Dict[str, Dict]:
    """
    Extract validation retry (loop_until) information per phase.

    When max_attempts > 1 and validation fails, the phase re-executes.
    This tracks those retry loops separately from ward retries.

    Returns:
        Dict: phase_name -> {
            'retry_count': int,  # Number of retry attempts (0 = passed first try)
            'max_attempts': int,  # Total attempts allowed
            'reasons': [str],    # Validation failure reasons
            'passed': bool       # Whether it eventually passed
        }
    """
    validation_retries = {}

    for entry in history:
        node_type = entry.get("node_type", "")

        # Track validation_retry nodes (injected when attempt > 0)
        if node_type == "validation_retry":
            meta = extract_metadata(entry)
            phase_name = meta.get("phase_name", "unknown")
            content = entry.get("content", "")

            if phase_name not in validation_retries:
                validation_retries[phase_name] = {
                    'retry_count': 0,
                    'max_attempts': meta.get('max_attempts', 1),
                    'reasons': [],
                    'passed': False  # Will update if we see success
                }

            validation_retries[phase_name]['retry_count'] += 1

            # Extract reason from content
            if "rejected" in content.lower() or "failed" in content.lower():
                reason = content[:100] if len(content) > 100 else content
                validation_retries[phase_name]['reasons'].append(reason)

        # Track schema_validation success to mark as passed
        elif node_type == "schema_validation":
            meta = extract_metadata(entry)
            phase_name = meta.get("phase_name", "unknown")
            content = entry.get("content", "")

            if phase_name in validation_retries and "passed" in content.lower():
                validation_retries[phase_name]['passed'] = True

        # Also look for loop_until validator results
        elif node_type == "loop_until_validation":
            meta = extract_metadata(entry)
            phase_name = meta.get("phase_name", "unknown")
            valid = meta.get("valid")

            if phase_name not in validation_retries:
                validation_retries[phase_name] = {
                    'retry_count': 0,
                    'max_attempts': meta.get('max_attempts', 1),
                    'reasons': [],
                    'passed': False
                }

            if valid:
                validation_retries[phase_name]['passed'] = True
            else:
                validation_retries[phase_name]['retry_count'] += 1
                reason = meta.get('reason', 'Validation failed')
                validation_retries[phase_name]['reasons'].append(reason)

    return validation_retries


def extract_errors(history: List[Dict]) -> Dict[str, List[Dict]]:
    """
    Extract error nodes per phase.

    Returns:
        Dict: phase_name -> [
            {'error_type': str, 'message': str, 'trace_id': str}
        ]
    """
    errors = {}

    for entry in history:
        node_type = entry.get("node_type", "")
        if node_type in ("error", "validation_error", "schema_validation_failed"):
            meta = extract_metadata(entry)
            phase_name = meta.get("phase_name", "unknown")
            content = entry.get("content", "")

            error_info = {
                'error_type': node_type,
                'message': content[:100] if len(content) > 100 else content,
                'trace_id': entry.get("trace_id", "")
            }

            if phase_name not in errors:
                errors[phase_name] = []
            errors[phase_name].append(error_info)

    return errors


def extract_quartermaster_selections(history: List[Dict]) -> Dict[str, Dict]:
    """
    Extract Quartermaster (manifest) tool selections per phase.

    Returns:
        Dict: phase_name -> {
            'selected_tools': [list of tool names],
            'reasoning': str
        }
    """
    selections = {}

    for entry in history:
        node_type = entry.get("node_type", "")
        if node_type == "quartermaster_result":
            meta = extract_metadata(entry)
            phase_name = meta.get("phase_name", "unknown")
            selected_tackle = meta.get("selected_tackle", [])
            reasoning = meta.get("reasoning", "")

            selections[phase_name] = {
                'selected_tools': selected_tackle,
                'reasoning': reasoning[:100] if len(reasoning) > 100 else reasoning
            }

    return selections


def extract_turns(history: List[Dict]) -> Dict[str, List[Dict]]:
    """
    Extract turn information per phase for detailed visualization.

    Returns:
        Dict: phase_name -> [
            {'turn_number': int, 'has_tool_calls': bool, 'content_preview': str}
        ]
    """
    turns = {}

    for entry in history:
        node_type = entry.get("node_type", "")
        if node_type == "turn":
            meta = extract_metadata(entry)
            phase_name = meta.get("phase_name", "unknown")
            turn_number = meta.get("turn_number", 1)

            if phase_name not in turns:
                turns[phase_name] = []

            turns[phase_name].append({
                'turn_number': turn_number,
                'trace_id': entry.get("trace_id", "")
            })

        # Also track agent responses within turns
        elif node_type == "agent":
            meta = extract_metadata(entry)
            phase_name = meta.get("phase_name", "unknown")
            content = entry.get("content", "")
            tool_calls = entry.get("tool_calls")

            # Find the corresponding turn and add info
            if phase_name in turns and turns[phase_name]:
                last_turn = turns[phase_name][-1]
                last_turn['has_tool_calls'] = bool(tool_calls)
                last_turn['content_preview'] = content[:50] if content else ""

    return turns


def extract_blocked_phases(history: List[Dict]) -> Dict[str, Dict]:
    """
    Extract phases that were blocked by blocking-mode wards.

    Returns:
        Dict: phase_name -> {
            'blocked': True,
            'validator': str,
            'reason': str
        }
    """
    blocked = {}

    for entry in history:
        node_type = entry.get("node_type", "")
        if node_type in ("pre_ward", "post_ward", "ward_block"):
            meta = extract_metadata(entry)
            mode = meta.get("mode")
            valid = meta.get("valid")
            phase_name = meta.get("phase_name", "unknown")

            if mode == "blocking" and valid is False:
                blocked[phase_name] = {
                    'blocked': True,
                    'validator': meta.get("validator", "validator"),
                    'reason': meta.get("reason", "Validation failed"),
                    'ward_type': meta.get("ward_type", "post")
                }

    return blocked


def extract_state_changes(history: List[Dict]) -> Dict[str, List[str]]:
    """
    Extract set_state calls to show state flow between phases.

    Returns:
        Dict: phase_name -> [list of state keys set]
    """
    state_changes = {}

    for entry in history:
        node_type = entry.get("node_type", "")
        if node_type == "tool_result":
            content = entry.get("content", "")
            meta = extract_metadata(entry)
            phase_name = meta.get("phase_name", "unknown")

            # Check if this is a set_state result
            # Format: "State updated: {key} = {value}"
            if isinstance(content, str) and ("state updated" in content.lower() or "set_state" in content.lower()):
                import re
                # Try multiple patterns
                match = re.search(r"[Ss]tate\s+updated:\s*(\w+)\s*=", content)
                if not match:
                    match = re.search(r"[Ss]tate\s*['\"](\w+)['\"]", content)
                if match:
                    key = match.group(1)
                    if phase_name not in state_changes:
                        state_changes[phase_name] = []
                    if key not in state_changes[phase_name]:
                        state_changes[phase_name].append(key)

        # Also check tool_calls for set_state
        tool_calls = entry.get("tool_calls")
        if tool_calls:
            meta = extract_metadata(entry)
            phase_name = meta.get("phase_name", "unknown")
            for tc in tool_calls:
                if isinstance(tc, dict):
                    func = tc.get("function", {})
                    if isinstance(func, dict) and func.get("name") == "set_state":
                        args = func.get("arguments", "{}")
                        try:
                            if isinstance(args, str):
                                args = json.loads(args)
                            key = args.get("key", args.get("name"))
                            if key:
                                if phase_name not in state_changes:
                                    state_changes[phase_name] = []
                                if key not in state_changes[phase_name]:
                                    state_changes[phase_name].append(key)
                        except:
                            pass

    return state_changes


def extract_sounding_mutations(history: List[Dict]) -> Dict[str, Dict[int, Dict]]:
    """
    Extract mutation information for sounding attempts.

    Returns:
        Dict: phase_name -> {sounding_index -> {'mutation_applied': str, 'mutation_type': str, 'is_winner': bool}}
    """
    mutations = {}

    for entry in history:
        node_type = entry.get("node_type", "")
        if node_type == "sounding_attempt":
            meta = extract_metadata(entry)
            phase_name = meta.get("phase_name", "unknown")
            sounding_index = meta.get("sounding_index", 0)
            mutation_applied = meta.get("mutation_applied")
            is_winner = meta.get("is_winner", False)

            if phase_name not in mutations:
                mutations[phase_name] = {}

            mutations[phase_name][sounding_index] = {
                'mutation_applied': mutation_applied,
                'is_winner': is_winner
            }

    return mutations


def get_live_session_state(session_id: str) -> dict:
    """
    Get the live running state for a session.

    Returns:
        Dict with status, current_phase, phase_progress, or None if not found.
    """
    try:
        from .state import get_session_state
        return get_session_state(session_id)
    except Exception:
        return None


def format_phase_progress_indicator(phase_progress: dict) -> str:
    """
    Format a compact indicator string showing current position within a phase.

    Uses phase_progress from state.json to show exactly where execution is:
    - Stage: pre_ward, main, post_ward
    - Turn: T1/3 (turn 1 of 3)
    - Attempt: A2/5 (attempt 2 of 5 for validation)
    - Sounding: S2/5⚖ (sounding 2 of 5, currently evaluating)
    - Reforge: R1/3 (reforge step 1 of 3)
    - Ward: 🛡️grammar_check (current ward being run)
    - Tool: 🔧run_code (current tool being called)

    Returns compact indicator like: "T2/3 🔧run_code" or "S3/5 ⚖️eval"
    """
    if not phase_progress:
        return ""

    parts = []

    # Stage indicator (only if not 'main')
    stage = phase_progress.get("stage", "main")
    if stage == "pre_ward":
        parts.append("⏵pre")
    elif stage == "post_ward":
        parts.append("⏵post")

    # Turn info
    turn_info = phase_progress.get("turn", {})
    current_turn = turn_info.get("current", 0)
    max_turns = turn_info.get("max", 1)
    if current_turn > 0:
        parts.append(f"T{current_turn}/{max_turns}")

    # Attempt info (validation retries)
    attempt_info = phase_progress.get("attempt", {})
    current_attempt = attempt_info.get("current", 0)
    max_attempts = attempt_info.get("max", 1)
    if current_attempt > 0 and max_attempts > 1:
        parts.append(f"A{current_attempt}/{max_attempts}")

    # Sounding info
    sounding_info = phase_progress.get("sounding")
    if sounding_info:
        sounding_idx = sounding_info.get("index")
        sounding_factor = sounding_info.get("factor", 1)
        sounding_stage = sounding_info.get("stage", "executing")

        if sounding_idx is not None:
            stage_icon = "⚖️" if sounding_stage == "evaluating" else "🔱"
            parts.append(f"{stage_icon}S{sounding_idx + 1}/{sounding_factor}")

    # Reforge info
    reforge_info = phase_progress.get("reforge")
    if reforge_info:
        reforge_step = reforge_info.get("step")
        total_steps = reforge_info.get("total_steps", 1)
        if reforge_step is not None:
            parts.append(f"🔨R{reforge_step}/{total_steps}")

    # Ward info
    ward_info = phase_progress.get("ward")
    if ward_info and ward_info.get("name"):
        ward_name = ward_info.get("name", "")
        ward_type = ward_info.get("type", "post")
        ward_idx = ward_info.get("index", 1)
        total_wards = ward_info.get("total", 1)
        type_icon = "🛡️" if ward_type == "pre" else "🔄"
        # Truncate ward name
        short_name = ward_name[:10] + ".." if len(ward_name) > 12 else ward_name
        parts.append(f"{type_icon}{short_name}({ward_idx}/{total_wards})")

    # Tool info
    tool_info = phase_progress.get("tool", {})
    current_tool = tool_info.get("current")
    if current_tool:
        # Truncate tool name
        short_tool = current_tool[:10] + ".." if len(current_tool) > 12 else current_tool
        parts.append(f"🔧{short_tool}")

    # Timing info (optional - elapsed time)
    timing = phase_progress.get("timing", {})
    phase_elapsed = timing.get("phase_elapsed_ms", 0)
    if phase_elapsed > 1000:  # Only show if > 1 second
        seconds = phase_elapsed // 1000
        parts.append(f"⏱{seconds}s")

    return " ".join(parts) if parts else ""


def get_running_internal_node_id(phase_progress: dict, pid: str) -> Optional[str]:
    """
    Determine which internal node ID within a composite phase is currently executing.

    Returns the Mermaid node ID that should be highlighted, or None if not determinable.
    """
    if not phase_progress:
        return None

    stage = phase_progress.get("stage", "main")

    # Pre-ward stage
    if stage == "pre_ward":
        ward_info = phase_progress.get("ward")
        if ward_info:
            ward_idx = ward_info.get("index", 1) - 1  # 0-indexed
            return f"{pid}_pre{ward_idx}"

    # Post-ward stage
    elif stage == "post_ward":
        ward_info = phase_progress.get("ward")
        if ward_info:
            ward_idx = ward_info.get("index", 1) - 1  # 0-indexed
            return f"{pid}_post{ward_idx}"

    # Main stage - could be turn, sounding, or reforge
    elif stage == "main":
        sounding_info = phase_progress.get("sounding")
        if sounding_info:
            sounding_idx = sounding_info.get("index")
            sounding_stage = sounding_info.get("stage")

            if sounding_stage == "evaluating":
                return f"{pid}_eval"
            elif sounding_idx is not None:
                return f"{pid}_a{sounding_idx}"

        reforge_info = phase_progress.get("reforge")
        if reforge_info:
            reforge_step = reforge_info.get("step")
            if reforge_step is not None:
                return f"{pid}_rf{reforge_step}"

        # Turn-based progress
        turn_info = phase_progress.get("turn", {})
        current_turn = turn_info.get("current", 0)
        if current_turn > 0:
            return f"{pid}_t{current_turn - 1}"

    return None


def flatten_history(history: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """
    Flatten history entries, extracting nested sub_echo histories.

    When echo.merge() is called, sub-cascade history is stored as:
    {"sub_echo": "session_id", "history": [...]}

    Returns:
        (flattened_entries, sub_echo_entries)
        - flattened_entries: All regular history entries
        - sub_echo_entries: List of {"sub_echo": session_id, "history": [...]} entries
    """
    flattened = []
    sub_echoes = []
    for entry in history:
        if "sub_echo" in entry and "history" in entry:
            # This is a merged sub-cascade - keep track of it
            sub_echoes.append(entry)
            # Also recursively flatten its history
            sub_history = entry.get("history", [])
            nested_flat, nested_subs = flatten_history(sub_history)
            flattened.extend(nested_flat)
            sub_echoes.extend(nested_subs)
        else:
            flattened.append(entry)
    return flattened, sub_echoes


def build_execution_tree(echo: Echo) -> Tuple[List[ExecutionNode], Dict[str, ExecutionNode]]:
    """
    Build an execution tree from Echo history.
    Returns (root_nodes, all_nodes_map)
    """
    # Flatten history to include nested sub_echo entries
    history, _ = flatten_history(echo.history)
    nodes_map: Dict[str, ExecutionNode] = {}
    root_nodes: List[ExecutionNode] = []

    # First pass: create all nodes
    for entry in history:
        trace_id = entry.get("trace_id")
        if not trace_id or trace_id in nodes_map:
            continue

        # Extract metadata
        meta = extract_metadata(entry)

        node = ExecutionNode(
            id=trace_id,
            node_type=entry.get("node_type", "msg"),
            name=entry.get("content", "")[:30] if entry.get("node_type") in ("cascade", "phase") else "",
            role=entry.get("role", ""),
            content=entry.get("content", ""),
            parent_id=entry.get("parent_id"),
            metadata=meta,
            sounding_index=meta.get('sounding_index'),
            is_winner=meta.get('is_winner', False),
            reforge_step=meta.get('reforge_step')
        )
        nodes_map[trace_id] = node

    # Second pass: build parent-child relationships
    for node in nodes_map.values():
        if node.parent_id and node.parent_id in nodes_map:
            nodes_map[node.parent_id].children.append(node)
        else:
            root_nodes.append(node)

    return root_nodes, nodes_map


def collect_phases(nodes_map: Dict[str, ExecutionNode]) -> List[ExecutionNode]:
    """Collect all phase nodes in order of appearance."""
    phases = []
    seen = set()
    for node in nodes_map.values():
        if node.node_type == "phase" and node.id not in seen:
            phases.append(node)
            seen.add(node.id)
    return phases


def collect_soundings(nodes_map: Dict[str, ExecutionNode], phase_id: str) -> Dict[int, List[ExecutionNode]]:
    """Collect sounding attempts for a phase, grouped by sounding_index."""
    soundings: Dict[int, List[ExecutionNode]] = {}

    for node in nodes_map.values():
        if node.parent_id == phase_id or (node.parent_id and nodes_map.get(node.parent_id, ExecutionNode("", "", "")).parent_id == phase_id):
            if node.sounding_index is not None:
                if node.sounding_index not in soundings:
                    soundings[node.sounding_index] = []
                soundings[node.sounding_index].append(node)

    return soundings


def collect_reforge_steps(nodes_map: Dict[str, ExecutionNode], phase_id: str) -> Dict[int, List[ExecutionNode]]:
    """Collect reforge steps for a phase, grouped by reforge_step."""
    reforge_steps: Dict[int, List[ExecutionNode]] = {}

    for node in nodes_map.values():
        if node.reforge_step is not None:
            if node.reforge_step not in reforge_steps:
                reforge_steps[node.reforge_step] = []
            reforge_steps[node.reforge_step].append(node)

    return reforge_steps


def export_execution_graph_json(echo: Echo, output_path: str) -> str:
    """
    Export execution graph as structured JSON for UI consumption.

    Provides easy-to-query structure with trace_ids for DB lookups.
    Includes nodes, edges, and metadata without needing to parse mermaid.

    Returns:
        Path to written JSON file
    """
    root_nodes, nodes_map = build_execution_tree(echo)
    history, sub_echoes = flatten_history(echo.history)

    # Build nodes list
    nodes = []
    edges = []

    for trace_id, node in nodes_map.items():
        # Create node entry
        node_entry = {
            "trace_id": trace_id,
            "node_type": node.node_type,
            "role": node.role,
            "parent_id": node.parent_id,
            "depth": node.metadata.get("depth", 0),

            # Metadata
            "phase_name": node.metadata.get("phase_name"),
            "cascade_id": node.metadata.get("cascade_id"),

            # Soundings/Reforge
            "sounding_index": node.sounding_index,
            "is_winner": node.is_winner,
            "reforge_step": node.reforge_step,

            # Content preview (truncated for JSON size)
            "content_preview": str(node.content)[:100] if node.content else None,

            # Additional metadata
            "metadata": {
                k: v for k, v in node.metadata.items()
                if k not in ("phase_name", "cascade_id", "depth")
            }
        }
        nodes.append(node_entry)

        # Create edge if has parent
        if node.parent_id:
            edges.append({
                "source": node.parent_id,
                "target": trace_id,
                "edge_type": "parent_child"
            })

    # Collect phases in order
    phases = []
    for item in echo.lineage:
        phases.append({
            "phase": item.get("phase"),
            "trace_id": item.get("trace_id"),
            "output_preview": str(item.get("output", ""))[:100]
        })

    # Build phase connections from history
    phase_nodes = [n for n in nodes if n["node_type"] == "phase"]
    for i in range(len(phase_nodes) - 1):
        edges.append({
            "source": phase_nodes[i]["trace_id"],
            "target": phase_nodes[i+1]["trace_id"],
            "edge_type": "phase_sequence"
        })

    # Collect soundings info
    soundings_groups = {}
    for node in nodes:
        if node["sounding_index"] is not None:
            phase = node.get("phase_name", "unknown")
            if phase not in soundings_groups:
                soundings_groups[phase] = []
            soundings_groups[phase].append({
                "trace_id": node["trace_id"],
                "sounding_index": node["sounding_index"],
                "is_winner": node["is_winner"],
                "reforge_step": node.get("reforge_step")
            })

    # Build output structure
    graph = {
        "session_id": echo.session_id,
        "generated_at": None,  # Could add timestamp

        "nodes": nodes,
        "edges": edges,

        "phases": phases,
        "soundings": soundings_groups,

        "summary": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "total_phases": len(phases),
            "has_soundings": len(soundings_groups) > 0,
            "has_sub_cascades": len(sub_echoes) > 0
        }
    }

    # Write JSON
    with open(output_path, "w") as f:
        json.dump(graph, f, indent=2, default=str)

    return output_path


def export_react_flow_graph(echo: Echo, output_path: str) -> str:
    """
    Export execution graph in React Flow format for direct UI use.

    React Flow format: https://reactflow.dev/
    Ready to drop into React Flow component with custom node types.

    Returns:
        Path to written JSON file
    """
    root_nodes, nodes_map = build_execution_tree(echo)
    history, sub_echoes = flatten_history(echo.history)

    rf_nodes = []
    rf_edges = []

    # Position layout (simple left-to-right based on depth and order)
    node_positions = {}
    y_offset = 0
    x_spacing = 250
    y_spacing = 100

    # Group nodes by depth for layout
    depth_groups = {}
    for trace_id, node in nodes_map.items():
        depth = node.metadata.get("depth", 0)
        if depth not in depth_groups:
            depth_groups[depth] = []
        depth_groups[depth].append((trace_id, node))

    # Assign positions
    for depth in sorted(depth_groups.keys()):
        nodes_at_depth = depth_groups[depth]
        for i, (trace_id, node) in enumerate(nodes_at_depth):
            node_positions[trace_id] = {
                "x": depth * x_spacing,
                "y": i * y_spacing
            }

    # Build React Flow nodes
    for trace_id, node in nodes_map.items():
        pos = node_positions.get(trace_id, {"x": 0, "y": y_offset})
        y_offset += y_spacing

        # Determine node type for custom rendering
        if node.node_type == "phase":
            rf_type = "phaseNode"
        elif node.node_type == "cascade":
            rf_type = "cascadeNode"
        elif node.node_type in ("sounding_attempt", "soundings"):
            rf_type = "soundingNode"
        elif node.node_type in ("reforge_step", "reforge_attempt"):
            rf_type = "reforgeNode"
        elif node.node_type == "tool_result":
            rf_type = "toolNode"
        else:
            rf_type = "default"

        rf_node = {
            "id": trace_id,
            "type": rf_type,
            "position": pos,
            "data": {
                "label": node.content[:50] if node.content else node.node_type,
                "trace_id": trace_id,
                "node_type": node.node_type,
                "role": node.role,
                "phase_name": node.metadata.get("phase_name"),
                "cascade_id": node.metadata.get("cascade_id"),
                "sounding_index": node.sounding_index,
                "is_winner": node.is_winner,
                "reforge_step": node.reforge_step,
                "metadata": node.metadata
            }
        }

        # Add parent node reference for grouping
        if node.parent_id:
            rf_node["parentNode"] = node.parent_id
            rf_node["extent"] = "parent"  # Constrain to parent bounds

        rf_nodes.append(rf_node)

    # Build React Flow edges
    for trace_id, node in nodes_map.items():
        if node.parent_id:
            # Determine edge style based on relationship
            edge_style = {}
            animated = False
            edge_type = "default"

            if node.is_winner:
                edge_style = {"stroke": "#00ff00", "strokeWidth": 3}
                animated = True
                edge_type = "winner"
            elif node.sounding_index is not None:
                edge_style = {"stroke": "#fab005", "strokeDasharray": "5 5"}
                edge_type = "sounding"
            elif node.node_type == "phase":
                edge_style = {"stroke": "#1c7ed6", "strokeWidth": 2}
                edge_type = "phase"

            rf_edge = {
                "id": f"e_{node.parent_id}_{trace_id}",
                "source": node.parent_id,
                "target": trace_id,
                "type": edge_type,
                "animated": animated,
                "style": edge_style,
                "data": {
                    "edge_type": "parent_child"
                }
            }

            rf_edges.append(rf_edge)

    # Add phase sequence edges
    phases = [item.get("trace_id") for item in echo.lineage if item.get("trace_id")]
    for i in range(len(phases) - 1):
        rf_edges.append({
            "id": f"seq_{phases[i]}_{phases[i+1]}",
            "source": phases[i],
            "target": phases[i+1],
            "type": "phase_sequence",
            "animated": True,
            "style": {"stroke": "#1c7ed6", "strokeWidth": 2},
            "data": {"edge_type": "phase_sequence"}
        })

    # Output React Flow format
    react_flow_data = {
        "nodes": rf_nodes,
        "edges": rf_edges,
        "meta": {
            "session_id": echo.session_id,
            "total_nodes": len(rf_nodes),
            "total_edges": len(rf_edges)
        }
    }

    with open(output_path, "w") as f:
        json.dump(react_flow_data, f, indent=2, default=str)

    return output_path


def generate_mermaid_string(echo: Echo) -> str:
    """
    Generate a Mermaid flowchart string from Echo history.

    The diagram shows:
    - Cascade as the outer container
    - Phases as nodes connected by handoffs
    - Soundings as parallel branches with winner highlighting
    - Reforge as sequential refinement steps
    - Sub-cascades as nested groups

    Returns the mermaid diagram as a string without writing to file.
    """
    root_nodes, nodes_map = build_execution_tree(echo)

    # Flatten history to include nested sub_echo entries
    history, sub_echoes = flatten_history(echo.history)

    lines = ["graph TD"]

    # Style definitions - Midnight Fjord Dark Theme
    # Background: #0B1219 (Midnight Fjord), #16202A (Abyssal Slate)
    # Accents: #2DD4BF (Glacial Ice), #D9A553 (Compass Brass)
    # Text: #F0F4F8 (Frosted White), #9AA5B1 (Mist Gray)
    lines.extend([
        "    %% Node Styles - Midnight Fjord Dark Theme",
        "    classDef cascade fill:#16202A,stroke:#2C3B4B,stroke-width:2px,color:#F0F4F8;",
        "    classDef phase fill:#16202A,stroke:#2DD4BF,stroke-width:2px,color:#F0F4F8;",
        "    classDef phase_active fill:#1a2a3a,stroke:#2DD4BF,stroke-width:3px,color:#F0F4F8;",
        "    classDef system fill:#16202A,stroke:#60a5fa,color:#F0F4F8;",
        "    classDef user fill:#16202A,stroke:#D9A553,color:#F0F4F8;",
        "    classDef tool fill:#16202A,stroke:#f472b6,color:#F0F4F8;",
        "    classDef soundings_group fill:#16202A,stroke:#D9A553,stroke-width:2px,color:#F0F4F8;",
        "    classDef attempt fill:#16202A,stroke:#D9A553,stroke-dasharray:3 3,color:#F0F4F8;",
        "    classDef winner fill:#16202A,stroke:#F0F4F8,stroke-width:4px,color:#F0F4F8;",
        "    classDef loser fill:#16202A,stroke:#9AA5B1,stroke-dasharray:5 5,color:#9AA5B1;",
        "    classDef reforge_group fill:#16202A,stroke:#D9A553,stroke-width:2px,color:#F0F4F8;",
        "    classDef reforge_step fill:#16202A,stroke:#D9A553,color:#F0F4F8;",
        "    classDef evaluator fill:#16202A,stroke:#a78bfa,stroke-width:2px,color:#F0F4F8;",
        "    classDef agent fill:#16202A,stroke:#2DD4BF,color:#F0F4F8;",
        "    classDef sub_cascade fill:#16202A,stroke:#a78bfa,stroke-width:2px,color:#F0F4F8;",
        "    classDef ward_pre fill:#16202A,stroke:#2DD4BF,color:#F0F4F8;",
        "    classDef ward_post fill:#16202A,stroke:#CF6679,color:#F0F4F8;",
        "    classDef ward_fail fill:#16202A,stroke:#CF6679,stroke-width:3px,color:#CF6679;",
        "",
    ])

    # Collect sub-cascade trace IDs to filter out their phases from top-level rendering
    sub_cascade_trace_ids = set()
    for sub_echo in sub_echoes:
        sub_history = sub_echo.get("history", [])
        for entry in sub_history:
            if entry.get("node_type") == "cascade":
                sub_cascade_trace_ids.add(entry.get("trace_id"))

    # Collect structural entries from history with their metadata
    cascade_entry = None
    phase_entries = []
    soundings_entries = []
    sounding_attempts = []
    evaluator_entries = []
    ward_entries = []
    quartermaster_entries = []

    for entry in history:
        node_type = entry.get("node_type")
        meta = extract_metadata(entry)

        if node_type == "cascade":
            # Skip sub-cascade entries - they'll be rendered inline
            if entry.get("trace_id") in sub_cascade_trace_ids:
                continue
            cascade_entry = entry
        elif node_type == "phase":
            # Skip phases that belong to sub-cascades
            if entry.get("parent_id") in sub_cascade_trace_ids:
                continue
            phase_entries.append(entry)
        elif node_type == "soundings":
            soundings_entries.append(entry)
        elif node_type == "sounding_attempt":
            sounding_attempts.append(entry)
        elif node_type in ("evaluator", "evaluation"):
            evaluator_entries.append(entry)
        elif node_type in ("pre_ward", "post_ward"):
            ward_entries.append(entry)
        elif node_type == "quartermaster_result":
            quartermaster_entries.append(entry)
        elif node_type in ("validation", "schema_validation"):
            # Collect validation entries (loop_until and output_schema)
            # We'll render these inline in the phase
            pass  # Handled via phase messages below
        elif node_type == "validation_retry":
            # Retry messages are already captured as user messages
            pass
        elif node_type == "cascade_soundings":
            # Cascade-level soundings start marker
            pass  # Collected separately below
        elif node_type == "cascade_sounding_attempt":
            # Individual cascade sounding attempt
            pass  # Collected separately below
        elif node_type == "cascade_evaluator":
            # Cascade soundings evaluator
            pass  # Collected separately below
        elif node_type == "cascade_soundings_result":
            # Cascade soundings result/winner
            pass  # Collected separately below
        elif node_type in ("reforge_step", "reforge_attempt", "reforge_evaluator", "reforge_winner"):
            # Reforge entries - collected separately by phase
            pass

    # Extract phase order from lineage
    phase_order = [item.get("phase") for item in echo.lineage]

    # Sort phases by lineage order if available
    if phase_order:
        def phase_sort_key(entry):
            content = entry.get("content", "")
            name = content.replace("Phase: ", "") if content.startswith("Phase: ") else content
            try:
                return phase_order.index(name)
            except ValueError:
                return 999
        phase_entries.sort(key=phase_sort_key)

    # Note: Removed cascade container wrapper for cleaner visualization
    # Diagram renders phases directly without outer border box

    # Group sounding attempts by phase
    soundings_by_phase: Dict[str, List[Dict]] = {}
    for sa in sounding_attempts:
        meta = extract_metadata(sa)
        phase_name = meta.get("phase_name", "unknown")
        if phase_name not in soundings_by_phase:
            soundings_by_phase[phase_name] = []
        soundings_by_phase[phase_name].append(sa)

    # Group evaluator entries by phase
    evaluators_by_phase: Dict[str, Dict] = {}
    for ev in evaluator_entries:
        meta = extract_metadata(ev)
        phase_name = meta.get("phase_name", "unknown")
        evaluators_by_phase[phase_name] = ev

    # Group quartermaster entries by phase
    quartermaster_by_phase: Dict[str, Dict] = {}
    for qm in quartermaster_entries:
        meta = extract_metadata(qm)
        phase_name = meta.get("phase_name", "unknown")
        quartermaster_by_phase[phase_name] = qm

    # Group reforge entries by phase and step
    # Structure: {phase_name: {step: {steps: [], attempts: [], evaluator: None, winner: None}}}
    reforge_by_phase: Dict[str, Dict[int, Dict]] = {}
    for entry in history:
        node_type = entry.get("node_type")
        if node_type in ("reforge_step", "reforge_attempt", "reforge_evaluator", "reforge_winner"):
            meta = extract_metadata(entry)
            phase_name = meta.get("phase_name", "unknown")
            step = meta.get("reforge_step", 1)

            if phase_name not in reforge_by_phase:
                reforge_by_phase[phase_name] = {}
            if step not in reforge_by_phase[phase_name]:
                reforge_by_phase[phase_name][step] = {
                    "step_entry": None,
                    "attempts": [],
                    "evaluator": None,
                    "winner": None
                }

            if node_type == "reforge_step":
                reforge_by_phase[phase_name][step]["step_entry"] = entry
            elif node_type == "reforge_attempt":
                reforge_by_phase[phase_name][step]["attempts"].append(entry)
            elif node_type == "reforge_evaluator":
                reforge_by_phase[phase_name][step]["evaluator"] = entry
            elif node_type == "reforge_winner":
                reforge_by_phase[phase_name][step]["winner"] = entry

    # Group wards by phase (using parent_id to trace to phase)
    wards_by_phase: Dict[str, Dict[str, List[Dict]]] = {}  # phase_name -> {pre: [...], post: [...]}
    phase_trace_to_name = {pe.get("trace_id"): pe.get("content", "").replace("Phase: ", "") for pe in phase_entries}

    for ward in ward_entries:
        ward_meta = extract_metadata(ward)
        parent_id = ward.get("parent_id")
        phase_name = phase_trace_to_name.get(parent_id, "unknown")

        if phase_name not in wards_by_phase:
            wards_by_phase[phase_name] = {"pre": [], "post": []}

        ward_type = ward_meta.get("ward_type", "")
        if ward_type == "pre":
            wards_by_phase[phase_name]["pre"].append(ward)
        elif ward_type == "post":
            wards_by_phase[phase_name]["post"].append(ward)

    # Determine phase completion status
    # A phase is complete if it appears in lineage
    completed_phases = {item.get("phase") for item in echo.lineage}

    # Check which phases have any activity (messages logged)
    active_phases = set()
    for entry in history:
        meta = extract_metadata(entry)
        phase_name = meta.get("phase_name")
        if phase_name:
            active_phases.add(phase_name)

    def get_phase_status(phase_name: str) -> str:
        """Get status icon for a phase."""
        if phase_name in completed_phases:
            return "+"  # Completed
        elif phase_name in active_phases:
            return ">"  # In progress (has activity but not in lineage yet)
        else:
            return "-"  # Pending

    # Collect cascade-level soundings entries
    cascade_soundings_start = None
    cascade_sounding_attempts = []
    cascade_evaluator = None
    cascade_soundings_result = None

    for entry in history:
        node_type = entry.get("node_type")
        if node_type == "cascade_soundings":
            cascade_soundings_start = entry
        elif node_type == "cascade_sounding_attempt":
            cascade_sounding_attempts.append(entry)
        elif node_type == "cascade_evaluator":
            cascade_evaluator = entry
        elif node_type == "cascade_soundings_result":
            cascade_soundings_result = entry

    # Render cascade-level soundings if present (appears before phases)
    cascade_soundings_node_id = None
    if cascade_soundings_start and cascade_sounding_attempts:
        cs_meta = extract_metadata(cascade_soundings_start)
        factor = cs_meta.get("factor", len(cascade_sounding_attempts))
        cs_id = "n_cascade_soundings"

        lines.append(f'        subgraph {cs_id}["Cascade Soundings ({factor} executions)"]')
        lines.append("        direction TB")

        # Render attempts as boxes with sub-session links
        lines.append(f'            subgraph {cs_id}_attempts["Parallel Cascade Executions"]')
        lines.append("            direction LR")

        attempt_ids = []
        winner_index = None
        if cascade_soundings_result:
            result_meta = extract_metadata(cascade_soundings_result)
            winner_index = result_meta.get("winner_index")

        for attempt in sorted(cascade_sounding_attempts, key=lambda a: extract_metadata(a).get("sounding_index", 0)):
            a_meta = extract_metadata(attempt)
            idx = a_meta.get("sounding_index", 0)
            sub_session = a_meta.get("sub_session_id", f"sounding_{idx}")
            is_winner = (winner_index is not None and idx == winner_index)

            attempt_id = f"{cs_id}_a{idx}"
            attempt_ids.append(attempt_id)

            content_preview = sanitize_label(attempt.get("content", ""), 20)
            if is_winner:
                label = f"#{idx+1} ✓: {content_preview}" if content_preview else f"#{idx+1} ✓"
                lines.append(f'                {attempt_id}["{label}"]')
                lines.append(f"                class {attempt_id} winner")
            else:
                label = f"#{idx+1}: {content_preview}" if content_preview else f"#{idx+1}"
                lines.append(f'                {attempt_id}["{label}"]')
                lines.append(f"                class {attempt_id} loser")

        lines.append("            end")

        # Add evaluator node
        eval_id = f"{cs_id}_eval"
        if cascade_evaluator:
            eval_preview = sanitize_label(cascade_evaluator.get("content", ""), 35)
            lines.append(f'            {eval_id}{{"Eval: {eval_preview}"}}')
        else:
            lines.append(f'            {eval_id}{{"Evaluate"}}')
        lines.append(f"            class {eval_id} evaluator")

        # Connect attempts to evaluator
        for aid in attempt_ids:
            lines.append(f"            {aid} --> {eval_id}")

        # Add winner output
        if winner_index is not None:
            winner_out = f"{cs_id}_winner"
            lines.append(f'            {winner_out}(["* Cascade #{winner_index+1} selected"])')
            lines.append(f"            class {winner_out} winner")
            lines.append(f"            {eval_id} ==> {winner_out}")
            cascade_soundings_node_id = winner_out
        else:
            cascade_soundings_node_id = eval_id

        lines.append("        end")
        lines.append(f"        class {cs_id} soundings_group")

    # Render phases and their connections
    phase_ids = []
    phase_id_map = {}

    for i, phase_entry in enumerate(phase_entries):
        content = phase_entry.get("content", "")
        phase_name = content.replace("Phase: ", "") if content.startswith("Phase: ") else content
        phase_id = safe_id(phase_entry.get("trace_id", f"phase_{i}"))
        phase_ids.append(phase_id)
        phase_id_map[phase_name] = phase_id

        # Get phase status
        status_icon = get_phase_status(phase_name)

        meta = extract_metadata(phase_entry)
        has_soundings = meta.get("has_soundings", False) or phase_name in soundings_by_phase
        has_wards = meta.get("has_wards", False) or phase_name in wards_by_phase
        phase_wards = wards_by_phase.get(phase_name, {"pre": [], "post": []})

        if has_soundings and phase_name in soundings_by_phase:
            # Render soundings group
            lines.append(f'        subgraph {phase_id}["{status_icon} {sanitize_label(phase_name, 30)}"]')
            lines.append("        direction TB")

            # Get sounding attempts for this phase
            attempts = soundings_by_phase[phase_name]
            winner_index = None

            # Build attempts info with content
            attempts_info = {}
            for sa in attempts:
                sa_meta = extract_metadata(sa)
                idx = sa_meta.get("sounding_index", 0)
                is_winner = sa_meta.get("is_winner", False)
                content = sa.get("content", "")
                attempts_info[idx] = {"is_winner": is_winner, "content": content}
                if is_winner:
                    winner_index = idx

            # Get evaluator content if available
            eval_entry = evaluators_by_phase.get(phase_name, {})
            eval_content = eval_entry.get("content", "") if eval_entry else ""

            # Render parallel attempts
            if attempts_info:
                lines.append(f'            subgraph {phase_id}_attempts["Attempts"]')
                lines.append("            direction LR")

                attempt_ids = []
                for idx in sorted(attempts_info.keys()):
                    info = attempts_info[idx]
                    attempt_id = f"{phase_id}_a{idx}"
                    attempt_ids.append(attempt_id)

                    # Build label with content preview
                    content_preview = sanitize_label(info["content"], 25) if info["content"] else ""
                    if info["is_winner"]:
                        label = f"#{idx+1} ✓"
                        if content_preview:
                            label = f"#{idx+1} ✓: {content_preview}"
                        lines.append(f'                {attempt_id}["{label}"]')
                        lines.append(f"                class {attempt_id} winner")
                    else:
                        label = f"#{idx+1}"
                        if content_preview:
                            label = f"#{idx+1}: {content_preview}"
                        lines.append(f'                {attempt_id}["{label}"]')
                        lines.append(f"                class {attempt_id} loser")

                lines.append("            end")

                # Add evaluator node with content preview
                eval_id = f"{phase_id}_eval"
                if eval_content:
                    eval_preview = sanitize_label(eval_content, 35)
                    lines.append(f'            {eval_id}{{"Eval: {eval_preview}"}}')
                else:
                    lines.append(f'            {eval_id}{{"Evaluate"}}')
                lines.append(f"            class {eval_id} evaluator")

                # Connect attempts to evaluator
                for aid in attempt_ids:
                    lines.append(f"            {aid} --> {eval_id}")

                # Add winner output
                last_node_id = eval_id
                if winner_index is not None:
                    winner_out = f"{phase_id}_winner"
                    winner_content = attempts_info.get(winner_index, {}).get("content", "")
                    if winner_content:
                        winner_preview = sanitize_label(winner_content, 30)
                        lines.append(f'            {winner_out}(["* #{winner_index+1}: {winner_preview}"])')
                    else:
                        lines.append(f'            {winner_out}(["* Winner #{winner_index+1}"])')
                    lines.append(f"            class {winner_out} winner")
                    lines.append(f"            {eval_id} ==> {winner_out}")
                    last_node_id = winner_out

                # Render reforge steps if present
                phase_reforge = reforge_by_phase.get(phase_name, {})
                if phase_reforge:
                    for step_num in sorted(phase_reforge.keys()):
                        step_data = phase_reforge[step_num]
                        rf_step_entry = step_data.get("step_entry")
                        rf_attempts = step_data.get("attempts", [])
                        rf_evaluator = step_data.get("evaluator")
                        rf_winner = step_data.get("winner")

                        # Render if we have any reforge data (step entry, attempts, winner, or evaluator)
                        if rf_step_entry or rf_attempts or rf_evaluator or rf_winner:
                            # Create reforge step subgraph
                            rf_step_id = f"{phase_id}_rf{step_num}"
                            lines.append(f'            subgraph {rf_step_id}["Reforge Step {step_num}"]')
                            lines.append("            direction TB")

                            rf_attempt_ids = []
                            rf_winner_index = None
                            if rf_winner:
                                rf_winner_meta = extract_metadata(rf_winner)
                                rf_winner_index = rf_winner_meta.get("winner_index")

                            # Render refinement attempts if we have them
                            if rf_attempts:
                                lines.append(f'                subgraph {rf_step_id}_attempts["Refinements"]')
                                lines.append("                direction LR")

                                for rf_att in sorted(rf_attempts, key=lambda a: extract_metadata(a).get("attempt_index", 0)):
                                    rf_att_meta = extract_metadata(rf_att)
                                    rf_idx = rf_att_meta.get("attempt_index", 0)
                                    rf_is_winner = (rf_winner_index is not None and rf_idx == rf_winner_index)

                                    rf_att_id = f"{rf_step_id}_a{rf_idx}"
                                    rf_attempt_ids.append(rf_att_id)

                                    rf_content = rf_att.get("content", "")
                                    rf_preview = sanitize_label(rf_content, 20) if rf_content else ""

                                    if rf_is_winner:
                                        rf_label = f"R{rf_idx+1} ✓: {rf_preview}" if rf_preview else f"R{rf_idx+1} ✓"
                                        lines.append(f'                    {rf_att_id}["{rf_label}"]')
                                        lines.append(f"                    class {rf_att_id} winner")
                                    else:
                                        rf_label = f"R{rf_idx+1}: {rf_preview}" if rf_preview else f"R{rf_idx+1}"
                                        lines.append(f'                    {rf_att_id}["{rf_label}"]')
                                        lines.append(f"                    class {rf_att_id} loser")

                                lines.append("                end")

                            # Add reforge evaluator
                            rf_eval_id = f"{rf_step_id}_eval"
                            if rf_evaluator:
                                rf_eval_content = rf_evaluator.get("content", "")
                                rf_eval_preview = sanitize_label(rf_eval_content, 30)
                                lines.append(f'                {rf_eval_id}{{"Eval: {rf_eval_preview}"}}')
                            else:
                                lines.append(f'                {rf_eval_id}{{"Evaluate"}}')
                            lines.append(f"                class {rf_eval_id} evaluator")

                            # Connect refinement attempts to evaluator
                            for rf_aid in rf_attempt_ids:
                                lines.append(f"                {rf_aid} --> {rf_eval_id}")

                            # Add step winner
                            if rf_winner_index is not None:
                                rf_step_winner = f"{rf_step_id}_winner"
                                lines.append(f'                {rf_step_winner}(["* R{rf_winner_index+1}"])')
                                lines.append(f"                class {rf_step_winner} winner")
                                lines.append(f"                {rf_eval_id} ==> {rf_step_winner}")

                            lines.append("            end")
                            lines.append(f"            class {rf_step_id} reforge_group")

                            # Connect from previous step/winner to this reforge step
                            lines.append(f"            {last_node_id} --> {rf_step_id}")
                            last_node_id = rf_step_winner if rf_winner_index is not None else rf_eval_id

            lines.append("        end")
            lines.append(f"        class {phase_id} soundings_group")

        elif phase_wards["pre"] or phase_wards["post"]:
            # Phase with wards - render as subgraph with checkpoints
            lines.append(f'        subgraph {phase_id}["{status_icon} {sanitize_label(phase_name, 30)}"]')
            lines.append("        direction TB")

            internal_nodes = []

            # Pre-wards
            for j, ward in enumerate(phase_wards["pre"]):
                ward_meta = extract_metadata(ward)
                validator = ward_meta.get("validator", "validator")
                valid = ward_meta.get("valid", True)
                mode = ward_meta.get("mode", "blocking")

                ward_id = f"{phase_id}_pre{j}"
                internal_nodes.append(ward_id)

                mode_label = "[B]" if mode == "blocking" else ("[R]" if mode == "retry" else "[A]")
                status_mark = "+" if valid else "x"
                label = f"{mode_label} {validator} {status_mark}"

                lines.append(f'            {ward_id}(["{sanitize_label(label, 30)}"])')
                style = "ward_pre" if valid else "ward_fail"
                lines.append(f"            class {ward_id} {style}")

            # Main phase execution node
            exec_id = f"{phase_id}_exec"
            internal_nodes.append(exec_id)
            lines.append(f'            {exec_id}["{sanitize_label(phase_name, 25)}"]')
            lines.append(f"            class {exec_id} phase")

            # Post-wards
            for j, ward in enumerate(phase_wards["post"]):
                ward_meta = extract_metadata(ward)
                validator = ward_meta.get("validator", "validator")
                valid = ward_meta.get("valid", True)
                mode = ward_meta.get("mode", "blocking")

                ward_id = f"{phase_id}_post{j}"
                internal_nodes.append(ward_id)

                mode_label = "[B]" if mode == "blocking" else ("[R]" if mode == "retry" else "[A]")
                status_mark = "+" if valid else "x"
                label = f"{mode_label} {validator} {status_mark}"

                lines.append(f'            {ward_id}(["{sanitize_label(label, 30)}"])')
                style = "ward_post" if valid else "ward_fail"
                lines.append(f"            class {ward_id} {style}")

            # Connect internal nodes sequentially
            for k in range(len(internal_nodes) - 1):
                lines.append(f"            {internal_nodes[k]} --> {internal_nodes[k+1]}")

            lines.append("        end")
            lines.append(f"        class {phase_id} phase")

        else:
            # Phase with messages - render as subgraph containing message nodes
            phase_trace_id = phase_entry.get("trace_id")

            # Collect all turn traces under this phase
            turn_traces = set()
            for entry in history:
                if entry.get("parent_id") == phase_trace_id and entry.get("node_type") == "turn":
                    turn_traces.add(entry.get("trace_id"))

            # Check for sub-cascades under this phase
            # Sub-cascades are stored as sub_echo entries after merge
            sub_cascade_entries = []
            phase_meta = extract_metadata(phase_entry)
            if phase_meta.get('has_sub_cascades'):
                # Look for sub_echo entries that contain cascade entries for this phase
                for sub_echo in sub_echoes:
                    sub_history = sub_echo.get("history", [])
                    # Find the cascade entry in the sub_echo's history
                    for entry in sub_history:
                        if entry.get("node_type") == "cascade":
                            sub_cascade_entries.append({
                                "entry": entry,
                                "history": sub_history
                            })
                            break  # Only one cascade entry per sub_echo

            # Collect tool traces under turn traces
            tool_traces = set()
            for entry in history:
                if entry.get("parent_id") in turn_traces and entry.get("node_type") == "tool":
                    tool_traces.add(entry.get("trace_id"))

            # Collect messages belonging to this phase
            phase_messages = []
            for entry in history:
                entry_parent = entry.get("parent_id")
                entry_type = entry.get("node_type", "")
                entry_content = entry.get("content", "")

                # Direct children of phase (system, user, injection, validation, validation_retry)
                if entry_parent == phase_trace_id:
                    if entry_type in ("system", "user", "injection", "validation", "schema_validation", "validation_retry"):
                        phase_messages.append(entry)
                # Children of turn traces (turn_output, turn_input, follow_up)
                elif entry_parent in turn_traces:
                    if entry_type == "turn_output":
                        # Skip empty turn_output (tool call without text response)
                        if entry_content and entry_content.strip():
                            phase_messages.append(entry)
                    elif entry_type in ("turn_input", "follow_up"):
                        phase_messages.append(entry)
                # Tool results under tool traces
                elif entry_parent in tool_traces:
                    if entry_type == "tool_result":
                        phase_messages.append(entry)
                # Grandchildren (tool results under tool traces under turns) - fallback
                elif entry_parent and entry_parent in nodes_map:
                    grandparent_id = nodes_map[entry_parent].parent_id
                    if grandparent_id in turn_traces:
                        if entry_type in ("tool_result", "injection"):
                            phase_messages.append(entry)

            # Check for quartermaster result for this phase
            qm_entry = quartermaster_by_phase.get(phase_name)

            # If we have messages, sub-cascades, or quartermaster, render as subgraph
            if phase_messages or sub_cascade_entries or qm_entry:
                lines.append(f'        subgraph {phase_id}["{status_icon} {sanitize_label(phase_name, 32)}"]')
                lines.append("        direction TB")

                all_node_ids = []

                # Render quartermaster decision node first (if present)
                if qm_entry:
                    qm_id = f"{phase_id}_qm"
                    all_node_ids.append(qm_id)
                    qm_content = qm_entry.get("content", "")
                    qm_meta = extract_metadata(qm_entry)
                    selected_tackle = qm_meta.get("selected_tackle", [])
                    # Format as comma-separated list of tools
                    if selected_tackle:
                        tools_preview = ", ".join(selected_tackle[:3])
                        if len(selected_tackle) > 3:
                            tools_preview += f" +{len(selected_tackle) - 3}"
                        qm_label = f"Tackle: {tools_preview}"
                    else:
                        qm_label = "No tools"
                    lines.append(f'            {qm_id}{{"{sanitize_label(qm_label, 35)}"}}')
                    lines.append(f"            class {qm_id} evaluator")

                # Render phase messages
                for j, msg in enumerate(phase_messages):
                    msg_id = f"{phase_id}_m{j}"
                    all_node_ids.append(msg_id)

                    msg_type = msg.get("node_type", "msg")
                    msg_role = msg.get("role", "")
                    msg_content = msg.get("content", "")

                    # Determine icon and style based on type
                    if msg_type == "system" or msg_role == "system":
                        icon = "SYS"
                        style = "system"
                        preview = sanitize_label(msg_content, 30)
                        label = f"{icon}: {preview}" if preview else icon
                    elif msg_type in ("user", "turn_input") or msg_role == "user":
                        icon = "USE"
                        style = "user"
                        preview = sanitize_label(msg_content, 30)
                        label = f"{icon}: {preview}" if preview else icon
                    elif msg_type in ("turn_output", "follow_up") or msg_role == "assistant":
                        icon = "OUT"
                        style = "agent"
                        preview = sanitize_label(msg_content, 35)
                        label = f"{icon}: {preview}"
                    elif msg_type == "tool_result":
                        icon = "TOOL"
                        style = "tool"
                        preview = sanitize_label(msg_content, 25)
                        label = f"{icon}: {preview}" if preview else "Tool"
                    elif msg_type == "injection":
                        icon = "INJ"
                        style = "user"
                        preview = sanitize_label(msg_content, 25)
                        label = f"{icon}: {preview}" if preview else "Inject"
                    elif msg_type in ("validation", "schema_validation"):
                        # Validation result - render as diamond decision node
                        msg_meta = extract_metadata(msg)
                        is_valid = msg_meta.get("valid", False)
                        validator = msg_meta.get("validator", "schema")
                        status_mark = "+" if is_valid else "x"
                        style = "winner" if is_valid else "ward_fail"
                        preview = sanitize_label(msg_content, 30)
                        label = f"Valid {status_mark}: {preview}"
                        # Use diamond shape for validation
                        lines.append(f'            {msg_id}{{"{label}"}}')
                        lines.append(f"            class {msg_id} {style}")
                        continue  # Skip normal rendering below (msg_id already in all_node_ids)
                    elif msg_type == "validation_retry":
                        icon = "RETRY"
                        style = "user"
                        preview = sanitize_label(msg_content, 30)
                        label = f"{icon}: {preview}" if preview else "Retry"
                    else:
                        icon = "•"
                        style = "phase"
                        label = f"{icon} {msg_type}"

                    lines.append(f'            {msg_id}["{label}"]')
                    lines.append(f"            class {msg_id} {style}")

                # Render sub-cascades as nested subgraphs
                for sc_idx, sc_data in enumerate(sub_cascade_entries):
                    sc_entry = sc_data.get("entry", {})
                    sc_history = sc_data.get("history", [])
                    sc_trace_id = sc_entry.get("trace_id")
                    sc_content = sc_entry.get("content", "")
                    sc_name = sc_content.replace("Cascade: ", "") if sc_content.startswith("Cascade: ") else sc_content
                    sc_id = f"{phase_id}_sc{sc_idx}"
                    all_node_ids.append(sc_id)

                    # Find phases under this sub-cascade from its history
                    sc_phase_entries = []
                    for entry in sc_history:
                        if entry.get("parent_id") == sc_trace_id and entry.get("node_type") == "phase":
                            sc_phase_entries.append(entry)

                    lines.append(f'            subgraph {sc_id}["Sub: {sanitize_label(sc_name, 25)}"]')
                    lines.append("            direction TB")

                    sc_phase_ids = []
                    for sp_idx, sp_entry in enumerate(sc_phase_entries):
                        sp_trace_id = sp_entry.get("trace_id")
                        sp_content = sp_entry.get("content", "")
                        sp_name = sp_content.replace("Phase: ", "") if sp_content.startswith("Phase: ") else sp_content
                        sp_id = f"{sc_id}_p{sp_idx}"
                        sc_phase_ids.append(sp_id)

                        # Find turn traces for this sub-phase (from sub-cascade's history)
                        sp_turn_traces = set()
                        for entry in sc_history:
                            if entry.get("parent_id") == sp_trace_id and entry.get("node_type") == "turn":
                                sp_turn_traces.add(entry.get("trace_id"))

                        # Collect messages for this sub-phase (from sub-cascade's history)
                        sp_messages = []
                        for entry in sc_history:
                            entry_parent = entry.get("parent_id")
                            entry_type = entry.get("node_type", "")

                            if entry_parent == sp_trace_id:
                                if entry_type in ("system", "user", "injection"):
                                    sp_messages.append(entry)
                            elif entry_parent in sp_turn_traces:
                                if entry_type in ("turn_output", "turn_input", "tool_result", "follow_up"):
                                    sp_messages.append(entry)

                        if sp_messages:
                            lines.append(f'                subgraph {sp_id}["{sanitize_label(sp_name, 20)}"]')
                            lines.append("                direction TB")

                            sp_msg_ids = []
                            for m_idx, sp_msg in enumerate(sp_messages):
                                sp_msg_id = f"{sp_id}_m{m_idx}"
                                sp_msg_ids.append(sp_msg_id)

                                msg_type = sp_msg.get("node_type", "msg")
                                msg_role = sp_msg.get("role", "")
                                msg_content = sp_msg.get("content", "")

                                if msg_type == "system" or msg_role == "system":
                                    icon = "SYS"
                                    style = "system"
                                    preview = sanitize_label(msg_content, 20)
                                    label = f"{icon}: {preview}" if preview else icon
                                elif msg_type in ("user", "turn_input") or msg_role == "user":
                                    icon = "USE"
                                    style = "user"
                                    preview = sanitize_label(msg_content, 20)
                                    label = f"{icon}: {preview}" if preview else icon
                                elif msg_type in ("turn_output", "follow_up") or msg_role == "assistant":
                                    icon = "OUT"
                                    style = "agent"
                                    preview = sanitize_label(msg_content, 25)
                                    label = f"{icon}: {preview}"
                                else:
                                    icon = "-"
                                    style = "phase"
                                    label = f"{icon} {msg_type}"

                                lines.append(f'                    {sp_msg_id}["{label}"]')
                                lines.append(f"                    class {sp_msg_id} {style}")

                            # Connect sub-phase messages
                            for k in range(len(sp_msg_ids) - 1):
                                lines.append(f"                    {sp_msg_ids[k]} --> {sp_msg_ids[k+1]}")

                            lines.append("                end")
                            lines.append(f"                class {sp_id} phase")
                        else:
                            lines.append(f'                {sp_id}["{sanitize_label(sp_name, 20)}"]')
                            lines.append(f"                class {sp_id} phase")

                    # Connect sub-cascade phases
                    for k in range(len(sc_phase_ids) - 1):
                        lines.append(f"                {sc_phase_ids[k]} --> {sc_phase_ids[k+1]}")

                    lines.append("            end")
                    lines.append(f"            class {sc_id} sub_cascade")

                # Connect all nodes (messages + sub-cascades) sequentially
                for k in range(len(all_node_ids) - 1):
                    lines.append(f"            {all_node_ids[k]} --> {all_node_ids[k+1]}")

                lines.append("        end")
                lines.append(f"        class {phase_id} phase")
            else:
                # No messages found, just render phase name with status
                lines.append(f'        {phase_id}["{status_icon} {sanitize_label(phase_name, 35)}"]')
                lines.append(f"        class {phase_id} phase")

    # If we have cascade soundings, connect the winner to the first phase
    if cascade_soundings_node_id and phase_ids:
        lines.append(f"        {cascade_soundings_node_id} ==> {phase_ids[0]}")

    # Connect phases using handoffs from metadata, or in order
    for i, phase_entry in enumerate(phase_entries):
        meta = extract_metadata(phase_entry)
        handoffs = meta.get("handoffs", [])
        current_id = phase_ids[i]

        if handoffs:
            # Use explicit handoffs
            for target in handoffs:
                if target in phase_id_map:
                    lines.append(f"        {current_id} --> {phase_id_map[target]}")
        elif i + 1 < len(phase_ids):
            # Default: connect to next phase
            lines.append(f"        {current_id} --> {phase_ids[i+1]}")

    # Note: Cascade container removed for cleaner visualization without outer border
    # The structural diagram focuses on flow; use logs/lineage for content details.

    # Return the mermaid diagram as a string
    return "\n".join(lines)


def generate_state_diagram_string(echo: Echo) -> str:
    """
    Generate a Mermaid state diagram string from Echo history.

    State diagrams provide a compact, semantic representation with encapsulated complexity:
    - Phases are composite states that contain their internal complexity
    - Fork/join pseudo-states show parallel execution (soundings)
    - Sub-cascades appear as nested composite states within parent phases
    - Wards chain as sequential validation steps
    - Reforge chains sequentially after soundings
    - Dynamic routing shown with taken (✓) vs available (○) paths
    - Blocked phases terminate at error states (⛔)
    - Live running state shows currently executing phase (▶)
    - Mutation strategies shown on sounding attempts

    Visual language:
    - ▶ running (currently executing phase) + green glow border
    - ✓ completed, ○ pending, ⛔ blocked
    - 🔱 soundings (parallel attempts)
    - 🔨 reforge (iterative refinement)
    - 📦 sub-cascade (nested workflow)
    - 🛡️ blocking ward, 🔄 retry ward, ℹ️ advisory ward
    - ⚖️ evaluator, ★ winner
    - 🔧 tool usage
    - 🔄N retry count (N retries occurred)
    - 📝key1,key2 state keys set (via set_state)

    CSS Classes (applied via Mermaid classDef):
    - running: thick green border (4px), green fill - for currently executing phase
    - blocked: red border, red fill - for blocked phases

    Sounding labels:
    - [baseline] = first attempt, no mutation
    - [mutation...] = mutation strategy applied (truncated)
    - ✓ = winner

    Routing transitions:
    - "✓ route" = taken path (agent chose this)
    - "○ available" = available but not taken
    - "⛔ validator" = blocked by validator

    Returns the mermaid state diagram as a string.
    """
    history, sub_echoes = flatten_history(echo.history)

    # Helper to create safe state IDs
    def sid(name: str) -> str:
        # Replace problematic characters and ensure valid ID
        s = name.replace("-", "_").replace(" ", "_").replace(".", "_")
        s = s.replace("(", "").replace(")", "").replace(":", "").replace("/", "_")
        return s

    # Helper to get status icon
    def status_icon(phase_name: str, completed_phases: set) -> str:
        if is_running and phase_name == running_phase:
            return "▶"  # Currently running
        elif phase_name in completed_phases:
            return "✓"  # Completed
        else:
            return "○"  # Pending

    # Collect data structures
    completed_phases = {item.get("phase") for item in echo.lineage}

    # Extract routing choices (which phase dynamically routed to which target)
    routing_choices = extract_routing_choices(echo.lineage)

    # Extract ward retry information
    ward_retries = extract_ward_retries(history)

    # Extract phases blocked by blocking wards
    blocked_phases = extract_blocked_phases(history)

    # Extract state changes (set_state calls per phase)
    state_changes = extract_state_changes(history)

    # Extract sounding mutations
    sounding_mutations = extract_sounding_mutations(history)

    # Extract validation retries (loop_until / max_attempts > 1)
    validation_retries = extract_validation_retries(history)

    # Extract errors per phase
    errors_by_phase = extract_errors(history)

    # Extract Quartermaster tool selections
    qm_selections = extract_quartermaster_selections(history)

    # Extract detailed turn info per phase
    turns_detail = extract_turns(history)

    # Get live session state for running indicator
    live_state = get_live_session_state(echo.session_id)
    running_phase = None
    is_running = False
    phase_progress = None
    progress_indicator = ""
    running_internal_node = None

    if live_state:
        is_running = live_state.get("status") == "running"
        running_phase = live_state.get("current_phase")
        phase_progress = live_state.get("phase_progress")

        # Generate compact progress indicator from phase_progress
        if phase_progress and is_running:
            progress_indicator = format_phase_progress_indicator(phase_progress)

    # Build lookup maps
    sub_cascade_trace_ids = set()
    sub_cascades_by_phase: Dict[str, List[Dict]] = {}  # phase_trace_id -> [sub_echo_data]

    for sub_echo in sub_echoes:
        sub_history = sub_echo.get("history", [])
        for entry in sub_history:
            if entry.get("node_type") == "cascade":
                sub_cascade_trace_ids.add(entry.get("trace_id"))

    # Collect all entries by type
    phase_entries = []
    soundings_by_phase: Dict[str, List[Dict]] = {}
    reforge_by_phase: Dict[str, Dict[int, Dict]] = {}
    wards_by_phase: Dict[str, Dict[str, List[Dict]]] = {}
    tools_by_phase: Dict[str, List[str]] = {}
    turns_by_phase: Dict[str, int] = {}
    handoffs_by_phase: Dict[str, List[str]] = {}  # phase_name -> list of available handoff targets
    cascade_sounding_attempts = []
    cascade_soundings_result = None

    for entry in history:
        node_type = entry.get("node_type", "")
        meta = extract_metadata(entry)

        if node_type == "phase":
            # Only collect top-level phases (not sub-cascade phases)
            if entry.get("parent_id") not in sub_cascade_trace_ids:
                phase_entries.append(entry)
                # Also capture handoffs for this phase
                content = entry.get("content", "")
                phase_name = content.replace("Phase: ", "") if content.startswith("Phase: ") else content
                handoffs = meta.get("handoffs", [])
                if handoffs:
                    handoffs_by_phase[phase_name] = handoffs

        elif node_type == "sounding_attempt":
            phase_name = meta.get("phase_name", "unknown")
            if phase_name not in soundings_by_phase:
                soundings_by_phase[phase_name] = []
            soundings_by_phase[phase_name].append(entry)

        elif node_type in ("reforge_step", "reforge_attempt", "reforge_evaluator", "reforge_winner"):
            phase_name = meta.get("phase_name", "unknown")
            step = meta.get("reforge_step", 1)
            if phase_name not in reforge_by_phase:
                reforge_by_phase[phase_name] = {}
            if step not in reforge_by_phase[phase_name]:
                reforge_by_phase[phase_name][step] = {"attempts": [], "winner": None}

            if node_type == "reforge_attempt":
                reforge_by_phase[phase_name][step]["attempts"].append(entry)
            elif node_type == "reforge_winner":
                reforge_by_phase[phase_name][step]["winner"] = entry

        elif node_type in ("pre_ward", "post_ward"):
            phase_name = meta.get("phase_name", "unknown")
            if phase_name not in wards_by_phase:
                wards_by_phase[phase_name] = {"pre": [], "post": []}
            ward_type = meta.get("ward_type", "")
            if ward_type in ("pre", "post"):
                wards_by_phase[phase_name][ward_type].append(entry)

        elif node_type == "tool_result":
            phase_name = meta.get("phase_name", "unknown")
            if phase_name not in tools_by_phase:
                tools_by_phase[phase_name] = []
            # Extract tool name from metadata (preferred) or content
            tool_name = meta.get("tool_name")
            if not tool_name:
                # Try to extract from content format "Tool Result (tool_name):"
                content = entry.get("content", "")
                if "Tool Result (" in content:
                    import re
                    match = re.search(r"Tool Result \((\w+)\)", content)
                    if match:
                        tool_name = match.group(1)
            if tool_name and tool_name not in tools_by_phase[phase_name]:
                tools_by_phase[phase_name].append(tool_name)

        elif node_type == "turn":
            phase_name = meta.get("phase_name", "unknown")
            turns_by_phase[phase_name] = turns_by_phase.get(phase_name, 0) + 1

        elif node_type == "cascade_sounding_attempt":
            cascade_sounding_attempts.append(entry)

        elif node_type == "cascade_soundings_result":
            cascade_soundings_result = entry

    # Map phase trace_id to phase data for ward lookup
    phase_trace_to_name = {}
    phase_trace_to_entry = {}
    for pe in phase_entries:
        content = pe.get("content", "")
        name = content.replace("Phase: ", "") if content.startswith("Phase: ") else content
        phase_trace_to_name[pe.get("trace_id")] = name
        phase_trace_to_entry[pe.get("trace_id")] = pe

    # Re-process wards with correct phase names (using parent_id lookup)
    wards_by_phase = {}
    for entry in history:
        node_type = entry.get("node_type", "")
        if node_type in ("pre_ward", "post_ward"):
            parent_id = entry.get("parent_id")
            phase_name = phase_trace_to_name.get(parent_id, "unknown")
            meta = extract_metadata(entry)
            if phase_name not in wards_by_phase:
                wards_by_phase[phase_name] = {"pre": [], "post": []}
            ward_type = meta.get("ward_type", "")
            if ward_type in ("pre", "post"):
                wards_by_phase[phase_name][ward_type].append(entry)

    # Map sub-cascades to their parent phases
    sub_cascades_by_phase_name: Dict[str, List[Dict]] = {}
    for sub_echo in sub_echoes:
        sub_history = sub_echo.get("history", [])
        # Find cascade entry and its phases
        cascade_entry = None
        sub_phases = []
        for entry in sub_history:
            if entry.get("node_type") == "cascade":
                cascade_entry = entry
            elif entry.get("node_type") == "phase":
                sub_phases.append(entry)

        if cascade_entry:
            # Find which parent phase this belongs to
            # Look for has_sub_cascades metadata in phase entries
            for pe in phase_entries:
                pe_meta = extract_metadata(pe)
                if pe_meta.get("has_sub_cascades"):
                    phase_name = phase_trace_to_name.get(pe.get("trace_id"), "unknown")
                    if phase_name not in sub_cascades_by_phase_name:
                        sub_cascades_by_phase_name[phase_name] = []
                    sub_cascades_by_phase_name[phase_name].append({
                        "cascade": cascade_entry,
                        "phases": sub_phases,
                        "sub_echo": sub_echo.get("sub_echo", "sub")
                    })

    # Sort phases by lineage order
    phase_order = [item.get("phase") for item in echo.lineage]
    if phase_order:
        def phase_sort_key(entry):
            content = entry.get("content", "")
            name = content.replace("Phase: ", "") if content.startswith("Phase: ") else content
            try:
                return phase_order.index(name)
            except ValueError:
                return 999
        phase_entries.sort(key=phase_sort_key)

    # =========================================================================
    # BUILD THE STATE DIAGRAM
    # =========================================================================

    lines = ["stateDiagram-v2"]
    lines.append("    direction LR")
    lines.append("")

    # Add style definitions for running states (thick border, glow effect via stroke)
    # Mermaid state diagrams support classDef for styling
    lines.append("    %% Style for running states - thick green border for visibility")
    lines.append("    classDef running fill:#1a2a1a,stroke:#00ff00,stroke-width:4px,color:#00ff00")
    lines.append("    classDef blocked fill:#2a1a1a,stroke:#ff4444,stroke-width:3px,color:#ff4444")
    lines.append("")

    # Track which phase IDs need the running class applied
    running_phase_ids = []

    # Cascade-level soundings (if present)
    first_state = None
    if cascade_sounding_attempts:
        cs_meta = extract_metadata(cascade_soundings_result) if cascade_soundings_result else {}
        winner_index = cs_meta.get("winner_index")
        factor = len(cascade_sounding_attempts)

        lines.append("    state cascade_soundings {")
        lines.append("        cs_label : 🔱 Cascade Soundings")
        lines.append("        [*] --> cs_fork")
        lines.append("        state cs_fork <<fork>>")

        for attempt in sorted(cascade_sounding_attempts, key=lambda a: extract_metadata(a).get("sounding_index", 0)):
            a_meta = extract_metadata(attempt)
            idx = a_meta.get("sounding_index", 0)
            is_winner = (winner_index is not None and idx == winner_index)
            marker = " ✓" if is_winner else ""
            lines.append(f"        cs_fork --> cs_a{idx}")
            lines.append(f"        cs_a{idx} : #{idx+1}{marker}")

        lines.append("        state cs_join <<join>>")
        for i in range(factor):
            lines.append(f"        cs_a{i} --> cs_join")

        lines.append("        cs_join --> cs_eval")
        lines.append("        cs_eval : ⚖️ Evaluate")

        if winner_index is not None:
            lines.append("        cs_eval --> cs_winner")
            lines.append(f"        cs_winner : ★ #{winner_index+1}")
            lines.append("        cs_winner --> [*]")
        else:
            lines.append("        cs_eval --> [*]")

        lines.append("    }")
        lines.append("")
        first_state = "cascade_soundings"

    # =========================================================================
    # RENDER EACH PHASE
    # =========================================================================

    phase_ids = []

    for phase_entry in phase_entries:
        content = phase_entry.get("content", "")
        phase_name = content.replace("Phase: ", "") if content.startswith("Phase: ") else content
        pid = sid(phase_name)
        phase_ids.append(pid)
        phase_trace_id = phase_entry.get("trace_id")

        meta = extract_metadata(phase_entry)
        status = status_icon(phase_name, completed_phases)

        # Determine what complexity this phase has
        has_soundings = phase_name in soundings_by_phase
        has_reforge = phase_name in reforge_by_phase
        has_wards = phase_name in wards_by_phase and (wards_by_phase[phase_name]["pre"] or wards_by_phase[phase_name]["post"])
        has_sub_cascades = phase_name in sub_cascades_by_phase_name
        turn_count = turns_by_phase.get(phase_name, 0)
        has_retries = phase_name in ward_retries
        is_blocked = phase_name in blocked_phases
        has_validation_retries = phase_name in validation_retries
        has_errors = phase_name in errors_by_phase
        has_qm_selection = phase_name in qm_selections
        detailed_turns = turns_detail.get(phase_name, [])
        has_multi_turns = len(detailed_turns) > 1

        # Get tools and state changes for this phase
        phase_tools = tools_by_phase.get(phase_name, [])
        phase_state_changes = state_changes.get(phase_name, [])

        # Build annotation string for simple phases
        annotations = []
        # Show tool names (up to 3) instead of just count
        if phase_tools:
            if len(phase_tools) <= 3:
                tool_str = ",".join(phase_tools)
            else:
                tool_str = ",".join(phase_tools[:2]) + f"+{len(phase_tools)-2}"
            annotations.append(f"🔧{tool_str}")
        if turn_count > 1:
            annotations.append(f"↻{turn_count}")
        # Show ward retry count if retries occurred
        if has_retries:
            retry_count = ward_retries[phase_name].get('retry_count', 0)
            if retry_count > 0:
                annotations.append(f"🔄{retry_count}")
        # Show validation retry loop (loop_until / max_attempts) - different icon
        if has_validation_retries:
            vr = validation_retries[phase_name]
            retry_count = vr.get('retry_count', 0)
            passed = vr.get('passed', False)
            if retry_count > 0:
                # Show attempt/max format: ⟳2/3 means 2 retries out of 3 max
                max_attempts = vr.get('max_attempts', retry_count + 1)
                loop_icon = "✓" if passed else "✗"
                annotations.append(f"⟳{retry_count+1}/{max_attempts}{loop_icon}")
        # Show blocked indicator if phase was blocked
        if is_blocked:
            annotations.append("⛔")
        # Show error indicator if errors occurred
        if has_errors:
            error_count = len(errors_by_phase[phase_name])
            annotations.append(f"❌{error_count}")
        # Show Quartermaster (manifest) indicator
        if has_qm_selection:
            qm_tools = qm_selections[phase_name].get('selected_tools', [])
            annotations.append(f"🧭{len(qm_tools)}")
        # Show state changes (keys set)
        if phase_state_changes:
            state_keys = ",".join(phase_state_changes[:2])  # Limit to 2 keys
            if len(phase_state_changes) > 2:
                state_keys += f"+{len(phase_state_changes)-2}"
            annotations.append(f"📝{state_keys}")
        annotation_str = " " + " ".join(annotations) if annotations else ""

        # Override status if blocked
        if is_blocked:
            status = "⛔"

        # Track running and blocked phases for styling
        is_phase_running = is_running and phase_name == running_phase
        phase_running_internal_node = None

        if is_phase_running:
            running_phase_ids.append(pid)
            # Calculate which internal node is currently executing
            if phase_progress:
                phase_running_internal_node = get_running_internal_node_id(phase_progress, pid)

        # Decide if phase needs composite state
        # Include errors and multi-turns as reasons for composite rendering
        needs_composite = (has_soundings or has_reforge or has_wards or has_sub_cascades
                          or has_errors or has_multi_turns or has_qm_selection)

        if not needs_composite:
            # Simple phase - single state
            # Add progress indicator if this phase is currently running
            progress_str = ""
            if is_phase_running and progress_indicator:
                progress_str = f" [{progress_indicator}]"
            lines.append(f'    state "{status} {sanitize_label(phase_name, 28)}{annotation_str}{progress_str}" as {pid}')

        else:
            # Composite state
            lines.append(f"    state {pid} {{")

            # Phase label with status
            label_parts = [status, sanitize_label(phase_name, 25)]
            if has_soundings:
                factor = len(soundings_by_phase[phase_name])
                label_parts.append(f"🔱{factor}")
            if has_reforge:
                steps = len(reforge_by_phase[phase_name])
                label_parts.append(f"🔨{steps}")
            if has_sub_cascades:
                count = len(sub_cascades_by_phase_name[phase_name])
                label_parts.append(f"📦{count}")
            # Show tool names for composite phases
            if phase_tools:
                if len(phase_tools) <= 2:
                    tool_str = ",".join(phase_tools)
                else:
                    tool_str = ",".join(phase_tools[:2]) + f"+{len(phase_tools)-2}"
                label_parts.append(f"🔧{tool_str}")
            # Add ward retry annotation for composite phases
            if has_retries:
                retry_count = ward_retries[phase_name].get('retry_count', 0)
                if retry_count > 0:
                    label_parts.append(f"🔄{retry_count}")
            # Add validation retry (loop_until) annotation for composite phases
            if has_validation_retries:
                vr = validation_retries[phase_name]
                retry_count = vr.get('retry_count', 0)
                passed = vr.get('passed', False)
                if retry_count > 0:
                    max_attempts = vr.get('max_attempts', retry_count + 1)
                    loop_icon = "✓" if passed else "✗"
                    label_parts.append(f"⟳{retry_count+1}/{max_attempts}{loop_icon}")
            # Add error indicator for composite phases
            if has_errors:
                error_count = len(errors_by_phase[phase_name])
                label_parts.append(f"❌{error_count}")
            # Add Quartermaster indicator for composite phases
            if has_qm_selection:
                qm_tool_count = len(qm_selections[phase_name].get('selected_tools', []))
                label_parts.append(f"🧭{qm_tool_count}")
            # Add state changes for composite phases
            if phase_state_changes:
                state_keys = ",".join(phase_state_changes[:2])
                if len(phase_state_changes) > 2:
                    state_keys += f"+{len(phase_state_changes)-2}"
                label_parts.append(f"📝{state_keys}")

            # Add progress indicator for running composite phases
            if is_phase_running and progress_indicator:
                label_parts.append(f"[{progress_indicator}]")

            lines.append(f"        {pid}_label : {' '.join(label_parts)}")
            lines.append("")

            # Track last node for chaining
            last_node = None
            first_internal = None

            # Track internal nodes that need running style
            running_internal_nodes = []
            if phase_running_internal_node:
                running_internal_nodes.append(phase_running_internal_node)

            # QUARTERMASTER SELECTION (show which tools were auto-selected)
            if has_qm_selection:
                qm_data = qm_selections[phase_name]
                qm_tools = qm_data.get('selected_tools', [])
                if qm_tools:
                    qm_id = f"{pid}_qm"
                    # Show up to 3 tool names
                    if len(qm_tools) <= 3:
                        tools_display = ", ".join(qm_tools)
                    else:
                        tools_display = ", ".join(qm_tools[:3]) + f" +{len(qm_tools)-3}"
                    lines.append(f"        {qm_id} : 🧭 manifest: {sanitize_label(tools_display, 30)}")
                    if last_node:
                        lines.append(f"        {last_node} --> {qm_id}")
                    else:
                        first_internal = qm_id
                    last_node = qm_id

            # PRE-WARDS
            if has_wards and wards_by_phase[phase_name]["pre"]:
                for j, ward in enumerate(wards_by_phase[phase_name]["pre"]):
                    ward_meta = extract_metadata(ward)
                    validator = ward_meta.get("validator", "check")
                    valid = ward_meta.get("valid", True)
                    mode = ward_meta.get("mode", "blocking")

                    mode_icon = "🛡️" if mode == "blocking" else ("🔄" if mode == "retry" else "ℹ️")
                    status_mark = "✓" if valid else "✗"

                    ward_id = f"{pid}_pre{j}"
                    lines.append(f"        {ward_id} : {mode_icon} {sanitize_label(validator, 12)} {status_mark}")

                    if last_node:
                        lines.append(f"        {last_node} --> {ward_id}")
                    else:
                        first_internal = ward_id
                    last_node = ward_id

            # SOUNDINGS
            if has_soundings:
                attempts = soundings_by_phase[phase_name]
                attempts_info = {}
                winner_index = None

                for sa in attempts:
                    sa_meta = extract_metadata(sa)
                    idx = sa_meta.get("sounding_index", 0)
                    is_winner = sa_meta.get("is_winner", False)
                    attempts_info[idx] = {"is_winner": is_winner}
                    if is_winner:
                        winner_index = idx

                # Fork
                fork_id = f"{pid}_fork"
                lines.append(f"        state {fork_id} <<fork>>")

                if last_node:
                    lines.append(f"        {last_node} --> {fork_id}")
                else:
                    first_internal = fork_id

                # Attempts - include mutation info if available
                phase_mutations = sounding_mutations.get(phase_name, {})
                for idx in sorted(attempts_info.keys()):
                    info = attempts_info[idx]
                    marker = " ✓" if info["is_winner"] else ""

                    # Check for mutation info
                    mutation_info = phase_mutations.get(idx, {})
                    mutation_applied = mutation_info.get('mutation_applied')

                    # Determine mutation label (shortened)
                    mutation_label = ""
                    if mutation_applied:
                        # Shorten the mutation description
                        if len(mutation_applied) > 15:
                            mutation_label = f" [{mutation_applied[:12]}...]"
                        else:
                            mutation_label = f" [{mutation_applied}]"
                    elif idx == 0:
                        mutation_label = " [baseline]"

                    lines.append(f"        {fork_id} --> {pid}_a{idx}")
                    lines.append(f"        {pid}_a{idx} : #{idx+1}{mutation_label}{marker}")

                # Join
                join_id = f"{pid}_join"
                lines.append(f"        state {join_id} <<join>>")
                for idx in sorted(attempts_info.keys()):
                    lines.append(f"        {pid}_a{idx} --> {join_id}")

                # Evaluator
                eval_id = f"{pid}_eval"
                lines.append(f"        {join_id} --> {eval_id}")
                lines.append(f"        {eval_id} : ⚖️ Evaluate")

                # Winner
                if winner_index is not None:
                    winner_id = f"{pid}_winner"
                    lines.append(f"        {eval_id} --> {winner_id}")
                    lines.append(f"        {winner_id} : ★ #{winner_index+1}")
                    last_node = winner_id
                else:
                    last_node = eval_id

                # REFORGE (chains after soundings)
                if has_reforge:
                    for step_num in sorted(reforge_by_phase[phase_name].keys()):
                        step_data = reforge_by_phase[phase_name][step_num]
                        rf_attempts = step_data.get("attempts", [])
                        rf_winner = step_data.get("winner")

                        if rf_attempts:
                            rf_id = f"{pid}_rf{step_num}"
                            rf_factor = len(rf_attempts)
                            rf_winner_meta = extract_metadata(rf_winner) if rf_winner else {}
                            rf_winner_index = rf_winner_meta.get("winner_index")

                            # Nested composite for reforge step
                            lines.append(f"        state {rf_id} {{")
                            lines.append(f"            {rf_id}_label : 🔨 Reforge {step_num}")
                            lines.append(f"            [*] --> {rf_id}_fork")
                            lines.append(f"            state {rf_id}_fork <<fork>>")

                            for rf_att in sorted(rf_attempts, key=lambda a: extract_metadata(a).get("attempt_index", 0)):
                                rf_att_meta = extract_metadata(rf_att)
                                rf_idx = rf_att_meta.get("attempt_index", 0)
                                rf_is_winner = (rf_winner_index is not None and rf_idx == rf_winner_index)
                                rf_marker = " ✓" if rf_is_winner else ""
                                lines.append(f"            {rf_id}_fork --> {rf_id}_a{rf_idx}")
                                lines.append(f"            {rf_id}_a{rf_idx} : R{rf_idx+1}{rf_marker}")

                            lines.append(f"            state {rf_id}_join <<join>>")
                            for j in range(rf_factor):
                                lines.append(f"            {rf_id}_a{j} --> {rf_id}_join")

                            if rf_winner_index is not None:
                                lines.append(f"            {rf_id}_join --> {rf_id}_winner")
                                lines.append(f"            {rf_id}_winner : ★ R{rf_winner_index+1}")
                                lines.append(f"            {rf_id}_winner --> [*]")
                            else:
                                lines.append(f"            {rf_id}_join --> [*]")

                            lines.append(f"        }}")
                            lines.append(f"        {last_node} --> {rf_id}")
                            last_node = rf_id

            # SUB-CASCADES
            if has_sub_cascades:
                for sc_idx, sc_data in enumerate(sub_cascades_by_phase_name[phase_name]):
                    sc_cascade = sc_data["cascade"]
                    sc_phases = sc_data["phases"]
                    sc_name = sc_data.get("sub_echo", f"sub_{sc_idx}")

                    sc_content = sc_cascade.get("content", "")
                    sc_cascade_name = sc_content.replace("Cascade: ", "") if sc_content.startswith("Cascade: ") else sc_content
                    sc_id = f"{pid}_sc{sc_idx}"

                    # Nested composite for sub-cascade
                    lines.append(f"        state {sc_id} {{")
                    lines.append(f"            {sc_id}_label : 📦 {sanitize_label(sc_cascade_name, 20)}")

                    if sc_phases:
                        # Render sub-cascade phases
                        sc_phase_ids = []
                        for sp_idx, sp_entry in enumerate(sc_phases):
                            sp_content = sp_entry.get("content", "")
                            sp_name = sp_content.replace("Phase: ", "") if sp_content.startswith("Phase: ") else sp_content
                            sp_id = f"{sc_id}_p{sp_idx}"
                            sc_phase_ids.append(sp_id)

                            # Check if sub-phase is complete (in parent lineage or has output)
                            sp_status = "✓" if sp_name in completed_phases else "○"
                            lines.append(f"            {sp_id} : {sp_status} {sanitize_label(sp_name, 18)}")

                        # Connect sub-phases
                        if sc_phase_ids:
                            lines.append(f"            [*] --> {sc_phase_ids[0]}")
                            for k in range(len(sc_phase_ids) - 1):
                                lines.append(f"            {sc_phase_ids[k]} --> {sc_phase_ids[k+1]}")
                            lines.append(f"            {sc_phase_ids[-1]} --> [*]")
                    else:
                        # Empty sub-cascade placeholder
                        lines.append(f"            {sc_id}_empty : (no phases)")
                        lines.append(f"            [*] --> {sc_id}_empty")
                        lines.append(f"            {sc_id}_empty --> [*]")

                    lines.append(f"        }}")

                    if last_node:
                        lines.append(f"        {last_node} --> {sc_id}")
                    else:
                        first_internal = sc_id
                    last_node = sc_id

            # POST-WARDS
            if has_wards and wards_by_phase[phase_name]["post"]:
                for j, ward in enumerate(wards_by_phase[phase_name]["post"]):
                    ward_meta = extract_metadata(ward)
                    validator = ward_meta.get("validator", "check")
                    valid = ward_meta.get("valid", True)
                    mode = ward_meta.get("mode", "blocking")

                    mode_icon = "🛡️" if mode == "blocking" else ("🔄" if mode == "retry" else "ℹ️")
                    status_mark = "✓" if valid else "✗"

                    ward_id = f"{pid}_post{j}"
                    lines.append(f"        {ward_id} : {mode_icon} {sanitize_label(validator, 12)} {status_mark}")

                    if last_node:
                        lines.append(f"        {last_node} --> {ward_id}")
                    else:
                        first_internal = ward_id
                    last_node = ward_id

            # TURNS (show individual turn progression for multi-turn phases)
            if has_multi_turns and not has_soundings:  # Don't show turns if soundings handles it
                lines.append("")
                lines.append(f"        %% Turn progression")
                turn_ids = []
                for t_idx, turn_info in enumerate(detailed_turns):
                    t_num = turn_info.get('turn_number', t_idx + 1)
                    has_tools = turn_info.get('has_tool_calls', False)
                    content_preview = turn_info.get('content_preview', '')
                    t_id = f"{pid}_t{t_idx}"
                    turn_ids.append(t_id)

                    # Show turn with tool indicator and content preview
                    tool_mark = "🔧" if has_tools else ""
                    # Add short content preview like soundings do with mutations
                    context_label = ""
                    if content_preview:
                        # Truncate and clean for Mermaid
                        preview = sanitize_label(content_preview, 18)
                        if preview:
                            context_label = f" [{preview}]"
                    lines.append(f"        {t_id} : T{t_num}{context_label} {tool_mark}")

                # Connect turns in sequence
                if turn_ids:
                    if last_node:
                        lines.append(f"        {last_node} --> {turn_ids[0]}")
                    else:
                        first_internal = turn_ids[0]
                    for k in range(len(turn_ids) - 1):
                        lines.append(f"        {turn_ids[k]} --> {turn_ids[k+1]}")
                    last_node = turn_ids[-1]

            # ERRORS (show error nodes if errors occurred)
            if has_errors:
                lines.append("")
                lines.append(f"        %% Errors")
                for e_idx, error_info in enumerate(errors_by_phase[phase_name]):
                    error_type = error_info.get('error_type', 'error')
                    error_msg = sanitize_label(error_info.get('message', 'Error'), 25)
                    e_id = f"{pid}_err{e_idx}"

                    # Different icons for different error types
                    if error_type == "validation_error":
                        err_icon = "⚠️"
                    elif error_type == "schema_validation_failed":
                        err_icon = "📋❌"
                    else:
                        err_icon = "❌"

                    lines.append(f"        {e_id} : {err_icon} {error_msg}")

                    # Errors branch off but don't necessarily block flow
                    # Connect from last node (error happened during processing)
                    if last_node:
                        lines.append(f"        {last_node} --> {e_id}")

            # Connect internal flow
            if first_internal:
                lines.append(f"        [*] --> {first_internal}")
            if last_node:
                lines.append(f"        {last_node} --> [*]")

            # Apply running style to internal nodes that are currently executing
            if running_internal_nodes:
                lines.append("")
                lines.append("        %% Highlight currently executing internal node")
                for internal_node_id in running_internal_nodes:
                    lines.append(f"        class {internal_node_id} running")

            lines.append("    }")

        lines.append("")

    # =========================================================================
    # CONNECT PHASES
    # =========================================================================

    # Build phase_name -> pid mapping
    phase_name_to_pid = {}
    for phase_entry in phase_entries:
        content = phase_entry.get("content", "")
        pname = content.replace("Phase: ", "") if content.startswith("Phase: ") else content
        phase_name_to_pid[pname] = sid(pname)

    if first_state is None and phase_ids:
        first_state = phase_ids[0]
        lines.append(f"    [*] --> {first_state}")
    elif first_state and phase_ids:
        lines.append(f"    {first_state} --> {phase_ids[0]}")

    # Track which phases were actually executed (from lineage)
    executed_phases = [item.get("phase") for item in echo.lineage]

    # Phase-to-phase transitions with routing differentiation
    for i, phase_entry in enumerate(phase_entries):
        content = phase_entry.get("content", "")
        phase_name = content.replace("Phase: ", "") if content.startswith("Phase: ") else content
        pid = phase_ids[i]

        # Check if this phase was blocked
        if phase_name in blocked_phases:
            # Add blocked terminal state
            blocked_id = f"{pid}_blocked"
            validator = blocked_phases[phase_name].get('validator', 'ward')
            reason_short = sanitize_label(blocked_phases[phase_name].get('reason', 'blocked')[:20], 20)
            lines.append(f'    state "{reason_short}" as {blocked_id}')
            lines.append(f"    {pid} --> {blocked_id} : ⛔ {validator}")
            # No further transitions from blocked phase
            continue

        # Get handoffs for this phase
        phase_handoffs = handoffs_by_phase.get(phase_name, [])
        routing_target = routing_choices.get(phase_name)

        if phase_handoffs and len(phase_handoffs) > 1:
            # Multiple handoff options - show routing choices
            for target in phase_handoffs:
                target_pid = phase_name_to_pid.get(target)
                if target_pid:
                    if routing_target == target:
                        # This was the taken path - bold arrow with checkmark
                        lines.append(f"    {pid} --> {target_pid} : ✓ route")
                    else:
                        # Available but not taken - note syntax for dashed (Mermaid state diagrams don't support dashed, so we use note)
                        # Use different notation to indicate not-taken
                        lines.append(f"    {pid} --> {target_pid} : ○ available")
        elif phase_handoffs and len(phase_handoffs) == 1:
            # Single handoff - show taken path
            target = phase_handoffs[0]
            target_pid = phase_name_to_pid.get(target)
            if target_pid:
                lines.append(f"    {pid} --> {target_pid}")
        elif i + 1 < len(phase_ids):
            # Default sequential - connect to next phase
            lines.append(f"    {phase_ids[i]} --> {phase_ids[i+1]}")

    # =========================================================================
    # SELF-LOOP ARROWS FOR VALIDATION RETRIES
    # =========================================================================
    # Add self-loop arrows for phases that had validation retries (loop_until / max_attempts)
    lines.append("")
    lines.append("    %% Validation retry loops")
    for phase_entry in phase_entries:
        content = phase_entry.get("content", "")
        pname = content.replace("Phase: ", "") if content.startswith("Phase: ") else content
        pid = phase_name_to_pid.get(pname)

        if pname in validation_retries and pid:
            vr = validation_retries[pname]
            retry_count = vr.get('retry_count', 0)
            if retry_count > 0:
                max_attempts = vr.get('max_attempts', retry_count + 1)
                passed = vr.get('passed', False)
                loop_status = "✓" if passed else "✗"
                # Self-loop showing retry behavior
                lines.append(f"    {pid} --> {pid} : ⟳ retry {retry_count}x {loop_status}")

    # End state - only connect if last phase wasn't blocked
    if phase_ids:
        last_phase_entry = phase_entries[-1] if phase_entries else None
        if last_phase_entry:
            last_content = last_phase_entry.get("content", "")
            last_phase_name = last_content.replace("Phase: ", "") if last_content.startswith("Phase: ") else last_content
            if last_phase_name not in blocked_phases:
                lines.append(f"    {phase_ids[-1]} --> [*]")

    # =========================================================================
    # APPLY STYLING CLASSES
    # =========================================================================

    # Apply running class to running phases (thick green border)
    if running_phase_ids:
        lines.append("")
        lines.append("    %% Apply running style to active phases")
        for pid in running_phase_ids:
            lines.append(f"    class {pid} running")

    return "\n".join(lines)


def generate_state_diagram_with_metadata(echo: Echo, include_click_handlers: bool = True) -> Tuple[str, Dict[str, Any]]:
    """
    Generate a Mermaid state diagram with companion metadata for interactive debugging.

    Returns:
        Tuple of (mermaid_string, metadata_dict)

    The metadata dict contains:
    - node_map: Maps Mermaid node IDs to trace_ids and metadata
    - session_id: The session this diagram represents
    - phases: List of phase info with trace_ids
    - click_handlers: If enabled, adds click callbacks to the Mermaid

    This enables:
    - Clicking nodes to navigate to log entries
    - Highlighting nodes dynamically (e.g., for current execution)
    - Querying logs by trace_id for detailed inspection
    """
    history, sub_echoes = flatten_history(echo.history)

    # Build node metadata map
    node_map: Dict[str, Dict[str, Any]] = {}

    # Helper to create safe state IDs (same as in main function)
    def sid(name: str) -> str:
        s = name.replace("-", "_").replace(" ", "_").replace(".", "_")
        s = s.replace("(", "").replace(")", "").replace(":", "").replace("/", "_")
        return s

    # Collect phase info with trace_ids
    phases_info = []
    for entry in history:
        if entry.get("node_type") == "phase":
            content = entry.get("content", "")
            phase_name = content.replace("Phase: ", "") if content.startswith("Phase: ") else content
            trace_id = entry.get("trace_id", "")
            pid = sid(phase_name)

            phase_info = {
                "node_id": pid,
                "phase_name": phase_name,
                "trace_id": trace_id,
                "parent_id": entry.get("parent_id"),
                "node_type": "phase"
            }
            phases_info.append(phase_info)
            node_map[pid] = phase_info

    # Collect turn info
    for entry in history:
        if entry.get("node_type") == "turn":
            meta = extract_metadata(entry)
            phase_name = meta.get("phase_name", "unknown")
            turn_number = meta.get("turn_number", 1)
            trace_id = entry.get("trace_id", "")
            pid = sid(phase_name)
            turn_id = f"{pid}_t{turn_number - 1}"

            node_map[turn_id] = {
                "node_id": turn_id,
                "phase_name": phase_name,
                "turn_number": turn_number,
                "trace_id": trace_id,
                "parent_id": entry.get("parent_id"),
                "node_type": "turn"
            }

    # Collect sounding attempts
    for entry in history:
        if entry.get("node_type") == "sounding_attempt":
            meta = extract_metadata(entry)
            phase_name = meta.get("phase_name", "unknown")
            sounding_index = meta.get("sounding_index", 0)
            is_winner = meta.get("is_winner", False)
            trace_id = entry.get("trace_id", "")
            pid = sid(phase_name)
            sounding_id = f"{pid}_a{sounding_index}"

            node_map[sounding_id] = {
                "node_id": sounding_id,
                "phase_name": phase_name,
                "sounding_index": sounding_index,
                "is_winner": is_winner,
                "trace_id": trace_id,
                "parent_id": entry.get("parent_id"),
                "node_type": "sounding_attempt"
            }

    # Collect ward info
    for entry in history:
        if entry.get("node_type") in ("pre_ward", "post_ward"):
            meta = extract_metadata(entry)
            phase_name = meta.get("phase_name", "unknown")
            validator = meta.get("validator", "check")
            ward_type = "pre" if entry.get("node_type") == "pre_ward" else "post"
            trace_id = entry.get("trace_id", "")
            pid = sid(phase_name)
            # Ward IDs are indexed, find next available
            ward_idx = sum(1 for k in node_map if k.startswith(f"{pid}_{ward_type}"))
            ward_id = f"{pid}_{ward_type}{ward_idx}"

            node_map[ward_id] = {
                "node_id": ward_id,
                "phase_name": phase_name,
                "validator": validator,
                "ward_type": ward_type,
                "valid": meta.get("valid"),
                "mode": meta.get("mode"),
                "trace_id": trace_id,
                "parent_id": entry.get("parent_id"),
                "node_type": entry.get("node_type")
            }

    # Collect error info
    for entry in history:
        if entry.get("node_type") in ("error", "validation_error", "schema_validation_failed"):
            meta = extract_metadata(entry)
            phase_name = meta.get("phase_name", "unknown")
            trace_id = entry.get("trace_id", "")
            pid = sid(phase_name)
            err_idx = sum(1 for k in node_map if k.startswith(f"{pid}_err"))
            err_id = f"{pid}_err{err_idx}"

            node_map[err_id] = {
                "node_id": err_id,
                "phase_name": phase_name,
                "error_type": entry.get("node_type"),
                "message": entry.get("content", "")[:100],
                "trace_id": trace_id,
                "parent_id": entry.get("parent_id"),
                "node_type": entry.get("node_type")
            }

    # Collect quartermaster info
    for entry in history:
        if entry.get("node_type") == "quartermaster_result":
            meta = extract_metadata(entry)
            phase_name = meta.get("phase_name", "unknown")
            trace_id = entry.get("trace_id", "")
            pid = sid(phase_name)
            qm_id = f"{pid}_qm"

            node_map[qm_id] = {
                "node_id": qm_id,
                "phase_name": phase_name,
                "selected_tools": meta.get("selected_tackle", []),
                "reasoning": meta.get("reasoning", ""),
                "trace_id": trace_id,
                "parent_id": entry.get("parent_id"),
                "node_type": "quartermaster"
            }

    # Generate the base diagram
    mermaid_str = generate_state_diagram_string(echo)

    # Add click handlers if requested
    if include_click_handlers:
        click_lines = ["\n    %% Click handlers for interactive debugging"]
        for node_id, node_info in node_map.items():
            trace_id = node_info.get("trace_id", "")
            if trace_id:
                # Mermaid click syntax: click nodeId callback or click nodeId "url"
                # Using callback style for maximum flexibility
                click_lines.append(f'    click {node_id} call handleNodeClick("{node_id}", "{trace_id}")')

        mermaid_str += "\n".join(click_lines)

    # Get live session state for additional metadata
    live_state = get_live_session_state(echo.session_id)
    running_info = None
    if live_state and live_state.get("status") == "running":
        running_phase = live_state.get("current_phase")
        phase_progress = live_state.get("phase_progress")
        progress_indicator = format_phase_progress_indicator(phase_progress) if phase_progress else ""

        running_info = {
            "running_phase": running_phase,
            "phase_progress": phase_progress,
            "progress_indicator": progress_indicator,
            "running_internal_node": get_running_internal_node_id(
                phase_progress,
                sid(running_phase) if running_phase else ""
            ) if phase_progress else None
        }

    # Build metadata structure
    metadata = {
        "session_id": echo.session_id,
        "node_map": node_map,
        "phases": phases_info,
        "lineage": echo.lineage,
        "node_count": len(node_map),
        "has_click_handlers": include_click_handlers,
        # Live execution state (null if not running)
        "running_state": running_info
    }

    return mermaid_str, metadata


def generate_state_diagram(echo: Echo, output_path: str) -> str:
    """
    Generate a Mermaid state diagram from Echo history and write to file.

    This is an alternative to generate_mermaid() that produces a more compact,
    semantically meaningful visualization using state diagram syntax.

    Returns:
        Path to written .mmd file
    """
    content = generate_state_diagram_string(echo)

    with open(output_path, "w") as f:
        f.write(content)

    return output_path


def generate_mermaid(echo: Echo, output_path: str) -> str:
    """
    Generate a Mermaid state diagram from Echo history and write to file.

    The diagram shows:
    - Phases as composite states with internal complexity
    - Soundings as fork/join parallel branches with winner highlighting
    - Reforge as nested refinement states
    - Sub-cascades as nested composite states
    - Wards as entry/exit validation states

    Also generates companion JSON files with execution graph structure.

    Returns:
        Path to written .mmd file
    """
    # Generate the state diagram (more compact than flowchart)
    mermaid_content = generate_state_diagram_string(echo)

    # Generate companion JSON files
    json_path = output_path.replace(".mmd", ".json")
    reactflow_path = output_path.replace(".mmd", "_reactflow.json")

    try:
        export_execution_graph_json(echo, json_path)
    except Exception as e:
        # Don't fail mermaid generation if JSON fails
        print(f"[Warning] Failed to generate execution graph JSON: {e}")

    try:
        export_react_flow_graph(echo, reactflow_path)
    except Exception as e:
        print(f"[Warning] Failed to generate React Flow JSON: {e}")

    # Write to file
    with open(output_path, "w") as f:
        f.write(mermaid_content)

    return output_path


def generate_mermaid_from_config(config: Any, output_path: str) -> str:
    """
    Generate a static Mermaid diagram from CascadeConfig.
    Shows the intended structure before execution.
    """
    lines = ["graph TD"]

    # Styles - Midnight Fjord Dark Theme
    lines.extend([
        "    %% Static Structure Styles - Midnight Fjord Dark Theme",
        "    classDef cascade fill:#16202A,stroke:#2C3B4B,stroke-width:2px,color:#F0F4F8;",
        "    classDef phase fill:#16202A,stroke:#2DD4BF,stroke-width:2px,color:#F0F4F8;",
        "    classDef soundings fill:#16202A,stroke:#D9A553,stroke-width:2px,color:#F0F4F8;",
        "    classDef reforge fill:#16202A,stroke:#D9A553,stroke-width:2px,color:#F0F4F8;",
        "    classDef sub_cascade fill:#16202A,stroke:#a78bfa,stroke-width:2px,color:#F0F4F8;",
        "",
    ])

    # Note: Removed cascade container for cleaner visualization without outer border

    phase_ids = []

    for phase in config.phases:
        phase_id = f"p_{phase.name.replace('-', '_').replace(' ', '_')}"
        phase_ids.append(phase_id)

        # Determine phase decoration
        if phase.soundings and phase.soundings.factor > 1:
            icon = "[ToT]"  # Soundings / Tree of Thought
            style = "soundings"
            if phase.soundings.reforge:
                icon = "[ToT+R]"  # Soundings + Reforge
                style = "reforge"
        elif phase.sub_cascades:
            icon = "[Sub]"  # Sub-cascade
            style = "sub_cascade"
        else:
            icon = ""
            style = "phase"

        label = f"{icon} {phase.name}" if icon else phase.name
        lines.append(f'        {phase_id}["{sanitize_label(label, 40)}"]')
        lines.append(f"        class {phase_id} {style}")

    # Connect phases (handoffs)
    for i, phase in enumerate(config.phases):
        current_id = phase_ids[i]

        # Check for explicit handoffs
        if phase.handoffs:
            for handoff in phase.handoffs:
                target = handoff.target if hasattr(handoff, 'target') else handoff
                # Find target phase
                for j, p in enumerate(config.phases):
                    if p.name == target:
                        lines.append(f"        {current_id} --> {phase_ids[j]}")
                        break
        elif i + 1 < len(phase_ids):
            # Default sequential connection
            lines.append(f"        {current_id} --> {phase_ids[i+1]}")

    with open(output_path, "w") as f:
        f.write("\n".join(lines))

    return output_path
