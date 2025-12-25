from .base import simple_eddy
import threading
import time
import uuid
from typing import Optional, List, Dict, Any, Union
from ..tracing import get_current_trace, TraceNode
from ..config import get_config
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
    # Resolve path. Assume cascade_ref is either absolute or relative to the project root.
    resolved_cascade_ref = cascade_ref
    if not os.path.isabs(cascade_ref):
        # Assume cascade_ref is relative to the project root (where run_cascade is called)
        resolved_cascade_ref = os.path.join(os.getcwd(), cascade_ref)

    if not os.path.exists(resolved_cascade_ref) and os.path.exists(resolved_cascade_ref + ".json"):
         resolved_cascade_ref = resolved_cascade_ref + ".json"

    # Generate unique session ID (include candidate index if provided)
    if candidate_index is not None:
        session_id = f"spawned_{int(time.time())}_{uuid.uuid4().hex[:6]}_sounding_{candidate_index}"
    else:
        session_id = f"spawned_{int(time.time())}_{uuid.uuid4().hex[:6]}"

    def worker():
        # Import locally to avoid circular dependency
        from ..runner import run_cascade

        # Run in separate thread
        try:
            # We use a new runner instance, passing the parent trace AND parent_session_id AND candidate_index
            run_cascade(resolved_cascade_ref, input_data or {}, session_id=session_id, parent_trace=parent_trace, parent_session_id=parent_session_id, candidate_index=candidate_index)
        except Exception as e:
            print(f"[Spawn Error] {e}")

    t = threading.Thread(target=worker, daemon=True)
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
            cascade: "tackle/process_customer.yaml"
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

    # Resolve cascade path
    resolved_cascade_ref = cascade
    if not os.path.isabs(cascade):
        resolved_cascade_ref = os.path.join(os.getcwd(), cascade)

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

    results = []
    errors = []
    successful_count = 0

    def run_single_item(index: int, item: Any) -> Dict[str, Any]:
        """Execute cascade for single item."""
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