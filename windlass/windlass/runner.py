import os
import json
from typing import Dict, Any, Optional, List, Union
import logging
import litellm
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.spinner import Spinner
import threading

# We assume these imports exist or are provided by the environment
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

from .cascade import load_cascade_config, CascadeConfig, PhaseConfig, AsyncCascadeRef, HandoffConfig
from .echo import get_echo, Echo
from .config import get_config
from .tackle import get_tackle
from .logs import log_message
from .eddies.base import create_eddy

console = Console()

from .agent import Agent
from .utils import get_tool_schema, encode_image_base64
from .tracing import TraceNode, set_current_trace
from .visualizer import generate_mermaid
from .prompts import render_instruction
from .state import update_session_state, update_phase_progress, clear_phase_progress
from .eddies.system import spawn_cascade
from .eddies.state_tools import set_current_session_id
from .rag.indexer import ensure_rag_index
from .rag.context import set_current_rag_context, clear_current_rag_context
# NOTE: Old cost.py track_request() no longer used - cost tracking via unified_logs.py

from rich.tree import Tree

class HookAction:
    CONTINUE = "continue"
    PAUSE = "pause"
    INJECT = "inject"

class WindlassHooks:
    """Base class for Windlass lifecycle hooks"""

    def on_cascade_start(self, cascade_id: str, session_id: str, context: dict) -> dict:
        """Called when cascade execution begins"""
        return {"action": HookAction.CONTINUE}

    def on_cascade_complete(self, cascade_id: str, session_id: str, result: dict) -> dict:
        """Called when cascade execution completes successfully"""
        return {"action": HookAction.CONTINUE}

    def on_cascade_error(self, cascade_id: str, session_id: str, error: Exception) -> dict:
        """Called when cascade execution fails"""
        return {"action": HookAction.CONTINUE}

    def on_phase_start(self, phase_name: str, context: dict) -> dict:
        """Called when phase execution begins"""
        return {"action": HookAction.CONTINUE}

    def on_phase_complete(self, phase_name: str, session_id: str, result: dict) -> dict:
        """Called when phase execution completes"""
        return {"action": HookAction.CONTINUE}

    def on_turn_start(self, phase_name: str, turn_index: int, context: dict) -> dict:
        """Called when a turn begins"""
        return {"action": HookAction.CONTINUE}

    def on_tool_call(self, tool_name: str, phase_name: str, session_id: str, args: dict) -> dict:
        """Called when a tool is invoked"""
        return {"action": HookAction.CONTINUE}

    def on_tool_result(self, tool_name: str, phase_name: str, session_id: str, result: Any) -> dict:
        """Called when a tool returns a result"""
        return {"action": HookAction.CONTINUE}

