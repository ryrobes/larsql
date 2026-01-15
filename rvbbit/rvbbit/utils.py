import inspect
from typing import Any, Callable, Dict, List, get_type_hints, Tuple, Optional
import re
import base64
import mimetypes
import os
import shutil
import json
import hashlib


def compute_species_hash(cell_config: Optional[Dict[str, Any]], input_data: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """
    Compute a deterministic hash ("species hash") for a cell configuration.

    The species hash captures the "DNA" of a cell execution - the template, config,
    and input parameters that define the effective prompt/code sent to the model/runtime.
    This allows comparing cell executions across runs that use the same template AND inputs.

    Updated to handle BOTH LLM cells (instructions-based) and deterministic cells (tool-based).

    Species identity includes:
    - instructions (LLM cells) OR tool+code (deterministic cells)
    - input_data: Template parameters that affect the rendered prompt/code
    - takes: Full config (factor, evaluator_instructions, mutations, reforge)
    - rules: max_turns, loop_until, etc.
    - output_schema, wards: Validation and output requirements

    Species identity EXCLUDES (these are filterable attributes):
    - model: Allows "which model wins with this template?" analysis
    - cascade_id: Allows reusing cells across cascades
    - timestamps, session_id: Not part of identity

    Args:
        cell_config: Dict from CellConfig.model_dump() or cell JSON
        input_data: Input parameters that get rendered into the template

    Returns:
        16-character hex hash, or "unknown_species" if cell_config is invalid

    Example:
        >>> config = {"instructions": "Write a poem about {{topic}}", "takes": {"factor": 3}}
        >>> compute_species_hash(config, {"topic": "cats"})
        'a1b2c3d4e5f6g7h8'
    """
    if not cell_config:
        return "unknown_species"

    # Determine if this is a deterministic cell (tool-based) or LLM cell (instructions-based)
    is_deterministic = bool(cell_config.get('tool'))

    if is_deterministic:
        # For deterministic cells (sql_data, python_data, js_data, etc.)
        # Hash the tool name and its inputs (code, query, etc.)
        spec_parts = {
            'tool': cell_config.get('tool'),
            'inputs': cell_config.get('inputs', {}),  # Tool inputs (code, query, etc.)
            'input_data': input_data or {},  # Cascade inputs
            'rules': cell_config.get('rules'),
            'for_each_row': cell_config.get('for_each_row'),  # SQL mapping config
        }
    else:
        # For LLM cells (instructions-based)
        spec_parts = {
            # The template itself - the core DNA
            'instructions': cell_config.get('instructions', ''),

            # Input data - template parameters that affect rendered prompt
            'input_data': input_data or {},

            # Takes config affects prompt generation strategy
            'takes': cell_config.get('takes') or cell_config.get('takes'),

            # Rules affect execution behavior
            'rules': cell_config.get('rules'),

            # Output schema affects what we're asking for
            'output_schema': cell_config.get('output_schema'),

            # Wards (validators) affect the evolution pressure
            'wards': cell_config.get('wards'),
        }

    # Create deterministic JSON string (sorted keys, no whitespace)
    spec_json = json.dumps(spec_parts, sort_keys=True, separators=(',', ':'), default=str)

    # SHA256 truncated to 16 chars (64 bits) - collision-resistant for our use case
    return hashlib.sha256(spec_json.encode('utf-8')).hexdigest()[:16]


def _compute_input_fingerprint(input_data: Optional[Dict[str, Any]]) -> str:
    """
    Compute structural fingerprint of inputs (keys + types + size buckets).

    This allows clustering similar inputs by both structure AND size:
    - {"product_name": "iPhone"} → fingerprint X (str_tiny)
    - {"product_name": "Samsung Galaxy S24..."} → fingerprint Y (str_small)
    - {"user_id": 123} → fingerprint Z (DIFFERENT structure)

    Includes size buckets for strings and arrays to enable size-based clustering.

    Returns:
        JSON string representing input structure with size hints
    """
    if not input_data:
        return "empty"

    def get_structure(obj):
        if isinstance(obj, dict):
            return {k: get_structure(obj[k]) for k in sorted(obj.keys())}
        elif isinstance(obj, list):
            # Include array length bucket for clustering
            length_bucket = (
                'tiny' if len(obj) < 10 else
                'small' if len(obj) < 100 else
                'medium' if len(obj) < 1000 else
                'large'
            )
            return ['array', length_bucket]
        elif isinstance(obj, str):
            # Include string length bucket for clustering different-sized inputs
            length_bucket = (
                'tiny' if len(obj) < 20 else
                'small' if len(obj) < 100 else
                'medium' if len(obj) < 500 else
                'large'
            )
            return ['str', length_bucket]
        elif isinstance(obj, (int, float)):
            # Include number magnitude bucket
            abs_val = abs(obj)
            magnitude = (
                'tiny' if abs_val < 10 else
                'small' if abs_val < 1000 else
                'medium' if abs_val < 1000000 else
                'large'
            )
            return [type(obj).__name__, magnitude]
        else:
            return type(obj).__name__

    structure = get_structure(input_data)
    return json.dumps(structure, sort_keys=True)


def compute_genus_hash(cascade_config: Dict[str, Any], input_data: Optional[Dict[str, Any]] = None) -> str:
    """
    Compute cascade-level identity hash (genus_hash).

    The genus hash captures the "species" of a CASCADE INVOCATION - the
    structure and inputs that define comparable cascade runs.

    Think of it as: species_hash is for a single cell, genus_hash is for the whole cascade.

    Genus identity includes:
    - cascade_id: Which cascade template
    - cells: Array of cell names + types (structure)
    - input_data: Top-level inputs passed to cascade
    - input_fingerprint: Structure of inputs (for clustering similar invocations)

    Genus identity EXCLUDES:
    - Cell-level instructions (too granular - use species_hash for that)
    - model (allows cross-model comparison)
    - session_id, timestamps (not part of identity)

    Args:
        cascade_config: Dict with cascade_id and cells array
        input_data: Top-level inputs passed to cascade

    Returns:
        16-character hex hash

    Example:
        >>> config = {"cascade_id": "extract_brand", "cells": [{"name": "extract", "tool": None}, ...]}
        >>> compute_genus_hash(config, {"product_name": "iPhone 15"})
        'f1e2d3c4b5a69788'
    """
    if not cascade_config:
        return "unknown_genus"

    # Extract genus-defining fields
    genus_parts = {
        # Cascade identity
        'cascade_id': cascade_config.get('cascade_id', 'unknown'),

        # Cascade structure (cell names + types, not full config)
        'cells': [
            {
                'name': cell.get('name'),
                'type': 'deterministic' if cell.get('tool') else 'llm',
                'tool': cell.get('tool'),  # Include tool type for deterministic cells
            }
            for cell in cascade_config.get('cells', [])
        ],

        # Input structure (for clustering)
        'input_fingerprint': _compute_input_fingerprint(input_data),

        # Input data (for exact matching)
        'input_data': input_data or {},
    }

    # Create deterministic JSON string
    genus_json = json.dumps(genus_parts, sort_keys=True, separators=(',', ':'), default=str)

    # SHA256 truncated to 16 chars
    return hashlib.sha256(genus_json.encode('utf-8')).hexdigest()[:16]

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
    and removes older base64 images from multimodal content arrays.

    IMPORTANT: The caller should check if keep_recent > 0 before calling this function.
    If keep_recent=0, ALL images would be removed (not "keep all").

    Args:
        messages: List of message dicts
        keep_recent: Number of recent images to keep. Must be > 0 to preserve any images.

    Returns:
        New list of messages with old base64 culled (deep copy, doesn't modify original)
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

def get_next_image_index(session_id: str, cell_name: str, take_index: int | None = None) -> int:
    """
    Find the next available image index for a session/cell directory.
    Scans existing files to avoid overwriting.
    If take_index is provided, only considers images for that take.
    """
    from .config import get_config
    config = get_config()

    images_dir = config.image_dir
    cell_dir = os.path.join(images_dir, session_id, cell_name)

    if not os.path.exists(cell_dir):
        return 0

    # Find all existing image files and extract their indices
    existing_indices = set()
    for filename in os.listdir(cell_dir):
        if take_index is not None:
            # Match pattern: take_N_image_M.ext
            match = re.match(rf'take_{take_index}_image_(\d+)\.\w+$', filename)
        else:
            # Match pattern: image_N.ext (without take prefix)
            match = re.match(r'image_(\d+)\.\w+$', filename)
        if match:
            existing_indices.add(int(match.group(1)))

    if not existing_indices:
        return 0

    # Return next index after the highest existing one
    return max(existing_indices) + 1

def get_image_save_path(session_id: str, cell_name: str, image_index: int, extension: str = "png", take_index: int | None = None) -> str:
    """
    Generate standardized path for saving images.
    Format: images/{session_id}/{cell_name}/image_{index}.{ext}
    Or with take: images/{session_id}/{cell_name}/take_{s}_image_{index}.{ext}
    """
    from .config import get_config
    config = get_config()

    # Use configured image_dir
    images_dir = config.image_dir

    if take_index is not None:
        filename = f"take_{take_index}_image_{image_index}.{extension}"
    else:
        filename = f"image_{image_index}.{extension}"

    path = os.path.join(images_dir, session_id, cell_name, filename)
    return path

def get_next_audio_index(session_id: str, cell_name: str, take_index: int | None = None) -> int:
    """
    Find the next available audio index for a session/cell directory.
    Scans existing files to avoid overwriting.
    If take_index is provided, only considers audio for that take.
    """
    from .config import get_config
    config = get_config()

    audio_dir = config.audio_dir
    cell_dir = os.path.join(audio_dir, session_id, cell_name)

    if not os.path.exists(cell_dir):
        return 0

    # Find all existing audio files and extract their indices
    existing_indices = set()
    for filename in os.listdir(cell_dir):
        if take_index is not None:
            # Match pattern: take_N_audio_M.ext
            match = re.match(rf'take_{take_index}_audio_(\d+)\.\w+$', filename)
        else:
            # Match pattern: audio_N.ext (without take prefix)
            match = re.match(r'audio_(\d+)\.\w+$', filename)
        if match:
            existing_indices.add(int(match.group(1)))

    if not existing_indices:
        return 0

    # Return next index after the highest existing one
    return max(existing_indices) + 1

def get_audio_save_path(session_id: str, cell_name: str, audio_index: int, extension: str = "mp3", take_index: int | None = None) -> str:
    """
    Generate standardized path for saving audio files.
    Format: audio/{session_id}/{cell_name}/audio_{index}.{ext}
    Or with take: audio/{session_id}/{cell_name}/take_{s}_audio_{index}.{ext}
    """
    from .config import get_config
    config = get_config()

    # Use configured audio_dir
    audio_dir = config.audio_dir

    if take_index is not None:
        filename = f"take_{take_index}_audio_{audio_index}.{extension}"
    else:
        filename = f"audio_{audio_index}.{extension}"

    path = os.path.join(audio_dir, session_id, cell_name, filename)
    return path

# =============================================================================
# Video Utilities
# =============================================================================

# Supported video MIME types and their extensions
VIDEO_MIME_TO_EXT = {
    "video/mp4": "mp4",
    "video/webm": "webm",
    "video/quicktime": "mov",
    "video/x-msvideo": "avi",
    "video/x-matroska": "mkv",
    "video/ogg": "ogv",
    "video/mpeg": "mpeg",
}

VIDEO_EXT_TO_MIME = {v: k for k, v in VIDEO_MIME_TO_EXT.items()}

def get_video_extension_from_mime(mime_type: str) -> str:
    """Get file extension from video MIME type. Defaults to mp4."""
    return VIDEO_MIME_TO_EXT.get(mime_type.lower(), "mp4")

def get_video_mime_from_extension(extension: str) -> str:
    """Get MIME type from video file extension. Defaults to video/mp4."""
    ext = extension.lower().lstrip(".")
    return VIDEO_EXT_TO_MIME.get(ext, "video/mp4")

def encode_video_base64(video_path: str) -> str:
    """
    Encodes a local video to base64 data URL.

    Args:
        video_path: Path to video file

    Returns:
        Base64 data URL string (e.g., "data:video/mp4;base64,...")
    """
    if not os.path.exists(video_path):
        return f"[Error: Video not found at {video_path}]"

    # Determine MIME type from extension
    ext = os.path.splitext(video_path)[1].lower().lstrip(".")
    mime_type = get_video_mime_from_extension(ext)

    with open(video_path, "rb") as video_file:
        encoded_string = base64.b64encode(video_file.read()).decode('utf-8')

    return f"data:{mime_type};base64,{encoded_string}"

def decode_and_save_video(base64_data: str, save_path: str) -> str:
    """
    Decodes a base64 data URL and saves video to disk.
    Returns the saved file path.

    Handles formats:
    - data:video/mp4;base64,{base64_string}
    - data:video/webm;base64,{base64_string}
    - Raw base64 string (without data: prefix)
    """
    # Extract base64 content from data URL
    if base64_data.startswith("data:"):
        # Format: data:video/mp4;base64,AAAA...
        base64_content = base64_data.split(",", 1)[1]
    else:
        base64_content = base64_data

    # Decode and save
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    with open(save_path, "wb") as f:
        f.write(base64.b64decode(base64_content))

    return save_path

def get_video_extension_from_data_url(data_url: str) -> str:
    """
    Extract extension from a video data URL.
    e.g., "data:video/mp4;base64,..." -> "mp4"
    """
    if not data_url.startswith("data:video/"):
        return "mp4"  # Default

    try:
        # Extract mime type: data:video/mp4;base64,...
        mime_part = data_url.split(";")[0]  # data:video/mp4
        mime_type = mime_part.split(":")[1]  # video/mp4
        return get_video_extension_from_mime(mime_type)
    except (IndexError, ValueError):
        return "mp4"

def get_next_video_index(session_id: str, cell_name: str, take_index: int | None = None) -> int:
    """
    Find the next available video index for a session/cell directory.
    Scans existing files to avoid overwriting.
    If take_index is provided, only considers videos for that take.
    """
    from .config import get_config
    config = get_config()

    video_dir = config.video_dir
    cell_dir = os.path.join(video_dir, session_id, cell_name)

    if not os.path.exists(cell_dir):
        return 0

    # Find all existing video files and extract their indices
    existing_indices = set()
    for filename in os.listdir(cell_dir):
        if take_index is not None:
            # Match pattern: take_N_video_M.ext
            match = re.match(rf'take_{take_index}_video_(\d+)\.\w+$', filename)
        else:
            # Match pattern: video_N.ext (without take prefix)
            match = re.match(r'video_(\d+)\.\w+$', filename)
        if match:
            existing_indices.add(int(match.group(1)))

    if not existing_indices:
        return 0

    # Return next index after the highest existing one
    return max(existing_indices) + 1

def get_video_save_path(session_id: str, cell_name: str, video_index: int, extension: str = "mp4", take_index: int | None = None) -> str:
    """
    Generate standardized path for saving videos.
    Format: videos/{session_id}/{cell_name}/video_{index}.{ext}
    Or with take: videos/{session_id}/{cell_name}/take_{s}_video_{index}.{ext}
    """
    from .config import get_config
    config = get_config()

    # Use configured video_dir
    video_dir = config.video_dir

    if take_index is not None:
        filename = f"take_{take_index}_video_{video_index}.{extension}"
    else:
        filename = f"video_{video_index}.{extension}"

    path = os.path.join(video_dir, session_id, cell_name, filename)
    return path

def extract_videos_from_messages(messages: List[Dict]) -> List[Tuple[str, str]]:
    """
    Extract video base64 data and URLs from message history.
    Returns list of (base64_data, description) tuples.
    """
    videos = []

    for msg in messages:
        content = msg.get("content")

        # Handle string content (might have embedded base64)
        if isinstance(content, str):
            # Look for data URLs in text
            data_url_pattern = r'data:video/[^;]+;base64,[A-Za-z0-9+/=]+'
            matches = re.findall(data_url_pattern, content)
            for match in matches:
                videos.append((match, "embedded_video"))

        # Handle multi-modal content (array format)
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "video_url":
                        video_url = item.get("video_url", {})
                        if isinstance(video_url, dict):
                            url = video_url.get("url", "")
                        else:
                            url = video_url

                        if url.startswith("data:"):
                            videos.append((url, item.get("description", "video")))

        # Handle 'videos' key in message (like we do for images)
        videos_list = msg.get("videos", [])
        if videos_list:
            for vid in videos_list:
                if isinstance(vid, dict):
                    url = vid.get("video_url", {}).get("url", "")
                    if url.startswith("data:"):
                        videos.append((url, vid.get("description", "video")))
                elif isinstance(vid, str) and vid.startswith("data:"):
                    videos.append((vid, "video"))

    return videos

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

def get_tool_schema(func: Callable, name: str | None = None) -> Dict[str, Any]:
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
