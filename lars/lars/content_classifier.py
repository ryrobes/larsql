"""
Content Classifier - Semantic classification of message content

Classifies content into types for filtering and specialized rendering:
- text: Plain text without special formatting
- markdown: Text with markdown syntax (headers, bold, lists, code blocks)
- json: Structured JSON data (objects/arrays)
- table: Tabular data with rows/columns
- image: Content with associated images
- chart: Visualization data (plotly, etc.)
- tool_call:<tool_name>: LLM tool invocation (e.g., tool_call:request_decision)
- error: Error message

Tool calls are hierarchical - the base type is 'tool_call' with sub-types based on
the tool name. This enables both broad filtering (all tool calls) and specific
filtering (just gen-ui decision requests).
"""

import json
import re
from typing import Any, Dict, List, Optional, Union


# Known tool names for special handling
KNOWN_TOOLS = {
    # Gen-UI / Human-in-the-loop
    'request_decision',
    'ask_human',
    'ask_human_custom',
    'request_input',

    # Data tools
    'sql_data',
    'python_data',
    'js_data',
    'clojure_data',
    'lars_data',

    # Visualization
    'create_chart',
    'plotly_chart',

    # System
    'route_to',
    'spawn_cascade',
    'map_cascade',
    'set_state',

    # Browser automation
    'rabbitize_click',
    'rabbitize_navigate',
    'rabbitize_type',
    'rabbitize_screenshot',

    # Shell/code
    'linux_shell',
    'run_code',

    # Voice
    'say',
    'listen',
    'transcribe_audio',
}


def classify_content(
    content: Any = None,
    metadata: Optional[Dict] = None,
    images: Optional[List[str]] = None,
    videos: Optional[List[str]] = None,
    tool_calls: Optional[List[Dict]] = None,
    role: Optional[str] = None,
) -> str:
    """
    Classify message content into a semantic type.

    Priority order:
    1. Explicit tool_calls parameter (highest signal)
    2. Videos (has_videos or videos array)
    3. Images (has_images or images array)
    4. Metadata type hints (plotly, table, etc.)
    5. Content structure analysis
    6. Text pattern analysis (markdown vs plain text)

    Args:
        content: The message content (string, dict, list, or None)
        metadata: Optional metadata dict with type hints
        images: Optional list of image paths/URLs
        videos: Optional list of video paths/URLs
        tool_calls: Optional list of tool call dicts
        role: Optional message role (user, assistant, system, tool)

    Returns:
        Content type string (e.g., 'text', 'markdown', 'video', 'tool_call:request_decision')
    """
    # 1. Check for explicit tool calls
    if tool_calls and len(tool_calls) > 0:
        tool_type = _extract_tool_type(tool_calls)
        if tool_type:
            return tool_type

    # 2. Check for videos (before images - video takes precedence)
    if videos and len(videos) > 0:
        return 'video'

    # Check metadata for videos
    if metadata:
        meta_videos = metadata.get('videos')
        if meta_videos and len(meta_videos) > 0:
            return 'video'

    # 3. Check for images
    if images and len(images) > 0:
        return 'image'

    # Check metadata for images
    if metadata:
        meta_images = metadata.get('images')
        if meta_images and len(meta_images) > 0:
            return 'image'

    # 5. Check metadata type hints
    if metadata:
        meta_type = metadata.get('type')
        if meta_type == 'plotly':
            return 'chart'
        if meta_type == 'video':
            return 'video'
        if meta_type == 'image':
            return 'image'
        if meta_type == 'error':
            return 'error'

        # Check for table structure in metadata
        if metadata.get('rows') is not None and metadata.get('columns') is not None:
            return 'table'

    # 4. Analyze content structure
    if content is None:
        return 'text'

    # Parse JSON string if needed
    parsed_content = content
    if isinstance(content, str):
        parsed_content = _try_parse_json(content)

    # Check if parsed content is structured
    if isinstance(parsed_content, dict):
        content_type = _classify_dict_content(parsed_content)
        if content_type:
            return content_type

    # 5. Analyze text patterns
    if isinstance(content, str):
        return _classify_text_content(content)

    # Default for other types (lists, numbers, etc.)
    if isinstance(content, (list, dict)):
        return 'json'

    return 'text'