class WindlassRunner:
    def __init__(self, config_path: str | dict, session_id: str = "default", overrides: dict = None,
                 depth: int = 0, parent_trace: TraceNode = None, hooks: WindlassHooks = None,
                 sounding_index: int = None, parent_session_id: str = None):
        self.config_path = config_path
        self.config = load_cascade_config(config_path)
        self.session_id = session_id
        self.overrides = overrides or {}
        self.echo = get_echo(session_id, parent_session_id=parent_session_id)
        self.depth = depth
        self.max_depth = 5
        self.hooks = hooks or WindlassHooks()
        self.context_messages: List[Dict[str, str]] = []
        self.sounding_index = sounding_index  # Track which sounding attempt this is (for cascade-level soundings)
        self.current_phase_sounding_index = None  # Track sounding index within current phase
        self.current_reforge_step = None  # Track which reforge step we're in
        self.current_retry_attempt = None  # Track retry/validation attempt index
        self.current_turn_number = None  # Track turn number within phase (for max_turns)
        self.current_mutation_applied = None  # Track mutation applied to current sounding
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

    def _tag_message_with_ttl(self, message: dict, category: str, phase: 'PhaseConfig') -> dict:
        """Tag a message with TTL metadata if context_ttl is configured."""
        if not phase.context_ttl or category not in phase.context_ttl:
            return message

        ttl = phase.context_ttl.get(category)
        if ttl is None:  # None means keep forever
            return message

        # Tag with expiry metadata
        if "metadata" not in message:
            message["metadata"] = {}

        message["metadata"]["ttl"] = ttl
        message["metadata"]["category"] = category
        message["metadata"]["created_at_turn"] = self.current_turn_number or 0
        message["metadata"]["expires_at_turn"] = (self.current_turn_number or 0) + ttl

        return message

    def _prune_expired_context(self, current_turn: int):
        """Remove messages that have expired based on their TTL."""
        self.context_messages = [
            msg for msg in self.context_messages
            if not msg.get("metadata", {}).get("expires_at_turn")
            or msg["metadata"]["expires_at_turn"] > current_turn
        ]

    def _save_to_memory(self, message: dict):
        """
        Save a message to the configured memory bank.

        Args:
            message: Message dict with role, content, etc.
        """
        # Only save if memory is configured and we're not in a sounding (non-winners aren't canon)
        if not self.memory_name or not self.memory_system:
            return

        # Skip saving losing soundings (they're alternate universes, not canon)
        if self.current_phase_sounding_index is not None or self.sounding_index is not None:
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
            'phase_name': self.echo._current_phase_name or 'unknown',
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

    def _get_metadata(self, extra: dict = None) -> dict:
        """
        Helper to build metadata dict with sounding_index automatically included.
        Use this in all echo.add_history() calls to ensure consistent tagging.
        """
        meta = extra.copy() if extra else {}

        # Auto-inject sounding_index if we're in a sounding
        if self.current_phase_sounding_index is not None:
            meta.setdefault("sounding_index", self.current_phase_sounding_index)
        elif self.sounding_index is not None:
            meta.setdefault("sounding_index", self.sounding_index)

        # Auto-inject reforge_step if we're in reforge
        if hasattr(self, 'current_reforge_step') and self.current_reforge_step is not None:
            meta.setdefault("reforge_step", self.current_reforge_step)

        return meta

    def _update_graph(self):
        """Updates the mermaid graph in real-time."""
        try:
            generate_mermaid(self.echo, self.graph_path)
        except Exception:
            pass # Don't crash execution for visualization

    def _generate_tool_description(self, func: Callable, name: str) -> str:
        """
        Generate a prompt-based description of a tool for the agent.
        Returns formatted text describing the tool, its parameters, and how to call it.
        """
        import inspect
        from typing import get_type_hints

        sig = inspect.signature(func)
        hints = get_type_hints(func)

        # Get docstring
        doc = func.__doc__ or f"Tool: {name}"
        doc_lines = [line.strip() for line in doc.strip().split('\n') if line.strip()]
        description = doc_lines[0] if doc_lines else f"Tool: {name}"

        # Build parameter list
        params = []
        for param_name, param in sig.parameters.items():
            if param_name == "self":
                continue

            param_type = hints.get(param_name, str).__name__
            is_required = param.default == inspect.Parameter.empty
            required_marker = " (required)" if is_required else f" (optional, default: {param.default})"

            params.append(f"  - {param_name} ({param_type}){required_marker}")

        params_str = "\n".join(params) if params else "  (no parameters)"

        # Format as markdown
        tool_desc = f"""
**{name}**
{description}
Parameters:
{params_str}

To use: Output JSON in this format:
{{"tool": "{name}", "arguments": {{"param1": "value1", "param2": "value2"}}}}
"""
        return tool_desc.strip()

    def _parse_prompt_tool_calls(self, content: str) -> tuple[List[Dict], str]:
        """
        Parse prompt-based tool calls from agent response.
        Looks for JSON structures like: {"tool": "name", "arguments": {...}}
        Handles both raw JSON and markdown code-fenced JSON (```json ... ```)

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

        # ONLY extract JSON from markdown code fences (```json ... ```)
        # This is the ONLY reliable way to find tool calls
        # DO NOT try to parse arbitrary {...} patterns - they could be:
        #   - Python dicts: {'key': 'value'}
        #   - Python f-strings: {variable}
        #   - JSON examples in text
        #   - Formatted output examples
        code_fence_pattern = r'```json\s*(\{[^`]*\})\s*```'
        all_json_blocks = re.findall(code_fence_pattern, content, re.DOTALL | re.IGNORECASE)

        # If no ```json blocks found, agent isn't trying to call tools
        # This is fine - phase might not have tools, or agent is just responding

        for block_idx, block in enumerate(all_json_blocks):
            # Clean up any remaining markdown or whitespace
            block = block.strip()

            # Try to parse the JSON
            try:
                data = json.loads(block)
            except json.JSONDecodeError as e:
                # ONLY report errors for blocks that LOOK like tool calls
                # Check if this looks like a tool call attempt (has "tool" string in it)
                if '"tool"' in block or "'tool'" in block:
                    # This looks like a tool call attempt that's malformed
                    error_detail = f"Tool call JSON is malformed:\n"
                    error_detail += f"  Error: {e.msg} at position {e.pos}\n"
                    error_detail += f"  Your JSON: {block[:150]}{'...' if len(block) > 150 else ''}\n"

                    # Diagnose common errors
                    opens = block.count('{')
                    closes = block.count('}')
                    if closes > opens:
                        error_detail += f"  → You have {closes - opens} extra closing braces }}\n"
                    elif opens > closes:
                        error_detail += f"  → You're missing {opens - closes} closing braces }}\n"

                    if block.count('"') % 2 != 0:
                        error_detail += f"  → Unmatched quotes detected\n"

                    parse_errors.append(error_detail)
                # else: Not a tool call, just some other JSON (ignore it)
                continue

            # Successfully parsed - now check if it's actually a TOOL CALL
            if not isinstance(data, dict):
                continue  # Not a dict, ignore

            if "tool" not in data:
                continue  # No "tool" key, not a tool call, ignore

            # This IS a tool call - validate structure
            tool_name = data.get("tool")
            arguments = data.get("arguments", {})

            if not isinstance(arguments, dict):
                parse_errors.append(f"Tool call 'arguments' must be an object/dict, got {type(arguments).__name__}")
                continue

            # Successfully parsed and validated tool call!
            tool_calls.append({
                "id": f"prompt_tool_{len(tool_calls)}",
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": json.dumps(arguments)
                }
            })

        # Return results
        if tool_calls:
            return tool_calls, None  # Success!

        if parse_errors:
            # Found blocks that LOOKED like tool calls but were malformed
            error_msg = "\n".join(parse_errors)
            return [], error_msg

        # No tool calls found (no ```json blocks, or JSON blocks weren't tool calls)
        return [], None  # No error, agent just not calling tools

    def _run_with_cascade_soundings(self, input_data: dict = None) -> dict:
        """
        Execute cascade with soundings (Tree of Thought at cascade level).
        Spawns N complete cascade executions, evaluates them, and returns only the winner.
        """
        indent = "  " * self.depth
        factor = self.config.soundings.factor

        console.print(f"{indent}[bold blue]🔱 Taking {factor} CASCADE Soundings (Parallel Full Executions)...[/bold blue]")

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
               "phase_name": "_orchestration",  # Ensure UI can query this
               "factor": factor
           })

        # Store all sounding results
        sounding_results = []

        # Execute each sounding as a complete separate cascade run
        for i in range(factor):
            console.print(f"{indent}  [cyan]🌊 Cascade Sounding {i+1}/{factor}[/cyan]")

            # Create trace for this sounding
            sounding_trace = soundings_trace.create_child("cascade_sounding_attempt", f"attempt_{i+1}")

            # Create a fresh Echo for this sounding attempt
            sounding_session_id = f"{self.session_id}_sounding_{i}"
            from .echo import Echo
            sounding_echo = Echo(sounding_session_id, parent_session_id=self.session_id)

            try:
                # Create a new runner for this sounding with sounding_index set
                sounding_runner = WindlassRunner(
                    config_path=self.config_path,
                    session_id=sounding_session_id,
                    overrides=self.overrides,
                    depth=self.depth,
                    parent_trace=sounding_trace,
                    hooks=self.hooks,
                    sounding_index=i,  # Mark this runner as part of a sounding
                    parent_session_id=self.session_id  # Link child to parent session
                )

                # Run the cascade with sounding metadata
                result = sounding_runner._run_cascade_internal(input_data)

                # Extract final result from echo
                final_output = result.get("final_output", str(result))

                sounding_results.append({
                    "index": i,
                    "result": final_output,
                    "echo": sounding_echo,
                    "trace_id": sounding_trace.id,
                    "full_result": result
                })

                console.print(f"{indent}    [green]✓ Cascade Sounding {i+1} complete[/green]")

                # Add to echo history for visualization - store sub-session reference (auto-logs via unified_logs)
                self.echo.add_history({
                    "role": "cascade_sounding_attempt",
                    "content": str(final_output)[:150] if final_output else "Completed",
                    "node_type": "cascade_sounding_attempt"
                }, trace_id=sounding_trace.id, parent_id=soundings_trace.id, node_type="cascade_sounding_attempt",
                   metadata={
                       "cascade_id": self.config.cascade_id,
                       "phase_name": "_orchestration",  # Ensure UI can query this
                       "sounding_index": i,
                       "sub_session_id": sounding_session_id,
                       "is_winner": False,  # Updated later when winner is selected
                       "result_preview": str(final_output)[:200]
                   })

            except Exception as e:
                console.print(f"{indent}    [red]✗ Cascade Sounding {i+1} failed: {e}[/red]")
                log_message(self.session_id, "cascade_sounding_error", str(e),
                           trace_id=sounding_trace.id, parent_id=soundings_trace.id,
                           node_type="error", depth=self.depth,
                           sounding_index=i, is_winner=False)
                sounding_results.append({
                    "index": i,
                    "result": f"[ERROR: {str(e)}]",
                    "echo": None,
                    "trace_id": sounding_trace.id,
                    "full_result": {}
                })

        # Now evaluate all soundings
        console.print(f"{indent}[bold yellow]⚖️  Evaluating {len(sounding_results)} cascade executions...[/bold yellow]")

        # Create evaluator trace
        evaluator_trace = soundings_trace.create_child("evaluator", "cascade_evaluation")

        # Build evaluation prompt
        eval_prompt = f"{self.config.soundings.evaluator_instructions}\n\n"
        eval_prompt += "Please evaluate the following complete cascade executions and select the best one.\n\n"

        for i, sounding in enumerate(sounding_results):
            eval_prompt += f"## Cascade Execution {i+1}\n"
            eval_prompt += f"Result: {sounding['result']}\n\n"

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

        # Add evaluator to echo history for visualization (auto-logs via unified_logs)
        self.echo.add_history({
            "role": "cascade_evaluator",
            "content": eval_content if eval_content else "Evaluating...",  # Full content, no truncation
            "node_type": "cascade_evaluator"
        }, trace_id=evaluator_trace.id, parent_id=soundings_trace.id, node_type="cascade_evaluator",
           metadata={
               "cascade_id": self.config.cascade_id,
               "phase_name": "_orchestration",  # Ensure UI can query this
               "factor": factor,
               "model": self.model
           })

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
            # This allows backend queries (which filter by phase_name IS NOT NULL) to find parent's data
            for lineage_item in winner['echo'].lineage:
                phase_name = lineage_item.get('phase')
                output_content = lineage_item.get('output', '')

                # Log phase completion to parent session
                self.echo.add_history({
                    "role": "phase_result",
                    "content": f"Phase {phase_name} completed (from sounding #{winner_index})",
                    "node_type": "phase_result"
                }, trace_id=soundings_trace.id, parent_id=self.trace.id, node_type="phase_result",
                   metadata={
                       "cascade_id": self.config.cascade_id,
                       "phase_name": phase_name,
                       "source_sounding": winner_index,
                       "output_preview": str(output_content)[:200] if output_content else ""
                   })

        # Add soundings result to history (auto-logs via unified_logs)
        self.echo.add_history({
            "role": "cascade_soundings_result",
            "content": f"🏆 Winner: Cascade #{winner_index + 1}",
            "node_type": "cascade_soundings_result"
        }, trace_id=soundings_trace.id, parent_id=self.trace.id, node_type="cascade_soundings_result",
           metadata={
               "cascade_id": self.config.cascade_id,
               "phase_name": "_orchestration",  # Ensure UI can query this
               "winner_index": winner_index,
               "winner_session_id": f"{self.session_id}_sounding_{winner_index}",
               "factor": factor,
               "evaluation": eval_content,  # Full content, no truncation
               "winner_trace_id": winner['trace_id'],
               "sounding_index": winner_index,
               "is_winner": True
           })

        self._update_graph()

        # Check if reforge is configured for cascade soundings
        if self.config.soundings.reforge:
            winner = self._reforge_cascade_winner(
                winner=winner,
                input_data=input_data,
                trace=soundings_trace,
                reforge_step=0  # Initial soundings = step 0
            )

        return winner['full_result']

    def _reforge_cascade_winner(self, winner: dict, input_data: dict, trace: TraceNode, reforge_step: int) -> dict:
        """
        Reforge (refine) the winning cascade execution through iterative soundings.
        Each step runs complete cascade executions with honing prompt to progressively improve quality.
        """
        indent = "  " * self.depth
        reforge_config = self.config.soundings.reforge
        current_output = winner['result']

        # Build refinement context from original cascade config
        original_cascade_description = self.config.description or self.config.cascade_id

        for step in range(1, reforge_config.steps + 1):
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

            # Run mini-soundings for this reforge step (complete cascade executions)
            reforge_results = []
            for i in range(reforge_config.factor_per_step):
                console.print(f"{indent}    [cyan]🔨 Cascade Refinement {i+1}/{reforge_config.factor_per_step}[/cyan]")

                # Create trace for this refinement attempt
                refinement_trace = reforge_trace.create_child("cascade_refinement_attempt", f"attempt_{i+1}")

                # Create fresh Echo for this refinement
                refinement_session_id = f"{self.session_id}_reforge{step}_{i}"
                from .echo import Echo
                refinement_echo = Echo(refinement_session_id, parent_session_id=self.session_id)

                try:
                    # Create a new runner for this refinement
                    # We'll inject the refinement context as additional input
                    refinement_input = input_data.copy() if input_data else {}
                    refinement_input['_refinement_context'] = refinement_context

                    refinement_runner = WindlassRunner(
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

                    reforge_results.append({
                        "index": i,
                        "result": final_output,
                        "echo": refinement_echo,
                        "trace_id": refinement_trace.id,
                        "full_result": result
                    })

                    console.print(f"{indent}      [green]✓ Cascade Refinement {i+1} complete[/green]")

                except Exception as e:
                    console.print(f"{indent}      [red]✗ Cascade Refinement {i+1} failed: {e}[/red]")
                    log_message(self.session_id, "cascade_refinement_error", str(e),
                               trace_id=refinement_trace.id, parent_id=reforge_trace.id,
                               node_type="error", depth=self.depth, reforge_step=step)
                    reforge_results.append({
                        "index": i,
                        "result": f"[ERROR: {str(e)}]",
                        "echo": None,
                        "trace_id": refinement_trace.id,
                        "full_result": {}
                    })

            # Evaluate refinements
            console.print(f"{indent}    [bold yellow]⚖️  Evaluating cascade refinements...[/bold yellow]")

            evaluator_trace = reforge_trace.create_child("evaluator", "cascade_reforge_evaluation")

            # Use custom evaluator or default
            eval_instructions = reforge_config.evaluator_override or self.config.soundings.evaluator_instructions

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

            log_message(self.session_id, "cascade_reforge_evaluation", eval_content,
                       trace_id=evaluator_trace.id, parent_id=reforge_trace.id,
                       node_type="evaluation", depth=self.depth, reforge_step=step)

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
        trace_context_token = set_current_trace(self.trace)

        # Set visualization context
        self.echo.set_cascade_context(self.config.cascade_id)

        update_session_state(self.session_id, self.config.cascade_id, "running", "init", self.depth)

        if self.depth > self.max_depth:
            log_message(self.session_id, "error", "Max recursion depth reached.",
                       trace_id=self.trace.id, parent_id=self.trace.parent_id, node_type="error", depth=self.depth,
                       sounding_index=self.sounding_index)
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
            "sounding_index": self.sounding_index,
        })

        log_message(self.session_id, "system", f"Starting cascade {self.config.cascade_id}", input_data,
                   trace_id=self.trace.id, parent_id=self.trace.parent_id, node_type="cascade", depth=self.depth,
                   sounding_index=self.sounding_index, parent_session_id=self.parent_session_id)

        # Add structure to Echo for visualization
        self.echo.add_history({
            "role": "structure",
            "content": f"Cascade: {self.config.cascade_id}",
            "node_type": "cascade"
        }, trace_id=self.trace.id, parent_id=self.trace.parent_id, node_type="cascade",
           metadata={"cascade_id": self.config.cascade_id, "depth": self.depth})
        self._update_graph()

        current_phase_name = self.config.phases[0].name
        chosen_next_phase = None # For dynamic handoff


        # Simple state machine for phases
        while current_phase_name and current_phase_name != chosen_next_phase: # Also check against chosen_next_phase
            phase = next((p for p in self.config.phases if p.name == current_phase_name), None)
            if not phase:
                break

            update_session_state(self.session_id, self.config.cascade_id, "running", phase.name, self.depth)

            # Set phase context for visualization metadata
            self.echo.set_phase_context(phase.name)

            # Hook: Phase Start
            hook_result = self.hooks.on_phase_start(phase.name, {
                "echo": self.echo,
                "input": input_data,
                "sounding_index": self.current_phase_sounding_index or self.sounding_index,
            })

            # Phase Trace
            phase_trace = self.trace.create_child("phase", phase.name)

            # Log Phase Structure with rich metadata
            phase_meta = {
                "phase_name": phase.name,
                "has_soundings": phase.soundings is not None and phase.soundings.factor > 1,
                "has_wards": phase.wards is not None,
                "has_sub_cascades": len(phase.sub_cascades) > 0 if phase.sub_cascades else False,
                "handoffs": [h.target if hasattr(h, 'target') else h for h in phase.handoffs] if phase.handoffs else []
            }
            self.echo.add_history({
                "role": "structure",
                "content": f"Phase: {phase.name}",
                "node_type": "phase"
            }, trace_id=phase_trace.id, parent_id=phase_trace.parent_id, node_type="phase",
               metadata=phase_meta)

            # Snapshot context length before phase (for context_retention pruning)
            context_snapshot_length = len(self.context_messages)

            output_or_next_phase = self.execute_phase(phase, input_data, phase_trace, initial_injection=hook_result)

            # Handle context_retention: prune phase history if output_only
            if phase.context_retention == "output_only":
                # Remove all messages added during this phase except the final assistant message
                phase_messages = self.context_messages[context_snapshot_length:]

                # Find the last assistant message from this phase
                final_assistant_msg = None
                for msg in reversed(phase_messages):
                    if msg.get("role") == "assistant":
                        final_assistant_msg = msg
                        break

                # Replace phase's messages with just the final assistant message
                self.context_messages = self.context_messages[:context_snapshot_length]
                if final_assistant_msg:
                    self.context_messages.append(final_assistant_msg)

            # Log phase completion for UI visibility
            log_message(self.session_id, "phase_complete", f"Phase {phase.name} completed",
                       trace_id=phase_trace.id, parent_id=phase_trace.parent_id, node_type="phase",
                       depth=self.depth, phase_name=phase.name, cascade_id=self.config.cascade_id,
                       parent_session_id=self.parent_session_id)

            # Hook: Phase Complete
            self.hooks.on_phase_complete(phase.name, self.session_id, {"output": output_or_next_phase})

            if isinstance(output_or_next_phase, str) and output_or_next_phase in [h.target if isinstance(h, HandoffConfig) else h for h in phase.handoffs]:
                chosen_next_phase = output_or_next_phase # Dynamic handoff chosen by agent
                self.echo.add_lineage(phase.name, f"Dynamically routed to: {chosen_next_phase}", trace_id=phase_trace.id)
            else:
                self.echo.add_lineage(phase.name, output_or_next_phase, trace_id=phase_trace.id)

            self._update_graph() # After phase

            if chosen_next_phase: # If agent decided next phase
                current_phase_name = chosen_next_phase
                chosen_next_phase = None # Reset for next phase's routing
            elif phase.handoffs: # Else, follow linear if exists
                # Default to first handoff, or dynamically chosen
                next_handoff_target = phase.handoffs[0].target if isinstance(phase.handoffs[0], HandoffConfig) else phase.handoffs[0]
                current_phase_name = next_handoff_target
            else:
                current_phase_name = None

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

        # Log cascade completion with status
        log_message(self.session_id, "system", f"Cascade {final_status}: {self.config.cascade_id}",
                   metadata={"status": final_status, "error_count": len(result.get("errors", []))},
                   node_type=f"cascade_{final_status}", parent_session_id=self.parent_session_id)

        return result

    def run(self, input_data: dict = None) -> dict:
        """
        Main entry point for cascade execution.
        Checks if cascade-level soundings are configured and delegates appropriately.
        """
        try:
            # Check if cascade has soundings configured
            if self.config.soundings and self.config.soundings.factor > 1:
                return self._run_with_cascade_soundings(input_data)

            # Normal execution (no cascade soundings)
            return self._run_cascade_internal(input_data)
        except Exception as e:
            # Hook: Cascade Error
            self.hooks.on_cascade_error(self.config.cascade_id, self.session_id, e)
            raise

    def _run_quartermaster(self, phase: PhaseConfig, input_data: dict, trace: TraceNode, phase_model: str = None) -> list[str]:
        """
        Run the Quartermaster agent to select appropriate tackle for this phase.

        Returns list of tool names to make available.
        """
        from .tackle_manifest import get_tackle_manifest, format_manifest_for_quartermaster

        indent = "  " * self.depth

        # Create quartermaster trace
        qm_trace = trace.create_child("quartermaster", "manifest_selection")

        # Get full tackle manifest
        manifest = get_tackle_manifest()
        manifest_text = format_manifest_for_quartermaster(manifest)

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
           metadata={
               "phase_name": phase.name,
               "selected_tackle": valid_tackle,
               "reasoning": response_content,  # Full content, no truncation
               "manifest_context": phase.manifest_context,
               "model": qm_model
           })

        console.print(f"{indent}    [dim]Reasoning: {response_content[:150]}...[/dim]")

        return valid_tackle

    def _rewrite_prompt_with_llm(self, phase: PhaseConfig, input_data: dict, mutation_template: str, parent_trace: TraceNode) -> str:
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
        outputs = {item['phase']: item['output'] for item in self.echo.lineage}
        render_context = {
            "input": input_data,
            "state": self.echo.state,
            "history": self.echo.history,
            "outputs": outputs,
            "lineage": self.echo.lineage
        }
        original_prompt = render_instruction(phase.instructions, render_context)

        # Build the rewrite request
        rewrite_request = f"""You are a prompt rewriting assistant. Your job is to rewrite a prompt while preserving its core intent.

