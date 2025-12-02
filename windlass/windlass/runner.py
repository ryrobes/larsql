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
from .cost import track_request # Ensure this is imported

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
                 sounding_index: int = None):
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

        # Log cascade soundings start
        log_message(self.session_id, "cascade_soundings_start", f"{self.config.cascade_id} with {factor} attempts",
                   trace_id=soundings_trace.id, parent_id=self.trace.id, node_type="cascade_soundings", depth=self.depth)

        # Add to echo history for visualization
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

                # Log this sounding completion with metadata
                log_message(self.session_id, "cascade_sounding_complete", f"Sounding {i+1} completed",
                           {"result_preview": str(final_output)[:200]},
                           trace_id=sounding_trace.id, parent_id=soundings_trace.id,
                           node_type="cascade_sounding", depth=self.depth,
                           sounding_index=i, is_winner=False)  # Will update winner later

                # Add to echo history for visualization - store sub-session reference
                self.echo.add_history({
                    "role": "cascade_sounding_attempt",
                    "content": str(final_output)[:150] if final_output else "Completed",
                    "node_type": "cascade_sounding_attempt"
                }, trace_id=sounding_trace.id, parent_id=soundings_trace.id, node_type="cascade_sounding_attempt",
                   metadata={
                       "cascade_id": self.config.cascade_id,
                       "sounding_index": i,
                       "sub_session_id": sounding_session_id,
                       "is_winner": False  # Updated later when winner is selected
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

        # Log evaluation reasoning
        log_message(self.session_id, "cascade_sounding_evaluation", eval_content,
                   trace_id=evaluator_trace.id, parent_id=soundings_trace.id,
                   node_type="evaluation", depth=self.depth)

        # Add evaluator to echo history for visualization
        self.echo.add_history({
            "role": "cascade_evaluator",
            "content": eval_content[:150] if eval_content else "Evaluating...",
            "node_type": "cascade_evaluator"
        }, trace_id=evaluator_trace.id, parent_id=soundings_trace.id, node_type="cascade_evaluator",
           metadata={
               "cascade_id": self.config.cascade_id,
               "factor": factor
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

        # Log the winner selection with is_winner=True
        log_message(self.session_id, "cascade_sounding_winner", f"Selected cascade execution {winner_index + 1}",
                   {"winner_trace_id": winner['trace_id'], "evaluation": eval_content},
                   trace_id=soundings_trace.id, parent_id=self.trace.id,
                   node_type="winner", depth=self.depth,
                   sounding_index=winner_index, is_winner=True)

        # Merge winner's echo into our main echo (this becomes the "canon" result)
        if winner['echo']:
            # Copy winner's state, history, and lineage into main echo
            self.echo.state.update(winner['echo'].state)
            self.echo.history.extend(winner['echo'].history)
            self.echo.lineage.extend(winner['echo'].lineage)

        # Add soundings result to history
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
               "evaluation": eval_content[:200]
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
        self.hooks.on_cascade_start(self.config.cascade_id, self.session_id, {"depth": self.depth, "input": input_data})

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

        update_session_state(self.session_id, self.config.cascade_id, "completed", "end", self.depth)

        result = self.echo.get_full_echo()

        # Hook: Cascade Complete
        self.hooks.on_cascade_complete(self.config.cascade_id, self.session_id, result)

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

    def _run_quartermaster(self, phase: PhaseConfig, input_data: dict, trace: TraceNode) -> list[str]:
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

        # Create quartermaster agent
        qm_agent = Agent(
            model=self.model,
            system_prompt="You are an expert Quartermaster who selects the right tools for each job.",
            tools=[],
            base_url=self.base_url,
            api_key=self.api_key
        )

        # Run quartermaster
        log_message(self.session_id, "quartermaster_start", "Manifesting tackle",
                   trace_id=qm_trace.id, parent_id=trace.id, node_type="quartermaster", depth=self.depth)

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

        # Log selection
        log_message(self.session_id, "quartermaster_result", f"Selected: {valid_tackle}",
                   {"reasoning": response_content, "manifest_context": phase.manifest_context},
                   trace_id=qm_trace.id, parent_id=trace.id, node_type="quartermaster_result", depth=self.depth)

        # Add to echo history for visualization
        self.echo.add_history({
            "role": "quartermaster",
            "content": f"Selected tools: {', '.join(valid_tackle) if valid_tackle else 'none'}",
            "node_type": "quartermaster_result"
        }, trace_id=qm_trace.id, parent_id=trace.id, node_type="quartermaster_result",
           metadata={
               "phase_name": phase.name,
               "selected_tackle": valid_tackle,
               "reasoning": response_content[:200]
           })

        console.print(f"{indent}    [dim]Reasoning: {response_content[:150]}...[/dim]")

        return valid_tackle

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

        # Log ward result
        log_message(self.session_id, f"{ward_type}_ward", f"{validator_name}: {is_valid}",
                   {"validator": validator_name, "mode": mode, "valid": is_valid, "reason": reason},
                   trace_id=ward_trace.id, parent_id=trace.id,
                   node_type=f"{ward_type}_ward", depth=self.depth)

        # Add ward to Echo history for visualization
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

        # Log soundings start with rich metadata
        soundings_meta = {
            "phase_name": phase.name,
            "factor": factor,
            "has_reforge": phase.soundings.reforge is not None
        }
        log_message(self.session_id, "soundings_start", f"{phase.name} with {factor} attempts",
                   trace_id=soundings_trace.id, parent_id=trace.id, node_type="soundings", depth=self.depth)

        # Add soundings structure to Echo for visualization
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

        # Execute each sounding in sequence (to avoid threading complexity with Rich output)
        # Each sounding gets the same starting context
        for i in range(factor):
            console.print(f"{indent}  [cyan]🌊 Sounding {i+1}/{factor}[/cyan]")

            # Create trace for this sounding
            sounding_trace = soundings_trace.create_child("sounding_attempt", f"attempt_{i+1}")

            # Reset context to snapshot for this attempt
            self.context_messages = context_snapshot.copy()
            self.echo.state = echo_state_snapshot.copy()
            self.echo.history = echo_history_snapshot.copy()
            self.echo.lineage = echo_lineage_snapshot.copy()

            # Execute the phase normally
            try:
                result = self._execute_phase_internal(phase, input_data, sounding_trace, initial_injection)

                # Capture the context that was generated during this sounding
                sounding_context = self.context_messages[len(context_snapshot):]  # New messages added

                sounding_results.append({
                    "index": i,
                    "result": result,
                    "context": sounding_context,
                    "trace_id": sounding_trace.id,
                    "final_state": self.echo.state.copy()
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
                    "final_state": {}
                })

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

        # Log evaluation reasoning
        log_message(self.session_id, "sounding_evaluation", eval_content,
                   trace_id=evaluator_trace.id, parent_id=soundings_trace.id, node_type="evaluation", depth=self.depth)

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

        # Log the winner selection
        log_message(self.session_id, "sounding_winner", f"Selected attempt {winner_index + 1}",
                   {"winner_trace_id": winner['trace_id'], "evaluation": eval_content},
                   trace_id=soundings_trace.id, parent_id=trace.id, node_type="winner", depth=self.depth)

        # Now apply ONLY the winner's context to the main snowball
        self.context_messages = context_snapshot + winner['context']
        self.echo.state = winner['final_state']

        # Add all sounding attempts to Echo history with metadata for visualization
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
                   "factor": factor
               })

        # Add evaluator entry
        self.echo.add_history({
            "role": "evaluator",
            "content": eval_content[:200],
            "node_type": "evaluator"
        }, trace_id=evaluator_trace.id, parent_id=soundings_trace.id, node_type="evaluator",
           metadata={"phase_name": phase.name, "winner_index": winner_index})

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
        Auto-save ALL images found in message history to structured directory.
        This catches images from ANY source (tools, manual injection, feedback loops).
        """
        from .utils import extract_images_from_messages, get_image_save_path, decode_and_save_image

        images = extract_images_from_messages(messages)

        if images:
            indent = "  " * self.depth
            for img_idx, (img_data, desc) in enumerate(images):
                save_path = get_image_save_path(
                    self.session_id,
                    phase_name,
                    img_idx,
                    extension='png'  # Default, could extract from data URL mime type
                )

                # Check if already saved (avoid duplicates)
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

    def _execute_phase_internal(self, phase: PhaseConfig, input_data: dict, trace: TraceNode, initial_injection: dict = None) -> Any:
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
        
        console.print(f"\n{indent}[bold magenta]📍 Bearing (Phase): {phase.name}[/bold magenta]")
        console.print(f"{indent}[italic]{rendered_instructions[:100]}...[/italic]")

        log_message(self.session_id, "phase_start", phase.name,
                   trace_id=trace.id, parent_id=trace.parent_id, node_type="phase", depth=trace.depth)

        # Resolve tools (Tackle) - Check if Quartermaster needed
        tackle_list = phase.tackle
        if phase.tackle == "manifest":
            console.print(f"{indent}  [bold cyan]🗺️  Quartermaster charting tackle...[/bold cyan]")
            tackle_list = self._run_quartermaster(phase, input_data, trace)
            console.print(f"{indent}  [bold cyan]📋 Manifest: {', '.join(tackle_list)}[/bold cyan]")

        tools_schema = []
        tool_map = {}
        for t_name in tackle_list:
            t = get_tackle(t_name)
            if t:
                tool_map[t_name] = t
                tools_schema.append(get_tool_schema(t, name=t_name))
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
            tools_schema.append(get_tool_schema(route_to_tool)) # Manually pass tool object

        # Construct context from lineage
        # Since we are snowballing context_messages, we don't need to stringify previous outputs into the user message anymore.
        # This prevents duplicating history.
        user_content = f"## Input Data:\n{json.dumps(input_data or {})}"

        # Initialize Agent
        agent = Agent(
            model=self.model,
            system_prompt="", # We manage system prompts in context_messages
            tools=tools_schema,
            base_url=self.base_url,
            api_key=self.api_key
        )

        # Add initial messages to echo history
        sys_trace = trace.create_child("msg", "system_instructions")
        sys_msg = {"role": "system", "content": rendered_instructions}
        self.echo.add_history(sys_msg, trace_id=sys_trace.id, parent_id=trace.id, node_type="system")
        
        # Append to snowball context
        self.context_messages.append(sys_msg)
        
        user_trace = trace.create_child("msg", "user_input")
        user_msg = {"role": "user", "content": user_content}
        self.echo.add_history(user_msg, trace_id=user_trace.id, parent_id=trace.id, node_type="user")
        
        # Append to snowball context
        self.context_messages.append(user_msg)
        
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
                    # It needs the parent_trace object directly
                    spawn_cascade(ref_path, sub_input, parent_trace=trace)

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
                
                # Pass trace context AND HOOKS
                sub_result = run_cascade(ref_path, sub_input, f"{self.session_id}_sub", self.overrides, self.depth + 1, parent_trace=trace, hooks=self.hooks)
                
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

                try:
                    is_main_thread = threading.current_thread() is threading.main_thread()
                
                    if self.depth == 0 and is_main_thread:
                        with console.status(f"{indent}[bold green]Agent thinking...[/bold green] ", spinner="dots") as status: # Added status here
                            response_dict = agent.run(current_input, context_messages=self.context_messages)
                    else:
                        # For sub-cascades, no spinner to avoid Rich Live conflicts
                        console.print(f"{indent}[dim]Agent thinking (depth {self.depth})...[/dim]")
                        response_dict = agent.run(current_input, context_messages=self.context_messages)
                
                    content = response_dict.get("content")
                    tool_calls = response_dict.get("tool_calls")
                    request_id = response_dict.get("id")

                    log_message(self.session_id, "agent", str(content), 
                                trace_id=turn_trace.id, parent_id=turn_trace.parent_id, node_type="agent", depth=turn_trace.depth)
                
                    if request_id:
                        track_request(self.session_id, request_id, turn_trace.id, turn_trace.parent_id)
                
                    if content:
                        console.print(Panel(Markdown(content), title=f"Agent ({self.model})", border_style="green", expand=False))
                
                    # Update histories (Snowball)
                    if current_input:
                         self.context_messages.append({"role": "user", "content": current_input})
                
                    assistant_msg = {"role": "assistant", "content": content}
                    if tool_calls:
                        assistant_msg["tool_calls"] = tool_calls
                    self.context_messages.append(assistant_msg)

                    # Add to Echo (global history)
                    input_trace = turn_trace.create_child("msg", "user_input")
                    if current_input:
                         self.echo.add_history({"role": "user", "content": current_input}, trace_id=input_trace.id, parent_id=turn_trace.id, node_type="turn_input")
                
                    output_trace = turn_trace.create_child("msg", "agent_output")
                    self.echo.add_history(assistant_msg, trace_id=output_trace.id, parent_id=turn_trace.id, node_type="turn_output")
                    self._update_graph()
                
                    response_content = content
                
                    # Handle tool calls
                    if tool_calls:
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
                        
                            log_message(self.session_id, "tool_result", str(result), {"tool": func_name}, 
                                       trace_id=tool_trace.id, parent_id=tool_trace.parent_id, node_type="tool", depth=tool_trace.depth)
                        
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

                                for img_idx, img_path in enumerate(images):
                                    encoded_img = encode_image_base64(img_path)
                                    if not encoded_img.startswith("[Error"):
                                        content_block.append({
                                            "type": "image_url",
                                            "image_url": {"url": encoded_img}
                                        })
                                        valid_images += 1

                                        # Auto-save image to structured directory
                                        from .utils import get_image_save_path, decode_and_save_image
                                        save_path = get_image_save_path(
                                            self.session_id,
                                            phase.name,
                                            img_idx,
                                            extension=img_path.split('.')[-1] if '.' in img_path else 'png'
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

                            # Add standard tool result message
                            tool_msg = {"role": "tool", "tool_call_id": tc["id"], "content": str(result)}
                            self.context_messages.append(tool_msg)
                        
                            # Add to Echo
                            result_trace = tool_trace.create_child("msg", "tool_result")
                            self.echo.add_history(tool_msg, trace_id=result_trace.id, parent_id=tool_trace.id, node_type="tool_result")
                        
                            # Inject Image Message if present
                            if image_injection_message:
                                self.context_messages.append(image_injection_message)
                                img_trace = tool_trace.create_child("msg", "image_injection")
                                self.echo.add_history(image_injection_message, trace_id=img_trace.id, parent_id=tool_trace.id, node_type="injection")

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
                    
                        log_message(self.session_id, "agent", str(content), trace_id=turn_trace.id, parent_id=turn_trace.parent_id, node_type="follow_up", depth=turn_trace.depth)
                    
                        if request_id:
                            track_request(self.session_id, request_id, turn_trace.id, turn_trace.parent_id)

                        if content:
                            console.print(Panel(Markdown(content), title=f"Agent ({self.model})", border_style="green", expand=False))
                    
                        assistant_msg = {"role": "assistant", "content": content}
                        self.context_messages.append(assistant_msg)
                    
                        followup_trace = turn_trace.create_child("msg", "follow_up")
                        self.echo.add_history(assistant_msg, trace_id=followup_trace.id, parent_id=turn_trace.id, node_type="follow_up")
                        self._update_graph() # Update after follow up
                        response_content = content

                        # Auto-save any images from messages (catches manual injection, feedback loops, etc.)
                        self._save_images_from_messages(self.context_messages, phase.name)

                except Exception as e:
                    console.print(f"[bold red]Error in Agent call:[/bold red] {e}")
                    log_message(self.session_id, "error", str(e), trace_id=turn_trace.id, parent_id=turn_trace.parent_id, node_type="error")
                    self.echo.add_history({"role": "system", "content": f"Error: {str(e)}"}, trace_id=turn_trace.id, parent_id=turn_trace.parent_id, node_type="error")
                    self._update_graph()
                    break

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

                        console.print(f"{indent}  [dim]Running cascade validator: {validator_name}[/dim]")

                        try:
                            # Run the validator cascade
                            validator_result_echo = run_cascade(
                                cascade_path,
                                validator_input,
                                f"{self.session_id}_validator",
                                self.overrides,
                                self.depth + 1,
                                parent_trace=validation_trace,
                                hooks=self.hooks
                            )

                            # Extract the result - look in lineage for last phase output
                            if validator_result_echo.get("lineage"):
                                last_output = validator_result_echo["lineage"][-1].get("output", "")
                                # Try to parse as JSON
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
                            console.print(f"{indent}  [bold red]Validator Error:[/bold red] {str(e)}")
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
                if 'validator_result' in locals():
                    is_valid = validator_result.get("valid", False)
                    reason = validator_result.get("reason", "No reason provided")

                    # Log validation result
                    log_message(self.session_id, "validation", f"Valid: {is_valid}",
                               {"validator": validator_name, "reason": reason, "attempt": attempt + 1},
                               trace_id=validation_trace.id, parent_id=trace.id,
                               node_type="validation", depth=self.depth)

                    # Add to echo history for visualization
                    self.echo.add_history({
                        "role": "validation",
                        "content": f"{'✓' if is_valid else '✗'} {validator_name}: {reason[:100]}",
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
                        console.print(f"{indent}  [bold green]✓ Validation Passed:[/bold green] {reason}")
                        validation_passed = True
                        break  # Exit attempt loop
                    else:
                        console.print(f"{indent}  [bold red]✗ Validation Failed:[/bold red] {reason}")
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

            # No validation/ward failures, exit retry loop
            if not phase.rules.loop_until and not (phase.wards and phase.wards.post):
                # No validation required, exit after first attempt
                validation_passed = True
            break  # Exit retry loop

        # Auto-save any images from final phase context (catches all images before phase completion)
        self._save_images_from_messages(self.context_messages, phase.name)

        return chosen_next_phase if chosen_next_phase else response_content

def run_cascade(config_path: str | dict, input_data: dict = None, session_id: str = "default", overrides: dict = None, 
                depth: int = 0, parent_trace: TraceNode = None, hooks: WindlassHooks = None) -> dict:
    runner = WindlassRunner(config_path, session_id, overrides, depth, parent_trace, hooks)
    result = runner.run(input_data)
    
    if depth == 0:
        # Only print tree at the end of the root
        graph_dir = get_config().graph_dir
        graph_path = generate_mermaid(runner.echo, os.path.join(graph_dir, f"{session_id}.mmd"))
        console.print(f"\n[bold cyan]📊 Execution Graph saved to:[/bold cyan] {graph_path}")
        
    return result
