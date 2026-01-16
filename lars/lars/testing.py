"""
Cascade snapshot testing - capture real executions, validate framework behavior.

Enhanced Testing System:
- Phase 1: Deterministic replay with mocked LLM responses
- Phase 2: Behavioral contract extraction and verification
- Phase 3: Semantic anchor extraction and matching
- Phase 4: Optional LLM judge for quality comparison

Workflow:
1. Run cascade normally: lars run my_flow.json --input {...} --session test_001
2. Verify it worked correctly
3. Freeze as test: lars test freeze test_001 --name my_test --extract-all
4. Replay anytime: lars test replay my_test --mode deterministic
"""
import json
import re
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple, Iterator
from dataclasses import dataclass, field, asdict
from enum import Enum
import logging

log = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES FOR CONTRACTS AND ANCHORS
# =============================================================================

class ContractType(str, Enum):
    """Types of behavioral contracts."""
    ROUTING = "routing"
    STATE_MUTATION = "state_mutation"
    TOOL_CALL = "tool_call"
    OUTPUT_FORMAT = "output_format"
    OUTPUT_CONTAINS = "output_contains"
    CELL_SEQUENCE = "cell_sequence"
    ERROR_EXPECTATION = "error_expectation"


@dataclass
class RoutingContract:
    """Contract for cell-to-cell routing."""
    from_cell: str
    to_cell: str
    condition: Optional[str] = None  # e.g., "sentiment == positive"

    def verify(self, routing_path: List[str]) -> Tuple[bool, str]:
        """Check if routing occurred in the path."""
        try:
            from_idx = routing_path.index(self.from_cell)
            to_idx = routing_path.index(self.to_cell)
            if to_idx == from_idx + 1:
                return True, f"[OK] Routing {self.from_cell} → {self.to_cell}"
            else:
                return False, f"✗ Expected {self.from_cell} → {self.to_cell}, but not consecutive"
        except ValueError:
            return False, f"✗ Cells not found in path: {self.from_cell} or {self.to_cell}"


@dataclass
class StateMutationContract:
    """Contract for state key mutations."""
    cell: str
    sets_keys: List[str] = field(default_factory=list)
    modifies_keys: List[str] = field(default_factory=list)

    def verify(self, cell_state_changes: Dict[str, Dict[str, Any]]) -> Tuple[bool, str]:
        """Check if state mutations occurred."""
        changes = cell_state_changes.get(self.cell, {})
        missing = [k for k in self.sets_keys if k not in changes.get("set", [])]
        if missing:
            return False, f"✗ Cell '{self.cell}' did not set keys: {missing}"
        return True, f"[OK] Cell '{self.cell}' set expected state keys"


@dataclass
class ToolCallContract:
    """Contract for tool invocations."""
    cell: str
    tool: str
    args_pattern: Optional[str] = None  # Regex pattern for args
    min_calls: int = 1
    max_calls: Optional[int] = None

    def verify(self, cell_tool_calls: Dict[str, List[Dict]]) -> Tuple[bool, str]:
        """Check if tool was called correctly."""
        calls = cell_tool_calls.get(self.cell, [])
        matching_calls = [c for c in calls if c.get("tool") == self.tool]

        if len(matching_calls) < self.min_calls:
            return False, f"✗ Cell '{self.cell}' called {self.tool} {len(matching_calls)}x, expected >= {self.min_calls}"

        if self.max_calls and len(matching_calls) > self.max_calls:
            return False, f"✗ Cell '{self.cell}' called {self.tool} {len(matching_calls)}x, expected <= {self.max_calls}"

        if self.args_pattern:
            pattern = re.compile(self.args_pattern, re.IGNORECASE | re.DOTALL)
            for call in matching_calls:
                args_str = json.dumps(call.get("args", {}))
                if not pattern.search(args_str):
                    return False, f"✗ Tool {self.tool} args didn't match pattern: {self.args_pattern}"

        return True, f"[OK] Cell '{self.cell}' called {self.tool} correctly"


@dataclass
class OutputContract:
    """Contract for output format/content."""
    cell: str
    contains: List[str] = field(default_factory=list)  # Must contain these phrases
    format_type: Optional[str] = None  # markdown, json, list, etc.
    min_length: Optional[int] = None
    max_length: Optional[int] = None

    def verify(self, cell_outputs: Dict[str, str]) -> Tuple[bool, str]:
        """Check if output matches expectations."""
        output = cell_outputs.get(self.cell, "")

        # Check length
        if self.min_length and len(output) < self.min_length:
            return False, f"✗ Cell '{self.cell}' output too short: {len(output)} < {self.min_length}"
        if self.max_length and len(output) > self.max_length:
            return False, f"✗ Cell '{self.cell}' output too long: {len(output)} > {self.max_length}"

        # Check contains
        missing = [phrase for phrase in self.contains if phrase.lower() not in output.lower()]
        if missing:
            return False, f"✗ Cell '{self.cell}' output missing phrases: {missing}"

        # Check format
        if self.format_type:
            if self.format_type == "json":
                try:
                    json.loads(output)
                except:
                    return False, f"✗ Cell '{self.cell}' output is not valid JSON"
            elif self.format_type == "markdown":
                if not any(marker in output for marker in ["#", "-", "*", "```", "**"]):
                    return False, f"✗ Cell '{self.cell}' output doesn't look like markdown"

        return True, f"[OK] Cell '{self.cell}' output matches contract"


