#!/usr/bin/env python3
"""
Test script to compare flowchart vs state diagram output.

Creates mock Echo data representing realistic cascade executions.
"""
import sys
import os
import uuid

# Add windlass to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'windlass'))

from windlass.visualizer import generate_mermaid_string, generate_state_diagram_string
from windlass.echo import Echo


def create_soundings_echo() -> Echo:
    """Create Echo with soundings data (like ui_run_7c40bd5822a5)."""
    echo = Echo(session_id="test_soundings")

    # Lineage showing completed phases
    echo.lineage = [
        {"phase": "generate_solution", "trace_id": "phase1", "output": "Solution generated"},
        {"phase": "test_solution", "trace_id": "phase2", "output": "Tests passed"}
    ]

    # History with soundings
    echo.history = [
        # Cascade start
        {
            "trace_id": "cascade1",
            "node_type": "cascade",
            "content": "Cascade: code_solver",
            "role": "system",
            "metadata": {"cascade_id": "code_solver"}
        },
        # Phase 1 with soundings
        {
            "trace_id": "phase1",
            "parent_id": "cascade1",
            "node_type": "phase",
            "content": "Phase: generate_solution",
            "role": "system",
            "metadata": {
                "phase_name": "generate_solution",
                "has_soundings": True
            }
        },
        # Sounding attempts
        {
            "trace_id": "sa0",
            "parent_id": "phase1",
            "node_type": "sounding_attempt",
            "content": "Let's break down how to solve this...",
            "role": "assistant",
            "metadata": {
                "phase_name": "generate_solution",
                "sounding_index": 0,
                "is_winner": True
            }
        },
        {
            "trace_id": "sa1",
            "parent_id": "phase1",
            "node_type": "sounding_attempt",
            "content": "Let's dive into this challenge...",
            "role": "assistant",
            "metadata": {
                "phase_name": "generate_solution",
                "sounding_index": 1,
                "is_winner": False
            }
        },
        {
            "trace_id": "sa2",
            "parent_id": "phase1",
            "node_type": "sounding_attempt",
            "content": "You're asking to solve...",
            "role": "assistant",
            "metadata": {
                "phase_name": "generate_solution",
                "sounding_index": 2,
                "is_winner": False
            }
        },
        # Evaluator
        {
            "trace_id": "eval1",
            "parent_id": "phase1",
            "node_type": "evaluator",
            "content": "Attempt 1 correctly identified...",
            "role": "assistant",
            "metadata": {
                "phase_name": "generate_solution"
            }
        },
        # Phase 2 simple
        {
            "trace_id": "phase2",
            "parent_id": "cascade1",
            "node_type": "phase",
            "content": "Phase: test_solution",
            "role": "system",
            "metadata": {
                "phase_name": "test_solution"
            }
        },
        # Validation
        {
            "trace_id": "val1",
            "parent_id": "phase2",
            "node_type": "validation",
            "content": "Schema validation passed",
            "role": "system",
            "metadata": {
                "phase_name": "test_solution",
                "valid": True,
                "validator": "code_validator"
            }
        }
    ]

    return echo