def _extract_tool_type(tool_calls: List[Dict]) -> Optional[str]:
    """
    Extract tool type from tool_calls array.

    Returns 'tool_call:<tool_name>' or just 'tool_call' if tool name unknown.
    """
    if not tool_calls:
        return None

    # Get the first tool call (most recent/relevant)
    first_call = tool_calls[0] if isinstance(tool_calls, list) else tool_calls

    if isinstance(first_call, dict):
        # Standard format: {"name": "tool_name", "arguments": {...}}
        tool_name = first_call.get('name') or first_call.get('tool') or first_call.get('function', {}).get('name')

        if tool_name:
            # Normalize tool name
            tool_name = str(tool_name).strip().lower()
            return f'tool_call:{tool_name}'

    return 'tool_call'


def _try_parse_json(text: str) -> Any:
    """
    Try to parse JSON from text, handling embedded JSON in markdown code blocks.

    Returns parsed JSON or original text if parsing fails.
    """
    if not text or not isinstance(text, str):
        return text

    text = text.strip()

    # Try direct JSON parse first
    if text.startswith('{') or text.startswith('['):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

    # Try extracting from markdown code block
    # Matches: ```json\n{...}\n``` or ```\n{...}\n```
    json_block_match = re.search(
        r'```(?:json)?\s*\n?(\{[\s\S]*?\}|\[[\s\S]*?\])\s*\n?```',
        text,
        re.IGNORECASE
    )

    if json_block_match:
        try:
            return json.loads(json_block_match.group(1))
        except json.JSONDecodeError:
            pass

    return text


def _extract_tool_call_from_text(text: str) -> Optional[Dict]:
    """
    Extract a tool call JSON object from text content.

    Handles:
    - Pure JSON code blocks: ```json\n{"tool": "...", "arguments": {...}}\n```
    - Mixed content: "Some text...\n\n```json\n{"tool": ...}\n```"
    - Raw JSON (no code block): {"tool": "...", "arguments": {...}}

    Returns the parsed tool call dict or None if not found.
    """
    if not text or not isinstance(text, str):
        return None

    # Quick check - must have both "tool" and "arguments"
    if '"tool"' not in text or '"arguments"' not in text:
        return None

    # Strategy 1: Look for JSON code blocks containing tool calls
    # This regex finds ```json ... ``` blocks and extracts the JSON
    code_block_pattern = r'```(?:json)?\s*\n?(\{[^`]*"tool"[^`]*"arguments"[^`]*\})\s*\n?```'

    for match in re.finditer(code_block_pattern, text, re.IGNORECASE | re.DOTALL):
        json_str = match.group(1).strip()
        try:
            parsed = json.loads(json_str)
            if isinstance(parsed, dict) and 'tool' in parsed and 'arguments' in parsed:
                return parsed
        except json.JSONDecodeError:
            # Try to fix common JSON issues (trailing commas, etc.)
            continue

    # Strategy 2: Look for raw JSON object with tool/arguments pattern
    # Find JSON-like content starting with { and containing tool/arguments
    raw_json_pattern = r'(\{[^{}]*"tool"\s*:\s*"[^"]+"\s*,\s*"arguments"\s*:\s*\{[^{}]*(?:\{[^{}]*\}[^{}]*)?\}\s*\})'

    for match in re.finditer(raw_json_pattern, text, re.DOTALL):
        json_str = match.group(1).strip()
        try:
            parsed = json.loads(json_str)
            if isinstance(parsed, dict) and 'tool' in parsed:
                return parsed
        except json.JSONDecodeError:
            continue

    # Strategy 3: Greedy extraction - find { ... } that contains tool/arguments
    # and try to parse balanced braces
    brace_start = text.find('{"tool"')
    if brace_start == -1:
        brace_start = text.find('{ "tool"')

    if brace_start != -1:
        # Count braces to find matching close
        depth = 0
        end_pos = brace_start
        for i, char in enumerate(text[brace_start:], brace_start):
            if char == '{':
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0:
                    end_pos = i + 1
                    break

        if end_pos > brace_start:
            json_str = text[brace_start:end_pos]
            try:
                parsed = json.loads(json_str)
                if isinstance(parsed, dict) and 'tool' in parsed:
                    return parsed
            except json.JSONDecodeError:
                pass

    return None


