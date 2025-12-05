import inspect
from typing import Any, Callable, Dict, List, get_type_hints, Tuple
import re
import base64
import mimetypes
import os
import shutil

def encode_image_base64(image_path: str) -> str:
    """Encodes a local image to base64 data URL."""
    if not os.path.exists(image_path):
        return f"[Error: Image not found at {image_path}]"

    mime_type, _ = mimetypes.guess_type(image_path)
    if not mime_type:
        mime_type = "image/png" # Default

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