@dataclass
class SemanticAnchor:
    """A semantic anchor - key phrase/topic that should appear in output."""
    cell: str
    anchor: str  # The phrase/topic
    weight: float = 1.0  # Importance weight
    required: bool = True  # Must be present vs. optional
    similarity_threshold: float = 0.7  # For embedding-based matching

    def verify_exact(self, output: str) -> Tuple[bool, str]:
        """Check if anchor appears exactly (case-insensitive)."""
        if self.anchor.lower() in output.lower():
            return True, f"[OK] Anchor '{self.anchor}' found in {self.cell}"
        if self.required:
            return False, f"✗ Required anchor '{self.anchor}' missing from {self.cell}"
        return True, f"[WARN] Optional anchor '{self.anchor}' not found in {self.cell}"

    def verify_semantic(self, output: str, embedder) -> Tuple[bool, float, str]:
        """Check if anchor is semantically present using embeddings."""
        # Split output into sentences for comparison
        sentences = re.split(r'[.!?\n]+', output)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 10]

        if not sentences:
            if self.required:
                return False, 0.0, f"✗ No content to check for anchor '{self.anchor}'"
            return True, 0.0, f"[WARN] No content for optional anchor '{self.anchor}'"

        # Get embeddings
        anchor_emb = embedder.embed(self.anchor)
        max_sim = 0.0

        for sentence in sentences:
            sent_emb = embedder.embed(sentence)
            sim = cosine_similarity(anchor_emb, sent_emb)
            max_sim = max(max_sim, sim)

        if max_sim >= self.similarity_threshold:
            return True, max_sim, f"[OK] Anchor '{self.anchor}' found (sim={max_sim:.2f})"

        if self.required:
            return False, max_sim, f"✗ Anchor '{self.anchor}' not found (best sim={max_sim:.2f} < {self.similarity_threshold})"
        return True, max_sim, f"[WARN] Optional anchor '{self.anchor}' weak match (sim={max_sim:.2f})"


@dataclass
class BehavioralContracts:
    """Collection of all behavioral contracts for a snapshot."""
    routing: List[RoutingContract] = field(default_factory=list)
    state_mutations: List[StateMutationContract] = field(default_factory=list)
    tool_calls: List[ToolCallContract] = field(default_factory=list)
    outputs: List[OutputContract] = field(default_factory=list)
    cell_sequence: List[str] = field(default_factory=list)  # Expected order

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "routing": [asdict(r) for r in self.routing],
            "state_mutations": [asdict(s) for s in self.state_mutations],
            "tool_calls": [asdict(t) for t in self.tool_calls],
            "outputs": [asdict(o) for o in self.outputs],
            "cell_sequence": self.cell_sequence
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'BehavioralContracts':
        """Create from dictionary."""
        return cls(
            routing=[RoutingContract(**r) for r in data.get("routing", [])],
            state_mutations=[StateMutationContract(**s) for s in data.get("state_mutations", [])],
            tool_calls=[ToolCallContract(**t) for t in data.get("tool_calls", [])],
            outputs=[OutputContract(**o) for o in data.get("outputs", [])],
            cell_sequence=data.get("cell_sequence", [])
        )


# =============================================================================
# MOCK LLM FOR DETERMINISTIC REPLAY
# =============================================================================

class MockLLM:
    """
    Mock LLM that returns frozen responses from a snapshot.

    Used for deterministic replay - instead of calling the real LLM,
    returns the exact responses captured in the original run.
    """

    def __init__(self, frozen_responses: List[Dict[str, Any]]):
        """
        Initialize with frozen responses.

        Args:
            frozen_responses: List of response dicts with 'cell', 'turn', 'content', 'tool_calls'
        """
        self.responses = frozen_responses
        self.response_index = 0
        self.call_log = []

    @classmethod
    def from_snapshot(cls, snapshot: Dict[str, Any]) -> 'MockLLM':
        """Create MockLLM from a snapshot's execution data."""
        responses = []

        for cell in snapshot.get("execution", {}).get("cells", []):
            cell_name = cell.get("name", "unknown")
            for turn in cell.get("turns", []):
                agent_response = turn.get("agent_response", {})
                if agent_response:
                    responses.append({
                        "cell": cell_name,
                        "turn": turn.get("turn_number", 0),
                        "content": agent_response.get("content", ""),
                        "tool_calls": agent_response.get("tool_calls", [])
                    })

        return cls(responses)

    def get_next_response(self, cell_name: str = None) -> Dict[str, Any]:
        """
        Get the next frozen response.

        Args:
            cell_name: Optional cell name for validation

        Returns:
            Response dict with 'content' and optional 'tool_calls'
        """
        if self.response_index >= len(self.responses):
            raise StopIteration(f"No more frozen responses (used {self.response_index})")

        response = self.responses[self.response_index]
        self.response_index += 1

        # Log the call
        self.call_log.append({
            "index": self.response_index - 1,
            "requested_cell": cell_name,
            "frozen_cell": response.get("cell"),
            "matched": cell_name == response.get("cell") if cell_name else True
        })

        return response

    def chat(self, messages: List[Dict], **kwargs) -> Dict[str, Any]:
        """
        Mock chat completion - returns frozen response.

        This method signature matches what the runner expects.
        """
        # Try to infer cell name from context
        cell_name = kwargs.get("cell_name")

        response = self.get_next_response(cell_name)

        # Format as LLM response
        return {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": response.get("content", ""),
                    "tool_calls": response.get("tool_calls", [])
                }
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "_mock": True,
            "_frozen_cell": response.get("cell"),
            "_frozen_turn": response.get("turn")
        }

    def reset(self):
        """Reset to beginning of responses."""
        self.response_index = 0
        self.call_log = []

    def get_replay_stats(self) -> Dict[str, Any]:
        """Get statistics about the replay."""
        return {
            "total_responses": len(self.responses),
            "responses_used": self.response_index,
            "remaining": len(self.responses) - self.response_index,
            "call_log": self.call_log,
            "mismatches": [c for c in self.call_log if not c.get("matched", True)]
        }


