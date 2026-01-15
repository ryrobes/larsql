"""
Practical integration example showing how to add echo logging to runner.py.

This file demonstrates the key integration points with before/after code.
Copy these patterns into runner.py incrementally.
"""

# ============================================================================
# IMPORTS TO ADD
# ============================================================================

# Add these imports to runner.py:
from .echoes import log_echo, flush_echoes, close_echoes
from .echo_enrichment import (
    TimingContext,
    extract_usage_from_litellm,
    extract_request_id,
    detect_base64_in_content,
    extract_image_paths_from_tool_result,
    enrich_echo_with_llm_response,
)


# ============================================================================
# EXAMPLE 1: Agent Call with Timing & Usage Tracking
# ============================================================================

def example_agent_call_integration():
    """
    Shows how to wrap agent.run() with timing and log to echoes.

    Location in runner.py: Wherever agent.run() is called (multiple places)
    """

    # BEFORE (existing code):
    # ----------------------
    response = agent.run(prompt, context_messages)
    msg_dict = {
        "role": response.get("role", "assistant"),
        "content": response.get("content", ""),
    }
    echo.add_history(msg_dict, trace_id=turn_trace.id, parent_id=cell_trace.id)


    # AFTER (with echo logging):
    # -------------------------

    # 1. Wrap with timing
    with TimingContext() as timer:
        response = agent.run(prompt, context_messages)

    # 2. Extract message
    msg_dict = {
        "role": response.get("role", "assistant"),
        "content": response.get("content", ""),
        "tool_calls": response.get("tool_calls"),  # Include tool calls
    }

    # 3. Extract usage (if agent.py is modified to include usage)
    usage = response.get("usage", {})
    tokens_in = usage.get("prompt_tokens")
    tokens_out = usage.get("completion_tokens")
    request_id = response.get("id")

    # 4. Existing logging (keep as-is)
    echo.add_history(msg_dict, trace_id=turn_trace.id, parent_id=cell_trace.id, node_type="agent")
    log_message(session_id, "agent", msg_dict["content"], {}, turn_trace.id, cell_trace.id, "agent")

    # 5. NEW: Comprehensive echo logging
    log_echo(
        session_id=session_id,
        trace_id=turn_trace.id,
        parent_id=cell_trace.id,
        node_type="agent",
        role="assistant",
        depth=depth,
        cell_name=cell.name,
        cascade_id=cascade_config.cascade_id,
        cascade_file=config_path if isinstance(config_path, str) else None,
        duration_ms=timer.get_duration_ms(),
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        request_id=request_id,
        content=msg_dict["content"],
        tool_calls=msg_dict.get("tool_calls"),
        metadata={
            "model": agent.model,
            "turn_index": turn_idx,
            "max_turns": max_turns,
        }
    )


# ============================================================================
# EXAMPLE 2: Tool Execution with Image Handling
# ============================================================================

def example_tool_execution_integration():
    """
    Shows how to log tool execution with timing and image linking.

    Location in runner.py: Around line 1796 (tool execution)
    """

    # BEFORE (existing code):
    # ----------------------
    result = tool_eddy.run(**validated_args)

    tool_result_msg = {
        "role": "tool",
        "tool_call_id": tc["id"],
        "content": str(result)
    }
    echo.add_history(tool_result_msg, trace_id=tool_trace.id, parent_id=turn_trace.id)
    log_message(session_id, "tool", str(result), {"tool": tool_name}, tool_trace.id, turn_trace.id, "tool_result")


    # AFTER (with echo logging):
    # -------------------------

    # 1. Wrap with timing
    with TimingContext() as timer:
        result = tool_eddy.run(**validated_args)

    # 2. Extract images if tool returned them
    image_paths = extract_image_paths_from_tool_result(result)

    # 3. Build tool result message (existing)
    tool_result_msg = {
        "role": "tool",
        "tool_call_id": tc["id"],
        "content": str(result)
    }

    # 4. Existing logging (keep as-is)
    echo.add_history(tool_result_msg, trace_id=tool_trace.id, parent_id=turn_trace.id, node_type="tool_result")
    log_message(session_id, "tool", str(result), {"tool": tool_name}, tool_trace.id, turn_trace.id, "tool_result")

    # 5. NEW: Comprehensive echo logging
    log_echo(
        session_id=session_id,
        trace_id=tool_trace.id,
        parent_id=turn_trace.id,
        node_type="tool_result",
        role="tool",
        depth=depth,
        cell_name=cell.name,
        cascade_id=cascade_config.cascade_id,
        duration_ms=timer.get_duration_ms(),
        content=result,  # Full result (dict/str/etc - not stringified!)
        metadata={
            "tool_name": tool_name,
            "tool_call_id": tc["id"],
            "arguments": validated_args,  # Full arguments preserved
        },
        images=image_paths,  # Link to filesystem images
    )


