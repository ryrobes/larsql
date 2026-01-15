"""
RLM-Style Tools for Context Decomposition

These tools implement the "model as context programmer" pattern, allowing
LLM cells to write code that decomposes and analyzes large contexts.

Key tools:
- rlm_exec: Execute Python code with RLM tools injected (llm_query, chunk_text)
- llm_analyze: Simple sub-LLM call for chunk analysis (also callable directly)
- llm_batch_analyze: Parallel sub-LLM calls for multiple chunks
- chunk_text: Deterministic text chunking

The pattern:
1. Model receives large context + task
2. Model writes Python code using rlm_exec
3. Code calls llm_query() for sub-LLM queries (RLM-style naming)
4. Model synthesizes results and calls set_state()

All calls go through RVBBIT's normal observability (unified_logs, cost tracking).
"""

from .base import simple_eddy
from ..logs import log_message
from ..config import get_config
from ..agent import Agent
from typing import Dict, Any, List, Optional, Union
import json
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================================
# RLM Executor - The main tool for RLM-style code execution
# ============================================================================

@simple_eddy
def rlm_exec(
    code: str,
    context: str | None = None,
    task: str | None = None,
    _state: Dict[str, Any] | None = None,
    _input: Dict[str, Any] | None = None,
    _session_id: str | None = None
) -> Dict[str, Any]:
    """
    Execute Python code with RLM-style tools injected.

    This is the RLM execution environment. Your code has access to:
    - `context`: The input context string (if provided)
    - `task`: The task description (if provided)
    - `llm_query(prompt)`: Make a sub-LLM call, returns string
    - `llm_query_batched([prompts])`: Parallel sub-LLM calls, returns list of strings
    - `chunk(text, strategy)`: Chunk text, returns list of strings
    - `set_state(key, value)`: Store result in state
    - `results`: Pre-initialized empty list for accumulating findings
    - `provenance`: Pre-initialized empty dict for tracking chunk sources

    Args:
        code: Python code to execute
        context: The large context to process (optional, can come from _input)
        task: The task description (optional, can come from _input)
        _state: Injected cascade state
        _input: Injected cascade input
        _session_id: Session ID for logging

    Returns:
        Dict with stdout, any set_state calls, and execution info

    Example:
        ```python
        # Chunk the context
        chunks = chunk(context, "paragraph")
        print(f"Split into {len(chunks)} chunks")

        # Analyze each chunk
        for i, c in enumerate(chunks):
            summary = llm_query(f"Summarize: {c}")
            results.append({"chunk": i, "summary": summary})

        # Synthesize
        all_summaries = "\\n".join([r["summary"] for r in results])
        final = llm_query(f"Combine these summaries: {all_summaries}")
        set_state("final_answer", final)
        ```
    """
    import io
    import sys

    cfg = get_config()

    # Get context and task from explicit args or _input
    ctx = context or (_input or {}).get("context", "")
    tsk = task or (_input or {}).get("task", "")

    # State updates collector
    state_updates = {}

    # Stdout capture
    stdout_capture = io.StringIO()

    # Token/cost tracking
    total_tokens = 0
    llm_calls = 0

    # ---- Define injected functions ----

    def llm_query(prompt: str, model: str | None = None) -> str:
        """Make a sub-LLM call. Returns the response string."""
        nonlocal total_tokens, llm_calls

        analysis_model = model or cfg.context_selector_model
        llm_calls += 1

        try:
            agent = Agent(
                model=analysis_model,
                system_prompt="You are a precise analyst. Be concise.",
                base_url=cfg.provider_base_url,
                api_key=cfg.provider_api_key
            )
            response = agent.run(prompt)
            total_tokens += (response.get("tokens_in", 0) or 0) + (response.get("tokens_out", 0) or 0)
            return response.get("content", "")
        except Exception as e:
            return f"[LLM Error: {e}]"

    def llm_query_batched(prompts: List[str], model: str | None = None) -> List[str]:
        """Make parallel sub-LLM calls. Returns list of response strings."""
        nonlocal total_tokens, llm_calls

        analysis_model = model or cfg.context_selector_model
        results = [None] * len(prompts)

        def process_one(idx: int, prompt: str) -> tuple:
            nonlocal llm_calls
            llm_calls += 1
            try:
                agent = Agent(
                    model=analysis_model,
                    system_prompt="You are a precise analyst. Be concise.",
                    base_url=cfg.provider_base_url,
                    api_key=cfg.provider_api_key
                )
                response = agent.run(prompt)
                tokens = (response.get("tokens_in", 0) or 0) + (response.get("tokens_out", 0) or 0)
                return (idx, response.get("content", ""), tokens)
            except Exception as e:
                return (idx, f"[LLM Error: {e}]", 0)

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(process_one, i, p) for i, p in enumerate(prompts)]
            for future in as_completed(futures):
                idx, result, tokens = future.result()
                results[idx] = result
                nonlocal total_tokens
                total_tokens += tokens

        return results

    def chunk(text: str, strategy: str = "paragraph") -> List[str]:
        """Chunk text using a strategy. Returns list of chunk strings."""
        result = _chunk_text_internal(text, strategy)
        return result.get("chunks", [])

    def set_state_func(key: str, value: Any):
        """Store a value in state."""
        state_updates[key] = value if isinstance(value, str) else json.dumps(value)

    # ---- Build execution environment ----

    exec_globals = {
        # Context variables
        'context': ctx,
        'task': tsk,
        # RLM primitives (RLM naming convention)
        'llm_query': llm_query,
        'llm_query_batched': llm_query_batched,
        'chunk': chunk,
        'set_state': set_state_func,
        # Accumulation variables
        'results': [],
        'provenance': {},
        # Standard utilities
        'print': lambda *args: print(*args, file=stdout_capture),
        'json': json,
        'len': len,
        'str': str,
        'int': int,
        'float': float,
        'list': list,
        'dict': dict,
        'range': range,
        'enumerate': enumerate,
        'zip': zip,
        'sum': sum,
        'min': min,
        'max': max,
        'sorted': sorted,
    }

    exec_locals = {}

    # Execute
    try:
        exec(code, exec_globals, exec_locals)

        # Capture final state of accumulation variables
        final_results = exec_globals.get('results', [])
        final_provenance = exec_globals.get('provenance', {})

        stdout_output = stdout_capture.getvalue()

        return {
            "stdout": stdout_output,
            "state_updates": state_updates,
            "results": final_results,
            "provenance": final_provenance,
            "llm_calls": llm_calls,
            "total_tokens": total_tokens,
            "_route": "success"
        }

    except Exception as e:
        import traceback
        return {
            "error": str(e),
            "traceback": traceback.format_exc(),
            "stdout": stdout_capture.getvalue(),
            "state_updates": state_updates,
            "_route": "error"
        }