## Original Prompt:
{original_prompt}

## Rewrite Instruction:
{mutation_template}

## Rules:
1. Preserve the core task/intent of the original prompt
2. Apply the rewrite instruction to change how the prompt is formulated
3. Output ONLY the rewritten prompt, nothing else
4. Do not add meta-commentary or explanations
5. The rewritten prompt should be self-contained and complete

## Rewritten Prompt:"""

        # Use a fast, cheap model for rewriting (gemini flash lite or similar)
        rewrite_model = os.environ.get("WINDLASS_REWRITE_MODEL", "google/gemini-2.5-flash-lite")

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
                "phase_name": phase.name
            },
            trace_id=rewrite_trace.id,
            parent_id=parent_trace.id,
            node_type="prompt_rewrite",
            depth=self.depth,
            phase_name=phase.name,
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

    def _run_ward(self, ward_config, content: str, trace: TraceNode, ward_type: str = "post") -> dict:
        """
        Run a single ward (validator) and return validation result.

        Returns dict with:
        - valid: bool
        - reason: str
        - mode: str (blocking, retry, advisory)
        """
        indent = "  " * self.depth
        validator_name = ward_config.validator
        mode = ward_config.mode

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
        validator_tool = get_tackle(validator_name)
        validator_result = None

        # If not found as function, check if it's a cascade tool
        if not validator_tool:
            from .tackle_manifest import get_tackle_manifest
            manifest = get_tackle_manifest()

            if validator_name in manifest and manifest[validator_name]["type"] == "cascade":
                # It's a cascade validator
                cascade_path = manifest[validator_name]["path"]
                validator_input = {"content": content}

                # Generate unique ward session ID (include sounding index if inside soundings)
                ward_sounding_index = None
                if self.current_phase_sounding_index is not None:
                    ward_session_id = f"{self.session_id}_ward_{self.current_phase_sounding_index}"
                    ward_sounding_index = self.current_phase_sounding_index
                elif self.sounding_index is not None:
                    ward_session_id = f"{self.session_id}_ward_{self.sounding_index}"
                    ward_sounding_index = self.sounding_index
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
                        sounding_index=ward_sounding_index
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
           metadata={
               "ward_type": ward_type,
               "validator": validator_name,
               "mode": mode,
               "valid": is_valid,
               "reason": reason[:100] if reason else ""
           })

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

    def _assign_models(self, soundings_config) -> List[str]:
        """
        Assign models to sounding attempts based on configuration.

        Returns a list of model names, one per sounding attempt.

        Args:
            soundings_config: SoundingsConfig with optional multi-model settings

        Returns:
            List of model names to use for each sounding
        """
        import random

        # Case 1: No multi-model configuration - use default model for all
        if soundings_config.models is None:
            return [self.model] * soundings_config.factor

        # Case 2: List of models - apply strategy (round-robin, random, etc.)
        if isinstance(soundings_config.models, list):
            models = soundings_config.models
            strategy = soundings_config.model_strategy

            if strategy == "round_robin":
                # Cycle through models in order
                return [models[i % len(models)] for i in range(soundings_config.factor)]

            elif strategy == "random":
                # Random selection for each sounding
                return [random.choice(models) for _ in range(soundings_config.factor)]

            else:
                # Default to round-robin if unknown strategy
                return [models[i % len(models)] for i in range(soundings_config.factor)]

        # Case 3: Dict with per-model factors - expand based on each model's factor
        elif isinstance(soundings_config.models, dict):
            assigned = []
            for model_name, config in soundings_config.models.items():
                # Add this model N times based on its factor
                assigned.extend([model_name] * config.factor)
            return assigned

        # Fallback: use default
        return [self.model] * soundings_config.factor

    def _get_sounding_costs(self, sounding_results: List[Dict], timeout: float = 5.0) -> List[float]:
        """
        Get costs for each sounding attempt from unified logs.

        Waits briefly for async cost tracking to complete, then queries logs.
        Falls back to cost estimation if costs aren't available.

        Args:
            sounding_results: List of sounding result dicts with trace_id
            timeout: Max seconds to wait for costs

        Returns:
            List of costs, one per sounding
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
            sounding_results: List of sounding result dicts
            costs: List of costs per sounding
            soundings_config: SoundingsConfig with cost_aware_evaluation settings
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

        for i, sounding in enumerate(sounding_results):
            eval_prompt += f"## Attempt {i+1}\n"

            if cost_config.show_costs_to_evaluator:
                model = sounding.get("model", "unknown")
                cost = costs[i]
                eval_prompt += f"Model: {model}\n"
                eval_prompt += f"Cost: ${cost:.6f}\n"

            eval_prompt += f"Result: {sounding['result']}\n\n"

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

        A sounding is Pareto-optimal (non-dominated) if no other sounding is
        both cheaper AND higher quality.

        Args:
            sounding_results: List of sounding result dicts
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
            sounding_results: List of sounding result dicts
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
    ) -> List[float]:
        """
        Get quality scores for each sounding from the evaluator.

        Uses LLM to assign numeric quality scores to each sounding.

        Returns:
            List of quality scores (0-100 scale)
        """
        indent = "  " * self.depth

        # Build prompt for quality scoring
        score_prompt = f"""{evaluator_instructions}

