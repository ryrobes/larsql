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
from .state import update_session_state
from .eddies.system import spawn_cascade
from .eddies.state_tools import set_current_session_id
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
        self.echo = get_echo(session_id)
        self.depth = depth
        self.max_depth = 5
        self.hooks = hooks or WindlassHooks()
        self.context_messages: List[Dict[str, str]] = []
        self.sounding_index = sounding_index  # Track which sounding attempt this is (for cascade-level soundings)
        self.current_phase_sounding_index = None  # Track sounding index within current phase
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
            sounding_echo = Echo(sounding_session_id)

            try:
                # Create a new runner for this sounding with sounding_index set
                sounding_runner = WindlassRunner(
                    config_path=self.config_path,
                    session_id=sounding_session_id,
                    overrides=self.overrides,
                    depth=self.depth,
                    parent_trace=sounding_trace,
                    hooks=self.hooks,
                    sounding_index=i  # Mark this runner as part of a sounding
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
            "content": eval_content[:150] if eval_content else "Evaluating...",
            "node_type": "cascade_evaluator"
        }, trace_id=evaluator_trace.id, parent_id=soundings_trace.id, node_type="cascade_evaluator",
           metadata={
               "cascade_id": self.config.cascade_id,
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

        # Add soundings result to history (auto-logs via unified_logs)
        self.echo.add_history({
            "role": "cascade_soundings_result",
            "content": f"🏆 Winner: Cascade #{winner_index + 1}",
            "node_type": "cascade_soundings_result"
        }, trace_id=soundings_trace.id, parent_id=self.trace.id, node_type="cascade_soundings_result",
           metadata={
               "cascade_id": self.config.cascade_id,
               "winner_index": winner_index,
               "winner_session_id": f"{self.session_id}_sounding_{winner_index}",
               "factor": factor,
               "evaluation": eval_content[:200],
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
                refinement_echo = Echo(refinement_session_id)

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
                        hooks=self.hooks
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
            "parent_session_id": getattr(self, 'parent_session_id', None)
        })

        log_message(self.session_id, "system", f"Starting cascade {self.config.cascade_id}", input_data,
                   trace_id=self.trace.id, parent_id=self.trace.parent_id, node_type="cascade", depth=self.depth,
                   sounding_index=self.sounding_index)

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
            hook_result = self.hooks.on_phase_start(phase.name, {"echo": self.echo, "input": input_data})

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

            output_or_next_phase = self.execute_phase(phase, input_data, phase_trace, initial_injection=hook_result)

            # Log phase completion for UI visibility
            log_message(self.session_id, "phase_complete", f"Phase {phase.name} completed",
                       trace_id=phase_trace.id, parent_id=phase_trace.parent_id, node_type="phase",
                       depth=self.depth, phase_name=phase.name, cascade_id=self.config.cascade_id)

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
                   node_type=f"cascade_{final_status}")

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
               "reasoning": response_content[:200],
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

                try:
                    # Run the validator cascade
                    validator_result_echo = run_cascade(
                        cascade_path,
                        validator_input,
                        f"{self.session_id}_ward",
                        self.overrides,
                        self.depth + 1,
                        parent_trace=ward_trace,
                        hooks=self.hooks
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

        # Execute each sounding in sequence (to avoid threading complexity with Rich output)
        # Each sounding gets the same starting context
        for i in range(factor):
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
                    "mutation_template": mutation_template
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
                    "mutation_template": mutation_template
                })

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
        console.print(f"{indent}[bold yellow]⚖️  Evaluating {len(sounding_results)} soundings...[/bold yellow]")

        # Create evaluator trace
        evaluator_trace = soundings_trace.create_child("evaluator", "sounding_evaluation")

        # Build evaluation prompt
        eval_prompt = f"{phase.soundings.evaluator_instructions}\n\n"
        eval_prompt += "Please evaluate the following attempts and select the best one.\n\n"

        for i, sounding in enumerate(sounding_results):
            eval_prompt += f"## Attempt {i+1}\n"
            eval_prompt += f"Result: {sounding['result']}\n\n"

        eval_prompt += "\nRespond with ONLY the number of the best attempt (1-{0}) and a brief explanation.".format(len(sounding_results))

        # Create evaluator agent
        evaluator_agent = Agent(
            model=self.model,
            system_prompt="You are an expert evaluator. Your job is to compare multiple attempts and select the best one.",
            tools=[],
            base_url=self.base_url,
            api_key=self.api_key
        )

        # Run evaluation
        eval_response = evaluator_agent.run(eval_prompt, context_messages=[])
        eval_content = eval_response.get("content", "")

        console.print(f"{indent}  [bold magenta]Evaluator:[/bold magenta] {eval_content[:200]}...")

        # Extract winner index from evaluation (simple parsing - look for first digit)
        winner_index = 0
        import re
        match = re.search(r'\b([1-9]\d*)\b', eval_content)
        if match:
            winner_index = int(match.group(1)) - 1  # Convert to 0-indexed
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
            self.echo.add_history({
                "role": "sounding_attempt",
                "content": str(sr["result"])[:200] if sr["result"] else "",
                "node_type": "sounding_attempt"
            }, trace_id=sr["trace_id"], parent_id=soundings_trace.id, node_type="sounding_attempt",
               metadata={
                   "phase_name": phase.name,
                   "sounding_index": sr["index"],
                   "is_winner": is_winner,
                   "factor": factor,
                   "mutation_applied": sr.get("mutation_applied")  # Log what mutation was used
               })

        # Add evaluator entry (auto-logs via unified_logs)
        self.echo.add_history({
            "role": "evaluator",
            "content": eval_content[:200],
            "node_type": "evaluator"
        }, trace_id=evaluator_trace.id, parent_id=soundings_trace.id, node_type="evaluator",
           metadata={
               "phase_name": phase.name,
               "winner_index": winner_index,
               "winner_trace_id": winner['trace_id'],
               "evaluation": eval_content,
               "model": self.model
           })

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
                "content": eval_content[:150] if eval_content else "Evaluating...",
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

            # Prepare input content for validation
            input_content = json.dumps(input_data)

            for ward_config in phase.wards.pre:
                ward_result = self._run_ward(ward_config, input_content, trace, ward_type="pre")

                if not ward_result["valid"]:
                    # Handle based on mode
                    if ward_result["mode"] == "blocking":
                        console.print(f"{indent}[bold red]⛔ Pre-Ward BLOCKING: Phase aborted[/bold red]")
                        log_message(self.session_id, "pre_ward_blocked", f"Phase blocked by {ward_result['validator']}",
                                   {"reason": ward_result["reason"]},
                                   trace_id=trace.id, parent_id=trace.parent_id,
                                   node_type="ward_block", depth=self.depth)
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
        
        # Determine model to use (phase override or default)
        phase_model = phase.model if phase.model else self.model

        console.print(f"\n{indent}[bold magenta]📍 Bearing (Phase): {phase.name}[/bold magenta] [bold cyan]🤖 {phase_model}[/bold cyan]")
        console.print(f"{indent}[italic]{rendered_instructions[:100]}...[/italic]")

        log_message(self.session_id, "phase_start", phase.name,
                   trace_id=trace.id, parent_id=trace.parent_id, node_type="phase", depth=trace.depth,
                   model=phase_model)

        # Resolve tools (Tackle) - Check if Quartermaster needed
        tackle_list = phase.tackle
        if phase.tackle == "manifest":
            console.print(f"{indent}  [bold cyan]🗺️  Quartermaster charting tackle...[/bold cyan]")
            tackle_list = self._run_quartermaster(phase, input_data, trace, phase_model)
            console.print(f"{indent}  [bold cyan]📋 Manifest: {', '.join(tackle_list)}[/bold cyan]")

        tools_schema = []  # For native tool calling
        tool_descriptions = []  # For prompt-based tool calling
        tool_map = {}

        for t_name in tackle_list:
            t = get_tackle(t_name)
            if t:
                tool_map[t_name] = t
                # Generate both formats
                tools_schema.append(get_tool_schema(t, name=t_name))
                tool_descriptions.append(self._generate_tool_description(t, t_name))
            else:
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
        final_instructions = rendered_instructions
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

        # Add initial messages to echo history
        sys_trace = trace.create_child("msg", "system_instructions")
        sys_msg = {"role": "system", "content": final_instructions}
        self.echo.add_history(sys_msg, trace_id=sys_trace.id, parent_id=trace.id, node_type="system")

        # Append to snowball context
        self.context_messages.append(sys_msg)

        # NOTE: We do NOT add a separate "## Input Data:" user message
        # Input data is already available to the agent via:
        # 1. Jinja2 template rendering in system prompt (e.g., {{ input.problem }})
        # 2. Snowball context from previous phases (full conversation history)
        # Adding a redundant user message would confuse the agent with duplicate information.

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
                    
                    # Call spawn (fire and forget). spawn_cascade handles the threading.
                    # It needs the parent_trace object directly AND parent_session_id
                    spawn_cascade(ref_path, sub_input, parent_trace=trace, parent_session_id=self.session_id)

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

                # Pass trace context AND HOOKS AND parent_session_id
                sub_result = run_cascade(ref_path, sub_input, f"{self.session_id}_sub", self.overrides, self.depth + 1, parent_trace=trace, hooks=self.hooks, parent_session_id=self.session_id)
                
                # 2. Handle Output (Context Out)
                if sub.context_out:
                    # Merge echoes logic
                    self.echo.merge(get_echo(f"{self.session_id}_sub"))
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
                self.echo.add_history(retry_msg, trace_id=retry_trace.id, parent_id=trace.id, node_type="validation_retry")
                self._update_graph()

            # Turn loop
            for i in range(max_turns):
                # Track turn number
                self.current_turn_number = i if max_turns > 1 else None

                # Hook: Turn Start
                hook_result = self.hooks.on_turn_start(phase.name, i, {"echo": self.echo})
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
                if turn_injection:
                    current_input = f"USER INJECTION: {turn_injection}"
                elif i == 0:
                    current_input = None # Handled by snowball
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
                    self.context_messages.append(assistant_msg)

                    # Add to Echo (global history)
                    input_trace = turn_trace.create_child("msg", "user_input")
                    if current_input:
                         self.echo.add_history({"role": "user", "content": current_input}, trace_id=input_trace.id, parent_id=turn_trace.id, node_type="turn_input")

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
                            self.echo.add_history(error_msg, trace_id=error_trace.id, parent_id=turn_trace.id, node_type="validation_error")

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

                            # Find tool
                            tool_func = tool_map.get(func_name)
                            result = "Tool not found."
                        
                            # Check for route_to specifically to capture state
                            if func_name == "route_to" and "target" in args:
                                chosen_next_phase = args["target"]
                                console.print(f"{indent}  🚀 [bold magenta]Dynamic Handoff Triggered:[/bold magenta] {chosen_next_phase}")
                        
                            if tool_func:
                                 # Set context for tool (e.g. spawn_cascade)
                                 set_current_trace(tool_trace)
                                 try:
                                     result = tool_func(**args)
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
                                                 metadata={"tool_name": func_name, "result": str(result)[:500]})
                        
                            # Inject Image Message if present
                            if image_injection_message:
                                self.context_messages.append(image_injection_message)
                                img_trace = tool_trace.create_child("msg", "image_injection")
                                self.echo.add_history(image_injection_message, trace_id=img_trace.id, parent_id=tool_trace.id, node_type="injection",
                                                     metadata={"sounding_index": self.current_phase_sounding_index, "phase_name": phase.name})

                            self._update_graph() # Update after tool

                        # Immediate follow-up
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
                            from .unified_logs import log_unified
                            log_unified(
                                session_id=self.session_id,
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
                        validator_input = {"content": response_content}

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
                                parent_session_id=self.session_id
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

                for ward_config in phase.wards.post:
                    ward_result = self._run_ward(ward_config, response_content, trace, ward_type="post")

                    if not ward_result["valid"]:
                        # Handle based on mode
                        if ward_result["mode"] == "blocking":
                            console.print(f"{indent}[bold red]⛔ Post-Ward BLOCKING: Phase failed[/bold red]")
                            log_message(self.session_id, "post_ward_blocked", f"Phase blocked by {ward_result['validator']}",
                                       {"reason": ward_result["reason"]},
                                       trace_id=trace.id, parent_id=trace.parent_id,
                                       node_type="ward_block", depth=self.depth)
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

        return chosen_next_phase if chosen_next_phase else response_content

def run_cascade(config_path: str | dict, input_data: dict = None, session_id: str = "default", overrides: dict = None,
                depth: int = 0, parent_trace: TraceNode = None, hooks: WindlassHooks = None, parent_session_id: str = None) -> dict:
    runner = WindlassRunner(config_path, session_id, overrides, depth, parent_trace, hooks, sounding_index=None, parent_session_id=parent_session_id)
    result = runner.run(input_data)
    
    if depth == 0:
        # Only print tree at the end of the root
        graph_dir = get_config().graph_dir
        graph_path = generate_mermaid(runner.echo, os.path.join(graph_dir, f"{session_id}.mmd"))
        console.print(f"\n[bold cyan]📊 Execution Graph saved to:[/bold cyan] {graph_path}")
        
    return result