def _classify_dict_content(content: Dict) -> Optional[str]:
    """
    Classify structured dict content.

    Returns content type or None if should fall through to text analysis.
    """
    # Tool call format: {"tool": "name", "arguments": {...}}
    if 'tool' in content and 'arguments' in content:
        tool_name = content.get('tool', 'unknown')
        return f'tool_call:{tool_name}'

    # Function call format: {"name": "func", "arguments": {...}}
    if 'name' in content and 'arguments' in content:
        tool_name = content.get('name', 'unknown')
        return f'tool_call:{tool_name}'

    # OpenAI function call format
    if 'function' in content and isinstance(content.get('function'), dict):
        func = content['function']
        if 'name' in func:
            return f'tool_call:{func["name"]}'

    # Plotly/chart data
    if content.get('type') == 'plotly' or 'data' in content and 'layout' in content:
        return 'chart'

    # Table data
    if 'rows' in content and 'columns' in content:
        return 'table'

    # Error format
    if content.get('error') or content.get('type') == 'error':
        return 'error'

    # Video reference
    if content.get('type') == 'video' or content.get('url', '').endswith(('.mp4', '.webm', '.mov', '.avi', '.mkv')):
        return 'video'

    # Image reference
    if content.get('type') == 'image' or content.get('url', '').endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
        return 'image'

    # Generic JSON object
    return 'json'


def _classify_text_content(text: str) -> str:
    """
    Classify text content based on patterns.

    Detects:
    - Embedded tool calls in JSON code blocks (highest priority)
    - Error patterns
    - Markdown syntax (headers, bold, lists, code blocks)
    """
    if not text:
        return 'text'

    # Check for embedded tool call JSON FIRST (highest priority)
    # This handles: ```json\n{"tool": "...", "arguments": {...}}\n```
    # as well as mixed content like "Let me search...\n\n```json\n{...}\n```"
    tool_call = _extract_tool_call_from_text(text)
    if tool_call:
        tool_name = tool_call.get('tool', 'unknown')
        return f'tool_call:{tool_name}'

    # Check for error patterns
    error_patterns = [
        r'^error:',
        r'^Error:',
        r'^ERROR:',
        r'exception:',
        r'Exception:',
        r'Traceback \(most recent call last\):',
        r'^\s*raise\s+',
    ]
    for pattern in error_patterns:
        if re.search(pattern, text, re.MULTILINE | re.IGNORECASE):
            return 'error'

    # Check for markdown patterns
    markdown_patterns = [
        r'^#{1,6}\s+',           # Headers: # Title
        r'\*\*[^*]+\*\*',        # Bold: **text**
        r'\*[^*]+\*',            # Italic: *text*
        r'`[^`]+`',              # Inline code: `code`
        r'^```',                 # Code block start
        r'^\s*[-*+]\s+',         # Unordered list: - item
        r'^\s*\d+\.\s+',         # Ordered list: 1. item
        r'^\s*>\s+',             # Blockquote: > quote
        r'\[.+\]\(.+\)',         # Link: [text](url)
        r'!\[.+\]\(.+\)',        # Image: ![alt](url)
        r'^\s*\|.+\|',           # Table: | col | col |
        r'^---+$',               # Horizontal rule
    ]

    markdown_score = 0
    for pattern in markdown_patterns:
        if re.search(pattern, text, re.MULTILINE):
            markdown_score += 1

    # If 2+ markdown patterns found, classify as markdown
    if markdown_score >= 2:
        return 'markdown'

    # Single header at start is also markdown
    if re.match(r'^#{1,6}\s+', text.strip()):
        return 'markdown'

    return 'text'


def get_base_content_type(content_type: str) -> str:
    """
    Get the base content type (without sub-type).

    Example: 'tool_call:request_decision' -> 'tool_call'
    """
    if ':' in content_type:
        return content_type.split(':')[0]
    return content_type


def get_content_type_subtype(content_type: str) -> Optional[str]:
    """
    Get the sub-type from a content type.

    Example: 'tool_call:request_decision' -> 'request_decision'
    """
    if ':' in content_type:
        return content_type.split(':', 1)[1]
    return None


# All possible base content types
CONTENT_TYPES = [
    'text',
    'markdown',
    'json',
    'table',
    'image',
    'video',
    'chart',
    'tool_call',
    'error',
]


def is_valid_content_type(content_type: str) -> bool:
    """Check if a content type (or base type) is valid."""
    base = get_base_content_type(content_type)
    return base in CONTENT_TYPES
