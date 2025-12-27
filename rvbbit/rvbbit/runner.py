import os
import sys
import json
from typing import Dict, Any, Optional, List, Union, Callable
from contextvars import ContextVar
import logging
import litellm
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.spinner import Spinner
import threading

# Context variable for current hooks - allows tools to call hook methods
_current_hooks: ContextVar[Optional['RVBBITHooks']] = ContextVar('current_hooks', default=None)

def get_current_hooks() -> Optional['RVBBITHooks']:
    """Get the current hooks from context."""
    return _current_hooks.get()

def set_current_hooks(hooks: Optional['RVBBITHooks']):
    """Set the current hooks in context."""
    _current_hooks.set(hooks)

# We assume these imports exist or are provided by the environment
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

from .cascade import load_cascade_config, CascadeConfig, CellConfig, AsyncCascadeRef, HandoffConfig, ContextConfig, ContextSourceConfig, HumanInputConfig, AudibleConfig, DecisionPointConfig, IntraPhaseContextConfig, AutoFixConfig, PolyglotValidatorConfig
from .auto_context import IntraPhaseContextBuilder, IntraContextConfig, ContextSelectionStats
import re
from .echo import get_echo, Echo
from .checkpoints import get_checkpoint_manager, CheckpointType, CheckpointStatus, TraceContext
from .human_ui import UIGenerator, normalize_human_input_config, generate_simple_ui
from .config import get_config
from .trait_registry import get_trait
from .logs import log_message
from .traits.base import create_eddy

console = Console()

from .agent import Agent
from .utils import get_tool_schema, encode_image_base64, compute_species_hash
from .tracing import TraceNode, set_current_trace
from .visualizer import generate_mermaid
from .prompts import render_instruction
from .artifact_resolver import enrich_outputs_with_artifacts, convert_to_multimodal_content
from .state import update_session_state, update_phase_progress, clear_phase_progress
from .session_state import (
    get_session_state_manager, create_session as create_session_state,
    update_session_status, session_heartbeat, is_session_cancelled,
    SessionStatus, BlockedType
)
from .traits.system import spawn_cascade
from .traits.state_tools import set_current_session_id, set_current_cell_name, set_current_cascade_id, set_current_candidate_index
from .traits.research_db import set_current_research_db
from .rag.indexer import ensure_rag_index
from .rag.context import set_current_rag_context, clear_current_rag_context
from .browser_manager import (
    BrowserSession, BrowserSessionManager,
    create_browser_session, close_browser_session, get_browser_manager
)
# NOTE: Old cost.py track_request() no longer used - cost tracking via unified_logs.py

from rich.tree import Tree


def _format_validator_name(validator_spec) -> str:
    """
    Format a validator spec for display/logging.
    Handles: string (cascade name), or PolyglotValidatorConfig object.
    """
    if isinstance(validator_spec, str):
        return validator_spec
    if isinstance(validator_spec, PolyglotValidatorConfig):
        if validator_spec.python:
            return "python (inline)"
        if validator_spec.javascript:
            return "javascript (inline)"
        if validator_spec.sql:
            return "sql (inline)"
        if validator_spec.clojure:
            return "clojure (inline)"
        if validator_spec.bash:
            return "bash (inline)"
        if validator_spec.tool:
            return f"{validator_spec.tool} (inline)"
        return "polyglot (inline)"
    return str(validator_spec)


class HookAction:
    CONTINUE = "continue"
    PAUSE = "pause"
    INJECT = "inject"


class RVBBITHooks:
    """Base class for RVBBIT lifecycle hooks"""

    def on_cascade_start(self, cascade_id: str, session_id: str, context: dict) -> dict:
        """Called when cascade execution begins"""
        return {"action": HookAction.CONTINUE}

    def on_cascade_complete(self, cascade_id: str, session_id: str, result: dict) -> dict:
        """Called when cascade execution completes successfully"""
        return {"action": HookAction.CONTINUE}

    def on_cascade_error(self, cascade_id: str, session_id: str, error: Exception) -> dict:
        """Called when cascade execution fails"""
        return {"action": HookAction.CONTINUE}

    def on_phase_start(self, cell_name: str, context: dict) -> dict:
        """Called when phase execution begins"""
        return {"action": HookAction.CONTINUE}

    def on_phase_complete(self, cell_name: str, session_id: str, result: dict) -> dict:
        """Called when phase execution completes"""
        return {"action": HookAction.CONTINUE}

    def on_turn_start(self, cell_name: str, turn_index: int, context: dict) -> dict:
        """Called when a turn begins"""
        return {"action": HookAction.CONTINUE}

    def on_tool_call(self, tool_name: str, cell_name: str, session_id: str, args: dict) -> dict:
        """Called when a tool is invoked"""
        return {"action": HookAction.CONTINUE}

    def on_tool_result(self, tool_name: str, cell_name: str, session_id: str, result: Any) -> dict:
        """Called when a tool returns a result"""
        return {"action": HookAction.CONTINUE}

    def on_checkpoint_suspended(self, session_id: str, checkpoint_id: str, checkpoint_type: str,
                                cell_name: str, message: str = None, cascade_id: str = None) -> dict:
        """Called when cascade is suspended waiting for human input"""
        return {"action": HookAction.CONTINUE}

    def on_checkpoint_resumed(self, session_id: str, checkpoint_id: str, cell_name: str,
                              response: Any = None) -> dict:
        """Called when checkpoint is resumed with human input"""
        return {"action": HookAction.CONTINUE}

class RVBBITRunner:
    def __init__(self, config_path: str | dict, session_id: str = "default", overrides: dict = None,
                 depth: int = 0, parent_trace: TraceNode = None, hooks: RVBBITHooks = None,
                 candidate_index: int = None, parent_session_id: str = None,
                 caller_id: str = None, invocation_metadata: dict = None):
        self.config_path = config_path
        self.config = load_cascade_config(config_path)
        self.session_id = session_id
        self.overrides = overrides or {}

        # Get or create Echo with caller tracking
        self.echo = get_echo(session_id, parent_session_id=parent_session_id,
                            caller_id=caller_id, invocation_metadata=invocation_metadata)

        # Store caller tracking for propagation
        self.caller_id = caller_id
        self.invocation_metadata = invocation_metadata

        self.depth = depth
        self.max_depth = 5
        self.hooks = hooks or RVBBITHooks()
        self.context_messages: List[Dict[str, str]] = []
        self.candidate_index = candidate_index  # Track which candidate attempt this is (for cascade-level soundings)
        self.current_phase_candidate_index = None  # Track candidate index within current phase
        self.current_reforge_step = None  # Track which reforge step we're in
        self.current_winning_candidate_index = None  # Track which initial candidate won (for reforge)
        self.current_retry_attempt = None  # Track retry/validation attempt index
        self.current_turn_number = None  # Track turn number within phase (for max_turns)
        self.current_mutation_applied = None  # Track mutation applied to current candidate
        self.current_mutation_type = None  # Track mutation type: 'rewrite', 'augment', 'approach'
        self.current_mutation_template = None  # Track mutation template (for rewrite: instruction used)
        self.parent_session_id = parent_session_id  # Track parent session for sub-cascades
        
        # Tracing
        if parent_trace:
            self.trace = parent_trace.create_child("cascade", self.config.cascade_id)
        else:
            self.trace = TraceNode("cascade", self.config.cascade_id)

        # Provider config
        self.base_url = self.overrides.get("base_url", get_config().provider_base_url)
        self.api_key = self.overrides.get("api_key", get_config().provider_api_key)
        self.model = self.overrides.get("model", get_config().default_model)

        # Configure litellm if needed
        if self.api_key:
            os.environ["OPENROUTER_API_KEY"] = self.api_key

        # Graph path
        self.graph_path = os.path.join(get_config().graph_dir, f"{self.session_id}.mmd")

        # Token budget manager (if configured)
        if self.config.token_budget:
            from .token_budget import TokenBudgetManager
            self.token_manager = TokenBudgetManager(self.config.token_budget, self.model)
        else:
            self.token_manager = None

        # Tool cache (if configured)
        if self.config.tool_caching and self.config.tool_caching.enabled:
            from .tool_cache import ToolCache
            self.tool_cache = ToolCache(self.config.tool_caching)
        else:
            self.tool_cache = None

        # Memory system (if configured)
        self.memory_name = self.config.memory  # Store memory bank name if configured
        if self.memory_name:
            from .memory import get_memory_system
            self.memory_system = get_memory_system()
            # Set callback on echo to save messages
            self.echo.set_message_callback(self._save_to_memory)
        else:
            self.memory_system = None

        # Audible system state
        self._audible_signal = threading.Event()  # Set when UI signals an audible
        self._audible_budget_used = {}  # cell_name -> count of audibles used
        self._audible_lock = threading.Lock()

        # Narrator config (cascade-level, can be overridden per-phase)
        self.cascade_narrator = self.config.narrator if hasattr(self.config, 'narrator') else None
        self._narrator_service = None  # Will be initialized in run() if configured

        # Auto-context system for intelligent context management
        self._intra_context_builder: Optional[IntraPhaseContextBuilder] = None
        self._loop_validation_failures: List[Dict] = []  # Track failures for loop compression

        # Heartbeat system for durable execution
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._heartbeat_running = False
        self._heartbeat_interval = 30  # seconds

    def _log(self, **kwargs):
        """Helper to log with automatic caller tracking fields."""
        from .unified_logs import log_unified
        log_unified(
            caller_id=self.caller_id,
            invocation_metadata=self.invocation_metadata,
            **kwargs
        )

    def _save_to_memory(self, message: dict):
        """
        Save a message to the configured memory bank.

        Args:
            message: Message dict with role, content, etc.
        """
        # Only save if memory is configured and we're not in a candidate (non-winners aren't canon)
        if not self.memory_name or not self.memory_system:
            return

        # Skip saving losing soundings (they're alternate universes, not canon)
        if self.current_phase_candidate_index is not None or self.candidate_index is not None:
            # We're inside soundings - don't save until we know if we're a winner
            return

        # NOTE: No longer filtering system messages - we want to see ALL messages
        # to diagnose root causes instead of hiding symptoms
        role = message.get('role')
        content = message.get('content')
        if not content or (isinstance(content, str) and not content.strip()):
            return

        # Build metadata
        metadata = {
            'session_id': self.session_id,
            'cascade_id': self.config.cascade_id,
            'cascade_file': str(self.config_path) if isinstance(self.config_path, str) else 'inline',
            'cell_name': self.echo._current_cell_name or 'unknown',
            'timestamp': None,  # Will be set by memory system
        }

        # Add tool call info if present
        if 'tool_calls' in message:
            metadata['tool_calls'] = message['tool_calls']

        try:
            self.memory_system.save_message(
                memory_name=self.memory_name,
                message=message,
                metadata=metadata
            )
        except Exception as e:
            # Don't crash cascade if memory save fails
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to save message to memory '{self.memory_name}': {e}")

    # =========================================================================
    # Heartbeat System - Durable Execution
    # =========================================================================

    def _start_heartbeat(self):
        """Start the heartbeat thread for zombie detection."""
        if self._heartbeat_running:
            return

        self._heartbeat_running = True
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()

    def _stop_heartbeat(self):
        """Stop the heartbeat thread."""
        self._heartbeat_running = False
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=2)
        self._heartbeat_thread = None

    def _heartbeat_loop(self):
        """Background heartbeat loop - proves session is still alive."""
        import time

        while self._heartbeat_running:
            try:
                session_heartbeat(self.session_id)
            except Exception as e:
                # Don't crash on heartbeat failure - just log
                logger = logging.getLogger(__name__)
                logger.debug(f"Heartbeat failed for {self.session_id}: {e}")

            # Sleep in small increments to allow quick shutdown
            for _ in range(self._heartbeat_interval):
                if not self._heartbeat_running:
                    break
                time.sleep(1)

    def _start_narrator_service(self, input_data: dict = None):
        """Start the event-driven narrator service."""
        from .narrator_service import NarratorService, check_tts_available
        from .events import get_event_bus

        # Check if TTS is available
        if not check_tts_available():
            log_message(self.session_id, "narrator", "Narrator skipped: TTS not configured (missing ELEVENLABS keys)")
            return

        try:
            self._narrator_service = NarratorService(
                config=self.cascade_narrator,
                session_id=self.session_id,
                cascade_id=self.config.cascade_id,
                parent_session_id=self.parent_session_id,
                cascade_input=input_data,  # Pass original cascade input for template access
                echo=self.echo,  # Pass echo for polling mode
            )
            self._narrator_service.start(get_event_bus())
            log_message(self.session_id, "narrator", "Narrator service started",
                       metadata={"on_events": self.cascade_narrator.effective_on_events})
        except Exception as e:
            log_message(self.session_id, "narrator_error", f"Failed to start narrator: {e}")
            self._narrator_service = None

    def _stop_narrator_service(self):
        """Stop the narrator service."""
        if self._narrator_service:
            try:
                self._narrator_service.stop()
                log_message(self.session_id, "narrator", "Narrator service stopped")
            except Exception as e:
                log_message(self.session_id, "narrator_error", f"Failed to stop narrator: {e}")
            self._narrator_service = None

    def _publish_event(self, event_type: str, data: dict):
        """Publish an event to the event bus for narrator and other subscribers."""
        from .events import get_event_bus, Event
        from datetime import datetime

        event_bus = get_event_bus()
        event_bus.publish(Event(
            type=event_type,
            session_id=self.session_id,
            timestamp=datetime.now().isoformat(),
            data=data
        ))

    def _check_cancellation(self) -> bool:
        """
        Check if cancellation was requested for this session.

        Called between phases to allow graceful cancellation.
        Returns True if cascade should stop.
        """
        try:
            if is_session_cancelled(self.session_id):
                # Update status to cancelled
                try:
                    update_session_status(self.session_id, SessionStatus.CANCELLED)
                except Exception:
                    pass
                return True
        except Exception as e:
            # Don't fail cascade if cancellation check fails
            logger = logging.getLogger(__name__)
            logger.debug(f"Cancellation check failed for {self.session_id}: {e}")
        return False

    # =========================================================================
    # Parallel Phase Execution
    # =========================================================================

    def _analyze_cell_dependencies(self) -> Dict[str, set]:
        """
        Analyze all phases to build a dependency graph.

        Returns:
            Dict mapping cell_name -> set of phase names it depends on.
            A phase with an empty set has no dependencies (can run immediately).

        Dependencies are detected from:
        1. context.from - explicit phase references
        2. Template variables - {{ outputs.cell_name }} or {{ state.output_cell_name }}
        3. Handoffs pointing TO this phase (reverse lookup)
        """
        import re

        dependencies = {}
        cell_names = {p.name for p in self.config.cells}

        # Pattern to match template variables referencing outputs
        # Matches: {{ outputs.cell_name }} or {{ state.output_cell_name }}
        outputs_pattern = re.compile(r'\{\{\s*outputs\.(\w+)\s*\}\}')
        state_output_pattern = re.compile(r'\{\{\s*state\.output_(\w+)\s*\}\}')

        for cell in self.config.cells:
            deps = set()

            # 1. Check context.from for explicit dependencies
            if cell.context and cell.context.from_:
                for source in cell.context.from_:
                    source_name = source if isinstance(source, str) else getattr(source, 'phase', None)
                    if source_name:
                        # Handle special keywords
                        if source_name == "all":
                            # Depends on ALL prior phases in definition order
                            for p in self.config.cells:
                                if p.name == cell.name:
                                    break
                                deps.add(p.name)
                        elif source_name == "previous":
                            # Find the phase defined before this one
                            prev_phase = None
                            for p in self.config.cells:
                                if p.name == cell.name:
                                    break
                                prev_phase = p.name
                            if prev_phase:
                                deps.add(prev_phase)
                        elif source_name == "first":
                            # First phase
                            if self.config.cells:
                                deps.add(self.config.cells[0].name)
                        elif source_name in cell_names:
                            deps.add(source_name)

            # 2. Check instructions for template variable references
            if cell.instructions:
                # Find {{ outputs.X }} references
                for match in outputs_pattern.finditer(cell.instructions):
                    ref_phase = match.group(1)
                    if ref_phase in cell_names and ref_phase != cell.name:
                        deps.add(ref_phase)

                # Find {{ state.output_X }} references
                for match in state_output_pattern.finditer(cell.instructions):
                    ref_phase = match.group(1)
                    if ref_phase in cell_names and ref_phase != cell.name:
                        deps.add(ref_phase)

            # 3. Check soundings.factor for template variable references (for dynamic factors)
            if cell.candidates and isinstance(cell.candidates.factor, str):
                # Find {{ outputs.X }} references in soundings.factor
                for match in outputs_pattern.finditer(cell.candidates.factor):
                    ref_phase = match.group(1)
                    if ref_phase in cell_names and ref_phase != cell.name:
                        deps.add(ref_phase)

                # Find {{ state.output_X }} references in soundings.factor
                for match in state_output_pattern.finditer(cell.candidates.factor):
                    ref_phase = match.group(1)
                    if ref_phase in cell_names and ref_phase != cell.name:
                        deps.add(ref_phase)

            dependencies[cell.name] = deps

        return dependencies

    def _can_run_phases_parallel(self) -> bool:
        """
        Check if this cascade can benefit from parallel phase execution.

        Returns True if:
        - There are multiple phases
        - No phases have handoffs (handoffs imply sequential/routing logic)
        - At least 2 phases have no dependencies on each other

        Returns False if:
        - Single phase cascade
        - Any phase has handoffs (explicit routing)
        - All phases depend on previous phases (linear chain)
        """
        cells = self.config.cells
        if len(cells) <= 1:
            return False

        # If any cell has handoffs, use sequential execution
        for cell in cells:
            if cell.handoffs:
                return False

        # Analyze dependencies
        deps = self._analyze_cell_dependencies()

        # Count cells with no dependencies
        root_cells = [name for name, dep_set in deps.items() if not dep_set]

        # If we have 2+ root cells, parallel execution makes sense
        return len(root_cells) >= 2

    def _execute_phases_parallel(self, input_data: dict) -> dict:
        """
        Execute phases in parallel based on their dependencies.

        Uses a DAG-based execution model:
        1. Find all phases with satisfied dependencies (initially: root phases)
        2. Execute them in parallel using ThreadPoolExecutor
        3. When phases complete, check if new phases are unblocked
        4. Continue until all phases complete

        Returns the combined echo result.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import copy

        indent = "  " * self.depth
        console.print(f"{indent}[bold magenta]⚡ Parallel execution mode enabled[/bold magenta]")

        # Build dependency graph
        dependencies = self._analyze_cell_dependencies()
        phase_map = {p.name: p for p in self.config.cells}

        # Track state
        completed = set()
        results = {}  # cell_name -> result
        running = {}  # cell_name -> Future

        # Snapshot context for thread safety
        echo_state_snapshot = copy.deepcopy(self.echo.state)

        # Determine max workers (like soundings)
        max_workers = min(len(self.config.cells), 5)

        def execute_single_phase(cell_name: str, phase_input: dict) -> dict:
            """Execute a single phase in a worker thread."""
            cell = phase_map[cell_name]

            # Set thread-local context vars
            session_token = set_current_session_id(self.session_id)
            phase_token = set_current_cell_name(cell.name)
            cascade_token = set_current_cascade_id(self.config.cascade_id)

            try:
                # Create trace for this phase
                phase_trace = self.trace.create_child("phase", cell.name)

                # Hook: Phase Start (emits SSE event)
                self.hooks.on_phase_start(cell.name, {
                    "echo": self.echo,
                    "input": phase_input,
                    "parallel_execution": True,
                })

                # Publish phase_start event
                self._publish_event("phase_start", {
                    "cell_name": cell.name,
                    "cascade_id": self.config.cascade_id,
                    "parallel_execution": True,
                })

                # Log phase start
                log_message(self.session_id, "system", f"Phase {cell.name} starting (parallel)",
                           trace_id=phase_trace.id, parent_id=phase_trace.parent_id,
                           node_type="phase", depth=self.depth, cell_name=cell.name,
                           cascade_id=self.config.cascade_id)

                # Execute the phase with timing
                import time as time_module
                phase_start_time = time_module.time()
                result = self.execute_phase(cell, phase_input, phase_trace)
                phase_duration_ms = (time_module.time() - phase_start_time) * 1000

                # Store in echo state (thread-safe for simple dict updates)
                self.echo.state[f"output_{cell.name}"] = result

                # Add to lineage
                self.echo.add_lineage(cell.name, result, trace_id=phase_trace.id)

                # Hook: Phase Complete (emits SSE event)
                # In parallel execution, ALWAYS call this to ensure phase_complete is logged
                self.hooks.on_phase_complete(cell.name, self.session_id, {
                    "output": result,
                    "duration_ms": phase_duration_ms,
                })

                # Log phase completion to unified_logs
                log_message(
                    self.session_id,
                    "phase_complete",
                    f"Phase {cell.name} completed",
                    trace_id=phase_trace.id,
                    cell_name=cell.name,
                    cascade_id=self.config.cascade_id,
                    duration_ms=phase_duration_ms
                )

                return {
                    "cell_name": cell.name,
                    "result": result,
                    "success": True,
                }
            except Exception as e:
                console.print(f"{indent}  [red]✗ Phase {cell.name} failed: {e}[/red]")
                return {
                    "cell_name": cell.name,
                    "error": str(e),
                    "success": False,
                }
            finally:
                # Reset context vars
                set_current_session_id(None)
                set_current_cell_name(None)
                set_current_cascade_id(None)

        def get_runnable_phases() -> List[str]:
            """Find phases that can run (dependencies satisfied, not running/completed)."""
            runnable = []
            for cell_name, deps in dependencies.items():
                if cell_name in completed:
                    continue
                if cell_name in running:
                    continue
                if deps.issubset(completed):
                    runnable.append(cell_name)
            return runnable

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            while len(completed) < len(self.config.cells):
                # Check for cancellation
                if self._check_cancellation():
                    console.print(f"{indent}[bold yellow]⚠ Cascade cancelled during parallel execution[/bold yellow]")
                    break

                # Find phases that can run now
                runnable = get_runnable_phases()

                # Submit runnable phases
                for cell_name in runnable:
                    console.print(f"{indent}  [cyan]▶ Starting: {cell_name}[/cyan]")
                    future = executor.submit(execute_single_phase, cell_name, input_data)
                    running[cell_name] = future

                if not running:
                    # No phases running and none runnable - we're done or stuck
                    break

                # Wait for at least one phase to complete
                from concurrent.futures import wait, FIRST_COMPLETED
                done, _ = wait(running.values(), return_when=FIRST_COMPLETED)

                # Process completed phases
                for future in done:
                    result = future.result()
                    cell_name = result["cell_name"]

                    completed.add(cell_name)
                    results[cell_name] = result
                    del running[cell_name]

                    if result["success"]:
                        console.print(f"{indent}  [green]✓ Completed: {cell_name}[/green]")
                    else:
                        console.print(f"{indent}  [red]✗ Failed: {cell_name}[/red]")

        console.print(f"{indent}[bold magenta]⚡ Parallel execution complete: {len(completed)}/{len(self.config.cells)} phases[/bold magenta]")

        return self.echo.get_full_echo()

    def _get_metadata(self, extra: dict = None, semantic_actor: str = None, semantic_purpose: str = None) -> dict:
        """
        Helper to build metadata dict with candidate_index and semantic fields automatically included.
        Use this in all echo.add_history() calls to ensure consistent tagging.

        Semantic Actors (WHO is speaking):
            - main_agent: Primary LLM doing phase work
            - sounding_agent: Main agent in a candidate attempt
            - reforge_agent: Main agent in a reforge iteration
            - evaluator: LLM judging soundings/reforge quality
            - quartermaster: LLM selecting tools
            - validator: LLM/function checking output (wards, loop_until)
            - mutator: LLM rewriting prompts for mutation
            - human: Human-in-the-loop input
            - framework: System-generated metadata/lifecycle

        Semantic Purposes (WHAT is this message for):
            - instructions: Phase system prompt
            - task_input: The actual work request
            - context_injection: Prior phase context being injected
            - tool_request: Agent calling a tool
            - tool_response: Tool returning result
            - continuation: Turn follow-up prompt
            - refinement: Reforge honing prompt
            - validation_input: What's being validated
            - validation_output: Pass/fail verdict
            - evaluation_input: Sounding attempts being compared
            - evaluation_output: Winner selection decision
            - winner_selection: Selected winning output marked
            - lifecycle: Start/complete markers
            - error: Error messages
        """
        meta = extra.copy() if extra else {}

        # Auto-inject candidate_index if we're in a candidate
        if self.current_phase_candidate_index is not None:
            meta.setdefault("candidate_index", self.current_phase_candidate_index)
        elif self.candidate_index is not None:
            meta.setdefault("candidate_index", self.candidate_index)

        # Auto-inject reforge_step if we're in reforge
        if hasattr(self, 'current_reforge_step') and self.current_reforge_step is not None:
            meta.setdefault("reforge_step", self.current_reforge_step)

        # Auto-inject winning_candidate_index if we're in reforge
        if hasattr(self, 'current_winning_candidate_index') and self.current_winning_candidate_index is not None:
            meta.setdefault("winning_candidate_index", self.current_winning_candidate_index)

        # Add semantic classification if provided
        if semantic_actor:
            meta["semantic_actor"] = semantic_actor
        if semantic_purpose:
            meta["semantic_purpose"] = semantic_purpose

        # Auto-derive semantic_actor from context if not explicitly set
        if "semantic_actor" not in meta:
            if hasattr(self, 'current_reforge_step') and self.current_reforge_step is not None:
                meta["semantic_actor"] = "reforge_agent"
            elif self.current_phase_candidate_index is not None or self.candidate_index is not None:
                meta["semantic_actor"] = "sounding_agent"

        return meta

    def _get_callout_config(self, phase):
        """
        Get normalized callout config from phase.

        Handles shorthand: callouts="Result" → CalloutsConfig(output="Result")

        Returns CalloutsConfig or None
        """
        from .cascade import CalloutsConfig

        if not phase.callouts:
            return None

        # String shorthand: convert to CalloutsConfig with output set
        if isinstance(phase.callouts, str):
            return CalloutsConfig(output=phase.callouts)

        return phase.callouts

    def _should_tag_as_callout(self, phase, message_type: str, turn_number: int = None) -> tuple:
        """
        Check if a message should be tagged as a callout based on phase config.

        Args:
            phase: CellConfig object
            message_type: 'output' or 'assistant_message'
            turn_number: Current turn number (for message filtering)

        Returns:
            (should_tag: bool, template: str or None)
        """
        callout_config = self._get_callout_config(phase)
        if not callout_config:
            return False, None

        if message_type == 'output' and callout_config.output:
            return True, callout_config.output

        if message_type == 'assistant_message':
            # Priority: messages config, fallback to output (for shorthand syntax)
            if callout_config.messages:
                # Check messages_filter to see if this message qualifies
                # For now, assistant_only is default and we're already filtering to assistant messages
                # TODO: Implement last_turn filter if needed
                return True, callout_config.messages
            elif callout_config.output:
                # Fallback: use output template for shorthand syntax
                return True, callout_config.output

        return False, None

    def _render_callout_name(self, template: str, phase, input_data: dict, turn_number: int = None) -> str:
        """
        Render a callout name template with Jinja2.

        Available context:
        - input.*: Original cascade input
        - state.*: Current state variables
        - turn: Current turn number
        - phase: Current phase name

        Args:
            template: Jinja2 template string
            phase: CellConfig object
            input_data: Cascade input data
            turn_number: Current turn number

        Returns:
            Rendered callout name
        """
        from .prompts import render_instruction

        # Build render context similar to instruction rendering
        render_context = {
            "input": input_data,
            "state": self.echo.state,
            "turn": turn_number if turn_number is not None else 0,
            "cell": phase.name,
        }

        try:
            return render_instruction(template, render_context)
        except Exception as e:
            # Fallback to template if rendering fails
            print(f"[Callout] Failed to render callout name template: {e}")
            return template

    def _message_has_images(self, msg: dict) -> bool:
        """
        Check if a message contains images (base64 or image_url format).
        Used for logging metadata about context injection.
        """
        content = msg.get("content")
        if isinstance(content, list):
            # Multi-modal content - check for image_url type
            return any(
                isinstance(item, dict) and item.get("type") == "image_url"
                for item in content
            )
        elif isinstance(content, str):
            # Check for embedded base64 data URLs
            return "data:image/" in content
        return False

    # ========== AUTO-CONTEXT SYSTEM ==========

    def _get_intra_context_config(self, phase: CellConfig) -> IntraContextConfig:
        """
        Get the intra-phase auto-context config for a phase.

        Priority:
        1. Phase-level intra_context config
        2. Cascade-level auto_context.intra_phase config
        3. Default config (enabled with sensible defaults)

        Args:
            phase: The phase config

        Returns:
            IntraContextConfig dataclass for use with IntraPhaseContextBuilder
        """
        # Phase-level override takes precedence
        if phase.intra_context:
            return IntraContextConfig(
                enabled=phase.intra_context.enabled,
                window=phase.intra_context.window,
                mask_observations_after=phase.intra_context.mask_observations_after,
                compress_loops=phase.intra_context.compress_loops,
                loop_history_limit=phase.intra_context.loop_history_limit,
                preserve_reasoning=phase.intra_context.preserve_reasoning,
                preserve_errors=phase.intra_context.preserve_errors,
                min_masked_size=phase.intra_context.min_masked_size,
            )

        # Cascade-level default
        if self.config.auto_context and self.config.auto_context.intra_phase:
            cfg = self.config.auto_context.intra_phase
            return IntraContextConfig(
                enabled=cfg.enabled,
                window=cfg.window,
                mask_observations_after=cfg.mask_observations_after,
                compress_loops=cfg.compress_loops,
                loop_history_limit=cfg.loop_history_limit,
                preserve_reasoning=cfg.preserve_reasoning,
                preserve_errors=cfg.preserve_errors,
                min_masked_size=cfg.min_masked_size,
            )

        # Default: disabled for now to ensure backward compatibility
        # Users must explicitly enable via phase or cascade config
        return IntraContextConfig(enabled=False)

    def _get_or_create_intra_context_builder(self, phase: CellConfig) -> IntraPhaseContextBuilder:
        """
        Get or create the intra-phase context builder for a phase.

        Creates a new builder with the phase's config if one doesn't exist
        or if the config has changed.
        """
        config = self._get_intra_context_config(phase)

        # Create or update builder
        if self._intra_context_builder is None:
            self._intra_context_builder = IntraPhaseContextBuilder(config)
        else:
            # Update config if it changed
            self._intra_context_builder.config = config

        return self._intra_context_builder

    def _build_turn_context(
        self,
        phase: CellConfig,
        turn_number: int,
        is_loop_retry: bool = False
    ) -> tuple:
        """
        Build context for a single turn using auto-context system.

        This wraps the IntraPhaseContextBuilder and handles:
        - Getting the right config for the phase
        - Passing loop validation failures
        - Logging context selection stats

        Args:
            phase: The phase config
            turn_number: Current turn number (0-indexed)
            is_loop_retry: Whether this is a loop_until retry

        Returns:
            Tuple of (context_messages, stats)
        """
        builder = self._get_or_create_intra_context_builder(phase)

        # Build context
        context, stats = builder.build_turn_context(
            full_history=self.context_messages,
            turn_number=turn_number,
            is_loop_retry=is_loop_retry,
            loop_validation_failures=self._loop_validation_failures
        )

        return context, stats

    def _log_context_selection(
        self,
        phase: CellConfig,
        turn_number: int,
        stats: ContextSelectionStats,
        trace: TraceNode
    ):
        """Log context selection decision for observability."""
        # Add structural message for intra-phase context selection
        compression_pct = round((1 - stats.compression_ratio) * 100) if stats.compression_ratio < 1 else 0
        selection_emoji = "🗜️" if stats.selection_type == "standard" else "🔄" if stats.selection_type == "loop_retry" else "📝"

        # Create a child trace for context selection to avoid token duplication
        # (cost updates propagate by trace_id, so structural entries need their own ID)
        ctx_trace = trace.create_child("intra_context", "selection") if trace else None

        self.echo.add_history({
            "role": "structure",
            "content": (
                f"{selection_emoji} Intra-Phase Auto-Context (Turn {turn_number + 1})\n"
                f"   Type: {stats.selection_type}\n"
                f"   Messages: {stats.context_size}/{stats.full_history_size} "
                f"(masked: {stats.masked_count}, preserved: {stats.preserved_count})\n"
                f"   Tokens: ~{stats.tokens_estimated_after:,}/{stats.tokens_estimated_before:,} "
                f"(saved: ~{stats.tokens_saved:,}, {compression_pct}% reduction)"
            ),
            "node_type": "intra_context_selection"
        }, trace_id=ctx_trace.id if ctx_trace else None, parent_id=trace.id if trace else None,
           node_type="intra_context_selection",
           metadata={
               "cell_name": phase.name,
               "cascade_id": self.config.cascade_id,
               "turn_number": turn_number,
               "semantic_actor": "auto_context",
               "semantic_purpose": "intra_phase_selection",
               "selection_type": stats.selection_type,
               "full_history_size": stats.full_history_size,
               "context_size": stats.context_size,
               "masked_count": stats.masked_count,
               "preserved_count": stats.preserved_count,
               "tokens_before": stats.tokens_estimated_before,
               "tokens_after": stats.tokens_estimated_after,
               "tokens_saved": stats.tokens_saved,
               "compression_ratio": stats.compression_ratio,
               "compression_pct": compression_pct
           })

    # ========== AUDIBLE SYSTEM ==========
    # These methods implement real-time feedback injection, allowing users to
    # steer cascades mid-phase by injecting feedback as messages.

    def signal_audible(self):
        """
        Signal that an audible should be triggered at the next safe point.
        Called from external code (e.g., API endpoint) when user clicks the audible button.
        """
        self._audible_signal.set()

    def clear_audible_signal(self):
        """Clear the audible signal after it has been handled."""
        self._audible_signal.clear()

    def _check_audible_signal(self, phase: 'CellConfig') -> bool:
        """
        Check if an audible signal has been received and if we can process it.

        Checks both:
        1. Local threading.Event (same-process signal)
        2. API endpoint (cross-process signal from UI)

        Args:
            phase: Current phase configuration

        Returns:
            True if an audible should be processed, False otherwise
        """
        # Check local signal first (same-process case)
        local_signaled = self._audible_signal.is_set()

        # Check API signal (cross-process case - UI backend)
        api_signaled = False
        try:
            import urllib.request
            import urllib.error
            url = f"http://localhost:5001/api/audible/status/{self.session_id}"
            req = urllib.request.Request(url, method='GET')
            with urllib.request.urlopen(req, timeout=1) as response:
                data = json.loads(response.read().decode())
                api_signaled = data.get("signaled", False)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            # API not available or timeout - that's fine, just use local signal
            pass
        except Exception:
            # Any other error - just use local signal
            pass

        if not local_signaled and not api_signaled:
            return False

        # Check if audibles are enabled for this phase
        audible_config = phase.audibles
        if not audible_config or not audible_config.enabled:
            console.print(f"  [dim yellow]Audible signal received but audibles not enabled for phase '{phase.name}'[/dim yellow]")
            self.clear_audible_signal()
            self._clear_api_audible_signal()
            return False

        # Check budget
        with self._audible_lock:
            used = self._audible_budget_used.get(phase.name, 0)
            if used >= audible_config.budget:
                console.print(f"  [dim yellow]Audible budget exhausted ({used}/{audible_config.budget})[/dim yellow]")
                self.clear_audible_signal()
                self._clear_api_audible_signal()
                return False

        return True

    def _clear_api_audible_signal(self):
        """Clear the audible signal via API (for cross-process communication)."""
        try:
            import urllib.request
            import urllib.error
            url = f"http://localhost:5001/api/audible/clear/{self.session_id}"
            req = urllib.request.Request(url, method='POST')
            req.add_header('Content-Type', 'application/json')
            with urllib.request.urlopen(req, timeout=2) as response:
                pass  # Just need to make the call
        except Exception:
            pass  # API not available - that's fine

    def _handle_audible(self, phase: 'CellConfig', current_output: str, turn_number: int,
                       trace: 'TraceNode') -> Optional[dict]:
        """
        Handle an audible signal by creating a checkpoint and waiting for feedback.

        Args:
            phase: Current phase configuration
            current_output: The most recent output from the agent
            turn_number: Current turn number
            trace: Current trace node for logging

        Returns:
            Dict with feedback data if user submitted, None if cancelled/timed out
        """
        from .checkpoints import get_checkpoint_manager, CheckpointType, TraceContext

        console.print(f"  [bold magenta]🏈 AUDIBLE - Pausing for feedback[/bold magenta]")

        # Clear both local and API signals
        self.clear_audible_signal()
        self._clear_api_audible_signal()

        # Increment budget usage
        audible_config = phase.audibles
        with self._audible_lock:
            used = self._audible_budget_used.get(phase.name, 0)
            self._audible_budget_used[phase.name] = used + 1
            audibles_remaining = audible_config.budget - used - 1

        # Get recent images from the phase
        recent_images = self._get_recent_phase_images(phase.name)

        # Build trace context for proper resume linkage
        trace_context = TraceContext(
            trace_id=trace.id,
            parent_id=trace.parent_id,
            cascade_trace_id=self.trace.id,
            phase_trace_id=trace.id,
            depth=self.depth,
            node_type="audible",
            name=f"audible_{turn_number}"
        )

        # Build UI spec for the audible modal
        # Use DynamicUI-compatible section types: preview, text, choice, image
        ui_spec = {
            "type": "audible",
            "title": "🏈 Call Audible",
            "subtitle": f"Turn {turn_number + 1} of {phase.rules.max_turns or 1} | {audibles_remaining} audibles remaining",
            "current_output": current_output,
            "turn_number": turn_number,
            "max_turns": phase.rules.max_turns or 1,
            "turns_remaining": (phase.rules.max_turns or 1) - turn_number - 1,
            "audibles_remaining": audibles_remaining,
            "recent_images": recent_images,
            "allow_retry": audible_config.allow_retry,
            "submit_label": "Submit Feedback",
            "sections": [
                {
                    "type": "preview",
                    "label": "Current Output",
                    "content": current_output[:2000] if current_output else "(no output yet)",
                    "render": "markdown",
                    "collapsible": True,
                    "max_height": 200
                },
                {
                    "type": "text",
                    "label": "What should change?",
                    "input_name": "feedback",
                    "multiline": True,
                    "rows": 4,
                    "placeholder": "Describe what's wrong or needs adjustment...",
                    "required": True
                },
                {
                    "type": "choice",
                    "label": "Action",
                    "input_name": "mode",
                    "options": [
                        {"value": "continue", "label": "Continue", "description": "Keep current output, apply feedback in next turn"},
                        {"value": "retry", "label": "Retry", "description": "Discard current output, redo this turn with feedback"}
                    ] if audible_config.allow_retry else [
                        {"value": "continue", "label": "Continue", "description": "Keep current output, apply feedback in next turn"}
                    ],
                    "default": "continue"
                }
            ]
        }

        # Add images if available (insert before the text input)
        if recent_images:
            for i, img_path in enumerate(recent_images[-3:]):  # Last 3 images
                ui_spec["sections"].insert(1 + i, {
                    "type": "image",
                    "src": img_path,
                    "caption": f"Recent image {i + 1}",
                    "max_height": 200
                })

        # Create checkpoint
        checkpoint_manager = get_checkpoint_manager()
        checkpoint = checkpoint_manager.create_checkpoint(
            session_id=self.session_id,
            cascade_id=self.config.cascade_id,
            cell_name=phase.name,
            checkpoint_type=CheckpointType.AUDIBLE,
            ui_spec=ui_spec,
            echo_snapshot=self.echo.get_full_echo(),
            phase_output=current_output,
            cascade_config=self.config.model_dump() if hasattr(self.config, 'model_dump') else None,
            trace_context=trace_context,
            timeout_seconds=audible_config.timeout_seconds
        )

        # Notify hooks
        self.hooks.on_checkpoint_suspended(
            self.session_id,
            checkpoint.id,
            CheckpointType.AUDIBLE.value,
            phase.name,
            "Waiting for audible feedback",
            cascade_id=self.config.cascade_id
        )

        # Wait for response (blocking)
        response = checkpoint_manager.wait_for_response(
            checkpoint.id,
            timeout=audible_config.timeout_seconds
        )

        if response:
            # Notify hooks
            self.hooks.on_checkpoint_resumed(
                self.session_id,
                checkpoint.id,
                phase.name,
                response
            )
            return response
        else:
            console.print(f"  [dim yellow]Audible cancelled or timed out[/dim yellow]")
            return None

    def _get_recent_phase_images(self, cell_name: str, max_images: int = 5) -> List[str]:
        """
        Get recent image file paths from the current phase.

        Args:
            cell_name: Name of the phase
            max_images: Maximum number of images to return

        Returns:
            List of image file paths (most recent last)
        """
        import glob

        image_dir = os.path.join(get_config().image_dir, self.session_id, cell_name)

        if not os.path.exists(image_dir):
            return []

        # Find all image files
        image_patterns = ['*.png', '*.jpg', '*.jpeg', '*.gif', '*.webp']
        image_files = []
        for pattern in image_patterns:
            image_files.extend(glob.glob(os.path.join(image_dir, pattern)))

        # Sort by modification time (oldest first)
        image_files.sort(key=os.path.getmtime)

        # Return the most recent ones
        return image_files[-max_images:]

    def _format_audible_message(self, feedback: dict) -> Union[str, List[dict]]:
        """
        Format audible feedback as a user message content.

        Args:
            feedback: Feedback dict from checkpoint response

        Returns:
            Message content (string or multimodal list)
        """
        text = feedback.get("feedback", "")
        mode = feedback.get("mode", "continue")
        annotations = feedback.get("annotations", [])
        voice_transcript = feedback.get("voice_transcript")

        content_parts = []

        # Main feedback text
        header = "[AUDIBLE - User Feedback]"
        if text:
            content_parts.append(f"{header}:\n{text}")
        else:
            content_parts.append(f"{header}:\n(no text provided)")

        # Voice transcript (if any - future feature)
        if voice_transcript:
            content_parts.append(f"\n[Voice]: {voice_transcript}")

        # Mode instruction
        if mode == "retry":
            content_parts.append("\nPlease redo your last response incorporating this feedback.")
        else:
            content_parts.append("\nPlease incorporate this feedback in your next response.")

        # If there are annotations (images with drawings), return multimodal content
        if annotations:
            multimodal_content = [
                {"type": "text", "text": "\n".join(content_parts)},
                {"type": "text", "text": "\n[Annotated image showing requested changes]:"}
            ]
            for annotation in annotations:
                # Annotations should be base64 data URLs
                if annotation.startswith("data:"):
                    multimodal_content.append({
                        "type": "image_url",
                        "image_url": {"url": annotation}
                    })
            return multimodal_content

        return "\n".join(content_parts)

    def _inject_audible_feedback(self, feedback: dict, phase: 'CellConfig', trace: 'TraceNode'):
        """
        Inject audible feedback into the conversation as a user message.

        Args:
            feedback: Feedback dict from checkpoint response
            phase: Current phase configuration
            trace: Current trace node for logging
        """
        from .unified_logs import log_unified

        # Format the feedback as a message
        content = self._format_audible_message(feedback)
        mode = feedback.get("mode", "continue")

        # Create the message
        audible_msg = {"role": "user", "content": content}

        # Add to context messages
        self.context_messages.append(audible_msg)

        # Create trace for audible
        audible_trace = trace.create_child("audible", f"audible_{feedback.get('mode', 'continue')}")

        # Log to unified system
        audible_metadata = {
            "audible_mode": mode,
            "has_annotations": bool(feedback.get("annotations")),
            "has_voice": bool(feedback.get("voice_transcript")),
            "turn_number": self.current_turn_number,
            "feedback_length": len(feedback.get("feedback", "")),
            "audibles_used": self._audible_budget_used.get(phase.name, 0),
            "audibles_remaining": (phase.audibles.budget - self._audible_budget_used.get(phase.name, 0)) if phase.audibles else 0,
            "cell_name": phase.name,
            "cascade_id": self.config.cascade_id
        }

        log_unified(
            session_id=self.session_id,
            trace_id=audible_trace.id,
            parent_id=trace.id,
            node_type="audible",
            role="user",
            content=content if isinstance(content, str) else json.dumps(content),
            metadata=audible_metadata
        )

        # Add to echo history
        audible_metadata["semantic_actor"] = "framework"
        audible_metadata["semantic_purpose"] = "context_injection"
        self.echo.add_history(
            audible_msg,
            trace_id=audible_trace.id,
            parent_id=trace.id,
            node_type="audible",
            metadata=audible_metadata
        )

        console.print(f"  [bold green]✓ Audible feedback injected ({mode} mode)[/bold green]")

    # ========== CONTEXT INJECTION SYSTEM ==========
    # These methods implement selective context management, allowing phases to
    # explicitly declare their context dependencies rather than relying solely
    # on the snowball architecture where all context accumulates.

    def _resolve_phase_reference(self, ref: str) -> Union[str, List[str], None]:
        """
        Resolve special phase reference keywords to actual phase names.

        Supported keywords:
            - "all": All completed phases (explicit snowball)
            - "first": The first phase that executed (often contains original problem)
            - "previous" or "prev": The most recently completed phase

        Args:
            ref: Phase name or special keyword

        Returns:
            - For "all": List of all completed phase names
            - For "first"/"previous": Single phase name string
            - For literal names: The name unchanged
            - None if keyword can't be resolved (e.g., "first" in first phase)
        """
        ref_lower = ref.lower()

        if ref_lower == "all":
            if self.echo.lineage:
                cells = [entry.get("cell") for entry in self.echo.lineage]
                console.print(f"    [dim]Resolved 'all' → {cells}[/dim]")
                return cells
            else:
                console.print(f"    [dim yellow]Cannot resolve 'all': no cells have completed yet[/dim yellow]")
                return []  # Return empty list, not None (allows loop to work)

        elif ref_lower == "first":
            if self.echo.lineage:
                resolved = self.echo.lineage[0].get("phase")
                console.print(f"    [dim]Resolved 'first' → '{resolved}'[/dim]")
                return resolved
            else:
                console.print(f"    [dim yellow]Cannot resolve 'first': no cells have completed yet[/dim yellow]")
                return None

        elif ref_lower in ("previous", "prev"):
            if self.echo.lineage:
                resolved = self.echo.lineage[-1].get("phase")
                console.print(f"    [dim]Resolved 'previous' → '{resolved}'[/dim]")
                return resolved
            else:
                console.print(f"    [dim yellow]Cannot resolve 'previous': no cells have completed yet[/dim yellow]")
                return None

        # Not a special keyword - return as literal phase name
        return ref

    def _normalize_source_config(self, source: Union[str, ContextSourceConfig]) -> Optional[ContextSourceConfig]:
        """
        Normalize a context source specification to ContextSourceConfig.
        Resolves special keywords like "first", "previous" to actual phase names.

        Args:
            source: Either a phase name string (or keyword) or a ContextSourceConfig object

        Returns:
            ContextSourceConfig with defaults applied, or None if reference couldn't be resolved
        """
        if isinstance(source, str):
            resolved_phase = self._resolve_phase_reference(source)
            if resolved_phase is None:
                return None
            return ContextSourceConfig(cell=resolved_phase)
        else:
            # ContextSourceConfig object - may need to resolve the phase name
            resolved_phase = self._resolve_phase_reference(source.cell)
            if resolved_phase is None:
                return None
            if resolved_phase != source.cell:
                # Create new config with resolved phase name
                return ContextSourceConfig(
                    cell=resolved_phase,
                    include=source.include,
                    images_filter=source.images_filter,
                    images_count=source.images_count,
                    messages_filter=source.messages_filter,
                    as_role=source.as_role,
                    condition=source.condition
                )
            return source

    def _load_cell_images(self, cell_name: str, config: ContextSourceConfig) -> List[str]:
        """
        Load images from disk for a specific phase.

        Args:
            cell_name: Name of the phase to load images from
            config: Source configuration with filtering options

        Returns:
            List of base64-encoded image data URLs
        """
        import glob
        import base64

        image_dir = os.path.join(get_config().image_dir, self.session_id, cell_name)

        if not os.path.exists(image_dir):
            console.print(f"  [dim]No images found for phase '{cell_name}' (directory doesn't exist)[/dim]")
            return []

        # Find all image files
        image_patterns = ['*.png', '*.jpg', '*.jpeg', '*.gif', '*.webp']
        image_files = []
        for pattern in image_patterns:
            image_files.extend(glob.glob(os.path.join(image_dir, pattern)))

        # Sort by modification time (oldest first)
        image_files.sort(key=os.path.getmtime)

        if not image_files:
            console.print(f"  [dim]No images found for phase '{cell_name}'[/dim]")
            return []

        # Apply filtering
        if config.images_filter == "last":
            image_files = image_files[-1:] if image_files else []
        elif config.images_filter == "last_n":
            image_files = image_files[-config.images_count:] if image_files else []
        # "all" keeps all files

        # Encode images to base64 data URLs
        encoded_images = []
        for img_path in image_files:
            try:
                ext = os.path.splitext(img_path)[1].lower()
                mime_type = {
                    '.png': 'image/png',
                    '.jpg': 'image/jpeg',
                    '.jpeg': 'image/jpeg',
                    '.gif': 'image/gif',
                    '.webp': 'image/webp'
                }.get(ext, 'image/png')

                with open(img_path, 'rb') as f:
                    img_data = base64.b64encode(f.read()).decode('utf-8')
                    encoded_images.append(f"data:{mime_type};base64,{img_data}")
            except Exception as e:
                console.print(f"  [yellow]Warning: Failed to load image {img_path}: {e}[/yellow]")

        console.print(f"  [dim]Loaded {len(encoded_images)} image(s) from phase '{cell_name}'[/dim]")
        return encoded_images

    def _get_phase_output(self, cell_name: str) -> Optional[str]:
        """
        Get the output from a specific phase via echo.lineage.

        Args:
            cell_name: Name of the phase to get output from

        Returns:
            The phase output as a string, or None if not found
        """
        for entry in self.echo.lineage:
            if entry.get('phase') == cell_name:
                output = entry.get('output')
                if output is not None:
                    return str(output)
        return None

    def _get_phase_messages(self, cell_name: str, config: ContextSourceConfig) -> List[Dict]:
        """
        Get messages from a specific phase via echo.history.

        Args:
            cell_name: Name of the phase to get messages from
            config: Source configuration with filtering options

        Returns:
            List of message dicts with role/content
        """
        messages = []
        in_phase = False
        last_turn_messages = []

        for entry in self.echo.history:
            # Check if this entry belongs to the target phase
            entry_phase = entry.get('metadata', {}).get('cell_name')
            if entry_phase == cell_name:
                in_phase = True
                role = entry.get('role')
                content = entry.get('content')

                if not content or role in ['cascade_soundings', 'cascade_sounding_attempt', 'evaluator']:
                    continue

                # Apply message filtering
                if config.messages_filter == "assistant_only":
                    if role == 'assistant':
                        messages.append({"role": role, "content": content})
                elif config.messages_filter == "last_turn":
                    # Collect all, then take last turn
                    if role in ['user', 'assistant', 'tool']:
                        last_turn_messages.append({"role": role, "content": content})
                else:  # "all"
                    if role in ['user', 'assistant', 'tool', 'system']:
                        messages.append({"role": role, "content": content})
            elif in_phase:
                # We've left the phase, stop collecting
                break

        # For last_turn filter, find the last user->assistant exchange
        if config.messages_filter == "last_turn" and last_turn_messages:
            # Find last assistant message and include it plus preceding context
            for i in range(len(last_turn_messages) - 1, -1, -1):
                if last_turn_messages[i]['role'] == 'assistant':
                    # Include from last user message to this assistant message
                    start = i
                    for j in range(i - 1, -1, -1):
                        if last_turn_messages[j]['role'] == 'user':
                            start = j
                            break
                    messages = last_turn_messages[start:i+1]
                    break

        return messages

    def _build_injection_messages(self, config: ContextSourceConfig, trace: 'TraceNode') -> List[Dict]:
        """
        Build injection messages for a single source configuration.

        Args:
            config: Source configuration specifying what to include
            trace: Current trace node for logging

        Returns:
            List of message dicts to inject into context
        """
        messages = []
        cell_name = config.cell

        # Check if the cell has executed
        executed_cells = [entry['cell'] for entry in self.echo.lineage]
        if cell_name not in executed_cells:
            console.print(f"  [dim]Skipping injection from '{cell_name}' (not executed)[/dim]")
            return messages

        # Include images
        if "images" in config.include:
            images = self._load_cell_images(cell_name, config)
            if images:
                # Build multimodal message with images
                content = [{"type": "text", "text": f"[Images from {cell_name}]:"}]
                for img_url in images:
                    content.append({
                        "type": "image_url",
                        "image_url": {"url": img_url}
                    })
                messages.append({
                    "role": config.as_role,
                    "content": content
                })

        # Include output
        if "output" in config.include:
            output = self._get_phase_output(cell_name)
            if output:
                messages.append({
                    "role": config.as_role,
                    "content": f"[Output from {cell_name}]:\n{output}"
                })

        # Include messages (full conversation replay)
        if "messages" in config.include:
            phase_messages = self._get_phase_messages(cell_name, config)
            if phase_messages:
                # Add header message
                messages.append({
                    "role": config.as_role,
                    "content": f"[Conversation from {cell_name}]:"
                })
                # Add the actual messages with their original roles
                messages.extend(phase_messages)

        # Include state (Phase 4 feature - basic implementation)
        if "state" in config.include:
            # For now, include the full state as JSON
            # Future: filter to only keys set during that phase
            if self.echo.state:
                messages.append({
                    "role": config.as_role,
                    "content": f"[State from {cell_name}]:\n{json.dumps(self.echo.state, indent=2)}"
                })

        return messages

    def _build_phase_context(self, phase: CellConfig, input_data: dict, trace: 'TraceNode') -> List[Dict]:
        """
        Build the context messages for a phase based on its context configuration.

        SELECTIVE-BY-DEFAULT: Phases without a context config get NO prior context (clean slate).
        Use context.from: ["all"] for explicit snowball behavior.
        Use context.mode: "auto" for LLM-assisted context selection.

        Args:
            phase: Phase configuration
            input_data: Original cascade input
            trace: Current trace node

        Returns:
            List of context messages (empty list for clean slate)
        """
        # No context config = clean slate (selective-by-default)
        if not phase.context:
            console.print(f"  [dim]No context config → clean slate[/dim]")
            return []

        # AUTO MODE: Use InterPhaseContextBuilder for intelligent selection
        if phase.context.mode == "auto":
            return self._build_auto_context(phase, input_data, trace)

        console.print(f"  [bold cyan]📦 Building context from config...[/bold cyan]")
        messages = []

        # Optionally include original input
        if phase.context.include_input and input_data:
            messages.append({
                "role": "user",
                "content": f"[Original Input]:\n{json.dumps(input_data, indent=2)}"
            })

        # Get the exclude list for filtering
        exclude_set = set(phase.context.exclude)

        # Pull from each specified source (in order!)
        for source in phase.context.from_:
            # Handle string sources (may be keywords like "all", "first", "previous")
            if isinstance(source, str):
                resolved = self._resolve_phase_reference(source)

                if resolved is None:
                    # Keyword couldn't be resolved (e.g., "first" in first phase)
                    continue

                if isinstance(resolved, list):
                    # "all" returns a list of phase names
                    for cell_name in resolved:
                        if cell_name in exclude_set:
                            console.print(f"    [dim]Excluding '{cell_name}'[/dim]")
                            continue
                        source_config = ContextSourceConfig(cell=cell_name)
                        injection_messages = self._build_injection_messages(source_config, trace)
                        messages.extend(injection_messages)
                else:
                    # Single phase name
                    if resolved in exclude_set:
                        console.print(f"    [dim]Excluding '{resolved}'[/dim]")
                        continue
                    source_config = ContextSourceConfig(cell=resolved)
                    injection_messages = self._build_injection_messages(source_config, trace)
                    messages.extend(injection_messages)
            else:
                # ContextSourceConfig object - resolve phase name if needed
                resolved = self._resolve_phase_reference(source.cell)
                if resolved is None:
                    continue
                if isinstance(resolved, list):
                    # "all" in a ContextSourceConfig - apply the same config to all phases
                    for cell_name in resolved:
                        if cell_name in exclude_set:
                            console.print(f"    [dim]Excluding '{cell_name}'[/dim]")
                            continue
                        source_config = ContextSourceConfig(
                            cell=cell_name,
                            include=source.include,
                            images_filter=source.images_filter,
                            images_count=source.images_count,
                            messages_filter=source.messages_filter,
                            as_role=source.as_role,
                            condition=source.condition
                        )
                        injection_messages = self._build_injection_messages(source_config, trace)
                        messages.extend(injection_messages)
                else:
                    if resolved in exclude_set:
                        console.print(f"    [dim]Excluding '{resolved}'[/dim]")
                        continue
                    source_config = self._normalize_source_config(source)
                    if source_config:
                        injection_messages = self._build_injection_messages(source_config, trace)
                        messages.extend(injection_messages)

        console.print(f"  [dim]Built context: {len(messages)} message(s) from {len(phase.context.from_)} source(s)[/dim]")
        return messages

    def _build_auto_context(self, phase: CellConfig, input_data: dict, trace: 'TraceNode') -> List[Dict]:
        """
        Build context using LLM-assisted auto-selection.

        This is the "crowning jewel" - uses context cards (summaries + embeddings)
        to intelligently select the most relevant prior messages for the current task.

        Args:
            phase: Phase configuration
            input_data: Original cascade input
            trace: Current trace node

        Returns:
            List of selected context messages
        """
        from .auto_context import InterPhaseContextBuilder
        from .cascade import InterPhaseContextConfig

        console.print(f"  [bold magenta]🧠 Auto-context mode: intelligent selection...[/bold magenta]")

        # Log auto-context start as structural message
        auto_ctx_trace = trace.create_child("auto_context", "inter_phase_selection")
        self.echo.add_history({
            "role": "structure",
            "content": f"🧠 Auto-Context: Inter-Phase Selection",
            "node_type": "auto_context_start"
        }, trace_id=auto_ctx_trace.id, parent_id=trace.id, node_type="auto_context_start",
           metadata={
               "cell_name": phase.name,
               "cascade_id": self.config.cascade_id,
               "semantic_actor": "auto_context",
               "semantic_purpose": "inter_phase_selection",
               "mode": "auto"
           })

        # Get inter-phase config from cascade or phase
        inter_phase_config = None
        selection_strategy = "hybrid"  # default
        if self.config.auto_context and self.config.auto_context.inter_phase:
            inter_phase_config = InterPhaseContextConfig(
                enabled=self.config.auto_context.inter_phase.enabled,
                anchors=self.config.auto_context.inter_phase.anchors,
                selection=self.config.auto_context.inter_phase.selection
            )
            if inter_phase_config.selection:
                selection_strategy = inter_phase_config.selection.strategy

        # Phase-level override
        if phase.context and phase.context.selection:
            selection_strategy = phase.context.selection.strategy

        # Build list of executed phases
        executed_phases = [
            entry["phase"] for entry in self.echo.lineage
            if entry.get("phase") and entry["phase"] != phase.name
        ]

        # Log source phases
        self.echo.add_history({
            "role": "structure",
            "content": f"📦 Source Phases: {', '.join(executed_phases) if executed_phases else '(none)'}",
            "node_type": "auto_context_sources"
        }, trace_id=auto_ctx_trace.id, parent_id=trace.id, node_type="auto_context_sources",
           metadata={
               "cell_name": phase.name,
               "cascade_id": self.config.cascade_id,
               "executed_phases": executed_phases,
               "strategy": selection_strategy,
               "semantic_actor": "auto_context",
               "semantic_purpose": "source_identification"
           })

        # Create builder
        builder = InterPhaseContextBuilder(
            session_id=self.session_id,
            echo=self.echo,
            config=inter_phase_config
        )

        # Build context
        messages, stats = builder.build_phase_context(
            current_cell=phase,
            input_data=input_data,
            executed_phases=executed_phases
        )

        # Log selection stats
        strategy = stats.strategy
        console.print(f"  [dim cyan]Strategy: {strategy} | "
                     f"Anchors: {stats.anchor_count} | "
                     f"Selected: {stats.selected_count}/{stats.candidate_count} | "
                     f"Tokens: ~{stats.tokens_used} | "
                     f"Time: {stats.selection_time_ms}ms[/dim cyan]")

        # Log selection result as structural message
        self.echo.add_history({
            "role": "structure",
            "content": (
                f"✅ Auto-Context Selection Complete\n"
                f"   Strategy: {stats.strategy}\n"
                f"   Anchors: {stats.anchor_count} messages\n"
                f"   Candidates: {stats.candidate_count} from context cards\n"
                f"   Selected: {stats.selected_count} messages\n"
                f"   Tokens: ~{stats.tokens_used}/{stats.tokens_budget} budget\n"
                f"   Time: {stats.selection_time_ms}ms"
            ),
            "node_type": "auto_context_result"
        }, trace_id=auto_ctx_trace.id, parent_id=trace.id, node_type="auto_context_result",
           metadata={
               "cell_name": phase.name,
               "cascade_id": self.config.cascade_id,
               "strategy": stats.strategy,
               "anchor_count": stats.anchor_count,
               "candidate_count": stats.candidate_count,
               "selected_count": stats.selected_count,
               "tokens_budget": stats.tokens_budget,
               "tokens_used": stats.tokens_used,
               "tokens_saved": stats.tokens_budget - stats.tokens_used,
               "selection_time_ms": stats.selection_time_ms,
               "semantic_actor": "auto_context",
               "semantic_purpose": "selection_complete"
           })

        # Log each injected message for debugging
        for i, msg in enumerate(messages):
            anchor_type = msg.get("_anchor_type", "selected")
            source = msg.get("_source_phase", msg.get("_content_hash", "unknown")[:8] if msg.get("_content_hash") else "unknown")
            role = msg.get("role", "unknown")
            content_preview = str(msg.get("content", ""))[:100]

            self.echo.add_history({
                "role": "structure",
                "content": f"💉 Context #{i+1}: [{anchor_type}] {role} from {source}\n   {content_preview}...",
                "node_type": "auto_context_injection"
            }, trace_id=auto_ctx_trace.id, parent_id=trace.id, node_type="auto_context_injection",
               metadata={
                   "cell_name": phase.name,
                   "cascade_id": self.config.cascade_id,
                   "injection_index": i,
                   "anchor_type": anchor_type,
                   "source": source,
                   "role": role,
                   "content_preview": content_preview,
                   "is_anchor": msg.get("_anchor", False),
                   "semantic_actor": "auto_context",
                   "semantic_purpose": "context_injection"
               })

        return messages

    def _update_graph(self):
        """Updates the mermaid graph in real-time."""
        try:
            generate_mermaid(self.echo, self.graph_path)
        except Exception:
            pass # Don't crash execution for visualization

    def _handle_human_input_checkpoint(
        self,
        phase: CellConfig,
        phase_output: str,
        trace: TraceNode,
        input_data: dict = None
    ) -> Optional[Dict[str, Any]]:
        """
        Handle human-in-the-loop checkpoint if configured for this phase.

        This method uses a BLOCKING approach - the cascade thread waits here
        until the human responds (similar to waiting for an LLM API call).
        No suspend/resume complexity needed.

        If phase.human_input is configured, this method:
        1. Generates the UI specification
        2. Creates a checkpoint record
        3. BLOCKS waiting for human response
        4. Returns the response (or None if timed out/cancelled)

        Args:
            phase: The phase configuration
            phase_output: The output from the phase
            trace: The trace node for this phase
            input_data: The input data for this cascade

        Returns:
            Human response dict, or None if timed out/cancelled
        """
        if not phase.human_input:
            return None

        # Normalize config (handles bool vs HumanInputConfig)
        config = normalize_human_input_config(phase.human_input)
        if config is None:
            return None

        input_data = input_data or {}
        indent = "  " * self.depth
        console.print(f"{indent}[bold yellow]⏸️  Human checkpoint: {phase.name}[/bold yellow]")

        # Check condition if specified
        if config.condition:
            try:
                # Simple condition evaluation with state context
                condition_result = eval(config.condition, {
                    "state": self.echo.state,
                    "output": phase_output,
                    "input": input_data
                })
                if not condition_result:
                    console.print(f"{indent}  [dim]Checkpoint condition not met, skipping[/dim]")
                    return None
            except Exception as e:
                console.print(f"{indent}  [yellow]⚠️  Condition evaluation error: {e}[/yellow]")
                # On error, proceed with checkpoint

        # Generate UI specification
        ui_generator = UIGenerator()
        context = {
            "cascade_id": self.config.cascade_id,
            "cell_name": phase.name,
            "lineage": [entry.get("phase") for entry in self.echo.lineage],
            "state": self.echo.state
        }

        ui_spec = ui_generator.generate(config, phase_output, context)

        # Create checkpoint (no need for echo_snapshot or cascade_config - we're not suspending)
        checkpoint_manager = get_checkpoint_manager()
        checkpoint = checkpoint_manager.create_checkpoint(
            session_id=self.session_id,
            cascade_id=self.config.cascade_id,
            cell_name=phase.name,
            checkpoint_type=CheckpointType.PHASE_INPUT,
            ui_spec=ui_spec,
            echo_snapshot={},  # Not needed for blocking approach
            phase_output=phase_output,
            cascade_config=None,  # Not needed for blocking approach
            trace_context=None,  # Not needed for blocking approach
            timeout_seconds=config.timeout_seconds
        )

        console.print(f"{indent}  [cyan]Checkpoint created: {checkpoint.id}[/cyan]")
        console.print(f"{indent}  [dim]UI type: {config.type.value}[/dim]")
        if config.timeout_seconds:
            console.print(f"{indent}  [dim]Timeout: {config.timeout_seconds}s[/dim]")

        # Log checkpoint creation
        self.echo.add_history(
            {"role": "system", "content": f"Waiting for human input: {checkpoint.id}"},
            trace_id=trace.id,
            node_type="checkpoint_waiting",
            metadata={
                "cell": phase.name,
                "checkpoint_id": checkpoint.id,
                "checkpoint_type": "phase_input",
                "ui_type": config.type.value,
                "semantic_actor": "framework",
                "semantic_purpose": "lifecycle",
            }
        )

        # BLOCK waiting for human response
        # The cascade thread just waits here, like waiting for an LLM API call
        response = checkpoint_manager.wait_for_response(
            checkpoint_id=checkpoint.id,
            timeout=config.timeout_seconds,
            poll_interval=0.5
        )

        if response is None:
            # Timed out or cancelled
            console.print(f"{indent}  [yellow]⚠️  No human response received[/yellow]")
            self.echo.add_history(
                {"role": "system", "content": f"Checkpoint timed out or cancelled: {checkpoint.id}"},
                trace_id=trace.id,
                node_type="checkpoint_timeout",
                metadata={
                    "cell": phase.name,
                    "checkpoint_id": checkpoint.id,
                    "semantic_actor": "framework",
                    "semantic_purpose": "lifecycle",
                }
            )
            return None

        # Response received!
        console.print(f"{indent}  [green]✓ Human response received[/green]")
        self.echo.add_history(
            {"role": "user", "content": f"Human response: {json.dumps(response)}"},
            trace_id=trace.id,
            node_type="checkpoint_response",
            metadata={
                "cell": phase.name,
                "checkpoint_id": checkpoint.id,
                "response": response,
                "semantic_actor": "human",
                "semantic_purpose": "task_input",
            }
        )

        return response

    # ===== Decision Point Handling (LLM-Generated HITL) =====

    # Regex pattern to detect <decision> blocks in phase output
    DECISION_PATTERN = re.compile(
        r'<decision>\s*(\{.*?\})\s*</decision>',
        re.DOTALL
    )

    def _check_for_decision_point(
        self,
        phase_output: str,
        phase: CellConfig
    ) -> Optional[Dict[str, Any]]:
        """
        Detect and parse <decision> blocks in phase output.

        The LLM can output a decision block to request human input:
        <decision>
        {
            "question": "How should I handle X?",
            "options": [
                {"id": "opt1", "label": "Option 1", "description": "..."},
                {"id": "opt2", "label": "Option 2"}
            ],
            "allow_custom": true,
            "severity": "warning"
        }
        </decision>

        Returns:
            Dict with decision data if found, None otherwise
        """
        if not phase.decision_points or not phase.decision_points.enabled:
            return None

        match = self.DECISION_PATTERN.search(phase_output)
        if not match:
            return None

        try:
            decision = json.loads(match.group(1))

            # Validate required fields
            if not decision.get("question") or not decision.get("options"):
                console.print(f"[yellow]⚠️ Invalid decision block: missing question or options[/yellow]")
                return None

            # Extract context (text before the decision block)
            context_before = phase_output[:match.start()].strip()

            return {
                "decision": decision,
                "context_before": context_before,
                "full_output": phase_output,
                "match_start": match.start(),
                "match_end": match.end()
            }
        except json.JSONDecodeError as e:
            console.print(f"[yellow]⚠️ Invalid JSON in decision block: {e}[/yellow]")
            return None

    def _handle_decision_point(
        self,
        decision_data: Dict[str, Any],
        phase: CellConfig,
        trace: TraceNode
    ) -> Optional[Dict[str, Any]]:
        """
        Handle an LLM-generated decision point.

        Creates a checkpoint with the decision UI, blocks for human response,
        and returns routing information based on the selection.

        Args:
            decision_data: Parsed decision data from _check_for_decision_point
            phase: The phase configuration
            trace: The trace node for this phase

        Returns:
            Dict with routing info: {"_action": "continue|retry|route", ...}
        """
        decision = decision_data["decision"]
        config = phase.decision_points
        indent = "  " * self.depth

        console.print(f"{indent}[bold magenta]🔀 Decision point detected: {decision['question']}[/bold magenta]")

        # Build UI spec from decision block
        sections = []

        # Show context/output if configured
        if config.ui.present_output and decision_data.get("context_before"):
            sections.append({
                "type": "preview",
                "content": decision_data["context_before"],
                "render": "markdown",
                "label": "Context"
            })

        # Add decision context if provided in the block
        if decision.get("context"):
            sections.append({
                "type": "preview",
                "content": decision["context"],
                "render": "markdown",
                "label": "Details"
            })

        # Build choice section from options
        options = decision["options"][:config.ui.max_options]  # Limit options

        # Use card_grid for rich cards or choice for simple radio buttons
        if len(options) <= 4 and config.ui.layout == "cards":
            # Rich card grid layout
            options_section = {
                "type": "card_grid",
                "label": decision["question"],
                "input_name": "decision_choice",
                "columns": min(len(options), 3),
                "selection_mode": "single",
                "cards": [
                    {
                        "id": opt.get("id", f"opt_{i}"),
                        "title": opt.get("label", f"Option {i+1}"),
                        "content": opt.get("description"),
                        "badge": "Recommended" if opt.get("style") == "primary" else None,
                    }
                    for i, opt in enumerate(options)
                ]
            }
        else:
            # Simple choice with radio buttons
            options_section = {
                "type": "choice",
                "prompt": decision["question"],
                "label": decision["question"],
                "input_name": "decision_choice",
                "options": [
                    {
                        "value": opt.get("id", f"opt_{i}"),
                        "label": opt.get("label", f"Option {i+1}"),
                        "description": opt.get("description"),
                        "icon": opt.get("icon"),
                    }
                    for i, opt in enumerate(options)
                ]
            }

        # Add "Other" text input if custom allowed
        allow_custom = decision.get("allow_custom", config.ui.allow_text_fallback)
        if allow_custom:
            sections.append(options_section)
            sections.append({
                "type": "text",
                "label": "Or provide custom response",
                "input_name": "decision_custom",
                "placeholder": "Enter custom response...",
                "multiline": False,
                "required": False
            })
        else:
            sections.append(options_section)

        ui_spec = {
            "layout": "vertical",
            "title": decision["question"],
            "sections": sections,
            "_meta": {
                "type": "decision_point",
                "severity": decision.get("severity", "info"),
                "category": decision.get("category"),
                "options_count": len(options),
                "cell_name": phase.name
            }
        }

        # Create checkpoint
        checkpoint_manager = get_checkpoint_manager()
        checkpoint = checkpoint_manager.create_checkpoint(
            session_id=self.session_id,
            cascade_id=self.config.cascade_id,
            cell_name=phase.name,
            checkpoint_type=CheckpointType.DECISION,
            ui_spec=ui_spec,
            echo_snapshot={},
            phase_output=decision_data["full_output"],
            cascade_config=None,
            trace_context=None,
            timeout_seconds=config.timeout_seconds
        )

        console.print(f"{indent}  [cyan]Decision checkpoint created: {checkpoint.id}[/cyan]")
        console.print(f"{indent}  [dim]Options: {len(options)}, Timeout: {config.timeout_seconds}s[/dim]")

        # Log checkpoint creation
        self.echo.add_history(
            {"role": "system", "content": f"Decision point: {decision['question']} (checkpoint: {checkpoint.id})"},
            trace_id=trace.id,
            node_type="decision_waiting",
            metadata={
                "cell": phase.name,
                "checkpoint_id": checkpoint.id,
                "checkpoint_type": "decision",
                "question": decision["question"],
                "options_count": len(options),
                "semantic_actor": "framework",
                "semantic_purpose": "lifecycle",
            }
        )

        # BLOCK waiting for human response
        response = checkpoint_manager.wait_for_response(
            checkpoint_id=checkpoint.id,
            timeout=config.timeout_seconds,
            poll_interval=0.5
        )

        if response is None:
            console.print(f"{indent}  [yellow]⚠️ Decision timed out or cancelled[/yellow]")
            self.echo.add_history(
                {"role": "system", "content": f"Decision checkpoint timed out: {checkpoint.id}"},
                trace_id=trace.id,
                node_type="decision_timeout",
                metadata={
                    "cell": phase.name,
                    "checkpoint_id": checkpoint.id,
                    "semantic_actor": "framework",
                    "semantic_purpose": "lifecycle",
                }
            )
            return None

        # Response received - extract selection
        selected_id = response.get("decision_choice") or response.get("selected") or response.get("choice")
        custom_text = response.get("decision_custom") or response.get("other_text") or response.get("custom") or response.get("text")

        console.print(f"{indent}  [green]✓ Decision received: {selected_id}[/green]")

        # Find the selected option
        selected_option = next(
            (opt for opt in decision["options"] if opt.get("id") == selected_id),
            None
        )

        # Log response
        self.echo.add_history(
            {"role": "user", "content": f"Decision: {selected_option['label'] if selected_option else selected_id}" + (f" - {custom_text}" if custom_text else "")},
            trace_id=trace.id,
            node_type="decision_response",
            metadata={
                "cell": phase.name,
                "checkpoint_id": checkpoint.id,
                "selected_id": selected_id,
                "selected_label": selected_option["label"] if selected_option else None,
                "custom_text": custom_text,
                "semantic_actor": "human",
                "semantic_purpose": "task_input",
            }
        )

        # Store decision in state for downstream access
        self.echo.state[f"_decision_{phase.name}"] = {
            "choice": selected_id,
            "label": selected_option["label"] if selected_option else selected_id,
            "custom_text": custom_text,
            "question": decision["question"]
        }

        # Determine routing action
        return self._route_decision(response, decision, config, phase, selected_id, custom_text, selected_option)

    def _route_decision(
        self,
        response: Dict[str, Any],
        decision: Dict[str, Any],
        config: DecisionPointConfig,
        phase: CellConfig,
        selected_id: str,
        custom_text: Optional[str],
        selected_option: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Determine routing based on decision selection.

        Checks (in order):
        1. Option-level action (from the <decision> block)
        2. Config-level routing (from phase.decision_points.routing)
        3. Default: continue to next phase
        """
        indent = "  " * self.depth

        # Check option-level action
        action = None
        if selected_option and selected_option.get("action"):
            action = selected_option["action"]
        # Check config-level routing
        elif config.routing and selected_id in config.routing:
            action = config.routing[selected_id]
        elif config.routing:
            action = config.routing.get("_continue", "next")
        else:
            action = "next"

        # Normalize action to dict form
        if isinstance(action, str):
            if action in ("_abort", "abort"):
                action = {"fail": True}
            elif action in ("_retry", "retry", "self"):
                action = {"to": "self", "inject": "feedback"}
            elif action == "next":
                action = {"to": "next"}
            else:
                action = {"to": action}  # Phase name

        # Handle failure
        if action.get("fail"):
            error_msg = f"Decision aborted: {selected_option['label'] if selected_option else selected_id}"
            if custom_text:
                error_msg += f" - {custom_text}"
            console.print(f"{indent}  [red]✗ Decision aborted cascade[/red]")
            raise Exception(error_msg)

        # Build feedback for injection
        feedback = f"Human selected: {selected_option['label'] if selected_option else selected_id}"
        if custom_text:
            feedback += f"\nAdditional input: {custom_text}"

        # Handle retry (route to self)
        if action.get("to") == "self":
            console.print(f"{indent}  [yellow]↻ Retrying phase with decision feedback[/yellow]")
            # Store feedback for injection on retry
            self.echo.state["_decision_feedback"] = feedback
            return {
                "_action": "retry",
                "decision_choice": selected_id,
                "decision_feedback": feedback,
                "custom_text": custom_text
            }

        # Handle route to specific phase
        target = action.get("to", "next")
        if target != "next":
            console.print(f"{indent}  [cyan]→ Routing to phase: {target}[/cyan]")
            return {
                "_action": "route",
                "target_phase": target,
                "decision_choice": selected_id,
                "decision_feedback": feedback
            }

        # Default: continue to next phase
        return {
            "_action": "continue",
            "decision_choice": selected_id,
            "decision_feedback": feedback
        }

    def _generate_tool_description(self, func: Callable, name: str) -> str:
        """
        Generate a prompt-based description of a tool for the agent.
        Returns formatted text describing the tool, its parameters, and how to call it.
        """
        import inspect
        from typing import get_type_hints

        sig = inspect.signature(func)
        hints = get_type_hints(func)

        # Get FULL docstring - cleandoc handles indentation from multi-line docstrings
        description = inspect.cleandoc(func.__doc__) if func.__doc__ else f"Tool: {name}"

        # Build parameter list with types and example values
        params = []
        example_args = {}
        for param_name, param in sig.parameters.items():
            if param_name == "self":
                continue

            param_type = hints.get(param_name, str).__name__
            is_required = param.default == inspect.Parameter.empty
            required_marker = " (required)" if is_required else f" (optional, default: {param.default})"

            params.append(f"  - {param_name} ({param_type}){required_marker}")

            # Build example value based on type (only for required params)
            if is_required:
                if param_type == "str":
                    example_args[param_name] = f"<{param_name}>"
                elif param_type == "int":
                    example_args[param_name] = 0
                elif param_type == "float":
                    example_args[param_name] = 0.0
                elif param_type == "bool":
                    example_args[param_name] = True
                elif param_type == "list":
                    example_args[param_name] = ["<item1>", "<item2>"]
                elif param_type == "dict":
                    example_args[param_name] = {"key": "value"}
                else:
                    example_args[param_name] = f"<{param_name}>"

        params_str = "\n".join(params) if params else "  (no parameters)"

        # Format example args as JSON
        import json
        example_str = json.dumps(example_args) if example_args else "{}"

        # Format as markdown with full docstring
        tool_desc = f"""
**{name}**
{description}

Parameter Types:
{params_str}

To call this tool, output a JSON code block:
```json
{{"tool": "{name}", "arguments": {example_str}}}
```
"""
        return tool_desc.strip()

    def _parse_prompt_tool_calls(self, content: str) -> tuple[List[Dict], str]:
        """
        Parse prompt-based tool calls from agent response.

        Supports 22 formats for maximum LLM compatibility:

        Format 1 (Preferred): Standard JSON with tool wrapper in code fence
            ```json
            {"tool": "tool_name", "arguments": {"param": "value"}}
            ```

        Format 2: Tool name as code fence language identifier (direct arguments)
            ```request_decision
            {"question": "...", "options": [...]}
            ```

        Format 3: XML-style tags with JSON body
            <tool_call>{"tool": "name", "arguments": {...}}</tool_call>
            <function_call>...</function_call>
            <invoke name="tool_name">{"param": "value"}</invoke>

        Format 4: Function call syntax
            tool_name({"param": "value"})

        Format 5: Anthropic/Claude-style with parameter elements
            <invoke name="tool_name">
                <parameter name="key">value</parameter>
            </invoke>
            (Also supports <invoke> namespace variant)

        Format 6: ReAct-style (LangChain, AutoGPT)
            Action: tool_name
            Action Input: {"key": "value"}

        Format 7: Mistral-style
            [TOOL_CALLS] [{"name": "tool", "arguments": {...}}]

        Format 8: Hermes/ChatML-style
            <tool_call>{"name": "tool", "arguments": {...}}</tool_call>

        Format 9: Bare JSON on its own line
            {"tool": "name", "arguments": {...}}

        Format 10: XML with name attributes
            <function_call name="tool">...</function_call>
            <tool name="...">...</tool>
            <action name="...">...</action>

        Format 11: YAML in code fences
            ```yaml
            tool: tool_name
            arguments:
              key: value
            ```

        Format 12: Thought/Action/Observation pattern
            Thought: reasoning
            Action: tool_name
            Action Input: {...}
            Observation: result

        Format 13: OpenAI function wrapper
            {"type": "function", "function": {"name": "...", "arguments": {...}}}

        Format 14: Cohere-style
            {"tool_name": "...", "parameters": {...}}

        Format 15: Gemini-style
            {"function_call": {"name": "...", "args": {...}}}

        Format 16: Array formats for multiple calls
            <tool_calls>[{...}, {...}]</tool_calls>
            <function_calls>[...]</function_calls>

        Format 17: Raw JSON array (no wrapper)
            [{"tool": "a", "arguments": {}}, ...]

        Format 18: Qwen/DeepSeek special tokens
            <|tool_call|>{"name": "...", "arguments": {...}}<|/tool_call|>
            [TOOL_CALL]...[/TOOL_CALL]

        Format 19: Use/Call directive style
            Use: tool_name
            With: {"key": "value"}

        Format 20: Markdown-style sections
            ## Tool: tool_name
            ### Arguments:
            ```json
            {...}
            ```

        Format 21: Simple key-value style (no JSON)
            tool: tool_name
            arg1: value1
            arg2: value2

        Format 22: HTML code fence auto-correction (request_decision injection)
            ```html
            <div>Any HTML content here</div>
            ```
            → Automatically converted to request_decision(html=...) for rendering

        Returns:
            tuple: (tool_calls, error_message)
                - tool_calls: List of parsed tool calls in native format
                - error_message: Error description if parsing failed, None if successful
        """
        if not content:
            return [], None

        import re
        tool_calls = []
        parse_errors = []

        # Common programming languages that should NOT be treated as tool names
        NON_TOOL_LANGUAGES = {
            'json', 'javascript', 'js', 'typescript', 'ts', 'python', 'py',
            'bash', 'sh', 'shell', 'zsh', 'html', 'css', 'xml', 'yaml', 'yml',
            'sql', 'markdown', 'md', 'text', 'txt', 'plaintext', 'c', 'cpp',
            'java', 'go', 'rust', 'ruby', 'php', 'swift', 'kotlin', 'scala',
            'r', 'matlab', 'perl', 'lua', 'vim', 'diff', 'dockerfile', 'makefile',
            'toml', 'ini', 'conf', 'config', 'log', 'csv', 'tsv', 'graphql',
            'proto', 'protobuf', 'terraform', 'hcl', 'nginx', 'apache'
        }

        def add_tool_call(tool_name: str, arguments: dict):
            """Helper to add a validated tool call."""
            tool_calls.append({
                "id": f"prompt_tool_{len(tool_calls)}",
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": json.dumps(arguments)
                }
            })

        # ============================================================
        # Pattern 1: Code fences with any language identifier
        # Matches: ```language_or_tool {...} ```
        # ============================================================
        code_fence_pattern = r'```(\w*)\s*\n?([\s\S]*?)\n?\s*```'

        for match in re.finditer(code_fence_pattern, content, re.DOTALL):
            language = (match.group(1) or '').lower().strip()
            block_content = match.group(2).strip()

            if not block_content:
                continue

            # Try to parse as JSON
            try:
                data = json.loads(block_content)
            except json.JSONDecodeError as e:
                # Check if this looks like a tool call attempt
                if '"tool"' in block_content or language not in NON_TOOL_LANGUAGES:
                    # Might be a malformed tool call
                    if '{' in block_content:  # Only report if it looks like JSON
                        error_detail = f"Possible tool call with malformed JSON:\n"
                        error_detail += f"  Language: {language or '(none)'}\n"
                        error_detail += f"  Error: {e.msg} at position {e.pos}\n"
                        error_detail += f"  Content: {block_content[:150]}{'...' if len(block_content) > 150 else ''}\n"
                        parse_errors.append(error_detail)
                continue

            if not isinstance(data, dict):
                continue

            # Case A: Standard format {"tool": "name", "arguments": {...}}
            if "tool" in data:
                tool_name = data.get("tool")
                arguments = data.get("arguments", {})

                # Handle case where arguments is the tool call itself (nested)
                if not isinstance(arguments, dict):
                    # Try to use the rest of the data as arguments
                    arguments = {k: v for k, v in data.items() if k != "tool"}

                if tool_name and isinstance(tool_name, str):
                    add_tool_call(tool_name, arguments)
                continue

            # Case B: {"name": "tool_name", "arguments": {...}} variant
            if "name" in data and "arguments" in data:
                tool_name = data.get("name")
                arguments = data.get("arguments", {})
                if tool_name and isinstance(tool_name, str) and isinstance(arguments, dict):
                    add_tool_call(tool_name, arguments)
                continue

            # Case C: Language identifier IS the tool name
            # Only if language is not a known programming language
            if language and language not in NON_TOOL_LANGUAGES:
                # The JSON content is the arguments directly
                # Check if it has an "arguments" wrapper
                if "arguments" in data and isinstance(data["arguments"], dict):
                    arguments = data["arguments"]
                else:
                    # Content is direct arguments
                    arguments = data

                add_tool_call(language, arguments)
                continue

        # ============================================================
        # Pattern 2: XML-style tags with tool structure inside
        # ============================================================
        xml_patterns = [
            (r'<tool_call>\s*([\s\S]*?)\s*</tool_call>', None),
            (r'<function_call>\s*([\s\S]*?)\s*</function_call>', None),
            (r'<tools?>\s*([\s\S]*?)\s*</tools?>', None),
            # Invoke pattern with name attribute
            (r'<invoke\s+name=["\'](\w+)["\']\s*>\s*([\s\S]*?)\s*</invoke>', 'invoke'),
            (r'<call\s+name=["\'](\w+)["\']\s*>\s*([\s\S]*?)\s*</call>', 'invoke'),
        ]

        for pattern, pattern_type in xml_patterns:
            for match in re.finditer(pattern, content, re.DOTALL | re.IGNORECASE):
                if pattern_type == 'invoke':
                    # Name is in the tag attribute, content is arguments
                    tool_name = match.group(1)
                    xml_content = match.group(2).strip()

                    try:
                        arguments = json.loads(xml_content) if xml_content else {}
                        if isinstance(arguments, dict):
                            add_tool_call(tool_name, arguments)
                    except json.JSONDecodeError:
                        parse_errors.append(f"Malformed JSON in <invoke name=\"{tool_name}\">: {xml_content[:100]}")
                else:
                    # Standard XML tag - content should have tool structure
                    xml_content = match.group(1).strip()

                    try:
                        data = json.loads(xml_content)
                        if isinstance(data, dict) and "tool" in data:
                            tool_name = data.get("tool")
                            arguments = data.get("arguments", {})
                            if isinstance(arguments, dict):
                                add_tool_call(tool_name, arguments)
                    except json.JSONDecodeError:
                        if '"tool"' in xml_content:
                            parse_errors.append(f"Malformed JSON in XML tool tag: {xml_content[:100]}")

        # ============================================================
        # Pattern 3: Array formats for multiple tool calls
        # ============================================================
        array_patterns = [
            r'<function_calls>\s*(\[[\s\S]*?\])\s*</function_calls>',
            r'<tool_calls>\s*(\[[\s\S]*?\])\s*</tool_calls>',
        ]

        for pattern in array_patterns:
            for match in re.finditer(pattern, content, re.DOTALL | re.IGNORECASE):
                array_block = match.group(1)
                try:
                    array_data = json.loads(array_block.strip())
                    if isinstance(array_data, list):
                        for item in array_data:
                            if isinstance(item, dict) and "tool" in item:
                                tool_name = item.get("tool")
                                arguments = item.get("arguments", {})
                                if isinstance(arguments, dict):
                                    add_tool_call(tool_name, arguments)
                except json.JSONDecodeError as e:
                    if '"tool"' in array_block:
                        parse_errors.append(f"Malformed tool calls array: {e.msg}")

        # ============================================================
        # Pattern 4: Function call syntax: tool_name({...})
        # Matches: request_decision({"question": "...", "options": [...]})
        # ============================================================
        func_call_pattern = r'\b(\w+)\s*\(\s*(\{[\s\S]*?\})\s*\)'

        for match in re.finditer(func_call_pattern, content):
            func_name = match.group(1)
            func_args = match.group(2)

            # Skip common non-tool function names
            if func_name.lower() in {'print', 'console', 'log', 'json', 'dict', 'list', 'str', 'int', 'float', 'bool'}:
                continue

            try:
                arguments = json.loads(func_args)
                if isinstance(arguments, dict):
                    # This looks like a tool call in function syntax
                    add_tool_call(func_name, arguments)
            except json.JSONDecodeError:
                pass  # Not valid JSON, skip silently

        # ============================================================
        # Pattern 5: Anthropic/Claude-style <function_calls><invoke>
        # With <parameter> elements for each argument
        # ============================================================
        # Pattern: <function_calls><invoke name="tool_name"><parameter name="key">value</parameter></invoke></function_calls>
        # Also: <function_calls><invoke name="...">
        invoke_with_params_pattern = r'<(?:antml:)?invoke\s+name=["\'](\w+)["\']>\s*([\s\S]*?)\s*</(?:antml:)?invoke>'

        for match in re.finditer(invoke_with_params_pattern, content, re.DOTALL | re.IGNORECASE):
            tool_name = match.group(1)
            params_content = match.group(2).strip()

            # Check if it contains <parameter> or <parameter> elements
            param_pattern = r'<(?:antml:)?parameter\s+name=["\'](\w+)["\']\s*>([\s\S]*?)</(?:antml:)?parameter>'
            param_matches = re.findall(param_pattern, params_content, re.DOTALL | re.IGNORECASE)

            if param_matches:
                # Build arguments from parameter elements
                arguments = {}
                for param_name, param_value in param_matches:
                    # Try to parse as JSON, otherwise use as string
                    param_value = param_value.strip()
                    try:
                        arguments[param_name] = json.loads(param_value)
                    except json.JSONDecodeError:
                        arguments[param_name] = param_value
                add_tool_call(tool_name, arguments)
            elif params_content:
                # Fall back to trying to parse as JSON directly
                try:
                    arguments = json.loads(params_content)
                    if isinstance(arguments, dict):
                        add_tool_call(tool_name, arguments)
                except json.JSONDecodeError:
                    pass

        # ============================================================
        # Pattern 6: ReAct-style (Action: / Action Input:)
        # Common in agent frameworks like LangChain
        # ============================================================
        # Pattern: Action: tool_name\nAction Input: {"key": "value"}
        # Also handles: Action: tool_name\nAction Input:\n```json\n{...}\n```
        react_pattern = r'Action:\s*(\w+)\s*\n\s*Action\s*Input:\s*(.+?)(?=\n(?:Observation:|Thought:|Action:|$)|\Z)'

        for match in re.finditer(react_pattern, content, re.DOTALL | re.IGNORECASE):
            action_name = match.group(1).strip()
            action_input = match.group(2).strip()

            if action_name.lower() in NON_TOOL_LANGUAGES:
                continue

            # Strip code fences if present
            code_fence_match = re.search(r'```(?:\w*)\s*\n?([\s\S]*?)\n?\s*```', action_input)
            if code_fence_match:
                action_input = code_fence_match.group(1).strip()

            try:
                arguments = json.loads(action_input)
                if isinstance(arguments, dict):
                    add_tool_call(action_name, arguments)
            except json.JSONDecodeError:
                # Try treating the whole input as a single string argument
                if action_input and not action_input.startswith('{'):
                    add_tool_call(action_name, {"input": action_input})

        # ============================================================
        # Pattern 7: Mistral-style [TOOL_CALLS] format
        # ============================================================
        # Pattern: [TOOL_CALLS] [{"name": "tool", "arguments": {...}}]
        mistral_pattern = r'\[TOOL_CALLS?\]\s*(\[[\s\S]*?\])'

        for match in re.finditer(mistral_pattern, content, re.DOTALL | re.IGNORECASE):
            tool_array = match.group(1).strip()
            try:
                tools = json.loads(tool_array)
                if isinstance(tools, list):
                    for tool in tools:
                        if isinstance(tool, dict):
                            tool_name = tool.get("name") or tool.get("tool")
                            arguments = tool.get("arguments") or tool.get("parameters") or {}
                            if tool_name and isinstance(arguments, dict):
                                add_tool_call(tool_name, arguments)
            except json.JSONDecodeError:
                parse_errors.append(f"Malformed Mistral-style tool calls: {tool_array[:100]}")

        # ============================================================
        # Pattern 8: Hermes/ChatML tool call format
        # ============================================================
        # Pattern: <tool_call>\n{"name": "tool", "arguments": {...}}\n</tool_call>
        # Some models use "name" instead of "tool" as the key
        hermes_pattern = r'<tool_call>\s*([\s\S]*?)\s*</tool_call>'

        for match in re.finditer(hermes_pattern, content, re.DOTALL | re.IGNORECASE):
            tool_content = match.group(1).strip()
            try:
                data = json.loads(tool_content)
                if isinstance(data, dict):
                    tool_name = data.get("name") or data.get("tool") or data.get("function")
                    arguments = data.get("arguments") or data.get("parameters") or data.get("args") or {}
                    # Handle nested function structure
                    if "function" in data and isinstance(data["function"], dict):
                        tool_name = data["function"].get("name")
                        arguments = data["function"].get("arguments", {})
                        if isinstance(arguments, str):
                            try:
                                arguments = json.loads(arguments)
                            except json.JSONDecodeError:
                                arguments = {"input": arguments}
                    if tool_name and isinstance(arguments, dict):
                        add_tool_call(tool_name, arguments)
            except json.JSONDecodeError:
                pass

        # ============================================================
        # Pattern 9: Single-line JSON tool calls (no code fences)
        # For models that output bare JSON on its own line
        # ============================================================
        # Match lines starting with { that contain tool/name/function key
        bare_json_indicator = r'^[ \t]*\{.*"(?:tool|name|function)"'

        for match in re.finditer(bare_json_indicator, content, re.MULTILINE):
            # Found a potential bare JSON tool call, extract full JSON
            start_pos = match.start()
            # Skip leading whitespace
            while start_pos < len(content) and content[start_pos] in ' \t':
                start_pos += 1

            # Find balanced braces
            brace_count = 0
            end_pos = start_pos

            for i, c in enumerate(content[start_pos:]):
                if c == '{':
                    brace_count += 1
                elif c == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        end_pos = start_pos + i + 1
                        break
                elif c == '\n' and brace_count == 0:
                    # Hit newline before closing brace at root level
                    break

            if brace_count == 0 and end_pos > start_pos:
                json_str = content[start_pos:end_pos].strip()
                try:
                    data = json.loads(json_str)
                    if isinstance(data, dict):
                        tool_name = data.get("tool") or data.get("name") or data.get("function")
                        arguments = data.get("arguments") or data.get("parameters") or data.get("args") or {}
                        # Handle nested {"function": {"name": ..., "arguments": ...}}
                        if "function" in data and isinstance(data["function"], dict):
                            tool_name = data["function"].get("name")
                            arguments = data["function"].get("arguments", {})
                            if isinstance(arguments, str):
                                try:
                                    arguments = json.loads(arguments)
                                except json.JSONDecodeError:
                                    arguments = {"input": arguments}
                        if tool_name and isinstance(arguments, dict):
                            add_tool_call(tool_name, arguments)
                except json.JSONDecodeError:
                    pass

        # ============================================================
        # Pattern 10: XML with name attribute variants
        # <function_call name="tool">...</function_call>
        # ============================================================
        xml_name_attr_patterns = [
            (r'<function_call\s+name=["\'](\w+)["\']\s*(?:/)?\s*>', 'function_call'),
            (r'<function_call\s+name=["\'](\w+)["\']\s*>\s*([\s\S]*?)\s*</function_call>', 'function_call_full'),
            (r'<tool\s+name=["\'](\w+)["\']\s*>\s*([\s\S]*?)\s*</tool>', 'tool_full'),
            (r'<action\s+name=["\'](\w+)["\']\s*>\s*([\s\S]*?)\s*</action>', 'action_full'),
        ]

        for pattern, pattern_type in xml_name_attr_patterns:
            for match in re.finditer(pattern, content, re.DOTALL | re.IGNORECASE):
                if pattern_type == 'function_call':
                    # Self-closing or empty, no arguments
                    tool_name = match.group(1)
                    add_tool_call(tool_name, {})
                else:
                    tool_name = match.group(1)
                    xml_content = match.group(2).strip() if len(match.groups()) > 1 else ""

                    arguments = {}
                    if xml_content:
                        # Try JSON first
                        try:
                            arguments = json.loads(xml_content)
                            if not isinstance(arguments, dict):
                                arguments = {"value": arguments}
                        except json.JSONDecodeError:
                            # Try parsing as XML parameters
                            param_pattern = r'<(\w+)>([\s\S]*?)</\1>'
                            param_matches = re.findall(param_pattern, xml_content, re.DOTALL)
                            if param_matches:
                                for param_name, param_value in param_matches:
                                    param_value = param_value.strip()
                                    try:
                                        arguments[param_name] = json.loads(param_value)
                                    except json.JSONDecodeError:
                                        arguments[param_name] = param_value
                            else:
                                # Use as single input
                                arguments = {"input": xml_content}

                    if isinstance(arguments, dict):
                        add_tool_call(tool_name, arguments)

        # ============================================================
        # Pattern 11: YAML-style tool calls in code fences
        # ```yaml
        # tool: tool_name
        # arguments:
        #   key: value
        # ```
        # ============================================================
        yaml_fence_pattern = r'```ya?ml\s*\n([\s\S]*?)\n\s*```'

        for match in re.finditer(yaml_fence_pattern, content, re.DOTALL | re.IGNORECASE):
            yaml_content = match.group(1).strip()
            try:
                import yaml as yaml_lib
                data = yaml_lib.safe_load(yaml_content)
                if isinstance(data, dict):
                    tool_name = data.get("tool") or data.get("name") or data.get("function") or data.get("action")
                    arguments = data.get("arguments") or data.get("parameters") or data.get("args") or data.get("input") or {}
                    # If tool_name not found but there's a single key that looks like a tool
                    if not tool_name and len(data) == 2:
                        for key in data:
                            if key not in ('arguments', 'parameters', 'args', 'input'):
                                tool_name = key
                                arguments = data.get(key, {})
                                break
                    if tool_name and isinstance(tool_name, str):
                        if not isinstance(arguments, dict):
                            arguments = {"value": arguments}
                        add_tool_call(tool_name, arguments)
            except Exception:
                pass  # YAML parsing failed, skip

        # ============================================================
        # Pattern 12: Thought/Action/Action Input (TAO) with Observation
        # Used by some agent frameworks
        # ============================================================
        tao_pattern = r'(?:Thought:.*?\n)?Action:\s*(\w+)\s*\nAction\s*Input:\s*([\s\S]*?)(?=\nObservation:|\nThought:|\nAction:|\Z)'

        for match in re.finditer(tao_pattern, content, re.DOTALL | re.IGNORECASE):
            action_name = match.group(1).strip()
            action_input = match.group(2).strip()

            if action_name.lower() in NON_TOOL_LANGUAGES:
                continue

            # Skip if already handled by ReAct pattern
            # (This is a more permissive variant)
            try:
                # Try parsing as JSON
                arguments = json.loads(action_input)
                if isinstance(arguments, dict):
                    add_tool_call(action_name, arguments)
            except json.JSONDecodeError:
                # Use as string input if not valid JSON
                if action_input:
                    add_tool_call(action_name, {"input": action_input})

        # ============================================================
        # Pattern 13: OpenAI-style function wrapper
        # {"type": "function", "function": {"name": "...", "arguments": "..."}}
        # ============================================================
        # Look for JSON objects containing "type": "function" pattern
        openai_indicator_pattern = r'\{[^{}]*"type"\s*:\s*"function"[^{}]*"function"\s*:'

        for match in re.finditer(openai_indicator_pattern, content, re.DOTALL):
            # Found potential OpenAI format, extract the full JSON object
            start_pos = match.start()
            brace_count = 0
            end_pos = start_pos

            for i, c in enumerate(content[start_pos:]):
                if c == '{':
                    brace_count += 1
                elif c == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        end_pos = start_pos + i + 1
                        break

            try:
                data = json.loads(content[start_pos:end_pos])
                if isinstance(data, dict) and data.get("type") == "function" and "function" in data:
                    func_data = data["function"]
                    tool_name = func_data.get("name")
                    arguments = func_data.get("arguments", {})
                    if isinstance(arguments, str):
                        try:
                            arguments = json.loads(arguments)
                        except json.JSONDecodeError:
                            arguments = {"input": arguments}
                    if tool_name and isinstance(arguments, dict):
                        add_tool_call(tool_name, arguments)
            except json.JSONDecodeError:
                pass

        # ============================================================
        # Pattern 14: Cohere-style tool calls
        # {"tool_name": "...", "parameters": {...}}
        # ============================================================
        # Already partially covered by other patterns but let's be explicit
        cohere_pattern = r'\{\s*"tool_name"\s*:\s*"(\w+)"\s*,\s*"parameters"\s*:\s*(\{[^{}]*\})\s*\}'

        for match in re.finditer(cohere_pattern, content, re.DOTALL):
            tool_name = match.group(1)
            params_str = match.group(2)
            try:
                arguments = json.loads(params_str)
                if isinstance(arguments, dict):
                    add_tool_call(tool_name, arguments)
            except json.JSONDecodeError:
                pass

        # ============================================================
        # Pattern 15: Gemini-style function_call
        # {"function_call": {"name": "...", "args": {...}}}
        # ============================================================
        gemini_pattern = r'\{\s*"function_call"\s*:\s*\{\s*"name"\s*:\s*"(\w+)"\s*,\s*"args"\s*:\s*(\{[\s\S]*?\})\s*\}\s*\}'

        for match in re.finditer(gemini_pattern, content, re.DOTALL):
            tool_name = match.group(1)
            args_str = match.group(2)
            try:
                arguments = json.loads(args_str)
                if isinstance(arguments, dict):
                    add_tool_call(tool_name, arguments)
            except json.JSONDecodeError:
                pass

        # ============================================================
        # Pattern 16: Raw JSON array of tool calls (no wrapper)
        # [{"tool": "a", "arguments": {}}, {"tool": "b", "arguments": {}}]
        # ============================================================
        # Match a JSON array that starts on its own line
        raw_array_pattern = r'^[ \t]*(\[[\s\S]*?\])[ \t]*$'

        for match in re.finditer(raw_array_pattern, content, re.MULTILINE):
            array_str = match.group(1).strip()
            try:
                data = json.loads(array_str)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            tool_name = item.get("tool") or item.get("name") or item.get("function")
                            arguments = item.get("arguments") or item.get("parameters") or item.get("args") or {}
                            if tool_name and isinstance(arguments, dict):
                                add_tool_call(tool_name, arguments)
            except json.JSONDecodeError:
                pass

        # ============================================================
        # Pattern 17: Qwen/DeepSeek style with <|tool_call|> tokens
        # <|tool_call|>{"name": "...", "arguments": {...}}<|/tool_call|>
        # ============================================================
        special_token_patterns = [
            r'<\|tool_call\|>\s*([\s\S]*?)\s*<\|/tool_call\|>',
            r'<\|function_call\|>\s*([\s\S]*?)\s*<\|/function_call\|>',
            r'<\|action\|>\s*([\s\S]*?)\s*<\|/action\|>',
            r'\[TOOL_CALL\]\s*([\s\S]*?)\s*\[/TOOL_CALL\]',
        ]

        for pattern in special_token_patterns:
            for match in re.finditer(pattern, content, re.DOTALL | re.IGNORECASE):
                token_content = match.group(1).strip()
                try:
                    data = json.loads(token_content)
                    if isinstance(data, dict):
                        tool_name = data.get("name") or data.get("tool") or data.get("function")
                        arguments = data.get("arguments") or data.get("parameters") or data.get("args") or {}
                        if tool_name and isinstance(arguments, dict):
                            add_tool_call(tool_name, arguments)
                except json.JSONDecodeError:
                    pass

        # ============================================================
        # Pattern 18: Use/Call directive style (some instruction models)
        # Use: tool_name
        # With: {"key": "value"}
        # ============================================================
        use_directive_pattern = r'(?:Use|Call|Execute|Run):\s*(\w+)\s*\n\s*(?:With|Args|Arguments|Params|Parameters):\s*(\{[\s\S]*?\})'

        for match in re.finditer(use_directive_pattern, content, re.IGNORECASE):
            tool_name = match.group(1).strip()
            args_str = match.group(2).strip()

            if tool_name.lower() in NON_TOOL_LANGUAGES:
                continue

            try:
                arguments = json.loads(args_str)
                if isinstance(arguments, dict):
                    add_tool_call(tool_name, arguments)
            except json.JSONDecodeError:
                pass

        # ============================================================
        # Pattern 19: Markdown-style tool call (## Tool: / ### Arguments:)
        # ## Tool: tool_name
        # ### Arguments:
        # ```json
        # {...}
        # ```
        # ============================================================
        md_tool_pattern = r'#{1,3}\s*Tool:\s*(\w+)\s*\n(?:.*\n)*?#{1,3}\s*Arguments?:\s*\n```(?:json)?\s*\n([\s\S]*?)\n```'

        for match in re.finditer(md_tool_pattern, content, re.IGNORECASE):
            tool_name = match.group(1).strip()
            args_str = match.group(2).strip()

            try:
                arguments = json.loads(args_str)
                if isinstance(arguments, dict):
                    add_tool_call(tool_name, arguments)
            except json.JSONDecodeError:
                pass

        # ============================================================
        # Pattern 20: Simple key-value style without JSON
        # tool: tool_name
        # arg1: value1
        # arg2: value2
        # ============================================================
        # Match lines starting with "tool:" or "function:" followed by key-value pairs
        simple_kv_pattern = r'^(?:tool|function|action):\s*(\w+)\s*\n((?:\w+:\s*.+\n?)+)'

        for match in re.finditer(simple_kv_pattern, content, re.MULTILINE | re.IGNORECASE):
            tool_name = match.group(1).strip()
            kv_block = match.group(2)

            if tool_name.lower() in NON_TOOL_LANGUAGES:
                continue

            # Parse key-value pairs
            arguments = {}
            kv_lines = kv_block.strip().split('\n')
            for line in kv_lines:
                if ':' in line:
                    key, value = line.split(':', 1)
                    key = key.strip()
                    value = value.strip()
                    # Skip if key looks like a tool indicator
                    if key.lower() in ('tool', 'function', 'action', 'name'):
                        continue
                    # Try to parse value as JSON
                    try:
                        arguments[key] = json.loads(value)
                    except json.JSONDecodeError:
                        arguments[key] = value

            if arguments:
                add_tool_call(tool_name, arguments)

        # ============================================================
        # Pattern 22: Auto-correct HTML code fences to request_decision
        # When dumber models forget to use request_decision and just
        # output HTML in code fences, auto-convert it to a tool call.
        # The checkpoint system has fallback UI for responses even
        # without proper form callbacks, so we render ALL HTML.
        # Pattern handles both actual newlines and escaped \n as literal strings
        # ============================================================
        html_fence_pattern = r'```html(?:\s*\n|\\n)([\s\S]*?)(?:\n|\\n)?\s*```'

        for match in re.finditer(html_fence_pattern, content, re.DOTALL | re.IGNORECASE):
            html_content = match.group(1).strip()

            if not html_content:
                continue

            # Unescape literal \n and \t to actual newlines/tabs
            html_content = html_content.replace('\\n', '\n').replace('\\t', '\t')

            # Skip if we already have a request_decision tool call
            # (this would mean the model did it correctly)
            has_request_decision = any(
                tc.get("function", {}).get("name") == "request_decision"
                for tc in tool_calls
            )
            if has_request_decision:
                continue

            # Try to extract a question from the surrounding text
            # Look for text before the code fence that looks like a question
            match_start = match.start()
            preceding_text = content[:match_start].strip()

            # Get the last paragraph or sentence before the HTML
            question = "Please provide your response"
            if preceding_text:
                # Split by double newlines to get paragraphs
                paragraphs = preceding_text.split('\n\n')
                if paragraphs:
                    last_para = paragraphs[-1].strip()
                    # Clean up markdown and get last meaningful line
                    lines = [l.strip() for l in last_para.split('\n') if l.strip()]
                    if lines:
                        # Use last non-empty line as question context
                        potential_question = lines[-1]
                        # Remove markdown formatting
                        potential_question = re.sub(r'^#+\s*', '', potential_question)  # Remove headers
                        potential_question = re.sub(r'^\*+\s*', '', potential_question)  # Remove bullets
                        potential_question = re.sub(r'^-\s*', '', potential_question)    # Remove dashes
                        potential_question = potential_question.strip()
                        if potential_question and len(potential_question) > 5:
                            question = potential_question

            # Log the auto-correction to console
            console.print(
                f"[yellow]⚠️  AUTO-CORRECTED: Model output HTML in code fence instead of "
                f"using request_decision tool. Injecting into request_decision call.[/yellow]"
            )

            # Create the request_decision tool call
            arguments = {
                "question": question,
                "options": [],  # Empty - the HTML has its own UI
                "html": html_content,
                "severity": "info",
                "allow_custom": True
            }

            add_tool_call("request_decision", arguments)

        # ============================================================
        # Return results
        # ============================================================
        if tool_calls:
            # Deduplicate tool calls (same tool + same arguments)
            seen = set()
            unique_calls = []
            for call in tool_calls:
                key = (call["function"]["name"], call["function"]["arguments"])
                if key not in seen:
                    seen.add(key)
                    # Re-number the IDs
                    call["id"] = f"prompt_tool_{len(unique_calls)}"
                    unique_calls.append(call)
            return unique_calls, None

        if parse_errors:
            error_msg = "\n".join(parse_errors)
            return [], error_msg

        # No tool calls found
        return [], None

    def _auto_correct_html_to_request_decision(self, content: str, existing_tool_calls: list) -> list:
        """
        Auto-correct HTML code fences to request_decision tool calls.

        When models output HTML in ```html code fences instead of properly
        using the request_decision tool, this method detects and converts them.
        The checkpoint system has fallback UI for responses even without
        proper form callbacks.

        Args:
            content: The assistant response content
            existing_tool_calls: Already parsed tool calls (to check for existing request_decision)

        Returns:
            List of auto-corrected tool calls (may be empty)
        """
        import re

        if not content:
            return []

        # Skip if we already have a request_decision tool call
        has_request_decision = any(
            tc.get("function", {}).get("name") == "request_decision"
            for tc in existing_tool_calls
        )
        if has_request_decision:
            return []

        auto_calls = []
        # Pattern handles both actual newlines and escaped \n as literal strings
        html_fence_pattern = r'```html(?:\s*\n|\\n)([\s\S]*?)(?:\n|\\n)?\s*```'

        for match in re.finditer(html_fence_pattern, content, re.DOTALL | re.IGNORECASE):
            html_content = match.group(1).strip()

            if not html_content:
                continue

            # Unescape literal \n and \t to actual newlines/tabs
            html_content = html_content.replace('\\n', '\n').replace('\\t', '\t')

            # Try to extract a question from the surrounding text
            match_start = match.start()
            preceding_text = content[:match_start].strip()

            question = "Please provide your response"
            if preceding_text:
                paragraphs = preceding_text.split('\n\n')
                if paragraphs:
                    last_para = paragraphs[-1].strip()
                    lines = [l.strip() for l in last_para.split('\n') if l.strip()]
                    if lines:
                        potential_question = lines[-1]
                        potential_question = re.sub(r'^#+\s*', '', potential_question)
                        potential_question = re.sub(r'^\*+\s*', '', potential_question)
                        potential_question = re.sub(r'^-\s*', '', potential_question)
                        potential_question = potential_question.strip()
                        if potential_question and len(potential_question) > 5:
                            question = potential_question

            # Log the auto-correction to console
            console.print(
                f"[yellow]⚠️  AUTO-CORRECTED: Model output HTML in code fence instead of "
                f"using request_decision tool. Injecting into request_decision call.[/yellow]"
            )

            # Create the request_decision tool call
            arguments = {
                "question": question,
                "options": [],
                "html": html_content,
                "severity": "info",
                "allow_custom": True
            }

            auto_calls.append({
                "id": f"html_auto_{len(auto_calls)}",
                "type": "function",
                "function": {
                    "name": "request_decision",
                    "arguments": json.dumps(arguments)
                }
            })

        return auto_calls

    def _run_with_cascade_soundings(self, input_data: dict = None) -> dict:
        """
        Execute cascade with soundings (Tree of Thought at cascade level).
        Spawns N complete cascade executions in parallel, evaluates them, and returns only the winner.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        indent = "  " * self.depth

        # Resolve soundings factor (may be Jinja2 template string)
        if isinstance(self.config.candidates.factor, str):
            from .prompts import render_instruction
            # For cascade-level soundings, we have limited context (just inputs)
            render_context = {
                "input": input_data or {},
                "state": {},
                "history": [],
                "outputs": {},
                "lineage": [],
            }
            rendered_factor = render_instruction(self.config.candidates.factor, render_context)
            try:
                factor = int(rendered_factor.strip())
            except ValueError:
                console.print(f"{indent}[red]⚠ Warning: Could not parse cascade soundings factor '{rendered_factor}' as integer, defaulting to 1[/red]")
                factor = 1
        else:
            factor = self.config.candidates.factor

        max_parallel = self.config.candidates.max_parallel or 3
        max_workers = min(factor, max_parallel)

        console.print(f"{indent}[bold blue]🔱 Taking {factor} CASCADE Soundings (Parallel: {max_workers} workers)...[/bold blue]")

        # Create soundings trace node
        soundings_trace = self.trace.create_child("cascade_soundings", f"{self.config.cascade_id}_soundings")

        # Add to echo history for visualization (auto-logs via unified_logs)
        self.echo.add_history({
            "role": "cascade_soundings",
            "content": f"🔱 Running {factor} cascade soundings",
            "node_type": "cascade_soundings"
        }, trace_id=soundings_trace.id, parent_id=self.trace.id, node_type="cascade_soundings",
           metadata={
               "cascade_id": self.config.cascade_id,
               "cell_name": "_orchestration",  # Ensure UI can query this
               "factor": factor,
               "max_parallel": max_workers,
               "semantic_actor": "framework",
               "semantic_purpose": "lifecycle"
           })

        # Pre-create traces for all soundings (must be done sequentially for proper hierarchy)
        sounding_traces = []
        for i in range(factor):
            trace = soundings_trace.create_child("cascade_sounding_attempt", f"attempt_{i+1}")
            sounding_traces.append(trace)

        # Define the worker function for parallel execution
        def run_single_cascade_sounding(i: int) -> dict:
            """Execute a single cascade candidate. Returns result dict."""
            from .echo import Echo
            from .events import get_event_bus, Event
            from datetime import datetime

            sounding_trace = sounding_traces[i]
            sounding_session_id = f"{self.session_id}_sounding_{i}"
            sounding_echo = Echo(sounding_session_id, parent_session_id=self.session_id)

            console.print(f"{indent}  [cyan]🌊 Cascade Sounding {i+1}/{factor} starting...[/cyan]")

            # Create session state in ClickHouse for the sub-cascade candidate
            # This ensures the UI can track sub-cascade sessions correctly
            try:
                create_session_state(
                    session_id=sounding_session_id,
                    cascade_id=self.config.cascade_id,
                    parent_session_id=self.session_id,
                    depth=self.depth,
                    metadata={"cascade_sounding": True, "candidate_index": i, "factor": factor}
                )
                update_session_status(sounding_session_id, SessionStatus.RUNNING)
            except Exception as state_err:
                # Don't fail the candidate if session state creation fails
                import logging
                logging.getLogger(__name__).debug(f"Could not create session state for cascade candidate: {state_err}")

            # Emit sounding_start event for real-time UI tracking
            event_bus = get_event_bus()
            event_bus.publish(Event(
                type="sounding_start",
                session_id=self.session_id,
                timestamp=datetime.now().isoformat(),
                data={
                    "cell_name": "_orchestration",
                    "candidate_index": i,
                    "trace_id": sounding_trace.id,
                    "factor": factor,
                    "cascade_sounding": True,
                    "sub_session_id": sounding_session_id
                }
            ))

            try:
                # Create a new runner for this candidate with candidate_index set
                sounding_runner = RVBBITRunner(
                    config_path=self.config_path,
                    session_id=sounding_session_id,
                    overrides=self.overrides,
                    depth=self.depth,
                    parent_trace=sounding_trace,
                    hooks=self.hooks,
                    candidate_index=i,  # Mark this runner as part of a candidate
                    parent_session_id=self.session_id  # Link child to parent session
                )

                # Run the cascade with candidate metadata
                result = sounding_runner._run_cascade_internal(input_data)

                # Update session status to COMPLETED in ClickHouse
                try:
                    final_status = SessionStatus.ERROR if result.get("has_errors") else SessionStatus.COMPLETED
                    update_session_status(
                        sounding_session_id,
                        final_status,
                        error_message=str(result.get("errors", [])[:1]) if result.get("has_errors") else None
                    )
                except Exception:
                    pass  # Don't fail if status update fails

                # Extract final result from echo
                final_output = result.get("final_output", str(result))

                console.print(f"{indent}    [green]✓ Cascade Sounding {i+1} complete[/green]")

                # Emit sounding_complete event for real-time UI tracking
                event_bus.publish(Event(
                    type="sounding_complete",
                    session_id=self.session_id,
                    timestamp=datetime.now().isoformat(),
                    data={
                        "cell_name": "_orchestration",
                        "candidate_index": i,
                        "trace_id": sounding_trace.id,
                        "factor": factor,
                        "cascade_sounding": True,
                        "sub_session_id": sounding_session_id,
                        "success": True
                    }
                ))

                return {
                    "index": i,
                    "result": final_output,
                    "echo": sounding_echo,
                    "trace_id": sounding_trace.id,
                    "full_result": result,
                    "session_id": sounding_session_id
                }

            except Exception as e:
                console.print(f"{indent}    [red]✗ Cascade Sounding {i+1} failed: {e}[/red]")

                # Update session status to ERROR in ClickHouse
                try:
                    update_session_status(
                        sounding_session_id,
                        SessionStatus.ERROR,
                        error_message=str(e)[:500]
                    )
                except Exception:
                    pass  # Don't fail if status update fails

                # Emit sounding_complete event for real-time UI tracking (error case)
                event_bus.publish(Event(
                    type="sounding_complete",
                    session_id=self.session_id,
                    timestamp=datetime.now().isoformat(),
                    data={
                        "cell_name": "_orchestration",
                        "candidate_index": i,
                        "trace_id": sounding_trace.id,
                        "factor": factor,
                        "cascade_sounding": True,
                        "sub_session_id": sounding_session_id,
                        "success": False,
                        "error": str(e)
                    }
                ))

                return {
                    "index": i,
                    "result": f"[ERROR: {str(e)}]",
                    "echo": None,
                    "trace_id": sounding_trace.id,
                    "full_result": {},
                    "session_id": sounding_session_id,
                    "failed": True,
                    "error": str(e)
                }

        # Execute soundings in parallel
        sounding_results = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(run_single_cascade_sounding, i): i for i in range(factor)}

            for future in as_completed(futures):
                result = future.result()
                sounding_results.append(result)

        # Sort results by index to maintain consistent ordering
        sounding_results.sort(key=lambda x: x['index'])

        # Log results to echo history (must be done sequentially after parallel execution)
        for sr in sounding_results:
            i = sr['index']
            if sr.get('failed'):
                log_message(self.session_id, "cascade_sounding_error", sr.get('error', 'Unknown error'),
                           trace_id=sr['trace_id'], parent_id=soundings_trace.id,
                           node_type="sounding_error", depth=self.depth,
                           candidate_index=i, is_winner=False,
                           metadata={"cell_name": "_orchestration", "error": sr.get('error'), "cascade_sounding": True})
            else:
                self.echo.add_history({
                    "role": "cascade_sounding_attempt",
                    "content": str(sr['result'])[:150] if sr['result'] else "Completed",
                    "node_type": "cascade_sounding_attempt"
                }, trace_id=sr['trace_id'], parent_id=soundings_trace.id, node_type="cascade_sounding_attempt",
                   metadata={
                       "cascade_id": self.config.cascade_id,
                       "cell_name": "_orchestration",
                       "candidate_index": i,
                       "sub_session_id": sr['session_id'],
                       "is_winner": False,  # Updated later when winner is selected
                       "result_preview": str(sr['result'])[:200],
                       "semantic_actor": "sounding_agent",
                       "semantic_purpose": "generation"
                   })

        # Now evaluate all soundings
        console.print(f"{indent}[bold yellow]⚖️  Evaluating {len(sounding_results)} cascade executions...[/bold yellow]")

        # Create evaluator trace
        evaluator_trace = soundings_trace.create_child("evaluator", "cascade_evaluation")

        # Build evaluation prompt
        eval_prompt = f"{self.config.candidates.evaluator_instructions}\n\n"
        eval_prompt += "Please evaluate the following complete cascade executions and select the best one.\n\n"

        for i, candidate in enumerate(sounding_results):
            eval_prompt += f"## Cascade Execution {i+1}\n"
            eval_prompt += f"Result: {candidate['result']}\n\n"

        eval_prompt += f"\nRespond with ONLY the number of the best execution (1-{len(sounding_results)}) and a brief explanation."

        # Create evaluator agent
        evaluator_agent = Agent(
            model=self.model,
            system_prompt="You are an expert evaluator. Your job is to compare multiple complete cascade executions and select the best one.",
            tools=[],
            base_url=self.base_url,
            api_key=self.api_key
        )

        # Run evaluation
        eval_response = evaluator_agent.run(eval_prompt, context_messages=[])
        eval_content = eval_response.get("content", "")

        console.print(f"{indent}  [bold magenta]Cascade Evaluator:[/bold magenta] {eval_content[:200]}...")

        # Log evaluator LLM call with cost data (this ensures parent session has costs)
        from .unified_logs import log_unified
        eval_model = eval_response.get("model", self.model)
        eval_cost = eval_response.get("cost")
        eval_tokens_in = eval_response.get("tokens_in", 0)
        eval_tokens_out = eval_response.get("tokens_out", 0)
        eval_request_id = eval_response.get("id")
        eval_provider = eval_response.get("provider", "unknown")
        eval_full_request = eval_response.get("full_request")
        eval_full_response = eval_response.get("full_response")

        # Extract reasoning token data (OpenRouter extended thinking)
        eval_reasoning_enabled = eval_response.get("reasoning_enabled")
        eval_reasoning_effort = eval_response.get("reasoning_effort")
        eval_reasoning_max_tokens = eval_response.get("reasoning_max_tokens")
        eval_tokens_reasoning = eval_response.get("tokens_reasoning")

        log_unified(
            session_id=self.session_id,
            parent_session_id=getattr(self, 'parent_session_id', None),
            trace_id=evaluator_trace.id,
            parent_id=soundings_trace.id,
            node_type="cascade_evaluator",
            role="assistant",
            depth=self.depth,
            cascade_id=self.config.cascade_id,
            cell_name="_orchestration",
            model=eval_model,
            request_id=eval_request_id,
            provider=eval_provider,
            tokens_in=eval_tokens_in,
            tokens_out=eval_tokens_out,
            cost=eval_cost,
            reasoning_enabled=eval_reasoning_enabled,
            reasoning_effort=eval_reasoning_effort,
            reasoning_max_tokens=eval_reasoning_max_tokens,
            tokens_reasoning=eval_tokens_reasoning,
            content=eval_content,
            full_request=eval_full_request,
            full_response=eval_full_response,
            metadata={
                "factor": factor,
                "semantic_actor": "evaluator",
                "semantic_purpose": "evaluation_output"
            }
        )

        # Also add to echo history for visualization (skip unified log since we just logged above)
        self.echo.add_history({
            "role": "cascade_evaluator",
            "content": eval_content if eval_content else "Evaluating...",
            "node_type": "cascade_evaluator"
        }, trace_id=evaluator_trace.id, parent_id=soundings_trace.id, node_type="cascade_evaluator",
           metadata=self._get_metadata({
               "cascade_id": self.config.cascade_id,
               "cell_name": "_orchestration",
               "factor": factor,
               "model": eval_model
           }, semantic_actor="evaluator", semantic_purpose="evaluation_output"),
           skip_unified_log=True)

        # Extract winner index from evaluation
        winner_index = 0
        import re
        match = re.search(r'\b([1-9]\d*)\b', eval_content)
        if match:
            winner_index = int(match.group(1)) - 1  # Convert to 0-indexed
            if winner_index >= len(sounding_results):
                winner_index = 0

        winner = sounding_results[winner_index]

        console.print(f"{indent}[bold green]🏆 Winner: Cascade Sounding {winner_index + 1}[/bold green]")

        # Merge winner's echo into our main echo (this becomes the "canon" result)
        if winner['echo']:
            # Copy winner's state, history, and lineage into main echo
            self.echo.state.update(winner['echo'].state)
            self.echo.history.extend(winner['echo'].history)
            self.echo.lineage.extend(winner['echo'].lineage)

            # IMPORTANT: Re-log winner's phases to parent session so parent shows data
            # The winner's data lives in the child session, but we need the parent to show phases too
            # This allows backend queries (which filter by cell_name IS NOT NULL) to find parent's data
            for lineage_item in winner['echo'].lineage:
                cell_name = lineage_item.get('phase')
                output_content = lineage_item.get('output', '')

                # Log phase completion to parent session
                self.echo.add_history({
                    "role": "phase_result",
                    "content": f"Phase {cell_name} completed (from candidate #{winner_index})",
                    "node_type": "phase_result"
                }, trace_id=soundings_trace.id, parent_id=self.trace.id, node_type="phase_result",
                   metadata={
                       "cascade_id": self.config.cascade_id,
                       "cell_name": cell_name,
                       "source_sounding": winner_index,
                       "output_preview": str(output_content)[:200] if output_content else "",
                       "semantic_actor": "framework",
                       "semantic_purpose": "lifecycle"
                   })

        # Add soundings result to history (auto-logs via unified_logs)
        self.echo.add_history({
            "role": "cascade_soundings_result",
            "content": f"🏆 Winner: Cascade #{winner_index + 1}",
            "node_type": "cascade_soundings_result"
        }, trace_id=soundings_trace.id, parent_id=self.trace.id, node_type="cascade_soundings_result",
           metadata={
               "cascade_id": self.config.cascade_id,
               "cell_name": "_orchestration",  # Ensure UI can query this
               "winner_index": winner_index,
               "winner_session_id": f"{self.session_id}_sounding_{winner_index}",
               "factor": factor,
               "evaluation": eval_content,  # Full content, no truncation
               "winner_trace_id": winner['trace_id'],
               "candidate_index": winner_index,
               "is_winner": True,
               "semantic_actor": "framework",
               "semantic_purpose": "lifecycle"
           })

        self._update_graph()

        # Check if reforge is configured for cascade soundings
        if self.config.candidates.reforge:
            # Track which candidate won so reforge messages can reference it
            self.current_winning_candidate_index = winner_index

            winner = self._reforge_cascade_winner(
                winner=winner,
                input_data=input_data,
                trace=soundings_trace,
                reforge_step=0  # Initial soundings = step 0
            )

            # Reset after reforge completes
            self.current_winning_candidate_index = None

        return winner['full_result']

    def _reforge_cascade_winner(self, winner: dict, input_data: dict, trace: TraceNode, reforge_step: int) -> dict:
        """
        Reforge (refine) the winning cascade execution through iterative soundings.
        Each step runs complete cascade executions with honing prompt to progressively improve quality.
        """
        indent = "  " * self.depth
        reforge_config = self.config.candidates.reforge
        current_output = winner['result']

        # Build refinement context from original cascade config
        original_cascade_description = self.config.description or self.config.cascade_id

        for step in range(1, reforge_config.steps + 1):
            # Set current reforge step for metadata tagging
            self.current_reforge_step = step

            console.print(f"{indent}[bold cyan]🔨 CASCADE Reforge Step {step}/{reforge_config.steps}[/bold cyan]")

            # Create reforge trace
            reforge_trace = trace.create_child("cascade_reforge", f"reforge_step_{step}")

            # Build refinement instructions for cascades
            refinement_context = f"""Original cascade goal: {original_cascade_description}

Current best output: {current_output}

Refinement directive: {reforge_config.honing_prompt}
"""

            # Apply mutation if configured
            if reforge_config.mutate:
                mutation_prompt = self._get_mutation_prompt(step - 1)
                refinement_context += f"\n\nVariation strategy: {mutation_prompt}"
                console.print(f"{indent}  [yellow]🧬 Mutation applied: {mutation_prompt[:60]}...[/yellow]")

            # Log reforge start
            log_message(self.session_id, "cascade_reforge_start",
                       f"Cascade reforge step {step} with factor {reforge_config.factor_per_step}",
                       {"honing_prompt": reforge_config.honing_prompt},
                       trace_id=reforge_trace.id, parent_id=trace.id,
                       node_type="cascade_reforge", depth=self.depth, reforge_step=step)

            # Run mini-soundings for this reforge step (complete cascade executions) - IN PARALLEL
            from concurrent.futures import ThreadPoolExecutor, as_completed

            factor_per_step = reforge_config.factor_per_step
            max_parallel = self.config.candidates.max_parallel or 3
            max_workers = min(factor_per_step, max_parallel)

            console.print(f"{indent}    [cyan]Running {factor_per_step} cascade refinements (Parallel: {max_workers} workers)[/cyan]")

            # Pre-create traces for all refinement attempts (must be sequential for proper hierarchy)
            refinement_traces = []
            for i in range(factor_per_step):
                trace = reforge_trace.create_child("cascade_refinement_attempt", f"attempt_{i+1}")
                refinement_traces.append(trace)

            # Define worker function for parallel refinement execution
            def run_single_refinement(i: int) -> dict:
                """Execute a single cascade refinement. Returns result dict."""
                from .echo import Echo

                refinement_trace = refinement_traces[i]
                refinement_session_id = f"{self.session_id}_reforge{step}_{i}"
                refinement_echo = Echo(refinement_session_id, parent_session_id=self.session_id)

                console.print(f"{indent}      [cyan]🔨 Cascade Refinement {i+1}/{factor_per_step} starting...[/cyan]")

                try:
                    # Create a new runner for this refinement
                    # We'll inject the refinement context as additional input
                    refinement_input = input_data.copy() if input_data else {}
                    refinement_input['_refinement_context'] = refinement_context

                    refinement_runner = RVBBITRunner(
                        config_path=self.config_path,
                        session_id=refinement_session_id,
                        overrides=self.overrides,
                        depth=self.depth,
                        parent_trace=refinement_trace,
                        hooks=self.hooks,
                        parent_session_id=self.session_id  # Link child to parent session
                    )

                    # Run the cascade
                    result = refinement_runner._run_cascade_internal(refinement_input)

                    # Extract final result
                    final_output = result.get("final_output", str(result))

                    console.print(f"{indent}      [green]✓ Cascade Refinement {i+1} complete[/green]")

                    return {
                        "index": i,
                        "result": final_output,
                        "echo": refinement_echo,
                        "trace_id": refinement_trace.id,
                        "full_result": result
                    }

                except Exception as e:
                    console.print(f"{indent}      [red]✗ Cascade Refinement {i+1} failed: {e}[/red]")
                    return {
                        "index": i,
                        "result": f"[ERROR: {str(e)}]",
                        "echo": None,
                        "trace_id": refinement_trace.id,
                        "full_result": {},
                        "failed": True,
                        "error": str(e)
                    }

            # Execute refinements in parallel
            reforge_results = []
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(run_single_refinement, i): i for i in range(factor_per_step)}

                for future in as_completed(futures):
                    result = future.result()
                    reforge_results.append(result)

            # Sort results by index to maintain consistent ordering
            reforge_results.sort(key=lambda x: x['index'])

            # Log errors sequentially after parallel completion
            for rr in reforge_results:
                if rr.get('failed'):
                    log_message(self.session_id, "cascade_refinement_error", rr.get('error', 'Unknown error'),
                               trace_id=rr['trace_id'], parent_id=reforge_trace.id,
                               node_type="error", depth=self.depth, reforge_step=step)

            # Evaluate refinements
            console.print(f"{indent}    [bold yellow]⚖️  Evaluating cascade refinements...[/bold yellow]")

            evaluator_trace = reforge_trace.create_child("evaluator", "cascade_reforge_evaluation")

            # Use custom evaluator or default
            eval_instructions = reforge_config.evaluator_override or self.config.candidates.evaluator_instructions

            eval_prompt = f"{eval_instructions}\n\n"
            eval_prompt += "Please evaluate the following refined cascade executions and select the best one.\n\n"

            for i, refinement in enumerate(reforge_results):
                eval_prompt += f"## Refinement {i+1}\n"
                eval_prompt += f"Result: {refinement['result']}\n\n"

            eval_prompt += f"\nRespond with ONLY the number of the best refinement (1-{len(reforge_results)}) and a brief explanation."

            evaluator_agent = Agent(
                model=self.model,
                system_prompt="You are an expert evaluator. Your job is to select the best refined cascade execution.",
                tools=[],
                base_url=self.base_url,
                api_key=self.api_key
            )

            eval_response = evaluator_agent.run(eval_prompt, context_messages=[])
            eval_content = eval_response.get("content", "")

            console.print(f"{indent}    [bold magenta]Evaluator:[/bold magenta] {eval_content[:150]}...")

            # Log with cost data from the evaluator LLM call
            eval_model = eval_response.get("model", self.model)
            eval_cost = eval_response.get("cost")
            eval_tokens_in = eval_response.get("tokens_in", 0)
            eval_tokens_out = eval_response.get("tokens_out", 0)
            eval_request_id = eval_response.get("id")

            log_message(self.session_id, "cascade_reforge_evaluation", eval_content,
                       trace_id=evaluator_trace.id, parent_id=reforge_trace.id,
                       node_type="reforge_evaluator", depth=self.depth, reforge_step=step,
                       model=eval_model, cost=eval_cost, tokens_in=eval_tokens_in,
                       tokens_out=eval_tokens_out, request_id=eval_request_id,
                       cascade_id=self.config.cascade_id, cell_name="_orchestration")

            # Extract winner
            import re
            winner_index = 0
            match = re.search(r'\b([1-9]\d*)\b', eval_content)
            if match:
                winner_index = int(match.group(1)) - 1
                if winner_index >= len(reforge_results):
                    winner_index = 0

            refined_winner = reforge_results[winner_index]

            console.print(f"{indent}    [bold green]🏆 Best Cascade Refinement: #{winner_index + 1}[/bold green]")

            log_message(self.session_id, "cascade_reforge_winner", f"Selected cascade refinement {winner_index + 1}",
                       {"winner_trace_id": refined_winner['trace_id'], "evaluation": eval_content},
                       trace_id=reforge_trace.id, parent_id=trace.id, node_type="cascade_reforge_winner",
                       depth=self.depth, reforge_step=step, is_winner=True)

            # Check threshold ward if configured
            if reforge_config.threshold:
                console.print(f"{indent}    [cyan]🛡️  Checking cascade reforge threshold...[/cyan]")

                threshold_result = self._run_ward(
                    reforge_config.threshold,
                    str(refined_winner['result']),
                    reforge_trace,
                    ward_type="cascade_threshold"
                )

                if threshold_result['valid']:
                    console.print(f"{indent}    [bold green]✨ Cascade threshold met! Stopping reforge early at step {step}[/bold green]")
                    log_message(self.session_id, "cascade_reforge_threshold_met",
                               f"Threshold satisfied at step {step}/{reforge_config.steps}",
                               {"reason": threshold_result['reason']},
                               trace_id=reforge_trace.id, parent_id=trace.id,
                               node_type="threshold", depth=self.depth, reforge_step=step)

                    # Update winner and break early
                    winner = refined_winner
                    current_output = refined_winner['result']
                    break

            # Update current output for next iteration
            current_output = refined_winner['result']
            winner = refined_winner

        # Reset candidate index and reforge step after cascade reforge completes
        self.current_phase_candidate_index = None
        self.current_reforge_step = None

        # Merge final winner's echo into main echo
        if winner['echo']:
            self.echo.state.update(winner['echo'].state)
            self.echo.history.extend(winner['echo'].history)
            self.echo.lineage.extend(winner['echo'].lineage)

        console.print(f"{indent}[bold green]🔨 CASCADE Reforge Complete[/bold green]")

        return winner

    def _run_cascade_internal(self, input_data: dict = None) -> dict:
        """Internal cascade execution (separated to allow soundings wrapper)."""
        # Set context for tools
        session_context_token = set_current_session_id(self.session_id)
        cascade_context_token = set_current_cascade_id(self.config.cascade_id)
        trace_context_token = set_current_trace(self.trace)

        # Set research database context if configured
        if self.config.research_db:
            set_current_research_db(self.config.research_db)

        # Set visualization context
        self.echo.set_cascade_context(self.config.cascade_id)

        update_session_state(self.session_id, self.config.cascade_id, "running", "init", self.depth)

        if self.depth > self.max_depth:
            log_message(self.session_id, "error", "Max recursion depth reached.",
                       trace_id=self.trace.id, parent_id=self.trace.parent_id, node_type="error", depth=self.depth,
                       candidate_index=self.candidate_index)
            console.print("[bold red]Max recursion depth reached.[/bold red]")
            update_session_state(self.session_id, self.config.cascade_id, "error", "max_depth", self.depth)
            return self.echo.get_full_echo()

        self.echo.update_state("input", input_data)
        self._update_graph() # Initial graph

        style = "bold blue" if self.depth == 0 else "bold cyan"
        indent = "  " * self.depth
        console.print(f"{indent}[{style}]🌊 Starting Cascade: {self.config.cascade_id} (Depth {self.depth})[/{style}]\n")

        # Hook: Cascade Start
        self.hooks.on_cascade_start(self.config.cascade_id, self.session_id, {
            "depth": self.depth,
            "input": input_data,
            "parent_session_id": getattr(self, 'parent_session_id', None),
            "candidate_index": self.candidate_index,
        })

        log_message(self.session_id, "system", f"Starting cascade {self.config.cascade_id}", input_data,
                   trace_id=self.trace.id, parent_id=self.trace.parent_id, node_type="cascade", depth=self.depth,
                   candidate_index=self.candidate_index, parent_session_id=self.parent_session_id,
                   caller_id=self.caller_id, invocation_metadata=self.invocation_metadata,
                   genus_hash=getattr(self, 'genus_hash', None))

        # Add structure to Echo for visualization
        self.echo.add_history({
            "role": "structure",
            "content": f"Cascade: {self.config.cascade_id}",
            "node_type": "cascade"
        }, trace_id=self.trace.id, parent_id=self.trace.parent_id, node_type="cascade",
           metadata={"cascade_id": self.config.cascade_id, "depth": self.depth,
                     "semantic_actor": "framework", "semantic_purpose": "lifecycle"})
        self._update_graph()

        # Check if we can run phases in parallel (multiple independent phases)
        if self._can_run_phases_parallel():
            # Use parallel execution for independent phases
            result = self._execute_phases_parallel(input_data)

            # Update session state
            final_status = "failed" if result.get("has_errors") else "completed"
            update_session_state(self.session_id, self.config.cascade_id, final_status, "end", self.depth)

            # Hooks
            if result.get("has_errors"):
                cascade_error = Exception(f"Cascade completed with {len(result['errors'])} error(s)")
                self.hooks.on_cascade_error(self.config.cascade_id, self.session_id, cascade_error)
            self.hooks.on_cascade_complete(self.config.cascade_id, self.session_id, result)

            # Publish event
            self._publish_event("cascade_complete", {
                "cascade_id": self.config.cascade_id,
                "status": final_status,
                "parallel_execution": True,
            })

            return result

        # Sequential execution (original behavior)
        current_cell_name = self.config.cells[0].name
        chosen_next_phase = None # For dynamic handoff


        # Simple state machine for phases
        while current_cell_name and current_cell_name != chosen_next_phase: # Also check against chosen_next_phase
            cell = next((p for p in self.config.cells if p.name == current_cell_name), None)
            if not cell:
                break

            # Check for cancellation request before starting cell
            if self._check_cancellation():
                console.print(f"[bold yellow]⚠ Cascade cancelled before cell '{cell.name}'[/bold yellow]")
                break

            update_session_state(self.session_id, self.config.cascade_id, "running", cell.name, self.depth)

            # Update ClickHouse session state with current cell
            try:
                update_session_status(self.session_id, SessionStatus.RUNNING, current_cell=cell.name)
            except Exception:
                pass  # Don't fail cascade if ClickHouse update fails

            # Set cell context for visualization metadata
            self.echo.set_cell_context(cell.name)

            # Hook: Phase Start
            hook_result = self.hooks.on_phase_start(cell.name, {
                "echo": self.echo,
                "input": input_data,
                "candidate_index": self.current_phase_candidate_index or self.candidate_index,
            })

            # Phase Trace
            phase_trace = self.trace.create_child("cell", cell.name)

            # Log Phase Structure with rich metadata
            phase_meta = {
                "cell_name": cell.name,
                "has_soundings": cell.candidates is not None and (isinstance(cell.candidates.factor, str) or cell.candidates.factor > 1),
                "has_wards": cell.wards is not None,
                "has_sub_cascades": len(cell.sub_cascades) > 0 if cell.sub_cascades else False,
                "handoffs": [h.target if hasattr(h, 'target') else h for h in cell.handoffs] if cell.handoffs else []
            }
            phase_meta["semantic_actor"] = "framework"
            phase_meta["semantic_purpose"] = "lifecycle"
            self.echo.add_history({
                "role": "structure",
                "content": f"Phase: {cell.name}",
                "node_type": "cell"
            }, trace_id=phase_trace.id, parent_id=phase_trace.parent_id, node_type="cell",
               metadata=phase_meta)

            import time as time_module
            phase_start_time = time_module.time()
            output_or_next_phase = self.execute_phase(cell, input_data, phase_trace, initial_injection=hook_result)
            phase_duration_ms = (time_module.time() - phase_start_time) * 1000

            # Check if cell was blocked by a ward
            phase_was_blocked = isinstance(output_or_next_phase, str) and output_or_next_phase.startswith("[BLOCKED by")

            if phase_was_blocked:
                # Phase failed due to ward blocking - log as error and abort cascade
                console.print(f"{indent}[bold red]⛔ Cascade aborted: {output_or_next_phase}[/bold red]")
                log_message(self.session_id, "phase_error", f"Phase {cell.name} blocked",
                           trace_id=phase_trace.id, parent_id=phase_trace.parent_id, node_type="phase_error",
                           depth=self.depth, cell_name=cell.name, cascade_id=self.config.cascade_id,
                           parent_session_id=self.parent_session_id,
                           metadata={"error": output_or_next_phase, "blocked": True})

                # Add to echo errors
                self.echo.add_error(cell.name, "ward_blocked", output_or_next_phase)

                # Hook: Phase Error
                self.hooks.on_phase_error(cell.name, self.session_id, Exception(output_or_next_phase))

                # Abort cascade - break out of cell loop
                break

            # Log cell completion for UI visibility
            log_message(self.session_id, "phase_complete", f"Phase {cell.name} completed",
                       trace_id=phase_trace.id, parent_id=phase_trace.parent_id, node_type="cell",
                       depth=self.depth, cell_name=cell.name, cascade_id=self.config.cascade_id,
                       parent_session_id=self.parent_session_id)

            # Hook: Phase Complete
            # Skip if this was an image generation cell (it already called hooks.on_phase_complete)
            phase_model = cell.model or self.model
            if not Agent.is_image_generation_model(phase_model):
                self.hooks.on_phase_complete(cell.name, self.session_id, {
                    "output": output_or_next_phase,
                    "duration_ms": phase_duration_ms,
                })

            if isinstance(output_or_next_phase, str) and output_or_next_phase in [h.target if isinstance(h, HandoffConfig) else h for h in cell.handoffs]:
                chosen_next_phase = output_or_next_phase # Dynamic handoff chosen by agent
                self.echo.add_lineage(cell.name, f"Dynamically routed to: {chosen_next_phase}", trace_id=phase_trace.id)
            else:
                self.echo.add_lineage(cell.name, output_or_next_phase, trace_id=phase_trace.id)

            # Store cell output in state for access by subsequent phases via {{ state.output_<cell_name> }}
            # Note: Deterministic phases already do this in _execute_deterministic_phase
            if not cell.is_deterministic():
                self.echo.state[f"output_{cell.name}"] = output_or_next_phase

            self._update_graph() # After cell

            if chosen_next_phase: # If agent decided next cell
                current_cell_name = chosen_next_phase
                chosen_next_phase = None # Reset for next cell's routing
            elif cell.handoffs: # Else, follow explicit handoffs if exist
                # Default to first handoff, or dynamically chosen
                next_handoff_target = cell.handoffs[0].target if isinstance(cell.handoffs[0], HandoffConfig) else cell.handoffs[0]
                current_cell_name = next_handoff_target
            else:
                # No handoffs - check if there's a next cell in definition order
                # This enables simple linear cascades without explicit handoffs
                cell_names = [p.name for p in self.config.cells]
                try:
                    current_idx = cell_names.index(cell.name)
                    if current_idx + 1 < len(cell_names):
                        current_cell_name = cell_names[current_idx + 1]
                    else:
                        current_cell_name = None  # Last phase, cascade ends
                except ValueError:
                    current_cell_name = None

        # Get final result with error status
        result = self.echo.get_full_echo()

        # Update session state based on whether errors occurred
        final_status = "failed" if result.get("has_errors") else "completed"
        update_session_state(self.session_id, self.config.cascade_id, final_status, "end", self.depth)

        # Hook: Cascade Complete (called for both success and error cases)
        # The hook can check result["status"] to distinguish
        if result.get("has_errors"):
            # Also call error hook if errors occurred
            cascade_error = Exception(f"Cascade completed with {len(result['errors'])} error(s)")
            self.hooks.on_cascade_error(self.config.cascade_id, self.session_id, cascade_error)

        self.hooks.on_cascade_complete(self.config.cascade_id, self.session_id, result)

        # Publish cascade_complete event (for narrator and other subscribers)
        self._publish_event("cascade_complete", {
            "cascade_id": self.config.cascade_id,
            "status": final_status,
            "final_output": str(result.get("final_output", ""))[:500] if result else None,
            "error_count": len(result.get("errors", [])) if result else 0,
        })

        # Log cascade completion with status
        log_message(self.session_id, "system", f"Cascade {final_status}: {self.config.cascade_id}",
                   metadata={"status": final_status, "error_count": len(result.get("errors", []))},
                   node_type=f"cascade_{final_status}", parent_session_id=self.parent_session_id,
                   genus_hash=getattr(self, 'genus_hash', None))

        return result

    def run(self, input_data: dict = None) -> dict:
        """
        Main entry point for cascade execution.
        Checks if cascade-level soundings are configured and delegates appropriately.

        Manages durable execution via:
        - Session state creation in ClickHouse
        - Heartbeat thread for zombie detection
        - Status updates on completion/error
        """
        # Create session state in ClickHouse for durable tracking
        try:
            # Determine execution source
            execution_source = "cli"  # Default
            if self.depth > 0:
                execution_source = "sub_cascade"

            create_session_state(
                session_id=self.session_id,
                cascade_id=self.config.cascade_id,
                parent_session_id=self.parent_session_id,
                depth=self.depth,
                metadata={
                    "config_path": str(self.config_path) if isinstance(self.config_path, str) else "inline",
                    "execution_source": execution_source
                }
            )
        except Exception as e:
            # Don't fail cascade if session state creation fails (backward compat)
            logger = logging.getLogger(__name__)
            logger.debug(f"Could not create session state: {e}")

        # Save cascade definition and inputs for perfect replay
        try:
            from .db_adapter import get_db
            from datetime import datetime
            import yaml
            import json
            import sys

            db = get_db()

            # Read original cascade file contents (preserve YAML/JSON as-is)
            if isinstance(self.config_path, str):
                # It's a file path - read raw contents
                with open(self.config_path, 'r') as f:
                    cascade_def_raw = f.read()
            else:
                # It's an inline dict - dump to YAML (preserves all data)
                cascade_def_raw = yaml.dump(self.config_path, default_flow_style=False, sort_keys=False)

            # Serialize input data to JSON (small, simple data structure)
            input_json = json.dumps(input_data if input_data else {}, indent=2)

            # Get config path (ClickHouse String type doesn't support None)
            config_path_str = str(self.config_path) if isinstance(self.config_path, str) else ''

            # Insert into cascade_sessions table using insert_rows method
            db.insert_rows(
                'cascade_sessions',
                [{
                    'session_id': self.session_id,
                    'cascade_id': self.config.cascade_id,
                    'cascade_definition': cascade_def_raw,  # Store raw YAML/JSON, not parsed/re-serialized
                    'input_data': input_json,
                    'config_path': config_path_str,
                    'created_at': datetime.now(),
                    'parent_session_id': self.parent_session_id or '',  # ClickHouse doesn't support None for String type
                    'depth': self.depth,
                    'caller_id': self.caller_id or '',
                    'invocation_metadata_json': json.dumps(self.invocation_metadata) if self.invocation_metadata else '{}'
                }],
                columns=['session_id', 'cascade_id', 'cascade_definition', 'input_data', 'config_path', 'created_at', 'parent_session_id', 'depth', 'caller_id', 'invocation_metadata_json']
            )
        except Exception as e:
            # Don't fail cascade if cascade_sessions save fails (table might not exist yet)
            logger = logging.getLogger(__name__)
            logger.debug(f"Could not save cascade definition to cascade_sessions: {e}")

        # Compute cascade-level genus_hash for analytics and trending
        try:
            from .utils import compute_genus_hash
            from .db_adapter import get_db

            # Build cascade config for hashing
            cascade_config_for_hash = {
                'cascade_id': self.config.cascade_id,
                'cells': [cell.dict() if hasattr(cell, 'dict') else cell for cell in self.config.cells] if self.config.cells else [],
            }

            # Compute genus_hash (cascade invocation identity)
            genus_hash = compute_genus_hash(cascade_config_for_hash, input_data)

            # Update cascade_sessions with genus_hash
            db = get_db()
            db.update_row(
                'cascade_sessions',
                {'genus_hash': genus_hash},
                f"session_id = '{self.session_id}'",
                sync=False
            )

            # Store in both runner instance AND Echo for auto-injection into ALL logs
            self.genus_hash = genus_hash
            self.echo.genus_hash = genus_hash

        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.debug(f"Could not compute genus_hash: {e}")
            self.genus_hash = None
            self.echo.genus_hash = None

        # Set hooks context for tools (allows checkpoint callbacks)
        set_current_hooks(self.hooks)

        # Start heartbeat thread
        self._start_heartbeat()

        # Start narrator service if configured (only at depth 0 to avoid nested narrators)
        if self.cascade_narrator and self.cascade_narrator.enabled and self.depth == 0:
            self._start_narrator_service(input_data)

        try:
            # Update status to running
            try:
                update_session_status(self.session_id, SessionStatus.RUNNING)
            except Exception:
                pass  # Don't fail if status update fails

            # Check if cascade has soundings configured
            if self.config.candidates and (isinstance(self.config.candidates.factor, str) or self.config.candidates.factor > 1):
                result = self._run_with_cascade_soundings(input_data)
            else:
                # Normal execution (no cascade soundings)
                result = self._run_cascade_internal(input_data)

            # Update final status in ClickHouse
            try:
                final_status = SessionStatus.ERROR if result.get("has_errors") else SessionStatus.COMPLETED
                update_session_status(
                    self.session_id,
                    final_status,
                    error_message=str(result.get("errors", [])[:1]) if result.get("has_errors") else None
                )
            except Exception:
                pass  # Don't fail if status update fails

            # Save final output to cascade_sessions for Console UI
            try:
                from .db_adapter import get_db
                import json

                db = get_db()

                # Extract final output from cascade execution
                final_output = None

                # Strategy 1: Try to get from lineage (most reliable for all cell types)
                if result and result.get("lineage") and len(result["lineage"]) > 0:
                    # Get last lineage entry
                    lineage_entry = result["lineage"][-1]

                    # Lineage contains the actual output in the 'output' field
                    if isinstance(lineage_entry, dict) and "output" in lineage_entry:
                        final_output = lineage_entry["output"]

                # Strategy 2: Fallback to history for LLM cells with text responses
                if final_output is None and result and result.get("history"):
                    history = result["history"]

                    # Iterate in reverse to find last message with actual content
                    for message in reversed(history):
                        # Skip system and phase_complete messages (no real content)
                        msg_role = message.get("role", "")
                        if msg_role in ["system", "phase_complete", "structure"]:
                            continue

                        # Get content_json from this message (preferred)
                        content_json = message.get("content_json")
                        if content_json:
                            final_output = content_json
                            break

                        # Fallback to 'content' field if content_json not available
                        content = message.get("content")
                        if content and not content.startswith("Phase:") and not content.startswith("Cascade:"):
                            final_output = content
                            break

                # Serialize output for storage (preserve format as-is)
                if final_output is not None:
                    # Handle different output types
                    if isinstance(final_output, str):
                        output_str = final_output
                    elif isinstance(final_output, (dict, list)):
                        output_str = json.dumps(final_output, ensure_ascii=False)
                    else:
                        output_str = str(final_output)

                    # Update cascade_sessions with full output (NO truncation)
                    # Use db.update_row() which properly handles ClickHouse ALTER UPDATE syntax
                    db.update_row(
                        'cascade_sessions',
                        {'output': output_str},
                        f"session_id = '{self.session_id}'",
                        sync=False  # Don't wait for mutation (faster, non-blocking)
                    )

            except Exception as e:
                # Don't fail cascade if output save fails
                logger = logging.getLogger(__name__)
                logger.debug(f"Could not save output to cascade_sessions: {e}")

            # Trigger analytics worker (async, non-blocking)
            # Pre-computes context-aware insights, Z-scores, and anomaly detection
            try:
                from .analytics_worker import analyze_cascade_execution
                import threading

                def run_analytics():
                    try:
                        analyze_cascade_execution(self.session_id)
                    except Exception as e:
                        logger = logging.getLogger(__name__)
                        logger.debug(f"Analytics worker failed: {e}")

                # Run in background thread (don't block cascade completion)
                analytics_thread = threading.Thread(target=run_analytics, daemon=True)
                analytics_thread.start()

            except Exception:
                pass  # Analytics is optional, never fail cascade

            # For cascade soundings, emit cascade_complete event here since
            # _run_with_cascade_soundings doesn't call _run_cascade_internal for the parent
            if self.config.candidates and (isinstance(self.config.candidates.factor, str) or self.config.candidates.factor > 1):
                final_status_str = "error" if result.get("has_errors") else "completed"

                # Hook: Cascade Complete
                if result.get("has_errors"):
                    cascade_error = Exception(f"Cascade completed with {len(result.get('errors', []))} error(s)")
                    self.hooks.on_cascade_error(self.config.cascade_id, self.session_id, cascade_error)
                self.hooks.on_cascade_complete(self.config.cascade_id, self.session_id, result)

                # Publish cascade_complete event (for narrator, UI, and other subscribers)
                self._publish_event("cascade_complete", {
                    "cascade_id": self.config.cascade_id,
                    "status": final_status_str,
                    "final_output": str(result.get("final_output", ""))[:500] if result else None,
                    "error_count": len(result.get("errors", [])) if result else 0,
                })

                # Log cascade completion with status
                log_message(self.session_id, "system", f"Cascade {final_status_str}: {self.config.cascade_id}",
                           metadata={"status": final_status_str, "error_count": len(result.get("errors", []))},
                           node_type=f"cascade_{final_status_str}", parent_session_id=self.parent_session_id,
                           genus_hash=getattr(self, 'genus_hash', None))

            return result

        except Exception as e:
            # Log cascade-level error to unified logs
            from .unified_logs import log_unified
            import traceback

            error_type = type(e).__name__
            error_msg = str(e)
            # Use enhanced message if available (from agent.py error extraction)
            enhanced_msg = getattr(e, 'enhanced_message', None)
            display_msg = enhanced_msg or error_msg
            error_tb = traceback.format_exc()

            # Log to unified logs with cascade context
            log_unified(
                session_id=self.session_id,
                trace_id=self.trace.id if self.trace else None,
                parent_id=self.trace.parent_id if self.trace else None,
                parent_session_id=self.parent_session_id,
                node_type="cascade_error",
                role="error",
                depth=self.depth,
                cascade_id=self.config.cascade_id,
                cascade_config=self.config.dict() if hasattr(self.config, 'dict') else None,
                content=f"{error_type}: {display_msg}\n\nTraceback:\n{error_tb}",
                metadata={
                    "error_type": error_type,
                    "error_message": display_msg,
                    "cascade_id": self.config.cascade_id,
                    "depth": self.depth,
                }
            )

            # Add to echo for error tracking
            if hasattr(self, 'echo'):
                self.echo.add_error(
                    cell="cascade",
                    error_type=error_type,
                    error_message=display_msg
                )

            # Update status to error
            try:
                update_session_status(
                    self.session_id,
                    SessionStatus.ERROR,
                    error_message=str(e)[:500]
                )
            except Exception:
                pass

            # Hook: Cascade Error
            self.hooks.on_cascade_error(self.config.cascade_id, self.session_id, e)
            raise

        finally:
            # Always stop heartbeat thread
            self._stop_heartbeat()
            # Stop narrator service if running
            self._stop_narrator_service()
            # Close session DuckDB connection (but keep file for replay/debugging)
            # The Studio UI can explicitly cleanup via /api/studio/cleanup-session
            # Or files can be cleaned up via TTL/manual cleanup
            try:
                from .sql_tools.session_db import cleanup_session_db
                cleanup_session_db(self.session_id, delete_file=False)  # Keep file for temp table access
            except Exception:
                pass  # Don't fail cascade if cleanup fails

            # Terminate bash session (cleanup persistent bash process)
            try:
                from .traits.bash_session import cleanup_bash_session
                cleanup_bash_session(self.session_id)
            except Exception:
                pass  # Don't fail cascade if cleanup fails

    def _run_quartermaster(self, phase: CellConfig, input_data: dict, trace: TraceNode, phase_model: str = None) -> list[str]:
        """
        Run the Quartermaster agent to select appropriate tackle for this phase.

        Returns list of tool names to make available.
        """
        from .traits_manifest import get_trait_manifest, format_manifest_for_quartermaster

        indent = "  " * self.depth

        # Create quartermaster trace
        qm_trace = trace.create_child("quartermaster", "manifest_selection")

        # Get full tackle manifest
        manifest = get_trait_manifest()

        # Semantic pre-filtering: Use vector search to reduce manifest size
        filtered_manifest = manifest
        used_semantic_filtering = False

        if len(manifest) > phase.manifest_limit:
            try:
                from .db_adapter import get_db
                from .rag.indexer import embed_texts
                from .config import get_config

                config = get_config()
                db = get_db()

                # Embed phase instructions for semantic matching
                console.print(f"{indent}  [dim cyan]🔍 Semantic pre-filtering ({len(manifest)} → {phase.manifest_limit} tools)...[/dim cyan]")

                embed_result = embed_texts(
                    texts=[phase.instructions],
                    model=config.default_embed_model,
                    session_id=self.session_id,
                    cell_name=phase.name,
                    trace_id=qm_trace.id,
                    parent_id=trace.id
                )

                query_embedding = embed_result['embeddings'][0]

                # Vector search for most relevant tools
                search_query = f"""
                    SELECT
                        tool_name,
                        tool_type,
                        tool_description,
                        source_path,
                        cosineDistance(embedding, {query_embedding}) as distance
                    FROM tool_manifest_vectors FINAL
                    WHERE length(embedding) > 0
                    ORDER BY distance ASC
                    LIMIT {phase.manifest_limit}
                """

                relevant_tools = db.query(search_query)

                if relevant_tools:
                    # Rebuild manifest with only top N tools
                    filtered_manifest = {}
                    for row in relevant_tools:
                        tool_name = row['tool_name']
                        if tool_name in manifest:
                            filtered_manifest[tool_name] = manifest[tool_name]

                    used_semantic_filtering = True
                    console.print(f"{indent}  [green]✓[/green] Pre-filtered to {len(filtered_manifest)} most relevant tools")
                else:
                    console.print(f"{indent}  [yellow]⚠[/yellow] No embeddings found, using full manifest")

            except Exception as e:
                console.print(f"{indent}  [yellow]⚠[/yellow] Semantic filtering failed: {e}")
                console.print(f"{indent}  [dim]Falling back to full manifest[/dim]")
                # Fall through to use full manifest

        manifest_text = format_manifest_for_quartermaster(filtered_manifest)

        # Build context for quartermaster
        if phase.manifest_context == "full":
            # Full conversation history
            context_text = "## Full Mission Context:\n"
            for msg in self.context_messages[-20:]:  # Last 20 messages to avoid bloat
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                if isinstance(content, str):
                    context_text += f"\n{role.upper()}: {content[:200]}...\n"
        else:
            # Current phase only
            context_text = f"## Mission Instructions:\n{phase.instructions}\n\n## Input Data:\n{json.dumps(input_data)}"

        # Build quartermaster prompt
        qm_prompt = f"""You are the Quartermaster. Your job is to select the most relevant tackle (tools) for this specific mission phase.

{manifest_text}

{context_text}

Based on the mission requirements, select ONLY the tools that are likely to be needed. Do not include tools that won't be used.

Respond with a JSON array of tool names, nothing else. Example: ["tool1", "tool2", "tool3"]

If no tools are needed, return an empty array: []
"""

        # Use phase model or fall back to default
        qm_model = phase_model if phase_model else self.model

        # Create quartermaster agent
        qm_agent = Agent(
            model=qm_model,
            system_prompt="You are an expert Quartermaster who selects the right tools for each job.",
            tools=[],
            base_url=self.base_url,
            api_key=self.api_key
        )

        # Run quartermaster (logging via echo.add_history below)
        response = qm_agent.run(qm_prompt, context_messages=[])
        response_content = response.get("content", "[]")

        # Parse response
        import re
        # Extract JSON array from response (non-greedy to get the full array)
        json_match = re.search(r'\[.*\]', response_content, re.DOTALL)
        if json_match:
            try:
                selected_tackle = json.loads(json_match.group(0))
                if not isinstance(selected_tackle, list):
                    selected_tackle = []
            except Exception as e:
                console.print(f"{indent}    [red]Failed to parse Quartermaster response: {e}[/red]")
                console.print(f"{indent}    [dim]Response: {response_content}[/dim]")
                selected_tackle = []
        else:
            console.print(f"{indent}    [yellow]No JSON array found in response[/yellow]")
            console.print(f"{indent}    [dim]Response: {response_content}[/dim]")
            selected_tackle = []

        # Validate that selected tools exist
        valid_tackle = [t for t in selected_tackle if t in manifest]

        # Add to echo history for visualization (auto-logs via unified_logs)
        self.echo.add_history({
            "role": "quartermaster",
            "content": f"Selected tools: {', '.join(valid_tackle) if valid_tackle else 'none'}",
            "node_type": "quartermaster_result"
        }, trace_id=qm_trace.id, parent_id=trace.id, node_type="quartermaster_result",
           metadata=self._get_metadata({
               "cell_name": phase.name,
               "selected_tackle": valid_tackle,
               "reasoning": response_content,  # Full content, no truncation
               "manifest_context": phase.manifest_context,
               "manifest_limit": phase.manifest_limit,
               "semantic_filtering_used": used_semantic_filtering,
               "tools_considered": len(filtered_manifest),
               "tools_available": len(manifest),
               "model": qm_model
           }, semantic_actor="quartermaster", semantic_purpose="tool_selection"))

        console.print(f"{indent}    [dim]Reasoning: {response_content[:150]}...[/dim]")

        return valid_tackle

    def _fetch_winning_mutations(self, cascade_id: str, cell_name: str, species_hash: str, limit: int = 5) -> List[Dict]:
        """
        Fetch previous winning rewrite mutations for this exact phase species.

        Only returns winners from runs with the SAME species_hash (apples-to-apples).
        This enables learning from what worked before without cross-contaminating
        different phase configurations.

        Args:
            cascade_id: Cascade identifier
            cell_name: Phase name
            species_hash: Species hash for this phase config
            limit: Max number of winners to fetch

        Returns:
            List of dicts with winner info (prompt, score, cost, timestamp)
        """
        try:
            from .db_adapter import get_db

            db = get_db()

            # Query for previous winners with exact same species
            # Include both baseline winners (mutation_type = null) and rewrite winners
            # We want to learn from ANY previous winner of the same species
            query = f"""
                SELECT
                    mutation_applied,
                    timestamp,
                    mutation_type
                FROM unified_logs
                WHERE cascade_id = '{cascade_id}'
                  AND cell_name = '{cell_name}'
                  AND species_hash = '{species_hash}'
                  AND is_winner = true
                  AND (mutation_type = 'rewrite' OR mutation_type IS NULL)
                  AND mutation_applied IS NOT NULL
                  AND mutation_applied != ''
                ORDER BY timestamp DESC
                LIMIT {limit}
            """

            results = db.query(query, output_format='dict')

            # Format for rewrite prompt
            winners = []
            for row in results:
                winners.append({
                    'prompt': row.get('mutation_applied', ''),
                    'timestamp': row.get('timestamp')
                })

            return winners

        except Exception as e:
            # Silently fail - learning is optional
            logger.debug(f"Failed to fetch winning mutations: {e}")
            return []

    def _rewrite_prompt_with_llm(self, phase: CellConfig, input_data: dict, mutation_template: str, parent_trace: TraceNode, mutation_mode: str = "rewrite", species_hash: str = None) -> str:
        """
        Use an LLM to rewrite the phase prompt based on the mutation template.

        This creates a completely rewritten version of the prompt, discovering new
        formulations that may work better. The rewrite call is fully tracked in logs/costs.

        Args:
            phase: The phase config containing instructions to rewrite
            input_data: Input data for rendering the original instructions
            mutation_template: The rewrite instruction (e.g., "Rewrite to be more specific...")
            parent_trace: Parent trace for observability

        Returns:
            The rewritten prompt string
        """
        indent = "  " * self.depth

        # Create trace for this rewrite operation
        rewrite_trace = parent_trace.create_child("prompt_rewrite", "llm_rewrite")

        # Render the original instructions first
        outputs = {item['cell']: item['output'] for item in self.echo.lineage}
        outputs = enrich_outputs_with_artifacts(outputs, self.config.cells, self.session_id)
        render_context = {
            "input": input_data,
            "state": self.echo.state,
            "history": self.echo.history,
            "outputs": outputs,
            "lineage": self.echo.lineage
        }
        original_prompt = render_instruction(phase.instructions, render_context)

        # LEARNING FROM WINNERS: Fetch previous winning mutations for "rewrite" mode
        # (but not "rewrite_free" which is pure exploration)
        winner_context = ""
        if mutation_mode == "rewrite":
            # Get species hash for this exact phase config
            if not species_hash:
                species_hash = compute_species_hash(phase.dict(), input_data)

            # Fetch previous winners with same species (apples-to-apples)
            limit = int(os.environ.get("RVBBIT_WINNER_HISTORY_LIMIT", "5"))
            winners = self._fetch_winning_mutations(
                cascade_id=self.config.cascade_id,
                cell_name=phase.name,
                species_hash=species_hash,
                limit=limit
            )

            if winners:
                console.print(f"{indent}    [dim cyan]📚 Learning from {len(winners)} previous winning rewrites[/dim cyan]")

                # Format winners for inclusion in prompt
                winner_examples = []
                from datetime import datetime
                now = datetime.now()

                for i, w in enumerate(winners, 1):
                    # Calculate age
                    if w['timestamp']:
                        age = now - w['timestamp']
                        if age.days == 0:
                            time_info = "today"
                        elif age.days == 1:
                            time_info = "yesterday"
                        else:
                            time_info = f"{age.days} days ago"
                    else:
                        time_info = "recently"

                    # Truncate long prompts
                    prompt_text = w['prompt']
                    if len(prompt_text) > 400:
                        prompt_text = prompt_text[:400] + "..."

                    winner_examples.append(f"""
### Example {i} - Winner from {time_info}
{prompt_text}
""")

                winner_context = f"""
## Learning from Previous Winning Rewrites:
Below are {len(winners)} rewrites that WON in previous runs of this exact same phase configuration.
Use them as inspiration for effective patterns, but stay creative - find novel variations, don't just copy.
{"".join(winner_examples)}
"""
            else:
                console.print(f"{indent}    [dim]🔬 No previous winners - exploratory rewrite[/dim]")

        elif mutation_mode == "rewrite_free":
            console.print(f"{indent}    [dim]🔬 Pure exploration mode (rewrite_free)[/dim]")

        # Build the rewrite request with optional winner context
        rewrite_request = f"""You are a prompt rewriting assistant. Your job is to rewrite a prompt while preserving its core intent.
{winner_context}
## Original Prompt:
{original_prompt}

## Rewrite Instruction:
{mutation_template}

## Rules:
1. Preserve the core task/intent of the original prompt
2. Apply the rewrite instruction to change how the prompt is formulated
3. {"Consider the winning examples above as inspiration, but find creative variations" if winner_context else "Be creative and exploratory in your rewrite"}
4. Output ONLY the rewritten prompt, nothing else
5. Do not add meta-commentary or explanations
6. The rewritten prompt should be self-contained and complete

## Rewritten Prompt:"""

        # Use the cascade's base model for rewriting to ensure consistency
        # All rewrites within a cascade should use the same model (not per-candidate models)
        # This can be overridden via RVBBIT_REWRITE_MODEL env var
        rewrite_model = os.environ.get("RVBBIT_REWRITE_MODEL", self.model)

        rewrite_agent = Agent(
            model=rewrite_model,
            system_prompt="You are a prompt rewriting assistant. Output only the rewritten prompt.",
            tools=[],
            base_url=self.base_url,
            api_key=self.api_key
        )

        # Make the LLM call - this will be logged automatically by Agent.call()
        response = rewrite_agent.run(rewrite_request, context_messages=[])
        rewritten_prompt = response.get("content", "").strip()

        # Log the rewrite operation to unified logs
        log_message(
            self.session_id,
            "prompt_rewrite",
            rewritten_prompt,
            metadata={
                "original_prompt": original_prompt[:500],  # Truncate for storage
                "mutation_template": mutation_template,
                "rewrite_model": rewrite_model,
                "cell_name": phase.name
            },
            trace_id=rewrite_trace.id,
            parent_id=parent_trace.id,
            node_type="prompt_rewrite",
            depth=self.depth,
            cell_name=phase.name,
            cascade_id=self.config.cascade_id
        )

        # If rewrite failed or returned empty, fall back to original
        if not rewritten_prompt:
            console.print(f"{indent}    [yellow]⚠ Rewrite failed, using original prompt[/yellow]")
            return original_prompt

        return rewritten_prompt

    def _create_memory_tool(self, memory_name: str):
        """
        Dynamically create a callable tool for querying a specific memory bank.

        Args:
            memory_name: Name of the memory bank

        Returns:
            Callable function that queries this specific memory bank
        """
        from .memory import get_memory_system

        memory_system = get_memory_system()
        metadata = memory_system.get_metadata(memory_name)
        summary = metadata.get('summary', f'Conversational memory bank: {memory_name}')

        def memory_query_tool(query: str, limit: int = 5) -> str:
            """
            {summary}

            Args:
                query: Natural language search query
                limit: Maximum number of results to return (default: 5)

            Returns:
                Formatted results with relevant past conversations
            """
            return memory_system.query(memory_name, query, limit)

        # Set function name and docstring for schema generation
        memory_query_tool.__name__ = memory_name
        memory_query_tool.__doc__ = f"{summary}\n\nArgs:\n    query (str): Natural language search query\n    limit (int): Maximum results (default: 5)"

        return memory_query_tool

    def _run_polyglot_validator(
        self,
        validator_config: PolyglotValidatorConfig,
        content: str,
        original_input: dict,
        trace: TraceNode,
        validator_name: str = "polyglot_validator"
    ) -> dict:
        """
        Run a polyglot validator (Python, JS, SQL, etc.) and return validation result.

        The polyglot code receives:
        - content: The output to validate (string)
        - original_input: The original cascade input (dict)

        And must return {"valid": bool, "reason": str}.

        Args:
            validator_config: The PolyglotValidatorConfig with the code
            content: The content to validate
            original_input: Original cascade input for context
            trace: Parent trace node
            validator_name: Name for logging/tracing

        Returns:
            dict with: valid, reason, validator
        """
        indent = "  " * self.depth
        console.print(f"{indent}    [cyan]🔧 Running polyglot validator...[/cyan]")

        try:
            # Get the tool and inputs from the config
            tool_name, tool_inputs = validator_config.get_tool_and_inputs(content, original_input)

            # Get the polyglot tool
            polyglot_tool = get_trait(tool_name)
            if not polyglot_tool:
                return {
                    "valid": False,
                    "reason": f"Polyglot tool '{tool_name}' not found",
                    "validator": validator_name
                }

            # Prepare the execution context
            # For python_data, js_data, etc., we need to inject content and original_input
            # into the code's execution environment

            # Build the code with context injection based on language
            if validator_config.python:
                # Inject validation context at the start of the code
                code_with_context = f'''
# Validation context
content = """{content.replace('"', '\\"').replace("'''", "\\'\\'\\'")}"""
original_input = {json.dumps(original_input)}

# User validation code
{validator_config.python}
'''
                tool_inputs = {"code": code_with_context}

            elif validator_config.javascript:
                # Inject validation context for JS
                code_with_context = f'''
// Validation context
const content = {json.dumps(content)};
const original_input = {json.dumps(original_input)};

// User validation code
{validator_config.javascript}
'''
                tool_inputs = {"code": code_with_context}

            elif validator_config.sql:
                # SQL validators work differently - they query and return valid/reason columns
                # The query should be designed to return a single row with valid (bool) and reason (text)
                tool_inputs = {"query": validator_config.sql}

            elif validator_config.clojure:
                # Inject validation context for Clojure
                code_with_context = f'''
;; Validation context
(def content {json.dumps(content)})
(def original-input {json.dumps(original_input)})

;; User validation code
{validator_config.clojure}
'''
                tool_inputs = {"code": code_with_context}

            elif validator_config.bash:
                # Inject validation context via environment variables
                # The bash script receives CONTENT and ORIGINAL_INPUT as env vars
                code_with_context = f'''
export CONTENT={json.dumps(content)}
export ORIGINAL_INPUT='{json.dumps(original_input)}'

{validator_config.bash}
'''
                tool_inputs = {"script": code_with_context}

            # Add required context for tool execution
            tool_inputs["_cell_name"] = f"validator_{validator_name}"
            tool_inputs["_session_id"] = self.session_id
            tool_inputs["_outputs"] = self.echo.outputs if hasattr(self.echo, 'outputs') else {}
            tool_inputs["_state"] = self.echo.state if hasattr(self.echo, 'state') else {}
            tool_inputs["_input"] = original_input

            # Execute the polyglot tool
            set_current_trace(trace)
            result = polyglot_tool(**tool_inputs)

            # Extract the validation result
            if isinstance(result, dict):
                # Check if result is in the expected format
                if "result" in result:
                    # The polyglot tool wraps the output in a 'result' field for python_data
                    validator_result = result.get("result", result)
                elif "data" in result and isinstance(result["data"], list) and len(result["data"]) > 0:
                    # SQL result - first row should have valid and reason columns
                    row = result["data"][0]
                    validator_result = {
                        "valid": bool(row.get("valid", False)),
                        "reason": str(row.get("reason", "No reason provided"))
                    }
                else:
                    # Direct result from tool
                    validator_result = result

                # Ensure we have the expected structure
                if "valid" not in validator_result:
                    validator_result = {"valid": False, "reason": f"Invalid validator result format: {validator_result}"}

            elif isinstance(result, str):
                # Try to parse as JSON
                try:
                    validator_result = json.loads(result)
                except:
                    validator_result = {"valid": False, "reason": result}
            else:
                validator_result = {"valid": False, "reason": f"Unexpected result type: {type(result)}"}

            is_valid = validator_result.get("valid", False)
            reason = validator_result.get("reason", "No reason provided")

            # Log result
            if is_valid:
                console.print(f"{indent}    [bold green]✓ PASSED:[/bold green] {reason}")
            else:
                console.print(f"{indent}    [bold red]✗ FAILED:[/bold red] {reason}")

            return {
                "valid": is_valid,
                "reason": reason,
                "validator": validator_name
            }

        except Exception as e:
            error_msg = f"Polyglot validator error: {str(e)}"
            console.print(f"{indent}    [bold red]✗ ERROR:[/bold red] {error_msg}")
            return {
                "valid": False,
                "reason": error_msg,
                "validator": validator_name
            }

    def _run_ward(self, ward_config, content: str, trace: TraceNode, ward_type: str = "post") -> dict:
        """
        Run a single ward (validator) and return validation result.

        Returns dict with:
        - valid: bool
        - reason: str
        - mode: str (blocking, retry, advisory)
        """
        indent = "  " * self.depth
        validator_spec = ward_config.validator
        mode = ward_config.mode

        # Check if validator is a PolyglotValidatorConfig (inline polyglot code)
        if isinstance(validator_spec, PolyglotValidatorConfig):
            validator_name = "polyglot_validator"
            mode_icons = {
                "blocking": "🛡️",
                "retry": "🔄",
                "advisory": "ℹ️"
            }
            icon = mode_icons.get(mode, "🛡️")
            console.print(f"{indent}  {icon} [{ward_type.upper()} WARD] polyglot ({mode} mode)")

            # Create ward trace
            ward_trace = trace.create_child(f"{ward_type}_ward", "polyglot")

            # Run the polyglot validator
            result = self._run_polyglot_validator(
                validator_spec,
                content,
                self.echo.input if hasattr(self.echo, 'input') else {},
                ward_trace,
                validator_name="polyglot"
            )

            # Add ward to Echo history for visualization
            self.echo.add_history({
                "role": "ward",
                "content": f"{ward_type.title()} Ward: polyglot",
                "node_type": f"{ward_type}_ward"
            }, trace_id=ward_trace.id, parent_id=trace.id, node_type=f"{ward_type}_ward",
               metadata=self._get_metadata({
                   "ward_type": ward_type,
                   "validator": "polyglot",
                   "mode": mode,
                   "valid": result.get("valid", False),
                   "reason": result.get("reason", "")[:100]
               }, semantic_actor="validator", semantic_purpose="validation_output"))

            return {
                "valid": result.get("valid", False),
                "reason": result.get("reason", "No reason provided"),
                "mode": mode,
                "validator": "polyglot"
            }

        # String validator - existing behavior
        validator_name = validator_spec

        mode_icons = {
            "blocking": "🛡️",
            "retry": "🔄",
            "advisory": "ℹ️"
        }
        icon = mode_icons.get(mode, "🛡️")

        console.print(f"{indent}  {icon} [{ward_type.upper()} WARD] {validator_name} ({mode} mode)")

        # Create ward trace
        ward_trace = trace.create_child(f"{ward_type}_ward", validator_name)

        # Try to get validator as Python function first
        validator_tool = get_trait(validator_name)
        validator_result = None

        # If not found as function, check if it's a cascade tool
        if not validator_tool:
            from .traits_manifest import get_trait_manifest
            manifest = get_trait_manifest()

            if validator_name in manifest and manifest[validator_name]["type"] == "cascade":
                # It's a cascade validator
                cascade_path = manifest[validator_name]["path"]
                validator_input = {"content": content}

                # Generate unique ward session ID (include candidate index if inside soundings)
                ward_candidate_index = None
                if self.current_phase_candidate_index is not None:
                    ward_session_id = f"{self.session_id}_ward_{self.current_phase_candidate_index}"
                    ward_candidate_index = self.current_phase_candidate_index
                elif self.candidate_index is not None:
                    ward_session_id = f"{self.session_id}_ward_{self.candidate_index}"
                    ward_candidate_index = self.candidate_index
                else:
                    ward_session_id = f"{self.session_id}_ward"

                try:
                    # Run the validator cascade
                    validator_result_echo = run_cascade(
                        cascade_path,
                        validator_input,
                        ward_session_id,
                        self.overrides,
                        self.depth + 1,
                        parent_trace=ward_trace,
                        hooks=self.hooks,
                        parent_session_id=self.session_id,  # Link child to parent session
                        candidate_index=ward_candidate_index
                    )

                    # Extract result from lineage
                    if validator_result_echo.get("lineage"):
                        last_output = validator_result_echo["lineage"][-1].get("output", "")
                        try:
                            validator_result = json.loads(last_output)
                        except:
                            import re
                            json_match = re.search(r'\{[^}]*"valid"[^}]*\}', last_output, re.DOTALL)
                            if json_match:
                                try:
                                    validator_result = json.loads(json_match.group(0))
                                except:
                                    validator_result = {"valid": False, "reason": "Could not parse validator response"}
                            else:
                                validator_result = {"valid": False, "reason": last_output}
                    else:
                        validator_result = {"valid": False, "reason": "No output from validator"}

                except Exception as e:
                    validator_result = {"valid": False, "reason": f"Ward execution error: {str(e)}"}
            else:
                # Validator not found
                console.print(f"{indent}    [yellow]Warning: Validator '{validator_name}' not found[/yellow]")
                validator_result = {"valid": True, "reason": "Validator not found - skipping"}

        # Handle function validators
        if validator_tool and callable(validator_tool):
            try:
                set_current_trace(ward_trace)
                result = validator_tool(content=content)

                if isinstance(result, str):
                    try:
                        validator_result = json.loads(result)
                    except:
                        validator_result = {"valid": False, "reason": result}
                else:
                    validator_result = result

            except Exception as e:
                validator_result = {"valid": False, "reason": f"Ward error: {str(e)}"}

        # Parse result
        is_valid = validator_result.get("valid", False)
        reason = validator_result.get("reason", "No reason provided")

        # Add ward to Echo history for visualization (auto-logs via unified_logs)
        self.echo.add_history({
            "role": "ward",
            "content": f"{ward_type.title()} Ward: {validator_name}",
            "node_type": f"{ward_type}_ward"
        }, trace_id=ward_trace.id, parent_id=trace.id, node_type=f"{ward_type}_ward",
           metadata=self._get_metadata({
               "ward_type": ward_type,
               "validator": validator_name,
               "mode": mode,
               "valid": is_valid,
               "reason": reason[:100] if reason else ""
           }, semantic_actor="validator", semantic_purpose="validation_output"))

        # Display result
        if is_valid:
            console.print(f"{indent}    [bold green]✓ PASSED:[/bold green] {reason}")
        else:
            console.print(f"{indent}    [bold red]✗ FAILED:[/bold red] {reason}")

        return {
            "valid": is_valid,
            "reason": reason,
            "mode": mode,
            "validator": validator_name
        }

    def _run_sounding_validator(self, validator_spec: Union[str, PolyglotValidatorConfig], content: str, candidate_index: int, trace: TraceNode) -> dict:
        """
        Run a validator on a candidate result to determine if it should be evaluated.

        This is a simplified version of _run_ward for pre-evaluation filtering.
        Validators that return {"valid": false} will exclude the candidate from evaluation.

        Returns dict with:
        - valid: bool
        - reason: str
        """
        indent = "  " * self.depth

        # Check if validator is a PolyglotValidatorConfig (inline polyglot code)
        if isinstance(validator_spec, PolyglotValidatorConfig):
            validator_trace = trace.create_child("sounding_validator", f"polyglot_{candidate_index}")

            result = self._run_polyglot_validator(
                validator_spec,
                content,
                self.echo.input if hasattr(self.echo, 'input') else {},
                validator_trace,
                validator_name=f"polyglot_{candidate_index}"
            )

            return {
                "valid": result.get("valid", False),
                "reason": result.get("reason", "No reason provided"),
                "validator": "polyglot",
                "candidate_index": candidate_index
            }

        # String validator - existing behavior
        validator_name = validator_spec

        # Create validator trace
        validator_trace = trace.create_child("sounding_validator", f"{validator_name}_{candidate_index}")

        # Try to get validator as Python function first
        validator_tool = get_trait(validator_name)
        validator_result = None

        # If not found as function, check if it's a cascade tool
        if not validator_tool:
            from .traits_manifest import get_trait_manifest
            manifest = get_trait_manifest()

            if validator_name in manifest and manifest[validator_name]["type"] == "cascade":
                # It's a cascade validator
                cascade_path = manifest[validator_name]["path"]
                validator_input = {"content": content}

                # Generate unique validator session ID
                validator_session_id = f"{self.session_id}_sounding_validator_{candidate_index}"

                try:
                    # Run the validator cascade
                    validator_result_echo = run_cascade(
                        cascade_path,
                        validator_input,
                        validator_session_id,
                        self.overrides,
                        self.depth + 1,
                        parent_trace=validator_trace,
                        hooks=self.hooks,
                        parent_session_id=self.session_id,
                        candidate_index=candidate_index
                    )

                    # Extract result from lineage
                    if validator_result_echo.get("lineage"):
                        last_output = validator_result_echo["lineage"][-1].get("output", "")
                        try:
                            validator_result = json.loads(last_output)
                        except:
                            import re
                            json_match = re.search(r'\{[^}]*"valid"[^}]*\}', last_output, re.DOTALL)
                            if json_match:
                                try:
                                    validator_result = json.loads(json_match.group(0))
                                except:
                                    validator_result = {"valid": False, "reason": "Could not parse validator response"}
                            else:
                                validator_result = {"valid": False, "reason": last_output}
                    else:
                        validator_result = {"valid": False, "reason": "No output from validator"}

                except Exception as e:
                    validator_result = {"valid": False, "reason": f"Validator execution error: {str(e)}"}
            else:
                # Validator not found - skip validation (don't block)
                console.print(f"{indent}    [yellow]Warning: Sounding validator '{validator_name}' not found - skipping validation[/yellow]")
                validator_result = {"valid": True, "reason": "Validator not found - skipping"}

        # Handle function validators
        if validator_tool and callable(validator_tool):
            try:
                set_current_trace(validator_trace)
                result = validator_tool(content=content)

                if isinstance(result, str):
                    try:
                        validator_result = json.loads(result)
                    except:
                        validator_result = {"valid": False, "reason": result}
                else:
                    validator_result = result

            except Exception as e:
                validator_result = {"valid": False, "reason": f"Validator error: {str(e)}"}

        # Parse result
        is_valid = validator_result.get("valid", False)
        reason = validator_result.get("reason", "No reason provided")

        return {
            "valid": is_valid,
            "reason": reason,
            "validator": validator_name,
            "candidate_index": candidate_index
        }

    def _run_loop_until_validator(
        self,
        validator_spec: Union[str, PolyglotValidatorConfig],
        content: str,
        input_data: dict,
        trace: TraceNode,
        attempt: int = 0,
        turn: int = 0,
        is_per_turn: bool = False
    ) -> dict:
        """
        Run a loop_until validator to check if phase output satisfies requirements.

        This method supports per-turn validation (early exit from turn loop) as well as
        post-turn-loop validation. When is_per_turn=True, validation passes will allow
        breaking out of the turn loop early, preventing unnecessary context snowballing.

        Args:
            validator_spec: Validator specification - can be string name or PolyglotValidatorConfig
            content: The content to validate (agent response + tool outputs)
            input_data: Original cascade input (passed to cascade validators)
            trace: Parent trace node for logging
            attempt: Current attempt number (for session ID generation)
            turn: Current turn number (for logging)
            is_per_turn: Whether this is a per-turn check (vs post-loop)

        Returns:
            dict with:
            - valid: bool
            - reason: str
            - validator: str
        """
        indent = "  " * self.depth
        check_type = "per-turn" if is_per_turn else "post-loop"

        # === PRIORITY 0: Check if validator is a PolyglotValidatorConfig (inline polyglot code) ===
        if isinstance(validator_spec, PolyglotValidatorConfig):
            validation_trace = trace.create_child("loop_until_validation", f"polyglot_t{turn}")

            console.print(f"{indent}  🔁 [{check_type}] Running polyglot validator...")

            result = self._run_polyglot_validator(
                validator_spec,
                content,
                input_data,
                validation_trace,
                validator_name="loop_until_polyglot"
            )

            # Log validation result
            self.echo.add_history({
                "role": "loop_until_validation",
                "content": f"Loop-until polyglot validation ({check_type})",
                "node_type": "loop_until_validation"
            }, trace_id=validation_trace.id, parent_id=trace.id, node_type="loop_until_validation",
               metadata=self._get_metadata({
                   "validator": "polyglot",
                   "valid": result.get("valid", False),
                   "reason": result.get("reason", "")[:100],
                   "check_type": check_type,
                   "attempt": attempt,
                   "turn": turn
               }, semantic_actor="validator", semantic_purpose="validation_output"))

            return {
                "valid": result.get("valid", False),
                "reason": result.get("reason", "No reason provided"),
                "validator": "polyglot"
            }

        # String validator - existing behavior
        validator_name = validator_spec

        # Create validation trace
        validation_trace = trace.create_child("loop_until_validation", f"{validator_name}_t{turn}")

        validator_result = None

        # === PRIORITY 1: Check inline validators first ===
        if self.config.validators and validator_name in self.config.validators:
            inline_config = self.config.validators[validator_name]

            # Extract recent images from conversation context for multi-modal validation
            from .utils import extract_images_from_messages
            context_images = extract_images_from_messages(self.context_messages) if self.context_messages else []

            # Build validator input
            validator_input = {
                "content": content,
                "original_input": input_data,
                "has_images": len(context_images) > 0,
                "image_count": len(context_images)
            }

            # Generate unique validator session ID
            validator_candidate_index = None
            if self.current_phase_candidate_index is not None:
                validator_session_id = f"{self.session_id}_inline_validator_{attempt}_t{turn}_{self.current_phase_candidate_index}"
                validator_candidate_index = self.current_phase_candidate_index
            elif self.candidate_index is not None:
                validator_session_id = f"{self.session_id}_inline_validator_{attempt}_t{turn}_{self.candidate_index}"
                validator_candidate_index = self.candidate_index
            else:
                validator_session_id = f"{self.session_id}_inline_validator_{attempt}_t{turn}"

            try:
                # Build a mini-cascade config from inline validator
                from .cascade import CascadeConfig, CellConfig, RuleConfig

                # Use configured model or default to a cheap/fast model
                validator_model = inline_config.model or "google/gemini-2.5-flash-lite"

                # Render instructions with input context
                from .prompts import render_instruction
                rendered_instructions = render_instruction(
                    inline_config.instructions,
                    {"input": validator_input}
                )

                mini_cascade = CascadeConfig(
                    cascade_id=f"{self.config.cascade_id}_validator_{validator_name}",
                    description=f"Inline validator: {validator_name}",
                    inputs_schema={
                        "content": "The content to validate",
                        "original_input": "The original cascade input"
                    },
                    cells=[
                        CellConfig(
                            name="validate",
                            model=validator_model,
                            instructions=rendered_instructions,
                            rules=RuleConfig(max_turns=inline_config.max_turns)
                        )
                    ]
                )

                # Run the inline validator as a sub-cascade
                validator_runner = RVBBITRunner(
                    mini_cascade,
                    validator_session_id,
                    self.overrides,
                    self.depth + 1,
                    parent_trace=validation_trace,
                    hooks=self.hooks,
                    parent_session_id=self.session_id,
                    candidate_index=validator_candidate_index
                )

                # Inject images into validator context if available (multi-modal validation)
                if context_images:
                    # Build multi-modal context message with images
                    image_content = [{"type": "text", "text": f"[{len(context_images)} image(s) from the phase output to validate]:"}]
                    for img_data, desc in context_images[-3:]:  # Last 3 images max
                        image_content.append({
                            "type": "image_url",
                            "image_url": {"url": img_data}
                        })
                    # Pre-populate validator's context with images
                    validator_runner.context_messages = [{
                        "role": "user",
                        "content": image_content
                    }]

                validator_result_echo = validator_runner.run(validator_input)

                # Extract the result - look in lineage for last phase output
                if validator_result_echo.get("lineage"):
                    last_output = validator_result_echo["lineage"][-1].get("output", "")
                    try:
                        validator_result = json.loads(last_output)
                    except:
                        # If not JSON, try to extract from text
                        import re
                        json_match = re.search(r'\{[^}]*"valid"[^}]*\}', last_output, re.DOTALL)
                        if json_match:
                            try:
                                validator_result = json.loads(json_match.group(0))
                            except:
                                validator_result = {"valid": False, "reason": "Could not parse validator response"}
                        else:
                            validator_result = {"valid": False, "reason": last_output}
                else:
                    validator_result = {"valid": False, "reason": "No output from inline validator"}

            except Exception as e:
                validator_result = {"valid": False, "reason": f"Inline validator error: {str(e)}"}

        # === PRIORITY 2: Try to get validator as Python function ===
        if validator_result is None:
            validator_tool = get_trait(validator_name)

            # Handle function validators first
            if validator_tool and callable(validator_tool):
                try:
                    set_current_trace(validation_trace)
                    result = validator_tool(content=content)

                    if isinstance(result, str):
                        try:
                            validator_result = json.loads(result)
                        except:
                            validator_result = {"valid": False, "reason": result}
                    else:
                        validator_result = result

                except Exception as e:
                    validator_result = {"valid": False, "reason": f"Validator error: {str(e)}"}

            # === PRIORITY 3: Check if it's a cascade tool ===
            elif not validator_tool:
                from .traits_manifest import get_trait_manifest
                manifest = get_trait_manifest()

                if validator_name in manifest and manifest[validator_name]["type"] == "cascade":
                    # It's a cascade validator - invoke it as a sub-cascade
                    cascade_path = manifest[validator_name]["path"]
                    # Pass both the output AND original input for context
                    validator_input = {
                        "content": content,
                        "original_input": input_data
                    }

                    # Generate unique validator session ID
                    validator_candidate_index = None
                    if self.current_phase_candidate_index is not None:
                        validator_session_id = f"{self.session_id}_validator_{attempt}_t{turn}_{self.current_phase_candidate_index}"
                        validator_candidate_index = self.current_phase_candidate_index
                    elif self.candidate_index is not None:
                        validator_session_id = f"{self.session_id}_validator_{attempt}_t{turn}_{self.candidate_index}"
                        validator_candidate_index = self.candidate_index
                    else:
                        validator_session_id = f"{self.session_id}_validator_{attempt}_t{turn}"

                    try:
                        # Run the validator cascade
                        validator_result_echo = run_cascade(
                            cascade_path,
                            validator_input,
                            validator_session_id,
                            self.overrides,
                            self.depth + 1,
                            parent_trace=validation_trace,
                            hooks=self.hooks,
                            parent_session_id=self.session_id,
                            candidate_index=validator_candidate_index
                        )

                        # Extract the result - look in lineage for last phase output
                        if validator_result_echo.get("lineage"):
                            last_output = validator_result_echo["lineage"][-1].get("output", "")
                            try:
                                validator_result = json.loads(last_output)
                            except:
                                # If not JSON, try to extract from text
                                import re
                                json_match = re.search(r'\{[^}]*"valid"[^}]*\}', last_output, re.DOTALL)
                                if json_match:
                                    try:
                                        validator_result = json.loads(json_match.group(0))
                                    except:
                                        validator_result = {"valid": False, "reason": "Could not parse validator response"}
                                else:
                                    validator_result = {"valid": False, "reason": last_output}
                        else:
                            validator_result = {"valid": False, "reason": "No output from validator"}

                    except Exception as e:
                        validator_result = {"valid": False, "reason": f"Validator execution error: {str(e)}"}
                else:
                    # Validator not found
                    console.print(f"{indent}  [yellow]Warning: Validator '{validator_name}' not found[/yellow]")
                    return {"valid": True, "reason": "Validator not found - skipping", "validator": validator_name}

        # Parse result
        is_valid = validator_result.get("valid", False) if validator_result else False
        reason = validator_result.get("reason", "No reason provided") if validator_result else "Validator returned no result"

        # Log result (only show for per-turn if it passes, to reduce noise)
        if is_per_turn and is_valid:
            console.print(f"{indent}  [bold green]✓ Early exit: {validator_name} passed on turn {turn + 1}[/bold green]")
        elif not is_per_turn:
            if is_valid:
                console.print(f"{indent}  [bold green]✓ Validator passed: {reason[:100]}[/bold green]")
            else:
                console.print(f"{indent}  [bold yellow]✗ Validator failed: {reason[:100]}[/bold yellow]")

        return {
            "valid": is_valid,
            "reason": reason,
            "validator": validator_name
        }

    def _assign_models(self, soundings_config, resolved_factor: int = None) -> List[str]:
        """
        Assign models to candidate attempts based on configuration.

        Returns a list of model names, one per candidate attempt.

        Args:
            soundings_config: CandidatesConfig with optional multi-model settings
            resolved_factor: Resolved factor value (optional, overrides soundings_config.factor)

        Returns:
            List of model names to use for each candidate
        """
        import random

        # Use resolved_factor if provided, otherwise get from config (and handle string/int)
        if resolved_factor is not None:
            factor = resolved_factor
        elif isinstance(soundings_config.factor, str):
            # If factor is still a string template, we can't resolve it here
            # This shouldn't happen if caller passes resolved_factor
            raise ValueError(f"Cannot assign models with unresolved factor template: {soundings_config.factor}")
        else:
            factor = soundings_config.factor

        # Case 1: No multi-model configuration - use default model for all
        if soundings_config.models is None:
            return [self.model] * factor

        # Case 2: List of models - apply strategy (round-robin, random, etc.)
        if isinstance(soundings_config.models, list):
            models = soundings_config.models
            strategy = soundings_config.model_strategy

            if strategy == "round_robin":
                # Cycle through models in order
                return [models[i % len(models)] for i in range(factor)]

            elif strategy == "random":
                # Random selection for each candidate
                return [random.choice(models) for _ in range(factor)]

            else:
                # Default to round-robin if unknown strategy
                return [models[i % len(models)] for i in range(factor)]

        # Case 3: Dict with per-model factors - expand based on each model's factor
        elif isinstance(soundings_config.models, dict):
            assigned = []
            for model_name, config in soundings_config.models.items():
                # Add this model N times based on its factor
                assigned.extend([model_name] * config.factor)
            return assigned

        # Fallback: use default
        return [self.model] * factor

    def _filter_models_by_context(
        self,
        models: List[str],
        cell: CellConfig,
        input_data: dict
    ) -> Dict[str, Any]:
        """
        Filter models based on context window requirements.

        Estimates token usage for the current request and filters out models
        with insufficient context limits.

        Args:
            models: List of candidate model IDs
            cell: Cell configuration
            input_data: Input data for rendering

        Returns:
            Dict with:
                - viable_models: List[str] - Models with sufficient context
                - filtered_models: List[str] - Models that were filtered out
                - filter_details: Dict - Details about why models were filtered
                - estimated_tokens: int - Estimated token count
        """
        from .model_metadata import get_model_cache, estimate_request_tokens
        from .prompts import render_instruction

        # Get unique models (dedup before checking)
        unique_models = list(dict.fromkeys(models))

        # If only one unique model, skip filtering (no point)
        if len(unique_models) <= 1:
            return {
                "viable_models": models,
                "filtered_models": [],
                "filter_details": {},
                "estimated_tokens": 0,
                "required_tokens": 0
            }

        # Build render context for system prompt
        # outputs is built dynamically from lineage (not an Echo attribute)
        outputs = {item['cell']: item['output'] for item in self.echo.lineage}
        outputs = enrich_outputs_with_artifacts(outputs, self.config.cells, self.session_id)
        render_context = {
            "input": input_data or {},
            "state": self.echo.state,
            "outputs": outputs,
            "lineage": self.echo.lineage,
            "history": self.echo.history
        }

        # Render system prompt to estimate tokens
        try:
            rendered_instructions = render_instruction(cell.instructions, render_context)
        except Exception as e:
            # If rendering fails, skip filtering
            console.print(f"  [yellow]Warning: Failed to render instructions for token estimation: {e}[/yellow]")
            return {
                "viable_models": models,
                "filtered_models": [],
                "filter_details": {},
                "estimated_tokens": 0,
                "required_tokens": 0
            }

        # Get tool schemas (estimate token cost)
        tools_schema = []
        if cell.traits:
            try:
                from .trait_registry import get_trait
                tool_map, tools_schema, tool_descriptions = get_trait(cell.traits)
            except Exception:
                pass  # If tackle fails, just skip tool token estimation

        # Estimate tokens for full request
        estimated_tokens = estimate_request_tokens(
            messages=self.context_messages,
            tools=tools_schema if tools_schema else None,
            system_prompt=rendered_instructions,
            model=models[0] if models else self.model
        )

        # Get model cache and filter
        cache = get_model_cache()

        # Run async filtering
        import asyncio
        try:
            # Run in new event loop
            filter_result = asyncio.run(cache.filter_viable_models(
                models=unique_models,
                estimated_tokens=estimated_tokens,
                buffer_factor=1.15
            ))

            # Map filtered unique models back to original list (preserving duplicates)
            viable_unique = set(filter_result["viable_models"])
            viable_models = [m for m in models if m in viable_unique]

            # Update result with mapped models
            filter_result["viable_models"] = viable_models

            return filter_result

        except Exception as e:
            # If filtering fails, log and return all models
            console.print(f"  [yellow]Warning: Model filtering failed: {e}[/yellow]")
            return {
                "viable_models": models,
                "filtered_models": [],
                "filter_details": {},
                "estimated_tokens": estimated_tokens,
                "required_tokens": estimated_tokens
            }

    def _aggregate_with_llm(self, outputs: List[Dict], instructions: str, model: str, trace: TraceNode) -> str:
        """
        Use an LLM to aggregate/merge multiple candidate outputs into a single coherent output.

        Args:
            outputs: List of output dicts with "index", "output", "model", "mutation_applied", "images"
            instructions: Instructions for how to aggregate the outputs
            model: Model to use for aggregation
            trace: Parent trace node for tracking

        Returns:
            str: The aggregated output
        """
        indent = "  " * self.depth
        aggregator_trace = trace.create_child("llm_aggregator", "aggregate_outputs")

        # Check if any outputs have images (for multi-modal aggregation)
        any_images = any(o.get('images') for o in outputs)
        total_images = sum(len(o.get('images', [])) for o in outputs)

        # Build the aggregation prompt
        outputs_text = ""
        for i, o in enumerate(outputs):
            outputs_text += f"\n\n## Output {o['index']+1}"
            if o.get('model'):
                outputs_text += f" (Model: {o['model']})"
            outputs_text += f"\n{o['output']}"
            if o.get('images'):
                outputs_text += f"\n(📸 {len(o['images'])} image(s) attached below)"

        prompt = f"""{instructions}

Here are the {len(outputs)} outputs to aggregate:
{outputs_text}

Please combine/synthesize these outputs according to the instructions above. Produce a single coherent output that captures the best aspects of each."""

        # Build context messages with images for multi-modal aggregation
        context_messages = []
        if any_images:
            # Add images with clear labeling for which output they belong to
            for o in outputs:
                output_images = o.get('images', [])
                if output_images:
                    content_parts = [{
                        "type": "text",
                        "text": f"═══ Images from Output {o['index']+1} ({len(output_images)} image{'s' if len(output_images) > 1 else ''}) ═══"
                    }]
                    for img_idx, img_data in enumerate(output_images):
                        # Handle tuple format (base64_url, description) or plain string
                        if isinstance(img_data, tuple) and len(img_data) >= 1:
                            img_url = img_data[0]
                        else:
                            img_url = img_data
                        content_parts.append({
                            "type": "image_url",
                            "image_url": {"url": img_url}
                        })
                        content_parts.append({
                            "type": "text",
                            "text": f"↑ Output {o['index']+1}, Image {img_idx+1}/{len(output_images)}"
                        })
                    context_messages.append({
                        "role": "user",
                        "content": content_parts
                    })
            console.print(f"{indent}  [cyan]📸 Multi-modal aggregation: {total_images} total images[/cyan]")

        # Create aggregator agent
        from .agent import Agent
        aggregator_agent = Agent(
            model=model,
            system_prompt="You are an expert at synthesizing and combining multiple outputs into a coherent whole. Your task is to merge the given outputs according to the user's instructions. If images are provided, consider them when synthesizing.",
            tools=[],
            base_url=self.base_url,
            api_key=self.api_key
        )

        console.print(f"{indent}  [dim]Aggregating with {model}...[/dim]")
        response = aggregator_agent.run(prompt, context_messages=context_messages if context_messages else None)
        aggregated_content = response.get("content", "")

        # Log to echo
        self.echo.add_history({
            "role": "assistant",
            "content": aggregated_content[:200] + "..." if len(aggregated_content) > 200 else aggregated_content
        }, trace_id=aggregator_trace.id, parent_id=trace.id, node_type="aggregator_response",
           metadata={
               "model": model,
               "input_count": len(outputs),
               "total_images": total_images,
               "is_multimodal": any_images,
               "semantic_actor": "aggregator",
               "semantic_purpose": "aggregation",
           })

        return aggregated_content

    def _get_sounding_costs(self, sounding_results: List[Dict], timeout: float = 5.0) -> List[float]:
        """
        Get costs for each candidate attempt from unified logs.

        Waits briefly for async cost tracking to complete, then queries logs.
        Falls back to cost estimation if costs aren't available.

        Args:
            sounding_results: List of candidate result dicts with trace_id
            timeout: Max seconds to wait for costs

        Returns:
            List of costs, one per candidate
        """
        import time

        # Give the async cost tracker time to complete (OpenRouter delays ~3s)
        time.sleep(min(timeout, 2.0))

        costs = []
        for sr in sounding_results:
            trace_id = sr.get("trace_id")
            model = sr.get("model", self.model)

            # Try to get cost from logs
            cost = self._query_sounding_cost(trace_id)

            if cost is None or cost == 0:
                # Estimate cost based on model and typical token usage
                cost = self._estimate_cost(model, sr.get("result", ""))

            costs.append(cost)

        return costs

    def _query_sounding_cost(self, trace_id: str) -> Optional[float]:
        """Query unified logs for cost of a specific trace."""
        try:
            from .unified_logs import query_unified
            df = query_unified(f"trace_id = '{trace_id}' AND cost > 0", limit=10)
            if df is not None and len(df) > 0:
                return df['cost'].sum()
        except Exception:
            pass
        return None

    def _estimate_cost(self, model: str, result: str) -> float:
        """
        Estimate cost based on model and output length.

        Very rough estimates - actual costs vary significantly.
        """
        # Rough per-1M-token pricing (input + output averaged)
        model_pricing = {
            "anthropic/claude-sonnet-4": 9.0,
            "anthropic/claude-3-5-sonnet": 9.0,
            "anthropic/claude-3-opus": 45.0,
            "openai/gpt-4o": 7.5,
            "openai/gpt-4o-mini": 0.4,
            "google/gemini-2.0-flash-001": 0.3,
            "google/gemini-2.0-flash-exp": 0.3,
            "google/gemini-2.5-flash-lite": 0.075,
        }

        # Default to mid-tier pricing
        price_per_million = model_pricing.get(model, 5.0)

        # Estimate tokens (very rough: ~4 chars per token)
        estimated_tokens = len(result) / 4 if result else 100

        # Add typical input tokens (prompt)
        estimated_tokens += 500

        # Calculate cost
        return (estimated_tokens / 1_000_000) * price_per_million

    def _normalize_costs(self, costs: List[float], method: str = "min_max") -> List[float]:
        """
        Normalize costs for fair comparison in cost-aware evaluation.

        Args:
            costs: List of raw costs
            method: Normalization method ("min_max", "z_score", "log_scale")

        Returns:
            List of normalized costs (0-1 for min_max, standardized for z_score)
        """
        import math

        if not costs or all(c == 0 for c in costs):
            return [0.0] * len(costs)

        if method == "min_max":
            min_c, max_c = min(costs), max(costs)
            if max_c == min_c:
                return [0.0] * len(costs)
            return [(c - min_c) / (max_c - min_c) for c in costs]

        elif method == "z_score":
            mean = sum(costs) / len(costs)
            variance = sum((c - mean) ** 2 for c in costs) / len(costs)
            std = math.sqrt(variance) if variance > 0 else 1.0
            if std == 0:
                return [0.0] * len(costs)
            return [(c - mean) / std for c in costs]

        elif method == "log_scale":
            return [math.log(c + 1e-6) for c in costs]

        else:
            return costs

    def _build_cost_aware_eval_prompt(
        self,
        sounding_results: List[Dict],
        costs: List[float],
        soundings_config,
        base_instructions: str
    ) -> str:
        """
        Build an evaluation prompt that includes cost information.

        Args:
            sounding_results: List of candidate result dicts
            costs: List of costs per candidate
            soundings_config: CandidatesConfig with cost_aware_evaluation settings
            base_instructions: Original evaluator instructions

        Returns:
            Complete evaluation prompt with cost context
        """
        cost_config = soundings_config.cost_aware_evaluation

        eval_prompt = f"{base_instructions}\n\n"

        if cost_config.show_costs_to_evaluator:
            quality_pct = int(cost_config.quality_weight * 100)
            cost_pct = int(cost_config.cost_weight * 100)

            eval_prompt += f"""COST-QUALITY BALANCE:
Consider quality ({quality_pct}%) and cost ({cost_pct}%) when selecting the winner.
- If two outputs have similar quality, prefer the cheaper one.
- If one is significantly higher quality, it may justify higher cost.

"""

        eval_prompt += "Please evaluate the following attempts and select the best one.\n\n"

        for i, candidate in enumerate(sounding_results):
            eval_prompt += f"## Attempt {i+1}\n"

            if cost_config.show_costs_to_evaluator:
                model = candidate.get("model", "unknown")
                cost = costs[i]
                eval_prompt += f"Model: {model}\n"
                eval_prompt += f"Cost: ${cost:.6f}\n"

            eval_prompt += f"Result: {candidate['result']}\n\n"

        eval_prompt += f"\nRespond with ONLY the number of the best attempt (1-{len(sounding_results)}) and a brief explanation."

        return eval_prompt

    def _compute_pareto_frontier(
        self,
        sounding_results: List[Dict],
        quality_scores: List[float],
        costs: List[float]
    ) -> tuple:
        """
        Compute the Pareto frontier for cost vs quality.

        A candidate is Pareto-optimal (non-dominated) if no other candidate is
        both cheaper AND higher quality.

        Args:
            sounding_results: List of candidate result dicts
            quality_scores: List of quality scores (higher is better)
            costs: List of costs (lower is better)

        Returns:
            Tuple of (frontier_indices, dominated_map, pareto_ranks)
            - frontier_indices: List of indices that are on the frontier
            - dominated_map: Dict mapping dominated index -> dominating index
            - pareto_ranks: Dict mapping index -> rank (1 = frontier, 2+ = dominated)
        """
        n = len(sounding_results)
        frontier_indices = []
        dominated_map = {}

        for i in range(n):
            dominated = False
            dominator = None

            for j in range(n):
                if i == j:
                    continue

                # Check if j dominates i
                # j dominates i if: j has >= quality AND <= cost AND is strictly better in at least one
                quality_better_or_equal = quality_scores[j] >= quality_scores[i]
                cost_better_or_equal = costs[j] <= costs[i]
                strictly_better = (quality_scores[j] > quality_scores[i]) or (costs[j] < costs[i])

                if quality_better_or_equal and cost_better_or_equal and strictly_better:
                    dominated = True
                    dominator = j
                    break

            if not dominated:
                frontier_indices.append(i)
            else:
                dominated_map[i] = dominator

        # Compute Pareto ranks (distance from frontier)
        pareto_ranks = {}
        for i in range(n):
            if i in frontier_indices:
                pareto_ranks[i] = 1
            else:
                # Rank 2 = dominated by frontier, could compute deeper ranks if needed
                pareto_ranks[i] = 2

        return frontier_indices, dominated_map, pareto_ranks

    def _select_from_pareto_frontier(
        self,
        sounding_results: List[Dict],
        frontier_indices: List[int],
        quality_scores: List[float],
        costs: List[float],
        policy: str
    ) -> int:
        """
        Select winner from Pareto frontier based on policy.

        Args:
            sounding_results: List of candidate result dicts
            frontier_indices: Indices of frontier members
            quality_scores: Quality scores for all soundings
            costs: Costs for all soundings
            policy: Selection policy

        Returns:
            Index of selected winner
        """
        indent = "  " * self.depth

        if policy == "prefer_cheap":
            # Pick cheapest on frontier
            best_idx = min(frontier_indices, key=lambda i: costs[i])
            console.print(f"{indent}  [dim]Policy: prefer_cheap - selecting cheapest frontier member[/dim]")

        elif policy == "prefer_quality":
            # Pick highest quality on frontier
            best_idx = max(frontier_indices, key=lambda i: quality_scores[i])
            console.print(f"{indent}  [dim]Policy: prefer_quality - selecting highest quality frontier member[/dim]")

        elif policy == "balanced":
            # Maximize quality per dollar (quality / cost ratio)
            def quality_per_dollar(i):
                if costs[i] == 0:
                    return float('inf') if quality_scores[i] > 0 else 0
                return quality_scores[i] / costs[i]

            best_idx = max(frontier_indices, key=quality_per_dollar)
            console.print(f"{indent}  [dim]Policy: balanced - maximizing quality/cost ratio on frontier[/dim]")

        elif policy == "interactive":
            # Show options and prompt user (dev/research mode)
            console.print(f"\n{indent}[bold yellow]Pareto Frontier (non-dominated solutions):[/bold yellow]")
            for i, idx in enumerate(frontier_indices):
                model = sounding_results[idx].get("model", "unknown")
                quality = quality_scores[idx]
                cost = costs[idx]
                console.print(f"{indent}  [{i+1}] Model: {model}, Quality: {quality:.2f}, Cost: ${cost:.6f}")

            try:
                choice = int(input(f"{indent}Select winner (1-{len(frontier_indices)}): ")) - 1
                if 0 <= choice < len(frontier_indices):
                    best_idx = frontier_indices[choice]
                else:
                    best_idx = frontier_indices[0]
            except (ValueError, EOFError):
                # Fall back to balanced if interactive input fails
                best_idx = max(frontier_indices, key=lambda i: quality_scores[i] / costs[i] if costs[i] > 0 else 0)

        else:
            # Default to balanced
            best_idx = max(frontier_indices, key=lambda i: quality_scores[i] / costs[i] if costs[i] > 0 else 0)

        return best_idx

    def _get_quality_scores_from_evaluator(
        self,
        sounding_results: List[Dict],
        evaluator_instructions: str,
        evaluator_trace
    ) -> tuple:
        """
        Get quality scores for each candidate from the evaluator.

        Uses LLM to assign numeric quality scores to each candidate.

        Returns:
            Tuple of (
                List of quality scores (0-100 scale),
                evaluator response content,
                cost (float),
                tokens_in (int),
                tokens_out (int),
                request_id (str),
                model (str)
            )
        """
        indent = "  " * self.depth

        # Build prompt for quality scoring
        score_prompt = f"""{evaluator_instructions}

Rate each of the following attempts on a scale of 0-100 for quality.
Consider clarity, completeness, accuracy, and usefulness.

"""
        for i, candidate in enumerate(sounding_results):
            score_prompt += f"## Attempt {i+1}\n"
            # Include model info if available for multi-model comparison
            if candidate.get("model"):
                score_prompt += f"Model: {candidate['model']}\n"
            score_prompt += f"Result: {candidate['result']}\n\n"

        score_prompt += """
For each attempt, provide:
1. A brief assessment of its quality
2. A numeric score from 0-100

Respond with scores in this exact format:
Attempt 1: [score] - [brief reason]
Attempt 2: [score] - [brief reason]
...etc

Use only numbers 0-100 for scores."""

        # Create scoring agent
        scoring_agent = Agent(
            model=self.model,
            system_prompt="You are an expert evaluator. Rate each response objectively on a 0-100 scale. Provide brief reasoning for each score.",
            tools=[],
            base_url=self.base_url,
            api_key=self.api_key
        )

        # Get scores
        score_response = scoring_agent.run(score_prompt, context_messages=[])

        # Extract all response data (not just content!)
        score_content = score_response.get("content", "")
        score_cost = score_response.get("cost", 0.0)
        score_tokens_in = score_response.get("tokens_in", 0)
        score_tokens_out = score_response.get("tokens_out", 0)
        score_request_id = score_response.get("id")
        score_model = score_response.get("model", self.model)

        console.print(f"{indent}  [dim]Quality scores: {score_content[:200]}...[/dim]")

        # Parse scores from response
        import re
        scores = []
        pattern = r'Attempt\s*(\d+)\s*:\s*(\d+(?:\.\d+)?)'
        matches = re.findall(pattern, score_content, re.IGNORECASE)

        # Build score list in order
        score_map = {int(m[0]): float(m[1]) for m in matches}
        for i in range(len(sounding_results)):
            scores.append(score_map.get(i + 1, 50.0))  # Default to 50 if not found

        return scores, score_content, score_cost, score_tokens_in, score_tokens_out, score_request_id, score_model

    def _log_pareto_frontier(
        self,
        session_id: str,
        cell_name: str,
        sounding_results: List[Dict],
        frontier_indices: List[int],
        dominated_map: Dict[int, int],
        quality_scores: List[float],
        costs: List[float],
        winner_index: int
    ):
        """Log Pareto frontier data for visualization."""
        import json
        import os
        from .config import get_config

        config = get_config()
        graph_dir = config.graph_dir

        pareto_data = {
            "session_id": session_id,
            "cell_name": cell_name,
            "frontier": [
                {
                    "candidate_index": idx,
                    "model": sounding_results[idx].get("model", "unknown"),
                    "quality": quality_scores[idx],
                    "cost": costs[idx],
                    "is_winner": idx == winner_index
                }
                for idx in frontier_indices
            ],
            "dominated": [
                {
                    "candidate_index": idx,
                    "dominated_by": dom_idx,
                    "model": sounding_results[idx].get("model", "unknown"),
                    "quality": quality_scores[idx],
                    "cost": costs[idx]
                }
                for idx, dom_idx in dominated_map.items()
            ],
            "all_soundings": [
                {
                    "index": i,
                    "model": sr.get("model", "unknown"),
                    "quality": quality_scores[i],
                    "cost": costs[i],
                    "is_pareto_optimal": i in frontier_indices,
                    "is_winner": i == winner_index
                }
                for i, sr in enumerate(sounding_results)
            ]
        }

        # Write to pareto file
        pareto_file = os.path.join(graph_dir, f"pareto_{session_id}.json")
        os.makedirs(graph_dir, exist_ok=True)
        with open(pareto_file, "w") as f:
            json.dump(pareto_data, f, indent=2)

        console.print(f"  [dim]Pareto frontier data saved to: {pareto_file}[/dim]")

    def _execute_phase_with_soundings(self, phase: CellConfig, input_data: dict, trace: TraceNode, initial_injection: dict = None) -> Any:
        """
        Execute a phase with soundings (Tree of Thought).
        Spawns N parallel attempts, evaluates them, and returns only the winner.
        """
        from .unified_logs import log_unified

        indent = "  " * self.depth

        # Resolve soundings factor FIRST (may be Jinja2 template string)
        # Build context for rendering
        outputs = {item['cell']: item['output'] for item in self.echo.lineage}
        render_context = {
            "input": input_data,
            "state": self.echo.state,
            "history": self.echo.history,
            "outputs": outputs,
            "lineage": self.echo.lineage,
        }

        # Render factor if it's a string (Jinja2 template)
        if isinstance(phase.candidates.factor, str):
            from .prompts import render_instruction
            rendered_factor = render_instruction(phase.candidates.factor, render_context)
            try:
                resolved_factor = int(rendered_factor.strip())
            except ValueError:
                console.print(f"{indent}[red]⚠ Warning: Could not parse soundings factor '{rendered_factor}' as integer, defaulting to 1[/red]")
                resolved_factor = 1
        else:
            resolved_factor = phase.candidates.factor

        # Assign models using resolved factor
        assigned_models = self._assign_models(phase.candidates, resolved_factor)

        # Filter models by context window if multi-model soundings
        if phase.candidates.models and len(set(assigned_models)) > 1:
            filter_result = self._filter_models_by_context(
                models=assigned_models,
                cell=phase,
                input_data=input_data
            )

            # Show detailed per-model context check (dimmed)
            if filter_result["estimated_tokens"] > 0:
                console.print(f"{indent}  [dim]Context check: estimated {filter_result['estimated_tokens']:,} tokens (with buffer: {filter_result['required_tokens']:,})[/dim]")

                # Show each model's verdict
                unique_models_checked = list(dict.fromkeys(assigned_models))
                model_limits = filter_result.get("model_limits", {})

                for model in unique_models_checked:
                    filter_detail = filter_result["filter_details"].get(model)
                    if filter_detail:
                        # Model was filtered
                        console.print(
                            f"{indent}  [dim red]✗ {model}: {filter_detail['model_limit']:,} token limit "
                            f"(shortfall: {filter_detail['shortfall']:,})[/dim red]"
                        )
                    else:
                        # Model passed - show its limit if available
                        limit = model_limits.get(model)
                        if limit:
                            console.print(f"{indent}  [dim green]✓ {model}: {limit:,} token limit[/dim green]")
                        else:
                            console.print(f"{indent}  [dim green]✓ {model}: sufficient context[/dim green]")

            # Update assigned models with filtered list
            original_count = len(assigned_models)
            assigned_models = filter_result["viable_models"]
            filtered_count = len(filter_result["filtered_models"])

            # Emit event if any models were filtered
            if filtered_count > 0:
                console.print(
                    f"{indent}  [yellow]⚡ Filtered {filtered_count} model(s) with insufficient context[/yellow]"
                )

                # Log filtering event to unified logs and emit event
                from .events import get_event_bus, Event
                from datetime import datetime

                filter_event_data = {
                    "cell_name": phase.name,
                    "original_models": list(set(self._assign_models(phase.candidates))),
                    "filtered_models": filter_result["filtered_models"],
                    "viable_models": list(set(assigned_models)),
                    "filter_details": filter_result["filter_details"],
                    "estimated_tokens": filter_result["estimated_tokens"],
                    "required_tokens": filter_result["required_tokens"],
                    "buffer_factor": filter_result.get("buffer_factor", 1.15)
                }

                # Emit real-time event for UI observability
                event_bus = get_event_bus()
                event_bus.publish(Event(
                    type="models_filtered",
                    session_id=self.session_id,
                    timestamp=datetime.now().isoformat(),
                    data=filter_event_data
                ))

                # Log to unified logs for analytics
                from .unified_logs import log_unified
                log_unified(
                    session_id=self.session_id,
                    trace_id=trace.id,
                    parent_id=trace.parent_id,
                    node_type="model_filter",
                    role="system",
                    depth=self.depth,
                    cell_name=phase.name,
                    cascade_id=self.config.cascade_id,
                    content=f"Filtered {filtered_count} models with insufficient context",
                    metadata=filter_event_data
                )

        # When using dict-based models with per-model factors, the actual number of soundings
        # is determined by the model assignments, not the top-level factor
        if isinstance(phase.candidates.models, dict):
            factor = len(assigned_models)
            if resolved_factor != factor:
                console.print(f"{indent}[yellow]Note: Using {factor} soundings from per-model factors (top-level factor: {resolved_factor} ignored)[/yellow]")
        else:
            factor = resolved_factor

        console.print(f"{indent}[bold blue]🔱 Taking {factor} Soundings (Parallel Attempts)...[/bold blue]")

        # Create soundings trace node
        soundings_trace = trace.create_child("soundings", f"{phase.name}_soundings")

        # Add soundings structure to Echo for visualization (auto-logs via unified_logs)
        soundings_meta = {
            "cell_name": phase.name,
            "factor": factor,
            "has_reforge": phase.candidates.reforge is not None,
            "semantic_actor": "framework",
            "semantic_purpose": "lifecycle"
        }
        self.echo.add_history({
            "role": "structure",
            "content": f"Soundings: {phase.name}",
            "node_type": "soundings"
        }, trace_id=soundings_trace.id, parent_id=trace.id, node_type="soundings",
           metadata=soundings_meta)

        # Snapshot current context state (before any soundings)
        context_snapshot = self.context_messages.copy()
        echo_state_snapshot = self.echo.state.copy()
        echo_history_snapshot = self.echo.history.copy()
        echo_lineage_snapshot = self.echo.lineage.copy()

        # Store all candidate results
        sounding_results = []

        # Determine mutations to apply
        mutations_to_use = []
        mutation_mode = phase.candidates.mutation_mode  # "rewrite", "rewrite_free", "augment", or "approach"

        # Compute species hash ONLY for rewrite mode (for winner learning)
        # Species hash is used to compare similar prompt rewrites, not needed for other mutation modes
        phase_species_hash = None
        if mutation_mode == 'rewrite':
            phase_species_hash = compute_species_hash(phase.dict(), input_data)

        if phase.candidates.mutate:
            if phase.candidates.mutations:
                # Use custom mutations/templates
                mutations_to_use = phase.candidates.mutations
            elif mutation_mode in ("rewrite", "rewrite_free"):
                # Rewrite templates: LLM will rewrite the prompt using these instructions
                # These are META-instructions for how to transform the prompt
                # IMPORTANT: Templates must be task-agnostic (work for creative, analytical, coding, etc.)
                # "rewrite" mode learns from previous winners, "rewrite_free" is pure exploration
                mutations_to_use = [
                    "Rewrite this prompt to be more specific and detailed. Add concrete details while preserving the core intent.",
                    "Rewrite this prompt to be more concise and focused. Keep only what's essential, remove fluff.",
                    "Rewrite this prompt to be more evocative and engaging. Use vivid language and sensory details.",
                    "Rewrite this prompt to include specific constraints (length, format, style, or structure).",
                    "Rewrite this prompt to encourage a unique perspective or unconventional approach.",
                    "Rewrite this prompt to emphasize quality and polish. Ask for refined, polished output.",
                    "Rewrite this prompt to specify a particular tone or voice (e.g., professional, casual, dramatic).",
                    "Rewrite this prompt to ask for depth over breadth. Focus on exploring one aspect thoroughly.",
                ]
            elif mutation_mode == "augment":
                # Augment mutations: prepended to the prompt as-is
                # These are direct instruction additions that can be learned from
                # IMPORTANT: Templates must be task-agnostic (work for creative, analytical, coding, etc.)
                mutations_to_use = [
                    "Be thorough and comprehensive. Cover all important aspects.",
                    "Be concise and direct. Focus only on what's essential.",
                    "Be vivid and engaging. Use specific details and strong imagery.",
                    "Take an unexpected angle. Surprise with your approach.",
                    "Prioritize clarity above all else.",
                    "Show, don't tell. Use concrete examples.",
                    "Focus on the most impactful elements first.",
                    "Aim for polish and refinement in your response.",
                ]
            else:
                # Approach mutations: appended as thinking strategy hints (Tree of Thought)
                # These change HOW the agent thinks, not the prompt itself
                # IMPORTANT: Templates must be task-agnostic (work for creative, analytical, coding, etc.)
                mutations_to_use = [
                    "Approach this from an unexpected angle - subvert expectations.",
                    "Focus on the emotional or human element.",
                    "Prioritize boldness and confidence over hedging.",
                    "Go for maximum impact in minimum words.",
                    "Consider what would make this memorable or distinctive.",
                    "Optimize for simplicity and elegance.",
                    "Think about what's surprising or counterintuitive here.",
                    "Challenge the obvious interpretation - what's the deeper layer?"
                ]

        # Show which models will be used (already assigned earlier)
        console.print(f"{indent}  [dim]Models: {', '.join(set(assigned_models))}[/dim]")

        # Pre-create traces for all soundings (must be done sequentially for proper hierarchy)
        sounding_traces = []
        for i in range(factor):
            trace_node = soundings_trace.create_child("sounding_attempt", f"attempt_{i+1}")
            sounding_traces.append(trace_node)

        # Pre-compute mutations for all soundings (some need LLM calls)
        sounding_mutations = []
        for i in range(factor):
            mutation_template = None
            mutation_applied = None
            mutation_type = None

            if mutations_to_use and i > 0:  # First candidate (i=0) uses original prompt (baseline)
                mutation_template = mutations_to_use[(i - 1) % len(mutations_to_use)]
                mutation_type = mutation_mode

                if mutation_mode in ("rewrite", "rewrite_free"):
                    # For rewrite modes: use LLM to rewrite the prompt
                    console.print(f"{indent}  [dim]Pre-computing mutation {i+1}: rewriting prompt...[/dim]")
                    mutation_applied = self._rewrite_prompt_with_llm(
                        phase, input_data, mutation_template, soundings_trace,
                        mutation_mode=mutation_mode, species_hash=phase_species_hash
                    )
                else:
                    mutation_applied = mutation_template

            sounding_mutations.append({
                "template": mutation_template,
                "applied": mutation_applied,
                "type": mutation_type
            })

        # Parallel execution setup
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from .echo import Echo
        max_parallel = phase.candidates.max_parallel or 3
        max_workers = min(factor, max_parallel)
        console.print(f"{indent}  [dim]Parallel workers: {max_workers}[/dim]")

        # Define worker function that creates isolated runner with SAME session_id
        def run_single_sounding(i: int) -> dict:
            """Execute a single candidate with isolated state but same session for logging."""
            mutation_info = sounding_mutations[i]
            sounding_trace = sounding_traces[i]
            sounding_model = assigned_models[i]

            console.print(f"{indent}  [cyan]🌊 Sounding {i+1}/{factor}[/cyan]" +
                         (f" [yellow]🧬 {mutation_info['type']}[/yellow]" if mutation_info['type'] else " [dim](baseline)[/dim]") +
                         f" [dim]({sounding_model})[/dim]")

            # Emit sounding_start event for real-time UI tracking
            from .events import get_event_bus, Event
            from datetime import datetime
            event_bus = get_event_bus()
            event_bus.publish(Event(
                type="sounding_start",
                session_id=self.session_id,
                timestamp=datetime.now().isoformat(),
                data={
                    "cell_name": phase.name,
                    "candidate_index": i,
                    "trace_id": sounding_trace.id,
                    "model": sounding_model,
                    "factor": factor,
                    "mutation_type": mutation_info['type']
                }
            ))

            try:
                # Create isolated runner with SAME session_id (logs go to same session)
                sounding_runner = RVBBITRunner(
                    config_path=self.config_path,
                    session_id=self.session_id,  # SAME session_id - all logs go here
                    overrides=self.overrides,
                    depth=self.depth,
                    parent_trace=sounding_trace,
                    hooks=self.hooks,
                    candidate_index=i,
                    parent_session_id=self.parent_session_id
                )

                # Replace echo with fresh ISOLATED instance (bypasses SessionManager singleton)
                # Same session_id means logs still go to the same session in DB
                sounding_runner.echo = Echo(self.session_id, parent_session_id=self.parent_session_id)
                sounding_runner.echo.state = echo_state_snapshot.copy()
                sounding_runner.echo.history = echo_history_snapshot.copy()
                sounding_runner.echo.lineage = echo_lineage_snapshot.copy()

                # Copy context and model
                sounding_runner.context_messages = context_snapshot.copy()
                sounding_runner.model = sounding_model

                # Set candidate tracking state
                sounding_runner.current_phase_candidate_index = i
                sounding_runner._current_sounding_factor = factor  # For Jinja2 templates
                sounding_runner.current_mutation_applied = mutation_info['applied']
                sounding_runner.current_mutation_type = mutation_info['type']
                sounding_runner.current_mutation_template = mutation_info['template']

                # CRITICAL: Set context vars IN THIS THREAD (candidate thread)
                # Context vars are thread-local, must be set in each candidate thread
                session_token = set_current_session_id(sounding_runner.session_id)
                phase_token = set_current_cell_name(phase.name)
                cascade_token = set_current_cascade_id(sounding_runner.config.cascade_id)
                sounding_token = set_current_candidate_index(i)

                print(f"[Sounding {i}] Set context vars: session={sounding_runner.session_id}, cell={phase.name}, candidate_index={i}")

                # Execute the phase on isolated runner
                result = sounding_runner._execute_phase_internal(
                    phase, input_data, sounding_trace,
                    initial_injection=initial_injection,
                    mutation=mutation_info['applied'],
                    mutation_mode=mutation_mode
                )

                # Capture context generated during this candidate
                sounding_context = sounding_runner.context_messages[len(context_snapshot):]

                # Extract images for evaluator
                from .utils import extract_images_from_messages
                sounding_images = extract_images_from_messages(sounding_context)

                console.print(f"{indent}    [green]✓ Sounding {i+1} complete[/green]")

                # Create a preview of the result for UI display
                result_preview = str(result)[:500] if result else None

                # Emit sounding_complete event for real-time UI tracking
                event_bus.publish(Event(
                    type="sounding_complete",
                    session_id=self.session_id,
                    timestamp=datetime.now().isoformat(),
                    data={
                        "cell_name": phase.name,
                        "candidate_index": i,
                        "trace_id": sounding_trace.id,
                        "model": sounding_model,
                        "factor": factor,
                        "success": True,
                        "output": result_preview
                    }
                ))

                return {
                    "index": i,
                    "result": result,
                    "context": sounding_context,
                    "images": sounding_images,
                    "trace_id": sounding_trace.id,
                    "final_state": sounding_runner.echo.state.copy(),
                    "mutation_applied": mutation_info['applied'],
                    "mutation_type": mutation_info['type'],
                    "mutation_template": mutation_info['template'],
                    "model": sounding_model
                }

            except Exception as e:
                console.print(f"{indent}    [red]✗ Sounding {i+1} failed: {e}[/red]")

                # Emit sounding_complete event for real-time UI tracking (error case)
                event_bus.publish(Event(
                    type="sounding_complete",
                    session_id=self.session_id,
                    timestamp=datetime.now().isoformat(),
                    data={
                        "cell_name": phase.name,
                        "candidate_index": i,
                        "trace_id": sounding_trace.id,
                        "model": sounding_model,
                        "factor": factor,
                        "success": False,
                        "error": str(e)
                    }
                ))

                return {
                    "index": i,
                    "result": f"[ERROR: {str(e)}]",
                    "context": [],
                    "images": [],
                    "trace_id": sounding_trace.id,
                    "final_state": {},
                    "mutation_applied": mutation_info['applied'],
                    "mutation_type": mutation_info['type'],
                    "mutation_template": mutation_info['template'],
                    "model": sounding_model,
                    "failed": True,
                    "error": str(e)
                }

        # Execute soundings in parallel - all logs go to same session
        sounding_results = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(run_single_sounding, i): i for i in range(factor)}

            for future in as_completed(futures):
                result = future.result()
                sounding_results.append(result)

        # Sort results by index to maintain consistent ordering for evaluator
        sounding_results.sort(key=lambda x: x['index'])

        # Log errors after parallel completion
        for sr in sounding_results:
            if sr.get('failed'):
                log_message(self.session_id, "sounding_error", sr.get('error', 'Unknown error'),
                           trace_id=sr['trace_id'], parent_id=soundings_trace.id, node_type="sounding_error", depth=self.depth,
                           candidate_index=sr['index'], metadata={"cell_name": phase.name, "error": sr.get('error'), "model": sr.get('model')})

        # Clear mutation tracking
        self.current_mutation_applied = None
        self.current_mutation_type = None
        self.current_mutation_template = None

        # Reset to original snapshot before evaluation
        self.context_messages = context_snapshot.copy()
        self.echo.state = echo_state_snapshot.copy()
        self.echo.history = echo_history_snapshot.copy()
        self.echo.lineage = echo_lineage_snapshot.copy()

        # Pre-evaluation validation (if configured)
        # Filters out soundings that fail validation before sending to evaluator
        valid_sounding_results = sounding_results
        if phase.candidates.validator:
            validator_spec = phase.candidates.validator
            validator_display_name = _format_validator_name(validator_spec)
            console.print(f"{indent}[bold cyan]🔍 Pre-evaluation validation with '{validator_display_name}'...[/bold cyan]")

            validation_results = []
            for sr in sounding_results:
                result_content = str(sr.get("result", ""))
                validation = self._run_sounding_validator(
                    validator_spec,
                    result_content,
                    sr["index"],
                    soundings_trace
                )
                sr["validation"] = validation
                validation_results.append(validation)

                if validation["valid"]:
                    console.print(f"{indent}  [green]✓ Sounding {sr['index']+1}: VALID[/green] - {validation['reason'][:60]}...")
                else:
                    console.print(f"{indent}  [red]✗ Sounding {sr['index']+1}: INVALID[/red] - {validation['reason'][:60]}...")

            # Filter to only valid soundings
            valid_sounding_results = [sr for sr in sounding_results if sr.get("validation", {}).get("valid", True)]

            # Handle edge case: all soundings failed validation
            if not valid_sounding_results:
                console.print(f"{indent}[bold red]⚠️  All {len(sounding_results)} soundings failed validation![/bold red]")
                console.print(f"{indent}[yellow]Falling back to evaluating all soundings (validation results will be shown to evaluator)[/yellow]")
                # Fall back to all results, but evaluator will see validation info
                valid_sounding_results = sounding_results
            else:
                console.print(f"{indent}[bold green]✓ {len(valid_sounding_results)}/{len(sounding_results)} soundings passed validation[/bold green]")

        # AGGREGATE MODE: Combine all outputs instead of picking one winner
        if phase.candidates.mode == "aggregate":
            console.print(f"{indent}[bold cyan]📦 Aggregate mode: Combining {len(valid_sounding_results)} outputs...[/bold cyan]")

            # Update phase progress
            update_phase_progress(
                self.session_id, self.config.cascade_id, phase.name, self.depth,
                sounding_stage="aggregating"
            )

            # Gather all successful outputs
            all_outputs = []
            for sr in valid_sounding_results:
                output = str(sr.get("result", ""))
                if output.strip():
                    all_outputs.append({
                        "index": sr["index"],
                        "output": output,
                        "model": sr.get("model"),
                        "mutation_applied": sr.get("mutation_applied"),
                        "images": sr.get("images", []),
                    })

            if not all_outputs:
                raise ValueError("All candidate outputs were empty or failed")

            # Create aggregator trace
            aggregator_trace = soundings_trace.create_child("aggregator", "sounding_aggregation")

            # Aggregate the outputs
            if phase.candidates.aggregator_instructions:
                # Use LLM to aggregate/merge outputs
                console.print(f"{indent}  [dim]Using LLM aggregator...[/dim]")
                aggregated_output = self._aggregate_with_llm(
                    all_outputs,
                    phase.candidates.aggregator_instructions,
                    phase.candidates.aggregator_model or self.model,
                    aggregator_trace
                )
            else:
                # Simple concatenation
                console.print(f"{indent}  [dim]Simple concatenation of {len(all_outputs)} outputs[/dim]")
                aggregated_parts = []
                for o in all_outputs:
                    header = f"## Output {o['index']+1}"
                    if o.get('model'):
                        header += f" (Model: {o['model']})"
                    aggregated_parts.append(f"{header}\n{o['output']}")
                aggregated_output = "\n\n---\n\n".join(aggregated_parts)

            # Collect all images from all outputs
            all_images = []
            for o in all_outputs:
                all_images.extend(o.get("images", []))

            # Create synthetic "winner" with aggregated output
            # Use the first valid result's context as the base
            winner = valid_sounding_results[0].copy()
            winner["result"] = aggregated_output
            winner["is_aggregated"] = True
            winner["aggregated_count"] = len(all_outputs)
            winner["aggregated_indices"] = [o["index"] for o in all_outputs]  # Store which soundings contributed
            winner["images"] = all_images  # Combine all images
            winner_index = 0  # synthetic index

            console.print(f"{indent}[bold green]✓ Aggregated {len(all_outputs)} outputs[/bold green]")

            # Log aggregation to echo (for visualization)
            self.echo.add_history({
                "role": "aggregator",
                "content": f"Aggregated {len(all_outputs)} candidate outputs"
            }, trace_id=aggregator_trace.id, parent_id=soundings_trace.id, node_type="aggregator",
               metadata={
                   "cell_name": phase.name,
                   "aggregated_count": len(all_outputs),
                   "output_indices": [o["index"] for o in all_outputs],
                   "used_llm": phase.candidates.aggregator_instructions is not None,
                   "semantic_actor": "aggregator",
                   "semantic_purpose": "aggregation",
               })

            # Skip evaluation and jump to winner processing
            # Set variables needed by post-evaluation code
            eval_prompt = None
            eval_content = f"[Aggregate mode] Combined {len(all_outputs)} outputs"
            sounding_costs = None
            quality_scores = None
            frontier_indices = None
            dominated_map = None
            pareto_ranks = None
            use_cost_aware = False
            use_pareto = False
            use_human_eval = False
            use_hybrid_eval = False
            winner_already_set = True  # Flag to skip winner assignment below

            # Skip directly to winner processing (below)
        else:
            # Now evaluate soundings (only valid ones, unless all failed)
            # Update phase progress for evaluation stage
            update_phase_progress(
                self.session_id, self.config.cascade_id, phase.name, self.depth,
                sounding_stage="evaluating"
            )

            # Create evaluator trace
            evaluator_trace = soundings_trace.create_child("evaluator", "sounding_evaluation")

            # Check for human evaluation mode
            use_human_eval = phase.candidates.evaluator == "human"
            use_hybrid_eval = phase.candidates.evaluator == "hybrid"
            winner_already_set = False  # Evaluation will determine winner

        # Human evaluation: block for human to pick winner via UI
        if use_human_eval or use_hybrid_eval:
            # For hybrid: first do LLM prefilter, then human picks from top N
            eval_candidates = valid_sounding_results
            if use_hybrid_eval and phase.candidates.llm_prefilter:
                prefilter_n = phase.candidates.llm_prefilter
                console.print(f"{indent}[bold cyan]🔀 Hybrid mode: LLM prefiltering to top {prefilter_n}...[/bold cyan]")
                eval_candidates = self._llm_prefilter_soundings(
                    valid_sounding_results,
                    prefilter_n,
                    phase.candidates.llm_prefilter_instructions or phase.candidates.evaluator_instructions,
                    evaluator_trace
                )
                console.print(f"{indent}  [dim]Filtered to {len(eval_candidates)} candidates for human evaluation[/dim]")

            console.print(f"{indent}[bold yellow]👤 Human Evaluation: Waiting for human to pick winner...[/bold yellow]")

            # Get costs for each candidate from unified logs
            sounding_costs = self._get_sounding_costs(eval_candidates)

            # Build candidate outputs and metadata for the UI
            sounding_outputs = [str(sr.get("result", "")) for sr in eval_candidates]
            sounding_metadata = []
            for idx, sr in enumerate(eval_candidates):
                # Extract images from candidate results
                # Images are stored as (base64_data_url, description) tuples
                sounding_images = sr.get("images", [])
                image_urls = []
                for img_data in sounding_images:
                    if isinstance(img_data, tuple) and len(img_data) >= 1:
                        # First element is base64 data URL
                        image_urls.append(img_data[0])
                    elif isinstance(img_data, str):
                        # Direct data URL or path
                        image_urls.append(img_data)

                meta = {
                    "index": sr["index"],
                    "cost": sounding_costs[idx] if idx < len(sounding_costs) else None,
                    "tokens": None,  # Could extract from trace
                    "model": sr.get("model"),
                    "mutation_applied": sr.get("mutation_applied"),
                    "mutation_type": sr.get("mutation_type"),
                    "validation": sr.get("validation"),
                    "images": image_urls,
                }
                sounding_metadata.append(meta)

            # Build UI spec from human_eval config
            human_eval_config = phase.candidates.human_eval
            ui_spec = {
                "type": "sounding_comparison",
                "presentation": human_eval_config.presentation.value if human_eval_config else "side_by_side",
                "selection_mode": human_eval_config.selection_mode.value if human_eval_config else "pick_one",
                "attempts": [
                    {
                        "index": i,
                        "output": output,
                        "metadata": meta,
                    }
                    for i, (output, meta) in enumerate(zip(sounding_outputs, sounding_metadata))
                ],
                "options": {
                    "show_index": human_eval_config.show_index if human_eval_config else False,
                    "show_metadata": human_eval_config.show_metadata if human_eval_config else True,
                    "show_mutations": human_eval_config.show_mutations if human_eval_config else True,
                    "preview_render": human_eval_config.preview_render if human_eval_config else "auto",
                    "max_preview_length": human_eval_config.max_preview_length if human_eval_config else None,
                    "allow_reject_all": human_eval_config.allow_reject_all if human_eval_config else True,
                    "allow_tie": human_eval_config.allow_tie if human_eval_config else False,
                    "require_reasoning": human_eval_config.require_reasoning if human_eval_config else False,
                }
            }

            # Create checkpoint for human evaluation
            checkpoint_manager = get_checkpoint_manager()
            checkpoint = checkpoint_manager.create_checkpoint(
                session_id=self.session_id,
                cascade_id=self.config.cascade_id,
                cell_name=phase.name,
                checkpoint_type=CheckpointType.SOUNDING_EVAL,
                ui_spec=ui_spec,
                echo_snapshot=self.echo.get_full_echo(),
                phase_output=f"Comparing {len(eval_candidates)} candidate attempts",
                sounding_outputs=sounding_outputs,
                sounding_metadata=sounding_metadata,
                timeout_seconds=human_eval_config.timeout_seconds if human_eval_config else None
            )

            console.print(f"{indent}  [dim]Checkpoint created: {checkpoint.id[:12]}...[/dim]")
            console.print(f"{indent}  [bold]Open the RVBBIT UI to select a winner[/bold]")

            # Block until human responds
            response = checkpoint_manager.wait_for_response(
                checkpoint.id,
                timeout=human_eval_config.timeout_seconds if human_eval_config else None
            )

            if response is None:
                # Timeout or cancelled - handle based on config
                on_timeout = human_eval_config.on_timeout if human_eval_config else "llm_fallback"
                console.print(f"{indent}[yellow]⚠ Human evaluation timed out or cancelled[/yellow]")

                if on_timeout == "abort":
                    raise TimeoutError(f"Human evaluation timed out for checkpoint {checkpoint.id}")
                elif on_timeout == "random":
                    import random
                    winner_index = random.randint(0, len(eval_candidates) - 1)
                    eval_content = f"[Timeout: Random selection] Selected attempt {winner_index + 1}"
                    eval_prompt = f"[Human Evaluation Timeout] Random selection fallback"
                elif on_timeout == "first":
                    winner_index = 0
                    eval_content = f"[Timeout: First selection] Selected attempt 1"
                    eval_prompt = f"[Human Evaluation Timeout] First selection fallback"
                else:  # llm_fallback
                    console.print(f"{indent}[cyan]Falling back to LLM evaluation...[/cyan]")
                    # Fall through to LLM evaluation (handled below)
                    use_human_eval = False
                    use_hybrid_eval = False
            else:
                # Got human response
                if response.get("reject_all"):
                    # Human rejected all - could retry or abort
                    console.print(f"{indent}[yellow]⚠ Human rejected all soundings[/yellow]")
                    raise ValueError("Human rejected all candidate attempts")

                # Get winner index (relative to eval_candidates)
                relative_winner_index = response.get("winner_index", 0)

                # Map back to original index in valid_sounding_results
                winner_candidate = eval_candidates[relative_winner_index]
                winner_index = next(
                    i for i, sr in enumerate(valid_sounding_results)
                    if sr["index"] == winner_candidate["index"]
                )

                # Build eval_content and eval_prompt for logging
                reasoning = response.get("reasoning", "")
                eval_content = f"[Human selection] Selected attempt {winner_candidate['index'] + 1}"
                if reasoning:
                    eval_content += f"\nReasoning: {reasoning}"
                eval_prompt = f"[Human Evaluation] {len(eval_candidates)} soundings presented to human evaluator"

                console.print(f"{indent}[bold green]✓ Human selected: Sounding {winner_candidate['index'] + 1}[/bold green]")
                if reasoning:
                    console.print(f"{indent}  [dim]Reasoning: {reasoning[:100]}...[/dim]")

                # Log human evaluation for training data
                from .hotornot import log_preference_eval
                log_preference_eval(
                    session_id=self.session_id,
                    cell_name=phase.name,
                    preferred_index=winner_candidate["index"],
                    system_winner_index=-1,  # No system winner in pure human eval
                    sounding_outputs=[
                        {"index": sr["index"], "content": str(sr.get("result", "")), "metadata": sr}
                        for sr in eval_candidates
                    ],
                    cascade_id=self.config.cascade_id,
                    notes=reasoning,
                    metadata={
                        "evaluation_mode": "human" if use_human_eval else "hybrid",
                        "checkpoint_id": checkpoint.id,
                        "rankings": response.get("rankings"),
                        "ratings": response.get("ratings"),
                    }
                )

        # Initialize variables used in both human eval and LLM eval paths
        sounding_costs = None
        quality_scores = None
        frontier_indices = None
        dominated_map = None
        pareto_ranks = None
        eval_prompt = None  # Initialize for all paths (used in metadata logging)
        use_cost_aware = phase.candidates.cost_aware_evaluation and phase.candidates.cost_aware_evaluation.enabled
        use_pareto = phase.candidates.pareto_frontier and phase.candidates.pareto_frontier.enabled

        # Only run LLM evaluation if we didn't do human eval (or fell back from timeout)
        # Also skip if winner_already_set (aggregate mode)
        if not (use_human_eval or use_hybrid_eval or winner_already_set):
            console.print(f"{indent}[bold yellow]⚖️  Evaluating {len(valid_sounding_results)} soundings...[/bold yellow]")

            # Phase 3: Pareto Frontier Analysis
            if use_pareto:
                console.print(f"{indent}  [bold cyan]📊 Computing Pareto Frontier...[/bold cyan]")

                # Initialize eval_prompt for metadata logging (Pareto uses quality scoring, not traditional eval)
                eval_prompt = f"{phase.candidates.evaluator_instructions}\n\nPareto Frontier Analysis: Quality scoring + cost-based frontier computation."

                # Get costs
                console.print(f"{indent}  [dim]Gathering cost data...[/dim]")
                sounding_costs = self._get_sounding_costs(valid_sounding_results)
                for i, sr in enumerate(valid_sounding_results):
                    sr["cost"] = sounding_costs[i]
                console.print(f"{indent}  [dim]Costs: {', '.join(f'${c:.6f}' for c in sounding_costs)}[/dim]")

                # Get quality scores
                console.print(f"{indent}  [dim]Getting quality scores from evaluator...[/dim]")
                (quality_scores, evaluator_reasoning, eval_cost, eval_tokens_in,
                 eval_tokens_out, eval_request_id, eval_model) = self._get_quality_scores_from_evaluator(
                    valid_sounding_results,
                    phase.candidates.evaluator_instructions,
                    evaluator_trace
                )

                # Log evaluator LLM call to unified_logs (with full cost tracking)
                log_unified(
                    session_id=self.session_id,
                    parent_session_id=getattr(self, 'parent_session_id', None),
                    trace_id=evaluator_trace.id,
                    parent_id=soundings_trace.id,
                    node_type="evaluator",
                    role="assistant",
                    depth=self.depth,
                    cascade_id=self.config.cascade_id,
                    cascade_config=None,
                    content=evaluator_reasoning,
                    cell_name=phase.name,
                    model=eval_model,
                    tokens_in=eval_tokens_in,
                    tokens_out=eval_tokens_out,
                    cost=eval_cost,
                    duration_ms=0,  # Not tracked for evaluators
                    tool_name=None,
                    tool_args=None,
                    tool_result=None,
                    request_id=eval_request_id,
                )

                for i, sr in enumerate(valid_sounding_results):
                    sr["quality_score"] = quality_scores[i]
                console.print(f"{indent}  [dim]Qualities: {', '.join(f'{q:.1f}' for q in quality_scores)}[/dim]")

                # Compute Pareto frontier
                frontier_indices, dominated_map, pareto_ranks = self._compute_pareto_frontier(
                    valid_sounding_results, quality_scores, sounding_costs
                )

                # Store Pareto data in candidate results
                for i, sr in enumerate(valid_sounding_results):
                    sr["is_pareto_optimal"] = i in frontier_indices
                    sr["dominated_by"] = dominated_map.get(i)
                    sr["pareto_rank"] = pareto_ranks.get(i, 2)

                # Display frontier
                console.print(f"{indent}  [bold green]Pareto Frontier ({len(frontier_indices)} non-dominated solutions):[/bold green]")
                for idx in frontier_indices:
                    model = valid_sounding_results[idx].get("model", "unknown")
                    quality = quality_scores[idx]
                    cost = sounding_costs[idx]
                    console.print(f"{indent}    • Sounding {valid_sounding_results[idx]['index']+1} ({model}): Quality={quality:.1f}, Cost=${cost:.6f}")

                # Select winner from frontier
                winner_index = self._select_from_pareto_frontier(
                    valid_sounding_results,
                    frontier_indices,
                    quality_scores,
                    sounding_costs,
                    phase.candidates.pareto_frontier.policy
                )

                # Build comprehensive eval_content with quality reasoning + Pareto selection
                winner_model = valid_sounding_results[winner_index].get("model", "unknown")
                winner_quality = quality_scores[winner_index]
                winner_cost = sounding_costs[winner_index]

                eval_content = f"""## Quality Assessment

{evaluator_reasoning}

## Pareto Frontier Analysis

- **Frontier size:** {len(frontier_indices)} non-dominated solutions out of {len(valid_sounding_results)} total
- **Selection policy:** `{phase.candidates.pareto_frontier.policy}`
- **Winner:** Attempt {winner_index + 1} ({winner_model}) - Quality: {winner_quality:.1f}, Cost: ${winner_cost:.6f}

### Frontier Members:
"""
                for idx in frontier_indices:
                    model = valid_sounding_results[idx].get("model", "unknown")
                    quality = quality_scores[idx]
                    cost = sounding_costs[idx]
                    is_winner = "**WINNER**" if idx == winner_index else ""
                    eval_content += f"- Attempt {idx + 1} ({model}): Quality={quality:.1f}, Cost=${cost:.6f} {is_winner}\n"

                # Log Pareto data for visualization
                if phase.candidates.pareto_frontier.show_frontier:
                    self._log_pareto_frontier(
                        self.session_id,
                        phase.name,
                        valid_sounding_results,
                        frontier_indices,
                        dominated_map,
                        quality_scores,
                        sounding_costs,
                        winner_index
                    )

            # Phase 2: Cost-Aware Evaluation
            elif use_cost_aware:
                console.print(f"{indent}  [dim]Gathering cost data for cost-aware evaluation...[/dim]")
                sounding_costs = self._get_sounding_costs(valid_sounding_results)
                normalized_costs = self._normalize_costs(
                    sounding_costs,
                    phase.candidates.cost_aware_evaluation.cost_normalization
                )
                # Store costs in candidate results for logging
                for i, sr in enumerate(valid_sounding_results):
                    sr["cost"] = sounding_costs[i]
                    sr["normalized_cost"] = normalized_costs[i]

                # Build cost-aware evaluation prompt
                eval_prompt = self._build_cost_aware_eval_prompt(
                    valid_sounding_results,
                    sounding_costs,
                    phase.candidates,
                    phase.candidates.evaluator_instructions
                )
                console.print(f"{indent}  [dim]Costs: {', '.join(f'${c:.6f}' for c in sounding_costs)}[/dim]")

                # Check if any soundings have images for multi-modal evaluation
                any_images = any(candidate.get('images') for candidate in valid_sounding_results)
                eval_context_messages = []

                if any_images:
                    # Build multi-modal context messages with images
                    # Images are shown with clear attempt labels for association
                    for i, candidate in enumerate(valid_sounding_results):
                        sounding_images = candidate.get('images', [])
                        if sounding_images:
                            num_images = len(sounding_images)
                            attempt_content = [{
                                "type": "text",
                                "text": f"═══ ATTEMPT {i+1} VISUAL OUTPUT ({num_images} image{'s' if num_images > 1 else ''}) ═══"
                            }]
                            for img_idx, (img_data, desc) in enumerate(sounding_images):
                                attempt_content.append({
                                    "type": "image_url",
                                    "image_url": {"url": img_data}
                                })
                                attempt_content.append({
                                    "type": "text",
                                    "text": f"↑ Attempt {i+1}, Image {img_idx+1}/{num_images}"
                                })
                            eval_context_messages.append({
                                "role": "user",
                                "content": attempt_content
                            })
                    console.print(f"{indent}  [cyan]📸 Multi-modal evaluation: {sum(len(s.get('images', [])) for s in valid_sounding_results)} total images[/cyan]")

                # Create evaluator agent and run
                evaluator_agent = Agent(
                    model=self.model,
                    system_prompt="You are an expert evaluator. Your job is to compare multiple attempts and select the best one. If attempts include images, consider the visual quality and correctness as well.",
                    tools=[],
                    base_url=self.base_url,
                    api_key=self.api_key
                )
                eval_response = evaluator_agent.run(eval_prompt, context_messages=eval_context_messages)
                # Extract all response data for cost tracking
                eval_content = eval_response.get("content", "")
                eval_cost = eval_response.get("cost", 0.0)
                eval_tokens_in = eval_response.get("tokens_in", 0)
                eval_tokens_out = eval_response.get("tokens_out", 0)
                eval_request_id = eval_response.get("id")
                eval_model = eval_response.get("model", self.model)
                console.print(f"{indent}  [bold magenta]Evaluator:[/bold magenta] {eval_content[:200]}...")

                # Log evaluator LLM call to unified_logs (cost-aware path)
                log_unified(
                    session_id=self.session_id,
                    parent_session_id=getattr(self, 'parent_session_id', None),
                    trace_id=evaluator_trace.id,
                    parent_id=soundings_trace.id,
                    node_type="evaluator",
                    role="assistant",
                    depth=self.depth,
                    cascade_id=self.config.cascade_id,
                    cascade_config=None,
                    content=eval_content,
                    cell_name=phase.name,
                    model=eval_model,
                    tokens_in=eval_tokens_in,
                    tokens_out=eval_tokens_out,
                    cost=eval_cost,
                    duration_ms=0,
                    tool_name=None,
                    tool_args=None,
                    tool_result=None,
                    request_id=eval_request_id,
                )

                # Extract winner index
                winner_index = 0
                import re
                match = re.search(r'\b([1-9]\d*)\b', eval_content)
                if match:
                    winner_index = int(match.group(1)) - 1
                    if winner_index >= len(valid_sounding_results):
                        winner_index = 0

            # Phase 1: Standard quality-only evaluation
            else:
                eval_prompt = f"{phase.candidates.evaluator_instructions}\n\n"
                eval_prompt += "Please evaluate the following attempts and select the best one.\n\n"

                # Check if any soundings have images
                any_images = any(candidate.get('images') for candidate in valid_sounding_results)

                if any_images:
                    # Multi-modal evaluation: build context with images
                    # Each attempt gets its own message with clear labeling: text result + images together
                    eval_context_messages = []

                    for i, candidate in enumerate(valid_sounding_results):
                        sounding_images = candidate.get('images', [])
                        num_images = len(sounding_images)

                        # Build content block with clear attempt identification
                        header = f"═══════════════════════════════════════\n"
                        header += f"ATTEMPT {i+1} OF {len(valid_sounding_results)}\n"
                        header += f"═══════════════════════════════════════\n\n"
                        header += f"Text Result:\n{candidate['result']}"

                        if num_images > 0:
                            header += f"\n\n📸 Visual Output ({num_images} image{'s' if num_images > 1 else ''} follow):"

                        attempt_content = [{"type": "text", "text": header}]

                        # Add images immediately after the header (same message = clear association)
                        for img_idx, (img_data, desc) in enumerate(sounding_images):
                            attempt_content.append({
                                "type": "image_url",
                                "image_url": {"url": img_data}
                            })
                            # Add image label after each image for clarity
                            attempt_content.append({
                                "type": "text",
                                "text": f"↑ Attempt {i+1}, Image {img_idx+1}/{num_images}"
                            })

                        eval_context_messages.append({
                            "role": "user",
                            "content": attempt_content
                        })

                    # Add final evaluation instruction
                    eval_prompt += f"\n\nI've shown you {len(valid_sounding_results)} attempts above. Each attempt is clearly labeled with 'ATTEMPT N' followed by its text result and any images it produced. "
                    eval_prompt += f"Compare both the text quality AND visual output quality. "
                    eval_prompt += f"Respond with ONLY the number of the best attempt (1-{len(valid_sounding_results)}) and a brief explanation."

                    console.print(f"{indent}  [cyan]📸 Multi-modal evaluation: {sum(len(s.get('images', [])) for s in valid_sounding_results)} total images[/cyan]")
                else:
                    # Text-only evaluation (original behavior)
                    eval_context_messages = []
                    for i, candidate in enumerate(valid_sounding_results):
                        eval_prompt += f"## Attempt {i+1}\n"
                        eval_prompt += f"Result: {candidate['result']}\n\n"

                    eval_prompt += "\nRespond with ONLY the number of the best attempt (1-{0}) and a brief explanation.".format(len(valid_sounding_results))

                # Create evaluator agent and run
                evaluator_agent = Agent(
                    model=self.model,
                    system_prompt="You are an expert evaluator. Your job is to compare multiple attempts and select the best one. If attempts include images, consider the visual quality and correctness as well.",
                    tools=[],
                    base_url=self.base_url,
                    api_key=self.api_key
                )
                eval_response = evaluator_agent.run(eval_prompt, context_messages=eval_context_messages)
                # Extract all response data for cost tracking
                eval_content = eval_response.get("content", "")
                eval_cost = eval_response.get("cost", 0.0)
                eval_tokens_in = eval_response.get("tokens_in", 0)
                eval_tokens_out = eval_response.get("tokens_out", 0)
                eval_request_id = eval_response.get("id")
                eval_model = eval_response.get("model", self.model)
                console.print(f"{indent}  [bold magenta]Evaluator:[/bold magenta] {eval_content[:200]}...")

                # Log evaluator LLM call to unified_logs (quality-only path)
                log_unified(
                    session_id=self.session_id,
                    parent_session_id=getattr(self, 'parent_session_id', None),
                    trace_id=evaluator_trace.id,
                    parent_id=soundings_trace.id,
                    node_type="evaluator",
                    role="assistant",
                    depth=self.depth,
                    cascade_id=self.config.cascade_id,
                    cascade_config=None,
                    content=eval_content,
                    cell_name=phase.name,
                    model=eval_model,
                    tokens_in=eval_tokens_in,
                    tokens_out=eval_tokens_out,
                    cost=eval_cost,
                    duration_ms=0,
                    request_id=eval_request_id,
                )

                # Extract winner index
                winner_index = 0
                import re
                match = re.search(r'\b([1-9]\d*)\b', eval_content)
                if match:
                    winner_index = int(match.group(1)) - 1
                    if winner_index >= len(valid_sounding_results):
                        winner_index = 0

        # Get winner from valid_sounding_results (winner_index is relative to this filtered list)
        # Skip if winner was already set by aggregate mode
        if not winner_already_set:
            winner = valid_sounding_results[winner_index]

        # Display winner with original index for clarity
        if winner.get("is_aggregated"):
            console.print(f"{indent}[bold green]📦 Aggregated: {winner.get('aggregated_count', 0)} outputs combined[/bold green]")
        else:
            console.print(f"{indent}[bold green]🏆 Winner: Sounding {winner['index'] + 1}[/bold green]")

        # Now apply ONLY the winner's context to the main snowball
        self.context_messages = context_snapshot + winner['context']
        self.echo.state = winner['final_state']

        # Reset candidate index (no longer in candidate context)
        self.current_phase_candidate_index = None

        # Track original winner index for metadata logging
        # In aggregate mode, all valid soundings contribute (no single winner)
        is_aggregated = winner.get("is_aggregated", False)
        if is_aggregated:
            original_winner_index = -1  # Sentinel value for aggregate mode
            aggregated_indices = set(winner.get("aggregated_indices", []))
        else:
            original_winner_index = winner['index']
            aggregated_indices = set()

        # Emit sounding_winner event for real-time UI tracking
        from .events import get_event_bus, Event as WinnerEvent
        from datetime import datetime as dt_winner
        winner_event_bus = get_event_bus()
        winner_output = str(winner.get('result', ''))[:500] if winner.get('result') else None
        winner_event_bus.publish(WinnerEvent(
            type="sounding_winner",
            session_id=self.session_id,
            timestamp=dt_winner.now().isoformat(),
            data={
                "cell_name": phase.name,
                "winner_index": original_winner_index,
                "is_aggregated": is_aggregated,
                "aggregated_indices": list(aggregated_indices) if is_aggregated else None,
                "factor": factor,
                "output": winner_output
            }
        ))

        # Compute species hash for prompt evolution tracking (once for all soundings in this phase)
        # NOTE: This should match the species_hash computed at the start of soundings (line 3374)
        # We re-compute here instead of passing it through to avoid coupling
        phase_config_dict = phase.model_dump() if hasattr(phase, 'model_dump') else None
        phase_species_hash = compute_species_hash(phase_config_dict, input_data)

        # Add all candidate attempts to Echo history with metadata for visualization (auto-logs via unified_logs)
        for sr in sounding_results:
            # In aggregate mode, all contributing soundings are "winners"
            if is_aggregated:
                is_winner = sr["index"] in aggregated_indices
            else:
                is_winner = sr["index"] == original_winner_index
            sounding_metadata = {
                "cell_name": phase.name,
                "candidate_index": sr["index"],
                "is_winner": is_winner,
                "factor": factor,
                "mutation_applied": sr.get("mutation_applied"),  # Log what mutation was used
                "mutation_type": sr.get("mutation_type"),  # Log mutation type: rewrite, augment, approach
                "mutation_template": sr.get("mutation_template"),  # Log mutation template/instruction
                "model": sr.get("model"),  # Log which model was used (Phase 1: Multi-Model Soundings)
                "validation": sr.get("validation"),  # Log validation result if validator was used
                "species_hash": phase_species_hash,  # Track prompt template DNA for evolution analysis
            }
            # Add cost data if available (Phase 2: Cost-Aware Evaluation)
            if sr.get("cost") is not None:
                sounding_metadata["cost"] = sr["cost"]
                sounding_metadata["normalized_cost"] = sr.get("normalized_cost")
            # Add Pareto data if available (Phase 3: Pareto Frontier Analysis)
            if sr.get("quality_score") is not None:
                sounding_metadata["quality_score"] = sr["quality_score"]
            if sr.get("is_pareto_optimal") is not None:
                sounding_metadata["is_pareto_optimal"] = sr["is_pareto_optimal"]
                sounding_metadata["dominated_by"] = sr.get("dominated_by")
                sounding_metadata["pareto_rank"] = sr.get("pareto_rank")

            # Add semantic classification
            sounding_metadata["semantic_actor"] = "sounding_agent"
            sounding_metadata["semantic_purpose"] = "generation"

            self.echo.add_history({
                "role": "sounding_attempt",
                "content": str(sr["result"])[:200] if sr["result"] else "",
                "node_type": "sounding_attempt"
            }, trace_id=sr["trace_id"], parent_id=soundings_trace.id, node_type="sounding_attempt",
               metadata=sounding_metadata)

        # Log evaluator entry (skip in aggregate mode - there's no evaluator)
        if not is_aggregated:
            # Build evaluator input summary for observability
            # This captures exactly what the evaluator received for debugging
            evaluator_system_prompt = "You are an expert evaluator. Your job is to compare multiple attempts and select the best one. If attempts include images, consider the visual quality and correctness as well."

            # Build per-attempt summary
            attempt_summaries = []
            total_images_evaluated = 0
            for i, candidate in enumerate(valid_sounding_results):
                sounding_images = candidate.get('images', [])
                num_images = len(sounding_images)
                total_images_evaluated += num_images
                attempt_summaries.append({
                    "attempt_number": i + 1,
                    "original_candidate_index": candidate.get('index', i),
                    "has_images": num_images > 0,
                    "image_count": num_images,
                    "result_length": len(str(candidate.get('result', ''))) if candidate.get('result') else 0,
                    "model": candidate.get('model'),
                    "mutation_applied": candidate.get('mutation_applied'),
                    "validation": candidate.get('validation'),
                    "cost": candidate.get('cost'),
                })

            evaluator_input_summary = {
                "is_multimodal": total_images_evaluated > 0,
                "total_attempts_shown": len(valid_sounding_results),
                "total_soundings_run": len(sounding_results),
                "filtered_count": len(sounding_results) - len(valid_sounding_results),
                "total_images": total_images_evaluated,
                "attempts": attempt_summaries,
                "evaluation_mode": "cost_aware" if use_cost_aware else ("pareto" if use_pareto else "quality_only"),
            }

            # Add evaluator entry (auto-logs via unified_logs)
            evaluator_metadata = {
                "cell_name": phase.name,
                "winner_index": original_winner_index,  # Use original index for consistency
                "winner_trace_id": winner['trace_id'],
                "evaluation": eval_content,
                "model": self.model,
                "total_soundings": len(sounding_results),
                "valid_soundings": len(valid_sounding_results),
                # NEW: Full evaluator input observability
                "evaluator_prompt": eval_prompt,  # The full text prompt sent to evaluator
                "evaluator_system_prompt": evaluator_system_prompt,  # System prompt used
                "evaluator_input_summary": evaluator_input_summary,  # Structured summary of what was evaluated
            }
            # Add cost-aware evaluation info (Phase 2: Multi-Model Soundings)
            if use_cost_aware:
                evaluator_metadata["cost_aware"] = True
                evaluator_metadata["quality_weight"] = phase.candidates.cost_aware_evaluation.quality_weight
                evaluator_metadata["cost_weight"] = phase.candidates.cost_aware_evaluation.cost_weight
                if sounding_costs:
                    evaluator_metadata["sounding_costs"] = sounding_costs
                    evaluator_metadata["winner_cost"] = winner.get("cost")
            # Add Pareto frontier info (Phase 3: Pareto Frontier Analysis)
            if use_pareto:
                evaluator_metadata["pareto_enabled"] = True
                evaluator_metadata["pareto_policy"] = phase.candidates.pareto_frontier.policy
                evaluator_metadata["frontier_size"] = len(frontier_indices) if frontier_indices else 0
                if quality_scores:
                    evaluator_metadata["quality_scores"] = quality_scores
                    evaluator_metadata["winner_quality"] = winner.get("quality_score")
                if sounding_costs:
                    evaluator_metadata["sounding_costs"] = sounding_costs
                    evaluator_metadata["winner_cost"] = winner.get("cost")

            # Add semantic classification to evaluator metadata
            evaluator_metadata["semantic_actor"] = "evaluator"
            evaluator_metadata["semantic_purpose"] = "evaluation_output"

            # Skip auto-logging to unified_logs if we already logged directly
            # All evaluator paths now log via log_unified() for full cost tracking
            skip_auto_log = use_pareto or use_cost_aware or (not (use_human_eval or use_hybrid_eval or winner_already_set))

            self.echo.add_history({
                "role": "evaluator",
                "content": eval_content,  # Full content, no truncation
                "node_type": "evaluator"
            }, trace_id=evaluator_trace.id, parent_id=soundings_trace.id, node_type="evaluator",
               metadata=evaluator_metadata, skip_unified_log=skip_auto_log)

        # Add winning result to history
        # IMPORTANT: Include candidate_index and is_winner so UI can identify winning model
        if is_aggregated:
            # Aggregate mode: all contributing soundings are "winners"
            self.echo.add_history({
                "role": "soundings_result",
                "content": f"Aggregated {winner.get('aggregated_count', 0)} of {factor} attempts",
                "winner_index": -1,  # No single winner
                "evaluation": eval_content,
                "is_aggregated": True,
                "aggregated_indices": list(aggregated_indices)
            }, trace_id=soundings_trace.id, parent_id=trace.id, node_type="soundings_result",
               metadata={"cell_name": phase.name, "winner_index": -1, "factor": factor,
                         "is_aggregated": True, "aggregated_count": winner.get('aggregated_count', 0),
                         "aggregated_indices": list(aggregated_indices),
                         "semantic_actor": "framework", "semantic_purpose": "lifecycle"})

            # Mark all contributing soundings as winners in database
            from .unified_logs import mark_sounding_winner
            for idx in aggregated_indices:
                mark_sounding_winner(self.session_id, phase.name, idx)
        else:
            # Single winner mode
            self.echo.add_history({
                "role": "soundings_result",
                "content": f"Selected best of {factor} attempts",
                "winner_index": winner_index + 1,
                "evaluation": eval_content
            }, trace_id=soundings_trace.id, parent_id=trace.id, node_type="soundings_result",
               metadata={"cell_name": phase.name, "winner_index": winner_index, "factor": factor,
                         "candidate_index": original_winner_index, "is_winner": True,
                         "model": winner.get('model'),  # Track winning model for UI highlighting
                         "semantic_actor": "framework", "semantic_purpose": "lifecycle"})

            # Mark winning candidate in database for prompt evolution learning
            # This updates all rows in the winning candidate thread with is_winner=True
            # so _fetch_winning_mutations() can find them for rewrite mode learning
            from .unified_logs import mark_sounding_winner
            mark_sounding_winner(self.session_id, phase.name, original_winner_index)

        self._update_graph()

        # Check if reforge is configured
        if phase.candidates.reforge:
            # Reforge doesn't make sense in aggregate mode (no single winner to refine)
            if is_aggregated:
                console.print(f"{indent}[yellow]⚠️  Reforge skipped: Not compatible with aggregate mode[/yellow]")
            else:
                # Track which candidate won so reforge messages can reference it
                self.current_winning_candidate_index = original_winner_index

                winner = self._reforge_winner(
                    winner=winner,
                    cell=phase,
                    input_data=input_data,
                    trace=soundings_trace,
                    context_snapshot=context_snapshot,
                    reforge_step=0  # Initial soundings = step 0
                )

                # Reset after reforge completes
                self.current_winning_candidate_index = None

        return winner['result']

    def _get_mutation_prompt(self, step: int) -> str:
        """
        Built-in mutation strategies for prompt variation.
        Returns a mutation instruction based on the step number.
        """
        mutations = [
            "Approach this from a contrarian perspective. Challenge conventional assumptions.",
            "Focus on edge cases and uncommon scenarios that others might miss.",
            "Emphasize practical, immediately actionable implementations.",
            "Take a first-principles approach. Question every assumption and rebuild from basics.",
            "Consider the user experience and human factors above all else.",
            "Optimize for simplicity and elegance over complexity.",
            "Think about scalability and long-term maintenance.",
            "Adopt a devil's advocate mindset. What could go wrong?",
        ]
        # Cycle through mutations
        return mutations[step % len(mutations)]

    def _save_images_from_messages(self, messages: list, cell_name: str):
        """
        Auto-save images from RECEIVED messages only (assistant, tool roles).
        Skips user-role messages (sent/injection messages) to avoid duplicates.
        Tool result images are already saved explicitly when received.
        """
        from .utils import get_image_save_path, decode_and_save_image, get_next_image_index
        import re

        indent = "  " * self.depth
        images_to_save = []

        for msg in messages:
            role = msg.get("role", "")
            # Only save from received messages (assistant, tool), not sent (user)
            if role == "user":
                continue

            content = msg.get("content")

            # Handle multi-modal content (array format)
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "image_url":
                        image_url = item.get("image_url", {})
                        url = image_url.get("url", "") if isinstance(image_url, dict) else image_url
                        if url.startswith("data:"):
                            images_to_save.append((url, item.get("description", "image")))

            # Handle string content with embedded base64
            elif isinstance(content, str):
                data_url_pattern = r'data:image/[^;]+;base64,[A-Za-z0-9+/=]+'
                matches = re.findall(data_url_pattern, content)
                for match in matches:
                    images_to_save.append((match, "embedded_image"))

        if images_to_save:
            next_idx = get_next_image_index(self.session_id, cell_name)

            for i, (img_data, desc) in enumerate(images_to_save):
                save_path = get_image_save_path(
                    self.session_id,
                    cell_name,
                    next_idx + i,
                    extension='png'
                )

                if not os.path.exists(save_path):
                    try:
                        decode_and_save_image(img_data, save_path)
                        console.print(f"{indent}    [dim]💾 Saved image: {save_path}[/dim]")
                        self._maybe_render_image_to_console(save_path, indent)
                    except Exception as e:
                        console.print(f"{indent}    [dim yellow]⚠️  Failed to save image: {e}[/dim yellow]")

    def _maybe_render_image_to_console(self, image_path: str, indent: str = ""):
        """Render image to console if enabled and terminal supports it."""
        # Check env var / config
        if not os.environ.get("RVBBIT_SHOW_CLI_IMAGES", "true").lower() in ("true", "1"):
            return

        # Check if stdout is a TTY
        if not sys.stdout.isatty():
            return

        try:
            from .terminal_image import render_image_in_terminal
            console.print(f"{indent}    [dim cyan]👁️  Rendering image:[/dim cyan]")
            render_image_in_terminal(image_path, max_width=80)
            console.print(f"{indent}    [dim]{'─' * 60}[/dim]")
        except Exception as e:
            # Silently fail - don't break execution
            pass

    def _build_context_with_images(self, winner_context: list, refinement_instructions: str) -> list:
        """
        Build refinement context messages that include re-encoded images.
        Extracts images from winner's context, re-encodes them, and injects into new context.
        """
        from .utils import extract_images_from_messages

        # Start with system/user messages for refinement
        context_messages = []

        # Add refinement instructions as user message
        context_messages.append({
            "role": "user",
            "content": refinement_instructions
        })

        # Check if winner's context contains images
        images = extract_images_from_messages(winner_context)

        if images:
            # Re-encode and inject images
            content_block = [{"type": "text", "text": "Context images from previous output:"}]

            for img_data, desc in images:
                # Image is already base64, just add to content
                content_block.append({
                    "type": "image_url",
                    "image_url": {"url": img_data}
                })

            context_messages.append({
                "role": "user",
                "content": content_block
            })

        return context_messages

    def _reforge_winner(self, winner: dict, cell: CellConfig, input_data: dict, trace: TraceNode,
                        context_snapshot: list, reforge_step: int) -> dict:
        """
        Reforge (refine) the winning output through iterative soundings.
        Each step runs mini-soundings with honing prompt to progressively improve quality.
        """
        indent = "  " * self.depth
        reforge_config = cell.candidates.reforge
        current_output = winner['result']
        original_instructions = cell.instructions

        for step in range(1, reforge_config.steps + 1):
            # Set current reforge step for metadata tagging
            self.current_reforge_step = step

            console.print(f"{indent}[bold cyan]🔨 Reforge Step {step}/{reforge_config.steps}[/bold cyan]")

            # Create reforge trace
            reforge_trace = trace.create_child("reforge", f"reforge_step_{step}")

            # Build refinement instructions
            refinement_instructions = f"""Original intent: {original_instructions}

Current best output: {current_output}

Refinement directive: {reforge_config.honing_prompt}
"""

            # Apply mutation if configured
            if reforge_config.mutate:
                mutation_prompt = self._get_mutation_prompt(step - 1)
                refinement_instructions += f"\n\nVariation strategy: {mutation_prompt}"
                console.print(f"{indent}  [yellow]🧬 Mutation applied: {mutation_prompt[:60]}...[/yellow]")

            # Log reforge start
            log_message(self.session_id, "reforge_start", f"Reforge step {step} with factor {reforge_config.factor_per_step}",
                       {"honing_prompt": reforge_config.honing_prompt},
                       trace_id=reforge_trace.id, parent_id=trace.id, node_type="reforge", depth=self.depth,
                       reforge_step=step)

            # Add to echo history for visualization
            self.echo.add_history({
                "role": "reforge_step",
                "content": f"🔨 Reforge Step {step}/{reforge_config.steps}",
                "node_type": "reforge_step"
            }, trace_id=reforge_trace.id, parent_id=trace.id, node_type="reforge_step",
               metadata={
                   "cell_name": cell.name,
                   "reforge_step": step,
                   "total_steps": reforge_config.steps,
                   "factor_per_step": reforge_config.factor_per_step,
                   "has_mutation": reforge_config.mutate,
                   "semantic_actor": "framework",
                   "semantic_purpose": "lifecycle"
               })

            # Create temporary phase config for refinement
            # Use a modified phase with refinement instructions
            from copy import deepcopy
            refine_phase = deepcopy(cell)
            refine_phase.instructions = refinement_instructions

            # Snapshot state before reforge soundings
            echo_state_snapshot = self.echo.state.copy()
            echo_history_snapshot = self.echo.history.copy()
            echo_lineage_snapshot = self.echo.lineage.copy()

            # Build context with images if present
            refinement_context_messages = self._build_context_with_images(winner['context'], refinement_instructions)

            # Build full reforge context (shared across all refinements)
            full_reforge_context = context_snapshot.copy() + refinement_context_messages

            # Parallel execution setup for reforge
            from concurrent.futures import ThreadPoolExecutor, as_completed
            from .echo import Echo
            factor_per_step = reforge_config.factor_per_step
            max_parallel = cell.candidates.max_parallel or 3
            max_workers = min(factor_per_step, max_parallel)
            console.print(f"{indent}    [dim]Parallel workers: {max_workers}[/dim]")

            # Pre-create traces for all refinements
            refinement_traces = []
            for i in range(factor_per_step):
                refinement_trace = reforge_trace.create_child("refinement_attempt", f"attempt_{i+1}")
                refinement_traces.append(refinement_trace)

            # Define worker function that creates isolated runner with SAME session_id
            def run_single_refinement(i: int) -> dict:
                """Execute a single refinement with isolated state but same session for logging."""
                refinement_trace = refinement_traces[i]

                console.print(f"{indent}    [cyan]🔨 Refinement {i+1}/{factor_per_step}[/cyan]")

                try:
                    # Create isolated runner with SAME session_id (logs go to same session)
                    refinement_runner = RVBBITRunner(
                        config_path=self.config_path,
                        session_id=self.session_id,  # SAME session_id - all logs go here
                        overrides=self.overrides,
                        depth=self.depth,
                        parent_trace=refinement_trace,
                        hooks=self.hooks,
                        candidate_index=i,
                        parent_session_id=self.parent_session_id
                    )

                    # Replace echo with fresh ISOLATED instance (bypasses SessionManager singleton)
                    refinement_runner.echo = Echo(self.session_id, parent_session_id=self.parent_session_id)
                    refinement_runner.echo.state = echo_state_snapshot.copy()
                    refinement_runner.echo.history = echo_history_snapshot.copy()
                    refinement_runner.echo.lineage = echo_lineage_snapshot.copy()

                    # Copy context
                    refinement_runner.context_messages = context_snapshot.copy()

                    # Set tracking state
                    refinement_runner.current_phase_candidate_index = i
                    refinement_runner._current_sounding_factor = factor_per_step  # For Jinja2 templates
                    refinement_runner.current_reforge_step = step

                    # Execute the phase on isolated runner
                    result = refinement_runner._execute_phase_internal(
                        refine_phase, input_data, refinement_trace,
                        pre_built_context=full_reforge_context
                    )

                    # Capture refined context
                    refinement_context = refinement_runner.context_messages[len(context_snapshot):]

                    # Extract images from this reforge attempt for evaluator
                    from .utils import extract_images_from_messages
                    reforge_images = extract_images_from_messages(refinement_context)

                    console.print(f"{indent}      [green]✓ Refinement {i+1} complete[/green]")

                    return {
                        "index": i,
                        "result": result,
                        "context": refinement_context,
                        "images": reforge_images,
                        "trace_id": refinement_trace.id,
                        "final_state": refinement_runner.echo.state.copy()
                    }

                except Exception as e:
                    console.print(f"{indent}      [red]✗ Refinement {i+1} failed: {e}[/red]")
                    log_message(self.session_id, "refinement_error", str(e),
                               trace_id=refinement_trace.id, parent_id=reforge_trace.id,
                               node_type="error", depth=self.depth, reforge_step=step)
                    return {
                        "index": i,
                        "result": f"[ERROR: {str(e)}]",
                        "context": [],
                        "images": [],
                        "trace_id": refinement_trace.id,
                        "final_state": {},
                        "failed": True,
                        "error": str(e)
                    }

            # Execute refinements in parallel - all logs go to same session
            reforge_results = []
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(run_single_refinement, i): i for i in range(factor_per_step)}

                for future in as_completed(futures):
                    result = future.result()
                    reforge_results.append(result)

            # Sort results by index to maintain consistent ordering for evaluator
            reforge_results.sort(key=lambda x: x['index'])

            # Reset to snapshot before evaluation
            self.context_messages = context_snapshot.copy()
            self.echo.state = echo_state_snapshot.copy()
            self.echo.history = echo_history_snapshot.copy()
            self.echo.lineage = echo_lineage_snapshot.copy()

            # Re-add reforge attempt entries for visualization (they were wiped by reset)
            for i, refinement in enumerate(reforge_results):
                self.echo.add_history({
                    "role": "reforge_attempt",
                    "content": str(refinement['result'])[:150] if refinement['result'] else "Completed",
                    "node_type": "reforge_attempt"
                }, trace_id=refinement['trace_id'], parent_id=reforge_trace.id, node_type="reforge_attempt",
                   metadata={
                       "cell_name": cell.name,
                       "reforge_step": step,
                       "attempt_index": i,
                       "is_winner": False,
                       "semantic_actor": "reforge_agent",
                       "semantic_purpose": "generation"
                   })

            # Evaluate refinements
            console.print(f"{indent}    [bold yellow]⚖️  Evaluating refinements...[/bold yellow]")

            evaluator_trace = reforge_trace.create_child("evaluator", "reforge_evaluation")

            # Use custom evaluator or default
            eval_instructions = reforge_config.evaluator_override or cell.candidates.evaluator_instructions

            eval_prompt = f"{eval_instructions}\n\n"
            eval_prompt += "Please evaluate the following refinements and select the best one.\n\n"

            # Check if any refinements have images (multi-modal evaluation like soundings)
            any_images = any(refinement.get('images') for refinement in reforge_results)

            if any_images:
                # Multi-modal evaluation: build context with images
                # Each refinement gets its own message with clear labeling: text result + images together
                eval_context_messages = []

                for i, refinement in enumerate(reforge_results):
                    refinement_images = refinement.get('images', [])
                    num_images = len(refinement_images)

                    # Build content block with clear refinement identification
                    header = f"═══════════════════════════════════════\n"
                    header += f"REFINEMENT {i+1} OF {len(reforge_results)}\n"
                    header += f"═══════════════════════════════════════\n\n"
                    header += f"Text Result:\n{refinement['result']}"

                    if num_images > 0:
                        header += f"\n\n📸 Visual Output ({num_images} image{'s' if num_images > 1 else ''} follow):"

                    refinement_content = [{"type": "text", "text": header}]

                    # Add images immediately after the header (same message = clear association)
                    for img_idx, (img_data, desc) in enumerate(refinement_images):
                        refinement_content.append({
                            "type": "image_url",
                            "image_url": {"url": img_data}
                        })
                        # Add image label after each image for clarity
                        refinement_content.append({
                            "type": "text",
                            "text": f"↑ Refinement {i+1}, Image {img_idx+1}/{num_images}"
                        })

                    eval_context_messages.append({
                        "role": "user",
                        "content": refinement_content
                    })

                # Add final evaluation instruction for multi-modal
                eval_prompt += f"\n\nI've shown you {len(reforge_results)} refinements above. Each refinement is clearly labeled with 'REFINEMENT N' followed by its text result and any images it produced. "
                eval_prompt += f"Compare both the text quality AND visual output quality. "
                eval_prompt += f"Respond with ONLY the number of the best refinement (1-{len(reforge_results)}) and a brief explanation."

                console.print(f"{indent}    [cyan]📸 Multi-modal reforge evaluation: {sum(len(r.get('images', [])) for r in reforge_results)} total images[/cyan]")
            else:
                # Text-only evaluation (original behavior)
                eval_context_messages = []
                for i, refinement in enumerate(reforge_results):
                    eval_prompt += f"## Refinement {i+1}\n"
                    eval_prompt += f"Result: {refinement['result']}\n\n"

                eval_prompt += f"\nRespond with ONLY the number of the best refinement (1-{len(reforge_results)}) and a brief explanation."

            evaluator_agent = Agent(
                model=self.model,
                system_prompt="You are an expert evaluator. Your job is to select the best refined version. If refinements include images, consider the visual quality and correctness as well.",
                tools=[],
                base_url=self.base_url,
                api_key=self.api_key
            )

            eval_response = evaluator_agent.run(eval_prompt, context_messages=eval_context_messages)
            eval_content = eval_response.get("content", "")

            console.print(f"{indent}    [bold magenta]Evaluator:[/bold magenta] {eval_content[:150]}...")

            # Log with cost data from the evaluator LLM call
            eval_model = eval_response.get("model", self.model)
            eval_cost = eval_response.get("cost")
            eval_tokens_in = eval_response.get("tokens_in", 0)
            eval_tokens_out = eval_response.get("tokens_out", 0)
            eval_request_id = eval_response.get("id")

            log_message(self.session_id, "reforge_evaluation", eval_content,
                       trace_id=evaluator_trace.id, parent_id=reforge_trace.id,
                       node_type="reforge_evaluator", depth=self.depth, reforge_step=step,
                       model=eval_model, cost=eval_cost, tokens_in=eval_tokens_in,
                       tokens_out=eval_tokens_out, request_id=eval_request_id,
                       cell_name=cell.name)

            # Build evaluator input summary for observability (like soundings)
            total_images_evaluated = sum(len(r.get('images', [])) for r in reforge_results)
            refinement_summaries = []
            for i, refinement in enumerate(reforge_results):
                refinement_images = refinement.get('images', [])
                refinement_summaries.append({
                    "index": i,
                    "result_preview": str(refinement.get('result', ''))[:200] + "..." if len(str(refinement.get('result', ''))) > 200 else str(refinement.get('result', '')),
                    "image_count": len(refinement_images),
                    "has_images": len(refinement_images) > 0,
                })

            evaluator_input_summary = {
                "is_multimodal": total_images_evaluated > 0,
                "total_refinements": len(reforge_results),
                "total_images": total_images_evaluated,
                "refinements": refinement_summaries,
                "reforge_step": step,
                "total_steps": reforge_config.steps,
            }

            # Add evaluator to echo history for visualization
            self.echo.add_history({
                "role": "reforge_evaluator",
                "content": eval_content if eval_content else "Evaluating...",  # Full content, no truncation
                "node_type": "reforge_evaluator"
            }, trace_id=evaluator_trace.id, parent_id=reforge_trace.id, node_type="reforge_evaluator",
               metadata=self._get_metadata({
                   "cell_name": cell.name,
                   "reforge_step": step,
                   "evaluator_prompt": eval_prompt,
                   "evaluator_system_prompt": "You are an expert evaluator. Your job is to select the best refined version. If refinements include images, consider the visual quality and correctness as well.",
                   "evaluator_input_summary": evaluator_input_summary,
               }, semantic_actor="evaluator", semantic_purpose="evaluation_output"))

            # Extract winner
            import re
            winner_index = 0
            match = re.search(r'\b([1-9]\d*)\b', eval_content)
            if match:
                winner_index = int(match.group(1)) - 1
                if winner_index >= len(reforge_results):
                    winner_index = 0

            refined_winner = reforge_results[winner_index]

            console.print(f"{indent}    [bold green]🏆 Best Refinement: #{winner_index + 1}[/bold green]")

            log_message(self.session_id, "reforge_winner", f"Selected refinement {winner_index + 1}",
                       {"winner_trace_id": refined_winner['trace_id'], "evaluation": eval_content},
                       trace_id=reforge_trace.id, parent_id=trace.id, node_type="reforge_winner",
                       depth=self.depth, reforge_step=step, is_winner=True)

            # Add winner to echo history for visualization
            self.echo.add_history({
                "role": "reforge_winner",
                "content": f"🏆 Step {step} Winner: #{winner_index + 1}",
                "node_type": "reforge_winner"
            }, trace_id=reforge_trace.id, parent_id=trace.id, node_type="reforge_winner",
               metadata={
                   "cell_name": cell.name,
                   "reforge_step": step,
                   "winner_index": winner_index,
                   "total_steps": reforge_config.steps,
                   "semantic_actor": "framework",
                   "semantic_purpose": "lifecycle"
               })

            # Mark reforge winner in database for prompt evolution learning
            from .unified_logs import mark_sounding_winner
            mark_sounding_winner(self.session_id, cell.name, winner_index)

            # Check threshold ward if configured
            if reforge_config.threshold:
                console.print(f"{indent}    [cyan]🛡️  Checking reforge threshold...[/cyan]")

                threshold_result = self._run_ward(
                    reforge_config.threshold,
                    refined_winner['result'],
                    reforge_trace,
                    ward_type="threshold"
                )

                if threshold_result['valid']:
                    console.print(f"{indent}    [bold green]✨ Threshold met! Stopping reforge early at step {step}[/bold green]")
                    log_message(self.session_id, "reforge_threshold_met",
                               f"Threshold satisfied at step {step}/{reforge_config.steps}",
                               {"reason": threshold_result['reason']},
                               trace_id=reforge_trace.id, parent_id=trace.id,
                               node_type="threshold", depth=self.depth, reforge_step=step)

                    # Update winner and break early
                    winner = refined_winner
                    current_output = refined_winner['result']
                    break

            # Update current output for next iteration
            current_output = refined_winner['result']
            winner = refined_winner

        # Reset candidate index and reforge step after reforge completes
        self.current_phase_candidate_index = None
        self.current_reforge_step = None

        # Apply final winner's context
        self.context_messages = context_snapshot + winner['context']
        self.echo.state = winner['final_state']

        console.print(f"{indent}[bold green]🔨 Reforge Complete[/bold green]")

        return winner

    def execute_phase(self, phase: CellConfig, input_data: dict, trace: TraceNode, initial_injection: dict = None) -> Any:
        import asyncio

        # ─────────────────────────────────────────────────────────────────────
        # Browser lifecycle management
        # ─────────────────────────────────────────────────────────────────────
        browser_session: Optional[BrowserSession] = None

        if phase.browser:
            # Set up browser session for this phase
            browser_session = self._setup_browser_session(phase, input_data, trace)

        try:
            # Check if SQL-native mapping phase (for_each_row)
            if phase.for_each_row:
                return self._execute_sql_mapping_phase(phase, input_data, trace)

            # Check if this is a deterministic (tool-based) phase
            if phase.is_deterministic():
                return self._execute_deterministic_phase(phase, input_data, trace)

            # Check if this is an image generation phase (uses image model like FLUX, SDXL)
            phase_model = phase.model or self.model
            if Agent.is_image_generation_model(phase_model):
                return self._execute_image_generation_phase(phase, input_data, trace)

            # Check if soundings (Tree of Thought) is enabled
            if phase.candidates and (isinstance(phase.candidates.factor, str) or phase.candidates.factor > 1):
                return self._execute_phase_with_soundings(phase, input_data, trace, initial_injection)

            return self._execute_phase_internal(phase, input_data, trace, initial_injection)

        except Exception as e:
            # Log uncaught phase errors to unified logs
            # (Note: Turn-loop errors and deterministic errors are already logged in their respective methods)
            from .unified_logs import log_unified
            import traceback
            import time

            error_type = type(e).__name__
            error_msg = str(e)
            # Use enhanced message if available (from agent.py error extraction)
            enhanced_msg = getattr(e, 'enhanced_message', None)
            display_msg = enhanced_msg or error_msg
            error_tb = traceback.format_exc()

            # Log to unified logs with full context
            log_unified(
                session_id=self.session_id,
                trace_id=trace.id,
                parent_id=trace.parent_id,
                parent_session_id=self.parent_session_id,
                node_type="phase_error",
                role="error",
                depth=self.depth,
                cascade_id=self.config.cascade_id,
                cell_name=phase.name,
                phase_config=phase.dict() if hasattr(phase, 'dict') else None,
                content=f"{error_type}: {display_msg}\n\nTraceback:\n{error_tb}",
                metadata={
                    "error_type": error_type,
                    "error_message": display_msg,
                    "cell_name": phase.name,
                    "phase_type": "deterministic" if phase.is_deterministic() else "llm",
                    "has_soundings": phase.candidates is not None and (isinstance(phase.candidates.factor, str) or phase.candidates.factor > 1) if phase.candidates else False,
                }
            )

            # Add to echo for cascade-level error tracking
            self.echo.add_error(
                cell=phase.name,
                error_type=error_type,
                error_message=error_msg
            )

            # Re-raise to let cascade-level handler process it
            raise

        finally:
            # Clean up browser session
            if browser_session:
                self._teardown_browser_session(browser_session, phase)

    def _setup_browser_session(self, phase: CellConfig, input_data: dict, trace: TraceNode) -> Optional[BrowserSession]:
        """
        Set up a browser session for a phase with browser config.

        Spawns a dedicated Rabbitize subprocess, initializes the browser,
        and stores session info in echo.state for tools to access.
        """
        import asyncio
        from .prompts import render_instruction

        indent = "  " * self.depth
        console.print(f"{indent}[bold cyan]🌐 Starting browser session for phase '{phase.name}'[/bold cyan]")

        try:
            # Create unique session ID for this phase
            session_id = f"{self.session_id}_{phase.name}"

            # Run async browser setup in sync context
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                browser_session = loop.run_until_complete(
                    create_browser_session(
                        session_id,
                        stability_detection=phase.browser.stability_detection,
                        stability_wait=phase.browser.stability_wait,
                        show_overlay=phase.browser.show_overlay,
                        # Cascade context for unified session registry
                        cascade_id=self.config.cascade_id,
                        cell_name=phase.name,
                        rvbbit_session_id=self.session_id
                    )
                )

                # Render URL template (supports {{ input.url }} etc.)
                outputs = {entry["phase"]: entry["output"] for entry in self.echo.lineage if "phase" in entry and "output" in entry}
                outputs = enrich_outputs_with_artifacts(outputs, self.config.cells, self.session_id)
                render_context = {
                    "input": input_data,
                    "state": self.echo.state,
                    "outputs": outputs,
                    "history": self.echo.history,
                    "lineage": self.echo.lineage
                }
                url = render_instruction(phase.browser.url, render_context)

                # Initialize browser and navigate to URL
                result = loop.run_until_complete(browser_session.initialize(url))

                if not result.get("success"):
                    raise RuntimeError(f"Failed to initialize browser: {result.get('error')}")

                # Store browser session info in echo.state for tools to access
                self.echo.state["_browser_session_id"] = session_id
                self.echo.state["_browser_port"] = browser_session.port
                self.echo.state["_browser_base_url"] = browser_session.base_url
                if browser_session.artifacts:
                    self.echo.state["_browser_artifacts"] = {
                        "base_path": browser_session.artifacts.base_path,
                        "screenshots": browser_session.artifacts.screenshots,
                        "video": browser_session.artifacts.video,
                        "dom_snapshots": browser_session.artifacts.dom_snapshots,
                        "dom_coords": browser_session.artifacts.dom_coords,
                    }

                console.print(f"{indent}[green]✓ Browser ready at {url}[/green]")
                console.print(f"{indent}[dim]  Port: {browser_session.port}, Session: {session_id}[/dim]")

                return browser_session

            finally:
                loop.close()

        except Exception as e:
            console.print(f"{indent}[bold red]✗ Failed to start browser: {e}[/bold red]")
            logging.error(f"Browser session setup failed for phase '{phase.name}': {e}")
            # Don't fail the phase - just continue without browser
            return None

    def _teardown_browser_session(self, browser_session: BrowserSession, phase: CellConfig) -> None:
        """
        Clean up a browser session after phase completion.

        Ends the browser session (finalizing video) and kills the subprocess.
        """
        import asyncio

        indent = "  " * self.depth
        console.print(f"{indent}[dim]🌐 Closing browser session...[/dim]")

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                # End session (this finalizes video recording)
                loop.run_until_complete(browser_session.end())
                # Close subprocess
                loop.run_until_complete(browser_session.close())
                # Remove from manager
                loop.run_until_complete(close_browser_session(browser_session.session_id))
            finally:
                loop.close()

            # Clear browser state from echo
            for key in list(self.echo.state.keys()):
                if key.startswith("_browser_"):
                    del self.echo.state[key]

            console.print(f"{indent}[green]✓ Browser session closed[/green]")

        except Exception as e:
            console.print(f"{indent}[yellow]⚠ Error closing browser: {e}[/yellow]")
            logging.warning(f"Browser session teardown failed: {e}")

    def _execute_image_generation_phase(self, phase: CellConfig, input_data: dict, trace: TraceNode) -> Any:
        """
        Execute an image generation phase using normal Agent with modalities.

        Image generation phases use models like Gemini that support image output.
        Uses the same Agent.run() path as text models, just with modalities=["text", "image"].
        This ensures full observability: cost tracking, unified logging, events.

        The phase.instructions becomes the image prompt (rendered with Jinja2).
        """
        from .unified_logs import log_unified
        from .utils import get_next_image_index
        import time
        import os
        import base64
        import uuid

        indent = "  " * self.depth
        start_time = time.time()
        phase_model = phase.model or self.model

        # Log phase start
        log_message(self.session_id, "phase_start", phase.name,
                    trace_id=trace.id, parent_id=trace.parent_id, node_type="image_generation_phase",
                    depth=self.depth, parent_session_id=self.parent_session_id,
                    cell_name=phase.name, cascade_id=self.config.cascade_id,
                    metadata={"phase_type": "image_generation", "model": phase_model})

        # Update phase progress
        update_phase_progress(
            self.session_id, self.config.cascade_id, phase.name, self.depth,
            stage="image_generation"
        )

        # Build outputs dict from lineage (same pattern as other phase methods)
        outputs = {item['cell']: item['output'] for item in self.echo.lineage}
        outputs = enrich_outputs_with_artifacts(outputs, self.config.cells, self.session_id)

        # Render the prompt from instructions using Jinja2
        prompt = render_instruction(phase.instructions, {
            "input": input_data,
            "state": self.echo.state,
            "outputs": outputs,
            "lineage": self.echo.lineage,
        })

        console.print(f"{indent}[bold magenta]🎨 Image Generation: {phase.name}[/bold magenta]")
        console.print(f"{indent}  Model: {phase_model}")
        console.print(f"{indent}  Prompt: {prompt[:100]}...")

        # Check if this phase has context.from for image-to-image
        context_images = []
        if phase.context and phase.context.from_:
            from .cascade import ContextSourceConfig
            for source in phase.context.from_:
                source_name = source if isinstance(source, str) else getattr(source, 'phase', None)
                if source_name:
                    # Create a config for loading images
                    source_config = source if isinstance(source, ContextSourceConfig) else ContextSourceConfig(cell=source_name)
                    source_images = self._load_cell_images(source_name, source_config)
                    context_images.extend(source_images)
                    if source_images:
                        console.print(f"{indent}  [cyan]📷 Loaded {len(source_images)} image(s) from phase '{source_name}'[/cyan]")

        # Retry logic for image generation (transient API failures are common)
        max_attempts = 3
        last_error = None
        response = None

        for attempt in range(max_attempts):
            try:
                # Create Agent with modalities for image generation
                # This uses the SAME Agent.run() path as text models
                agent = Agent(
                    model=phase_model,
                    system_prompt="Generate the requested image.",
                    tools=[],
                    base_url=self.base_url,
                    api_key=self.api_key,
                    modalities=["text", "image"],  # Enable image output
                )

                # Build input - if we have context images, create multimodal message
                if context_images:
                    # Build multimodal content: images FIRST, then text prompt
                    # This is more natural for image-to-image: "Here's the image, now do X with it"
                    multimodal_content = []
                    for img_url in context_images:
                        multimodal_content.append({
                            "type": "image_url",
                            "image_url": {"url": img_url}
                        })
                    # Add text prompt after images - prefix with instruction context
                    edit_prompt = f"Using the image(s) above as reference, {prompt}"
                    multimodal_content.append({"type": "text", "text": edit_prompt})
                    console.print(f"{indent}  Edit prompt: {edit_prompt[:80]}...")
                    # Create context with multimodal message
                    context_messages = [{"role": "user", "content": multimodal_content}]
                    response = agent.run(context_messages=context_messages)
                else:
                    # Simple text-to-image
                    response = agent.run(input_message=prompt)

                # Success! Break out of retry loop
                break

            except Exception as e:
                last_error = e
                error_msg = str(e)
                enhanced_msg = getattr(e, 'enhanced_message', None)

                # Check if this is a transient/parsing error worth retrying
                is_transient = (
                    not error_msg or  # Empty error message
                    error_msg.strip().endswith('-') or  # Incomplete error
                    'parsing' in error_msg.lower() or  # Parse error
                    'convert_to_model_response_object' in str(type(e).__module__) or  # LiteLLM parsing
                    'TimeoutError' in type(e).__name__ or  # Timeout
                    'ConnectionError' in type(e).__name__  # Connection issue
                )

                if is_transient and attempt < max_attempts - 1:
                    wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                    console.print(f"{indent}  [yellow]⚠ Image generation failed (attempt {attempt + 1}/{max_attempts}), retrying in {wait_time}s...[/yellow]")
                    console.print(f"{indent}    Error: {enhanced_msg or error_msg}")
                    import time
                    time.sleep(wait_time)
                    continue
                else:
                    # Non-transient error or final attempt - raise it
                    raise

        # If we got here without response, raise the last error
        if response is None:
            raise last_error

        try:

            duration_ms = (time.time() - start_time) * 1000

            # Extract and save images from response
            saved_paths = []
            raw_images = response.get("images", [])

            if raw_images:
                config = get_config()
                image_dir = os.path.join(config.image_dir, self.session_id, phase.name)
                os.makedirs(image_dir, exist_ok=True)

                for img_data in raw_images:
                    # OpenRouter returns: {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
                    if isinstance(img_data, dict):
                        url = img_data.get("image_url", {}).get("url", "")
                        if url.startswith("data:"):
                            # Extract base64 data from data URL
                            # Format: data:image/png;base64,<data>
                            try:
                                header, b64_data = url.split(",", 1)
                                # Determine extension from mime type
                                ext = ".png"
                                if "jpeg" in header or "jpg" in header:
                                    ext = ".jpg"
                                elif "webp" in header:
                                    ext = ".webp"

                                image_idx = get_next_image_index(self.session_id, phase.name)
                                filename = f"image_{image_idx}{ext}"
                                filepath = os.path.join(image_dir, filename)

                                # Decode and save
                                image_bytes = base64.b64decode(b64_data)
                                with open(filepath, 'wb') as f:
                                    f.write(image_bytes)

                                # API-servable path
                                relative_path = f"/api/images/{self.session_id}/{phase.name}/{filename}"
                                saved_paths.append(relative_path)

                                console.print(f"{indent}    📷 Saved: {relative_path}")
                            except Exception as e:
                                console.print(f"{indent}    [yellow]⚠ Failed to save image: {e}[/yellow]")

            # Build result in standard multimodal format
            result = {
                "content": response.get("content", f"Generated {len(saved_paths)} image(s)"),
                "images": saved_paths,
                "model": phase_model,
                "request_id": response.get("id"),
            }

            # Add to lineage
            self.echo.lineage.append({
                "cell": phase.name,
                "output": result,
                "type": "image_generation",
                "model": phase_model,
                "images": saved_paths,
                "duration_ms": duration_ms
            })

            # Store output in state for subsequent phases
            self.echo.state[f"output_{phase.name}"] = result

            # Log to unified logs
            log_unified(
                session_id=self.session_id,
                trace_id=trace.id,
                parent_id=trace.parent_id,
                parent_session_id=self.parent_session_id,
                node_type="image_generation",
                role="assistant",
                depth=self.depth,
                cascade_id=self.config.cascade_id,
                cell_name=phase.name,
                model=phase_model,
                request_id=response.get("id"),
                duration_ms=duration_ms,
                content=f"Generated {len(saved_paths)} image(s)",
                metadata={
                    "phase_type": "image_generation",
                    "images": saved_paths,
                }
            )

            # Console output
            console.print(f"{indent}  [green]✓ Generated {len(saved_paths)} image(s)[/green]")

            # Hook: Phase Complete (this also publishes event via EventPublishingHooks)
            # Pass result with images so the hook publishes them correctly
            self.hooks.on_phase_complete(phase.name, self.session_id, {
                **result,
                "phase_type": "image_generation",
                "duration_ms": duration_ms,
            })

            # Determine next phase from handoffs
            next_cell = None
            if phase.handoffs and len(phase.handoffs) > 0:
                first_handoff = phase.handoffs[0]
                if isinstance(first_handoff, str):
                    next_cell = first_handoff
                elif hasattr(first_handoff, 'target'):
                    next_cell = first_handoff.target

            return next_cell

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000

            # Use enhanced message if available (from agent.py error extraction)
            error_message = getattr(e, 'enhanced_message', None) or str(e)

            # Log error with enhanced details
            log_unified(
                session_id=self.session_id,
                trace_id=trace.id,
                parent_id=trace.parent_id,
                parent_session_id=self.parent_session_id,
                node_type="image_generation_error",
                role="system",
                depth=self.depth,
                cascade_id=self.config.cascade_id,
                cell_name=phase.name,
                content=f"Image generation failed: {error_message}",
                duration_ms=duration_ms,
                metadata={
                    "phase_type": "image_generation",
                    "model": phase_model,
                    "error": error_message,
                    "error_type": type(e).__name__,
                }
            )

            console.print(f"{indent}  [red]✗ Image generation failed: {error_message[:200]}[/red]")
            raise

    def _auto_fix_and_retry(
        self,
        cell: CellConfig,
        error: Exception,
        input_data: dict,
        trace: TraceNode,
        config: AutoFixConfig,
        depth: int = 0
    ) -> Any:
        """
        Attempt to auto-fix a failed deterministic phase using LLM.

        Uses an LLM to analyze the error and generate fixed code,
        then re-runs the tool with the fixed inputs.

        Args:
            phase: The phase that failed
            error: The exception that occurred
            input_data: Original input data
            trace: Trace node for logging
            config: Auto-fix configuration
            depth: Execution depth for logging

        Returns:
            The result from the successfully fixed tool execution

        Raises:
            Exception: If all fix attempts fail
        """
        from .deterministic import resolve_tool_function, render_inputs, execute_with_retry
        from .unified_logs import log_unified
        from .prompts import render_instruction

        indent = "  " * depth

        # Get original code/query from error inputs
        original_inputs = getattr(error, 'inputs', {}) or {}
        if cell.tool == "sql_data":
            original_code = original_inputs.get("query", "")
            tool_type = "SQL"
            code_key = "query"
        elif cell.tool == "python_data":
            original_code = original_inputs.get("code", "")
            tool_type = "Python"
            code_key = "code"
        else:
            # Unsupported tool type for auto-fix
            raise error

        error_message = str(getattr(error, 'original_error', error))

        # Default prompts for SQL and Python
        default_prompts = {
            "SQL": """Fix this SQL query that failed with an error.

Error: {{ error }}

Original query:
```sql
{{ original_code }}
```

Return ONLY the corrected SQL query. No explanations, no markdown code blocks, just the raw SQL.""",

            "Python": """Fix this Python code that failed with an error.

Error: {{ error }}

Original code:
```python
{{ original_code }}
```

The code should set a `result` variable with the output (DataFrame, dict, or scalar).
Available: `data.cell_name` for prior phase outputs, `pd` (pandas), `np` (numpy).

Return ONLY the corrected Python code. No explanations, no markdown code blocks, just the raw code."""
        }

        # Use custom prompt or default
        prompt_template = config.prompt or default_prompts.get(tool_type, default_prompts["Python"])

        last_error = error
        for attempt in range(config.max_attempts):
            console.print(f"{indent}    [dim]Fix attempt {attempt + 1}/{config.max_attempts}...[/dim]")

            # Render the fix prompt
            fix_context = {
                "tool_type": tool_type,
                "error": error_message,
                "original_code": original_code,
                "inputs": original_inputs,
            }
            rendered_prompt = render_instruction(prompt_template, fix_context)

            # Create fix trace
            fix_trace = trace.create_child("auto_fix", f"{cell.name}_fix_{attempt + 1}")

            # Call LLM for fix (uses session_id for cost tracking)
            try:
                from .agent import Agent

                agent = Agent(
                    model=config.model,
                    system_prompt=f"You are a {tool_type} code fixer. Return ONLY the fixed code, no explanations.",
                    max_turns=1,
                    temperature=0.0,
                )

                # Execute agent to get fix
                fix_result = agent.complete(
                    rendered_prompt,
                    session_id=self.session_id,
                    trace_id=fix_trace.id,
                    parent_id=trace.id,
                    depth=self.depth + 1
                )

                # Clean the response (remove markdown code blocks)
                fixed_code = fix_result.strip()
                if fixed_code.startswith("```"):
                    # Remove opening ``` line
                    lines = fixed_code.split("\n")
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    # Remove closing ```
                    if lines and lines[-1].strip() == "```":
                        lines = lines[:-1]
                    fixed_code = "\n".join(lines)

                console.print(f"{indent}    [dim]Generated fix ({len(fixed_code)} chars)[/dim]")

                # Log the fix attempt
                log_unified(
                    session_id=self.session_id,
                    trace_id=fix_trace.id,
                    parent_id=trace.id,
                    node_type="auto_fix_attempt",
                    role="system",
                    depth=self.depth,
                    cascade_id=self.config.cascade_id,
                    cell_name=cell.name,
                    content=f"Auto-fix attempt {attempt + 1}: Generated {len(fixed_code)} char fix",
                    metadata={
                        "attempt": attempt + 1,
                        "model": config.model,
                        "original_error": error_message,
                        "fixed_code_preview": fixed_code[:200] + "..." if len(fixed_code) > 200 else fixed_code
                    }
                )

                # Build new inputs with fixed code
                fixed_inputs = dict(original_inputs)
                fixed_inputs[code_key] = fixed_code

                # Re-run the tool
                tool_func = resolve_tool_function(cell.tool)

                # Inject context for data tools
                if cell.tool in ("sql_data", "python_data"):
                    fixed_inputs["_cell_name"] = cell.name
                    fixed_inputs["_session_id"] = self.echo.session_id

                    if cell.tool == "python_data":
                        # Build outputs dict
                        outputs = {}
                        for item in self.echo.lineage:
                            output = item.get("output")
                            if isinstance(output, dict):
                                outputs[item["cell"]] = output
                        fixed_inputs["_outputs"] = outputs
                        fixed_inputs["_state"] = self.echo.state
                        fixed_inputs["_input"] = input_data

                result = tool_func(**fixed_inputs)

                # Success!
                console.print(f"{indent}    [green]✓ Auto-fix succeeded on attempt {attempt + 1}[/green]")

                # Log success
                log_unified(
                    session_id=self.session_id,
                    trace_id=fix_trace.id,
                    parent_id=trace.id,
                    node_type="auto_fix_success",
                    role="system",
                    depth=self.depth,
                    cascade_id=self.config.cascade_id,
                    cell_name=cell.name,
                    content=f"Auto-fix succeeded on attempt {attempt + 1}",
                    metadata={
                        "attempt": attempt + 1,
                        "model": config.model,
                    }
                )

                # Update lineage with the successful result
                self.echo.add_lineage(cell.name, result, trace.id)

                return result

            except Exception as retry_error:
                last_error = retry_error
                error_message = str(retry_error)  # Update error message for next attempt
                console.print(f"{indent}    [yellow]Fix attempt {attempt + 1} failed: {str(retry_error)[:100]}[/yellow]")

                # Log failure
                log_unified(
                    session_id=self.session_id,
                    trace_id=fix_trace.id,
                    parent_id=trace.id,
                    node_type="auto_fix_failed",
                    role="system",
                    depth=self.depth,
                    cascade_id=self.config.cascade_id,
                    cell_name=cell.name,
                    content=f"Auto-fix attempt {attempt + 1} failed: {str(retry_error)}",
                    metadata={
                        "attempt": attempt + 1,
                        "model": config.model,
                        "error": str(retry_error)
                    }
                )

        # All attempts failed
        raise last_error

    def _execute_sql_mapping_phase(self, phase: CellConfig, input_data: dict, trace: TraceNode) -> Any:
        """
        Execute SQL-native mapping: fan out over rows from a temp table.

        This is like map_cascade but reads from DuckDB temp tables instead of arrays.
        Perfect for data pipeline patterns where you want to process each row.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from .sql_tools.session_db import get_session_db
        from .prompts import render_instruction
        import time
        import uuid

        indent = "  " * self.depth
        config = phase.for_each_row

        console.print(f"{indent}[bold magenta]🗂️  SQL Mapping: {config.table} → {config.max_parallel} parallel[/bold magenta]")

        # Get session DuckDB
        session_db = get_session_db(self.session_id)

        # Query the temp table to get rows
        try:
            result = session_db.execute(f"SELECT * FROM {config.table}").fetchdf()
            rows = result.to_dict('records')  # Convert to list of dicts
        except Exception as e:
            console.print(f"{indent}[red]✗ Failed to read table {config.table}: {e}[/red]")
            return {
                "_route": "error",
                "error": f"Failed to read table {config.table}: {str(e)}",
                "results": [],
                "count": 0,
                "total": 0
            }

        total_rows = len(rows)
        console.print(f"{indent}  Found {total_rows} rows in {config.table}")

        if total_rows == 0:
            return {
                "results": [],
                "count": 0,
                "total": 0,
                "_route": "success"
            }

        results = []
        errors = []
        successful_count = 0

        def process_single_row(index: int, row: dict) -> dict:
            """Process a single row."""
            # Generate session ID for this row
            row_session_id = f"{self.session_id}_row_{index}"

            # Build context for Jinja2 rendering
            render_context = {
                "row": row,
                "index": index,
                "total": total_rows,
                "input": input_data,
                "state": self.echo.state,
                "outputs": {item['cell']: item['output'] for item in self.echo.lineage}
            }

            try:
                if config.cascade:
                    # Spawn cascade per row
                    from .runner import run_cascade

                    # Render inputs with row data
                    cascade_inputs = {}
                    if config.inputs:
                        for key, template in config.inputs.items():
                            cascade_inputs[key] = render_instruction(template, render_context)

                    result = run_cascade(
                        config.cascade,
                        cascade_inputs,
                        session_id=row_session_id,
                        parent_trace=trace,
                        parent_session_id=self.session_id
                    )

                    return {
                        "index": index,
                        "row": row,
                        "result": result,
                        "error": None,
                        "session_id": row_session_id
                    }

                elif config.instructions:
                    # Run LLM phase per row
                    # Render instructions with row data
                    rendered_instructions = render_instruction(config.instructions, render_context)

                    # Create a mini LLM phase
                    from .agent import Agent
                    agent = Agent(model=self.model)

                    response = agent.run(
                        system_prompt=rendered_instructions,
                        user_message="",
                        tools=[],
                        max_turns=1
                    )

                    return {
                        "index": index,
                        "row": row,
                        "result": response,
                        "error": None,
                        "session_id": row_session_id
                    }

                else:
                    raise ValueError("for_each_row must specify either 'cascade' or 'instructions'")

            except Exception as e:
                error_info = {
                    "index": index,
                    "row": row,
                    "result": None,
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "session_id": row_session_id
                }

                if config.on_error == "fail_fast":
                    raise

                return error_info

        # Execute in parallel
        with ThreadPoolExecutor(max_workers=min(config.max_parallel, total_rows)) as executor:
            futures = {
                executor.submit(process_single_row, i, row): i
                for i, row in enumerate(rows)
            }

            for future in as_completed(futures):
                try:
                    result_dict = future.result()

                    if result_dict["error"] is None:
                        successful_count += 1
                        results.append(result_dict)
                    else:
                        errors.append(result_dict)
                        if config.on_error == "fail_fast":
                            # Cancel remaining
                            for f in futures:
                                f.cancel()
                            break

                except Exception as e:
                    errors.append({
                        "error": str(e),
                        "error_type": type(e).__name__
                    })

        console.print(f"{indent}  [bold green]✓ Processed {successful_count}/{total_rows} rows[/bold green]")

        # Optionally materialize results as temp table
        if config.result_table and len(results) > 0:
            try:
                import pandas as pd
                # Extract result data and create DataFrame
                result_rows = []
                for r in results:
                    result_row = {"_index": r["index"]}
                    # Merge original row data
                    result_row.update(r["row"])
                    # Add result (if it's a dict, flatten it)
                    if isinstance(r["result"], dict):
                        for k, v in r["result"].items():
                            if k not in result_row:  # Don't overwrite original columns
                                result_row[f"result_{k}"] = v
                    else:
                        result_row["result"] = r["result"]
                    result_rows.append(result_row)

                df = pd.DataFrame(result_rows)
                session_db.register("_temp_results", df)
                session_db.execute(f"CREATE OR REPLACE TABLE {config.result_table} AS SELECT * FROM _temp_results")
                session_db.unregister("_temp_results")

                console.print(f"{indent}  [dim]Created temp table: {config.result_table}[/dim]")

            except Exception as e:
                console.print(f"{indent}  [yellow]⚠ Warning: Could not create result table: {e}[/yellow]")

        # Return results
        return {
            "results": [r["result"] for r in results],
            "count": successful_count,
            "total": total_rows,
            "errors": errors if config.on_error == "collect_errors" else None,
            "session_ids": [r["session_id"] for r in results],
            "_route": "success" if successful_count > 0 else "error"
        }

    def _execute_deterministic_phase(self, phase: CellConfig, input_data: dict, trace: TraceNode) -> Any:
        """
        Execute a deterministic (tool-based) phase without LLM mediation.

        This provides direct tool execution for predictable, fast operations
        while maintaining the same observability as LLM phases.
        """
        from .deterministic import (
            execute_deterministic_phase,
            DeterministicExecutionError,
            determine_routing
        )
        from .unified_logs import log_unified
        import time

        indent = "  " * self.depth
        start_time = time.time()

        # Compute species hash for this cell execution (ALWAYS)
        try:
            from .utils import compute_species_hash

            phase_config = phase.dict() if hasattr(phase, 'dict') else (phase if isinstance(phase, dict) else {})
            phase_species_hash = compute_species_hash(phase_config, input_data)

        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.debug(f"Could not compute species_hash for deterministic {phase.name}: {e}")
            phase_species_hash = "unknown_species"

        # Log phase start
        log_message(self.session_id, "phase_start", phase.name,
                    trace_id=trace.id, parent_id=trace.parent_id, node_type="deterministic_phase",
                    depth=self.depth, parent_session_id=self.parent_session_id,
                    cell_name=phase.name, cascade_id=self.config.cascade_id,
                    species_hash=phase_species_hash,
                    metadata={"phase_type": "deterministic", "tool": phase.tool})

        # Update phase progress
        update_phase_progress(
            self.session_id, self.config.cascade_id, phase.name, self.depth,
            stage="deterministic"
        )

        try:
            # Execute the deterministic cell
            result, next_cell = execute_deterministic_phase(
                phase,
                input_data=input_data,
                echo=self.echo,
                config_path=self.config_path if isinstance(self.config_path, str) else None,
                depth=self.depth
            )

            duration_ms = (time.time() - start_time) * 1000

            # Update echo state with result
            self.echo.state[f"output_{phase.name}"] = result

            # Add to lineage
            self.echo.lineage.append({
                "cell": phase.name,
                "output": result,
                "type": "deterministic",
                "tool": phase.tool,
                "duration_ms": duration_ms
            })

            # Log to unified logs
            log_unified(
                session_id=self.session_id,
                trace_id=trace.id,
                parent_id=trace.parent_id,
                parent_session_id=self.parent_session_id,
                node_type="deterministic",
                role="tool",
                depth=self.depth,
                cascade_id=self.config.cascade_id,
                cascade_file=self.config_path if isinstance(self.config_path, str) else None,
                cell_name=phase.name,
                species_hash=phase_species_hash,
                content=json.dumps(result) if isinstance(result, (dict, list)) else str(result),
                duration_ms=duration_ms,
                metadata={
                    "phase_type": "deterministic",
                    "tool": phase.tool,
                    "inputs": list((phase.tool_inputs or {}).keys()),
                    "next_cell": next_cell
                }
            )

            # Hook: Phase Complete
            self.hooks.on_phase_complete(phase.name, self.session_id, {
                "output": result,
                "duration_ms": duration_ms,
            })

            # Return next phase name or result
            if next_cell:
                return next_cell
            return result

        except DeterministicExecutionError as e:
            duration_ms = (time.time() - start_time) * 1000

            # Log error
            log_unified(
                session_id=self.session_id,
                trace_id=trace.id,
                parent_id=trace.parent_id,
                node_type="error",
                role="error",
                depth=self.depth,
                cascade_id=self.config.cascade_id,
                cell_name=phase.name,
                content=f"Deterministic phase failed: {str(e)}",
                duration_ms=duration_ms,
                metadata={
                    "phase_type": "deterministic",
                    "tool": phase.tool,
                    "error": str(e.original_error) if e.original_error else str(e)
                }
            )

            # Handle on_error routing
            if phase.on_error:
                # Check for auto_fix mode
                auto_fix_config = None
                if phase.on_error == "auto_fix":
                    # Simple mode: on_error: auto_fix
                    auto_fix_config = AutoFixConfig()
                elif isinstance(phase.on_error, dict) and "auto_fix" in phase.on_error:
                    # Customized mode: on_error: {auto_fix: {...}}
                    if isinstance(phase.on_error["auto_fix"], dict):
                        auto_fix_config = AutoFixConfig(**phase.on_error["auto_fix"])
                    else:
                        auto_fix_config = AutoFixConfig()

                if auto_fix_config and auto_fix_config.enabled:
                    # Attempt auto-fix
                    console.print(f"{indent}  [yellow]🔧 Attempting auto-fix...[/yellow]")
                    try:
                        result = self._auto_fix_and_retry(
                            cell=phase,
                            error=e,
                            input_data=input_data,
                            trace=trace,
                            config=auto_fix_config,
                            depth=depth
                        )
                        # Success - determine routing and return
                        handoffs = phase.handoffs or []
                        next_cell = determine_routing(result, phase.routing, handoffs)
                        if next_cell:
                            console.print(f"{indent}  [magenta]→ Routing to: {next_cell}[/magenta]")
                            return next_cell
                        return result
                    except Exception as fix_error:
                        # Auto-fix failed after all attempts - continue to other error handling or re-raise
                        console.print(f"{indent}  [red]✗ Auto-fix exhausted all attempts[/red]")
                        e = fix_error  # Use the last error for further handling

                if isinstance(phase.on_error, str) and phase.on_error != "auto_fix":
                    # Route to error handler phase
                    console.print(f"{indent}  [yellow]→ Routing to error handler: {phase.on_error}[/yellow]")
                    # Store error info in state for error handler to access
                    self.echo.state["last_deterministic_error"] = {
                        "cell": phase.name,
                        "tool": phase.tool,
                        "error": str(e.original_error) if hasattr(e, 'original_error') and e.original_error else str(e),
                        "inputs": e.inputs if hasattr(e, 'inputs') else {}
                    }
                    return phase.on_error
                elif isinstance(phase.on_error, dict) and "instructions" in phase.on_error:
                    # Inline LLM fallback - create temporary phase and execute
                    console.print(f"{indent}  [yellow]→ Falling back to LLM handler[/yellow]")

                    # Build fallback phase config
                    fallback_config = {
                        "name": f"{phase.name}_fallback",
                        "instructions": phase.on_error.get("instructions", f"Handle error from {phase.name}: {{{{ state.last_deterministic_error }}}}"),
                        **{k: v for k, v in phase.on_error.items() if k != "instructions"}
                    }

                    # Store error info
                    self.echo.state["last_deterministic_error"] = {
                        "cell": phase.name,
                        "tool": phase.tool,
                        "error": str(e.original_error) if hasattr(e, 'original_error') and e.original_error else str(e),
                        "inputs": e.inputs if hasattr(e, 'inputs') else {}
                    }

                    # Create and execute fallback phase
                    fallback_phase = CellConfig(**fallback_config)
                    fallback_trace = trace.create_child("phase", f"{phase.name}_fallback")
                    return self._execute_phase_internal(fallback_phase, input_data, fallback_trace)

            # No error handler - re-raise
            raise

    def _execute_phase_internal(self, phase: CellConfig, input_data: dict, trace: TraceNode, initial_injection: dict = None, mutation: str = None, mutation_mode: str = None, pre_built_context: list = None) -> Any:
        indent = "  " * self.depth
        rag_context = None
        rag_prompt = ""
        rag_tool_names: List[str] = []

        # Compute species hash for this cell execution (ALWAYS)
        # Used for analytics, prompt optimization, and model comparison
        try:
            from .utils import compute_species_hash

            # Get phase config as dict
            phase_config = phase.dict() if hasattr(phase, 'dict') else (phase if isinstance(phase, dict) else {})

            # Compute species_hash (cell-level identity)
            phase_species_hash = compute_species_hash(phase_config, input_data)

        except Exception as e:
            # Fallback to unknown if computation fails (don't break execution)
            logger = logging.getLogger(__name__)
            logger.debug(f"Could not compute species_hash for {phase.name}: {e}")
            phase_species_hash = "unknown_species"

        # Set current phase name for tools like ask_human to use
        set_current_cell_name(phase.name)

        # Reset auto-context loop tracking for this phase
        self._loop_validation_failures = []

        # Set current candidate index if we're in a candidate (for parallel candidate decisions)
        if self.current_phase_candidate_index is not None:
            set_current_candidate_index(self.current_phase_candidate_index)

        def _cleanup_rag():
            if rag_context:
                clear_current_rag_context()

        # Prepare outputs dict for easier templating
        outputs = {item['cell']: item['output'] for item in self.echo.lineage}
        outputs = enrich_outputs_with_artifacts(outputs, self.config.cells, self.session_id)

        # Render Instructions (Jinja2)
        render_context = {
            "input": input_data,
            "state": self.echo.state,
            "history": self.echo.history,
            "outputs": outputs,
            "lineage": self.echo.lineage,
            # Sounding context - enables fan-out patterns like {{ state.items[candidate_index] }}
            "candidate_index": self.current_phase_candidate_index if self.current_phase_candidate_index is not None else 0,
            "candidate_factor": getattr(self, '_current_sounding_factor', 1),  # Total soundings in this phase
            "is_sounding": self.current_phase_candidate_index is not None,
        }

        # Build/update RAG index if configured for this phase
        if phase.rag:
            rag_context = ensure_rag_index(
                phase.rag,
                self.config_path,
                self.session_id,
                trace_id=trace.id,
                parent_id=trace.parent_id,
                cell_name=phase.name,
                cascade_id=self.config.cascade_id
            )
            set_current_rag_context(rag_context)
            rag_tool_names = ["rag_search", "rag_read_chunk", "rag_list_sources"]
            rag_prompt = (
                f"\n\n## Retrieval Context\n"
                f"A retrieval index is available for `{rag_context.directory}` "
                f"(recursive: {phase.rag.recursive}), RAG ID: `{rag_context.rag_id}`.\n\n"
                f"**CRITICAL: You MUST use `rag_search` first to get valid chunk_ids.** "
                f"Chunk IDs are opaque strings like `9de9b0d4a33d_1` - never invent or guess them! "
                f"Only use the exact chunk_id values returned by `rag_search` in the results array.\n\n"
                f"Workflow: 1) `rag_search` to find chunks → 2) copy exact `chunk_id` from results → 3) `rag_read_chunk` to get full text.\n"
                f"Cite sources as path#line_start-line_end."
            )
        else:
            # No rag block on this phase - check if RAG tools are in tackle list
            # If so, reuse the existing RAG context from an earlier phase
            from .rag.context import get_current_rag_context
            existing_ctx = get_current_rag_context()
            rag_tools_in_tackle = {"rag_search", "rag_read_chunk", "rag_list_sources"}
            phase_uses_rag_tools = bool(
                phase.traits and
                isinstance(phase.traits, list) and
                rag_tools_in_tackle.intersection(phase.traits)
            )

            if existing_ctx and phase_uses_rag_tools:
                # Reuse existing RAG context - no rebuild needed
                rag_context = existing_ctx
                rag_tool_names = list(rag_tools_in_tackle.intersection(phase.traits))
                rag_prompt = (
                    f"\n\n## Retrieval Context\n"
                    f"A retrieval index is available for `{rag_context.directory}`, "
                    f"RAG ID: `{rag_context.rag_id}`.\n\n"
                    f"**CRITICAL: You MUST use `rag_search` first to get valid chunk_ids.** "
                    f"Chunk IDs are opaque strings like `9de9b0d4a33d_1` - never invent or guess them! "
                    f"Only use the exact chunk_id values returned by `rag_search` in the results array.\n\n"
                    f"Workflow: 1) `rag_search` to find chunks → 2) copy exact `chunk_id` from results → 3) `rag_read_chunk` to get full text.\n"
                    f"Cite sources as path#line_start-line_end."
                )
            # else: no RAG context and no RAG tools requested - leave context as-is

        # ========== RESEARCH COCKPIT MODE: Inject UI scaffolding ==========
        # If this phase is running in Research Cockpit mode (interactive research UI),
        # inject system prompt with UI patterns, state management, and available tools
        from .research_cockpit import is_research_cockpit_mode, inject_research_scaffolding, get_detection_reason

        phase_instructions = phase.instructions
        if is_research_cockpit_mode(phase):
            reason = get_detection_reason(phase)
            console.print(f"{indent}[dim cyan]🧭 Research Cockpit mode detected ({reason})[/dim cyan]")
            console.print(f"{indent}[dim]Injecting UI scaffolding and state management patterns...[/dim]")
            phase_instructions = inject_research_scaffolding(phase.instructions, phase, render_context)

        rendered_instructions = render_instruction(phase_instructions, render_context)

        # Apply mutation if provided (for candidate variations)
        # Three modes:
        #   - rewrite: mutation IS the complete rewritten prompt (replace entirely)
        #   - augment: mutation is prepended to original prompt (test specific patterns)
        #   - approach: mutation is appended as thinking strategy (Tree of Thought sampling)
        if mutation:
            if mutation_mode == "rewrite":
                # Rewrite mode: The mutation is the complete rewritten prompt from LLM
                # Replace instructions entirely - this tests fundamentally different formulations
                rendered_instructions = mutation
            elif mutation_mode == "augment":
                # Augment mode: PREPEND mutation to instructions
                # Good for testing specific known patterns/fragments
                rendered_instructions = f"{mutation}\n\n{rendered_instructions}"
            else:  # approach mode or default
                # Approach mode: APPEND as strategy hint - guides thinking style
                # This is for diversity sampling (Tree of Thought), less learnable
                rendered_instructions += f"\n\n**Variation Strategy**: {mutation}"

        # ========== PRE-WARDS: Validate inputs before phase starts ==========
        if phase.wards and phase.wards.pre:
            console.print(f"{indent}[bold cyan]🛡️  Running Pre-Wards (Input Validation)...[/bold cyan]")

            # Update phase progress for pre-ward stage
            update_phase_progress(
                self.session_id, self.config.cascade_id, phase.name, self.depth,
                stage="pre_ward"
            )

            # Prepare input content for validation
            input_content = json.dumps(input_data)

            total_pre_wards = len(phase.wards.pre)
            for ward_idx, ward_config in enumerate(phase.wards.pre):
                # Update progress with current ward
                update_phase_progress(
                    self.session_id, self.config.cascade_id, phase.name, self.depth,
                    ward_name=_format_validator_name(ward_config.validator),
                    ward_type="pre",
                    ward_index=ward_idx + 1,
                    total_wards=total_pre_wards
                )
                ward_result = self._run_ward(ward_config, input_content, trace, ward_type="pre")

                if not ward_result["valid"]:
                    # Handle based on mode
                    if ward_result["mode"] == "blocking":
                        console.print(f"{indent}[bold red]⛔ Pre-Ward BLOCKING: Phase aborted[/bold red]")
                        log_message(self.session_id, "pre_ward_blocked", f"Phase blocked by {ward_result['validator']}",
                                   {"reason": ward_result["reason"]},
                                   trace_id=trace.id, parent_id=trace.parent_id,
                                   node_type="ward_block", depth=self.depth)
                        _cleanup_rag()
                        return f"[BLOCKED by pre-ward: {ward_result['reason']}]"

                    elif ward_result["mode"] == "advisory":
                        # Log warning but continue
                        console.print(f"{indent}  [yellow]⚠️  Advisory warning (continuing)...[/yellow]")

                    # Note: retry mode doesn't apply to pre-wards (can't retry input)
        
        # SMART HANDOFFS: Inject routing menu if multiple options or descriptions exist
        valid_handoff_targets = []
        routing_menu = ""
        
        normalized_handoffs = []
        if phase.handoffs:
            for h in phase.handoffs:
                if isinstance(h, str):
                    normalized_handoffs.append({"target": h, "description": None})
                else:
                    normalized_handoffs.append({"target": h.target, "description": h.description})
        
        enable_routing_tool = len(normalized_handoffs) > 1 or any(h['description'] for h in normalized_handoffs)

        if enable_routing_tool:
            routing_menu += "\n\n## Routing Options\nYou must decide what to do next. Call the 'route_to' tool with one of these targets:\n"
            for h in normalized_handoffs:
                desc = f": {h['description']}" if h['description'] else ""
                routing_menu += f"- '{h['target']}'{desc}\n"
                valid_handoff_targets.append(h['target'])

            rendered_instructions += routing_menu

        # AUTO-INJECT LOOP_UNTIL VALIDATION GOAL
        # If loop_until is configured, tell the agent upfront what validation it needs to pass
        # Unless loop_until_silent is True (for impartial/subjective validation)
        if phase.rules.loop_until and not phase.rules.loop_until_silent:
            validator_spec = phase.rules.loop_until
            validator_display_name = _format_validator_name(validator_spec)
            max_attempts = phase.rules.max_attempts if phase.rules.max_attempts else 5

            # Use custom prompt if provided, otherwise auto-generate from validator description
            if phase.rules.loop_until_prompt:
                validation_prompt = phase.rules.loop_until_prompt
            else:
                # Try to get validator description from manifest (only for string validators)
                validator_description = None
                if isinstance(validator_spec, str):
                    from .traits_manifest import get_trait_manifest
                    manifest = get_trait_manifest()
                    if validator_spec in manifest:
                        validator_description = manifest[validator_spec].get("description", "")

                # Build validation prompt
                if validator_description:
                    validation_prompt = f"Your output will be validated using '{validator_display_name}' which checks: {validator_description}"
                else:
                    validation_prompt = f"Your output will be validated using the '{validator_display_name}' validator"

            # Inject validation requirement into instructions
            rendered_instructions += f"\n\n---\n**VALIDATION REQUIREMENT:**\n{validation_prompt}\nYou have {max_attempts} attempt(s) to satisfy this validator.\n---"

        # Determine model to use (phase override or default)
        phase_model = phase.model if phase.model else self.model

        console.print(f"\n{indent}[bold magenta]📍 Bearing (Phase): {phase.name}[/bold magenta] [bold cyan]🤖 {phase_model}[/bold cyan]")
        console.print(f"{indent}[italic]{rendered_instructions[:100]}...[/italic]")

        log_message(self.session_id, "phase_start", phase.name,
                   trace_id=trace.id, parent_id=trace.parent_id, node_type="phase", depth=trace.depth,
                   model=phase_model, parent_session_id=self.parent_session_id,
                   cell_name=phase.name, cascade_id=self.config.cascade_id,
                   species_hash=phase_species_hash, phase_config=phase.dict() if phase_species_hash else None)

        # Publish phase_start event (for narrator and other subscribers)
        self._publish_event("phase_start", {
            "cell_name": phase.name,
            "cascade_id": self.config.cascade_id,
            "model": phase_model,
            "trace_id": trace.id if trace else None,
        })

        # Resolve tools (Tackle) - Check if Quartermaster needed
        trait_list = phase.traits
        # Handle manifest mode: tackle can be "manifest" (string) or ["manifest"] (list)
        is_manifest = (
            phase.traits == "manifest" or
            (isinstance(phase.traits, list) and "manifest" in phase.traits)
        )
        if is_manifest:
            console.print(f"{indent}  [bold cyan]🗺️  Quartermaster charting tackle...[/bold cyan]")
            trait_list = self._run_quartermaster(phase, input_data, trace, phase_model)
            console.print(f"{indent}  [bold cyan]📋 Manifest: {', '.join(trait_list)}[/bold cyan]")

        if rag_tool_names:
            for rag_tool in rag_tool_names:
                if rag_tool not in trait_list:
                    trait_list.append(rag_tool)

        tools_schema = []  # For native tool calling
        tool_descriptions = []  # For prompt-based tool calling
        tool_map = {}

        # Import memory system for dynamic tool registration
        from .memory import get_memory_system

        for t_name in trait_list:
            t = get_trait(t_name)
            if t:
                tool_map[t_name] = t
                # Generate both formats
                tools_schema.append(get_tool_schema(t, name=t_name))
                tool_descriptions.append(self._generate_tool_description(t, t_name))
            else:
                # Check if this is a memory bank name (either configured or existing)
                memory_system = get_memory_system()
                if t_name == self.memory_name or memory_system.exists(t_name):
                    # Dynamically create and register memory tool
                    memory_tool = self._create_memory_tool(t_name)
                    tool_map[t_name] = memory_tool
                    tools_schema.append(get_tool_schema(memory_tool, name=t_name))
                    tool_descriptions.append(self._generate_tool_description(memory_tool, t_name))
                else:
                    # Check if this is a cascade tool (triggers registration if needed)
                    from .traits_manifest import get_trait_manifest
                    manifest = get_trait_manifest()
                    if t_name in manifest and manifest[t_name].get("type") == "cascade":
                        # Try to get the now-registered tool
                        cascade_tool = get_trait(t_name)
                        if cascade_tool:
                            tool_map[t_name] = cascade_tool
                            tools_schema.append(get_tool_schema(cascade_tool, name=t_name))
                            tool_descriptions.append(self._generate_tool_description(cascade_tool, t_name))
                    # else: Tool not found

        # Inject 'route_to' tool if routing enabled
        chosen_next_phase_by_agent = None
        chosen_next_phase = None # Initialize for consistency

        if enable_routing_tool:
            def route_to_tool(target: str):
                """
                Routes execution to the specified target phase.
                """
                nonlocal chosen_next_phase_by_agent # Allow modification of outer scope variable
                if target in valid_handoff_targets:
                    chosen_next_phase_by_agent = target
                    return f"Routing to {target}."
                return f"Invalid target. Valid options: {valid_handoff_targets}"

            tool_map["route_to"] = route_to_tool
            tools_schema.append(get_tool_schema(route_to_tool))
            tool_descriptions.append(self._generate_tool_description(route_to_tool, "route_to"))

        # ========== CONTEXT SYSTEM (SELECTIVE-BY-DEFAULT) ==========
        # Build context fresh for each phase from config
        # No config = clean slate (empty context)
        # Use context.from: ["all"] for explicit snowball behavior
        #
        # EXCEPTION: pre_built_context is used for reforge iterations
        # where we need to pass images and previous output context
        if pre_built_context is not None:
            # Use pre-built context (from reforge with images)
            # Log these messages for observability
            self.context_messages = []
            for msg in pre_built_context:
                ctx_trace = trace.create_child("msg", "reforge_context_injection")
                self.echo.add_history(msg, trace_id=ctx_trace.id, parent_id=trace.id, node_type="context_injection",
                                     metadata=self._get_metadata({"context_source": "reforge_pre_built", "has_images": self._message_has_images(msg)},
                                                                 semantic_actor="framework", semantic_purpose="context_injection"))
                self.context_messages.append(msg)
            context_result = pre_built_context
        else:
            context_result = self._build_phase_context(phase, input_data, trace)

            # Always use the built context (selective-by-default)
            self.context_messages = []
            for msg in context_result:
                ctx_trace = trace.create_child("msg", "context_injection")
                self.echo.add_history(msg, trace_id=ctx_trace.id, parent_id=trace.id, node_type="context_injection",
                                     metadata=self._get_metadata({"context_from": phase.context.from_ if phase.context else []},
                                                                 semantic_actor="framework", semantic_purpose="context_injection"))
                self.context_messages.append(msg)

        # Construct context from lineage
        # Since we are snowballing context_messages, we don't need to add input_data as a separate user message.
        # Input data is already available via:
        # 1. Jinja2 template rendering in system prompt ({{ input.key }})
        # 2. Snowball context from previous phases (for multi-phase cascades)
        # Adding a redundant "## Input Data:" user message confuses the agent.
        # user_content = f"## Input Data:\n{json.dumps(input_data or {})}"  # REMOVED - redundant!

        # Add tool descriptions to instructions if using prompt-based tools
        final_instructions = rendered_instructions + rag_prompt
        use_native = phase.use_native_tools

        if tool_descriptions:
            if use_native:
                # Native tool calling via provider API
                console.print(f"{indent}  [dim cyan]Using native tool calling (provider-specific)[/dim cyan]")
            else:
                # Prompt-based tools: Add tool descriptions to system prompt
                console.print(f"{indent}  [dim cyan]Using prompt-based tools (provider-agnostic)[/dim cyan]")
                tools_prompt = "\n\n## Available Tools\n\n" + "\n\n".join(tool_descriptions)
                tools_prompt += "\n\n**Important:** To call a tool, you MUST wrap your JSON in a ```json code fence:\n\n"
                tools_prompt += "Example:\n```json\n"
                tools_prompt += '{"tool": "tool_name", "arguments": {"param": "value"}}\n```\n\n'
                tools_prompt += "Do NOT output raw JSON outside of code fences - it will not be detected."
                final_instructions += tools_prompt

        # Initialize Agent (using phase_model determined earlier)
        agent = Agent(
            model=phase_model,
            system_prompt="", # We manage system prompts in context_messages
            tools=tools_schema if use_native else None,  # Only pass tools if using native
            base_url=self.base_url,
            api_key=self.api_key,
            use_native_tools=use_native  # Pass flag so Agent can strip tool_calls/tool_call_id from messages
        )

        # Determine if this is the first phase (no prior assistant messages in context)
        has_prior_context = any(m.get("role") == "assistant" for m in self.context_messages)

        # Build phase messages based on context:
        # - First phase: system message (tools) + user message (task)
        # - Subsequent phases: user message only (task) - tools already in context
        #
        # This ensures proper conversation flow: user messages prompt responses,
        # while multiple system messages can confuse LLM APIs.

        # Build tool definitions prompt (for prompt-based tools only)
        tools_prompt = ""
        if not use_native and tool_descriptions:
            tools_prompt = "\n\n".join(tool_descriptions)
            tools_prompt += "\n\n**Important:** To call a tool, you MUST wrap your JSON in a ```json code fence:\n\n"
            tools_prompt += "Example:\n```json\n"
            tools_prompt += '{"tool": "tool_name", "arguments": {"param": "value"}}\n```\n\n'
            tools_prompt += "Do NOT output raw JSON outside of code fences - it will not be detected."

        if has_prior_context:
            # Subsequent phase: task as user message
            # For prompt-based tools: include tool definitions in a system message if tools changed,
            # otherwise include in user message for cleaner flow
            # For native tools: tools are passed via API parameter, no message needed

            if not use_native and tool_descriptions:
                # Add system message with tool definitions (Quartermaster may have selected different tools)
                sys_trace = trace.create_child("msg", "tool_definitions")
                sys_msg = {"role": "system", "content": f"## Tools for this phase\n\n{tools_prompt}"}
                self.echo.add_history(sys_msg, trace_id=sys_trace.id, parent_id=trace.id, node_type="system",
                                     metadata=self._get_metadata(semantic_actor="framework", semantic_purpose="instructions"))
                self.context_messages.append(sys_msg)

            # User message with the task
            task_content = f"## New Task\n\n{rendered_instructions}{rag_prompt}"
            # Convert to multimodal if images are embedded in rendered text
            task_content = convert_to_multimodal_content(task_content)
            user_trace = trace.create_child("msg", "phase_task")
            user_msg = {"role": "user", "content": task_content}
            self.echo.add_history(user_msg, trace_id=user_trace.id, parent_id=trace.id, node_type="user",
                                 metadata=self._get_metadata(semantic_actor="framework", semantic_purpose="task_input"))
            self.context_messages.append(user_msg)
        else:
            # First phase: system message with tools + user message with task
            if not use_native and tool_descriptions:
                sys_trace = trace.create_child("msg", "tool_definitions")
                sys_msg = {"role": "system", "content": f"## Available Tools\n\n{tools_prompt}"}
                self.echo.add_history(sys_msg, trace_id=sys_trace.id, parent_id=trace.id, node_type="system",
                                     metadata=self._get_metadata(semantic_actor="framework", semantic_purpose="instructions"))
                self.context_messages.append(sys_msg)

            # User message with the actual task
            task_content = rendered_instructions + rag_prompt
            # Convert to multimodal if images are embedded in rendered text
            task_content = convert_to_multimodal_content(task_content)
            user_trace = trace.create_child("msg", "phase_task")
            user_msg = {"role": "user", "content": task_content}
            self.echo.add_history(user_msg, trace_id=user_trace.id, parent_id=trace.id, node_type="user",
                                 metadata=self._get_metadata(semantic_actor="framework", semantic_purpose="task_input"))
            self.context_messages.append(user_msg)

        # For debugging, log input data to echo (but NOT to context_messages)
        if input_data:
            input_trace = trace.create_child("msg", "input_data_reference")
            self.echo.add_history(
                {"role": "user", "content": f"## Input Data:\n{json.dumps(input_data)}"},
                trace_id=input_trace.id, parent_id=trace.id, node_type="user",
                metadata=self._get_metadata({"debug_only": True, "not_sent_to_llm": True},
                                            semantic_actor="framework", semantic_purpose="task_input")
            )

        # Handle Phase Start Injection
        injected_messages = []
        if initial_injection and initial_injection.get("action") == HookAction.INJECT:
            inject_content = initial_injection.get("content")
            console.print(f"{indent}[bold red]⚡ Injection Triggered:[/bold red] {inject_content}")
            injected_messages.append({"role": "user", "content": f"URGENT USER INJECTION: {inject_content}"})

            inject_trace = trace.create_child("msg", "injection")
            inject_msg = {"role": "user", "content": inject_content}
            self.echo.add_history(inject_msg, trace_id=inject_trace.id, parent_id=trace.id, node_type="injection",
                                 metadata=self._get_metadata(semantic_actor="human", semantic_purpose="task_input"))
            self.context_messages.append(inject_msg)

        self._update_graph()

        # Async Cascades (Side Effects) - on_start
        if phase.async_cascades:
            for sub in phase.async_cascades:
                if sub.trigger == "on_start":
                    # Prepare Input (same logic as sub_cascades)
                    sub_input = {}
                    if sub.context_in:
                        sub_input.update(self.echo.state)
                        if "input" in self.echo.state and isinstance(self.echo.state["input"], dict):
                            sub_input.update(self.echo.state["input"])
                    
                    current_context = {**self.echo.state, **(input_data or {})}
                    for child_key, parent_val in sub.input_map.items():
                        if parent_val in current_context:
                            sub_input[child_key] = current_context[parent_val]
                        else:
                            sub_input[child_key] = parent_val
                    
                    console.print(f"{indent}  🔥 [bold orange1]Spawning Side-Effect: {sub.ref}[/bold orange1]")

                    # Resolve path for async_cascades
                    ref_path = sub.ref
                    if not os.path.isabs(ref_path):
                        if ref_path.startswith("rvbbit/"): # If it's already project-root-relative
                            # Assume project root is cwd
                            ref_path = os.path.join(os.getcwd(), ref_path)
                        elif isinstance(self.config_path, str): # Otherwise, relative to current config file
                            ref_path = os.path.join(os.path.dirname(self.config_path), ref_path)

                    # Determine candidate_index to pass to spawned cascade
                    async_candidate_index = None
                    if self.current_phase_candidate_index is not None:
                        async_candidate_index = self.current_phase_candidate_index
                    elif self.candidate_index is not None:
                        async_candidate_index = self.candidate_index

                    # Call spawn (fire and forget). spawn_cascade handles the threading.
                    # It needs the parent_trace object directly AND parent_session_id AND candidate_index
                    spawn_cascade(ref_path, sub_input, parent_trace=trace, parent_session_id=self.session_id, candidate_index=async_candidate_index)

        # Sub-cascades handling
        if phase.sub_cascades:
            for sub in phase.sub_cascades:
                # Resolve path relative to current config if possible
                ref_path = sub.ref
                if isinstance(self.config_path, str) and not os.path.isabs(ref_path):
                    ref_path = os.path.join(os.path.dirname(self.config_path), ref_path)
                
                # 1. Prepare Input (Context In)
                sub_input = {}
                
                # If context_in=True, we pass the entire current state
                if sub.context_in:
                    sub_input.update(self.echo.state)
                    # Flatten 'input' key if it exists so child can access {{ input.key }} directly
                    if "input" in self.echo.state and isinstance(self.echo.state["input"], dict):
                        sub_input.update(self.echo.state["input"])
                
                # Apply input mapping (overrides state)
                # input_map: {"child_key": "parent_key_or_value"}
                # Basic implementation: if value matches a key in state/input, use it, else treat as literal
                # For now, let's just support simple copying from current input_data or state
                current_context = {**self.echo.state, **(input_data or {})}
                
                for child_key, parent_val in sub.input_map.items():
                    # Check if parent_val is a key in our context
                    if parent_val in current_context:
                        sub_input[child_key] = current_context[parent_val]
                    else:
                        # Treat as literal
                        sub_input[child_key] = parent_val
                
                console.print(f"{indent}  ↳ [bold yellow]Routing to Sub-Cascade: {sub.ref}[/bold yellow] (In:{sub.context_in}, Out:{sub.context_out})")
                log_message(self.session_id, "sub_cascade_start", sub.ref, trace_id=trace.id, parent_id=trace.parent_id, node_type="link")

                # Generate unique sub-cascade session ID (include candidate index if inside soundings)
                # Also determine which candidate_index to pass through to child
                sub_candidate_index = None
                if self.current_phase_candidate_index is not None:
                    # Inside phase-level candidate - include candidate index
                    sub_session_id = f"{self.session_id}_sub_{self.current_phase_candidate_index}"
                    sub_candidate_index = self.current_phase_candidate_index
                elif self.candidate_index is not None:
                    # Inside cascade-level candidate - include candidate index
                    sub_session_id = f"{self.session_id}_sub_{self.candidate_index}"
                    sub_candidate_index = self.candidate_index
                else:
                    # Normal execution - no candidate
                    sub_session_id = f"{self.session_id}_sub"

                # Pass trace context AND HOOKS AND parent_session_id AND candidate_index
                sub_result = run_cascade(ref_path, sub_input, sub_session_id, self.overrides, self.depth + 1, parent_trace=trace, hooks=self.hooks, parent_session_id=self.session_id, candidate_index=sub_candidate_index)

                # 2. Handle Output (Context Out)
                if sub.context_out:
                    # Merge echoes logic
                    self.echo.merge(get_echo(sub_session_id))
                    self._update_graph() # After sub-cascade merge
                else:
                    # If not merging, we might still want to capture the result in lineage?
                    # The sub_result itself is the Echo dict.
                    # Let's add a lineage entry for the sub-cascade execution result
                    # But Echo.merge does this too.
                    # If context_out=False, it's like a black box.
                    pass

        # Loop for rules (max_turns, loop_until)
        max_turns = phase.rules.max_turns or 1
        max_attempts = phase.rules.max_attempts or 1

        response_content = ""
        validation_passed = False

        # We iterate turns.
        phase_history = []
        phase_history.extend(injected_messages)

        # Outer loop for validation attempts (loop_until)
        for attempt in range(max_attempts):
            # Track retry attempt
            self.current_retry_attempt = attempt if max_attempts > 1 else None

            # Update phase progress for visualization
            update_phase_progress(
                self.session_id, self.config.cascade_id, phase.name, self.depth,
                stage="main",
                attempt=attempt + 1,
                max_attempts=max_attempts
            )

            if attempt > 0:
                console.print(f"{indent}[bold yellow]🔄 Validation Retry Attempt {attempt + 1}/{max_attempts}[/bold yellow]")

                # Create retry trace
                retry_trace = trace.create_child("validation_retry", f"attempt_{attempt + 1}")

                # Inject retry instructions if provided
                if phase.rules.retry_instructions:
                    # Render retry instructions with context
                    # Check for both schema and validation errors
                    error_msg = self.echo.state.get("last_schema_error") or self.echo.state.get("last_validation_error", "Validation failed")

                    retry_context = {
                        "input": input_data,
                        "state": self.echo.state,
                        "validation_error": error_msg,
                        "schema_error": self.echo.state.get("last_schema_error", ""),
                        "attempt": attempt + 1,
                        "max_attempts": max_attempts
                    }
                    retry_msg_content = render_instruction(phase.rules.retry_instructions, retry_context)
                else:
                    # Default retry message
                    error_msg = self.echo.state.get("last_schema_error") or self.echo.state.get("last_validation_error", "Validation failed")

                    if self.echo.state.get("last_schema_error"):
                        retry_msg_content = f"Schema validation failed: {error_msg}. Please provide output matching the required schema."
                    else:
                        retry_msg_content = f"The validator rejected your output: {error_msg}. Please revise and try again."

                console.print(f"{indent}  [italic]{retry_msg_content[:150]}...[/italic]")

                retry_msg = {"role": "user", "content": retry_msg_content}
                self.context_messages.append(retry_msg)
                self.echo.add_history(retry_msg, trace_id=retry_trace.id, parent_id=trace.id, node_type="validation_retry",
                                      metadata={
                                          "cell_name": phase.name,
                                          "attempt": attempt + 1,
                                          "max_attempts": max_attempts,
                                          "loop_until": _format_validator_name(phase.rules.loop_until) if phase.rules.loop_until else None,
                                          "semantic_actor": "framework",
                                          "semantic_purpose": "validation_output"
                                      })
                self._update_graph()

            # Turn loop
            for i in range(max_turns):
                # Track turn number
                self.current_turn_number = i if max_turns > 1 else None

                # Update phase progress for visualization
                update_phase_progress(
                    self.session_id, self.config.cascade_id, phase.name, self.depth,
                    turn=i + 1,
                    max_turns=max_turns
                )

                # Hook: Turn Start
                hook_result = self.hooks.on_turn_start(phase.name, i, {
                    "echo": self.echo,
                    "candidate_index": self.current_phase_candidate_index or self.candidate_index,
                })
                turn_injection = ""
                if hook_result.get("action") == HookAction.INJECT:
                    turn_injection = hook_result.get("content")
                    console.print(f"{indent}[bold red]⚡ Turn Injection:[/bold red] {turn_injection}")

                # Trace Turn
                turn_trace = trace.create_child("turn", f"turn_{i+1}")

                # Add turn structure to Echo for visualization
                # Include candidate_index so turn messages group correctly with their candidate branch
                current_sounding = self.current_phase_candidate_index or self.candidate_index
                self.echo.add_history({
                    "role": "structure",
                    "content": f"Turn {i+1}",
                    "node_type": "turn"
                }, trace_id=turn_trace.id, parent_id=trace.id, node_type="turn",
                   metadata={"cell_name": phase.name, "turn_number": i+1, "max_turns": max_turns,
                             "candidate_index": current_sounding,  # Tag with candidate for correct grouping
                             "semantic_actor": "framework", "semantic_purpose": "lifecycle"})

                if max_turns > 1:
                    console.print(f"{indent}  [dim]Turn {i+1}/{max_turns}[/dim]")

                # Determine current_input before calling agent
                # Phase task is already in context_messages as a user message,
                # so turn 0 doesn't need additional input. Subsequent turns get a continuation prompt.
                if turn_injection:
                    current_input = f"USER INJECTION: {turn_injection}"
                elif i == 0:
                    current_input = None  # Phase task already in context_messages as user message
                else:
                    # Use turn_prompt if provided (with Jinja2 templating support)
                    if phase.rules.turn_prompt:
                        turn_render_context = {
                            "input": input_data,
                            "state": self.echo.state,
                            "outputs": outputs,
                            "lineage": self.echo.lineage,
                            "history": self.echo.history,
                            "turn": i + 1,
                            "max_turns": max_turns
                        }
                        current_input = render_instruction(phase.rules.turn_prompt, turn_render_context)
                    else:
                        current_input = "Continue/Refine based on previous output."

                # DEBUG: Show context_messages state before agent call (turn 2+)
                if i > 0:
                    console.print(f"{indent}  [dim cyan][DEBUG] Turn {i+1} context_messages: {len(self.context_messages)} messages[/dim cyan]")
                    for idx, msg in enumerate(self.context_messages[-5:]):  # Show last 5
                        role = msg.get("role", "?")
                        has_tools = "tool_calls" in msg
                        has_tool_id = "tool_call_id" in msg
                        content_preview = str(msg.get("content", ""))[:60]
                        console.print(f"{indent}    [dim][{idx}] {role:10s} | tools:{has_tools} | tool_id:{has_tool_id} | {content_preview}[/dim]")

                try:
                    # Infrastructure retry loop (for API errors, timeouts, empty responses)
                    # This is SEPARATE from validation retries (max_attempts)
                    # Retries up to 3 times for transient infrastructure issues
                    infrastructure_max_retries = 3
                    last_infrastructure_error = None

                    for infra_attempt in range(infrastructure_max_retries):
                        if infra_attempt > 0:
                            console.print(f"{indent}  [bold yellow]🔄 Infrastructure Retry {infra_attempt + 1}/{infrastructure_max_retries}[/bold yellow]")
                            console.print(f"{indent}  [dim]Previous error: {last_infrastructure_error}[/dim]")
                            import time
                            time.sleep(1)  # Brief backoff

                        try:
                            is_main_thread = threading.current_thread() is threading.main_thread()

                            # Cull old content to prevent token explosion
                            from .utils import cull_old_base64_images, cull_old_conversation_history

                            # Get config from environment (with defaults)
                            keep_images = int(os.getenv('RVBBIT_KEEP_RECENT_IMAGES', '0'))
                            keep_turns = int(os.getenv('RVBBIT_KEEP_RECENT_TURNS', '0'))

                            # FIX: Actually update self.context_messages to make culling persistent
                            # This also handles system prompt positioning (moves to front, keeps only most recent)
                            self.context_messages = cull_old_conversation_history(self.context_messages, keep_recent_turns=keep_turns)
                            self.context_messages = cull_old_base64_images(self.context_messages, keep_recent=keep_images)

                            # TOKEN BUDGET ENFORCEMENT: Check and enforce budget before agent call
                            if self.token_manager:
                                budget_status = self.token_manager.check_budget(self.context_messages)

                                if budget_status["warning"]:
                                    percentage = budget_status["percentage"] * 100
                                    console.print(f"{indent}  [yellow]⚠️  Token budget: {percentage:.1f}% used ({budget_status['current']}/{budget_status['limit']} tokens)[/yellow]")

                                if budget_status["over_budget"]:
                                    console.print(f"{indent}  [red]💥 Token budget exceeded, enforcing with strategy: {self.config.token_budget.strategy}[/red]")
                                    self.context_messages = self.token_manager.enforce_budget(self.context_messages)

                                    # Log budget enforcement
                                    from .unified_logs import log_unified
                                    log_unified(
                                        session_id=self.session_id,
                                        trace_id=turn_trace.id,
                                        parent_id=trace.id,
                                        node_type="token_budget_enforcement",
                                        role="system",
                                        content=f"Token budget enforced: {budget_status['current']} → {self.token_manager.count_tokens(self.context_messages)} tokens",
                                        metadata={
                                            "strategy": self.config.token_budget.strategy,
                                            "tokens_before": budget_status["current"],
                                            "tokens_after": self.token_manager.count_tokens(self.context_messages),
                                            "tokens_limit": budget_status["limit"],
                                            "cell_name": phase.name
                                        }
                                    )

                            # AUTO-CONTEXT: Build bounded context for this turn
                            # Check if this is a loop retry (attempt > 0 means we're retrying)
                            is_loop_retry = (
                                phase.rules.loop_until and
                                attempt > 0  # attempt variable tracks validation retries
                            )

                            # Build turn context (may be compressed if auto-context enabled)
                            turn_context, context_stats = self._build_turn_context(
                                phase,
                                turn_number=i,
                                is_loop_retry=is_loop_retry
                            )

                            # Log context selection if auto-context did something
                            if context_stats.selection_type != "disabled":
                                self._log_context_selection(phase, i, context_stats, turn_trace)
                                if context_stats.tokens_saved > 0:
                                    console.print(f"{indent}  [dim cyan]🗜️  Auto-context: {context_stats.context_size}/{context_stats.full_history_size} msgs, ~{context_stats.tokens_saved} tokens saved[/dim cyan]")

                            if self.depth == 0 and is_main_thread:
                                with console.status(f"{indent}[bold green]Agent thinking...[/bold green] ", spinner="dots") as status:
                                    response_dict = agent.run(current_input, context_messages=turn_context)
                            else:
                                # For sub-cascades, no spinner to avoid Rich Live conflicts
                                console.print(f"{indent}[dim]Agent thinking (depth {self.depth})...[/dim]")
                                response_dict = agent.run(current_input, context_messages=turn_context)

                            content = response_dict.get("content")
                            tool_calls = response_dict.get("tool_calls")
                            images = response_dict.get("images")
                            request_id = response_dict.get("id")

                            # CRITICAL: Detect empty responses - this is an infrastructure error
                            # Empty responses indicate API issues, not validation failures
                            # BUT: Image generation models return empty content + images array
                            # So we also check for images in the response
                            if (not content or content.strip() == "") and not tool_calls and not images:
                                error_msg = f"Agent returned empty response (0 tokens output). Model: {phase_model}"
                                console.print(f"{indent}  [bold red]⚠️  Infrastructure Error: {error_msg}[/bold red]")
                                last_infrastructure_error = error_msg

                                # Log the failed request for debugging (even though response was empty)
                                from .unified_logs import log_unified
                                full_request = response_dict.get("full_request")
                                full_response = response_dict.get("full_response")
                                log_unified(
                                    session_id=self.session_id,
                                    parent_session_id=self.parent_session_id,
                                    trace_id=turn_trace.id,
                                    parent_id=trace.id,
                                    node_type="error",
                                    role="error",
                                    content=f"Empty response (0 tokens). Attempt {infra_attempt + 1}/{infrastructure_max_retries}",
                                    model=phase_model,
                                    full_request=full_request,
                                    full_response=full_response,
                                    metadata={
                                        "error_type": "empty_response",
                                        "attempt": infra_attempt + 1,
                                        "max_attempts": infrastructure_max_retries,
                                        "cell_name": phase.name,
                                        "cascade_id": self.config.cascade_id
                                    }
                                )

                                if infra_attempt + 1 >= infrastructure_max_retries:
                                    console.print(f"{indent}  [bold red]Max infrastructure retries reached. Failing.[/bold red]")
                                    raise Exception(error_msg)
                                else:
                                    console.print(f"{indent}  [yellow]Retrying due to empty response...[/yellow]")
                                    continue  # Retry infrastructure loop

                            # Runtime detection of image models:
                            # If we got images but no/empty content, this is an image generation model
                            # that wasn't in our registry. Register it for future runs.
                            if images and (not content or content.strip() == ""):
                                from .model_registry import ModelRegistry
                                if not ModelRegistry.is_image_output_model(phase_model):
                                    console.print(f"{indent}  [cyan]📷 Runtime detected image model: {phase_model}[/cyan]")
                                    ModelRegistry.register_runtime_image_model(phase_model)

                            # Successfully got response, break from infrastructure retry loop
                            break

                        except Exception as infra_error:
                            # Check if this is an infrastructure error (API timeout, connection, etc.)
                            error_str = str(infra_error).lower()
                            is_infrastructure_error = any(keyword in error_str for keyword in [
                                'timeout', 'connection', 'empty response', 'rate limit',
                                'api error', 'service unavailable', '503', '502', '500', '429'
                            ])

                            # Log the failed request if available (Agent attaches full_request to exception)
                            from .unified_logs import log_unified
                            failed_request = getattr(infra_error, 'full_request', None)
                            log_unified(
                                session_id=self.session_id,
                                parent_session_id=self.parent_session_id,
                                trace_id=turn_trace.id,
                                parent_id=trace.id,
                                node_type="error",
                                role="error",
                                content=f"API Error: {type(infra_error).__name__}: {str(infra_error)[:500]}",
                                model=phase_model,
                                full_request=failed_request,
                                metadata={
                                    "error_type": type(infra_error).__name__,
                                    "error_message": str(infra_error)[:1000],
                                    "attempt": infra_attempt + 1,
                                    "max_attempts": infrastructure_max_retries,
                                    "is_infrastructure_error": is_infrastructure_error,
                                    "cell_name": phase.name,
                                    "cascade_id": self.config.cascade_id
                                }
                            )

                            if is_infrastructure_error:
                                last_infrastructure_error = str(infra_error)
                                console.print(f"{indent}  [bold yellow]⚠️  Infrastructure Error: {infra_error}[/bold yellow]")

                                if infra_attempt + 1 >= infrastructure_max_retries:
                                    console.print(f"{indent}  [bold red]Max infrastructure retries reached. Failing.[/bold red]")
                                    raise  # Re-raise to outer exception handler
                                else:
                                    console.print(f"{indent}  [yellow]Retrying infrastructure error...[/yellow]")
                                    continue  # Retry infrastructure loop
                            else:
                                # Not an infrastructure error - raise to outer handler
                                raise

                    # After infrastructure retry loop succeeds, continue with normal flow
                    # Log to unified logger (NON-BLOCKING - cost will be fetched by background worker)
                    # The unified logger queues messages with request_id and fetches cost after ~3s delay
                    from .unified_logs import log_unified

                    # Extract all data from agent response
                    full_request = response_dict.get("full_request")
                    full_response = response_dict.get("full_response")
                    model_used = response_dict.get("model", phase_model)
                    cost = response_dict.get("cost")
                    tokens_in = response_dict.get("tokens_in", 0)
                    tokens_out = response_dict.get("tokens_out", 0)
                    provider = response_dict.get("provider", "unknown")

                    # Extract reasoning token data (OpenRouter extended thinking)
                    reasoning_enabled = response_dict.get("reasoning_enabled")
                    reasoning_effort = response_dict.get("reasoning_effort")
                    reasoning_max_tokens = response_dict.get("reasoning_max_tokens")
                    tokens_reasoning = response_dict.get("tokens_reasoning")

                    # Build metadata
                    agent_metadata = {
                        "retry_attempt": self.current_retry_attempt,
                        "turn_number": self.current_turn_number,
                        "cell_name": phase.name,
                        "cascade_id": self.config.cascade_id
                    }

                    # Get cascade and phase configs for logging
                    cascade_config_dict = self.config.model_dump() if hasattr(self.config, 'model_dump') else None
                    phase_config_dict = phase.model_dump() if hasattr(phase, 'model_dump') else None

                    # Check if this message should be tagged as a callout
                    is_callout = False
                    callout_name = None
                    should_tag, template = self._should_tag_as_callout(phase, 'assistant_message', turn_number=i)
                    if should_tag:
                        is_callout = True
                        callout_name = self._render_callout_name(template, phase, input_data, turn_number=i)

                    # LOG WITH UNIFIED SYSTEM (immediate write with all context)
                    log_unified(
                        session_id=self.session_id,
                        trace_id=turn_trace.id,
                        parent_id=turn_trace.parent_id,
                        parent_session_id=getattr(self, 'parent_session_id', None),
                        parent_message_id=getattr(self, 'parent_message_id', None),
                        node_type="agent",
                        role="assistant",
                        depth=self.depth,
                        candidate_index=self.current_phase_candidate_index,
                        is_winner=None,  # Set later when candidate evaluation happens
                        reforge_step=getattr(self, 'current_reforge_step', None),
                        attempt_number=self.current_retry_attempt,
                        turn_number=self.current_turn_number,
                        mutation_applied=self.current_mutation_applied,
                        mutation_type=self.current_mutation_type,
                        mutation_template=self.current_mutation_template,
                        cascade_id=self.config.cascade_id,
                        cascade_file=self.config_path if isinstance(self.config_path, str) else None,
                        cascade_config=cascade_config_dict,
                        cell_name=phase.name,
                        phase_config=phase_config_dict,
                        species_hash=phase_species_hash,  # Species hash for winner learning (rewrite mode only)
                        model=model_used,              # Resolved model from API response
                        model_requested=phase_model,  # Originally requested model from config
                        request_id=request_id,
                        provider=provider,
                        duration_ms=None,  # Not tracking per-message duration yet
                        tokens_in=tokens_in,
                        tokens_out=tokens_out,
                        cost=cost,
                        reasoning_enabled=reasoning_enabled,
                        reasoning_effort=reasoning_effort,
                        reasoning_max_tokens=reasoning_max_tokens,
                        tokens_reasoning=tokens_reasoning,
                        content=content,
                        full_request=full_request,
                        full_response=full_response,
                        tool_calls=tool_calls,
                        images=None,  # Images handled separately
                        has_base64=False,
                        is_callout=is_callout,
                        callout_name=callout_name,
                        metadata=agent_metadata
                    )

                    if content:
                        console.print(Panel(Markdown(content), title=f"Agent ({phase_model})", border_style="green", expand=False))
                
                    # Update histories (Snowball)
                    if current_input:
                         self.context_messages.append({"role": "user", "content": current_input})
                
                    assistant_msg = {"role": "assistant", "content": content}
                    # Only add tool_calls field when using native tools
                    # For prompt-based tools, the tool call JSON is already in content
                    if tool_calls and use_native:
                        assistant_msg["tool_calls"] = tool_calls
                    self.context_messages.append(assistant_msg)

                    # Add to Echo (global history)
                    input_trace = turn_trace.create_child("msg", "user_input")
                    if current_input:
                         self.echo.add_history({"role": "user", "content": current_input}, trace_id=input_trace.id, parent_id=turn_trace.id, node_type="turn_input",
                                             metadata=self._get_metadata({"cell_name": phase.name, "turn": i},
                                                                         semantic_actor="framework", semantic_purpose="task_input"))

                    # Add assistant response to Echo (needed for message injection in context.from)
                    # skip_unified_log=True because we already logged this response above with full LLM metadata
                    output_trace = turn_trace.create_child("msg", "assistant_output")
                    self.echo.add_history({"role": "assistant", "content": content}, trace_id=output_trace.id, parent_id=turn_trace.id, node_type="agent",
                                         metadata=self._get_metadata({"cell_name": phase.name, "turn": i},
                                                                     semantic_purpose="generation"),
                                         skip_unified_log=True)

                    self._update_graph()

                    # Publish turn_complete event (for narrator and other subscribers)
                    # Include recent conversation history so narrator has full context
                    recent_history = self.echo.history[-10:] if len(self.echo.history) > 0 else []
                    self._publish_event("turn_complete", {
                        "cell_name": phase.name,
                        "cascade_id": self.config.cascade_id,
                        "turn_number": i + 1,
                        "max_turns": max_turns,
                        "tool_calls": [{"name": tc.get("function", {}).get("name", "unknown")} for tc in (tool_calls or [])],
                        "trace_id": turn_trace.id if turn_trace else None,
                        "recent_history": recent_history,  # Last 10 messages from echo
                        "assistant_response": content,  # The response content from this turn
                    })

                    response_content = content
                    tool_outputs = []  # Track tool outputs for validation

                    # Parse prompt-based tool calls if not using native tools
                    json_parse_error = None
                    if not use_native and not tool_calls:
                        # Try to extract JSON tool calls from the response content
                        parsed_tool_calls, parse_error = self._parse_prompt_tool_calls(content)

                        if parse_error:
                            # JSON parsing failed - this is a validation error that should trigger attempt retry
                            console.print(f"{indent}  [bold red]⚠️  JSON Parse Error:[/bold red] {parse_error}")

                            # Store error in state for retry message
                            self.echo.update_state("last_validation_error", f"Tool call JSON is malformed: {parse_error}")

                            # Log the error
                            error_trace = turn_trace.create_child("msg", "json_error")
                            log_message(self.session_id, "json_parse_error", parse_error,
                                       metadata={"cell_name": phase.name, "turn": i},
                                       trace_id=error_trace.id, parent_id=turn_trace.parent_id, node_type="validation_error")

                            # Add error to echo history
                            error_msg = {
                                "role": "user",
                                "content": f"⚠️ Tool Call JSON Error:\n{parse_error}\n\nPlease fix the JSON and try again. Ensure proper brace matching: {{ and }}"
                            }
                            self.echo.add_history(error_msg, trace_id=error_trace.id, parent_id=turn_trace.id, node_type="validation_error",
                                                metadata=self._get_metadata({"cell_name": phase.name, "turn": i},
                                                                            semantic_actor="framework", semantic_purpose="validation_output"))

                            # CRITICAL: Set validation_passed = False to trigger attempt retry
                            # JSON errors should retry the entire attempt, not just skip to next turn
                            validation_passed = False
                            json_parse_error = True

                            # Break from turn loop - will check validation_passed and retry if needed
                            break

                        elif parsed_tool_calls:
                            console.print(f"{indent}  [dim cyan]Parsed {len(parsed_tool_calls)} prompt-based tool call(s)[/dim cyan]")
                            tool_calls = parsed_tool_calls

                    # ================================================================
                    # HTML Auto-Correction: Always check for HTML code fences
                    # This runs regardless of native/prompt mode or existing tool_calls
                    # Models sometimes output HTML in code fences instead of using
                    # request_decision - we auto-inject it as a request_decision call
                    # Tool execution falls back to global registry, so no need to add to tool_map
                    # ================================================================
                    if content and not json_parse_error:
                        html_auto_calls = self._auto_correct_html_to_request_decision(content, tool_calls or [])
                        if html_auto_calls:
                            if tool_calls is None:
                                tool_calls = []
                            tool_calls = list(tool_calls) + html_auto_calls

                    # Handle tool calls (both native and prompt-based)
                    # Skip if there was a JSON parse error
                    if tool_calls and not json_parse_error:
                        console.print(f"{indent}  [bold yellow]Executing Tools...[/bold yellow]")
                        for tc in tool_calls:
                            # Trace Tool
                            func_name = tc["function"]["name"]
                            tool_trace = turn_trace.create_child("tool", func_name)
                        
                            args_str = tc["function"]["arguments"]
                            # Parse args
                            try:
                                args = json.loads(args_str)
                            except:
                                args = {}

                            # Add to echo history for visualization (auto-logs via unified_logs)
                            call_trace = tool_trace.create_child("msg", "tool_call")
                            self.echo.add_history(
                                {"role": "tool_call", "content": f"Calling {func_name}", "tool_name": func_name, "arguments": args},
                                trace_id=call_trace.id, parent_id=tool_trace.id, node_type="tool_call",
                                metadata=self._get_metadata({"tool_name": func_name, "arguments": args},
                                                           semantic_purpose="tool_request")
                            )

                            # Update phase progress with current tool
                            update_phase_progress(
                                self.session_id, self.config.cascade_id, phase.name, self.depth,
                                tool_name=func_name
                            )

                            # Find tool - first check phase tool_map, then fall back to global registry
                            tool_func = tool_map.get(func_name)
                            if not tool_func:
                                # Fallback to global tool registry - phase tackle only controls prompting
                                tool_func = get_trait(func_name)
                            result = "Tool not found."
                        
                            # Check for route_to specifically to capture state
                            if func_name == "route_to" and "target" in args:
                                chosen_next_phase = args["target"]
                                console.print(f"{indent}  🚀 [bold magenta]Dynamic Handoff Triggered:[/bold magenta] {chosen_next_phase}")
                        
                            if tool_func:
                                 # TOOL CACHING: Check cache before execution
                                 cached_result = None
                                 if self.tool_cache:
                                     cached_result = self.tool_cache.get(func_name, args)
                                     if cached_result is not None:
                                         # Cache hit!
                                         policy = self.tool_cache.config.tools.get(func_name)
                                         hit_msg = policy.hit_message if policy and policy.hit_message else f"⚡ Cache hit ({func_name})"
                                         console.print(f"{indent}    [dim green]{hit_msg}[/dim green]")
                                         result = cached_result

                                         # Hook: Tool Result (cached)
                                         self.hooks.on_tool_result(func_name, phase.name, self.session_id, cached_result)

                                 if cached_result is None:
                                     # Cache miss or caching disabled - execute normally
                                     # Set context for tool (e.g. spawn_cascade)
                                     set_current_trace(tool_trace)
                                     try:
                                         # Hook: Tool Call
                                         self.hooks.on_tool_call(func_name, phase.name, self.session_id, args)

                                         result = tool_func(**args)

                                         # Hook: Tool Result
                                         self.hooks.on_tool_result(func_name, phase.name, self.session_id, result)

                                         # TOOL CACHING: Store result after successful execution
                                         if self.tool_cache:
                                             self.tool_cache.set(func_name, args, result)

                                     except Exception as e:
                                         result = f"Error: {str(e)}"

                                 console.print(f"{indent}    [green]✔ {func_name}[/green] -> {str(result)[:100]}...")

                                 # Capture tool output for validation
                                 tool_outputs.append({
                                     "tool": func_name,
                                     "result": str(result)
                                 })
                                 console.print(f"{indent}    [dim cyan][DEBUG] tool_outputs.append() - now has {len(tool_outputs)} item(s)[/dim cyan]")

                                 # Publish tool_complete event (for narrator and other subscribers)
                                 # Include tool result so narrator knows what the tool did
                                 self._publish_event("tool_complete", {
                                     "cell_name": phase.name,
                                     "cascade_id": self.config.cascade_id,
                                     "tool_name": func_name,
                                     "tool_result": str(result)[:500],  # First 500 chars of result
                                     "turn_number": i + 1,
                                     "max_turns": max_turns,
                                     "trace_id": turn_trace.id if turn_trace else None,
                                 })

                            # Handle Smart Image Injection logic
                            parsed_result = result
                            image_injection_message = None
                        
                            if isinstance(result, str):
                                try:
                                    parsed_result = json.loads(result)
                                except:
                                    pass
                        
                            if isinstance(parsed_result, dict) and "images" in parsed_result:
                                # It's a multi-modal tool response!
                                # We keep the TOOL message as valid JSON string (for LLM to read as tool output)
                                # But we inject a NEW User message afterwards with the image.

                                images = parsed_result.get("images", [])
                                content_block = [{"type": "text", "text": "Result Images from tool:"}]

                                valid_images = 0
                                saved_image_paths = []

                                # Get the next available index to avoid overwriting existing images
                                from .utils import get_image_save_path, decode_and_save_image, get_next_image_index
                                next_idx = get_next_image_index(self.session_id, phase.name, self.current_phase_candidate_index)

                                for i, img_path in enumerate(images):
                                    encoded_img = encode_image_base64(img_path)
                                    if not encoded_img.startswith("[Error"):
                                        content_block.append({
                                            "type": "image_url",
                                            "image_url": {"url": encoded_img}
                                        })
                                        valid_images += 1

                                        # Auto-save image to structured directory
                                        save_path = get_image_save_path(
                                            self.session_id,
                                            phase.name,
                                            next_idx + i,
                                            extension=img_path.split('.')[-1] if '.' in img_path else 'png',
                                            candidate_index=self.current_phase_candidate_index
                                        )
                                        try:
                                            decode_and_save_image(encoded_img, save_path)
                                            saved_image_paths.append(save_path)
                                            console.print(f"{indent}    [dim]💾 Saved image: {save_path}[/dim]")
                                            self._maybe_render_image_to_console(save_path, indent)
                                        except Exception as e:
                                            console.print(f"{indent}    [dim yellow]⚠️  Failed to save image: {e}[/dim yellow]")
                                    else:
                                        content_block.append({"type": "text", "text": f"[Image Error: {img_path}]"})

                                if valid_images > 0:
                                    image_injection_message = {"role": "user", "content": content_block}
                                    console.print(f"{indent}    [bold magenta]📸 Injecting {valid_images} images into next turn[/bold magenta]")

                            # Handle audio files (similar to images, but no LLM injection)
                            if isinstance(parsed_result, dict) and "audio" in parsed_result:
                                audio_files = parsed_result.get("audio", [])
                                saved_audio_paths = []

                                # Get the next available index to avoid overwriting existing audio
                                from .utils import get_audio_save_path, get_next_audio_index
                                import shutil
                                next_audio_idx = get_next_audio_index(self.session_id, phase.name, self.current_phase_candidate_index)

                                for i, audio_path in enumerate(audio_files):
                                    if os.path.exists(audio_path):
                                        # Save audio to structured directory
                                        save_path = get_audio_save_path(
                                            self.session_id,
                                            phase.name,
                                            next_audio_idx + i,
                                            extension=audio_path.split('.')[-1] if '.' in audio_path else 'mp3',
                                            candidate_index=self.current_phase_candidate_index
                                        )
                                        try:
                                            os.makedirs(os.path.dirname(save_path), exist_ok=True)
                                            shutil.copy2(audio_path, save_path)
                                            saved_audio_paths.append(save_path)
                                            console.print(f"{indent}    [dim]🔊 Saved audio: {save_path}[/dim]")
                                        except Exception as e:
                                            console.print(f"{indent}    [dim yellow]⚠️  Failed to save audio: {e}[/dim yellow]")
                                    else:
                                        console.print(f"{indent}    [dim yellow]⚠️  Audio file not found: {audio_path}[/dim yellow]")

                            # Add tool result message
                            # Native tools use role="tool" with tool_call_id
                            # Prompt-based tools use role="user" to avoid provider-specific formats
                            if use_native:
                                tool_msg = {"role": "tool", "tool_call_id": tc["id"], "content": str(result)}
                            else:
                                tool_msg = {"role": "user", "content": f"Tool Result ({func_name}):\n{str(result)}"}
                            self.context_messages.append(tool_msg)

                            # DEBUG: Verify tool result was added
                            console.print(f"{indent}    [dim cyan][DEBUG] Tool result added to context_messages[/dim cyan]")
                            console.print(f"{indent}    [dim]  Index: {len(self.context_messages)-1}, Tool: {func_name}, Result: {len(str(result))} chars[/dim]")

                            # Add to Echo (auto-logs via unified_logs)
                            result_trace = tool_trace.create_child("msg", "tool_result")
                            self.echo.add_history(tool_msg, trace_id=result_trace.id, parent_id=tool_trace.id, node_type="tool_result",
                                                 metadata=self._get_metadata({"tool_name": func_name, "result": str(result)[:500]},
                                                                             semantic_actor="framework", semantic_purpose="tool_response"))

                            # Inject Image Message if present
                            if image_injection_message:
                                self.context_messages.append(image_injection_message)
                                img_trace = tool_trace.create_child("msg", "image_injection")
                                self.echo.add_history(image_injection_message, trace_id=img_trace.id, parent_id=tool_trace.id, node_type="injection",
                                                     metadata=self._get_metadata({"cell_name": phase.name},
                                                                                 semantic_actor="framework", semantic_purpose="context_injection"))

                            self._update_graph() # Update after tool

                        # Immediate follow-up
                        # Cull old content to prevent token explosion
                        from .utils import cull_old_base64_images, cull_old_conversation_history

                        # Get config from environment (with defaults)
                        keep_images = int(os.getenv('RVBBIT_KEEP_RECENT_IMAGES', '0'))
                        keep_turns = int(os.getenv('RVBBIT_KEEP_RECENT_TURNS', '0'))

                        # FIX: Actually update self.context_messages (not just temporary variable!)
                        # Previous bug: culling was temporary, never persisted, all images accumulated
                        self.context_messages = cull_old_conversation_history(self.context_messages, keep_recent_turns=keep_turns)

                        # For follow-up, keep ONLY the most recent image (for iterative feedback)
                        # This retains the latest generated image while dropping all older ones
                        # Rationale: Agent already saw old images, they're saved to disk, only need latest for refinement
                        self.context_messages = cull_old_base64_images(self.context_messages, keep_recent=1)

                        # AUTO-CONTEXT: Rebuild context for follow-up (after tool results added)
                        followup_context, followup_stats = self._build_turn_context(
                            phase,
                            turn_number=i,
                            is_loop_retry=False  # Follow-ups are not loop retries
                        )

                        if self.depth == 0 and is_main_thread:
                            with console.status(f"{indent}[bold green]Agent processing results...[/bold green]", spinner="dots") as status:
                                follow_up = agent.run(None, context_messages=followup_context)
                        else:
                            console.print(f"{indent}[dim]Agent processing results (depth {self.depth})...[/dim]")
                            follow_up = agent.run(None, context_messages=followup_context)
                         
                        content = follow_up.get("content")
                        request_id = follow_up.get("id")
                        model_used = follow_up.get("model", self.model)
                        provider = follow_up.get("provider", "unknown")
                        full_request = follow_up.get("full_request")  # Capture full request
                        full_response = follow_up.get("full_response")  # Capture full response

                        # Extract reasoning token data (OpenRouter extended thinking)
                        followup_reasoning_enabled = follow_up.get("reasoning_enabled")
                        followup_reasoning_effort = follow_up.get("reasoning_effort")
                        followup_reasoning_max_tokens = follow_up.get("reasoning_max_tokens")
                        followup_tokens_reasoning = follow_up.get("tokens_reasoning")

                        # NOTE: Don't call track_request() - old async cost system is deprecated
                        # Cost tracking now handled by unified_logs.py non-blocking worker

                        if content:
                            console.print(Panel(Markdown(content), title=f"Agent ({self.model})", border_style="green", expand=False))

                            # ONLY add to message history if content is non-empty
                            # Empty assistant messages violate Anthropic's API requirements
                            assistant_msg = {"role": "assistant", "content": content}
                            self.context_messages.append(assistant_msg)

                            followup_trace = turn_trace.create_child("msg", "follow_up")

                            # Log to unified system with full context for cost tracking
                            # IMPORTANT: Include full_request and full_response so we can see what was actually sent
                            from .unified_logs import log_unified
                            log_unified(
                                session_id=self.session_id,
                                parent_session_id=self.parent_session_id,
                                trace_id=followup_trace.id,
                                parent_id=turn_trace.id,
                                node_type="follow_up",
                                role="assistant",
                                depth=self.depth,
                                cell_name=phase.name,
                                cascade_id=self.config.cascade_id,
                                model=model_used,
                                request_id=request_id,  # For non-blocking cost tracking
                                provider=provider,
                                content=content,
                                full_request=full_request,  # ADD: Include complete request with images
                                full_response=full_response,  # ADD: Include complete response
                                candidate_index=self.current_phase_candidate_index or self.candidate_index,  # FIX: Tag with candidate
                                reforge_step=getattr(self, 'current_reforge_step', None),  # FIX: Tag with reforge
                                reasoning_enabled=followup_reasoning_enabled,
                                reasoning_effort=followup_reasoning_effort,
                                reasoning_max_tokens=followup_reasoning_max_tokens,
                                tokens_reasoning=followup_tokens_reasoning,
                                metadata=self._get_metadata({"is_follow_up": True, "turn_number": self.current_turn_number})
                            )

                            self._update_graph() # Update after follow up
                            response_content = content

                            # CRITICAL FIX: Check if follow-up contains tool calls
                            # This enables multi-step tool chains (e.g., create_chart -> ask_human_custom)
                            # Without this, tool calls in follow-up responses are ignored
                            if not use_native:
                                followup_tool_calls, followup_parse_error = self._parse_prompt_tool_calls(content)

                                if followup_parse_error:
                                    console.print(f"{indent}  [bold red]⚠️  Follow-up JSON Parse Error:[/bold red] {followup_parse_error}")
                                elif followup_tool_calls:
                                    console.print(f"{indent}  [dim cyan]Follow-up contains {len(followup_tool_calls)} tool call(s) - executing...[/dim cyan]")

                                    # Execute the follow-up tool calls
                                    for tc in followup_tool_calls:
                                        func_name = tc["function"]["name"]
                                        tool_trace_fu = turn_trace.create_child("tool", f"followup_{func_name}")

                                        args_str = tc["function"]["arguments"]
                                        try:
                                            args = json.loads(args_str)
                                        except:
                                            args = {}

                                        # Log tool call
                                        call_trace_fu = tool_trace_fu.create_child("msg", "tool_call")
                                        self.echo.add_history(
                                            {"role": "tool_call", "content": f"Calling {func_name} (follow-up)", "tool_name": func_name, "arguments": args},
                                            trace_id=call_trace_fu.id, parent_id=tool_trace_fu.id, node_type="tool_call",
                                            metadata=self._get_metadata({"tool_name": func_name, "arguments": args, "is_followup": True},
                                                                        semantic_purpose="tool_request")
                                        )

                                        # Update phase progress
                                        update_phase_progress(
                                            self.session_id, self.config.cascade_id, phase.name, self.depth,
                                            tool_name=func_name
                                        )

                                        # Find and execute tool - check phase tool_map, then global registry
                                        tool_func = tool_map.get(func_name)
                                        if not tool_func:
                                            tool_func = get_trait(func_name)
                                        result = "Tool not found."

                                        # Check for route_to
                                        if func_name == "route_to" and "target" in args:
                                            chosen_next_phase = args["target"]
                                            console.print(f"{indent}  🚀 [bold magenta]Dynamic Handoff Triggered (follow-up):[/bold magenta] {chosen_next_phase}")

                                        if tool_func:
                                            set_current_trace(tool_trace_fu)
                                            try:
                                                self.hooks.on_tool_call(func_name, phase.name, self.session_id, args)
                                                result = tool_func(**args)
                                                self.hooks.on_tool_result(func_name, phase.name, self.session_id, result)
                                            except Exception as e:
                                                result = f"Error: {str(e)}"

                                        console.print(f"{indent}    [green]✔ {func_name} (follow-up)[/green] -> {str(result)[:100]}...")

                                        # Track tool output
                                        tool_outputs.append({
                                            "tool": func_name,
                                            "result": str(result)
                                        })

                                        # Publish tool_complete event (follow-up)
                                        # Include tool result so narrator knows what the tool did
                                        self._publish_event("tool_complete", {
                                            "cell_name": phase.name,
                                            "cascade_id": self.config.cascade_id,
                                            "tool_name": func_name,
                                            "tool_result": str(result)[:500],  # First 500 chars of result
                                            "turn_number": i + 1,
                                            "max_turns": max_turns,
                                            "trace_id": turn_trace.id if turn_trace else None,
                                        })

                                        # Add tool result to context
                                        tool_msg_fu = {"role": "user", "content": f"Tool Result ({func_name}):\n{str(result)}"}
                                        self.context_messages.append(tool_msg_fu)

                                        # Log to echo
                                        result_trace_fu = tool_trace_fu.create_child("msg", "tool_result")
                                        self.echo.add_history(tool_msg_fu, trace_id=result_trace_fu.id, parent_id=tool_trace_fu.id, node_type="tool_result",
                                                            metadata=self._get_metadata({"tool_name": func_name, "result": str(result)[:500], "is_followup": True},
                                                                                        semantic_actor="framework", semantic_purpose="tool_response"))

                                        # Handle image injection from follow-up tools
                                        parsed_result = result
                                        if isinstance(result, str):
                                            try:
                                                parsed_result = json.loads(result)
                                            except:
                                                pass

                                        if isinstance(parsed_result, dict) and "images" in parsed_result:
                                            images = parsed_result.get("images", [])
                                            content_block = [{"type": "text", "text": "Result Images from follow-up tool:"}]

                                            from .utils import get_image_save_path, decode_and_save_image, get_next_image_index
                                            next_idx = get_next_image_index(self.session_id, phase.name, self.current_phase_candidate_index)

                                            for img_i, img_path in enumerate(images):
                                                encoded_img = encode_image_base64(img_path)
                                                if not encoded_img.startswith("[Error"):
                                                    content_block.append({
                                                        "type": "image_url",
                                                        "image_url": {"url": encoded_img}
                                                    })

                                                    save_path = get_image_save_path(
                                                        self.session_id, phase.name, next_idx + img_i,
                                                        extension=img_path.split('.')[-1] if '.' in img_path else 'png',
                                                        candidate_index=self.current_phase_candidate_index
                                                    )
                                                    try:
                                                        decode_and_save_image(encoded_img, save_path)
                                                        console.print(f"{indent}    [dim]💾 Saved follow-up image: {save_path}[/dim]")
                                                    except Exception as e:
                                                        console.print(f"{indent}    [dim yellow]⚠️  Failed to save follow-up image: {e}[/dim yellow]")

                                            if len(content_block) > 1:
                                                image_injection_msg = {"role": "user", "content": content_block}
                                                self.context_messages.append(image_injection_msg)
                                                img_trace_fu = tool_trace_fu.create_child("msg", "image_injection")
                                                self.echo.add_history(image_injection_msg, trace_id=img_trace_fu.id, parent_id=tool_trace_fu.id, node_type="injection",
                                                                    metadata=self._get_metadata({"cell_name": phase.name, "is_followup": True},
                                                                                                semantic_actor="framework", semantic_purpose="context_injection"))

                                        self._update_graph()
                        else:
                            # Log that follow-up had no content (don't add to history - would cause API error)
                            log_message(self.session_id, "system", "Follow-up response had empty content (not added to history)",
                                       trace_id=turn_trace.id, parent_id=turn_trace.parent_id, node_type="warning", depth=turn_trace.depth)

                        # Auto-save any images from messages (catches manual injection, feedback loops, etc.)
                        self._save_images_from_messages(self.context_messages, phase.name)

                    # ========== AUDIBLE CHECK ==========
                    # Check if user has signaled an audible (feedback injection)
                    # This happens at the end of each turn, after processing but before validation
                    if self._check_audible_signal(phase):
                        # Handle the audible - creates checkpoint and waits for feedback
                        feedback = self._handle_audible(phase, response_content, i, turn_trace)

                        if feedback:
                            mode = feedback.get("mode", "continue")

                            # Inject the feedback as a user message
                            self._inject_audible_feedback(feedback, phase, turn_trace)

                            # Handle retry mode - don't save this turn's output, redo it
                            if mode == "retry":
                                console.print(f"{indent}  [bold yellow]🔄 Retry mode - redoing turn {i + 1}[/bold yellow]")
                                # Remove the last assistant message from context (the one we're retrying)
                                # Find and remove the last assistant message
                                for j in range(len(self.context_messages) - 1, -1, -1):
                                    if self.context_messages[j].get("role") == "assistant":
                                        self.context_messages.pop(j)
                                        break
                                # Don't increment turn counter - will redo this turn
                                continue

                            # Continue mode - feedback injected, next turn will see it
                            # Don't break - let the turn loop continue naturally

                    # Build comprehensive validation content (agent response + tool outputs + follow-up)
                    # This ensures validators see the COMPLETE turn output, not just the agent's text
                    console.print(f"{indent}  [dim cyan][DEBUG] Building validation content: tool_outputs has {len(tool_outputs)} item(s)[/dim cyan]")
                    if tool_outputs:
                        validation_content_parts = []
                        if response_content:
                            validation_content_parts.append(f"Agent Response:\n{response_content}\n")

                        validation_content_parts.append("Tool Execution Results:")
                        for tool_output in tool_outputs:
                            validation_content_parts.append(f"\n[{tool_output['tool']}]:\n{tool_output['result']}\n")

                        response_content = "\n".join(validation_content_parts)
                        console.print(f"{indent}  [dim green][DEBUG] Validation content built: {len(response_content)} chars total[/dim green]")
                    else:
                        console.print(f"{indent}  [dim yellow][DEBUG] tool_outputs is empty - validator will only see agent response![/dim yellow]")

                    # ========== PER-TURN LOOP_UNTIL VALIDATION ==========
                    # Check if task is complete after each turn to enable early exit from turn loop.
                    # This prevents unnecessary context snowballing when the task is done early.
                    # Only runs if loop_until is configured and we have more turns remaining.
                    if phase.rules.loop_until and i < max_turns - 1:
                        per_turn_result = self._run_loop_until_validator(
                            validator_spec=phase.rules.loop_until,
                            content=response_content,
                            input_data=input_data,
                            trace=turn_trace,
                            attempt=attempt,
                            turn=i,
                            is_per_turn=True
                        )

                        if per_turn_result.get("valid"):
                            # Task complete! Exit turn loop early to avoid unnecessary snowballing
                            validation_passed = True
                            console.print(f"{indent}  [bold cyan]🚀 Early exit: Task complete after turn {i + 1}/{max_turns}[/bold cyan]")
                            break  # Exit turn loop

                except Exception as e:
                    # Enhanced error logging with detailed information
                    import traceback

                    error_type = type(e).__name__
                    error_msg = str(e)
                    error_tb = traceback.format_exc()

                    # Build comprehensive error metadata
                    error_metadata = {
                        "error_type": error_type,
                        "error_message": error_msg,
                        "cell_name": phase.name,
                        "turn_number": self.current_turn_number,
                        "model": phase_model,
                        "cascade_id": self.config.cascade_id,
                    }

                    # Try to extract more details from the exception
                    if hasattr(e, 'response'):
                        try:
                            error_metadata["http_status"] = e.response.status_code
                            error_metadata["http_response"] = e.response.text[:500]
                        except:
                            pass

                    if hasattr(e, '__dict__'):
                        error_metadata["exception_attributes"] = {
                            k: str(v)[:200] for k, v in e.__dict__.items() if not k.startswith('_')
                        }

                    # Print detailed error to console
                    console.print(f"[bold red]Error in Agent call:[/bold red] {error_type}: {error_msg}")
                    console.print(f"[dim]Phase: {phase.name}, Turn: {self.current_turn_number}[/dim]")
                    if "http_status" in error_metadata:
                        console.print(f"[dim]HTTP Status: {error_metadata['http_status']}[/dim]")
                        console.print(f"[dim]Response: {error_metadata['http_response'][:200]}...[/dim]")

                    # Log with full details including traceback
                    full_error_msg = f"{error_type}: {error_msg}\n\nTraceback:\n{error_tb}"
                    log_message(self.session_id, "error", full_error_msg,
                               trace_id=turn_trace.id, parent_id=turn_trace.parent_id,
                               node_type="error", metadata=error_metadata)

                    # Add to history with context
                    error_content = f"Error: {error_type}: {error_msg}"
                    if "http_status" in error_metadata:
                        error_content += f"\nHTTP Status: {error_metadata['http_status']}"
                        error_content += f"\nProvider Response: {error_metadata.get('http_response', 'N/A')[:200]}"

                    error_metadata["semantic_actor"] = "framework"
                    error_metadata["semantic_purpose"] = "validation_output"
                    self.echo.add_history(
                        {"role": "system", "content": error_content},
                        trace_id=turn_trace.id,
                        parent_id=turn_trace.parent_id,
                        node_type="error",
                        metadata=error_metadata
                    )

                    # Track error in echo for cascade-level status
                    self.echo.add_error(
                        cell=phase.name,
                        error_type=error_type,
                        error_message=error_msg,
                        metadata=error_metadata
                    )

                    # Store error in state for retry message
                    self.echo.update_state("last_validation_error", error_msg)

                    self._update_graph()
                    break  # Break from turn loop, continue to validation/next attempt

            # After turn loop: Check if schema validation is required (output_schema)
            if phase.output_schema:
                console.print(f"{indent}[bold cyan]📋 Validating Output Schema...[/bold cyan]")

                # Create schema validation trace
                schema_trace = trace.create_child("schema_validation", "output_schema")

                try:
                    import jsonschema
                    from jsonschema import ValidationError

                    # Try to parse response as JSON
                    try:
                        # First try to parse the entire response as JSON
                        output_data = json.loads(response_content)
                    except json.JSONDecodeError:
                        # If that fails, try to extract JSON from markdown code blocks
                        import re
                        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_content, re.DOTALL)
                        if json_match:
                            output_data = json.loads(json_match.group(1))
                        else:
                            # Try to find any JSON object in the response
                            json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', response_content, re.DOTALL)
                            if json_match:
                                output_data = json.loads(json_match.group(0))
                            else:
                                # No JSON found
                                raise json.JSONDecodeError("No valid JSON found in response", response_content, 0)

                    # Validate against schema
                    jsonschema.validate(instance=output_data, schema=phase.output_schema)

                    console.print(f"{indent}  [bold green]✓ Schema Validation Passed[/bold green]")
                    log_message(self.session_id, "schema_validation", "Schema validation passed",
                               {"schema": phase.output_schema},
                               trace_id=schema_trace.id, parent_id=trace.id,
                               node_type="schema_validation", depth=self.depth)

                    # Add to echo history for visualization
                    self.echo.add_history({
                        "role": "schema_validation",
                        "content": "✓ Schema validation passed",
                        "node_type": "schema_validation"
                    }, trace_id=schema_trace.id, parent_id=trace.id, node_type="schema_validation",
                       metadata={
                           "cell_name": phase.name,
                           "valid": True,
                           "attempt": attempt + 1,
                           "semantic_actor": "framework",
                           "semantic_purpose": "validation_output"
                       })

                    # Store the validated JSON in state
                    self.echo.update_state("validated_output", output_data)
                    validation_passed = True

                except (json.JSONDecodeError, ValidationError) as e:
                    # Schema validation failed
                    if isinstance(e, json.JSONDecodeError):
                        error_msg = f"Output is not valid JSON: {str(e)}"
                    else:
                        # Format the schema error for the LLM
                        error_msg = f"Schema validation failed: {e.message}"
                        if hasattr(e, 'path') and e.path:
                            path_str = '.'.join(str(p) for p in e.path)
                            error_msg += f" at path '{path_str}'"

                    console.print(f"{indent}  [bold red]✗ Schema Validation Failed:[/bold red] {error_msg}")

                    # Store error for retry
                    self.echo.update_state("last_schema_error", error_msg)

                    log_message(self.session_id, "schema_validation_failed", error_msg,
                               {"schema": phase.output_schema, "attempt": attempt + 1},
                               trace_id=schema_trace.id, parent_id=trace.id,
                               node_type="schema_validation_failed", depth=self.depth)

                    # Add to echo history for visualization
                    self.echo.add_history({
                        "role": "schema_validation",
                        "content": f"✗ Schema: {error_msg[:80]}",
                        "node_type": "schema_validation"
                    }, trace_id=schema_trace.id, parent_id=trace.id, node_type="schema_validation",
                       metadata={
                           "cell_name": phase.name,
                           "valid": False,
                           "reason": error_msg,
                           "attempt": attempt + 1,
                           "max_attempts": max_attempts,
                           "semantic_actor": "framework",
                           "semantic_purpose": "validation_output"
                       })

                    validation_passed = False

                    # If this was the last attempt, we're done
                    if attempt + 1 >= max_attempts:
                        console.print(f"{indent}[bold red]⚠️  Max schema validation attempts reached ({max_attempts})[/bold red]")
                    else:
                        # Continue to next attempt - the retry message will be injected at the start of the next iteration
                        continue

                except Exception as e:
                    console.print(f"{indent}  [bold red]Schema Validation Error:[/bold red] {str(e)}")
                    log_message(self.session_id, "schema_validation_error", str(e),
                               trace_id=schema_trace.id, parent_id=trace.id,
                               node_type="error", depth=self.depth)
                    validation_passed = False
                    if attempt + 1 >= max_attempts:
                        break
                    else:
                        continue

            # After schema validation: Check if validator is required (loop_until)
            # Skip if validation already passed from per-turn early exit
            if phase.rules.loop_until and not validation_passed:
                validator_spec = phase.rules.loop_until
                validator_display_name = _format_validator_name(validator_spec)
                console.print(f"{indent}[bold cyan]🛡️  Running Validator: {validator_display_name}[/bold cyan]")

                # Create validation trace
                validation_trace = trace.create_child("validation", validator_display_name)

                # Add to echo history (auto-logs via unified system - no need for separate log_message)
                self.echo.add_history({
                    "role": "validation",
                    "content": f"🛡️ Running validator: {validator_display_name}",
                    "node_type": "validation_start"
                }, trace_id=validation_trace.id, parent_id=trace.id, node_type="validation_start",
                   metadata={
                       "cell_name": phase.name,
                       "validator": validator_display_name,
                       "attempt": attempt + 1,
                       "content_preview": response_content[:200] if response_content else "(empty)",
                       "semantic_actor": "framework",
                       "semantic_purpose": "lifecycle"
                   })

                # Initialize validator_result to None (ensures it's in scope for logging later)
                validator_result = None

                # Check if this is a polyglot validator (inline code)
                if isinstance(validator_spec, PolyglotValidatorConfig):
                    # Run the polyglot validator directly
                    polyglot_result = self._run_polyglot_validator(
                        validator_spec,
                        response_content,
                        input_data,
                        validation_trace,
                        validator_name="loop_until"
                    )
                    validator_result = polyglot_result
                    validator_name = validator_display_name  # For logging below
                else:
                    # String validator - use existing lookup logic
                    validator_name = validator_spec

                # Try to get validator as Python function first (only for string validators)
                validator_tool = get_trait(validator_name) if isinstance(validator_spec, str) else None

                # If not found as function, check if it's a cascade tool (skip for polyglot validators)
                if not validator_tool and isinstance(validator_spec, str):
                    from .traits_manifest import get_trait_manifest
                    manifest = get_trait_manifest()

                    if validator_name in manifest and manifest[validator_name]["type"] == "cascade":
                        # It's a cascade validator - invoke it as a sub-cascade
                        cascade_path = manifest[validator_name]["path"]
                        # Pass both the output AND original input for context (validators can use what they need)
                        validator_input = {
                            "content": response_content,
                            "original_input": input_data
                        }

                        # Generate unique validator session ID (include candidate index if inside soundings)
                        validator_candidate_index = None
                        if self.current_phase_candidate_index is not None:
                            validator_session_id = f"{self.session_id}_validator_{attempt}_{self.current_phase_candidate_index}"
                            validator_candidate_index = self.current_phase_candidate_index
                        elif self.candidate_index is not None:
                            validator_session_id = f"{self.session_id}_validator_{attempt}_{self.candidate_index}"
                            validator_candidate_index = self.candidate_index
                        else:
                            validator_session_id = f"{self.session_id}_validator_{attempt}"

                        console.print(f"{indent}  [dim]Running cascade validator: {validator_name} (session: {validator_session_id})[/dim]")

                        # Log sub-cascade reference to parent
                        log_message(self.session_id, "sub_cascade_ref", f"Validator sub-cascade: {validator_name}",
                                   {"validator": validator_name, "sub_session_id": validator_session_id,
                                    "cascade_path": cascade_path, "cell_name": phase.name},
                                   trace_id=validation_trace.id, parent_id=trace.id,
                                   node_type="sub_cascade_ref", depth=self.depth)

                        try:
                            # Run the validator cascade
                            validator_result_echo = run_cascade(
                                cascade_path,
                                validator_input,
                                validator_session_id,
                                self.overrides,
                                self.depth + 1,
                                parent_trace=validation_trace,
                                hooks=self.hooks,
                                parent_session_id=self.session_id,
                                candidate_index=validator_candidate_index
                            )

                            console.print(f"{indent}  [dim cyan]Validator sub-cascade completed[/dim cyan]")

                            # Extract the result - look in lineage for last phase output
                            if validator_result_echo.get("lineage"):
                                last_output = validator_result_echo["lineage"][-1].get("output", "")
                                console.print(f"{indent}  [dim]Validator output: {last_output[:100]}...[/dim]")

                                # Try to parse as JSON
                                try:
                                    validator_result = json.loads(last_output)
                                    console.print(f"{indent}  [dim green]Parsed validator result: valid={validator_result.get('valid')}[/dim green]")
                                except:
                                    # If not JSON, try to extract from text
                                    import re
                                    json_match = re.search(r'\{[^}]*"valid"[^}]*\}', last_output, re.DOTALL)
                                    if json_match:
                                        try:
                                            validator_result = json.loads(json_match.group(0))
                                            console.print(f"{indent}  [dim green]Extracted validator result from text[/dim green]")
                                        except:
                                            validator_result = {"valid": False, "reason": "Could not parse validator response"}
                                            console.print(f"{indent}  [dim yellow]Failed to parse extracted JSON[/dim yellow]")
                                    else:
                                        validator_result = {"valid": False, "reason": last_output}
                                        console.print(f"{indent}  [dim yellow]No JSON found in output[/dim yellow]")
                            else:
                                validator_result = {"valid": False, "reason": "No output from validator"}
                                console.print(f"{indent}  [dim yellow]Validator lineage empty[/dim yellow]")

                        except Exception as e:
                            console.print(f"{indent}  [bold red]Validator Error:[/bold red] {str(e)}")
                            import traceback
                            console.print(f"{indent}  [dim red]{traceback.format_exc()}[/dim red]")

                            log_message(self.session_id, "validation_error", str(e),
                                       {"validator": validator_name},
                                       trace_id=validation_trace.id, parent_id=trace.id,
                                       node_type="error", depth=self.depth)
                            validation_passed = False
                            if attempt + 1 >= max_attempts:
                                break
                            continue  # Try next attempt if available
                    else:
                        console.print(f"{indent}  [yellow]Warning: Validator '{validator_name}' not found[/yellow]")
                        validation_passed = True  # Don't block if validator missing
                        break

                # Handle function validators
                if validator_tool and callable(validator_tool):
                    try:
                        # Set trace context for validator
                        set_current_trace(validation_trace)

                        # Call validator with response content
                        validator_result = validator_tool(content=response_content)

                        # Parse validator result
                        if isinstance(validator_result, str):
                            try:
                                validator_result = json.loads(validator_result)
                            except:
                                # If not JSON, treat as plain string (assume invalid)
                                validator_result = {"valid": False, "reason": validator_result}

                    except Exception as e:
                        console.print(f"{indent}  [bold red]Validator Error:[/bold red] {str(e)}")
                        log_message(self.session_id, "validation_error", str(e),
                                   {"validator": validator_name},
                                   trace_id=validation_trace.id, parent_id=trace.id,
                                   node_type="error", depth=self.depth)
                        validation_passed = False
                        if attempt + 1 >= max_attempts:
                            break
                        continue  # Try next attempt if available

                # Parse and handle validation result (common for both function and cascade validators)
                # ALWAYS log validation result, even if validator_result isn't set properly
                if 'validator_result' in locals() and validator_result is not None:
                    is_valid = validator_result.get("valid", False)
                    reason = validator_result.get("reason", "No reason provided")
                else:
                    # Validator didn't set result properly - treat as failure
                    console.print(f"{indent}  [yellow]Warning: Validator '{validator_name}' did not return proper result[/yellow]")
                    is_valid = False
                    reason = "Validator execution failed or returned invalid format"

                # Log validation result to parent session (ALWAYS)
                # Add to echo history (auto-logs via unified system - no separate log_message needed)
                self.echo.add_history({
                    "role": "validation",
                    "content": f"{'✓' if is_valid else '✗'} {validator_name}: {reason[:200]}",
                    "node_type": "validation"
                }, trace_id=validation_trace.id, parent_id=trace.id, node_type="validation",
                   metadata={
                       "cell_name": phase.name,
                       "validator": validator_name,
                       "valid": is_valid,
                       "reason": reason,
                       "attempt": attempt + 1,
                       "max_attempts": max_attempts,
                       "semantic_actor": "validator",
                       "semantic_purpose": "validation_output"
                   })

                if is_valid:
                    console.print(f"{indent}  [bold green]✓ Validation Passed:[/bold green] {reason[:150]}...")
                    validation_passed = True
                    break  # Exit attempt loop
                else:
                    console.print(f"{indent}  [bold red]✗ Validation Failed:[/bold red] {reason[:150]}...")
                    # Store error in state for retry instructions template
                    self.echo.update_state("last_validation_error", reason)
                    validation_passed = False

                    # Track for auto-context loop compression
                    self._loop_validation_failures.append({
                        "attempt": attempt + 1,
                        "output": response_content[:500] if response_content else "",
                        "validation_reason": reason
                    })

                    # If this was the last attempt, we're done
                    if attempt + 1 >= max_attempts:
                        console.print(f"{indent}[bold red]⚠️  Max validation attempts reached ({max_attempts})[/bold red]")

            # ========== POST-WARDS: Validate outputs after phase completes ==========
            post_ward_retry_needed = False
            if phase.wards and phase.wards.post:
                console.print(f"{indent}[bold cyan]🛡️  Running Post-Wards (Output Validation)...[/bold cyan]")

                # Update phase progress for post-ward stage
                update_phase_progress(
                    self.session_id, self.config.cascade_id, phase.name, self.depth,
                    stage="post_ward"
                )

                total_post_wards = len(phase.wards.post)
                for ward_idx, ward_config in enumerate(phase.wards.post):
                    # Update progress with current ward
                    update_phase_progress(
                        self.session_id, self.config.cascade_id, phase.name, self.depth,
                        ward_name=_format_validator_name(ward_config.validator),
                        ward_type="post",
                        ward_index=ward_idx + 1,
                        total_wards=total_post_wards
                    )
                    ward_result = self._run_ward(ward_config, response_content, trace, ward_type="post")

                    if not ward_result["valid"]:
                        # Handle based on mode
                        if ward_result["mode"] == "blocking":
                            console.print(f"{indent}[bold red]⛔ Post-Ward BLOCKING: Phase failed[/bold red]")
                            log_message(self.session_id, "post_ward_blocked", f"Phase blocked by {ward_result['validator']}",
                                       {"reason": ward_result["reason"]},
                                       trace_id=trace.id, parent_id=trace.parent_id,
                                       node_type="ward_block", depth=self.depth)
                            _cleanup_rag()
                            return f"[BLOCKED by post-ward: {ward_result['reason']}]"

                        elif ward_result["mode"] == "retry":
                            # Store error for retry
                            self.echo.update_state("last_validation_error", ward_result["reason"])

                            if attempt + 1 < max_attempts:
                                console.print(f"{indent}  [yellow]🔄 Post-ward will trigger retry...[/yellow]")
                                post_ward_retry_needed = True
                            else:
                                console.print(f"{indent}[bold red]⚠️  Max post-ward retry attempts reached[/bold red]")

                        elif ward_result["mode"] == "advisory":
                            # Log warning but continue
                            console.print(f"{indent}  [yellow]ℹ️  Advisory notice (not blocking)[/yellow]")
                            log_message(self.session_id, "post_ward_advisory", ward_result["reason"],
                                       {"validator": ward_result["validator"]},
                                       trace_id=trace.id, parent_id=trace.parent_id,
                                       node_type="ward_advisory", depth=self.depth)

            # If a post-ward requested retry, continue the attempt loop
            if post_ward_retry_needed:
                continue

            # Check if we should exit retry loop
            if not phase.rules.loop_until and not (phase.wards and phase.wards.post):
                # No validation required, exit after first attempt
                validation_passed = True
                break  # Exit retry loop

            # If validation passed (or no validation configured), exit
            if validation_passed:
                break  # Exit retry loop

            # Otherwise, validation failed - check if we have more attempts
            if attempt + 1 >= max_attempts:
                console.print(f"{indent}[bold red]⚠️  Max validation attempts reached ({max_attempts})[/bold red]")
                break  # Exit retry loop after max attempts

            # Continue to next attempt (loop will iterate)

        # Auto-save any images from final phase context (catches all images before phase completion)
        self._save_images_from_messages(self.context_messages, phase.name)

        # ========== OUTPUT EXTRACTION: Extract structured content from phase output ==========
        if phase.output_extraction:
            from .extraction import OutputExtractor, ExtractionError

            console.print(f"{indent}[bold cyan]🔍 Extracting structured content...[/bold cyan]")
            extractor = OutputExtractor()

            try:
                extracted = extractor.extract(response_content, phase.output_extraction)

                if extracted is not None:
                    # Store in state
                    state_key = phase.output_extraction.store_as
                    self.echo.update_state(state_key, extracted)

                    console.print(f"{indent}  [green]✓ Extracted '{state_key}': {str(extracted)[:100]}...[/green]")

                    # Log extraction
                    from .unified_logs import log_unified
                    log_unified(
                        session_id=self.session_id,
                        trace_id=trace.id,
                        parent_id=trace.parent_id,
                        node_type="extraction",
                        role="system",
                        content=f"Extracted {state_key}",
                        metadata={
                            "cell": phase.name,
                            "key": state_key,
                            "pattern": phase.output_extraction.pattern,
                            "size": len(str(extracted))
                        }
                    )
                else:
                    console.print(f"{indent}  [yellow]⚠️  Pattern not found (optional)[/yellow]")

            except ExtractionError as e:
                # Required extraction failed
                console.print(f"{indent}[red]✗ Extraction failed: {e}[/red]")
                self.echo.add_error(phase.name, "extraction_error", str(e))
                _cleanup_rag()
                return f"[EXTRACTION ERROR: {e}]"

        _cleanup_rag()

        # Convert output to string for checkpoint handling
        phase_output_str = response_content if isinstance(response_content, str) else str(response_content)

        # Check for LLM-generated decision points (<decision> blocks)
        # This allows the LLM to dynamically request human input with custom options
        decision_data = self._check_for_decision_point(phase_output_str, phase)
        if decision_data:
            decision_result = self._handle_decision_point(decision_data, phase, trace)
            if decision_result:
                action = decision_result.get("_action")
                if action == "retry":
                    # Retry this phase with decision feedback injected
                    # The feedback is stored in state["_decision_feedback"]
                    console.print(f"[yellow]↻ Retrying phase due to decision[/yellow]")
                    # Note: Actual retry logic would need to be handled at a higher level
                    # For now, we continue but the feedback is available in state
                elif action == "route":
                    # Route to a specific phase
                    target = decision_result.get("target_phase")
                    if target:
                        return target  # Return the target phase name as the chosen next phase

        # Handle human-in-the-loop checkpoint if configured (static HITL)
        # This BLOCKS waiting for human input (no exceptions, just waits)
        human_response = self._handle_human_input_checkpoint(phase, phase_output_str, trace, input_data)

        # If human input was received, it can be accessed via self.echo.state or passed to next phase
        # For now, we just log it and continue - the response is in the history

        # Publish phase_complete event (for narrator and other subscribers)
        self._publish_event("phase_complete", {
            "cell_name": phase.name,
            "cascade_id": self.config.cascade_id,
            "output": str(response_content)[:500] if response_content else None,
            "turn_number": max_turns,
            "max_turns": max_turns,
            "trace_id": trace.id if trace else None,
        })

        return chosen_next_phase if chosen_next_phase else response_content

def run_cascade(config_path: str | dict, input_data: dict = None, session_id: str = "default", overrides: dict = None,
                depth: int = 0, parent_trace: TraceNode = None, hooks: RVBBITHooks = None, parent_session_id: str = None,
                candidate_index: int = None, caller_id: str = None, invocation_metadata: dict = None) -> dict:

    # If caller tracking not provided, try to get from context
    if caller_id is None:
        from .caller_context import get_caller_context
        ctx_caller_id, ctx_metadata = get_caller_context()
        if ctx_caller_id:
            caller_id = ctx_caller_id
            invocation_metadata = invocation_metadata or ctx_metadata

    runner = RVBBITRunner(config_path, session_id, overrides, depth, parent_trace, hooks, candidate_index=candidate_index,
                          parent_session_id=parent_session_id, caller_id=caller_id, invocation_metadata=invocation_metadata)

    result = runner.run(input_data)

    if depth == 0:
        # Only print tree at the end of the root
        graph_dir = get_config().graph_dir
        graph_path = generate_mermaid(runner.echo, os.path.join(graph_dir, f"{session_id}.mmd"))
        console.print(f"\n[bold cyan]📊 Execution Graph saved to:[/bold cyan] {graph_path}")

    return result