Rate each of the following attempts on a scale of 0-100 for quality.
Consider clarity, completeness, accuracy, and usefulness.

"""
        for i, sounding in enumerate(sounding_results):
            score_prompt += f"## Attempt {i+1}\n"
            score_prompt += f"Result: {sounding['result']}\n\n"

        score_prompt += """
Respond with scores in this exact format:
Attempt 1: [score]
Attempt 2: [score]
...etc

Use only numbers 0-100 for scores."""

        # Create scoring agent
        scoring_agent = Agent(
            model=self.model,
            system_prompt="You are an expert evaluator. Rate each response objectively on a 0-100 scale.",
            tools=[],
            base_url=self.base_url,
            api_key=self.api_key
        )

        # Get scores
        score_response = scoring_agent.run(score_prompt, context_messages=[])
        score_content = score_response.get("content", "")

        console.print(f"{indent}  [dim]Quality scores: {score_content[:100]}...[/dim]")

        # Parse scores from response
        import re
        scores = []
        pattern = r'Attempt\s*(\d+)\s*:\s*(\d+(?:\.\d+)?)'
        matches = re.findall(pattern, score_content, re.IGNORECASE)

        # Build score list in order
        score_map = {int(m[0]): float(m[1]) for m in matches}
        for i in range(len(sounding_results)):
            scores.append(score_map.get(i + 1, 50.0))  # Default to 50 if not found

        return scores

    def _log_pareto_frontier(
        self,
        session_id: str,
        phase_name: str,
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
            "phase_name": phase_name,
            "frontier": [
                {
                    "sounding_index": idx,
                    "model": sounding_results[idx].get("model", "unknown"),
                    "quality": quality_scores[idx],
                    "cost": costs[idx],
                    "is_winner": idx == winner_index
                }
                for idx in frontier_indices
            ],
            "dominated": [
                {
                    "sounding_index": idx,
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

    def _execute_phase_with_soundings(self, phase: PhaseConfig, input_data: dict, trace: TraceNode, initial_injection: dict = None) -> Any:
        """
        Execute a phase with soundings (Tree of Thought).
        Spawns N parallel attempts, evaluates them, and returns only the winner.
        """
        indent = "  " * self.depth
        factor = phase.soundings.factor

        console.print(f"{indent}[bold blue]🔱 Taking {factor} Soundings (Parallel Attempts)...[/bold blue]")

        # Create soundings trace node
        soundings_trace = trace.create_child("soundings", f"{phase.name}_soundings")

        # Add soundings structure to Echo for visualization (auto-logs via unified_logs)
        soundings_meta = {
            "phase_name": phase.name,
            "factor": factor,
            "has_reforge": phase.soundings.reforge is not None
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

        # Store all sounding results
        sounding_results = []

        # Determine mutations to apply
        mutations_to_use = []
        mutation_mode = phase.soundings.mutation_mode  # "rewrite", "augment", or "approach"

        if phase.soundings.mutate:
            if phase.soundings.mutations:
                # Use custom mutations/templates
                mutations_to_use = phase.soundings.mutations
            elif mutation_mode == "rewrite":
                # Rewrite templates: LLM will rewrite the prompt using these instructions
                # These are META-instructions for how to transform the prompt
                # IMPORTANT: Templates must be task-agnostic (work for creative, analytical, coding, etc.)
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

        # Assign models to soundings (Phase 1: Multi-Model Soundings)
        assigned_models = self._assign_models(phase.soundings)
        console.print(f"{indent}  [dim]Models: {', '.join(set(assigned_models))}[/dim]")

        # Execute each sounding in sequence (to avoid threading complexity with Rich output)
        # Each sounding gets the same starting context
        for i in range(factor):
            # Update phase progress for sounding visualization
            update_phase_progress(
                self.session_id, self.config.cascade_id, phase.name, self.depth,
                stage="soundings",
                sounding_index=i + 1,
                sounding_factor=factor,
                sounding_stage="executing"
            )

            # Determine mutation for this sounding
            mutation_template = None  # The template/instruction used (for rewrite mode)
            mutation_applied = None   # The actual mutation (rewritten prompt or augment text)
            mutation_type = None      # 'rewrite', 'augment', 'approach', or None for baseline

            if mutations_to_use and i > 0:  # First sounding (i=0) uses original prompt (baseline)
                mutation_template = mutations_to_use[(i - 1) % len(mutations_to_use)]
                mutation_type = mutation_mode

                if mutation_mode == "rewrite":
                    # For rewrite mode: use LLM to rewrite the prompt
                    console.print(f"{indent}  [cyan]🌊 Sounding {i+1}/{factor}[/cyan] [yellow]🧬 Rewriting prompt...[/yellow]")
                    mutation_applied = self._rewrite_prompt_with_llm(
                        phase, input_data, mutation_template, soundings_trace
                    )
                    console.print(f"{indent}    [dim]Rewritten: {mutation_applied[:80]}...[/dim]")
                else:
                    # For augment/approach: use the template directly
                    mutation_applied = mutation_template
                    console.print(f"{indent}  [cyan]🌊 Sounding {i+1}/{factor}[/cyan] [yellow]🧬 {mutation_applied[:50]}...[/yellow]")
            else:
                console.print(f"{indent}  [cyan]🌊 Sounding {i+1}/{factor}[/cyan]" + (" [dim](baseline)[/dim]" if mutations_to_use else ""))

            # Set current sounding index for this attempt
            self.current_phase_sounding_index = i
            self.current_mutation_applied = mutation_applied  # Track for logging
            self.current_mutation_type = mutation_type  # Track type: rewrite, augment, approach
            self.current_mutation_template = mutation_template  # Track template/instruction used

            # Get model for this sounding (Phase 1: Multi-Model Soundings)
            sounding_model = assigned_models[i]
            original_model = self.model  # Save original model to restore later
            self.model = sounding_model  # Temporarily override model for this sounding
            console.print(f"{indent}    [dim]Using model: {sounding_model}[/dim]")

            # Create trace for this sounding
            sounding_trace = soundings_trace.create_child("sounding_attempt", f"attempt_{i+1}")

            # Reset context to snapshot for this attempt
            self.context_messages = context_snapshot.copy()
            self.echo.state = echo_state_snapshot.copy()
            self.echo.history = echo_history_snapshot.copy()
            self.echo.lineage = echo_lineage_snapshot.copy()

            # Execute the phase with optional mutation
            try:
                result = self._execute_phase_internal(
                    phase, input_data, sounding_trace,
                    initial_injection=initial_injection,
                    mutation=mutation_applied,
                    mutation_mode=mutation_mode
                )

                # Capture the context that was generated during this sounding
                sounding_context = self.context_messages[len(context_snapshot):]  # New messages added

                sounding_results.append({
                    "index": i,
                    "result": result,
                    "context": sounding_context,
                    "trace_id": sounding_trace.id,
                    "final_state": self.echo.state.copy(),
                    "mutation_applied": mutation_applied,
                    "mutation_type": mutation_type,
                    "mutation_template": mutation_template,
                    "model": sounding_model  # Track which model was used (Phase 1: Multi-Model)
                })

                console.print(f"{indent}    [green]✓ Sounding {i+1} complete[/green]")

            except Exception as e:
                console.print(f"{indent}    [red]✗ Sounding {i+1} failed: {e}[/red]")
                log_message(self.session_id, "sounding_error", str(e),
                           trace_id=sounding_trace.id, parent_id=soundings_trace.id, node_type="error", depth=self.depth)
                sounding_results.append({
                    "index": i,
                    "result": f"[ERROR: {str(e)}]",
                    "context": [],
                    "trace_id": sounding_trace.id,
                    "final_state": {},
                    "mutation_applied": mutation_applied,
                    "mutation_type": mutation_type,
                    "mutation_template": mutation_template,
                    "model": sounding_model  # Track which model was used (Phase 1: Multi-Model)
                })

            finally:
                # Restore original model after sounding execution (Phase 1: Multi-Model)
                self.model = original_model

        # Clear mutation tracking
        self.current_mutation_applied = None
        self.current_mutation_type = None
        self.current_mutation_template = None

        # Reset to original snapshot before evaluation
        self.context_messages = context_snapshot.copy()
        self.echo.state = echo_state_snapshot.copy()
        self.echo.history = echo_history_snapshot.copy()
        self.echo.lineage = echo_lineage_snapshot.copy()

        # Now evaluate all soundings
        # Update phase progress for evaluation stage
        update_phase_progress(
            self.session_id, self.config.cascade_id, phase.name, self.depth,
            sounding_stage="evaluating"
        )
        console.print(f"{indent}[bold yellow]⚖️  Evaluating {len(sounding_results)} soundings...[/bold yellow]")

        # Create evaluator trace
        evaluator_trace = soundings_trace.create_child("evaluator", "sounding_evaluation")

        # Get costs for cost-aware or Pareto evaluation (Phase 2/3: Multi-Model Soundings)
        sounding_costs = None
        quality_scores = None
        frontier_indices = None
        dominated_map = None
        pareto_ranks = None

        use_cost_aware = phase.soundings.cost_aware_evaluation and phase.soundings.cost_aware_evaluation.enabled
        use_pareto = phase.soundings.pareto_frontier and phase.soundings.pareto_frontier.enabled

        # Phase 3: Pareto Frontier Analysis
        if use_pareto:
            console.print(f"{indent}  [bold cyan]📊 Computing Pareto Frontier...[/bold cyan]")

            # Get costs
            console.print(f"{indent}  [dim]Gathering cost data...[/dim]")
            sounding_costs = self._get_sounding_costs(sounding_results)
            for i, sr in enumerate(sounding_results):
                sr["cost"] = sounding_costs[i]
            console.print(f"{indent}  [dim]Costs: {', '.join(f'${c:.6f}' for c in sounding_costs)}[/dim]")

            # Get quality scores
            console.print(f"{indent}  [dim]Getting quality scores from evaluator...[/dim]")
            quality_scores = self._get_quality_scores_from_evaluator(
                sounding_results,
                phase.soundings.evaluator_instructions,
                evaluator_trace
            )
            for i, sr in enumerate(sounding_results):
                sr["quality_score"] = quality_scores[i]
            console.print(f"{indent}  [dim]Qualities: {', '.join(f'{q:.1f}' for q in quality_scores)}[/dim]")

            # Compute Pareto frontier
            frontier_indices, dominated_map, pareto_ranks = self._compute_pareto_frontier(
                sounding_results, quality_scores, sounding_costs
            )

            # Store Pareto data in sounding results
            for i, sr in enumerate(sounding_results):
                sr["is_pareto_optimal"] = i in frontier_indices
                sr["dominated_by"] = dominated_map.get(i)
                sr["pareto_rank"] = pareto_ranks.get(i, 2)

            # Display frontier
            console.print(f"{indent}  [bold green]Pareto Frontier ({len(frontier_indices)} non-dominated solutions):[/bold green]")
            for idx in frontier_indices:
                model = sounding_results[idx].get("model", "unknown")
                quality = quality_scores[idx]
                cost = sounding_costs[idx]
                console.print(f"{indent}    • Sounding {idx+1} ({model}): Quality={quality:.1f}, Cost=${cost:.6f}")

            # Select winner from frontier
            winner_index = self._select_from_pareto_frontier(
                sounding_results,
                frontier_indices,
                quality_scores,
                sounding_costs,
                phase.soundings.pareto_frontier.policy
            )
            eval_content = f"Pareto frontier analysis: {len(frontier_indices)} non-dominated solutions. Winner selected by '{phase.soundings.pareto_frontier.policy}' policy."

            # Log Pareto data for visualization
            if phase.soundings.pareto_frontier.show_frontier:
                self._log_pareto_frontier(
                    self.session_id,
                    phase.name,
                    sounding_results,
                    frontier_indices,
                    dominated_map,
                    quality_scores,
                    sounding_costs,
                    winner_index
                )

        # Phase 2: Cost-Aware Evaluation
        elif use_cost_aware:
            console.print(f"{indent}  [dim]Gathering cost data for cost-aware evaluation...[/dim]")
            sounding_costs = self._get_sounding_costs(sounding_results)
            normalized_costs = self._normalize_costs(
                sounding_costs,
                phase.soundings.cost_aware_evaluation.cost_normalization
            )
            # Store costs in sounding results for logging
            for i, sr in enumerate(sounding_results):
                sr["cost"] = sounding_costs[i]
                sr["normalized_cost"] = normalized_costs[i]

            # Build cost-aware evaluation prompt
            eval_prompt = self._build_cost_aware_eval_prompt(
                sounding_results,
                sounding_costs,
                phase.soundings,
                phase.soundings.evaluator_instructions
            )
            console.print(f"{indent}  [dim]Costs: {', '.join(f'${c:.6f}' for c in sounding_costs)}[/dim]")

            # Create evaluator agent and run
            evaluator_agent = Agent(
                model=self.model,
                system_prompt="You are an expert evaluator. Your job is to compare multiple attempts and select the best one.",
                tools=[],
                base_url=self.base_url,
                api_key=self.api_key
            )
            eval_response = evaluator_agent.run(eval_prompt, context_messages=[])
            eval_content = eval_response.get("content", "")
            console.print(f"{indent}  [bold magenta]Evaluator:[/bold magenta] {eval_content[:200]}...")

            # Extract winner index
            winner_index = 0
            import re
            match = re.search(r'\b([1-9]\d*)\b', eval_content)
            if match:
                winner_index = int(match.group(1)) - 1
                if winner_index >= len(sounding_results):
                    winner_index = 0

        # Phase 1: Standard quality-only evaluation
        else:
            eval_prompt = f"{phase.soundings.evaluator_instructions}\n\n"
            eval_prompt += "Please evaluate the following attempts and select the best one.\n\n"

            for i, sounding in enumerate(sounding_results):
                eval_prompt += f"## Attempt {i+1}\n"
                eval_prompt += f"Result: {sounding['result']}\n\n"

            eval_prompt += "\nRespond with ONLY the number of the best attempt (1-{0}) and a brief explanation.".format(len(sounding_results))

            # Create evaluator agent and run
            evaluator_agent = Agent(
                model=self.model,
                system_prompt="You are an expert evaluator. Your job is to compare multiple attempts and select the best one.",
                tools=[],
                base_url=self.base_url,
                api_key=self.api_key
            )
            eval_response = evaluator_agent.run(eval_prompt, context_messages=[])
            eval_content = eval_response.get("content", "")
            console.print(f"{indent}  [bold magenta]Evaluator:[/bold magenta] {eval_content[:200]}...")

            # Extract winner index
            winner_index = 0
            import re
            match = re.search(r'\b([1-9]\d*)\b', eval_content)
            if match:
                winner_index = int(match.group(1)) - 1
                if winner_index >= len(sounding_results):
                    winner_index = 0

        winner = sounding_results[winner_index]

        console.print(f"{indent}[bold green]🏆 Winner: Sounding {winner_index + 1}[/bold green]")

        # Now apply ONLY the winner's context to the main snowball
        self.context_messages = context_snapshot + winner['context']
        self.echo.state = winner['final_state']

        # Reset sounding index (no longer in sounding context)
        self.current_phase_sounding_index = None

        # Add all sounding attempts to Echo history with metadata for visualization (auto-logs via unified_logs)
        for sr in sounding_results:
            is_winner = sr["index"] == winner_index
            sounding_metadata = {
                "phase_name": phase.name,
                "sounding_index": sr["index"],
                "is_winner": is_winner,
                "factor": factor,
                "mutation_applied": sr.get("mutation_applied"),  # Log what mutation was used
                "model": sr.get("model"),  # Log which model was used (Phase 1: Multi-Model Soundings)
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

            self.echo.add_history({
                "role": "sounding_attempt",
                "content": str(sr["result"])[:200] if sr["result"] else "",
                "node_type": "sounding_attempt"
            }, trace_id=sr["trace_id"], parent_id=soundings_trace.id, node_type="sounding_attempt",
               metadata=sounding_metadata)

        # Add evaluator entry (auto-logs via unified_logs)
        evaluator_metadata = {
            "phase_name": phase.name,
            "winner_index": winner_index,
            "winner_trace_id": winner['trace_id'],
            "evaluation": eval_content,
            "model": self.model,
        }
        # Add cost-aware evaluation info (Phase 2: Multi-Model Soundings)
        if use_cost_aware:
            evaluator_metadata["cost_aware"] = True
            evaluator_metadata["quality_weight"] = phase.soundings.cost_aware_evaluation.quality_weight
            evaluator_metadata["cost_weight"] = phase.soundings.cost_aware_evaluation.cost_weight
            if sounding_costs:
                evaluator_metadata["sounding_costs"] = sounding_costs
                evaluator_metadata["winner_cost"] = winner.get("cost")
        # Add Pareto frontier info (Phase 3: Pareto Frontier Analysis)
        if use_pareto:
            evaluator_metadata["pareto_enabled"] = True
            evaluator_metadata["pareto_policy"] = phase.soundings.pareto_frontier.policy
            evaluator_metadata["frontier_size"] = len(frontier_indices) if frontier_indices else 0
            if quality_scores:
                evaluator_metadata["quality_scores"] = quality_scores
                evaluator_metadata["winner_quality"] = winner.get("quality_score")
            if sounding_costs:
                evaluator_metadata["sounding_costs"] = sounding_costs
                evaluator_metadata["winner_cost"] = winner.get("cost")

        self.echo.add_history({
            "role": "evaluator",
            "content": eval_content,  # Full content, no truncation
            "node_type": "evaluator"
        }, trace_id=evaluator_trace.id, parent_id=soundings_trace.id, node_type="evaluator",
           metadata=evaluator_metadata)

        # Add winning result to history
        self.echo.add_history({
            "role": "soundings_result",
            "content": f"Selected best of {factor} attempts",
            "winner_index": winner_index + 1,
            "evaluation": eval_content
        }, trace_id=soundings_trace.id, parent_id=trace.id, node_type="soundings_result",
           metadata={"phase_name": phase.name, "winner_index": winner_index, "factor": factor})

        self._update_graph()

        # Check if reforge is configured
        if phase.soundings.reforge:
            winner = self._reforge_winner(
                winner=winner,
                phase=phase,
                input_data=input_data,
                trace=soundings_trace,
                context_snapshot=context_snapshot,
                reforge_step=0  # Initial soundings = step 0
            )

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

    def _save_images_from_messages(self, messages: list, phase_name: str):
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
            next_idx = get_next_image_index(self.session_id, phase_name)

            for i, (img_data, desc) in enumerate(images_to_save):
                save_path = get_image_save_path(
                    self.session_id,
                    phase_name,
                    next_idx + i,
                    extension='png'
                )

                if not os.path.exists(save_path):
                    try:
                        decode_and_save_image(img_data, save_path)
                        console.print(f"{indent}    [dim]💾 Saved image: {save_path}[/dim]")
                    except Exception as e:
                        console.print(f"{indent}    [dim yellow]⚠️  Failed to save image: {e}[/dim yellow]")

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

    def _reforge_winner(self, winner: dict, phase: PhaseConfig, input_data: dict, trace: TraceNode,
                        context_snapshot: list, reforge_step: int) -> dict:
        """
        Reforge (refine) the winning output through iterative soundings.
        Each step runs mini-soundings with honing prompt to progressively improve quality.
        """
        indent = "  " * self.depth
        reforge_config = phase.soundings.reforge
        current_output = winner['result']
        original_instructions = phase.instructions

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
                   "phase_name": phase.name,
                   "reforge_step": step,
                   "total_steps": reforge_config.steps,
                   "factor_per_step": reforge_config.factor_per_step,
                   "has_mutation": reforge_config.mutate
               })

            # Create temporary phase config for refinement
            # Use a modified phase with refinement instructions
            from copy import deepcopy
            refine_phase = deepcopy(phase)
            refine_phase.instructions = refinement_instructions

            # Snapshot state before reforge soundings
            echo_state_snapshot = self.echo.state.copy()
            echo_history_snapshot = self.echo.history.copy()
            echo_lineage_snapshot = self.echo.lineage.copy()

            # Build context with images if present
            refinement_context_messages = self._build_context_with_images(winner['context'], refinement_instructions)

            # Run mini-soundings for this reforge step
            reforge_results = []
            for i in range(reforge_config.factor_per_step):
                console.print(f"{indent}    [cyan]🔨 Refinement {i+1}/{reforge_config.factor_per_step}[/cyan]")

                # Create trace for this refinement attempt
                refinement_trace = reforge_trace.create_child("refinement_attempt", f"attempt_{i+1}")

                # Reset context to snapshot + refinement context with images
                self.context_messages = context_snapshot.copy() + refinement_context_messages
                self.echo.state = echo_state_snapshot.copy()
                self.echo.history = echo_history_snapshot.copy()
                self.echo.lineage = echo_lineage_snapshot.copy()

                try:
                    result = self._execute_phase_internal(refine_phase, input_data, refinement_trace)

                    # Capture refined context
                    refinement_context = self.context_messages[len(context_snapshot):]

                    reforge_results.append({
                        "index": i,
                        "result": result,
                        "context": refinement_context,
                        "trace_id": refinement_trace.id,
                        "final_state": self.echo.state.copy()
                    })

                    console.print(f"{indent}      [green]✓ Refinement {i+1} complete[/green]")

                    # Add refinement attempt to echo history for visualization
                    self.echo.add_history({
                        "role": "reforge_attempt",
                        "content": str(result)[:150] if result else "Completed",
                        "node_type": "reforge_attempt"
                    }, trace_id=refinement_trace.id, parent_id=reforge_trace.id, node_type="reforge_attempt",
                       metadata={
                           "phase_name": phase.name,
                           "reforge_step": step,
                           "attempt_index": i,
                           "is_winner": False  # Updated later
                       })

                except Exception as e:
                    console.print(f"{indent}      [red]✗ Refinement {i+1} failed: {e}[/red]")
                    log_message(self.session_id, "refinement_error", str(e),
                               trace_id=refinement_trace.id, parent_id=reforge_trace.id,
                               node_type="error", depth=self.depth, reforge_step=step)
                    reforge_results.append({
                        "index": i,
                        "result": f"[ERROR: {str(e)}]",
                        "context": [],
                        "trace_id": refinement_trace.id,
                        "final_state": {}
                    })

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
                       "phase_name": phase.name,
                       "reforge_step": step,
                       "attempt_index": i,
                       "is_winner": False
                   })

            # Evaluate refinements
            console.print(f"{indent}    [bold yellow]⚖️  Evaluating refinements...[/bold yellow]")

            evaluator_trace = reforge_trace.create_child("evaluator", "reforge_evaluation")

            # Use custom evaluator or default
            eval_instructions = reforge_config.evaluator_override or phase.soundings.evaluator_instructions

            eval_prompt = f"{eval_instructions}\n\n"
            eval_prompt += "Please evaluate the following refinements and select the best one.\n\n"

            for i, refinement in enumerate(reforge_results):
                eval_prompt += f"## Refinement {i+1}\n"
                eval_prompt += f"Result: {refinement['result']}\n\n"

            eval_prompt += f"\nRespond with ONLY the number of the best refinement (1-{len(reforge_results)}) and a brief explanation."

            evaluator_agent = Agent(
                model=self.model,
                system_prompt="You are an expert evaluator. Your job is to select the best refined version.",
                tools=[],
                base_url=self.base_url,
                api_key=self.api_key
            )

            eval_response = evaluator_agent.run(eval_prompt, context_messages=[])
            eval_content = eval_response.get("content", "")

            console.print(f"{indent}    [bold magenta]Evaluator:[/bold magenta] {eval_content[:150]}...")

            log_message(self.session_id, "reforge_evaluation", eval_content,
                       trace_id=evaluator_trace.id, parent_id=reforge_trace.id,
                       node_type="evaluation", depth=self.depth, reforge_step=step)

            # Add evaluator to echo history for visualization
            self.echo.add_history({
                "role": "reforge_evaluator",
                "content": eval_content if eval_content else "Evaluating...",  # Full content, no truncation
                "node_type": "reforge_evaluator"
            }, trace_id=evaluator_trace.id, parent_id=reforge_trace.id, node_type="reforge_evaluator",
               metadata={
                   "phase_name": phase.name,
                   "reforge_step": step
               })

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
                   "phase_name": phase.name,
                   "reforge_step": step,
                   "winner_index": winner_index,
                   "total_steps": reforge_config.steps
               })

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

        # Apply final winner's context
        self.context_messages = context_snapshot + winner['context']
        self.echo.state = winner['final_state']

        console.print(f"{indent}[bold green]🔨 Reforge Complete[/bold green]")

        return winner

    def execute_phase(self, phase: PhaseConfig, input_data: dict, trace: TraceNode, initial_injection: dict = None) -> Any:
        # Check if soundings (Tree of Thought) is enabled
        if phase.soundings and phase.soundings.factor > 1:
            return self._execute_phase_with_soundings(phase, input_data, trace, initial_injection)

        return self._execute_phase_internal(phase, input_data, trace, initial_injection)

    def _execute_phase_internal(self, phase: PhaseConfig, input_data: dict, trace: TraceNode, initial_injection: dict = None, mutation: str = None, mutation_mode: str = None) -> Any:
        indent = "  " * self.depth
        rag_context = None
        rag_prompt = ""
        rag_tool_names: List[str] = []

        def _cleanup_rag():
            if rag_context:
                clear_current_rag_context()

        # Prepare outputs dict for easier templating
        outputs = {item['phase']: item['output'] for item in self.echo.lineage}

        # Render Instructions (Jinja2)
        render_context = {
            "input": input_data,
            "state": self.echo.state,
            "history": self.echo.history,
            "outputs": outputs,
            "lineage": self.echo.lineage
        }

        # Build/update RAG index if configured for this phase
        if phase.rag:
            rag_context = ensure_rag_index(
                phase.rag,
                self.config_path,
                self.session_id,
                trace_id=trace.id,
                parent_id=trace.parent_id,
                phase_name=phase.name,
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
                phase.tackle and
                isinstance(phase.tackle, list) and
                rag_tools_in_tackle.intersection(phase.tackle)
            )

            if existing_ctx and phase_uses_rag_tools:
                # Reuse existing RAG context - no rebuild needed
                rag_context = existing_ctx
                rag_tool_names = list(rag_tools_in_tackle.intersection(phase.tackle))
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

        rendered_instructions = render_instruction(phase.instructions, render_context)

        # Apply mutation if provided (for sounding variations)
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
                    ward_name=ward_config.validator,
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
            validator_name = phase.rules.loop_until
            max_attempts = phase.rules.max_attempts if phase.rules.max_attempts else 5

            # Use custom prompt if provided, otherwise auto-generate from validator description
            if phase.rules.loop_until_prompt:
                validation_prompt = phase.rules.loop_until_prompt
            else:
                # Try to get validator description from manifest
                validator_description = None
                from .tackle_manifest import get_tackle_manifest
                manifest = get_tackle_manifest()
                if validator_name in manifest:
                    validator_description = manifest[validator_name].get("description", "")

                # Build validation prompt
                if validator_description:
                    validation_prompt = f"Your output will be validated using '{validator_name}' which checks: {validator_description}"
                else:
                    validation_prompt = f"Your output will be validated using the '{validator_name}' validator"

            # Inject validation requirement into instructions
            rendered_instructions += f"\n\n---\n**VALIDATION REQUIREMENT:**\n{validation_prompt}\nYou have {max_attempts} attempt(s) to satisfy this validator.\n---"

        # Determine model to use (phase override or default)
        phase_model = phase.model if phase.model else self.model

        console.print(f"\n{indent}[bold magenta]📍 Bearing (Phase): {phase.name}[/bold magenta] [bold cyan]🤖 {phase_model}[/bold cyan]")
        console.print(f"{indent}[italic]{rendered_instructions[:100]}...[/italic]")

        log_message(self.session_id, "phase_start", phase.name,
                   trace_id=trace.id, parent_id=trace.parent_id, node_type="phase", depth=trace.depth,
                   model=phase_model, parent_session_id=self.parent_session_id)

        # Resolve tools (Tackle) - Check if Quartermaster needed
        tackle_list = phase.tackle
        if phase.tackle == "manifest":
            console.print(f"{indent}  [bold cyan]🗺️  Quartermaster charting tackle...[/bold cyan]")
            tackle_list = self._run_quartermaster(phase, input_data, trace, phase_model)
            console.print(f"{indent}  [bold cyan]📋 Manifest: {', '.join(tackle_list)}[/bold cyan]")

        if rag_tool_names:
            for rag_tool in rag_tool_names:
                if rag_tool not in tackle_list:
                    tackle_list.append(rag_tool)

        tools_schema = []  # For native tool calling
        tool_descriptions = []  # For prompt-based tool calling
        tool_map = {}

        # Import memory system for dynamic tool registration
        from .memory import get_memory_system

        for t_name in tackle_list:
            t = get_tackle(t_name)
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
                    # Tool not found
                    pass

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

        if not use_native and tool_descriptions:
            # Prompt-based tools: Add tool descriptions to system prompt
            console.print(f"{indent}  [dim cyan]Using prompt-based tools (provider-agnostic)[/dim cyan]")
            tools_prompt = "\n\n## Available Tools\n\n" + "\n\n".join(tool_descriptions)
            tools_prompt += "\n\n**Important:** To call a tool, you MUST wrap your JSON in a ```json code fence:\n\n"
            tools_prompt += "Example:\n```json\n"
            tools_prompt += '{"tool": "tool_name", "arguments": {"param": "value"}}\n```\n\n'
            tools_prompt += "Do NOT output raw JSON outside of code fences - it will not be detected."
            final_instructions += tools_prompt
        else:
            console.print(f"{indent}  [dim cyan]Using native tool calling (provider-specific)[/dim cyan]")

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
                self.echo.add_history(sys_msg, trace_id=sys_trace.id, parent_id=trace.id, node_type="system")
                self.context_messages.append(sys_msg)

            # User message with the task
            task_content = f"## New Task\n\n{rendered_instructions}{rag_prompt}"
            user_trace = trace.create_child("msg", "phase_task")
            user_msg = {"role": "user", "content": task_content}
            self.echo.add_history(user_msg, trace_id=user_trace.id, parent_id=trace.id, node_type="user")
            self.context_messages.append(user_msg)
        else:
            # First phase: system message with tools + user message with task
            if not use_native and tool_descriptions:
                sys_trace = trace.create_child("msg", "tool_definitions")
                sys_msg = {"role": "system", "content": f"## Available Tools\n\n{tools_prompt}"}
                self.echo.add_history(sys_msg, trace_id=sys_trace.id, parent_id=trace.id, node_type="system")
                self.context_messages.append(sys_msg)

            # User message with the actual task
            task_content = rendered_instructions + rag_prompt
            user_trace = trace.create_child("msg", "phase_task")
            user_msg = {"role": "user", "content": task_content}
            self.echo.add_history(user_msg, trace_id=user_trace.id, parent_id=trace.id, node_type="user")
            self.context_messages.append(user_msg)

        # For debugging, log input data to echo (but NOT to context_messages)
        if input_data:
            input_trace = trace.create_child("msg", "input_data_reference")
            self.echo.add_history(
                {"role": "user", "content": f"## Input Data:\n{json.dumps(input_data)}"},
                trace_id=input_trace.id, parent_id=trace.id, node_type="user",
                metadata={"debug_only": True, "not_sent_to_llm": True}
            )

        # Handle Phase Start Injection
        injected_messages = []
        if initial_injection and initial_injection.get("action") == HookAction.INJECT:
            inject_content = initial_injection.get("content")
            console.print(f"{indent}[bold red]⚡ Injection Triggered:[/bold red] {inject_content}")
            injected_messages.append({"role": "user", "content": f"URGENT USER INJECTION: {inject_content}"})
            
            inject_trace = trace.create_child("msg", "injection")
            inject_msg = {"role": "user", "content": inject_content}
            self.echo.add_history(inject_msg, trace_id=inject_trace.id, parent_id=trace.id, node_type="injection")
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
                        if ref_path.startswith("windlass/"): # If it's already project-root-relative
                            # Assume project root is cwd
                            ref_path = os.path.join(os.getcwd(), ref_path)
                        elif isinstance(self.config_path, str): # Otherwise, relative to current config file
                            ref_path = os.path.join(os.path.dirname(self.config_path), ref_path)

                    # Determine sounding_index to pass to spawned cascade
                    async_sounding_index = None
                    if self.current_phase_sounding_index is not None:
                        async_sounding_index = self.current_phase_sounding_index
                    elif self.sounding_index is not None:
                        async_sounding_index = self.sounding_index

                    # Call spawn (fire and forget). spawn_cascade handles the threading.
                    # It needs the parent_trace object directly AND parent_session_id AND sounding_index
                    spawn_cascade(ref_path, sub_input, parent_trace=trace, parent_session_id=self.session_id, sounding_index=async_sounding_index)

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

                # Generate unique sub-cascade session ID (include sounding index if inside soundings)
                # Also determine which sounding_index to pass through to child
                sub_sounding_index = None
                if self.current_phase_sounding_index is not None:
                    # Inside phase-level sounding - include sounding index
                    sub_session_id = f"{self.session_id}_sub_{self.current_phase_sounding_index}"
                    sub_sounding_index = self.current_phase_sounding_index
                elif self.sounding_index is not None:
                    # Inside cascade-level sounding - include sounding index
                    sub_session_id = f"{self.session_id}_sub_{self.sounding_index}"
                    sub_sounding_index = self.sounding_index
                else:
                    # Normal execution - no sounding
                    sub_session_id = f"{self.session_id}_sub"

                # Pass trace context AND HOOKS AND parent_session_id AND sounding_index
                sub_result = run_cascade(ref_path, sub_input, sub_session_id, self.overrides, self.depth + 1, parent_trace=trace, hooks=self.hooks, parent_session_id=self.session_id, sounding_index=sub_sounding_index)

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
                                          "phase_name": phase.name,
                                          "attempt": attempt + 1,
                                          "max_attempts": max_attempts,
                                          "loop_until": phase.rules.loop_until if phase.rules.loop_until else None
                                      })
                self._update_graph()

            # Turn loop
            for i in range(max_turns):
                # Track turn number
                self.current_turn_number = i if max_turns > 1 else None

                # Prune expired context based on TTL (context timebomb!)
                if phase.context_ttl and i > 0:  # Don't prune on first turn
                    self._prune_expired_context(i)

                # Update phase progress for visualization
                update_phase_progress(
                    self.session_id, self.config.cascade_id, phase.name, self.depth,
                    turn=i + 1,
                    max_turns=max_turns
                )

                # Hook: Turn Start
                hook_result = self.hooks.on_turn_start(phase.name, i, {
                    "echo": self.echo,
                    "sounding_index": self.current_phase_sounding_index or self.sounding_index,
                })
                turn_injection = ""
                if hook_result.get("action") == HookAction.INJECT:
                    turn_injection = hook_result.get("content")
                    console.print(f"{indent}[bold red]⚡ Turn Injection:[/bold red] {turn_injection}")

                # Trace Turn
                turn_trace = trace.create_child("turn", f"turn_{i+1}")

                # Add turn structure to Echo for visualization
                self.echo.add_history({
                    "role": "structure",
                    "content": f"Turn {i+1}",
                    "node_type": "turn"
                }, trace_id=turn_trace.id, parent_id=trace.id, node_type="turn",
                   metadata={"phase_name": phase.name, "turn_number": i+1, "max_turns": max_turns})

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
                            import os

                            # Get config from environment (with defaults)
                            keep_images = int(os.getenv('WINDLASS_KEEP_RECENT_IMAGES', '0'))
                            keep_turns = int(os.getenv('WINDLASS_KEEP_RECENT_TURNS', '0'))

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
                                            "phase_name": phase.name
                                        }
                                    )

                            if self.depth == 0 and is_main_thread:
                                with console.status(f"{indent}[bold green]Agent thinking...[/bold green] ", spinner="dots") as status:
                                    response_dict = agent.run(current_input, context_messages=self.context_messages)
                            else:
                                # For sub-cascades, no spinner to avoid Rich Live conflicts
                                console.print(f"{indent}[dim]Agent thinking (depth {self.depth})...[/dim]")
                                response_dict = agent.run(current_input, context_messages=self.context_messages)

                            content = response_dict.get("content")
                            tool_calls = response_dict.get("tool_calls")
                            request_id = response_dict.get("id")

                            # CRITICAL: Detect empty responses - this is an infrastructure error
                            # Empty responses indicate API issues, not validation failures
                            if (not content or content.strip() == "") and not tool_calls:
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
                                        "phase_name": phase.name,
                                        "cascade_id": self.config.cascade_id
                                    }
                                )

                                if infra_attempt + 1 >= infrastructure_max_retries:
                                    console.print(f"{indent}  [bold red]Max infrastructure retries reached. Failing.[/bold red]")
                                    raise Exception(error_msg)
                                else:
                                    console.print(f"{indent}  [yellow]Retrying due to empty response...[/yellow]")
                                    continue  # Retry infrastructure loop

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
                                    "phase_name": phase.name,
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

                    # Build metadata
                    agent_metadata = {
                        "retry_attempt": self.current_retry_attempt,
                        "turn_number": self.current_turn_number,
                        "phase_name": phase.name,
                        "cascade_id": self.config.cascade_id
                    }

                    # Get cascade and phase configs for logging
                    cascade_config_dict = self.config.model_dump() if hasattr(self.config, 'model_dump') else None
                    phase_config_dict = phase.model_dump() if hasattr(phase, 'model_dump') else None

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
                        sounding_index=self.current_phase_sounding_index,
                        is_winner=None,  # Set later when sounding evaluation happens
                        reforge_step=getattr(self, 'current_reforge_step', None),
                        attempt_number=self.current_retry_attempt,
                        turn_number=self.current_turn_number,
                        mutation_applied=self.current_mutation_applied,
                        mutation_type=self.current_mutation_type,
                        mutation_template=self.current_mutation_template,
                        cascade_id=self.config.cascade_id,
                        cascade_file=self.config_path if isinstance(self.config_path, str) else None,
                        cascade_config=cascade_config_dict,
                        phase_name=phase.name,
                        phase_config=phase_config_dict,
                        model=model_used,
                        request_id=request_id,
                        provider=provider,
                        duration_ms=None,  # Not tracking per-message duration yet
                        tokens_in=tokens_in,
                        tokens_out=tokens_out,
                        cost=cost,
                        content=content,
                        full_request=full_request,
                        full_response=full_response,
                        tool_calls=tool_calls,
                        images=None,  # Images handled separately
                        has_base64=False,
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
                    # Tag with TTL if configured
                    assistant_msg = self._tag_message_with_ttl(assistant_msg, "assistant", phase)
                    self.context_messages.append(assistant_msg)

                    # Add to Echo (global history)
                    input_trace = turn_trace.create_child("msg", "user_input")
                    if current_input:
                         self.echo.add_history({"role": "user", "content": current_input}, trace_id=input_trace.id, parent_id=turn_trace.id, node_type="turn_input",
                                             metadata=self._get_metadata({"phase_name": phase.name, "turn": i}))

                    # NOTE: Agent output is now logged via cost tracker with cost merged in
                    # No need to log turn_output separately (was duplicate)
                    self._update_graph()

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
                                       metadata={"phase_name": phase.name, "turn": i},
                                       trace_id=error_trace.id, parent_id=turn_trace.parent_id, node_type="validation_error")

                            # Add error to echo history
                            error_msg = {
                                "role": "user",
                                "content": f"⚠️ Tool Call JSON Error:\n{parse_error}\n\nPlease fix the JSON and try again. Ensure proper brace matching: {{ and }}"
                            }
                            self.echo.add_history(error_msg, trace_id=error_trace.id, parent_id=turn_trace.id, node_type="validation_error",
                                                metadata=self._get_metadata({"phase_name": phase.name, "turn": i}))

                            # CRITICAL: Set validation_passed = False to trigger attempt retry
                            # JSON errors should retry the entire attempt, not just skip to next turn
                            validation_passed = False
                            json_parse_error = True

                            # Break from turn loop - will check validation_passed and retry if needed
                            break

                        elif parsed_tool_calls:
                            console.print(f"{indent}  [dim cyan]Parsed {len(parsed_tool_calls)} prompt-based tool call(s)[/dim cyan]")
                            tool_calls = parsed_tool_calls

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
                                metadata={"tool_name": func_name, "arguments": args}
                            )

                            # Update phase progress with current tool
                            update_phase_progress(
                                self.session_id, self.config.cascade_id, phase.name, self.depth,
                                tool_name=func_name
                            )

                            # Find tool
                            tool_func = tool_map.get(func_name)
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
                                next_idx = get_next_image_index(self.session_id, phase.name, self.current_phase_sounding_index)

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
                                            sounding_index=self.current_phase_sounding_index
                                        )
                                        try:
                                            decode_and_save_image(encoded_img, save_path)
                                            saved_image_paths.append(save_path)
                                            console.print(f"{indent}    [dim]💾 Saved image: {save_path}[/dim]")
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
                                next_audio_idx = get_next_audio_index(self.session_id, phase.name, self.current_phase_sounding_index)

                                for i, audio_path in enumerate(audio_files):
                                    if os.path.exists(audio_path):
                                        # Save audio to structured directory
                                        save_path = get_audio_save_path(
                                            self.session_id,
                                            phase.name,
                                            next_audio_idx + i,
                                            extension=audio_path.split('.')[-1] if '.' in audio_path else 'mp3',
                                            sounding_index=self.current_phase_sounding_index
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
                            # Tag with TTL if configured
                            tool_msg = self._tag_message_with_ttl(tool_msg, "tool_results", phase)
                            self.context_messages.append(tool_msg)

                            # DEBUG: Verify tool result was added
                            console.print(f"{indent}    [dim cyan][DEBUG] Tool result added to context_messages[/dim cyan]")
                            console.print(f"{indent}    [dim]  Index: {len(self.context_messages)-1}, Tool: {func_name}, Result: {len(str(result))} chars[/dim]")

                            # Add to Echo (auto-logs via unified_logs)
                            result_trace = tool_trace.create_child("msg", "tool_result")
                            self.echo.add_history(tool_msg, trace_id=result_trace.id, parent_id=tool_trace.id, node_type="tool_result",
                                                 metadata={"tool_name": func_name, "result": str(result)[:500]})
                        
                            # Inject Image Message if present
                            if image_injection_message:
                                # Tag with TTL if configured
                                image_injection_message = self._tag_message_with_ttl(image_injection_message, "images", phase)
                                self.context_messages.append(image_injection_message)
                                img_trace = tool_trace.create_child("msg", "image_injection")
                                self.echo.add_history(image_injection_message, trace_id=img_trace.id, parent_id=tool_trace.id, node_type="injection",
                                                     metadata={"sounding_index": self.current_phase_sounding_index, "phase_name": phase.name})

                            self._update_graph() # Update after tool

                        # Immediate follow-up
                        # Cull old content to prevent token explosion
                        from .utils import cull_old_base64_images, cull_old_conversation_history
                        import os

                        # Get config from environment (with defaults)
                        keep_images = int(os.getenv('WINDLASS_KEEP_RECENT_IMAGES', '0'))
                        keep_turns = int(os.getenv('WINDLASS_KEEP_RECENT_TURNS', '0'))

                        # FIX: Actually update self.context_messages (not just temporary variable!)
                        # Previous bug: culling was temporary, never persisted, all images accumulated
                        self.context_messages = cull_old_conversation_history(self.context_messages, keep_recent_turns=keep_turns)

                        # For follow-up, keep ONLY the most recent image (for iterative feedback)
                        # This retains the latest generated image while dropping all older ones
                        # Rationale: Agent already saw old images, they're saved to disk, only need latest for refinement
                        self.context_messages = cull_old_base64_images(self.context_messages, keep_recent=1)

                        if self.depth == 0 and is_main_thread:
                            with console.status(f"{indent}[bold green]Agent processing results...[/bold green]", spinner="dots") as status:
                                follow_up = agent.run(None, context_messages=self.context_messages)
                        else:
                            console.print(f"{indent}[dim]Agent processing results (depth {self.depth})...[/dim]")
                            follow_up = agent.run(None, context_messages=self.context_messages)
                         
                        content = follow_up.get("content")
                        request_id = follow_up.get("id")
                        model_used = follow_up.get("model", self.model)
                        provider = follow_up.get("provider", "unknown")
                        full_request = follow_up.get("full_request")  # Capture full request
                        full_response = follow_up.get("full_response")  # Capture full response

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
                                phase_name=phase.name,
                                cascade_id=self.config.cascade_id,
                                model=model_used,
                                request_id=request_id,  # For non-blocking cost tracking
                                provider=provider,
                                content=content,
                                full_request=full_request,  # ADD: Include complete request with images
                                full_response=full_response,  # ADD: Include complete response
                                metadata={"is_follow_up": True, "turn_number": self.current_turn_number}
                            )

                            self._update_graph() # Update after follow up
                            response_content = content
                        else:
                            # Log that follow-up had no content (don't add to history - would cause API error)
                            log_message(self.session_id, "system", "Follow-up response had empty content (not added to history)",
                                       trace_id=turn_trace.id, parent_id=turn_trace.parent_id, node_type="warning", depth=turn_trace.depth)

                        # Auto-save any images from messages (catches manual injection, feedback loops, etc.)
                        self._save_images_from_messages(self.context_messages, phase.name)

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
                        "phase_name": phase.name,
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

                    self.echo.add_history(
                        {"role": "system", "content": error_content},
                        trace_id=turn_trace.id,
                        parent_id=turn_trace.parent_id,
                        node_type="error",
                        metadata=error_metadata
                    )

                    # Track error in echo for cascade-level status
                    self.echo.add_error(
                        phase=phase.name,
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
                           "phase_name": phase.name,
                           "valid": True,
                           "attempt": attempt + 1
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
                           "phase_name": phase.name,
                           "valid": False,
                           "reason": error_msg,
                           "attempt": attempt + 1,
                           "max_attempts": max_attempts
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
            if phase.rules.loop_until:
                validator_name = phase.rules.loop_until
                console.print(f"{indent}[bold cyan]🛡️  Running Validator: {validator_name}[/bold cyan]")

                # Create validation trace
                validation_trace = trace.create_child("validation", validator_name)

                # Add to echo history (auto-logs via unified system - no need for separate log_message)
                self.echo.add_history({
                    "role": "validation",
                    "content": f"🛡️ Running validator: {validator_name}",
                    "node_type": "validation_start"
                }, trace_id=validation_trace.id, parent_id=trace.id, node_type="validation_start",
                   metadata={
                       "phase_name": phase.name,
                       "validator": validator_name,
                       "attempt": attempt + 1,
                       "content_preview": response_content[:200] if response_content else "(empty)"
                   })

                # Initialize validator_result to None (ensures it's in scope for logging later)
                validator_result = None

                # Try to get validator as Python function first
                validator_tool = get_tackle(validator_name)

                # If not found as function, check if it's a cascade tool
                if not validator_tool:
                    from .tackle_manifest import get_tackle_manifest
                    manifest = get_tackle_manifest()

                    if validator_name in manifest and manifest[validator_name]["type"] == "cascade":
                        # It's a cascade validator - invoke it as a sub-cascade
                        cascade_path = manifest[validator_name]["path"]
                        # Pass both the output AND original input for context (validators can use what they need)
                        validator_input = {
                            "content": response_content,
                            "original_input": input_data
                        }

                        # Generate unique validator session ID (include sounding index if inside soundings)
                        validator_sounding_index = None
                        if self.current_phase_sounding_index is not None:
                            validator_session_id = f"{self.session_id}_validator_{attempt}_{self.current_phase_sounding_index}"
                            validator_sounding_index = self.current_phase_sounding_index
                        elif self.sounding_index is not None:
                            validator_session_id = f"{self.session_id}_validator_{attempt}_{self.sounding_index}"
                            validator_sounding_index = self.sounding_index
                        else:
                            validator_session_id = f"{self.session_id}_validator_{attempt}"

                        console.print(f"{indent}  [dim]Running cascade validator: {validator_name} (session: {validator_session_id})[/dim]")

                        # Log sub-cascade reference to parent
                        log_message(self.session_id, "sub_cascade_ref", f"Validator sub-cascade: {validator_name}",
                                   {"validator": validator_name, "sub_session_id": validator_session_id,
                                    "cascade_path": cascade_path, "phase_name": phase.name},
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
                                sounding_index=validator_sounding_index
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
                       "phase_name": phase.name,
                       "validator": validator_name,
                       "valid": is_valid,
                       "reason": reason,
                       "attempt": attempt + 1,
                       "max_attempts": max_attempts
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
                        ward_name=ward_config.validator,
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
                            "phase": phase.name,
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
        return chosen_next_phase if chosen_next_phase else response_content

def run_cascade(config_path: str | dict, input_data: dict = None, session_id: str = "default", overrides: dict = None,
                depth: int = 0, parent_trace: TraceNode = None, hooks: WindlassHooks = None, parent_session_id: str = None,
                sounding_index: int = None) -> dict:
    runner = WindlassRunner(config_path, session_id, overrides, depth, parent_trace, hooks, sounding_index=sounding_index, parent_session_id=parent_session_id)
    result = runner.run(input_data)
    
    if depth == 0:
        # Only print tree at the end of the root
        graph_dir = get_config().graph_dir
        graph_path = generate_mermaid(runner.echo, os.path.join(graph_dir, f"{session_id}.mmd"))
        console.print(f"\n[bold cyan]📊 Execution Graph saved to:[/bold cyan] {graph_path}")
        
    return result
