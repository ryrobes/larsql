"""
Cascade Introspector

Analyzes a cascade definition and infers the graph structure for the playground.
When a cascade doesn't have _playground metadata, this can reconstruct
the visual graph from the cascade's implicit dependencies.

Sources of edge information:
1. context.from - explicit phase dependencies
2. {{ input.X }} in instructions - input/prompt dependencies
3. {{ outputs.X }} in instructions - phase output dependencies
4. handoffs - routing edges (optional visualization)
"""

import re
import yaml
from typing import Dict, List, Set, Tuple, Any, Optional
from collections import defaultdict


def introspect_cascade(cascade_dict: dict) -> dict:
    """
    Analyze a cascade definition and infer the graph structure.

    Args:
        cascade_dict: Parsed cascade configuration

    Returns:
        {
            "nodes": [...],      # React Flow node definitions with positions
            "edges": [...],      # React Flow edge definitions
            "inputs": {...},     # Discovered inputs with descriptions
            "viewport": {...},   # Suggested viewport
        }
    """
    nodes = []
    edges = []

    # Maps for tracking
    phase_to_node: Dict[str, str] = {}  # phase_name -> node_id
    input_to_node: Dict[str, str] = {}  # input_name -> node_id
    phase_dependencies: Dict[str, Set[str]] = defaultdict(set)  # phase -> set of phases it depends on
    phase_input_deps: Dict[str, Set[str]] = defaultdict(set)  # phase -> set of inputs it uses

    phases = cascade_dict.get('phases', [])
    inputs_schema = cascade_dict.get('inputs_schema', {})

    # =========================================================================
    # PASS 1: Discover all inputs (from schema + template references)
    # =========================================================================
    all_inputs = set(inputs_schema.keys())

    # Regex that matches {{ input.X }} with optional Jinja2 filters like | default(...)
    # Matches: {{ input.foo }}, {{ input.bar | default("x") }}, {{ input.baz|default("y") }}
    INPUT_PATTERN = re.compile(r'\{\{\s*input\.(\w+)(?:\s*\|[^}]*)?\s*\}\}')

    for phase in phases:
        instructions = phase.get('instructions', '')
        if isinstance(instructions, str):
            # Find {{ input.X }} and {{ input.X | default(...) }} references
            matches = INPUT_PATTERN.findall(instructions)
            all_inputs.update(matches)

    # =========================================================================
    # PASS 2: Create input/prompt nodes
    # =========================================================================
    for i, input_name in enumerate(sorted(all_inputs)):
        node_id = f"prompt_{i}"
        input_to_node[input_name] = node_id

        # Get description from inputs_schema if available (for placeholder text)
        input_description = inputs_schema.get(input_name, '')

        nodes.append({
            'id': node_id,
            'type': 'prompt',
            'data': {
                'name': input_name,
                'text': '',  # Will be filled when running
                'placeholder': input_description,  # Description as placeholder
            },
            # Position will be set in layout pass
            'position': {'x': 0, 'y': 0},
        })

    # =========================================================================
    # PASS 3: Create phase nodes and collect dependencies
    # =========================================================================
    for i, phase in enumerate(phases):
        phase_name = phase.get('name', f'phase_{i}')
        node_id = f"node_{i}"
        phase_to_node[phase_name] = node_id

        # Determine node type
        node_type, node_data = _classify_phase(phase, phase_name)

        nodes.append({
            'id': node_id,
            'type': node_type,
            'data': node_data,
            'position': {'x': 0, 'y': 0},
        })

        # Collect dependencies from context.from
        context = phase.get('context', {})
        context_from = context.get('from', [])
        for source in context_from:
            if isinstance(source, str):
                phase_dependencies[phase_name].add(source)
            elif isinstance(source, dict):
                source_phase = source.get('phase')
                if source_phase:
                    phase_dependencies[phase_name].add(source_phase)

        # Collect dependencies from {{ outputs.X }} in instructions
        instructions = phase.get('instructions', '')
        if isinstance(instructions, str):
            output_refs = re.findall(r'\{\{\s*outputs\.(\w+)(?:\s*\|[^}]*)?\s*\}\}', instructions)
            phase_dependencies[phase_name].update(output_refs)

            # Collect input dependencies (using same pattern that handles | default(...))
            input_refs = INPUT_PATTERN.findall(instructions)
            phase_input_deps[phase_name].update(input_refs)

    # =========================================================================
    # PASS 4: Create edges
    # =========================================================================
    edge_set = set()  # Track (source, target) to avoid duplicates

    # Input -> Phase edges
    for phase_name, input_deps in phase_input_deps.items():
        if phase_name not in phase_to_node:
            continue
        target_id = phase_to_node[phase_name]

        for input_name in input_deps:
            if input_name in input_to_node:
                source_id = input_to_node[input_name]
                edge_key = (source_id, target_id)
                if edge_key not in edge_set:
                    edge_set.add(edge_key)
                    edges.append({
                        'id': f"{source_id}-{target_id}",
                        'source': source_id,
                        'target': target_id,
                        'sourceHandle': 'text-out',
                        'targetHandle': 'text-in',
                    })

    # Phase -> Phase edges
    for phase_name, deps in phase_dependencies.items():
        if phase_name not in phase_to_node:
            continue
        target_id = phase_to_node[phase_name]
        target_node = next((n for n in nodes if n['id'] == target_id), None)

        for dep_name in deps:
            if dep_name in phase_to_node:
                source_id = phase_to_node[dep_name]
                source_node = next((n for n in nodes if n['id'] == source_id), None)

                # Use simple (source, target) key - handles don't matter for dedup
                edge_key = (source_id, target_id)
                if edge_key not in edge_set:
                    edge_set.add(edge_key)

                    # Determine handle types based on node types and context
                    source_handle, target_handle = _infer_handles(
                        source_node, target_node,
                        phase_to_node, phases, dep_name, phase_name
                    )

                    edges.append({
                        'id': f"{source_id}-{target_id}",
                        'source': source_id,
                        'target': target_id,
                        'sourceHandle': source_handle,
                        'targetHandle': target_handle,
                    })

    # Handoff edges (dashed/animated to distinguish from data flow)
    for phase in phases:
        phase_name = phase.get('name')
        if phase_name not in phase_to_node:
            continue
        source_id = phase_to_node[phase_name]

        for handoff in phase.get('handoffs', []):
            if handoff in phase_to_node:
                target_id = phase_to_node[handoff]
                edge_key = (source_id, target_id, 'handoff')
                if edge_key not in edge_set:
                    edge_set.add(edge_key)
                    edges.append({
                        'id': f"{source_id}-{target_id}-handoff",
                        'source': source_id,
                        'target': target_id,
                        'type': 'handoff',
                        'animated': True,
                        'style': {'strokeDasharray': '5,5'},
                    })

    # =========================================================================
    # PASS 5: Layout nodes using topological sort
    # =========================================================================
    nodes = _layout_nodes(nodes, edges, input_to_node, phase_to_node)

    # Calculate viewport to fit all nodes
    viewport = _calculate_viewport(nodes)

    return {
        'nodes': nodes,
        'edges': edges,
        'inputs': dict(inputs_schema),
        'viewport': viewport,
    }