def _chunk_text_internal(text: str, strategy: str = "paragraph") -> Dict[str, Any]:
    """Internal chunking function used by both rlm_exec and chunk_text tool."""
    chunks = []
    provenance = {}

    if strategy == "paragraph":
        raw_chunks = [p.strip() for p in text.split('\n\n') if p.strip()]
        for i, c in enumerate(raw_chunks):
            chunks.append(c)
            provenance[f"para_{i}"] = {"index": i, "length": len(c)}

    elif strategy == "sentence":
        import re
        sentences = re.split(r'(?<=[.!?])\s+', text)
        for i, s in enumerate(sentences):
            if s.strip():
                chunks.append(s.strip())
                provenance[f"sent_{i}"] = {"index": i, "length": len(s)}

    elif strategy == "markdown":
        import re
        sections = re.split(r'\n(?=#+\s)', text)
        for i, section in enumerate(sections):
            if section.strip():
                chunks.append(section.strip())
                header_match = re.match(r'^(#+)\s+(.+)', section)
                provenance[f"section_{i}"] = {
                    "index": i,
                    "header": header_match.group(2) if header_match else None,
                    "length": len(section)
                }

    elif strategy == "fixed":
        chunk_size = 4000
        overlap = 200
        pos = 0
        idx = 0
        while pos < len(text):
            end = min(pos + chunk_size, len(text))
            chunks.append(text[pos:end])
            provenance[f"chunk_{idx}"] = {"index": idx, "start": pos, "end": end}
            pos += chunk_size - overlap
            idx += 1

    else:
        # Default to paragraph
        return _chunk_text_internal(text, "paragraph")

    return {"chunks": chunks, "count": len(chunks), "strategy": strategy, "provenance": provenance}


