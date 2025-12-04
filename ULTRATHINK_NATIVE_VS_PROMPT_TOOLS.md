# ULTRATHINK: Native Tool Calling vs Prompt-Based Tools

## Your Insight

> "We just want it to return a structured command/code that we can use on our local tools. If we are trying to make legit 'Tool' calls on the agents, then that is a problem, since - yes, all the providers have their own weird calling and defining of tools. But tools calling is just prompt generation anyways, which we are doing here."

**You're absolutely correct!** This is a fundamental architectural issue.

---

## Current Architecture (Native Tool Calling)

### How It Works Now

**Line 1548-1554 in runner.py:**
```python
agent = Agent(
    model=phase_model,
    system_prompt="",
    tools=tools_schema,  # ← Passes tool schemas to LLM provider!
    base_url=self.base_url,
    api_key=self.api_key
)
```

**agent.py lines 63-65:**
```python
if self.tools:
    args["tools"] = self.tools
    args["tool_choice"] = "auto"
```

**What happens:**
1. Windlass extracts Python function signatures → OpenAI-compatible JSON schemas
2. Passes schemas to LiteLLM via `tools=` parameter
3. LiteLLM sends to provider (OpenRouter/Anthropic/OpenAI/Gemini)
4. **Provider's NATIVE tool calling is used**
5. Provider returns tool calls in provider-specific format
6. LiteLLM translates back to standard format
7. Windlass calls local Python functions
8. Results sent back as `role="tool"` messages

### The Problems with This Approach

