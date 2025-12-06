# Advanced Features Implementation Plan

Three production-grade patterns from "the big boys" that will make Windlass significantly more robust and efficient.

---

## 1. Token Budget Enforcement

### The Problem

**Current behavior:**
- Context grows unbounded until hitting model limits
- Cascade crashes with cryptic "context too long" errors
- No visibility into token consumption until failure
- User has to manually track and prune

**Real-world failure scenario:**
```
Phase 1: RAG search → 15K tokens
Phase 2: SQL query → 20K tokens
Phase 3: Chart generation → 10K tokens
Phase 4: Analysis → Context = 45K tokens
Phase 5: Refinement → Boom! Model limit exceeded
```

### The Solution

**Hard token budgets with automatic enforcement:**

```json
{
  "cascade_id": "dashboard_generator",
  "token_budget": {
    "max_total": 100000,
    "reserve_for_output": 4000,
    "strategy": "sliding_window",
    "warning_threshold": 0.8
  },
  "phases": [...]
}
```

**Configuration Options:**

```python
class TokenBudgetConfig(BaseModel):
    max_total: int = 100000  # Hard limit for context
    reserve_for_output: int = 4000  # Always leave room for response
    strategy: Literal["sliding_window", "prune_oldest", "summarize", "fail"] = "sliding_window"
    warning_threshold: float = 0.8  # Warn at 80% capacity
    phase_overrides: Optional[Dict[str, int]] = None  # Per-phase budgets
```

**Strategies:**

1. **`sliding_window`** (Recommended default)
   - Keep recent N messages that fit in budget
   - Always preserve: system prompt, current phase instructions, last 3 turns
   - Log what gets pruned for debugging

2. **`prune_oldest`**
   - Remove oldest messages first (FIFO)
   - Preserve critical markers (errors, decisions, handoffs)
   - More aggressive than sliding window

3. **`summarize`** (Most sophisticated)
   - When hitting threshold, pause execution
   - Use cheap model (Gemini Flash) to summarize old context
   - Replace 20K tokens with 2K summary
   - Continue with compressed context
   - Configuration:
     ```json
     {
       "strategy": "summarize",
       "summarizer": {
         "model": "google/gemini-2.0-flash-lite",
         "target_size": 5000,
         "preserve": ["errors", "decisions", "last_3_turns"]
       }
     }
     ```

4. **`fail`**
   - Throw clear error with token breakdown
   - Useful for testing/validation
   - Forces user to design tighter cascades

### Implementation

**New Module: `windlass/token_budget.py`**