def _classify_phase(phase: dict, phase_name: str) -> Tuple[str, dict]:
    """
    Determine the node type and data for a phase.

    Node types:
    - 'image': Image generation models (FLUX, Gemini Image, etc.)
    - 'phase': LLM phases and deterministic tool phases (rendered as YAML blocks)

    Returns:
        (node_type, node_data)
    """
    model = phase.get('model', '')

    # Check if it's an image generation model
    is_image_model = False
    if model:
        try:
            from windlass.model_registry import ModelRegistry
            is_image_model = ModelRegistry.is_image_output_model(model)
        except ImportError:
            # Fallback: check common image model patterns
            image_patterns = ['flux', 'sdxl', 'riverflow', 'dall-e']
            # Note: removed 'image' from patterns - too generic, catches things like "gemini-2.5-flash-image" but also false positives
            is_image_model = any(p in model.lower() for p in image_patterns)

    if is_image_model:
        # Image generation node
        return 'image', {
            'name': phase_name,
            'paletteConfig': {
                'openrouter': {'model': model},
            },
            'status': 'idle',
            'images': [],
        }
    else:
        # LLM Phase OR deterministic tool phase - both rendered as YAML blocks
        # This includes:
        # - Regular LLM phases with instructions
        # - Tool-only (deterministic) phases like `tool: linux_shell`
        # - Composite phases with tackle + instructions
        return 'phase', {
            'name': phase_name,
            'yaml': yaml.dump(phase, default_flow_style=False, sort_keys=False),
            'status': 'idle',
            'output': '',
        }