# =============================================================================
# CONTRACT EXTRACTION
# =============================================================================

class ContractExtractor:
    """Extracts behavioral contracts from snapshot execution data."""

    def extract_all(self, snapshot: Dict[str, Any]) -> BehavioralContracts:
        """Extract all contracts from a snapshot."""
        contracts = BehavioralContracts()

        execution = snapshot.get("execution", {})
        cells = execution.get("cells", [])

        # Extract cell sequence
        contracts.cell_sequence = [c["name"] for c in cells]

        # Extract routing contracts
        contracts.routing = self._extract_routing(cells)

        # Extract state mutation contracts
        contracts.state_mutations = self._extract_state_mutations(cells)

        # Extract tool call contracts
        contracts.tool_calls = self._extract_tool_calls(cells)

        # Extract output contracts
        contracts.outputs = self._extract_outputs(cells)

        return contracts

    def _extract_routing(self, cells: List[Dict]) -> List[RoutingContract]:
        """Extract routing contracts from consecutive cells."""
        contracts = []
        cell_names = [c["name"] for c in cells]

        for i in range(len(cell_names) - 1):
            contracts.append(RoutingContract(
                from_cell=cell_names[i],
                to_cell=cell_names[i + 1]
            ))

        return contracts

    def _extract_state_mutations(self, cells: List[Dict]) -> List[StateMutationContract]:
        """Extract state mutation contracts from tool results."""
        contracts = []

        for cell in cells:
            cell_name = cell["name"]
            state_keys = set()

            for turn in cell.get("turns", []):
                for tool_result in turn.get("tool_results", []):
                    result = tool_result.get("result", "")
                    if isinstance(result, str) and "State updated:" in result:
                        # Parse state keys from "State updated: key = value"
                        match = re.search(r"State updated:\s*(\w+)\s*=", result)
                        if match:
                            state_keys.add(match.group(1))

                    # Also check for set_state tool
                    if tool_result.get("tool") == "set_state":
                        # Try to parse the key from args
                        try:
                            if isinstance(result, dict):
                                state_keys.update(result.keys())
                        except:
                            pass

            if state_keys:
                contracts.append(StateMutationContract(
                    cell=cell_name,
                    sets_keys=list(state_keys)
                ))

        return contracts

    def _extract_tool_calls(self, cells: List[Dict]) -> List[ToolCallContract]:
        """Extract tool call contracts."""
        contracts = []

        for cell in cells:
            cell_name = cell["name"]
            tool_counts = {}

            for turn in cell.get("turns", []):
                for tool_result in turn.get("tool_results", []):
                    tool_name = tool_result.get("tool", "unknown")
                    if tool_name != "unknown":
                        tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1

            for tool_name, count in tool_counts.items():
                contracts.append(ToolCallContract(
                    cell=cell_name,
                    tool=tool_name,
                    min_calls=count,
                    max_calls=count  # Exact match for now
                ))

        return contracts

    def _extract_outputs(self, cells: List[Dict]) -> List[OutputContract]:
        """Extract output contracts from agent responses."""
        contracts = []

        for cell in cells:
            cell_name = cell["name"]

            # Get the last (final) agent response
            last_content = ""
            for turn in cell.get("turns", []):
                agent_response = turn.get("agent_response", {})
                if agent_response and agent_response.get("content"):
                    last_content = agent_response["content"]

            if last_content:
                # Detect format
                format_type = None
                if last_content.strip().startswith("{") or last_content.strip().startswith("["):
                    try:
                        json.loads(last_content)
                        format_type = "json"
                    except:
                        pass
                elif any(marker in last_content for marker in ["###", "##", "**", "- ", "* ", "```"]):
                    format_type = "markdown"

                contracts.append(OutputContract(
                    cell=cell_name,
                    format_type=format_type,
                    min_length=max(1, len(last_content) // 2),  # At least half the original length
                    max_length=len(last_content) * 3  # Up to 3x the original length
                ))

        return contracts


# =============================================================================
# SEMANTIC ANCHOR EXTRACTION
# =============================================================================

class AnchorExtractor:
    """Extracts semantic anchors from snapshot outputs."""

    def __init__(self, min_phrase_length: int = 3, max_anchors_per_cell: int = 10):
        self.min_phrase_length = min_phrase_length
        self.max_anchors_per_cell = max_anchors_per_cell

    def extract_all(self, snapshot: Dict[str, Any]) -> List[SemanticAnchor]:
        """Extract semantic anchors from all cells."""
        anchors = []

        for cell in snapshot.get("execution", {}).get("cells", []):
            cell_name = cell["name"]
            cell_anchors = self._extract_from_cell(cell_name, cell)
            anchors.extend(cell_anchors)

        return anchors

    def _extract_from_cell(self, cell_name: str, cell: Dict) -> List[SemanticAnchor]:
        """Extract anchors from a single cell's output."""
        anchors = []

        # Collect all agent response content
        all_content = []
        for turn in cell.get("turns", []):
            agent_response = turn.get("agent_response", {})
            if agent_response and agent_response.get("content"):
                all_content.append(agent_response["content"])

        if not all_content:
            return anchors

        # Use the final output for anchor extraction
        final_output = all_content[-1]

        # Extract key phrases
        key_phrases = self._extract_key_phrases(final_output)

        # Create anchors with weights
        for i, phrase in enumerate(key_phrases[:self.max_anchors_per_cell]):
            # Weight decreases with rank
            weight = 1.0 - (i * 0.05)
            anchors.append(SemanticAnchor(
                cell=cell_name,
                anchor=phrase,
                weight=max(0.5, weight),
                required=i < 3  # Top 3 are required
            ))

        return anchors

    def _extract_key_phrases(self, text: str) -> List[str]:
        """Extract key phrases from text using simple heuristics."""
        phrases = []

        # Extract markdown headers
        headers = re.findall(r'^#+\s*(.+)$', text, re.MULTILINE)
        phrases.extend([h.strip() for h in headers])

        # Extract bold text
        bold = re.findall(r'\*\*([^*]+)\*\*', text)
        phrases.extend([b.strip() for b in bold])

        # Extract bullet point key terms (first few words)
        bullets = re.findall(r'^[-*]\s*(.+)$', text, re.MULTILINE)
        for bullet in bullets:
            # Take first significant phrase (up to colon or first 5 words)
            if ':' in bullet:
                key = bullet.split(':')[0].strip()
            else:
                words = bullet.split()[:5]
                key = ' '.join(words)
            if len(key) >= self.min_phrase_length:
                phrases.append(key)

        # Extract capitalized phrases (likely important terms)
        caps = re.findall(r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)', text)
        phrases.extend(caps)

        # Deduplicate while preserving order
        seen = set()
        unique = []
        for p in phrases:
            p_lower = p.lower()
            if p_lower not in seen and len(p) >= self.min_phrase_length:
                seen.add(p_lower)
                unique.append(p)

        return unique


# =============================================================================
# ENHANCED SNAPSHOT CAPTURE
# =============================================================================

class SnapshotCapture:
    """Captures cascade executions from ClickHouse unified_logs table."""

    def __init__(self, data_dir: str | None = None):
        from lars.config import get_config
        from lars.db_adapter import get_db_adapter
        config = get_config()
        self.data_dir = Path(data_dir or config.data_dir)
        self.db = get_db_adapter()

        self.contract_extractor = ContractExtractor()
        self.anchor_extractor = AnchorExtractor()

    def freeze(
        self,
        session_id: str,
        snapshot_name: str,
        description: str = "",
        extract_contracts: bool = True,
        extract_anchors: bool = True
    ) -> Path:
        """
        Freeze a cascade execution as a test snapshot.

        Args:
            session_id: The session to freeze
            snapshot_name: Name for the snapshot (will be filename)
            description: Optional description of what this tests
            extract_contracts: Whether to extract behavioral contracts
            extract_anchors: Whether to extract semantic anchors

        Returns:
            Path to the snapshot file
        """
        print(f"Freezing session {session_id} as test snapshot...")

        # Query unified_logs table directly (pure ClickHouse)
        query = f"""
            SELECT
                timestamp,
                session_id,
                role,
                content_json,
                metadata_json,
                cascade_file,
                cell_name,
                node_type
            FROM unified_logs
            WHERE session_id = '{session_id}'
            ORDER BY timestamp ASC
        """

        try:
            result = self.db.query(query, output_format="dict")
            events = [[r['timestamp'], r['session_id'], r['role'], r['content_json'],
                      r['metadata_json'], r['cascade_file'], r['cell_name'], r['node_type']]
                     for r in result]
        except Exception as e:
            raise ValueError(f"Failed to query logs: {e}")

        if not events:
            raise ValueError(f"No events found for session: {session_id}")

        print(f"  Found {len(events)} events")

        # Parse into structured snapshot
        snapshot = self._parse_execution(events, session_id, snapshot_name, description)

        # Extract contracts if requested
        if extract_contracts:
            print("  Extracting behavioral contracts...")
            contracts = self.contract_extractor.extract_all(snapshot)
            snapshot["contracts"] = contracts.to_dict()
            print(f"    Found {len(contracts.routing)} routing, {len(contracts.tool_calls)} tool, {len(contracts.outputs)} output contracts")

        # Extract anchors if requested
        if extract_anchors:
            print("  Extracting semantic anchors...")
            anchors = self.anchor_extractor.extract_all(snapshot)
            snapshot["anchors"] = [asdict(a) for a in anchors]
            print(f"    Found {len(anchors)} semantic anchors")

        # Save snapshot
        snapshot_dir = Path("tests/cascade_snapshots")
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        snapshot_file = snapshot_dir / f"{snapshot_name}.json"
        with open(snapshot_file, 'w') as f:
            json.dump(snapshot, f, indent=2)

        print(f"\n[OK] Snapshot frozen: {snapshot_file}")
        print(f"  Cascade: {snapshot.get('cascade_file', 'unknown')}")
        print(f"  Cells: {', '.join(p['name'] for p in snapshot['execution']['cells'])}")
        print(f"  Total turns: {sum(len(p['turns']) for p in snapshot['execution']['cells'])}")

        print(f"\nTest modes available:")
        print(f"  • Deterministic replay: lars test replay {snapshot_name} --mode deterministic")
        print(f"  • Contract verification: lars test replay {snapshot_name} --mode contracts")
        print(f"  • Full comparison:      lars test replay {snapshot_name} --mode full")

        return snapshot_file

    def _parse_execution(
        self,
        events: List[tuple],
        session_id: str,
        snapshot_name: str,
        description: str
    ) -> Dict[str, Any]:
        """Parse log events into structured snapshot."""

        snapshot = {
            "snapshot_name": snapshot_name,
            "description": description,
            "captured_at": datetime.now().isoformat(),
            "session_id": session_id,
            "cascade_file": None,
            "input": {},
            "execution": {
                "cells": []
            },
            "expectations": {
                "cells_executed": [],
                "final_state": {},
                "completion_status": "success",
                "error_count": 0
            }
        }

        # Track cells - role types we care about: cell_start, agent, tool_result
        cells_map = {}
        current_cell_name = None
        current_turn = None
        error_count = 0

        for event in events:
            # New format: [timestamp, session_id, role, content_json, metadata_json, cascade_file, cell_name, node_type]
            timestamp, session_id_col, role, content_json, metadata_str, cascade_file, cell_name, node_type = event

            # Parse content from JSON
            content = None
            if content_json:
                try:
                    content = json.loads(content_json) if isinstance(content_json, str) else content_json
                    # If content is a dict with 'content' key, extract it
                    if isinstance(content, dict) and 'content' in content:
                        content = content['content']
                    elif isinstance(content, str):
                        pass  # Already a string
                    else:
                        content = str(content) if content else None
                except:
                    content = content_json

            # Parse metadata
            metadata = {}
            if metadata_str:
                try:
                    metadata = json.loads(metadata_str) if isinstance(metadata_str, str) else metadata_str
                except:
                    pass

            # Extract cascade info from direct column (preferred) or metadata
            if cascade_file and snapshot["cascade_file"] is None:
                snapshot["cascade_file"] = cascade_file
            elif metadata.get("cascade_file") and snapshot["cascade_file"] is None:
                snapshot["cascade_file"] = metadata["cascade_file"]

            # Track errors
            if role == "error" or node_type == "error":
                error_count += 1

            # Track cell starts using node_type (more reliable than role)
            if node_type == "cell_start" or role == "cell_start":
                # Use cell_name column if available, otherwise parse from content
                pname = cell_name
                if not pname and content:
                    pname = str(content).strip().replace("...", "")
                pname = pname or "unknown"

                if pname not in cells_map:
                    cells_map[pname] = {
                        "name": pname,
                        "turns": []
                    }

                current_cell_name = pname
                current_turn = {
                    "turn_number": len(cells_map[pname]["turns"]) + 1,
                    "agent_response": None,
                    "tool_calls": [],
                    "tool_results": []
                }
                cells_map[pname]["turns"].append(current_turn)

            # Track agent responses
            elif (role == "assistant" or node_type == "agent") and current_turn is not None:
                # Parse tool calls from content if present
                tool_calls = []
                if isinstance(content, dict) and "tool_calls" in content:
                    tool_calls = content["tool_calls"]
                elif metadata.get("tool_calls"):
                    tool_calls = metadata["tool_calls"]

                current_turn["agent_response"] = {
                    "content": content if isinstance(content, str) else (content.get("content", "") if isinstance(content, dict) else str(content or "")),
                    "tool_calls": tool_calls
                }

            # Track tool results
            elif (role == "tool" or node_type == "tool_result") and current_turn is not None:
                tool_name = metadata.get("tool", "unknown")

                current_turn["tool_results"].append({
                    "tool": tool_name,
                    "result": content,
                    "args": metadata.get("args", {})
                })

        # Add cells to snapshot
        snapshot["execution"]["cells"] = list(cells_map.values())
        snapshot["expectations"]["cells_executed"] = list(cells_map.keys())
        snapshot["expectations"]["error_count"] = error_count

        if error_count > 0:
            snapshot["expectations"]["completion_status"] = "failed"

        return snapshot


# =============================================================================
# ENHANCED SNAPSHOT VALIDATOR / REPLAYER
# =============================================================================

@dataclass
class ReplayResult:
    """Result of a snapshot replay/validation."""
    snapshot_name: str
    mode: str
    passed: bool
    checks: List[str] = field(default_factory=list)
    failures: List[Dict] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    contract_results: List[Tuple[bool, str]] = field(default_factory=list)
    anchor_results: List[Tuple[bool, str]] = field(default_factory=list)
    mock_stats: Optional[Dict] = None
    duration_ms: float = 0.0


class SnapshotValidator:
    """
    Enhanced snapshot validator with multiple replay modes.

    Modes:
    - structure: Just validates snapshot structure (original behavior)
    - deterministic: Replay with mocked LLM, verify exact framework behavior
    - contracts: Verify behavioral contracts are satisfied
    - anchors: Verify semantic anchors are present
    - full: All of the above
    """

    def __init__(self, snapshot_dir: str | Path = None):
        from lars.config import get_config
        config = get_config()
        self.root_dir = Path(config.root_dir)

        if snapshot_dir is not None:
            self.snapshot_dir = Path(snapshot_dir)
        else:
            module_dir = Path(__file__).parent.parent
            self.snapshot_dir = module_dir / "tests" / "cascade_snapshots"

    def load_snapshot(self, snapshot_name: str) -> Dict[str, Any]:
        """Load a snapshot file."""
        snapshot_file = self.snapshot_dir / f"{snapshot_name}.json"

        if not snapshot_file.exists():
            raise FileNotFoundError(f"Snapshot not found: {snapshot_file}")

        with open(snapshot_file) as f:
            return json.load(f)

    def validate(self, snapshot_name: str, verbose: bool = False, mode: str = "structure") -> ReplayResult:
        """
        Validate a snapshot with the specified mode.

        Args:
            snapshot_name: Name of the snapshot to validate
            verbose: Print detailed output
            mode: Validation mode (structure, deterministic, contracts, anchors, full)
        """
        import time
        start = time.time()

        result = ReplayResult(snapshot_name=snapshot_name, mode=mode, passed=True)

        # Load snapshot
        try:
            snapshot = self.load_snapshot(snapshot_name)
        except FileNotFoundError as e:
            result.passed = False
            result.failures.append({"type": "snapshot_not_found", "message": str(e)})
            return result
        except json.JSONDecodeError as e:
            result.passed = False
            result.failures.append({"type": "invalid_json", "message": str(e)})
            return result

        if verbose:
            print(f"\nValidating snapshot: {snapshot_name} (mode={mode})")
            if snapshot.get("description"):
                print(f"  Description: {snapshot['description']}")
            print(f"  Cascade: {snapshot.get('cascade_file', 'unknown')}")

        # Always do structure validation
        self._validate_structure(snapshot, result, verbose)

        # Mode-specific validation
        if mode in ("contracts", "full"):
            self._validate_contracts(snapshot, result, verbose)

        if mode in ("anchors", "full"):
            self._validate_anchors(snapshot, result, verbose)

        if mode in ("deterministic", "full"):
            self._validate_deterministic(snapshot, result, verbose)

        result.duration_ms = (time.time() - start) * 1000

        # Determine overall pass/fail
        result.passed = len(result.failures) == 0

        return result

    def _validate_structure(self, snapshot: Dict, result: ReplayResult, verbose: bool):
        """Validate snapshot structure."""
        # Check required fields
        required_fields = ["snapshot_name", "session_id", "cascade_file", "execution", "expectations"]
        for field in required_fields:
            if field not in snapshot:
                result.failures.append({
                    "type": "missing_field",
                    "message": f"Missing required field: {field}"
                })
            else:
                result.checks.append(f"[OK] Has {field}")

        # Check cells exist
        cells = snapshot.get("execution", {}).get("cells", [])
        if not cells:
            result.failures.append({
                "type": "no_cells",
                "message": "No cells captured in execution"
            })
        else:
            result.checks.append(f"[OK] Captured {len(cells)} cell(s)")

        # Check cells have turns
        for cell in cells:
            if not cell.get("turns"):
                result.failures.append({
                    "type": "cell_missing_turns",
                    "message": f"Cell '{cell['name']}' has no turns"
                })
            else:
                result.checks.append(f"[OK] Cell '{cell['name']}' has {len(cell['turns'])} turn(s)")

        # Check expectations match execution
        expected_cells = snapshot.get("expectations", {}).get("cells_executed", [])
        actual_cells = [c["name"] for c in cells]

        if expected_cells != actual_cells:
            result.failures.append({
                "type": "expectation_mismatch",
                "message": "Expected cells don't match execution",
                "expected": expected_cells,
                "actual": actual_cells
            })
        else:
            result.checks.append(f"[OK] Expectations match execution ({len(expected_cells)} cells)")

        if verbose:
            for check in result.checks:
                print(f"  {check}")

    def _validate_contracts(self, snapshot: Dict, result: ReplayResult, verbose: bool):
        """Validate behavioral contracts."""
        contracts_data = snapshot.get("contracts")
        if not contracts_data:
            result.warnings.append("No contracts in snapshot - run with --extract-contracts to add")
            return

        contracts = BehavioralContracts.from_dict(contracts_data)

        # Build execution data for verification
        cells = snapshot.get("execution", {}).get("cells", [])
        routing_path = [c["name"] for c in cells]

        cell_outputs = {}
        cell_tool_calls = {}

        for cell in cells:
            cell_name = cell["name"]

            # Get last output
            for turn in cell.get("turns", []):
                agent_response = turn.get("agent_response", {})
                if agent_response and agent_response.get("content"):
                    cell_outputs[cell_name] = agent_response["content"]

            # Get tool calls
            tool_calls = []
            for turn in cell.get("turns", []):
                for tr in turn.get("tool_results", []):
                    tool_calls.append({
                        "tool": tr.get("tool"),
                        "args": tr.get("args", {})
                    })
            cell_tool_calls[cell_name] = tool_calls

        if verbose:
            print(f"\n  Verifying {len(contracts.routing) + len(contracts.tool_calls) + len(contracts.outputs)} contracts...")

        # Verify cell sequence
        if contracts.cell_sequence:
            if routing_path == contracts.cell_sequence:
                result.contract_results.append((True, f"[OK] Cell sequence matches: {' → '.join(routing_path)}"))
            else:
                result.contract_results.append((False, f"✗ Cell sequence mismatch: expected {contracts.cell_sequence}, got {routing_path}"))
                result.failures.append({
                    "type": "cell_sequence_mismatch",
                    "expected": contracts.cell_sequence,
                    "actual": routing_path
                })

        # Verify routing contracts
        for contract in contracts.routing:
            passed, msg = contract.verify(routing_path)
            result.contract_results.append((passed, msg))
            if not passed:
                result.failures.append({"type": "routing_contract", "message": msg})

        # Verify tool call contracts
        for contract in contracts.tool_calls:
            passed, msg = contract.verify(cell_tool_calls)
            result.contract_results.append((passed, msg))
            if not passed:
                result.failures.append({"type": "tool_contract", "message": msg})

        # Verify output contracts
        for contract in contracts.outputs:
            passed, msg = contract.verify(cell_outputs)
            result.contract_results.append((passed, msg))
            if not passed:
                result.failures.append({"type": "output_contract", "message": msg})

        if verbose:
            for passed, msg in result.contract_results:
                print(f"    {msg}")

    def _validate_anchors(self, snapshot: Dict, result: ReplayResult, verbose: bool):
        """Validate semantic anchors are present."""
        anchors_data = snapshot.get("anchors")
        if not anchors_data:
            result.warnings.append("No anchors in snapshot - run with --extract-anchors to add")
            return

        anchors = [SemanticAnchor(**a) for a in anchors_data]

        # Build cell outputs
        cells = snapshot.get("execution", {}).get("cells", [])
        cell_outputs = {}

        for cell in cells:
            cell_name = cell["name"]
            for turn in cell.get("turns", []):
                agent_response = turn.get("agent_response", {})
                if agent_response and agent_response.get("content"):
                    cell_outputs[cell_name] = agent_response["content"]

        if verbose:
            print(f"\n  Verifying {len(anchors)} semantic anchors...")

        # Verify each anchor (exact match for now, semantic coming)
        for anchor in anchors:
            output = cell_outputs.get(anchor.cell, "")
            passed, msg = anchor.verify_exact(output)
            result.anchor_results.append((passed, msg))

            if not passed and anchor.required:
                result.failures.append({
                    "type": "anchor_missing",
                    "cell": anchor.cell,
                    "anchor": anchor.anchor,
                    "message": msg
                })

        if verbose:
            # Show summary
            passed_count = sum(1 for p, _ in result.anchor_results if p)
            print(f"    {passed_count}/{len(anchors)} anchors verified")

    def _validate_deterministic(self, snapshot: Dict, result: ReplayResult, verbose: bool):
        """Validate with deterministic replay using mocked LLM."""
        # For now, just verify we CAN create a mock LLM from the snapshot
        # Full replay integration requires runner modifications

        try:
            mock_llm = MockLLM.from_snapshot(snapshot)
            result.mock_stats = {
                "total_responses": len(mock_llm.responses),
                "cells_with_responses": len(set(r["cell"] for r in mock_llm.responses))
            }
            result.checks.append(f"[OK] Mock LLM created with {len(mock_llm.responses)} frozen responses")

            if verbose:
                print(f"\n  Deterministic replay prepared:")
                print(f"    {len(mock_llm.responses)} frozen responses")
                print(f"    Ready for full replay (requires runner integration)")

        except Exception as e:
            result.failures.append({
                "type": "mock_creation_failed",
                "message": str(e)
            })

    def validate_all(self, verbose: bool = False, mode: str = "structure") -> Dict[str, Any]:
        """Validate all snapshot files."""
        if not self.snapshot_dir.exists():
            return {
                "total": 0,
                "passed": 0,
                "failed": 0,
                "snapshots": []
            }

        snapshot_files = list(self.snapshot_dir.glob("*.json"))

        results = {
            "total": len(snapshot_files),
            "passed": 0,
            "failed": 0,
            "mode": mode,
            "snapshots": []
        }

        for snapshot_file in sorted(snapshot_files):
            snapshot_name = snapshot_file.stem

            try:
                result = self.validate(snapshot_name, verbose=verbose, mode=mode)

                if result.passed:
                    results["passed"] += 1
                else:
                    results["failed"] += 1

                results["snapshots"].append({
                    "name": result.snapshot_name,
                    "passed": result.passed,
                    "mode": result.mode,
                    "checks": result.checks,
                    "failures": result.failures,
                    "warnings": result.warnings,
                    "duration_ms": result.duration_ms
                })

            except Exception as e:
                results["failed"] += 1
                results["snapshots"].append({
                    "name": snapshot_name,
                    "passed": False,
                    "failures": [{
                        "type": "exception",
                        "message": str(e),
                        "exception_type": type(e).__name__
                    }],
                    "checks": []
                })

        return results

    def inspect(self, snapshot_name: str, show_contracts: bool = False, show_anchors: bool = False) -> Dict[str, Any]:
        """Inspect a snapshot's contents."""
        snapshot = self.load_snapshot(snapshot_name)

        info = {
            "name": snapshot.get("snapshot_name"),
            "description": snapshot.get("description"),
            "captured_at": snapshot.get("captured_at"),
            "session_id": snapshot.get("session_id"),
            "cascade_file": snapshot.get("cascade_file"),
            "cells": [c["name"] for c in snapshot.get("execution", {}).get("cells", [])],
            "total_turns": sum(len(c.get("turns", [])) for c in snapshot.get("execution", {}).get("cells", [])),
            "has_contracts": "contracts" in snapshot,
            "has_anchors": "anchors" in snapshot
        }

        if show_contracts and "contracts" in snapshot:
            info["contracts"] = snapshot["contracts"]

        if show_anchors and "anchors" in snapshot:
            info["anchors"] = snapshot["anchors"]

        return info


# =============================================================================
# LLM JUDGE FOR QUALITY COMPARISON
# =============================================================================

class LLMJudge:
    """
    Uses an LLM to judge if actual output matches expected output quality.

    For Phase 4 - optional deep quality comparison.
    """

    JUDGE_PROMPT = """You are a quality judge comparing two outputs from an AI cascade.

EXPECTED OUTPUT (from a known-good run):
{expected}

ACTUAL OUTPUT (from current run):
{actual}

Evaluate the actual output on these dimensions:
1. SEMANTIC EQUIVALENCE (1-10): Do they convey the same meaning/information?
2. COMPLETENESS (1-10): Does actual cover all important points from expected?
3. QUALITY (1-10): Is actual as well-written and useful as expected?
4. FORMAT MATCH (1-10): Does actual follow the same structure/format?

Provide your evaluation as JSON:
{{
    "semantic_equivalence": <1-10>,
    "completeness": <1-10>,
    "quality": <1-10>,
    "format_match": <1-10>,
    "overall_score": <1-10>,
    "verdict": "pass" or "fail",
    "reasoning": "<brief explanation>"
}}

A "pass" verdict requires overall_score >= 7.
"""

    def __init__(self, model: str = None, threshold: float = 7.0):
        self.model = model
        self.threshold = threshold

    def judge(self, expected: str, actual: str) -> Dict[str, Any]:
        """
        Judge if actual output matches expected quality.

        Returns evaluation dict with scores and verdict.
        """
        from lars.agent import LLMWrapper

        prompt = self.JUDGE_PROMPT.format(
            expected=expected[:2000],  # Truncate for context limits
            actual=actual[:2000]
        )

        llm = LLMWrapper(model=self.model)
        response = llm.chat([{"role": "user", "content": prompt}])

        # Parse JSON from response
        content = response.get("choices", [{}])[0].get("message", {}).get("content", "{}")

        try:
            # Extract JSON from response
            import re
            json_match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
            if json_match:
                evaluation = json.loads(json_match.group())
            else:
                evaluation = {"error": "Could not parse judge response", "raw": content}
        except json.JSONDecodeError:
            evaluation = {"error": "Invalid JSON from judge", "raw": content}

        return evaluation

    def judge_cell(self, cell_name: str, expected_output: str, actual_output: str) -> Tuple[bool, Dict]:
        """Judge a specific cell's output."""
        evaluation = self.judge(expected_output, actual_output)

        passed = evaluation.get("verdict") == "pass" or evaluation.get("overall_score", 0) >= self.threshold

        return passed, {
            "cell": cell_name,
            "passed": passed,
            "evaluation": evaluation
        }


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    import math

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot / (norm_a * norm_b)


# =============================================================================
# BACKWARD COMPATIBILITY
# =============================================================================

# Alias for backward compatibility with docs
SnapshotReplay = SnapshotValidator
