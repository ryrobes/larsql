"""
Device detection and management for local models.

Handles automatic detection of CUDA, MPS (Apple Silicon), and CPU devices.
"""

import os
from typing import Dict, Any, Optional


def auto_device() -> str:
    """
    Automatically detect the best available device.

    Returns:
        'cuda' if NVIDIA GPU available
        'mps' if Apple Silicon GPU available
        'cpu' otherwise
    """
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"

        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"

        return "cpu"
    except ImportError:
        return "cpu"


def resolve_device(device: str) -> str:
    """
    Resolve device string to actual device.

    Args:
        device: Device specification ('auto', 'cuda', 'cuda:0', 'mps', 'cpu')

    Returns:
        Resolved device string
    """
    # Check environment override
    env_device = os.getenv("LARS_LOCAL_MODEL_DEVICE")
    if env_device and env_device.lower() != "auto":
        device = env_device

    if device == "auto" or device is None:
        return auto_device()

    # Validate the device
    device_lower = device.lower()

    if device_lower == "cpu":
        return "cpu"

    if device_lower.startswith("cuda"):
        try:
            import torch
            if torch.cuda.is_available():
                return device_lower
            else:
                # Fall back to CPU if CUDA not available
                return "cpu"
        except ImportError:
            return "cpu"

    if device_lower == "mps":
        try:
            import torch
            if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                return "mps"
            else:
                return "cpu"
        except ImportError:
            return "cpu"

    # Unknown device, return as-is (let torch/transformers handle errors)
    return device


def get_device_info() -> Dict[str, Any]:
    """
    Get detailed information about available devices.

    Returns:
        Dict with device information including:
        - current_device: The device that would be selected by auto_device()
        - cuda_available: Whether CUDA is available
        - cuda_device_count: Number of CUDA devices
        - cuda_devices: List of CUDA device info
        - mps_available: Whether MPS is available
        - cpu_count: Number of CPU cores
    """
    info: Dict[str, Any] = {
        "current_device": "cpu",
        "cuda_available": False,
        "cuda_device_count": 0,
        "cuda_devices": [],
        "mps_available": False,
        "cpu_count": os.cpu_count() or 1,
    }

    try:
        import torch

        info["current_device"] = auto_device()

        # CUDA info
        if torch.cuda.is_available():
            info["cuda_available"] = True
            info["cuda_device_count"] = torch.cuda.device_count()

            for i in range(torch.cuda.device_count()):
                device_props = torch.cuda.get_device_properties(i)
                info["cuda_devices"].append({
                    "index": i,
                    "name": device_props.name,
                    "total_memory_gb": round(device_props.total_memory / (1024**3), 2),
                    "major": device_props.major,
                    "minor": device_props.minor,
                })

        # MPS info
        if hasattr(torch.backends, "mps"):
            info["mps_available"] = torch.backends.mps.is_available()

    except ImportError:
        pass

    return info


def get_device_memory(device: str) -> Optional[int]:
    """
    Get total memory available on a device in bytes.

    Args:
        device: Device string ('cuda', 'cuda:0', 'mps', 'cpu')

    Returns:
        Total memory in bytes, or None if unknown
    """
    try:
        import torch

        if device.startswith("cuda"):
            if torch.cuda.is_available():
                device_idx = 0
                if ":" in device:
                    device_idx = int(device.split(":")[1])
                return torch.cuda.get_device_properties(device_idx).total_memory

        # MPS doesn't expose memory info directly
        # CPU memory would require psutil

    except (ImportError, Exception):
        pass

    return None


def estimate_model_memory(model_id: str, task: str) -> int:
    """
    Estimate memory required for a model in bytes.

    This is a rough heuristic based on common model sizes.
    Actual memory usage depends on batch size, sequence length, etc.

    Args:
        model_id: HuggingFace model ID
        task: Pipeline task

    Returns:
        Estimated memory in bytes
    """
    # Base estimates for common model families (in GB)
    # These are very rough estimates for inference
    model_lower = model_id.lower()

    # Tiny models (< 100M params)
    if any(x in model_lower for x in ["tiny", "mini", "small"]):
        return int(0.5 * 1024**3)  # 500MB

    # DistilBERT, MobileBERT, etc.
    if any(x in model_lower for x in ["distil", "mobile"]):
        return int(1 * 1024**3)  # 1GB

    # Base BERT, RoBERTa, etc.
    if any(x in model_lower for x in ["bert", "roberta", "electra"]):
        if "large" in model_lower:
            return int(2 * 1024**3)  # 2GB
        return int(1 * 1024**3)  # 1GB

    # T5 models
    if "t5" in model_lower:
        if "xxl" in model_lower:
            return int(40 * 1024**3)  # 40GB
        if "xl" in model_lower:
            return int(12 * 1024**3)  # 12GB
        if "large" in model_lower:
            return int(3 * 1024**3)  # 3GB
        if "base" in model_lower:
            return int(1 * 1024**3)  # 1GB
        return int(0.5 * 1024**3)  # 500MB (small)

    # GPT-2 models
    if "gpt2" in model_lower:
        if "xl" in model_lower:
            return int(6 * 1024**3)  # 6GB
        if "large" in model_lower:
            return int(3 * 1024**3)  # 3GB
        if "medium" in model_lower:
            return int(1.5 * 1024**3)  # 1.5GB
        return int(0.5 * 1024**3)  # 500MB

    # Default estimate based on task
    task_estimates = {
        "text-classification": int(1 * 1024**3),
        "token-classification": int(1 * 1024**3),
        "question-answering": int(1 * 1024**3),
        "summarization": int(2 * 1024**3),
        "text-generation": int(2 * 1024**3),
        "text2text-generation": int(2 * 1024**3),
        "fill-mask": int(1 * 1024**3),
        "zero-shot-classification": int(1 * 1024**3),
        "image-classification": int(1 * 1024**3),
        "object-detection": int(2 * 1024**3),
    }

    return task_estimates.get(task, int(1 * 1024**3))
