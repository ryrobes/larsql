"""
Declarative Tool Definitions (.tool.json / .tool.yaml)

Allows users to define tools declaratively in JSON or YAML without writing Python code.
Supports shell commands, HTTP APIs, Python imports, and composite pipelines.

Example .tool.json file:
{
  "tool_id": "search_code",
  "description": "Search codebase with ripgrep",
  "inputs_schema": {
    "pattern": "Search pattern (regex)",
    "path": "Directory to search"
  },
  "type": "shell",
  "command": "rg --json '{{ pattern }}' {{ path | default('.') }}",
  "timeout": 30
}

Example .tool.yaml file:
tool_id: search_code
description: Search codebase with ripgrep
inputs_schema:
  pattern: Search pattern (regex)
  path: Directory to search
type: shell
command: "rg --json '{{ pattern }}' {{ path | default('.') }}"
timeout: 30
"""

import os
import json
import glob
import subprocess
import inspect
import importlib
from typing import Any, Dict, List, Optional, Literal, Union
from pydantic import BaseModel, Field, field_validator
from jinja2 import Template, Environment, BaseLoader


# ============================================================================
# Schema Definitions
# ============================================================================

class CompositeStep(BaseModel):
    """A single step in a composite tool pipeline."""
    tool: str = Field(..., description="Tool ID to invoke")
    args: Dict[str, Any] = Field(default_factory=dict, description="Arguments (Jinja2 templated)")
    condition: Optional[str] = Field(None, description="Jinja2 condition to run this step")


class ToolDefinition(BaseModel):
    """
    Schema for .tool.json declarative tool definitions.

    Supports six tool types:
    - shell: Execute a shell command
    - http: Make an HTTP request
    - python: Call a Python function by import path
    - composite: Chain multiple tools together
    - gradio: Call a Gradio endpoint (HuggingFace Spaces or direct URL)
    - local_model: Run a local HuggingFace transformers model
    """
    tool_id: str = Field(..., description="Unique identifier for the tool")
    description: str = Field(..., description="Description shown to LLM")
    inputs_schema: Dict[str, str] = Field(default_factory=dict, description="Parameter name -> description mapping")

    type: Literal["shell", "http", "python", "composite", "gradio", "local_model"] = Field(..., description="Tool execution type")

    # Shell options
    command: Optional[str] = Field(None, description="Shell command (Jinja2 template)")
    working_dir: Optional[str] = Field(None, description="Working directory (Jinja2 template)")
    timeout: int = Field(30, description="Timeout in seconds")
    sandbox: bool = Field(True, description="Run in Docker sandbox if available")

    # HTTP options
    method: Optional[str] = Field(None, description="HTTP method (GET, POST, etc.)")
    url: Optional[str] = Field(None, description="URL (Jinja2 template)")
    headers: Optional[Dict[str, str]] = Field(None, description="HTTP headers (Jinja2 templated values)")
    body: Optional[Any] = Field(None, description="Request body (Jinja2 template or object)")
    response_jq: Optional[str] = Field(None, description="jq expression to extract from response")

    # Python options
    import_path: Optional[str] = Field(None, description="Python import path (e.g., 'mymodule.tools.my_func')")

    # Composite options
    steps: Optional[List[CompositeStep]] = Field(None, description="Pipeline steps")

    # Gradio options (HuggingFace Spaces)
    space: Optional[str] = Field(None, description="HuggingFace Space ID (e.g., 'user/space-name')")
    gradio_url: Optional[str] = Field(None, description="Direct Gradio app URL (alternative to space)")
    api_name: Optional[str] = Field(None, description="Gradio endpoint name (e.g., '/predict')")
    introspect: bool = Field(False, description="Auto-fetch inputs_schema from Gradio API if not provided")

    # Local model options (HuggingFace transformers)
    model_id: Optional[str] = Field(None, description="HuggingFace model ID (e.g., 'distilbert/distilbert-base-uncased-finetuned-sst-2-english')")
    task: Optional[str] = Field(None, description="Pipeline task (e.g., 'text-classification', 'ner', 'summarization')")
    device: Optional[str] = Field(None, description="Device to use: 'auto', 'cuda', 'mps', 'cpu' (default: auto)")
    model_kwargs: Optional[Dict[str, Any]] = Field(None, description="Additional kwargs for model loading")
    pipeline_kwargs: Optional[Dict[str, Any]] = Field(None, description="Additional kwargs for pipeline execution")

    # Output processing
    output_transform: Optional[Literal["json", "text", "lines"]] = Field(None, description="How to transform output")
    error_pattern: Optional[str] = Field(None, description="Regex pattern to detect errors in output")

    @field_validator('type')
    @classmethod
    def validate_type_requirements(cls, v, info):
        return v

    def validate_complete(self):
        """Validate that required fields for the type are present."""
        if self.type == "shell" and not self.command:
            raise ValueError(f"Tool '{self.tool_id}': shell type requires 'command' field")
        if self.type == "http" and (not self.url or not self.method):
            raise ValueError(f"Tool '{self.tool_id}': http type requires 'url' and 'method' fields")
        if self.type == "python" and not self.import_path:
            raise ValueError(f"Tool '{self.tool_id}': python type requires 'import_path' field")
        if self.type == "composite" and not self.steps:
            raise ValueError(f"Tool '{self.tool_id}': composite type requires 'steps' field")
        if self.type == "gradio" and not self.space and not self.gradio_url:
            raise ValueError(f"Tool '{self.tool_id}': gradio type requires 'space' or 'gradio_url' field")
        if self.type == "local_model" and not self.model_id:
            raise ValueError(f"Tool '{self.tool_id}': local_model type requires 'model_id' field")
        if self.type == "local_model" and not self.task:
            raise ValueError(f"Tool '{self.tool_id}': local_model type requires 'task' field")