```python
from typing import List, Dict, Any
import tiktoken

class TokenBudgetManager:
    def __init__(self, config: TokenBudgetConfig, model: str):
        self.config = config
        self.model = model
        self.encoding = tiktoken.encoding_for_model(self._normalize_model(model))
        self.current_usage = 0

    def count_tokens(self, messages: List[Dict]) -> int:
        """Count tokens in message list."""
        total = 0
        for msg in messages:
            # Count message overhead (role, etc)
            total += 4  # Every message has ~4 token overhead

            # Count content
            if isinstance(msg.get("content"), str):
                total += len(self.encoding.encode(msg["content"]))

            # Count tool calls
            if "tool_calls" in msg:
                total += len(self.encoding.encode(str(msg["tool_calls"])))

        return total

    def check_budget(self, messages: List[Dict]) -> Dict[str, Any]:
        """Check if within budget, return status."""
        current = self.count_tokens(messages)
        available = self.config.max_total - self.config.reserve_for_output

        return {
            "current": current,
            "limit": available,
            "percentage": current / available,
            "over_budget": current > available,
            "warning": current > (available * self.config.warning_threshold)
        }

    def enforce_budget(self, messages: List[Dict]) -> List[Dict]:
        """Prune messages to fit within budget."""
        status = self.check_budget(messages)

        if not status["over_budget"]:
            return messages

        if self.config.strategy == "sliding_window":
            return self._sliding_window(messages)
        elif self.config.strategy == "prune_oldest":
            return self._prune_oldest(messages)
        elif self.config.strategy == "summarize":
            return self._summarize(messages)
        elif self.config.strategy == "fail":
            raise TokenBudgetExceeded(status)

    def _sliding_window(self, messages: List[Dict]) -> List[Dict]:
        """Keep most recent messages that fit."""
        # Always preserve system message
        preserved = [messages[0]] if messages[0].get("role") == "system" else []

        # Work backwards from most recent
        available = self.config.max_total - self.config.reserve_for_output
        current = self.count_tokens(preserved)

        for msg in reversed(messages[1:]):
            msg_tokens = self.count_tokens([msg])
            if current + msg_tokens <= available:
                preserved.insert(1, msg)
                current += msg_tokens
            else:
                break

        pruned_count = len(messages) - len(preserved)
        if pruned_count > 0:
            logger.info(f"Token budget: pruned {pruned_count} messages ({current}/{available} tokens)")

        return preserved

    def _prune_oldest(self, messages: List[Dict]) -> List[Dict]:
        """Remove oldest messages until within budget."""
        # Preserve: system, errors, last 3 turns
        critical_indices = self._find_critical_messages(messages)

        available = self.config.max_total - self.config.reserve_for_output

        # Start with all messages
        kept = list(range(len(messages)))
        current = self.count_tokens(messages)

        # Remove oldest non-critical messages
        for i in range(len(messages)):
            if i in critical_indices:
                continue

            if current <= available:
                break

            # Remove this message
            kept.remove(i)
            current = self.count_tokens([messages[j] for j in kept])

        return [messages[i] for i in sorted(kept)]

    def _summarize(self, messages: List[Dict]) -> List[Dict]:
        """Summarize old context using cheap model."""
        # Find split point (keep recent, summarize old)
        split_index = len(messages) - 10  # Keep last 10 messages

        old_messages = messages[:split_index]
        recent_messages = messages[split_index:]

        # Generate summary
        summary_prompt = self._build_summary_prompt(old_messages)

        from .agent import Agent
        summarizer = Agent(model=self.config.summarizer["model"])
        response = summarizer.call([{"role": "user", "content": summary_prompt}])

        summary_msg = {
            "role": "system",
            "content": f"CONTEXT SUMMARY:\n{response['content']}"
        }

        # Return: summary + recent messages
        return [summary_msg] + recent_messages

    def _find_critical_messages(self, messages: List[Dict]) -> set:
        """Find indices of critical messages to preserve."""
        critical = set()

        # System message
        if messages[0].get("role") == "system":
            critical.add(0)

        # Last 3 turns (user + assistant pairs)
        turn_count = 0
        for i in reversed(range(len(messages))):
            if messages[i].get("role") in ["user", "assistant"]:
                critical.add(i)
                if messages[i].get("role") == "assistant":
                    turn_count += 1
                if turn_count >= 3:
                    break

        # Messages with errors
        for i, msg in enumerate(messages):
            if "error" in str(msg.get("content", "")).lower():
                critical.add(i)

        # Messages with routing decisions
        for i, msg in enumerate(messages):
            if "route_to" in str(msg.get("content", "")):
                critical.add(i)

        return critical

    def _build_summary_prompt(self, messages: List[Dict]) -> str:
        """Build prompt for summarization model."""
        target_size = self.config.summarizer["target_size"]

        return f"""Summarize this conversation history in approximately {target_size} tokens.

Focus on:
1. Key decisions made
2. Important findings from tools
3. Errors encountered
4. Current state/progress

Be extremely concise. Omit pleasantries and explanations.

Conversation:
{self._format_messages_for_summary(messages)}

Summary:"""

    def _format_messages_for_summary(self, messages: List[Dict]) -> str:
        """Format messages for summarization."""
        lines = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = str(msg.get("content", ""))[:500]  # Truncate long messages
            lines.append(f"[{role}]: {content}")
        return "\n".join(lines)
```

**Integration Points:**

1. **In `runner.py` before each agent call:**
   ```python
   # Check budget before expensive operation
   budget_status = self.token_manager.check_budget(self.context_messages)

   if budget_status["warning"]:
       console.print(f"[yellow]⚠️  Token budget: {budget_status['percentage']:.1%} used[/yellow]")

   if budget_status["over_budget"]:
       console.print(f"[red]💥 Token budget exceeded, enforcing with strategy: {self.config.token_budget.strategy}[/red]")
       self.context_messages = self.token_manager.enforce_budget(self.context_messages)
   ```