@simple_eddy
def llm_analyze(
    text: str,
    instruction: str,
    model: str | None = None,
    max_tokens: int = 1000
) -> Dict[str, Any]:
    """
    Analyze text using a sub-LLM call.

    This is the core primitive for RLM-style context decomposition.
    Use it within run_code to process chunks of a larger context.

    Args:
        text: The text to analyze (a chunk of larger context)
        instruction: What to do with the text (summarize, extract, answer, etc.)
        model: Optional model override (default: context_selector_model - cheap/fast)
        max_tokens: Max response length (default: 1000)

    Returns:
        Dict with:
            - result: The LLM's analysis
            - tokens: Token usage
            - chunk_hash: Hash of input for provenance tracking

    Example (from within run_code):
        ```python
        for i, chunk in enumerate(chunks):
            result = llm_analyze({
                "text": chunk,
                "instruction": "Summarize the key points"
            })
            summaries.append({
                "index": i,
                "summary": result["result"],
                "hash": result["chunk_hash"]
            })
        ```
    """
    cfg = get_config()

    # Use cheap model by default for chunk processing
    analysis_model = model or cfg.context_selector_model

    # Compute hash for provenance tracking
    chunk_hash = hashlib.sha256(text.encode()).hexdigest()[:12]

    # Build prompt
    prompt = f"""{instruction}

Text to analyze:
```
{text}
```

Respond concisely. Focus on information directly relevant to the instruction."""

    # Log the call
    log_message(
        None, "system",
        f"llm_analyze: {len(text)} chars, instruction: {instruction[:50]}...",
        metadata={
            "tool": "llm_analyze",
            "text_length": len(text),
            "chunk_hash": chunk_hash,
            "model": analysis_model
        }
    )

    try:
        agent = Agent(
            model=analysis_model,
            system_prompt="You are a precise text analyst. Be concise and factual.",
            base_url=cfg.provider_base_url,
            api_key=cfg.provider_api_key
        )

        response = agent.run(prompt)
        result_text = response.get("content", "")
        tokens_in = response.get("tokens_in", 0)
        tokens_out = response.get("tokens_out", 0)

        return {
            "result": result_text,
            "tokens": tokens_in + tokens_out,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "chunk_hash": chunk_hash,
            "model": analysis_model
        }

    except Exception as e:
        log_message(
            None, "system",
            f"llm_analyze error: {type(e).__name__}: {e}",
            metadata={"tool": "llm_analyze", "error": str(e)}
        )
        return {
            "result": f"[Analysis failed: {e}]",
            "tokens": 0,
            "chunk_hash": chunk_hash,
            "error": str(e)
        }


