import inspect
from typing import Any, Callable, Dict, List, get_type_hints, Tuple, Optional
import re
import base64
import mimetypes
import os
import shutil
import json
import hashlib


def compute_species_hash(phase_config: Optional[Dict[str, Any]]) -> Optional[str]:
    """
    Compute a deterministic hash ("species hash") for a phase configuration.

    The species hash captures the "DNA" of a prompt - the template and config
    that defines how prompts are generated, NOT the rendered prompt itself.
    This allows comparing prompts across runs that use the same template.

    Species identity includes:
    - instructions: The Jinja2 template (pre-rendering)
    - soundings: Full config (factor, evaluator_instructions, mutations, reforge)
    - rules: max_turns, loop_until, etc.

    Species identity EXCLUDES (these are filterable attributes):
    - model: Allows "which model wins with this template?" analysis
    - rendered values: Template variables are NOT in the hash

    Args:
        phase_config: Dict from PhaseConfig.model_dump() or phase JSON

    Returns:
        16-character hex hash, or None if phase_config is None/empty

    Example:
        >>> config = {"instructions": "Write a poem about {{topic}}", "soundings": {"factor": 3}}
        >>> compute_species_hash(config)
        'a1b2c3d4e5f6g7h8'
    """
    if not phase_config:
        return None

    # Extract the DNA-defining fields (order matters for deterministic hash)
    spec_parts = {
        # The template itself - the core DNA
        'instructions': phase_config.get('instructions', ''),

        # Soundings config affects prompt generation strategy
        'soundings': phase_config.get('soundings'),

        # Rules affect execution behavior (max_turns, loop_until, etc.)
        'rules': phase_config.get('rules'),

        # Output schema affects what we're asking for
        'output_schema': phase_config.get('output_schema'),

        # Wards (validators) affect the evolution pressure
        'wards': phase_config.get('wards'),
    }

    # Create deterministic JSON string (sorted keys, no whitespace)
    # None values are preserved as null in JSON
    spec_json = json.dumps(spec_parts, sort_keys=True, separators=(',', ':'), default=str)

    # SHA256 truncated to 16 chars (64 bits) - collision-resistant for our use case
    return hashlib.sha256(spec_json.encode('utf-8')).hexdigest()[:16]