# ============================================================================
# Jinja2 Template Rendering
# ============================================================================

def create_jinja_env() -> Environment:
    """Create Jinja2 environment with useful filters."""
    env = Environment(loader=BaseLoader())

    # Add useful filters
    env.filters['json'] = json.dumps
    env.filters['quote'] = lambda s: f"'{s}'" if s else "''"
    env.filters['default'] = lambda s, d: s if s else d

    return env


def render_template(template_str: str, context: Dict[str, Any]) -> str:
    """Render a Jinja2 template string with the given context."""
    if not template_str:
        return ""

    env = create_jinja_env()
    template = env.from_string(template_str)
    return template.render(**context)


def render_dict_values(d: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively render Jinja2 templates in dict values."""
    result = {}
    for key, value in d.items():
        if isinstance(value, str):
            result[key] = render_template(value, context)
        elif isinstance(value, dict):
            result[key] = render_dict_values(value, context)
        else:
            result[key] = value
    return result


# ============================================================================
# Tool Executors
# ============================================================================

def execute_shell_tool(tool: ToolDefinition, inputs: Dict[str, Any], context: Dict[str, Any]) -> str:
    """Execute a shell-type tool."""
    # Build template context
    ctx = {
        "input": inputs,
        "env": dict(os.environ),
        **context
    }

    # Render command
    command = render_template(tool.command, ctx)

    # Render working directory
    cwd = None
    if tool.working_dir:
        cwd = render_template(tool.working_dir, ctx)

    # Check if we should use Docker sandbox
    use_sandbox = tool.sandbox

    if use_sandbox:
        # Try to use the existing linux_shell tool for sandboxed execution
        try:
            from .traits.extras import linux_shell
            result = linux_shell(command)
            return result
        except Exception as e:
            # Fall back to local execution if sandbox not available
            pass

    # Local execution (non-sandboxed or sandbox unavailable)
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=tool.timeout,
            cwd=cwd
        )

        output = result.stdout
        if result.returncode != 0 and result.stderr:
            output += f"\n[stderr]: {result.stderr}"

        # Apply output transform
        if tool.output_transform == "json":
            try:
                parsed = json.loads(output)
                output = json.dumps(parsed, indent=2)
            except json.JSONDecodeError:
                pass
        elif tool.output_transform == "lines":
            output = output.strip()

        # Check for error pattern
        if tool.error_pattern:
            import re
            if re.search(tool.error_pattern, output):
                return f"[ERROR] Tool detected error in output:\n{output}"

        return output

    except subprocess.TimeoutExpired:
        return f"[ERROR] Command timed out after {tool.timeout} seconds"
    except Exception as e:
        return f"[ERROR] Shell execution failed: {str(e)}"


def execute_http_tool(tool: ToolDefinition, inputs: Dict[str, Any], context: Dict[str, Any]) -> str:
    """Execute an HTTP-type tool."""
    import requests

    # Build template context
    ctx = {
        "input": inputs,
        "env": dict(os.environ),
        **context
    }

    # Render URL
    url = render_template(tool.url, ctx)

    # Render headers
    headers = {}
    if tool.headers:
        headers = render_dict_values(tool.headers, ctx)

    # Render body
    body = None
    if tool.body:
        if isinstance(tool.body, str):
            body = render_template(tool.body, ctx)
        elif isinstance(tool.body, dict):
            body = render_dict_values(tool.body, ctx)
        else:
            body = tool.body

    try:
        # Make request
        method = tool.method.upper()

        if method == "GET":
            resp = requests.get(url, headers=headers, timeout=tool.timeout)
        elif method == "POST":
            resp = requests.post(url, headers=headers, json=body if isinstance(body, dict) else None,
                               data=body if isinstance(body, str) else None, timeout=tool.timeout)
        elif method == "PUT":
            resp = requests.put(url, headers=headers, json=body if isinstance(body, dict) else None,
                              data=body if isinstance(body, str) else None, timeout=tool.timeout)
        elif method == "DELETE":
            resp = requests.delete(url, headers=headers, timeout=tool.timeout)
        else:
            return f"[ERROR] Unsupported HTTP method: {method}"

        # Extract response
        try:
            result = resp.json()
        except:
            result = resp.text

        # Apply jq-style extraction if specified
        if tool.response_jq and isinstance(result, (dict, list)):
            result = extract_jq_path(result, tool.response_jq)

        # Format output
        if isinstance(result, (dict, list)):
            return json.dumps(result, indent=2)
        return str(result)

    except requests.Timeout:
        return f"[ERROR] HTTP request timed out after {tool.timeout} seconds"
    except Exception as e:
        return f"[ERROR] HTTP request failed: {str(e)}"


def extract_jq_path(data: Any, jq_path: str) -> Any:
    """
    Simple jq-style path extraction.
    Supports: .field, .field.subfield, .[0], .field[0].subfield
    """
    if not jq_path or jq_path == ".":
        return data

    # Remove leading dot
    path = jq_path.lstrip(".")

    current = data
    parts = []

    # Parse path parts
    i = 0
    while i < len(path):
        if path[i] == "[":
            # Array index
            end = path.index("]", i)
            index = int(path[i+1:end])
            parts.append(("index", index))
            i = end + 1
        elif path[i] == ".":
            i += 1
        else:
            # Field name
            end = i
            while end < len(path) and path[end] not in ".[":
                end += 1
            parts.append(("field", path[i:end]))
            i = end

    # Navigate
    for part_type, part_value in parts:
        if part_type == "field":
            if isinstance(current, dict):
                current = current.get(part_value)
            else:
                return None
        elif part_type == "index":
            if isinstance(current, list) and len(current) > part_value:
                current = current[part_value]
            else:
                return None

    return current


def execute_python_tool(tool: ToolDefinition, inputs: Dict[str, Any], context: Dict[str, Any]) -> str:
    """Execute a Python-type tool by importing and calling the function."""
    try:
        # Parse import path
        parts = tool.import_path.rsplit(".", 1)
        if len(parts) != 2:
            return f"[ERROR] Invalid import_path: {tool.import_path} (expected 'module.path.function')"

        module_path, func_name = parts

        # Import module
        module = importlib.import_module(module_path)

        # Get function
        func = getattr(module, func_name)

        # Call function with inputs
        result = func(**inputs)

        # Format output
        if isinstance(result, (dict, list)):
            return json.dumps(result, indent=2)
        return str(result)

    except ImportError as e:
        return f"[ERROR] Failed to import {tool.import_path}: {str(e)}"
    except AttributeError as e:
        return f"[ERROR] Function not found in module: {str(e)}"
    except Exception as e:
        return f"[ERROR] Python execution failed: {str(e)}"


def execute_composite_tool(tool: ToolDefinition, inputs: Dict[str, Any], context: Dict[str, Any]) -> str:
    """Execute a composite-type tool by running steps in sequence."""
    from .trait_registry import get_trait

    results = []
    step_outputs = []

    # Build initial context
    ctx = {
        "input": inputs,
        "env": dict(os.environ),
        "steps": step_outputs,
        **context
    }

    for i, step in enumerate(tool.steps):
        # Check condition
        if step.condition:
            condition_result = render_template(step.condition, ctx)
            # Evaluate as Python boolean
            if condition_result.lower() in ("false", "0", "none", ""):
                step_outputs.append({"skipped": True, "tool": step.tool})
                continue

        # Get the tool to execute
        step_tool = get_trait(step.tool)
        if not step_tool:
            # Try to find it in declarative tools
            step_tool = get_declarative_tool_executor(step.tool)

        if not step_tool:
            error_msg = f"[ERROR] Step {i+1}: Tool '{step.tool}' not found"
            step_outputs.append({"error": error_msg, "tool": step.tool})
            results.append(error_msg)
            continue

        # Render step arguments
        step_args = {}
        for arg_name, arg_value in step.args.items():
            if isinstance(arg_value, str):
                step_args[arg_name] = render_template(arg_value, ctx)
            else:
                step_args[arg_name] = arg_value

        # Execute step
        try:
            result = step_tool(**step_args)
            step_outputs.append({
                "tool": step.tool,
                "result": result,
                "success": True,
                "exit_code": 0  # Assume success if no exception
            })
            results.append(f"[Step {i+1}: {step.tool}]\n{result}")

            # Update context with latest step result
            ctx["steps"] = step_outputs

        except Exception as e:
            error_msg = f"[ERROR] Step {i+1} ({step.tool}): {str(e)}"
            step_outputs.append({
                "tool": step.tool,
                "error": str(e),
                "success": False,
                "exit_code": 1
            })
            results.append(error_msg)

    return "\n\n".join(results)


def execute_gradio_tool(tool: ToolDefinition, inputs: Dict[str, Any], context: Dict[str, Any]) -> str:
    """
    Execute a gradio-type tool by calling a HuggingFace Space or direct Gradio URL.

    Supports:
    - HuggingFace Spaces (public and private with HF_TOKEN)
    - Direct Gradio app URLs
    - Multi-modal outputs (images, audio files)
    """
    try:
        from gradio_client import Client
    except ImportError:
        return "[ERROR] gradio_client package not installed. Run: pip install gradio_client"

    from .config import get_config

    config = get_config()
    hf_token = config.hf_token

    # Build template context for Jinja2 rendering
    ctx = {
        "input": inputs,
        "env": dict(os.environ),
        **context
    }

    # Determine connection target
    if tool.space:
        space_id = render_template(tool.space, ctx) if "{{" in tool.space else tool.space
        try:
            client = Client(space_id, token=hf_token)
        except Exception as e:
            return f"[ERROR] Failed to connect to HuggingFace Space '{space_id}': {str(e)}"
    elif tool.gradio_url:
        gradio_url = render_template(tool.gradio_url, ctx) if "{{" in tool.gradio_url else tool.gradio_url
        try:
            client = Client(gradio_url)
        except Exception as e:
            return f"[ERROR] Failed to connect to Gradio URL '{gradio_url}': {str(e)}"
    else:
        return "[ERROR] gradio tool requires 'space' or 'gradio_url'"

    # Render any templated input values
    rendered_inputs = {}
    for key, value in inputs.items():
        if isinstance(value, str) and "{{" in value:
            rendered_inputs[key] = render_template(value, ctx)
        else:
            rendered_inputs[key] = value

    # Determine API endpoint
    api_name = tool.api_name or "/predict"

    try:
        # Call the Gradio endpoint
        # Pass inputs as positional args in the order they appear
        result = client.predict(
            *rendered_inputs.values(),
            api_name=api_name
        )

        # Handle the result based on type
        return _process_gradio_result(result, tool)

    except Exception as e:
        return f"[ERROR] Gradio call failed: {str(e)}"


def _process_gradio_result(result: Any, tool: ToolDefinition) -> Any:
    """
    Process Gradio result, handling files (images, audio) specially.

    Returns either a string or a dict with content/images/audio for multi-modal.
    """
    from .config import get_config
    import shutil

    config = get_config()

    # Handle tuple results (multiple outputs)
    if isinstance(result, tuple):
        # Process each element and combine
        processed = []
        images = []
        for item in result:
            proc = _process_single_gradio_result(item, config)
            if isinstance(proc, dict):
                if "content" in proc:
                    processed.append(proc["content"])
                if "images" in proc:
                    images.extend(proc["images"])
            else:
                processed.append(str(proc))

        if images:
            return {"content": "\n".join(processed), "images": images}
        return "\n".join(processed)

    return _process_single_gradio_result(result, config)


def _process_single_gradio_result(result: Any, config) -> Any:
    """Process a single Gradio result value."""
    import shutil
    import uuid

    # Check if it's a file path
    if isinstance(result, str) and os.path.isfile(result):
        ext = os.path.splitext(result)[1].lower()

        # Image files
        if ext in ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'):
            # Copy to RVBBIT image directory
            filename = f"gradio_{uuid.uuid4().hex[:8]}{ext}"
            dest = os.path.join(config.image_dir, filename)
            os.makedirs(config.image_dir, exist_ok=True)
            shutil.copy2(result, dest)
            return {"content": f"Generated image: {dest}", "images": [dest]}

        # Audio files
        elif ext in ('.mp3', '.wav', '.ogg', '.flac', '.m4a'):
            filename = f"gradio_{uuid.uuid4().hex[:8]}{ext}"
            dest = os.path.join(config.audio_dir, filename)
            os.makedirs(config.audio_dir, exist_ok=True)
            shutil.copy2(result, dest)
            return {"content": f"Generated audio: {dest}", "audio": [dest]}

        # Other files - read content if text-like, otherwise return path
        elif ext in ('.txt', '.json', '.csv', '.md', '.xml', '.html'):
            try:
                with open(result, 'r') as f:
                    return f.read()
            except:
                return f"File output: {result}"
        else:
            return f"File output: {result}"

    # Gradio Gallery format: list of dicts with 'image' or 'video' keys
    # Each item has {"image": {"path": "/local/path/..."}, "caption": "..."}
    if isinstance(result, list) and len(result) > 0:
        first_item = result[0]
        if isinstance(first_item, dict):
            # Gallery of images
            if "image" in first_item and isinstance(first_item["image"], dict):
                images = []
                captions = []
                for item in result:
                    img_data = item.get("image", {})
                    path = img_data.get("path")
                    caption = item.get("caption", "")
                    if path and os.path.isfile(path):
                        ext = os.path.splitext(path)[1].lower() or ".png"
                        filename = f"gradio_{uuid.uuid4().hex[:8]}{ext}"
                        dest = os.path.join(config.image_dir, filename)
                        os.makedirs(config.image_dir, exist_ok=True)
                        shutil.copy2(path, dest)
                        images.append(dest)
                        if caption:
                            captions.append(caption)
                if images:
                    content = f"Gallery: {len(images)} images"
                    if captions:
                        content += f" ({', '.join(captions)})"
                    return {"content": content, "images": images}

            # Gallery of videos (similar pattern)
            elif "video" in first_item and isinstance(first_item["video"], dict):
                # Just return paths for now - video handling can be added later
                video_paths = []
                for item in result:
                    vid_data = item.get("video", {})
                    path = vid_data.get("path")
                    if path and os.path.isfile(path):
                        video_paths.append(path)
                if video_paths:
                    return {"content": f"Gallery: {len(video_paths)} videos", "videos": video_paths}

    # Dict/list results - JSON serialize
    if isinstance(result, (dict, list)):
        return json.dumps(result, indent=2)

    # Everything else - string
    return str(result) if result is not None else ""


def execute_local_model_tool(tool: ToolDefinition, inputs: Dict[str, Any], context: Dict[str, Any]) -> str:
    """
    Execute a local_model-type tool using HuggingFace transformers.

    Supports text classification, NER, summarization, question answering,
    and other tasks supported by transformers pipelines.
    """
    try:
        from .local_models import is_available, get_model_registry, TransformersExecutor
    except ImportError:
        return "[ERROR] Local models module not available. Install with: pip install rvbbit[local-models]"

    if not is_available():
        return "[ERROR] transformers/torch not installed. Run: pip install rvbbit[local-models]"

    registry = get_model_registry()
    device = tool.device or "auto"

    # Load or get cached model
    try:
        pipeline = registry.get_or_load(
            model_id=tool.model_id,
            task=tool.task,
            device=device,
            **(tool.model_kwargs or {})
        )
    except Exception as e:
        return f"[ERROR] Failed to load model '{tool.model_id}': {str(e)}"

    # Execute the pipeline
    try:
        executor = TransformersExecutor(pipeline, tool)
        result = executor.execute(inputs)

        # Handle multi-modal results (images need special formatting)
        if isinstance(result, dict) and "images" in result:
            return f"{result.get('content', '')}\n\nImages: {', '.join(result['images'])}"

        # Return raw data structure - framework handles serialization
        # This allows data cells to access results directly via data.cell_name
        return result

    except Exception as e:
        error_msg = str(e)
        # Check for common errors
        if "CUDA out of memory" in error_msg:
            return "[ERROR] CUDA out of memory. Try a smaller model or use device='cpu'."
        return f"[ERROR] Local model execution failed: {error_msg}"


# ============================================================================
# Tool Loading and Registration
# ============================================================================

# Cache for loaded declarative tools
_declarative_tools: Dict[str, ToolDefinition] = {}


def load_tool_definition(path: str) -> ToolDefinition:
    """Load a .tool.json or .tool.yaml file and return a ToolDefinition."""
    from .loaders import load_config_file
    data = load_config_file(path)

    tool = ToolDefinition(**data)
    tool.validate_complete()

    return tool


def get_declarative_tool_executor(tool_id: str):
    """Get an executor function for a declarative tool."""
    if tool_id not in _declarative_tools:
        return None

    tool = _declarative_tools[tool_id]

    def executor(**kwargs):
        return execute_tool(tool, kwargs)

    return executor


def execute_tool(tool: ToolDefinition, inputs: Dict[str, Any], context: Dict[str, Any] = None) -> str:
    """Execute a declarative tool with the given inputs."""
    context = context or {}

    if tool.type == "shell":
        return execute_shell_tool(tool, inputs, context)
    elif tool.type == "http":
        return execute_http_tool(tool, inputs, context)
    elif tool.type == "python":
        return execute_python_tool(tool, inputs, context)
    elif tool.type == "composite":
        return execute_composite_tool(tool, inputs, context)
    elif tool.type == "gradio":
        return execute_gradio_tool(tool, inputs, context)
    elif tool.type == "local_model":
        return execute_local_model_tool(tool, inputs, context)
    else:
        return f"[ERROR] Unknown tool type: {tool.type}"


def register_declarative_tool(tool: ToolDefinition, source_path: str = None):
    """
    Register a declarative tool in the traits registry.

    Creates a wrapper function that can be called like any other tool.
    """
    from .trait_registry import register_trait

    # Store in cache
    _declarative_tools[tool.tool_id] = tool

    # Create wrapper function
    def tool_wrapper(**kwargs):
        return execute_tool(tool, kwargs)

    # Set function metadata for schema generation
    tool_wrapper.__name__ = tool.tool_id
    tool_wrapper.__doc__ = tool.description

    # Build signature from inputs_schema
    if tool.inputs_schema:
        params = []
        for name, desc in tool.inputs_schema.items():
            param = inspect.Parameter(
                name,
                inspect.Parameter.KEYWORD_ONLY,
                annotation=str
            )
            params.append(param)

        sig = inspect.Signature(params)
        tool_wrapper.__signature__ = sig
        tool_wrapper.__annotations__ = {n: str for n in tool.inputs_schema}
        tool_wrapper.__annotations__["return"] = str

    # Store source path as attribute
    tool_wrapper._tool_definition = tool
    tool_wrapper._source_path = source_path

    # Register in traits registry
    register_trait(tool.tool_id, tool_wrapper)


def discover_and_register_declarative_tools(directories: List[str] = None):
    """
    Discover all .tool.json files in the given directories and register them.

    If directories is None, uses the default traits_dirs from config.
    """
    from .config import get_config

    if directories is None:
        config = get_config()
        directories = config.traits_dirs

    registered = []

    for traits_dir in directories:
        # Support both absolute and relative paths
        if not os.path.isabs(traits_dir):
            search_path = os.path.join(os.getcwd(), traits_dir)
            if not os.path.exists(search_path):
                package_dir = os.path.dirname(__file__)
                search_path = os.path.join(package_dir, traits_dir)
        else:
            search_path = traits_dir

        if not os.path.exists(search_path):
            continue

        # Find all .tool.json, .tool.yaml, and .tool.yml files
        for ext in ('json', 'yaml', 'yml'):
            pattern = os.path.join(search_path, f"**/*.tool.{ext}")
            for tool_path in glob.glob(pattern, recursive=True):
                try:
                    tool = load_tool_definition(tool_path)
                    register_declarative_tool(tool, source_path=tool_path)
                    registered.append(tool.tool_id)
                except Exception as e:
                    # Skip invalid tool files but log warning
                    print(f"[Warning] Failed to load {tool_path}: {e}")

    return registered