# ============================================================================
# EXAMPLE 3: Image Injection with Base64 Detection
# ============================================================================

def example_image_injection_integration():
    """
    Shows how to log image injection with base64 detection.

    Location in runner.py: After image encoding/injection
    """

    # BEFORE (existing code):
    # ----------------------
    # Image is encoded and injected
    img_data_url = encode_image_base64(image_path)
    injection_msg = {
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": img_data_url}}
        ]
    }
    echo.add_history(injection_msg, trace_id=injection_trace.id, parent_id=cell_trace.id, node_type="injection")


    # AFTER (with echo logging):
    # -------------------------

    # 1. Encode image (existing)
    img_data_url = encode_image_base64(image_path)

    # 2. Build injection message (existing)
    injection_msg = {
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": img_data_url}}
        ]
    }

    # 3. Existing logging (keep as-is)
    echo.add_history(injection_msg, trace_id=injection_trace.id, parent_id=cell_trace.id, node_type="injection")

    # 4. NEW: Comprehensive echo logging
    log_echo(
        session_id=session_id,
        trace_id=injection_trace.id,
        parent_id=cell_trace.id,
        node_type="image_injection",
        role="user",
        depth=depth,
        cell_name=cell.name,
        content=injection_msg["content"],  # Full multi-modal content
        has_base64=detect_base64_in_content(injection_msg["content"]),  # Auto-detect base64
        images=[image_path] if isinstance(image_path, str) else image_path,  # Link to original
    )


# ============================================================================
# EXAMPLE 4: Takes with Index Tracking
# ============================================================================

def example_takes_integration():
    """
    Shows how to log takes with index tracking.

    Location in runner.py: Around line 885 (cell takes)
    """

    # BEFORE (existing code):
    # ----------------------
    for i in range(factor):
        # Run take attempt
        output = self._run_cell_logic(...)

        log_message(session_id, "take_complete", f"Take {i+1} completed",
                   {"attempt": i}, take_trace.id, takes_trace.id, "take",
                   take_index=i, is_winner=False)


    # AFTER (with echo logging):
    # -------------------------

    for i in range(factor):
        # Run take attempt with timing
        with TimingContext() as timer:
            output = self._run_cell_logic(...)

        # Existing logging (keep as-is)
        log_message(session_id, "take_complete", f"Take {i+1} completed",
                   {"attempt": i}, take_trace.id, takes_trace.id, "take",
                   take_index=i, is_winner=False)

        # NEW: Comprehensive echo logging
        log_echo(
            session_id=take_session_id,  # Sub-session ID
            trace_id=take_trace.id,
            parent_id=takes_trace.id,
            node_type="take_attempt",
            role="take",
            depth=depth,
            take_index=i,  # Track which attempt
            is_winner=False,   # Updated later when winner selected
            cell_name=cell.name,
            cascade_id=cascade_config.cascade_id,
            duration_ms=timer.get_duration_ms(),
            content=output,  # Full take output
            metadata={
                "attempt": i,
                "factor": factor,
                "take_session_id": take_session_id,
            }
        )

    # After evaluation, mark winner
    winner_index = 2  # Example
    log_echo(
        session_id=session_id,
        trace_id=winner_trace.id,
        take_index=winner_index,
        is_winner=True,  # Mark as winner
        content=f"Winner: Take #{winner_index + 1}",
        metadata={"evaluation_reasoning": eval_content}
    )


# ============================================================================
# EXAMPLE 5: Cell Lifecycle Events
# ============================================================================