def _infer_handles(
    source_node: dict,
    target_node: dict,
    phase_to_node: dict,
    phases: list,
    source_name: str,
    target_name: str
) -> Tuple[str, str]:
    """
    Infer the appropriate source and target handles for an edge.

    For image nodes connecting to image nodes: image-out -> image-in
    For phase/prompt to phase: text-out -> text-in
    For image to phase (vision): image-out -> image-in
    """
    source_type = source_node.get('type', 'phase') if source_node else 'phase'
    target_type = target_node.get('type', 'phase') if target_node else 'phase'

    # Check if target phase specifically requests images from source
    target_phase = next((p for p in phases if p.get('name') == target_name), None)
    if target_phase:
        context_from = target_phase.get('context', {}).get('from', [])
        for source in context_from:
            if isinstance(source, dict):
                if source.get('phase') == source_name:
                    includes = source.get('include', [])
                    if 'images' in includes:
                        return 'image-out', 'image-in'

    # Default based on node types
    if source_type == 'image' and target_type == 'image':
        return 'image-out', 'image-in'
    elif source_type == 'image' and target_type == 'phase':
        # Image feeding into a phase (for vision/analysis)
        return 'image-out', 'image-in'
    elif source_type == 'prompt':
        return 'text-out', 'text-in'
    else:
        # Phase to phase: typically text output
        return 'text-out', 'text-in'


def _layout_nodes(
    nodes: List[dict],
    edges: List[dict],
    input_to_node: dict,
    phase_to_node: dict
) -> List[dict]:
    """
    Layout nodes using topological sort to determine columns,
    then distribute vertically within each column.
    """
    # Build adjacency for topological sort
    # node_id -> list of node_ids it points to
    outgoing: Dict[str, List[str]] = defaultdict(list)
    incoming: Dict[str, List[str]] = defaultdict(list)

    node_ids = {n['id'] for n in nodes}

    for edge in edges:
        source = edge.get('source')
        target = edge.get('target')
        if source in node_ids and target in node_ids:
            outgoing[source].append(target)
            incoming[target].append(source)

    # Calculate depth (column) for each node using BFS from roots
    depths: Dict[str, int] = {}

    # Find roots (nodes with no incoming edges)
    roots = [n['id'] for n in nodes if not incoming.get(n['id'])]

    # If no roots found (cycle or all connected), start from input nodes
    if not roots:
        roots = list(input_to_node.values())

    # BFS to assign depths
    from collections import deque
    queue = deque()
    for root in roots:
        depths[root] = 0
        queue.append(root)

    while queue:
        node_id = queue.popleft()
        current_depth = depths[node_id]

        for target in outgoing.get(node_id, []):
            # Assign max depth seen (ensures node is placed after all its dependencies)
            new_depth = current_depth + 1
            if target not in depths or depths[target] < new_depth:
                depths[target] = new_depth
                queue.append(target)

    # Handle any unvisited nodes (disconnected)
    max_depth = max(depths.values()) if depths else 0
    for node in nodes:
        if node['id'] not in depths:
            depths[node['id']] = max_depth + 1

    # Group nodes by depth
    by_depth: Dict[int, List[dict]] = defaultdict(list)
    for node in nodes:
        depth = depths.get(node['id'], 0)
        by_depth[depth].append(node)

    # Position nodes
    COLUMN_WIDTH = 350
    ROW_HEIGHT = 200
    START_X = 100
    START_Y = 100

    for depth, depth_nodes in by_depth.items():
        x = START_X + depth * COLUMN_WIDTH

        # Center vertically
        total_height = len(depth_nodes) * ROW_HEIGHT
        start_y = START_Y + (max(len(by_depth.get(d, [])) for d in by_depth) * ROW_HEIGHT - total_height) // 2

        for i, node in enumerate(depth_nodes):
            node['position'] = {
                'x': x,
                'y': start_y + i * ROW_HEIGHT,
            }

    return nodes


def _calculate_viewport(nodes: List[dict]) -> dict:
    """Calculate a viewport that fits all nodes with padding."""
    if not nodes:
        return {'x': 0, 'y': 0, 'zoom': 1}

    min_x = min(n['position']['x'] for n in nodes)
    min_y = min(n['position']['y'] for n in nodes)
    max_x = max(n['position']['x'] for n in nodes) + 300  # Node width
    max_y = max(n['position']['y'] for n in nodes) + 150  # Node height

    # Add padding
    padding = 50
    min_x -= padding
    min_y -= padding

    # Calculate zoom to fit (assuming 1200x800 viewport)
    width = max_x - min_x + padding * 2
    height = max_y - min_y + padding * 2

    zoom_x = 1200 / width if width > 0 else 1
    zoom_y = 800 / height if height > 0 else 1
    zoom = min(zoom_x, zoom_y, 1)  # Don't zoom in past 1

    return {
        'x': -min_x * zoom + padding,
        'y': -min_y * zoom + padding,
        'zoom': round(zoom, 2),
    }


# Convenience function for testing
def introspect_cascade_file(filepath: str) -> dict:
    """Load and introspect a cascade file."""
    with open(filepath, 'r') as f:
        if filepath.endswith('.json'):
            import json
            cascade = json.load(f)
        else:
            cascade = yaml.safe_load(f)

    return introspect_cascade(cascade)
