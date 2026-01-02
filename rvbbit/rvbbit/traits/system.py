from .base import simple_eddy
import threading
import time
import uuid
from typing import Optional, List, Dict, Any, Union
from ..tracing import get_current_trace, TraceNode
from ..config import get_config
from .state_tools import get_current_session_id
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

@simple_eddy
def spawn_cascade(cascade_ref: str, input_data: dict = None, parent_trace: Optional[TraceNode] = None, parent_session_id: str = None, candidate_index: int = None) -> str:
    """
    Spawns a cascade in the background (fire-and-forget).
    Returns the new session ID immediately.

    Args:
        cascade_ref: The path to the cascade JSON file.
        input_data: Optional dictionary of input data for the spawned cascade.
        parent_trace: The TraceNode of the calling cascade for lineage.
        parent_session_id: The session_id of the parent cascade.
        candidate_index: The candidate index if spawned from within a candidate.
    """
    # Get parent session ID from context if not explicitly provided
    if not parent_session_id:
        parent_session_id = get_current_session_id()
        if parent_session_id:
            print(f"[spawn_cascade] Using current session context: {parent_session_id}")

    # Resolve path relative to RVBBIT_ROOT (not cwd, which may be the studio backend)
    cfg = get_config()
    resolved_cascade_ref = None

    # If it's an absolute path, use it directly
    if os.path.isabs(cascade_ref):
        resolved_cascade_ref = cascade_ref
    else:
        # Smart search for the cascade file
        # Build list of candidate paths to check
        candidates = []

        # 1. Direct path relative to RVBBIT_ROOT
        candidates.append(os.path.join(cfg.root_dir, cascade_ref))

        # 2. With common extensions
        for ext in ['.yaml', '.yml', '.json']:
            candidates.append(os.path.join(cfg.root_dir, cascade_ref + ext))

        # 3. In cascades directory
        candidates.append(os.path.join(cfg.root_dir, 'cascades', cascade_ref))
        for ext in ['.yaml', '.yml', '.json']:
            candidates.append(os.path.join(cfg.root_dir, 'cascades', cascade_ref + ext))

        # 4. In calliope subdirectories - PRIORITIZE current session's directory
        # This ensures we find the cascade being built in the current session, not an older one
        calliope_dir = os.path.join(cfg.root_dir, 'cascades', 'calliope')
        if os.path.exists(calliope_dir):
            try:
                # First, check the parent session's calliope directory (if we're spawned from Calliope)
                if parent_session_id:
                    parent_calliope_dir = os.path.join(calliope_dir, parent_session_id)
                    if os.path.isdir(parent_calliope_dir):
                        for ext in ['', '.yaml', '.yml', '.json']:
                            candidates.append(os.path.join(parent_calliope_dir, cascade_ref + ext))
                        print(f"[spawn_cascade] Prioritizing parent session directory: {parent_calliope_dir}")

                # Then search all session directories, sorted by modification time (newest first)
                session_dirs = []
                for d in os.listdir(calliope_dir):
                    dir_path = os.path.join(calliope_dir, d)
                    if os.path.isdir(dir_path):
                        # Skip the parent session dir (already added above)
                        if parent_session_id and d == parent_session_id:
                            continue
                        session_dirs.append((dir_path, os.path.getmtime(dir_path)))
                session_dirs.sort(key=lambda x: x[1], reverse=True)  # Newest first

                for dir_path, _ in session_dirs:
                    # Try the cascade name in this session directory
                    for ext in ['', '.yaml', '.yml', '.json']:
                        candidates.append(os.path.join(dir_path, cascade_ref + ext))
            except Exception as e:
                print(f"[spawn_cascade] Error scanning calliope dirs: {e}")

        # 5. In traits directory
        candidates.append(os.path.join(cfg.root_dir, 'traits', cascade_ref))
        for ext in ['.yaml', '.yml', '.json']:
            candidates.append(os.path.join(cfg.root_dir, 'traits', cascade_ref + ext))

        # Find first existing file
        for candidate in candidates:
            if os.path.exists(candidate) and os.path.isfile(candidate):
                resolved_cascade_ref = candidate
                print(f"[spawn_cascade] Found cascade at: {resolved_cascade_ref}")
                break

        if not resolved_cascade_ref:
            # Fall back to the basic resolution
            resolved_cascade_ref = os.path.join(cfg.root_dir, cascade_ref)
            print(f"[spawn_cascade] WARNING: Could not find cascade '{cascade_ref}'")
            print(f"[spawn_cascade] Searched {len(candidates)} locations")

    # Debug: Log what we're about to spawn and verify file contents
    if os.path.exists(resolved_cascade_ref):
        try:
            import yaml
            with open(resolved_cascade_ref, 'r') as f:
                content = yaml.safe_load(f)
            cell_count = len(content.get('cells', [])) if content else 0
            print(f"[spawn_cascade] Loading {resolved_cascade_ref}")
            print(f"[spawn_cascade] Found {cell_count} cells in file")
            if cell_count > 0:
                print(f"[spawn_cascade] Cell names: {[c.get('name') for c in content.get('cells', [])]}")
        except Exception as e:
            print(f"[spawn_cascade] Failed to read cascade file: {e}")
    else:
        print(f"[spawn_cascade] WARNING: File does not exist: {resolved_cascade_ref}")

    # Generate unique session ID (include candidate index if provided)
    if candidate_index is not None:
        session_id = f"spawned_{int(time.time())}_{uuid.uuid4().hex[:6]}_candidate_{candidate_index}"
    else:
        session_id = f"spawned_{int(time.time())}_{uuid.uuid4().hex[:6]}"

    # Capture caller context from parent thread
    import contextvars
    ctx = contextvars.copy_context()

    def worker():
        # Import locally to avoid circular dependency
        from ..runner import run_cascade

        # Run in separate thread (context is preserved via ctx.run)
        try:
            # We use a new runner instance, passing the parent trace AND parent_session_id AND candidate_index
            run_cascade(resolved_cascade_ref, input_data or {}, session_id=session_id, parent_trace=parent_trace, parent_session_id=parent_session_id, candidate_index=candidate_index)
        except Exception as e:
            print(f"[Spawn Error] {e}")

    # Run worker in copied context so caller_id propagates
    t = threading.Thread(target=lambda: ctx.run(worker), daemon=True)
    t.start()

    return f"Spawned cascade '{cascade_ref}' with Session ID: {session_id}"


