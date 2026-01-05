"""
TransformersExecutor - Execute HuggingFace transformers pipelines.

Handles input mapping, output formatting, and multi-modal results.
"""

import json
import os
import uuid
from typing import Any, Dict, List, Optional, Union, TYPE_CHECKING


def _convert_numpy_types(obj: Any) -> Any:
    """
    Recursively convert numpy types to native Python types.

    Transformers pipelines often return np.float32/np.int64 which aren't
    JSON serializable. This converts them to native Python types.
    """
    try:
        import numpy as np

        if isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, dict):
            return {k: _convert_numpy_types(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [_convert_numpy_types(item) for item in obj]
        elif isinstance(obj, tuple):
            return tuple(_convert_numpy_types(item) for item in obj)
        return obj
    except ImportError:
        # numpy not available, return as-is
        return obj

if TYPE_CHECKING:
    from transformers import Pipeline


# Task-specific input parameter mappings
TASK_INPUT_MAPPINGS = {
    # Text classification tasks
    "text-classification": ["text", "texts"],
    "sentiment-analysis": ["text", "texts"],
    "zero-shot-classification": ["text", "candidate_labels"],

    # Token classification
    "token-classification": ["text", "texts"],
    "ner": ["text", "texts"],

    # Question answering
    "question-answering": ["question", "context"],

    # Generation tasks
    "text-generation": ["text", "prompt"],
    "text2text-generation": ["text", "input_text"],
    "summarization": ["text", "documents"],
    "translation": ["text", "texts"],

    # Fill mask
    "fill-mask": ["text", "texts"],

    # Image tasks
    "image-classification": ["image", "images"],
    "object-detection": ["image", "images"],
    "image-to-text": ["image", "images"],

    # Audio tasks
    "automatic-speech-recognition": ["audio", "inputs"],
}


class TransformersExecutor:
    """
    Executor for HuggingFace transformers pipelines.

    Handles:
    - Input parameter mapping based on task type
    - Output formatting (JSON for structured, string for text)
    - Multi-modal outputs (images saved to configured directory)
    """

    def __init__(
        self,
        pipeline: "Pipeline",
        tool_definition: Optional[Any] = None,
    ) -> None:
        """
        Initialize the executor.

        Args:
            pipeline: Loaded transformers Pipeline
            tool_definition: Optional ToolDefinition for configuration
        """
        self.pipeline = pipeline
        self.tool_definition = tool_definition
        self.task = pipeline.task if hasattr(pipeline, "task") else None

    def execute(self, inputs: Dict[str, Any]) -> Union[str, Dict[str, Any]]:
        """
        Execute the pipeline with the given inputs.

        Args:
            inputs: Dict of input parameters from tool invocation

        Returns:
            Formatted result as string or dict (for multi-modal)
        """
        # Map inputs to pipeline call
        pipeline_inputs = self._map_inputs(inputs)

        # Get pipeline kwargs if specified in tool definition
        pipeline_kwargs = {}
        if self.tool_definition and hasattr(self.tool_definition, "pipeline_kwargs"):
            if self.tool_definition.pipeline_kwargs:
                pipeline_kwargs = self.tool_definition.pipeline_kwargs

        # Execute pipeline
        if isinstance(pipeline_inputs, dict):
            result = self.pipeline(**pipeline_inputs, **pipeline_kwargs)
        elif isinstance(pipeline_inputs, list):
            result = self.pipeline(pipeline_inputs, **pipeline_kwargs)
        else:
            result = self.pipeline(pipeline_inputs, **pipeline_kwargs)

        # Format output
        return self._format_output(result)

    def _map_inputs(self, inputs: Dict[str, Any]) -> Any:
        """
        Map user-provided inputs to pipeline expected format.

        Different tasks expect different input formats:
        - text-classification: single string or list of strings
        - question-answering: dict with 'question' and 'context'
        - etc.
        """
        task = self.task or ""

        # Get expected input parameters for this task
        expected_params = TASK_INPUT_MAPPINGS.get(task, ["text"])

        # Special handling for question-answering (requires dict)
        if task == "question-answering":
            return {
                "question": inputs.get("question", inputs.get("text", "")),
                "context": inputs.get("context", ""),
            }

        # Special handling for zero-shot-classification
        if task == "zero-shot-classification":
            text = inputs.get("text", inputs.get("texts", ""))
            labels = inputs.get("candidate_labels", inputs.get("labels", []))
            if isinstance(labels, str):
                # Parse comma-separated labels
                labels = [l.strip() for l in labels.split(",")]
            return {"sequences": text, "candidate_labels": labels}

        # For most tasks, find the primary input
        for param in expected_params:
            if param in inputs:
                value = inputs[param]

                # Handle image inputs (file paths)
                if param in ("image", "images"):
                    return self._load_image(value)

                # Handle audio inputs (file paths)
                if param in ("audio", "inputs") and task == "automatic-speech-recognition":
                    return value  # Pipeline handles file paths

                return value

        # Fallback: use first available input or 'text'
        if "text" in inputs:
            return inputs["text"]

        # Use first input value
        for key, value in inputs.items():
            if not key.startswith("_"):  # Skip internal params
                return value

        return ""

    def _load_image(self, image_input: Any) -> Any:
        """Load image from path or return as-is."""
        if isinstance(image_input, str):
            # Check if it's a file path
            if os.path.exists(image_input):
                try:
                    from PIL import Image
                    return Image.open(image_input)
                except ImportError:
                    # Return path, let pipeline handle it
                    return image_input
        return image_input

    def _format_output(self, result: Any) -> Union[str, Dict[str, Any], List[Any]]:
        """
        Format pipeline output for return.

        Returns raw data structures (dicts/lists) for compatibility with
        data cell patterns. The framework handles serialization when needed.

        Args:
            result: Raw pipeline output

        Returns:
            Raw data structure (dict/list) or string for text results
        """
        # Check output_transform from tool definition
        output_transform = None
        if self.tool_definition and hasattr(self.tool_definition, "output_transform"):
            output_transform = self.tool_definition.output_transform

        # Handle different result types
        if isinstance(result, list):
            # Most pipelines return list of dicts
            if output_transform == "first" and result:
                return _convert_numpy_types(self._format_single(result[0]))

            # Check for image outputs
            if result and self._is_image_result(result[0]):
                return self._handle_image_output(result)

            # Return raw list with numpy types converted
            return _convert_numpy_types(result)

        if isinstance(result, dict):
            # Check for image outputs
            if self._is_image_result(result):
                return self._handle_image_output(result)

            # Return raw dict with numpy types converted
            return _convert_numpy_types(result)

        if isinstance(result, str):
            return result

        # Fallback
        return str(result)

    def _format_single(self, item: Any) -> Any:
        """Format a single result item."""
        # Return raw item - framework handles serialization
        return item

    def _is_image_result(self, result: Any) -> bool:
        """Check if result contains image data."""
        if isinstance(result, dict):
            # Check for common image output patterns
            if "image" in result or "mask" in result:
                return True
            # Check for PIL Image
            for value in result.values():
                if self._is_pil_image(value):
                    return True
        return self._is_pil_image(result)

    def _is_pil_image(self, obj: Any) -> bool:
        """Check if object is a PIL Image."""
        try:
            from PIL import Image
            return isinstance(obj, Image.Image)
        except ImportError:
            return False

    def _handle_image_output(self, result: Any) -> Dict[str, Any]:
        """
        Handle image outputs by saving to disk.

        Returns dict with 'content' and 'images' keys for multi-modal protocol.
        """
        try:
            from PIL import Image
        except ImportError:
            return {"content": str(result), "images": []}

        images = []
        content_parts = []

        # Get image directory from config
        try:
            from ..config import get_config
            config = get_config()
            image_dir = config.image_dir
        except Exception:
            image_dir = "images"

        os.makedirs(image_dir, exist_ok=True)

        def save_image(img: Image.Image, label: str = "") -> str:
            filename = f"local_model_{uuid.uuid4().hex[:8]}.png"
            path = os.path.join(image_dir, filename)
            img.save(path)
            return path

        # Extract images from result
        if isinstance(result, list):
            for i, item in enumerate(result):
                if isinstance(item, dict):
                    for key, value in item.items():
                        if isinstance(value, Image.Image):
                            path = save_image(value, key)
                            images.append(path)
                            content_parts.append(f"{key}: {path}")
                elif isinstance(item, Image.Image):
                    path = save_image(item, f"image_{i}")
                    images.append(path)
        elif isinstance(result, dict):
            for key, value in result.items():
                if isinstance(value, Image.Image):
                    path = save_image(value, key)
                    images.append(path)
                    content_parts.append(f"{key}: {path}")
                else:
                    content_parts.append(f"{key}: {value}")
        elif isinstance(result, Image.Image):
            path = save_image(result)
            images.append(path)

        content = "\n".join(content_parts) if content_parts else "Image generated"

        return {"content": content, "images": images}


def format_local_model_result(result: Any, tool_definition: Optional[Any] = None) -> str:
    """
    Format a local model result for return to the cascade.

    This is a standalone function that can be used without an executor instance.

    Args:
        result: Raw result from pipeline
        tool_definition: Optional tool definition for formatting hints

    Returns:
        Formatted string result
    """
    executor = TransformersExecutor(None, tool_definition)
    executor.task = None  # No task inference without pipeline

    formatted = executor._format_output(result)

    if isinstance(formatted, dict):
        # Multi-modal result
        if "images" in formatted:
            return f"{formatted.get('content', '')}\n\nImages: {', '.join(formatted['images'])}"
        return json.dumps(formatted, indent=2, default=str)

    return formatted