2. **In `cascade.py`:**
   ```python
   class CascadeConfig(BaseModel):
       # ... existing fields ...
       token_budget: Optional[TokenBudgetConfig] = None
   ```

3. **Logging integration:**
   ```python
   # Log token usage in unified_logs
   log_unified(
       session_id=self.session_id,
       metadata={
           "token_usage": budget_status["current"],
           "token_limit": budget_status["limit"],
           "token_percentage": budget_status["percentage"]
       }
   )
   ```

**UI Integration:**

In the debug UI, show token budget gauge:
```
Token Budget: ████████░░ 82% (82,000 / 100,000)
⚠️  Warning: Approaching limit
```

**Example Usage:**

```json
{
  "cascade_id": "data_analysis",
  "token_budget": {
    "max_total": 120000,
    "reserve_for_output": 4000,
    "strategy": "summarize",
    "warning_threshold": 0.75,
    "summarizer": {
      "model": "google/gemini-2.0-flash-lite",
      "target_size": 3000
    }
  },
  "phases": [
    {
      "name": "explore",
      "context_ttl": {"tool_results": 2},
      "tackle": ["sql_search", "sql_query"]
    }
  ]
}
```

**Benefits:**

- ✅ No more mysterious crashes
- ✅ Transparent token tracking
- ✅ Automatic pruning/summarization
- ✅ Per-cascade budget configuration
- ✅ Works with existing context_ttl/retention

---

## 2. Content-Addressed Tool Caching

### The Problem

**Current behavior:**
- Every tool call executes, even if identical to previous call
- Agent searches "sales tables" 5 times → 5 RAG queries
- SQL query runs 3 times with same parameters → 3 DB hits
- Massive waste for deterministic tools

**Real-world scenario:**
```
Turn 1: sql_search("sales data") → 10K token response
Turn 3: sql_search("sales data") → Same 10K token response (redundant!)
Turn 5: sql_search("sales data") → Same 10K token response (still redundant!)

Result: 30K tokens, 3 RAG queries, when 1 would suffice
```

### The Solution

**Content-addressed caching with tool-specific strategies:**

```json
{
  "tool_caching": {
    "enabled": true,
    "storage": "memory",
    "global_ttl": 3600,
    "tools": {
      "sql_search": {
        "enabled": true,
        "ttl": 7200,
        "key": "query",
        "hit_message": "✓ Cache hit (RAG query skipped)"
      },
      "sql_query": {
        "enabled": true,
        "ttl": 300,
        "key": "sql_hash",
        "invalidate_on": ["sql_schema_change"]
      },
      "create_chart": {
        "enabled": false,
        "reason": "Non-deterministic (style variations desired)"
      }
    }
  }
}
```

**Configuration:**

```python
class ToolCachingConfig(BaseModel):
    enabled: bool = False
    storage: Literal["memory", "redis", "sqlite"] = "memory"
    global_ttl: int = 3600  # Default TTL in seconds
    max_cache_size: int = 1000  # Max entries before LRU eviction
    tools: Dict[str, ToolCachePolicy] = Field(default_factory=dict)

class ToolCachePolicy(BaseModel):
    enabled: bool = True
    ttl: int  # Seconds
    key: Literal["args_hash", "query", "sql_hash", "custom"] = "args_hash"
    custom_key_fn: Optional[str] = None  # Python callable name
    hit_message: Optional[str] = None  # Message returned on cache hit
    invalidate_on: List[str] = Field(default_factory=list)  # Events that clear cache
```

### Implementation

**New Module: `windlass/tool_cache.py`**