def example_cell_lifecycle_integration():
    """
    Shows how to log cell start/end events.

    Location in runner.py: Around line 1470 (cell start), end of cell execution
    """

    # BEFORE (existing code):
    # ----------------------
    log_message(session_id, "system", f"Cell {cell.name} starting", {},
               cell_trace.id, cascade_trace.id, "cell", depth)

    # ... cell execution ...

    log_message(session_id, "system", f"Cell {cell.name} complete", {},
               cell_trace.id, cascade_trace.id, "cell", depth)


    # AFTER (with echo logging):
    # -------------------------

    # Cell start
    cell_start_time = time.time()

    log_message(session_id, "system", f"Cell {cell.name} starting", {},
               cell_trace.id, cascade_trace.id, "cell", depth)

    # NEW: Echo logging for cell start
    log_echo(
        session_id=session_id,
        trace_id=cell_trace.id,
        parent_id=cascade_trace.id,
        node_type="cell_start",
        role="system",
        depth=depth,
        cell_name=cell.name,
        cascade_id=cascade_config.cascade_id,
        content=f"Starting cell: {cell.name}",
        metadata={
            "instructions": rendered_instruction,
            "skills": cell.skills,
            "max_turns": cell.rules.max_turns if cell.rules else None,
        }
    )

    # ... cell execution ...

    # Cell end
    cell_duration_ms = (time.time() - cell_start_time) * 1000

    log_message(session_id, "system", f"Cell {cell.name} complete", {},
               cell_trace.id, cascade_trace.id, "cell", depth)

    # NEW: Echo logging for cell complete
    log_echo(
        session_id=session_id,
        trace_id=cell_trace.id,
        parent_id=cascade_trace.id,
        node_type="cell_complete",
        role="system",
        depth=depth,
        cell_name=cell.name,
        cascade_id=cascade_config.cascade_id,
        duration_ms=cell_duration_ms,  # Total cell duration
        content=final_output,  # Cell output
        metadata={
            "total_turns": total_turns,
            "handoff_target": handoff_target if handoff else None,
        }
    )


# ============================================================================
# EXAMPLE 6: Cascade Cleanup (Important!)
# ============================================================================

def example_cascade_cleanup_integration():
    """
    Shows how to ensure echo buffers are flushed at cascade end.

    Location in runner.py: In run() method, at the end
    """

    # Add to the end of run() method, in finally block:

    try:
        # ... cascade execution ...
        return result

    finally:
        # Existing cleanup
        # ... (if any) ...

        # NEW: Flush echo buffers to ensure all data is written
        flush_echoes()

        # Optional: Close echo files if this is the top-level cascade
        if depth == 0:
            close_echoes()


# ============================================================================
# TESTING THE INTEGRATION
# ============================================================================

def test_echo_logging():
    """
    Simple test to verify echo logging is working.

    Run this after adding integration to runner.py:
    """

    from rvbbit import run_cascade
    from rvbbit.echoes import query_echoes_jsonl, query_echoes_parquet

    # Run a simple cascade
    result = run_cascade(
        "examples/simple_flow.json",
        {"data": "test"},
        session_id="test_echo_001"
    )

    # Check JSONL file was created
    entries = query_echoes_jsonl("test_echo_001")
    print(f"✓ JSONL entries: {len(entries)}")

    for entry in entries:
        print(f"  - {entry['node_type']}: {entry.get('cell_name', 'N/A')}")
        if entry.get('duration_ms'):
            print(f"    Duration: {entry['duration_ms']:.2f}ms")
        if entry.get('tokens_in'):
            print(f"    Tokens: {entry['tokens_in']} in, {entry['tokens_out']} out")

    # Check Parquet data
    df = query_echoes_parquet("session_id = 'test_echo_001'")
    print(f"\n✓ Parquet entries: {len(df)}")
    print(f"  Columns: {list(df.columns)}")

    # Check for timing data
    timed_entries = df[df['duration_ms'].notna()]
    print(f"  Entries with timing: {len(timed_entries)}")

    # Check for token data
    token_entries = df[df['tokens_in'].notna()]
    print(f"  Entries with tokens: {len(token_entries)}")

    print("\n✓ Echo logging working!")


if __name__ == "__main__":
    print(__doc__)
    print("\nThis is an example file - copy patterns into runner.py incrementally.")
    print("See ECHO_INTEGRATION.md for complete guide.")