@simple_eddy
def map_cascade(
    cascade: str,
    map_over: Union[List[Any], str],
    input_key: str = "item",
    mode: str = "aggregate",
    max_parallel: Union[int, str] = 5,
    on_error: str = "continue",
    timeout: Optional[Union[int, str]] = None
) -> Dict[str, Any]:
    """
    Map a cascade over an array of items, spawning one cascade execution per item.

    This is the declarative equivalent of Airflow's dynamic task mapping.
    Each item in map_over triggers a separate cascade execution with that item
    injected as input.

    Args:
        cascade: Path to cascade file (JSON/YAML). Can be relative or absolute.
        map_over: Array of items to map over. Each item spawns one cascade.
                  Can also be a Jinja2 template string that resolves to an array.
        input_key: The input parameter name to inject each item as (default: "item")
        mode: How to collect results:
            - "aggregate": Return array of all results
            - "first_valid": Return first non-error result
            - "all_or_nothing": Fail if any cascade fails, otherwise return all
        max_parallel: Maximum number of concurrent cascade executions (default: 5)
        on_error: How to handle individual cascade failures:
            - "continue": Log error, continue processing remaining items
            - "fail_fast": Stop immediately on first error
            - "collect_errors": Continue but collect errors in result
        timeout: Optional timeout per cascade in seconds

    Returns:
        Dict with:
            - "results": Array of cascade outputs (or single result for first_valid)
            - "count": Number of successful executions
            - "errors": Array of error info (if on_error="collect_errors")
            - "total": Total items processed

    Example:
        ```yaml
        - name: process_customers
          tool: map_cascade
          inputs:
            cascade: "traits/process_customer.yaml"
            map_over: "{{ outputs.list_customers }}"
            input_key: "customer_id"
            mode: "aggregate"
            max_parallel: 10
        ```
    """
    from ..runner import run_cascade
    from ..tracing import get_current_trace

    # Convert string parameters to correct types (inputs come as strings from Jinja2)
    if isinstance(max_parallel, str):
        try:
            max_parallel = int(max_parallel)
        except ValueError:
            max_parallel = 5  # Default fallback

    if isinstance(timeout, str):
        try:
            timeout = int(timeout)
        except ValueError:
            timeout = None

    # Resolve cascade path relative to RVBBIT_ROOT (not cwd)
    cfg = get_config()
    resolved_cascade_ref = cascade
    if not os.path.isabs(cascade):
        resolved_cascade_ref = os.path.join(cfg.root_dir, cascade)

    # Add .yaml or .json extension if needed
    if not os.path.exists(resolved_cascade_ref):
        for ext in [".yaml", ".yml", ".json"]:
            if os.path.exists(resolved_cascade_ref + ext):
                resolved_cascade_ref = resolved_cascade_ref + ext
                break

    if not os.path.exists(resolved_cascade_ref):
        return {
            "_route": "error",
            "error": f"Cascade file not found: {cascade}",
            "results": [],
            "count": 0,
            "total": 0
        }

    # Handle map_over (might be a list or could be a string that needs evaluation)
    if isinstance(map_over, str):
        # If it's a string, assume it's already been rendered by Jinja2
        # and try to parse as a list
        import json
        try:
            items = json.loads(map_over)
        except:
            # If not JSON, treat as comma-separated string
            items = [item.strip() for item in map_over.split(",")]
    else:
        items = map_over

    if not isinstance(items, list):
        items = [items]  # Wrap single item in list

    total_items = len(items)
    if total_items == 0:
        return {
            "results": [],
            "count": 0,
            "total": 0,
            "_route": "success"
        }

    # Get trace context for lineage
    parent_trace = get_current_trace()
    parent_session_id = None
    try:
        from ..tracing import get_current_session_id
        parent_session_id = get_current_session_id()
    except:
        pass

    # Capture caller context for thread propagation
    import contextvars
    ctx = contextvars.copy_context()

    results = []
    errors = []
    successful_count = 0

    def run_single_item(index: int, item: Any) -> Dict[str, Any]:
        """Execute cascade for single item. Runs in copied context to preserve caller_id."""
        def _execute():
            # Generate unique session ID for this map item
            item_session_id = f"{parent_session_id}_map_{index}" if parent_session_id else f"map_{int(time.time())}_{uuid.uuid4().hex[:6]}_item_{index}"

            # Build input data
            input_data = {input_key: item}

            try:
                # Run cascade synchronously (blocking)
                result = run_cascade(
                    resolved_cascade_ref,
                    input_data,
                    session_id=item_session_id,
                    parent_trace=parent_trace,
                    parent_session_id=parent_session_id
                )

                return {
                    "index": index,
                    "item": item,
                    "result": result,
                    "error": None,
                    "session_id": item_session_id
                }

            except Exception as e:
                error_info = {
                    "index": index,
                    "item": item,
                    "result": None,
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "session_id": item_session_id
                }

                if on_error == "fail_fast":
                    raise

                return error_info

        # Run in copied context to preserve caller_id
        return ctx.run(_execute)

    # Execute cascades in parallel using ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(max_parallel, total_items)) as executor:
        # Submit all tasks
        futures = {
            executor.submit(run_single_item, i, item): i
            for i, item in enumerate(items)
        }

        # Collect results as they complete
        for future in as_completed(futures, timeout=timeout):
            try:
                result_dict = future.result()

                if result_dict["error"] is None:
                    successful_count += 1
                    results.append(result_dict)

                    # For first_valid mode, return immediately on first success
                    if mode == "first_valid" and successful_count == 1:
                        # Cancel remaining futures
                        for f in futures:
                            f.cancel()

                        return {
                            "result": result_dict["result"],
                            "item": result_dict["item"],
                            "index": result_dict["index"],
                            "session_id": result_dict["session_id"],
                            "_route": "success"
                        }
                else:
                    errors.append(result_dict)
                    if on_error == "fail_fast":
                        # Cancel remaining futures
                        for f in futures:
                            f.cancel()

                        return {
                            "_route": "error",
                            "error": result_dict["error"],
                            "item": result_dict["item"],
                            "index": result_dict["index"],
                            "results": results,
                            "errors": errors,
                            "count": successful_count,
                            "total": total_items
                        }

            except Exception as e:
                # Executor-level error
                errors.append({
                    "error": str(e),
                    "error_type": type(e).__name__
                })

    # All items processed - build final result
    if mode == "all_or_nothing" and len(errors) > 0:
        return {
            "_route": "error",
            "error": f"{len(errors)} of {total_items} cascades failed",
            "results": [r["result"] for r in results],
            "errors": errors,
            "count": successful_count,
            "total": total_items
        }

    # Default: aggregate mode
    return {
        "results": [r["result"] for r in results],
        "count": successful_count,
        "total": total_items,
        "errors": errors if on_error == "collect_errors" else None,
        "session_ids": [r["session_id"] for r in results],
        "_route": "success"
    }