```python
import hashlib
import json
import time
from typing import Any, Dict, Optional, Callable
from collections import OrderedDict

class ToolCache:
    """Content-addressed cache for deterministic tool results."""

    def __init__(self, config: ToolCachingConfig):
        self.config = config
        self.cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self.stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0
        }

    def get(self, tool_name: str, args: Dict[str, Any]) -> Optional[Any]:
        """Get cached result if available."""
        if not self.config.enabled:
            return None

        policy = self._get_policy(tool_name)
        if not policy or not policy.enabled:
            return None

        # Generate cache key
        cache_key = self._generate_key(tool_name, args, policy)

        # Check cache
        if cache_key in self.cache:
            entry = self.cache[cache_key]

            # Check expiry
            if time.time() - entry.timestamp < policy.ttl:
                # Move to end (LRU)
                self.cache.move_to_end(cache_key)
                self.stats["hits"] += 1

                logger.debug(f"Tool cache HIT: {tool_name} ({cache_key[:8]})")
                return entry.result
            else:
                # Expired
                del self.cache[cache_key]

        self.stats["misses"] += 1
        logger.debug(f"Tool cache MISS: {tool_name}")
        return None

    def set(self, tool_name: str, args: Dict[str, Any], result: Any):
        """Store result in cache."""
        if not self.config.enabled:
            return

        policy = self._get_policy(tool_name)
        if not policy or not policy.enabled:
            return

        # Generate cache key
        cache_key = self._generate_key(tool_name, args, policy)

        # Store entry
        entry = CacheEntry(
            tool=tool_name,
            args=args,
            result=result,
            timestamp=time.time()
        )

        self.cache[cache_key] = entry

        # Enforce size limit (LRU eviction)
        while len(self.cache) > self.config.max_cache_size:
            evicted_key = next(iter(self.cache))
            del self.cache[evicted_key]
            self.stats["evictions"] += 1

        logger.debug(f"Tool cache SET: {tool_name} ({cache_key[:8]})")

    def invalidate(self, event: str):
        """Invalidate cached entries based on event."""
        keys_to_remove = []

        for key, entry in self.cache.items():
            policy = self._get_policy(entry.tool)
            if policy and event in policy.invalidate_on:
                keys_to_remove.append(key)

        for key in keys_to_remove:
            del self.cache[key]
            logger.debug(f"Tool cache INVALIDATED: {key[:8]} (event: {event})")

    def clear(self, tool_name: Optional[str] = None):
        """Clear cache for specific tool or all tools."""
        if tool_name:
            keys_to_remove = [k for k, v in self.cache.items() if v.tool == tool_name]
            for key in keys_to_remove:
                del self.cache[key]
        else:
            self.cache.clear()

    def _get_policy(self, tool_name: str) -> Optional[ToolCachePolicy]:
        """Get caching policy for tool."""
        return self.config.tools.get(tool_name)

    def _generate_key(self, tool_name: str, args: Dict[str, Any], policy: ToolCachePolicy) -> str:
        """Generate cache key based on policy."""
        if policy.key == "args_hash":
            # Hash all arguments
            args_str = json.dumps(args, sort_keys=True)
            args_hash = hashlib.sha256(args_str.encode()).hexdigest()
            return f"{tool_name}:{args_hash}"

        elif policy.key == "query":
            # Use specific argument as key (e.g., search query)
            query = args.get("query", "")
            query_hash = hashlib.sha256(query.encode()).hexdigest()
            return f"{tool_name}:query:{query_hash}"

        elif policy.key == "sql_hash":
            # Hash SQL string
            sql = args.get("sql", "")
            sql_hash = hashlib.sha256(sql.encode()).hexdigest()
            return f"{tool_name}:sql:{sql_hash}"

        elif policy.key == "custom" and policy.custom_key_fn:
            # Custom key function
            key_fn = self._load_custom_key_fn(policy.custom_key_fn)
            return f"{tool_name}:custom:{key_fn(args)}"

        else:
            # Fallback to args hash
            args_str = json.dumps(args, sort_keys=True)
            args_hash = hashlib.sha256(args_str.encode()).hexdigest()
            return f"{tool_name}:{args_hash}"

    def _load_custom_key_fn(self, fn_name: str) -> Callable:
        """Load custom key function by name."""
        # TODO: Implement plugin system for custom key functions
        raise NotImplementedError("Custom key functions not yet implemented")

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        total = self.stats["hits"] + self.stats["misses"]
        hit_rate = self.stats["hits"] / total if total > 0 else 0

        return {
            "hits": self.stats["hits"],
            "misses": self.stats["misses"],
            "evictions": self.stats["evictions"],
            "hit_rate": hit_rate,
            "size": len(self.cache),
            "max_size": self.config.max_cache_size
        }


class CacheEntry:
    """Single cache entry."""
    def __init__(self, tool: str, args: Dict, result: Any, timestamp: float):
        self.tool = tool
        self.args = args
        self.result = result
        self.timestamp = timestamp
```