def create_reforge_echo() -> Echo:
    """Create Echo with soundings + reforge (like ui_run_9291b8340a8d)."""
    echo = Echo(session_id="test_reforge")

    echo.lineage = [
        {"phase": "create_and_refine_chart", "trace_id": "phase1", "output": "Chart created"},
        {"phase": "finalize", "trace_id": "phase2", "output": "Done"}
    ]

    echo.history = [
        # Cascade
        {
            "trace_id": "cascade1",
            "node_type": "cascade",
            "content": "Cascade: chart_refinement",
            "role": "system"
        },
        # Phase 1 with soundings
        {
            "trace_id": "phase1",
            "parent_id": "cascade1",
            "node_type": "phase",
            "content": "Phase: create_and_refine_chart",
            "role": "system",
            "metadata": {"phase_name": "create_and_refine_chart", "has_soundings": True}
        },
        # 3 sounding attempts
        {
            "trace_id": "sa0",
            "parent_id": "phase1",
            "node_type": "sounding_attempt",
            "content": "I'll create a chart with...",
            "metadata": {"phase_name": "create_and_refine_chart", "sounding_index": 0, "is_winner": False}
        },
        {
            "trace_id": "sa1",
            "parent_id": "phase1",
            "node_type": "sounding_attempt",
            "content": "I'll create the bar chart...",
            "metadata": {"phase_name": "create_and_refine_chart", "sounding_index": 1, "is_winner": True}
        },
        {
            "trace_id": "sa2",
            "parent_id": "phase1",
            "node_type": "sounding_attempt",
            "content": "I'll create the chart for...",
            "metadata": {"phase_name": "create_and_refine_chart", "sounding_index": 2, "is_winner": False}
        },
        # Evaluator
        {
            "trace_id": "eval1",
            "parent_id": "phase1",
            "node_type": "evaluator",
            "content": "Attempt 2 is the best...",
            "metadata": {"phase_name": "create_and_refine_chart"}
        },
        # Reforge step 1
        {
            "trace_id": "rf1",
            "parent_id": "phase1",
            "node_type": "reforge_step",
            "content": "Reforge step 1",
            "metadata": {"phase_name": "create_and_refine_chart", "reforge_step": 1}
        },
        {
            "trace_id": "rf1a0",
            "parent_id": "rf1",
            "node_type": "reforge_attempt",
            "content": "I'll take a contrarian...",
            "metadata": {"phase_name": "create_and_refine_chart", "reforge_step": 1, "attempt_index": 0}
        },
        {
            "trace_id": "rf1a1",
            "parent_id": "rf1",
            "node_type": "reforge_attempt",
            "content": "I'll take a contrarian approach...",
            "metadata": {"phase_name": "create_and_refine_chart", "reforge_step": 1, "attempt_index": 1}
        },
        {
            "trace_id": "rf1w",
            "parent_id": "rf1",
            "node_type": "reforge_winner",
            "content": "Winner: R2",
            "metadata": {"phase_name": "create_and_refine_chart", "reforge_step": 1, "winner_index": 1}
        },
        # Reforge step 2
        {
            "trace_id": "rf2",
            "parent_id": "phase1",
            "node_type": "reforge_step",
            "content": "Reforge step 2",
            "metadata": {"phase_name": "create_and_refine_chart", "reforge_step": 2}
        },
        {
            "trace_id": "rf2a0",
            "parent_id": "rf2",
            "node_type": "reforge_attempt",
            "content": "I'll create the chart with...",
            "metadata": {"phase_name": "create_and_refine_chart", "reforge_step": 2, "attempt_index": 0}
        },
        {
            "trace_id": "rf2a1",
            "parent_id": "rf2",
            "node_type": "reforge_attempt",
            "content": "I'll create the chart refined...",
            "metadata": {"phase_name": "create_and_refine_chart", "reforge_step": 2, "attempt_index": 1}
        },
        {
            "trace_id": "rf2w",
            "parent_id": "rf2",
            "node_type": "reforge_winner",
            "content": "Winner: R2",
            "metadata": {"phase_name": "create_and_refine_chart", "reforge_step": 2, "winner_index": 1}
        },
        # Phase 2 simple
        {
            "trace_id": "phase2",
            "parent_id": "cascade1",
            "node_type": "phase",
            "content": "Phase: finalize",
            "role": "system",
            "metadata": {"phase_name": "finalize"}
        }
    ]

    return echo


def create_subcascade_echo() -> Echo:
    """Create Echo with sub-cascade (like ui_run_ab023cdd8137)."""
    echo = Echo(session_id="test_subcascade")

    echo.lineage = [
        {"phase": "parent_start", "trace_id": "phase1", "output": "Started"},
        {"phase": "call_child", "trace_id": "phase2", "output": "Child done"},
        {"phase": "parent_finish", "trace_id": "phase3", "output": "Finished"}
    ]

    # Main cascade history
    echo.history = [
        {"trace_id": "cascade1", "node_type": "cascade", "content": "Cascade: parent_workflow"},
        {"trace_id": "phase1", "parent_id": "cascade1", "node_type": "phase",
         "content": "Phase: parent_start", "metadata": {"phase_name": "parent_start"}},
        {"trace_id": "phase2", "parent_id": "cascade1", "node_type": "phase",
         "content": "Phase: call_child", "metadata": {"phase_name": "call_child", "has_sub_cascades": True}},
        {"trace_id": "phase3", "parent_id": "cascade1", "node_type": "phase",
         "content": "Phase: parent_finish", "metadata": {"phase_name": "parent_finish"}},
        # Merged sub-cascade (this is how echo.merge() stores sub-cascade data)
        {
            "sub_echo": "sub_cascade_greeter",
            "history": [
                {"trace_id": "sub_cascade1", "node_type": "cascade",
                 "content": "Cascade: sub_cascade_greeter"},
                {"trace_id": "sub_phase1", "parent_id": "sub_cascade1", "node_type": "phase",
                 "content": "Phase: sub_greet", "metadata": {"phase_name": "sub_greet"}},
                {"trace_id": "sub_phase2", "parent_id": "sub_cascade1", "node_type": "phase",
                 "content": "Phase: sub_respond", "metadata": {"phase_name": "sub_respond"}},
            ]
        }
    ]

    return echo