@simple_eddy
def llm_batch_analyze(
    items: List[Dict[str, str]],
    model: str | None = None,
    max_parallel: int = 5
) -> Dict[str, Any]:
    """
    Analyze multiple text chunks in parallel.

    This is the batched version of llm_analyze for processing many chunks
    efficiently. Results are returned in the same order as inputs.

    Args:
        items: List of dicts with "text" and "instruction" keys
        model: Optional model override (default: context_selector_model)
        max_parallel: Max concurrent LLM calls (default: 5)

    Returns:
        Dict with:
            - results: List of analysis results (same order as inputs)
            - total_tokens: Sum of all token usage
            - success_count: Number of successful analyses
            - error_count: Number of failed analyses

    Example (from within run_code):
        ```python
        # Prepare batch
        batch = [
            {"text": chunk, "instruction": f"Summarize for: {task}"}
            for chunk in chunks
        ]

        # Process in parallel
        result = llm_batch_analyze({"items": batch, "max_parallel": 10})

        for i, r in enumerate(result["results"]):
            chunks_processed.append({
                "index": i,
                "summary": r["result"],
                "hash": r["chunk_hash"]
            })
        ```
    """
    cfg = get_config()
    analysis_model = model or cfg.context_selector_model

    # Parse items if passed as JSON string
    if isinstance(items, str):
        try:
            items = json.loads(items)
        except:
            return {"error": "items must be a list of {text, instruction} dicts"}

    if not items:
        return {
            "results": [],
            "total_tokens": 0,
            "success_count": 0,
            "error_count": 0
        }

    log_message(
        None, "system",
        f"llm_batch_analyze: {len(items)} items, max_parallel={max_parallel}",
        metadata={"tool": "llm_batch_analyze", "batch_size": len(items)}
    )

    results = [None] * len(items)  # Pre-allocate to maintain order
    total_tokens = 0
    success_count = 0
    error_count = 0

    def process_item(index: int, item: dict) -> tuple:
        """Process single item, returns (index, result)"""
        text = item.get("text", "")
        instruction = item.get("instruction", "Analyze this text")

        chunk_hash = hashlib.sha256(text.encode()).hexdigest()[:12]

        prompt = f"""{instruction}

Text:
```
{text}
```

Respond concisely."""

        try:
            agent = Agent(
                model=analysis_model,
                system_prompt="You are a precise text analyst. Be concise.",
                base_url=cfg.provider_base_url,
                api_key=cfg.provider_api_key
            )

            response = agent.run(prompt)
            tokens = (response.get("tokens_in", 0) or 0) + (response.get("tokens_out", 0) or 0)

            return (index, {
                "result": response.get("content", ""),
                "tokens": tokens,
                "chunk_hash": chunk_hash,
                "success": True
            })

        except Exception as e:
            return (index, {
                "result": f"[Error: {e}]",
                "tokens": 0,
                "chunk_hash": chunk_hash,
                "success": False,
                "error": str(e)
            })

    # Process in parallel
    with ThreadPoolExecutor(max_workers=min(max_parallel, len(items))) as executor:
        futures = {
            executor.submit(process_item, i, item): i
            for i, item in enumerate(items)
        }

        for future in as_completed(futures):
            try:
                index, result = future.result()
                results[index] = result
                total_tokens += result.get("tokens", 0)
                if result.get("success"):
                    success_count += 1
                else:
                    error_count += 1
            except Exception as e:
                index = futures[future]
                results[index] = {
                    "result": f"[Future error: {e}]",
                    "tokens": 0,
                    "success": False,
                    "error": str(e)
                }
                error_count += 1

    return {
        "results": results,
        "total_tokens": total_tokens,
        "success_count": success_count,
        "error_count": error_count
    }


@simple_eddy
def chunk_text(
    text: str,
    strategy: str = "paragraph",
    chunk_size: int = 4000,
    overlap: int = 200
) -> Dict[str, Any]:
    """
    Chunk text using various strategies.

    This is a deterministic helper for splitting text before LLM analysis.
    Use this when you want predictable chunking without LLM involvement.

    Args:
        text: The text to chunk
        strategy: Chunking strategy:
            - "paragraph": Split on double newlines
            - "sentence": Split on sentence boundaries
            - "fixed": Fixed-size chunks with overlap
            - "markdown": Split on markdown headers
            - "code": Split on function/class definitions
        chunk_size: Target chunk size for "fixed" strategy
        overlap: Overlap between chunks for "fixed" strategy

    Returns:
        Dict with:
            - chunks: List of text chunks
            - count: Number of chunks
            - strategy: Strategy used
            - provenance: Dict mapping chunk_id -> metadata
    """
    # Use the internal implementation
    return _chunk_text_internal(text, strategy)