**Integration in `runner.py`:**

```python
class WindlassRunner:
    def __init__(self, ...):
        # ... existing init ...

        # Initialize tool cache if configured
        if self.config.tool_caching:
            self.tool_cache = ToolCache(self.config.tool_caching)
        else:
            self.tool_cache = None

    def _execute_tool(self, func_name: str, arguments: dict, ...):
        # Check cache before execution
        if self.tool_cache:
            cached_result = self.tool_cache.get(func_name, arguments)
            if cached_result is not None:
                # Cache hit!
                policy = self.tool_cache.config.tools.get(func_name)
                hit_msg = policy.hit_message if policy else "Cache hit"

                console.print(f"{indent}    [dim green]⚡ {hit_msg}[/dim green]")

                # Log cache hit
                log_unified(
                    session_id=self.session_id,
                    node_type="tool_cache_hit",
                    metadata={
                        "tool": func_name,
                        "args": arguments,
                        "cache_stats": self.tool_cache.get_stats()
                    }
                )

                return cached_result

        # Execute tool normally
        result = func(**arguments)

        # Store in cache
        if self.tool_cache:
            self.tool_cache.set(func_name, arguments, result)

        return result
```

**Session-level cache statistics:**

```python
# At end of cascade, log cache effectiveness
if self.tool_cache:
    stats = self.tool_cache.get_stats()
    console.print(f"\n[dim]Tool Cache Stats:[/dim]")
    console.print(f"[dim]  Hit rate: {stats['hit_rate']:.1%}[/dim]")
    console.print(f"[dim]  Hits: {stats['hits']}, Misses: {stats['misses']}[/dim]")
    console.print(f"[dim]  Cache size: {stats['size']}/{stats['max_size']}[/dim]")
```

**Example Configurations:**

**SQL RAG workflow:**
```json
{
  "tool_caching": {
    "enabled": true,
    "tools": {
      "sql_search": {
        "enabled": true,
        "ttl": 7200,
        "key": "query",
        "hit_message": "✓ Using cached schema search"
      },
      "sql_query": {
        "enabled": true,
        "ttl": 600,
        "key": "sql_hash"
      }
    }
  }
}
```

**API integration workflow:**
```json
{
  "tool_caching": {
    "enabled": true,
    "tools": {
      "fetch_api_data": {
        "enabled": true,
        "ttl": 300,
        "key": "args_hash",
        "invalidate_on": ["api_update_event"]
      }
    }
  }
}
```

**Benefits:**

- ✅ Massive token savings (60-80% for repeated queries)
- ✅ Faster execution (skip expensive operations)
- ✅ Reduced API costs
- ✅ Per-tool configuration
- ✅ Cache hit/miss tracking in logs
- ✅ LRU eviction prevents memory bloat

---

## 3. Multi-Stage Thinking (Scratchpad Pattern)

### The Problem

**Current behavior:**
- Agent thinks and outputs in single step
- Reasoning mixed with final answer
- Hard to validate intermediate thinking
- Can't separate "working notes" from "deliverable"

**Example of messy output:**
```
Let me analyze this... The sales data shows... hmm, wait...
I need to consider Q4... Actually, looking at the trends...
Okay so the recommendation is: Increase marketing spend.
Wait, but what about... [continues rambling]
```

### The Solution

**Force structured thinking in isolated scratchpad, then clean output:**

```json
{
  "phases": [
    {
      "name": "think",
      "instructions": "Analyze the data. Write your reasoning in <scratchpad> tags.",
      "output_extraction": {
        "pattern": "<scratchpad>(.*?)</scratchpad>",
        "store_as": "reasoning"
      }
    },
    {
      "name": "execute",
      "instructions": "Based on this reasoning:\n\n{{ state.reasoning }}\n\nGenerate clean output.",
      "context_retention": "output_only"
    }
  ]
}
```

**What this does:**
1. Phase 1: Agent does messy thinking in scratchpad
2. Framework extracts scratchpad content
3. Phase 2: Clean slate + extracted reasoning → polished output
4. Next phases see only clean output (scratchpad hidden)