def create_complex_echo() -> Echo:
    """Create Echo with multiple complexity types combined."""
    echo = Echo(session_id="test_complex")

    echo.lineage = [
        {"phase": "intake", "trace_id": "phase1", "output": "Validated"},
        {"phase": "generate", "trace_id": "phase2", "output": "Generated with soundings"},
        {"phase": "delegate", "trace_id": "phase3", "output": "Delegated to sub-cascade"},
        {"phase": "finalize", "trace_id": "phase4", "output": "Done"}
    ]

    echo.history = [
        # Cascade
        {"trace_id": "cascade1", "node_type": "cascade", "content": "Cascade: complex_workflow"},

        # Phase 1: Simple with pre-ward
        {"trace_id": "phase1", "parent_id": "cascade1", "node_type": "phase",
         "content": "Phase: intake", "metadata": {"phase_name": "intake", "has_wards": True}},
        {"trace_id": "pre1", "parent_id": "phase1", "node_type": "pre_ward",
         "content": "Input validation", "metadata": {"ward_type": "pre", "validator": "input_check", "valid": True, "mode": "blocking"}},

        # Phase 2: Soundings + Reforge
        {"trace_id": "phase2", "parent_id": "cascade1", "node_type": "phase",
         "content": "Phase: generate", "metadata": {"phase_name": "generate", "has_soundings": True}},
        # Soundings
        {"trace_id": "sa0", "parent_id": "phase2", "node_type": "sounding_attempt",
         "content": "Approach A", "metadata": {"phase_name": "generate", "sounding_index": 0, "is_winner": False}},
        {"trace_id": "sa1", "parent_id": "phase2", "node_type": "sounding_attempt",
         "content": "Approach B", "metadata": {"phase_name": "generate", "sounding_index": 1, "is_winner": True}},
        {"trace_id": "sa2", "parent_id": "phase2", "node_type": "sounding_attempt",
         "content": "Approach C", "metadata": {"phase_name": "generate", "sounding_index": 2, "is_winner": False}},
        # Reforge
        {"trace_id": "rf1", "parent_id": "phase2", "node_type": "reforge_step",
         "content": "Reforge 1", "metadata": {"phase_name": "generate", "reforge_step": 1}},
        {"trace_id": "rf1a0", "parent_id": "rf1", "node_type": "reforge_attempt",
         "content": "Refinement A", "metadata": {"phase_name": "generate", "reforge_step": 1, "attempt_index": 0}},
        {"trace_id": "rf1a1", "parent_id": "rf1", "node_type": "reforge_attempt",
         "content": "Refinement B", "metadata": {"phase_name": "generate", "reforge_step": 1, "attempt_index": 1}},
        {"trace_id": "rf1w", "parent_id": "rf1", "node_type": "reforge_winner",
         "content": "Winner", "metadata": {"phase_name": "generate", "reforge_step": 1, "winner_index": 1}},

        # Phase 3: Sub-cascade
        {"trace_id": "phase3", "parent_id": "cascade1", "node_type": "phase",
         "content": "Phase: delegate", "metadata": {"phase_name": "delegate", "has_sub_cascades": True}},

        # Phase 4: Simple with post-ward
        {"trace_id": "phase4", "parent_id": "cascade1", "node_type": "phase",
         "content": "Phase: finalize", "metadata": {"phase_name": "finalize", "has_wards": True}},
        {"trace_id": "post1", "parent_id": "phase4", "node_type": "post_ward",
         "content": "Output validation", "metadata": {"ward_type": "post", "validator": "quality_check", "valid": True, "mode": "retry"}},

        # Merged sub-cascade for delegate phase
        {
            "sub_echo": "worker_cascade",
            "history": [
                {"trace_id": "worker_cascade", "node_type": "cascade",
                 "content": "Cascade: worker"},
                {"trace_id": "worker_p1", "parent_id": "worker_cascade", "node_type": "phase",
                 "content": "Phase: work_init", "metadata": {"phase_name": "work_init"}},
                {"trace_id": "worker_p2", "parent_id": "worker_cascade", "node_type": "phase",
                 "content": "Phase: work_execute", "metadata": {"phase_name": "work_execute"}},
                {"trace_id": "worker_p3", "parent_id": "worker_cascade", "node_type": "phase",
                 "content": "Phase: work_complete", "metadata": {"phase_name": "work_complete"}},
            ]
        }
    ]

    return echo