**Provider-specific quirks:**
- ✅ OpenAI: Standard format, works fine
- ✅ Anthropic: Requires role="user" with tool_result blocks (LiteLLM handles)
- ❌ **Gemini: Requires `thought_signature` field** (LiteLLM doesn't handle)
- ❌ **Each provider has unique requirements**
- ❌ **Message format differences** (role="tool" vs role="user")
- ❌ **Limited model support** (older models don't have tool calling)

**As you said:** This creates unnecessary complexity because tool calling is really just structured output generation anyway!

---

## Alternative Architecture (Prompt-Based Tools)

### How It Should Work

**Instead of passing `tools=` to the API:**

1. **Describe tools in system prompt:**
   ```
   You have access to these tools:

   **run_code**
   - Description: Executes Python code
   - Parameters:
     - code (str): The Python code to execute
     - language (str, optional): Programming language (default: python)
   - Usage: Return JSON: {"tool": "run_code", "arguments": {"code": "print('hello')"}}

   **set_state**
   - Description: Store a value in session state
   ...
   ```

2. **Agent returns plain text/JSON:**
   ```
   I'll run the code now:
   {"tool": "run_code", "arguments": {"code": "print('hello')"}}
   ```

3. **Windlass parses the output:**
   - Extract JSON from agent response
   - Look for `{"tool": "...", "arguments": {...}}`
   - Call local Python function
   - No provider tool calling involved!

4. **Tool result added as user message:**
   ```
   Tool Result (run_code):
   hello
   ```

### Benefits

✅ **Works with ANY model** (even those without native tool calling)
✅ **No provider-specific quirks** (Gemini thought_signature, Anthropic format, etc.)
✅ **Simpler message format** (just user/assistant, no role="tool")
✅ **More transparent** (can see tool calls in plain text)
✅ **Better for smaller/older models** (don't need tool calling support)
✅ **Easier to debug** (tool requests visible in chat)

### Drawbacks

❌ **Slightly more tokens** (tool schemas in prompt vs separate parameter)
❌ **Parsing required** (extract JSON from text vs structured response)
❌ **Less reliable** (agent might not format JSON correctly)
❌ **Native tool calling is more "official"** when it works

---

## The Real Issue

**Windlass is using NATIVE tool calling but treating it like it's provider-agnostic.**

The framework:
1. Generates OpenAI-format tool schemas ✅
2. Passes to LiteLLM ✅
3. **Assumes LiteLLM handles all provider differences** ❌ (it doesn't fully!)
4. Uses `role="tool"` format ✅
5. **Providers reject with quirks** ❌ (Gemini thought_signature, etc.)

---

## Two Paths Forward

### Option A: Fix Native Tool Calling (Current Approach)

**Keep using provider native tools, but handle quirks:**

1. Add provider detection
2. Add Gemini-specific handling (thought_signature)
3. Add Anthropic-specific handling (if needed)
4. Keep using `tools=` parameter
5. Handle all edge cases

**Pros:**
- More "official" use of LLM capabilities
- Structured responses
- May be more reliable for supported models

**Cons:**
- Ongoing maintenance for each provider
- Limited to models with tool calling
- Complex error handling
- Current bugs with message pollution

###Option B: Switch to Prompt-Based Tools (Simpler)

**Remove `tools=` parameter, use prompt engineering:**

1. Generate tool descriptions as text
2. Add to system prompt
3. Agent returns text with JSON
4. Parse JSON from response
5. Call Python functions
6. Add result as user message

**Pros:**
- Works with ANY model (no tool calling required)
- No provider quirks
- Simpler message format
- More transparent/debuggable

**Cons:**
- Slightly more tokens
- Need JSON parsing
- Less "official"

---

## Recommended Solution

**I suggest Option B (Prompt-Based)** for these reasons:

1. **Windlass philosophy:** Declarative, provider-agnostic
2. **Self-evolving:** Works with any model (even older/cheaper ones)
3. **Simpler:** No provider quirks to handle
4. **Your observation:** "Tool calling is just prompt generation anyway"

### Implementation

Add a config option:

```python
# cascade.py
class PhaseConfig(BaseModel):
    ...
    use_native_tools: bool = True  # Default to current behavior
```

```python
# runner.py
if phase.use_native_tools:
    # Current: Pass tools to API
    agent = Agent(model=..., tools=tools_schema, ...)
else:
    # New: Prompt-based tools
    tool_prompt = _generate_tool_prompt(tool_map)
    rendered_instructions += f"\n\n{tool_prompt}"
    agent = Agent(model=..., tools=None, ...)
```

Then parse responses for:
```python
# Look for JSON in response
import re
json_match = re.search(r'\{["\']tool["\']:\s*["\'](\w+)["\'].*\}', response, re.DOTALL)
if json_match:
    tool_data = json.loads(json_match.group(0))
    tool_name = tool_data["tool"]
    tool_args = tool_data.get("arguments", {})
    # Call local function
    result = tool_map[tool_name](**tool_args)
```

---

## Current Bugs Summary

**The immediate bugs we found:**

1. ✅ FIXED: `echo.add_history()` mutates dicts → pollutes context_messages
2. ✅ FIXED: Messages sent with extra fields (trace_id, metadata)
3. ✅ FIXED: Empty messages added to history
4. ❌ **STILL BROKEN: Gemini requires thought_signature for native tools**

**The architectural issue:**

Using native tool calling creates provider-specific problems that are fundamentally at odds with Windlass's declarative, provider-agnostic philosophy.

---

## My Recommendation

**Short term:**
- Use Claude or OpenAI models (avoid Gemini for now)
- The message pollution bugs are fixed
- Native tool calling will work for most providers

**Long term:**
- Add `use_native_tools: false` option for prompt-based tools
- Make it the default for maximum compatibility
- Keep native as option for providers that handle it well

**Your instinct is correct:** Prompt-based tool calling is simpler, more portable, and aligns better with Windlass's philosophy!

---

## Want Me To Implement Prompt-Based Tools?

I can add:
1. `use_native_tools` config option in PhaseConfig
2. Tool prompt generation (describe tools in system prompt)
3. JSON parsing from agent responses
4. Fallback to native for providers that prefer it

This would make Windlass truly provider-agnostic! 🌊

What do you think?