### Configuration

```python
class OutputExtractionConfig(BaseModel):
    """Extract structured data from phase output."""
    pattern: str  # Regex pattern
    store_as: str  # State variable name
    required: bool = False  # Fail if pattern not found
    format: Literal["text", "json", "code"] = "text"  # Parse extracted content
```

**In PhaseConfig:**
```python
class PhaseConfig(BaseModel):
    # ... existing fields ...
    output_extraction: Optional[OutputExtractionConfig] = None
```

### Implementation

**New Module: `windlass/extraction.py`**

```python
import re
import json
from typing import Any, Dict, Optional

class OutputExtractor:
    """Extract structured content from phase outputs."""

    def extract(self, content: str, config: OutputExtractionConfig) -> Optional[Any]:
        """Extract content based on pattern."""
        # Find match
        match = re.search(config.pattern, content, re.DOTALL | re.IGNORECASE)

        if not match:
            if config.required:
                raise ExtractionError(f"Required pattern not found: {config.pattern}")
            return None

        # Extract matched group (first capture group or full match)
        extracted = match.group(1) if match.groups() else match.group(0)
        extracted = extracted.strip()

        # Format based on type
        if config.format == "json":
            try:
                return json.loads(extracted)
            except json.JSONDecodeError as e:
                if config.required:
                    raise ExtractionError(f"Invalid JSON: {e}")
                return extracted

        elif config.format == "code":
            # Extract code blocks (remove markdown)
            code_match = re.search(r'```(?:\w+)?\n(.*?)```', extracted, re.DOTALL)
            return code_match.group(1) if code_match else extracted

        else:  # text
            return extracted

    def has_pattern(self, content: str, pattern: str) -> bool:
        """Check if pattern exists in content."""
        return bool(re.search(pattern, content, re.DOTALL | re.IGNORECASE))


class ExtractionError(Exception):
    """Raised when required extraction fails."""
    pass
```

**Integration in `runner.py`:**

```python
def _execute_phase_internal(self, phase: PhaseConfig, ...):
    # ... existing phase execution ...

    # After phase completes, extract structured content
    if phase.output_extraction:
        extractor = OutputExtractor()

        try:
            extracted = extractor.extract(response_content, phase.output_extraction)

            if extracted is not None:
                # Store in state
                state_key = phase.output_extraction.store_as
                self.echo.state[state_key] = extracted

                console.print(f"{indent}[dim green]✓ Extracted: {state_key}[/dim green]")

                # Log extraction
                log_unified(
                    session_id=self.session_id,
                    node_type="extraction",
                    metadata={
                        "phase": phase.name,
                        "key": state_key,
                        "size": len(str(extracted))
                    }
                )

        except ExtractionError as e:
            # Required extraction failed
            console.print(f"{indent}[red]✗ Extraction failed: {e}[/red]")
            self.echo.add_error(phase.name, "extraction_error", str(e))
```

### Common Patterns

**1. Scratchpad (Think → Execute):**
```json
{
  "phases": [
    {
      "name": "think",
      "instructions": "Analyze deeply. Use <scratchpad> for rough notes.",
      "output_extraction": {
        "pattern": "<scratchpad>(.*?)</scratchpad>",
        "store_as": "thinking",
        "required": true
      }
    },
    {
      "name": "act",
      "instructions": "Your analysis:\n{{ state.thinking }}\n\nNow generate clean output.",
      "context_retention": "output_only"
    }
  ]
}
```

**2. Confidence Score Extraction:**
```json
{
  "name": "evaluate",
  "instructions": "Assess quality. Include: <confidence>0.0-1.0</confidence>",
  "output_extraction": {
    "pattern": "<confidence>([0-9.]+)</confidence>",
    "store_as": "confidence_score",
    "format": "text"
  }
}
```

**3. JSON Data Extraction:**
```json
{
  "name": "structure_data",
  "instructions": "Convert to JSON. Return in <json> tags.",
  "output_extraction": {
    "pattern": "<json>(.*?)</json>",
    "store_as": "structured_data",
    "format": "json",
    "required": true
  }
}
```