def create_wards_echo() -> Echo:
    """Create Echo with wards validation."""
    echo = Echo(session_id="test_wards")

    echo.lineage = [
        {"phase": "generate", "trace_id": "phase1", "output": "Generated"},
        {"phase": "validate", "trace_id": "phase2", "output": "Validated"}
    ]

    echo.history = [
        {"trace_id": "cascade1", "node_type": "cascade", "content": "Cascade: validated_flow"},
        {"trace_id": "phase1", "parent_id": "cascade1", "node_type": "phase",
         "content": "Phase: generate", "metadata": {"phase_name": "generate", "has_wards": True}},
        # Pre-ward
        {"trace_id": "pre1", "parent_id": "phase1", "node_type": "pre_ward",
         "content": "Input check", "metadata": {"ward_type": "pre", "validator": "input_sanitizer", "valid": True, "mode": "blocking"}},
        # Post-ward
        {"trace_id": "post1", "parent_id": "phase1", "node_type": "post_ward",
         "content": "Grammar check", "metadata": {"ward_type": "post", "validator": "grammar_check", "valid": True, "mode": "retry"}},
        {"trace_id": "post2", "parent_id": "phase1", "node_type": "post_ward",
         "content": "Safety check", "metadata": {"ward_type": "post", "validator": "content_safety", "valid": True, "mode": "blocking"}},
        # Phase 2
        {"trace_id": "phase2", "parent_id": "cascade1", "node_type": "phase",
         "content": "Phase: validate", "metadata": {"phase_name": "validate"}}
    ]

    return echo


def compare_diagrams(echo: Echo, name: str):
    """Generate and compare both diagram types."""
    print(f"\n{'='*70}")
    print(f"Test: {name}")
    print('='*70)

    # Generate flowchart
    flowchart = generate_mermaid_string(echo)
    flowchart_lines = len(flowchart.split('\n'))

    # Generate state diagram
    state_diagram = generate_state_diagram_string(echo)
    state_lines = len(state_diagram.split('\n'))

    reduction = 100 - (state_lines * 100 // flowchart_lines) if flowchart_lines > 0 else 0

    print(f"\nFlowchart: {flowchart_lines} lines")
    print(f"State Diagram: {state_lines} lines")
    print(f"Reduction: {reduction}%")

    # Save both
    flowchart_path = f"/tmp/{name}_flowchart.mmd"
    with open(flowchart_path, 'w') as f:
        f.write(flowchart)

    state_path = f"/tmp/{name}_statediagram.mmd"
    with open(state_path, 'w') as f:
        f.write(state_diagram)

    print(f"\nSaved: {flowchart_path}")
    print(f"Saved: {state_path}")

    # Print state diagram
    print(f"\n--- State Diagram ---")
    print(state_diagram)

    return flowchart_lines, state_lines


def main():
    print("State Diagram vs Flowchart Comparison")
    print("="*70)

    test_cases = [
        (create_soundings_echo(), "soundings_only"),
        (create_reforge_echo(), "soundings_with_reforge"),
        (create_subcascade_echo(), "subcascade"),
        (create_wards_echo(), "wards"),
        (create_complex_echo(), "complex_all_features"),
    ]

    total_flow = 0
    total_state = 0

    for echo, name in test_cases:
        flow, state = compare_diagrams(echo, name)
        total_flow += flow
        total_state += state

    print(f"\n{'='*70}")
    print(f"SUMMARY")
    print(f"{'='*70}")
    print(f"Total Flowchart lines: {total_flow}")
    print(f"Total State Diagram lines: {total_state}")
    if total_flow > 0:
        print(f"Overall reduction: {100 - (total_state * 100 // total_flow)}%")


if __name__ == "__main__":
    main()