def encode_image_base64(image_path: str, max_dimension: int = 1280) -> str:
    """
    Encodes a local image to base64 data URL with optional resizing.

    Args:
        image_path: Path to image file
        max_dimension: Maximum size for longest side (default: 1280px for chart legibility)
                      Set to None to disable resizing

    Returns:
        Base64 data URL string
    """
    if not os.path.exists(image_path):
        return f"[Error: Image not found at {image_path}]"

    mime_type, _ = mimetypes.guess_type(image_path)
    if not mime_type:
        mime_type = "image/png" # Default

    # Resize image if max_dimension is set
    if max_dimension:
        try:
            from PIL import Image
            import io

            # Open and process image
            img = Image.open(image_path)
            original_size = img.size
            should_resize = max(img.size) > max_dimension

            # ONLY optimize/re-encode if we're actually resizing
            # Otherwise, use original file to avoid unnecessary re-compression
            if should_resize:
                # Resize and optimize images for LLM vision
                buffer = io.BytesIO()

                # Resize
                img.thumbnail((max_dimension, max_dimension), Image.LANCZOS)

                # Convert RGBA->RGB for better compression (LLMs don't need alpha channel)
                if img.mode in ('RGBA', 'LA', 'P'):
                    # Create white background
                    rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                    rgb_img.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                    rgb_img.save(buffer, format='JPEG', quality=80, optimize=True)
                else:
                    # RGB or L mode - save as JPEG directly
                    img.save(buffer, format='JPEG', quality=80, optimize=True)

                # Always use JPEG mime type when optimizing
                mime_type = 'image/jpeg'
                buffer.seek(0)
                encoded_string = base64.b64encode(buffer.read()).decode('utf-8')
            else:
                # Image is already small enough - use original file without re-encoding
                # This preserves the original compression and avoids making small images bigger
                with open(image_path, "rb") as image_file:
                    encoded_string = base64.b64encode(image_file.read()).decode('utf-8')

        except ImportError:
            # PIL not available, fall back to no optimization
            with open(image_path, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
        except Exception as e:
            # Any other error, fall back to no optimization
            with open(image_path, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
    else:
        # No resizing requested
        with open(image_path, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode('utf-8')

    return f"data:{mime_type};base64,{encoded_string}"

def decode_and_save_image(base64_data: str, save_path: str) -> str:
    """
    Decodes a base64 data URL and saves to disk.
    Returns the saved file path.
    """
    # Extract base64 content from data URL
    if base64_data.startswith("data:"):
        # Format: data:image/png;base64,iVBORw0KGgo...
        base64_content = base64_data.split(",", 1)[1]
    else:
        base64_content = base64_data

    # Decode and save
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    with open(save_path, "wb") as f:
        f.write(base64.b64decode(base64_content))

    return save_path

def extract_images_from_messages(messages: List[Dict]) -> List[Tuple[str, str]]:
    """
    Extract image base64 data and URLs from message history.
    Returns list of (base64_data, description) tuples.
    """
    images = []

    for msg in messages:
        content = msg.get("content")

        # Handle string content (might have embedded base64)
        if isinstance(content, str):
            # Look for data URLs in text
            data_url_pattern = r'data:image/[^;]+;base64,[A-Za-z0-9+/=]+'
            matches = re.findall(data_url_pattern, content)
            for match in matches:
                images.append((match, "embedded_image"))

        # Handle multi-modal content (array format)
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "image_url":
                        image_url = item.get("image_url", {})
                        if isinstance(image_url, dict):
                            url = image_url.get("url", "")
                        else:
                            url = image_url

                        if url.startswith("data:"):
                            images.append((url, item.get("description", "image")))

    return images

def cull_old_base64_images(messages: List[Dict], keep_recent: int = 3) -> List[Dict]:
    """
    Cull old base64 images from messages, keeping only the most recent N images.

    Iterates through messages in reverse order, keeps base64 for the last N images,
    and replaces older base64 data with placeholders to save tokens.

    Args:
        messages: List of message dicts
        keep_recent: Number of recent images to keep (default: 3)

    Returns:
        New list of messages with old base64 culled
    """
    import copy

    # Deep copy to avoid mutating original messages
    culled_messages = copy.deepcopy(messages)

    # Track how many images we've seen (counting from end)
    images_seen = 0

    # Iterate in reverse order (most recent first)
    for msg in reversed(culled_messages):
        content = msg.get("content")

        # Handle multi-modal content (array format) - where images live
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "image_url":
                    image_url = item.get("image_url", {})

                    if isinstance(image_url, dict):
                        url = image_url.get("url", "")
                    else:
                        url = image_url

                    # If it's a base64 image
                    if url.startswith("data:"):
                        images_seen += 1

                        # If we've seen more than keep_recent images, cull this one
                        if images_seen > keep_recent:
                            # Remove the entire image_url item from content array
                            # This is safer than placeholder text which LLMs might reject
                            content.remove(item)

        # Handle string content with embedded base64 (less common)
        elif isinstance(content, str):
            data_url_pattern = r'data:image/[^;]+;base64,[A-Za-z0-9+/=]+'
            matches = list(re.finditer(data_url_pattern, content))

            # Iterate matches in reverse (for proper indexing during replacement)
            for match in reversed(matches):
                images_seen += 1

                if images_seen > keep_recent:
                    # Replace base64 URL with placeholder
                    start, end = match.span()
                    placeholder = "[Image previously shown - saved to disk]"
                    content = content[:start] + placeholder + content[end:]

            msg["content"] = content

    return culled_messages

def cull_old_conversation_history(messages: List[Dict], keep_recent_turns: int = 10) -> List[Dict]:
    """
    Cull old conversation messages to prevent context bloat.

    Keeps the most recent conversation turns and system messages in their natural flow position.
    This prevents token explosion while preserving feedback loop context.

    IMPORTANT: Does NOT move system messages to the front - leaves them in natural position
    to avoid overriding recent feedback from the conversation.

    Args:
        messages: List of message dicts
        keep_recent_turns: Number of recent user/assistant message pairs to keep (default: 10)
                          Set to 0 or None to disable culling (keep all messages)

    Returns:
        New list of messages with old conversation culled
    """
    import copy

    # If culling disabled, return original messages
    if not keep_recent_turns or keep_recent_turns <= 0:
        return messages

    # Strategy: Keep the last N messages total, preserving natural flow
    # A turn typically has ~3 messages (user, assistant, tool), so multiply by 3
    keep_count = keep_recent_turns * 3

    if len(messages) <= keep_count:
        # All messages fit within limit
        return messages

    # Keep only the most recent messages in their natural order
    # This preserves the feedback loop context and recent conversation flow
    culled_messages = messages[-keep_count:]

    # Find if there's a tool definition system message in the kept messages
    has_tool_def = any(
        msg.get("role") == "system" and ("Tool" in msg.get("content", "") or "tool" in msg.get("content", ""))
        for msg in culled_messages
    )

    # If no tool definition in kept messages, prepend the most recent one from all messages
    # This ensures agent always knows what tools are available
    if not has_tool_def:
        all_tool_systems = [
            msg for msg in messages
            if msg.get("role") == "system" and ("Tool" in msg.get("content", "") or "tool" in msg.get("content", ""))
        ]
        if all_tool_systems:
            # Prepend ONLY the most recent tool definition
            culled_messages.insert(0, all_tool_systems[-1])

    return culled_messages

def get_next_image_index(session_id: str, phase_name: str, sounding_index: int = None) -> int:
    """
    Find the next available image index for a session/phase directory.
    Scans existing files to avoid overwriting.
    If sounding_index is provided, only considers images for that sounding.
    """
    from .config import get_config
    config = get_config()

    images_dir = config.image_dir
    phase_dir = os.path.join(images_dir, session_id, phase_name)

    if not os.path.exists(phase_dir):
        return 0

    # Find all existing image files and extract their indices
    existing_indices = set()
    for filename in os.listdir(phase_dir):
        if sounding_index is not None:
            # Match pattern: sounding_N_image_M.ext
            match = re.match(rf'sounding_{sounding_index}_image_(\d+)\.\w+$', filename)
        else:
            # Match pattern: image_N.ext (without sounding prefix)
            match = re.match(r'image_(\d+)\.\w+$', filename)
        if match:
            existing_indices.add(int(match.group(1)))

    if not existing_indices:
        return 0

    # Return next index after the highest existing one
    return max(existing_indices) + 1

def get_image_save_path(session_id: str, phase_name: str, image_index: int, extension: str = "png", sounding_index: int = None) -> str:
    """
    Generate standardized path for saving images.
    Format: images/{session_id}/{phase_name}/image_{index}.{ext}
    Or with sounding: images/{session_id}/{phase_name}/sounding_{s}_image_{index}.{ext}
    """
    from .config import get_config
    config = get_config()

    # Use configured image_dir
    images_dir = config.image_dir

    if sounding_index is not None:
        filename = f"sounding_{sounding_index}_image_{image_index}.{extension}"
    else:
        filename = f"image_{image_index}.{extension}"

    path = os.path.join(images_dir, session_id, phase_name, filename)
    return path

def get_next_audio_index(session_id: str, phase_name: str, sounding_index: int = None) -> int:
    """
    Find the next available audio index for a session/phase directory.
    Scans existing files to avoid overwriting.
    If sounding_index is provided, only considers audio for that sounding.
    """
    from .config import get_config
    config = get_config()

    audio_dir = config.audio_dir
    phase_dir = os.path.join(audio_dir, session_id, phase_name)

    if not os.path.exists(phase_dir):
        return 0

    # Find all existing audio files and extract their indices
    existing_indices = set()
    for filename in os.listdir(phase_dir):
        if sounding_index is not None:
            # Match pattern: sounding_N_audio_M.ext
            match = re.match(rf'sounding_{sounding_index}_audio_(\d+)\.\w+$', filename)
        else:
            # Match pattern: audio_N.ext (without sounding prefix)
            match = re.match(r'audio_(\d+)\.\w+$', filename)
        if match:
            existing_indices.add(int(match.group(1)))

    if not existing_indices:
        return 0

    # Return next index after the highest existing one
    return max(existing_indices) + 1

def get_audio_save_path(session_id: str, phase_name: str, audio_index: int, extension: str = "mp3", sounding_index: int = None) -> str:
    """
    Generate standardized path for saving audio files.
    Format: audio/{session_id}/{phase_name}/audio_{index}.{ext}
    Or with sounding: audio/{session_id}/{phase_name}/sounding_{s}_audio_{index}.{ext}
    """
    from .config import get_config
    config = get_config()

    # Use configured audio_dir
    audio_dir = config.audio_dir

    if sounding_index is not None:
        filename = f"sounding_{sounding_index}_audio_{audio_index}.{extension}"
    else:
        filename = f"audio_{audio_index}.{extension}"

    path = os.path.join(audio_dir, session_id, phase_name, filename)
    return path

def python_type_to_json_type(t: Any) -> str:
    if t == str:
        return "string"
    elif t == int:
        return "integer"
    elif t == float:
        return "number"
    elif t == bool:
        return "boolean"
    elif t == list:
        return "array"
    elif t == dict:
        return "object"
    return "string" # default

def get_tool_schema(func: Callable, name: str = None) -> Dict[str, Any]:
    """
    Generates an OpenAI-compatible tool schema from a Python function.
    """
    sig = inspect.signature(func)
    hints = get_type_hints(func)
    
    tool_name = name or func.__name__
    
    parameters = {
        "type": "object",
        "properties": {},
        "required": []
    }
    
    for name, param in sig.parameters.items():
        if name == "self":
            continue
            
        param_type = hints.get(name, str) # default to string
        json_type = python_type_to_json_type(param_type)
        
        parameters["properties"][name] = {
            "type": json_type,
            "description": f"Parameter {name}" # parsing docstrings is harder, skip for MVP
        }
        
        if param.default == inspect.Parameter.empty:
            parameters["required"].append(name)
            
    return {
        "type": "function",
        "function": {
            "name": tool_name,
            "description": func.__doc__ or "",
            "parameters": parameters
        }
    }