**4. Code Generation:**
```json
{
  "name": "generate_code",
  "instructions": "Write Python code in markdown code block.",
  "output_extraction": {
    "pattern": "```python\\n(.*?)```",
    "store_as": "generated_code",
    "format": "code",
    "required": true
  },
  "handoffs": ["test_code"]
}
```

**5. Multi-Step Reasoning (Chain of Thought):**
```json
{
  "phases": [
    {
      "name": "step1_explore",
      "instructions": "List possibilities in <options>",
      "output_extraction": {
        "pattern": "<options>(.*?)</options>",
        "store_as": "options"
      }
    },
    {
      "name": "step2_analyze",
      "instructions": "Options found:\n{{ state.options }}\n\nAnalyze pros/cons in <analysis>",
      "output_extraction": {
        "pattern": "<analysis>(.*?)</analysis>",
        "store_as": "analysis"
      }
    },
    {
      "name": "step3_decide",
      "instructions": "Analysis:\n{{ state.analysis }}\n\nMake decision.",
      "context_retention": "output_only"
    }
  ]
}
```

### Advanced: Multiple Extractions

```python
class OutputExtractionConfig(BaseModel):
    extractions: List[ExtractionRule] = Field(default_factory=list)

class ExtractionRule(BaseModel):
    pattern: str
    store_as: str
    required: bool = False
    format: Literal["text", "json", "code"] = "text"
```

**Usage:**
```json
{
  "output_extraction": {
    "extractions": [
      {
        "pattern": "<reasoning>(.*?)</reasoning>",
        "store_as": "reasoning"
      },
      {
        "pattern": "<confidence>([0-9.]+)</confidence>",
        "store_as": "confidence"
      },
      {
        "pattern": "<recommendation>(.*?)</recommendation>",
        "store_as": "recommendation",
        "required": true
      }
    ]
  }
}
```

### Benefits

- ✅ Cleaner outputs (thinking separated from deliverable)
- ✅ Better reasoning quality (explicit scratchpad)
- ✅ Easier validation (extract confidence scores, etc.)
- ✅ Modular workflows (pass extracted data between phases)
- ✅ Reduces prompt injection (structured tags vs free text)

### Combo with Context Management

**Powerful pattern:**
```json
{
  "name": "research",
  "context_ttl": {"tool_results": 1},
  "context_retention": "output_only",
  "output_extraction": {
    "pattern": "<summary>(.*?)</summary>",
    "store_as": "research_summary"
  },
  "instructions": "Research using tools. Summarize in <summary> tags."
}
```

**Result:**
- Tool results expire after 1 turn (TTL)
- Only final assistant message crosses phase (retention)
- Summary extracted and stored (extraction)
- Next phase gets: `{{ state.research_summary }}` (clean!)

---

## Implementation Priority

**Phase 1: Token Budget (Most Critical)**
- Prevents production crashes
- Foundation for other features
- ~2-3 days implementation

**Phase 2: Tool Caching (High ROI)**
- Massive efficiency gains
- Easy to add after token budget
- ~1-2 days implementation

**Phase 3: Scratchpad Pattern (Quality Improvement)**
- Improves output quality
- Good for complex reasoning tasks
- ~1 day implementation

**Total: ~5-7 days for all three features**

---

## Testing Strategy

### Token Budget Tests
```python
def test_token_budget_sliding_window():
    # Create cascade that exceeds budget
    # Verify pruning works correctly
    # Check preserved messages

def test_token_budget_summarize():
    # Verify summarization triggers
    # Check summary quality
    # Ensure recent context preserved

def test_token_budget_logging():
    # Verify warning at 80%
    # Check logging of pruned messages
```

### Tool Caching Tests
```python
def test_cache_hit():
    # Run same tool twice
    # Verify second call uses cache
    # Check stats updated

def test_cache_expiry():
    # Set short TTL
    # Wait for expiry
    # Verify cache miss

def test_cache_invalidation():
    # Trigger invalidation event
    # Verify affected entries removed
```

### Scratchpad Tests
```python
def test_extraction_basic():
    # Phase with scratchpad
    # Verify extraction to state
    # Check subsequent phase access

def test_extraction_required_fails():
    # Missing required pattern
    # Verify error raised

def test_multi_extraction():
    # Multiple patterns
    # Verify all extracted correctly
```

---

## Configuration Examples

### Production RAG Workflow
```json
{
  "cascade_id": "production_rag",
  "token_budget": {
    "max_total": 150000,
    "reserve_for_output": 8000,
    "strategy": "summarize",
    "warning_threshold": 0.8
  },
  "tool_caching": {
    "enabled": true,
    "tools": {
      "sql_search": {"enabled": true, "ttl": 7200, "key": "query"},
      "sql_query": {"enabled": true, "ttl": 300, "key": "sql_hash"}
    }
  },
  "phases": [
    {
      "name": "research",
      "context_ttl": {"tool_results": 1},
      "context_retention": "output_only",
      "output_extraction": {
        "pattern": "<findings>(.*?)</findings>",
        "store_as": "research"
      },
      "tackle": ["sql_search"],
      "instructions": "Research. Summarize in <findings> tags."
    }
  ]
}
```

### Complex Reasoning Workflow
```json
{
  "cascade_id": "complex_reasoning",
  "token_budget": {
    "max_total": 100000,
    "strategy": "sliding_window"
  },
  "phases": [
    {
      "name": "explore",
      "output_extraction": {
        "pattern": "<options>(.*?)</options>",
        "store_as": "options"
      }
    },
    {
      "name": "analyze",
      "output_extraction": {
        "extractions": [
          {"pattern": "<pros>(.*?)</pros>", "store_as": "pros"},
          {"pattern": "<cons>(.*?)</cons>", "store_as": "cons"},
          {"pattern": "<confidence>([0-9.]+)</confidence>", "store_as": "confidence"}
        ]
      },
      "instructions": "Options: {{ state.options }}\n\nAnalyze in structured tags."
    },
    {
      "name": "decide",
      "context_retention": "output_only",
      "instructions": "Confidence: {{ state.confidence }}\nPros: {{ state.pros }}\nCons: {{ state.cons }}\n\nDecide."
    }
  ]
}
```

---

## Migration Path

**For existing cascades:**
1. All features are opt-in (backwards compatible)
2. No changes required unless explicitly configured
3. Can adopt incrementally:
   - Start with token_budget (safety net)
   - Add tool_caching (performance)
   - Use scratchpad for new workflows

**Recommended adoption:**
```json
{
  "token_budget": {
    "max_total": 120000,
    "strategy": "fail"
  }
}
```
Start with "fail" strategy to understand token usage, then switch to "sliding_window" or "summarize" once comfortable.

---

## Questions to Answer Before Implementation

1. **Token counting library:** Use tiktoken (OpenAI) or sentencepiece (universal)?
   - Recommendation: tiktoken (better model coverage, actively maintained)

2. **Cache storage:** Memory-only or add Redis/SQLite support?
   - Recommendation: Start with memory, add Redis later for distributed systems

3. **Scratchpad tags:** Fixed tags or user-configurable?
   - Recommendation: User-configurable patterns (more flexible)

4. **Token budget per-phase overrides:** Needed?
   - Recommendation: Yes, some phases need more budget than others

5. **Cache persistence:** Should cache survive session restarts?
   - Recommendation: Optional, useful for development workflows

---

## Success Metrics

**Token Budget:**
- ✅ Zero crashes from context limits
- ✅ >80% of cascades stay within budget without pruning
- ✅ Token usage visible in UI/logs

**Tool Caching:**
- ✅ 40-60% cache hit rate for RAG workflows
- ✅ 30-50% reduction in API calls
- ✅ 20-30% faster execution time

**Scratchpad:**
- ✅ Cleaner final outputs (subjective, but observable)
- ✅ Easier debugging (reasoning visible in state)
- ✅ Better evaluation scores (compare with/without scratchpad)

---

## Future Extensions

**Token Budget:**
- Adaptive budgets (learn optimal size per cascade)
- Budget "loans" (borrow from future phases)
- Visual budget planner in UI

**Tool Caching:**
- Distributed cache (Redis)
- Cache warming (preload common queries)
- Smart invalidation (detect schema changes)

**Scratchpad:**
- Multi-modal scratchpad (images, tables)
- Scratchpad templates (pre-structured thinking)
- Automatic scratchpad generation (framework suggests structure)
