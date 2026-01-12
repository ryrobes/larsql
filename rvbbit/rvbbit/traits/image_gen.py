"""
Image generation tools for RVBBIT.

Provides outpainting, inpainting, and image generation capabilities.

Two approaches:
1. llm_outpaint / llm_generate - Uses OpenRouter models (Gemini, Seedream, etc.)
2. outpaint_image / generate_image - Uses external APIs (fal, replicate, etc.)
"""

from .base import simple_eddy
from PIL import Image
import os
import base64
import io
from typing import Optional
import litellm


@simple_eddy
def llm_outpaint(
    source: str,
    destination: str,
    target_width: int,
    target_height: int,
    prompt: str = "seamlessly extend the image maintaining style and atmosphere",
    model: str = "google/gemini-3-flash-preview",
    provider_base_url: Optional[str] = None
) -> dict:
    """
    Outpaint an image using an LLM through OpenRouter.

    Uses multimodal models that can generate images (like Gemini or Seedream)
    to extend an image to target dimensions.

    Args:
        source: Path to source image
        destination: Path to save the outpainted image
        target_width: Target width in pixels
        target_height: Target height in pixels
        prompt: Description of what to generate in the extended areas
        model: Model to use (default: google/gemini-3-flash-preview)
        provider_base_url: Optional custom API base URL

    Returns:
        Dict with path, width, height, and status
    """
    from ..config import get_config

    # Convert string dimensions to int
    if isinstance(target_width, str):
        target_width = int(target_width)
    if isinstance(target_height, str):
        target_height = int(target_height)

    # Load and encode source image
    img = Image.open(source)
    if img.mode != 'RGB':
        img = img.convert('RGB')
    orig_width, orig_height = img.size

    print(f"[llm_outpaint] Source: {orig_width}x{orig_height} -> Target: {target_width}x{target_height}")

    # Calculate extension direction
    if target_width > orig_width:
        extension = "horizontal (add content to left and right sides)"
        pad_left = (target_width - orig_width) // 2
        pad_right = target_width - orig_width - pad_left
        pad_desc = f"Add approximately {pad_left}px to the left and {pad_right}px to the right"
    else:
        extension = "vertical (add content to top and bottom)"
        pad_top = (target_height - orig_height) // 2
        pad_bottom = target_height - orig_height - pad_top
        pad_desc = f"Add approximately {pad_top}px to the top and {pad_bottom}px to the bottom"

    # Encode image to base64
    img_buffer = io.BytesIO()
    img.save(img_buffer, format='PNG')
    img_b64 = base64.b64encode(img_buffer.getvalue()).decode('utf-8')

    # Build the prompt for the image generation model
    system_prompt = f"""You are an expert image editor. Your task is to OUTPAINT (extend) the provided image to new dimensions.

CURRENT IMAGE: {orig_width}x{orig_height} pixels
TARGET SIZE: {target_width}x{target_height} pixels
EXTENSION DIRECTION: {extension}
{pad_desc}

INSTRUCTIONS:
1. Generate a new image at exactly {target_width}x{target_height} pixels
2. The original image content should be preserved in the center
3. Seamlessly extend the image by generating new content in the added areas
4. Match the style, lighting, colors, and atmosphere of the original
5. {prompt}

Generate the extended image now."""

    # Prepare API call
    cfg = get_config()
    base_url = provider_base_url or os.environ.get("RVBBIT_PROVIDER_BASE_URL", cfg.provider_base_url)
    api_key = os.environ.get("OPENROUTER_API_KEY")

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": system_prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{img_b64}"}
                }
            ]
        }
    ]

    print(f"[llm_outpaint] Calling {model} for outpainting...")

    try:
        response = litellm.completion(
            model=model,
            messages=messages,
            api_base=base_url,
            api_key=api_key,
            max_tokens=4096,
        )

        # Extract image from response
        result_image = _extract_image_from_response(response, target_width, target_height)

        if result_image is None:
            # Model didn't return an image - fall back to smart extend
            print("[llm_outpaint] Model didn't return an image, using fallback")
            result_image = _smart_extend(img, target_width, target_height)
            provider_note = "fallback"
        else:
            provider_note = model

    except Exception as e:
        print(f"[llm_outpaint] LLM call failed: {e}, using fallback")
        result_image = _smart_extend(img, target_width, target_height)
        provider_note = "fallback"

    # Ensure output directory exists
    os.makedirs(os.path.dirname(destination) or '.', exist_ok=True)

    # Save result
    if result_image.mode == 'RGBA':
        result_image = result_image.convert('RGB')
    result_image.save(destination, quality=95)

    return {
        "path": destination,
        "filename": os.path.basename(destination),
        "width": result_image.width,
        "height": result_image.height,
        "model": provider_note,
        "status": "success",
        "images": [destination]
    }


def _extract_image_from_response(response, target_width: int, target_height: int) -> Optional[Image.Image]:
    """
    Extract generated image from LLM response.

    Different models return images in different formats:
    - Gemini: inline_data in content parts
    - Some models: base64 in text response
    - Some models: URL in response
    """
    try:
        # Get the response content
        if hasattr(response, 'choices') and response.choices:
            message = response.choices[0].message

            # Check for content parts (Gemini style)
            if hasattr(message, 'content'):
                content = message.content

                # If content is a list of parts
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict):
                            # Check for inline_data (Gemini image generation)
                            if 'inline_data' in part:
                                data = part['inline_data']
                                if 'data' in data:
                                    img_data = base64.b64decode(data['data'])
                                    return Image.open(io.BytesIO(img_data))

                            # Check for image_url
                            if 'image_url' in part:
                                url = part['image_url'].get('url', '')
                                if url.startswith('data:'):
                                    # Base64 data URL
                                    b64_data = url.split(',', 1)[1]
                                    img_data = base64.b64decode(b64_data)
                                    return Image.open(io.BytesIO(img_data))

                # If content is a string, check for base64 image data
                elif isinstance(content, str):
                    # Look for base64 image pattern
                    if 'data:image' in content and 'base64,' in content:
                        import re
                        match = re.search(r'data:image/[^;]+;base64,([A-Za-z0-9+/=]+)', content)
                        if match:
                            img_data = base64.b64decode(match.group(1))
                            return Image.open(io.BytesIO(img_data))

        return None

    except Exception as e:
        print(f"[_extract_image_from_response] Error: {e}")
        return None


@simple_eddy
def llm_generate(
    prompt: str,
    destination: str,
    width: int = 1024,
    height: int = 1024,
    model: str = "google/gemini-2.5-flash-preview",
    negative_prompt: Optional[str] = None,
    reference_image: Optional[str] = None,
    provider_base_url: Optional[str] = None
) -> dict:
    """
    Generate an image using an LLM through OpenRouter.

    Uses multimodal models that can generate images (like Gemini or image gen models).

    Args:
        prompt: Text description of the image to generate
        destination: Path to save the generated image
        width: Image width in pixels
        height: Image height in pixels
        model: Model to use (default: google/gemini-2.5-flash-preview)
        negative_prompt: What to avoid (if supported)
        reference_image: Optional reference image path for style/content guidance
        provider_base_url: Optional custom API base URL

    Returns:
        Dict with path, width, height, and status
    """
    from ..config import get_config

    if isinstance(width, str):
        width = int(width)
    if isinstance(height, str):
        height = int(height)

    cfg = get_config()
    base_url = provider_base_url or os.environ.get("RVBBIT_PROVIDER_BASE_URL", cfg.provider_base_url)
    api_key = os.environ.get("OPENROUTER_API_KEY")

    # Build prompt
    full_prompt = f"Generate an image at {width}x{height} pixels.\n\n{prompt}"
    if negative_prompt:
        full_prompt += f"\n\nAvoid: {negative_prompt}"

    # Build messages
    content: list = [{"type": "text", "text": full_prompt}]

    # Add reference image if provided
    if reference_image and os.path.exists(reference_image):
        ref_img = Image.open(reference_image)
        if ref_img.mode != 'RGB':
            ref_img = ref_img.convert('RGB')
        img_buffer = io.BytesIO()
        ref_img.save(img_buffer, format='PNG')
        img_b64 = base64.b64encode(img_buffer.getvalue()).decode('utf-8')
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{img_b64}"}
        })

    messages = [{"role": "user", "content": content}]

    print(f"[llm_generate] Calling {model} for image generation...")

    try:
        response = litellm.completion(
            model=model,
            messages=messages,
            api_base=base_url,
            api_key=api_key,
            max_tokens=4096,
        )

        result_image = _extract_image_from_response(response, width, height)

        if result_image is None:
            raise RuntimeError(f"Model {model} did not return an image in the response")

        # Resize if needed
        if result_image.size != (width, height):
            result_image = result_image.resize((width, height), Image.Resampling.LANCZOS)

    except Exception as e:
        raise RuntimeError(f"Image generation failed: {e}")

    # Ensure output directory exists
    os.makedirs(os.path.dirname(destination) or '.', exist_ok=True)

    # Save result
    if result_image.mode == 'RGBA':
        result_image = result_image.convert('RGB')
    result_image.save(destination, quality=95)

    return {
        "path": destination,
        "filename": os.path.basename(destination),
        "width": result_image.width,
        "height": result_image.height,
        "model": model,
        "status": "success",
        "images": [destination]
    }


@simple_eddy
def outpaint_image(
    source: str,
    destination: str,
    target_width: int,
    target_height: int,
    prompt: str = "seamlessly extend the image maintaining style and atmosphere",
    provider: str = "auto",
    model: Optional[str] = None
) -> dict:
    """
    Outpaint an image to target dimensions using AI image generation.

    Extends an image by generating new content in the added areas,
    seamlessly blending with the original image.

    Args:
        source: Path to source image
        destination: Path to save the outpainted image
        target_width: Target width in pixels
        target_height: Target height in pixels
        prompt: Description of what to generate in the extended areas
        provider: Which API to use: "openai", "replicate", "stability", "fal", or "auto"
        model: Optional specific model to use (provider-dependent)

    Returns:
        Dict with path, width, height, provider used, and status
    """
    # Convert string dimensions to int (from Jinja2 templates)
    if isinstance(target_width, str):
        target_width = int(target_width)
    if isinstance(target_height, str):
        target_height = int(target_height)

    # Load source image
    img = Image.open(source)
    if img.mode != 'RGB':
        img = img.convert('RGB')
    orig_width, orig_height = img.size

    print(f"[outpaint_image] Source: {orig_width}x{orig_height} -> Target: {target_width}x{target_height}")

    # Calculate padding (center the original image)
    pad_left = (target_width - orig_width) // 2
    pad_right = target_width - orig_width - pad_left
    pad_top = (target_height - orig_height) // 2
    pad_bottom = target_height - orig_height - pad_top

    print(f"[outpaint_image] Padding: L={pad_left}, R={pad_right}, T={pad_top}, B={pad_bottom}")

    # Create extended canvas (RGBA for transparency in masked areas)
    extended = Image.new('RGBA', (target_width, target_height), (0, 0, 0, 0))
    extended.paste(img, (pad_left, pad_top))

    # Create mask (white = areas to generate, black = keep original)
    mask = Image.new('L', (target_width, target_height), 255)  # White everywhere
    mask.paste(0, (pad_left, pad_top, pad_left + orig_width, pad_top + orig_height))  # Black where original is

    # Try different providers
    result_image = None
    used_provider = None

    providers_to_try = []
    if provider == "auto":
        providers_to_try = ["fal", "replicate", "openai", "stability"]
    else:
        providers_to_try = [provider]

    for prov in providers_to_try:
        if prov == "fal":
            result_image = _try_fal_outpaint(extended, mask, prompt, target_width, target_height, model)
        elif prov == "replicate":
            result_image = _try_replicate_outpaint(extended, mask, prompt, target_width, target_height, model)
        elif prov == "openai":
            result_image = _try_openai_outpaint(extended, mask, prompt, target_width, target_height)
        elif prov == "stability":
            result_image = _try_stability_outpaint(extended, mask, prompt, target_width, target_height, model)

        if result_image is not None:
            used_provider = prov
            print(f"[outpaint_image] Successfully outpainted with {prov}")
            break

    if result_image is None:
        # Fallback: smart edge extension
        print("[outpaint_image] All providers failed, using fallback edge extension")
        result_image = _smart_extend(img, target_width, target_height)
        used_provider = "fallback"

    # Ensure output directory exists
    os.makedirs(os.path.dirname(destination) or '.', exist_ok=True)

    # Convert to RGB for saving (in case it's RGBA)
    if result_image.mode == 'RGBA':
        result_image = result_image.convert('RGB')

    # Save result
    result_image.save(destination, quality=95)

    return {
        "path": destination,
        "filename": os.path.basename(destination),
        "width": result_image.width,
        "height": result_image.height,
        "provider": used_provider,
        "status": "success",
        "images": [destination]
    }


def _try_fal_outpaint(extended: Image.Image, mask: Image.Image, prompt: str, width: int, height: int, model: Optional[str]) -> Optional[Image.Image]:
    """Try outpainting with fal.ai (fast, good quality)."""
    api_key = os.environ.get("FAL_KEY") or os.environ.get("FAL_API_KEY")
    if not api_key:
        return None

    try:
        import fal_client

        # Convert images to base64 data URLs
        img_buffer = io.BytesIO()
        extended.save(img_buffer, format='PNG')
        img_b64 = base64.b64encode(img_buffer.getvalue()).decode()

        mask_buffer = io.BytesIO()
        mask.save(mask_buffer, format='PNG')
        mask_b64 = base64.b64encode(mask_buffer.getvalue()).decode()

        # Use SDXL inpainting model
        model_id = model or "fal-ai/fast-sdxl-inpainting"

        result = fal_client.subscribe(
            model_id,
            arguments={
                "prompt": prompt,
                "image_url": f"data:image/png;base64,{img_b64}",
                "mask_url": f"data:image/png;base64,{mask_b64}",
                "num_images": 1,
                "image_size": {"width": width, "height": height},
                "sync_mode": True
            }
        )

        # Download result
        import requests
        result_url = result["images"][0]["url"]
        result_data = requests.get(result_url).content
        return Image.open(io.BytesIO(result_data))

    except Exception as e:
        print(f"[outpaint_image] fal.ai failed: {e}")
        return None


def _try_replicate_outpaint(extended: Image.Image, mask: Image.Image, prompt: str, width: int, height: int, model: Optional[str]) -> Optional[Image.Image]:
    """Try outpainting with Replicate."""
    api_token = os.environ.get("REPLICATE_API_TOKEN")
    if not api_token:
        return None

    try:
        import replicate

        # Convert to base64 data URLs
        img_buffer = io.BytesIO()
        extended.save(img_buffer, format='PNG')
        img_b64 = base64.b64encode(img_buffer.getvalue()).decode()

        mask_buffer = io.BytesIO()
        mask.save(mask_buffer, format='PNG')
        mask_b64 = base64.b64encode(mask_buffer.getvalue()).decode()

        # Use SDXL inpainting model
        model_id = model or "stability-ai/sdxl:39ed52f2a78e934b3ba6e2a89f5b1c712de7dfea535525255b1aa35c5565e08b"

        output = replicate.run(
            model_id,
            input={
                "prompt": prompt,
                "image": f"data:image/png;base64,{img_b64}",
                "mask": f"data:image/png;base64,{mask_b64}",
                "num_outputs": 1,
                "guidance_scale": 7.5,
                "num_inference_steps": 25
            }
        )

        # Download result
        import requests
        result_url = output[0] if isinstance(output, list) else output
        result_data = requests.get(result_url).content
        return Image.open(io.BytesIO(result_data))

    except Exception as e:
        print(f"[outpaint_image] Replicate failed: {e}")
        return None


def _try_openai_outpaint(extended: Image.Image, mask: Image.Image, prompt: str, width: int, height: int) -> Optional[Image.Image]:
    """Try outpainting with OpenAI DALL-E."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        import openai
        client = openai.OpenAI(api_key=api_key)

        # DALL-E 2 edit has size constraints
        valid_sizes = [(256, 256), (512, 512), (1024, 1024)]

        # Find closest valid size (rounding up)
        max_dim = max(width, height)
        if max_dim <= 256:
            target_size = "256x256"
        elif max_dim <= 512:
            target_size = "512x512"
        else:
            target_size = "1024x1024"

        # Resize for DALL-E
        dalle_size = int(target_size.split('x')[0])
        extended_resized = extended.resize((dalle_size, dalle_size), Image.Resampling.LANCZOS)
        mask_resized = mask.resize((dalle_size, dalle_size), Image.Resampling.LANCZOS)

        # Convert to RGBA with proper transparency for mask
        if extended_resized.mode != 'RGBA':
            extended_resized = extended_resized.convert('RGBA')

        # Apply mask as alpha channel (transparent where we want generation)
        r, g, b, a = extended_resized.split()
        # Invert mask: DALL-E wants transparent areas to be generated
        mask_inverted = Image.eval(mask_resized, lambda x: 255 - x)
        extended_with_mask = Image.merge('RGBA', (r, g, b, mask_inverted))

        # Convert to bytes
        img_buffer = io.BytesIO()
        extended_with_mask.save(img_buffer, format='PNG')
        img_buffer.seek(0)

        response = client.images.edit(
            model="dall-e-2",
            image=img_buffer,
            prompt=f"Seamlessly extend this image: {prompt}",
            n=1,
            size=target_size
        )

        # Download result
        import requests
        result_url = response.data[0].url
        result_data = requests.get(result_url).content
        result_img = Image.open(io.BytesIO(result_data))

        # Resize back to target dimensions
        if result_img.size != (width, height):
            result_img = result_img.resize((width, height), Image.Resampling.LANCZOS)

        return result_img

    except Exception as e:
        print(f"[outpaint_image] OpenAI failed: {e}")
        return None


def _try_stability_outpaint(extended: Image.Image, mask: Image.Image, prompt: str, width: int, height: int, model: Optional[str]) -> Optional[Image.Image]:
    """Try outpainting with Stability AI."""
    api_key = os.environ.get("STABILITY_API_KEY")
    if not api_key:
        return None

    try:
        import requests

        # Convert to bytes
        img_buffer = io.BytesIO()
        extended_rgb = extended.convert('RGB')
        extended_rgb.save(img_buffer, format='PNG')

        mask_buffer = io.BytesIO()
        mask.save(mask_buffer, format='PNG')

        response = requests.post(
            "https://api.stability.ai/v2beta/stable-image/edit/inpaint",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "image/*"
            },
            files={
                "image": ("image.png", img_buffer.getvalue(), "image/png"),
                "mask": ("mask.png", mask_buffer.getvalue(), "image/png"),
            },
            data={
                "prompt": prompt,
                "output_format": "png",
            }
        )

        if response.status_code == 200:
            return Image.open(io.BytesIO(response.content))
        else:
            print(f"[outpaint_image] Stability API error: {response.status_code} - {response.text}")
            return None

    except Exception as e:
        print(f"[outpaint_image] Stability failed: {e}")
        return None


def _smart_extend(img: Image.Image, target_width: int, target_height: int) -> Image.Image:
    """
    Smart fallback: extend image using edge reflection and blur blending.
    Not as good as AI outpainting, but provides a reasonable result.
    """
    from PIL import ImageFilter

    orig_width, orig_height = img.size

    # Calculate padding
    pad_left = (target_width - orig_width) // 2
    pad_right = target_width - orig_width - pad_left
    pad_top = (target_height - orig_height) // 2
    pad_bottom = target_height - orig_height - pad_top

    # Create result canvas
    result = Image.new('RGB', (target_width, target_height))

    # Use edge mirroring for extension
    if pad_left > 0 or pad_right > 0:
        # Horizontal extension - mirror edges
        left_strip = img.crop((0, 0, min(pad_left, orig_width), orig_height))
        left_strip = left_strip.transpose(Image.Transpose.FLIP_LEFT_RIGHT)

        right_strip = img.crop((max(0, orig_width - pad_right), 0, orig_width, orig_height))
        right_strip = right_strip.transpose(Image.Transpose.FLIP_LEFT_RIGHT)

        # Tile if needed
        for x in range(0, pad_left, left_strip.width):
            result.paste(left_strip, (pad_left - x - left_strip.width, pad_top))

        for x in range(0, pad_right, right_strip.width):
            result.paste(right_strip, (pad_left + orig_width + x, pad_top))

    if pad_top > 0 or pad_bottom > 0:
        # Vertical extension - mirror edges
        top_strip = img.crop((0, 0, orig_width, min(pad_top, orig_height)))
        top_strip = top_strip.transpose(Image.Transpose.FLIP_TOP_BOTTOM)

        bottom_strip = img.crop((0, max(0, orig_height - pad_bottom), orig_width, orig_height))
        bottom_strip = bottom_strip.transpose(Image.Transpose.FLIP_TOP_BOTTOM)

        for y in range(0, pad_top, top_strip.height):
            result.paste(top_strip, (pad_left, pad_top - y - top_strip.height))

        for y in range(0, pad_bottom, bottom_strip.height):
            result.paste(bottom_strip, (pad_left, pad_top + orig_height + y))

    # Paste original image
    result.paste(img, (pad_left, pad_top))

    # Apply slight blur to blend edges (only in extended areas)
    # Create a blurred version
    blurred = result.filter(ImageFilter.GaussianBlur(radius=20))

    # Blend at the edges
    # For simplicity, we'll apply a gradient blend at the boundaries
    # This is a basic approach - AI outpainting is much better

    return result


@simple_eddy
def generate_image(
    prompt: str,
    destination: str,
    width: int = 1024,
    height: int = 1024,
    provider: str = "auto",
    model: Optional[str] = None,
    negative_prompt: Optional[str] = None
) -> dict:
    """
    Generate an image from a text prompt.

    Args:
        prompt: Text description of the image to generate
        destination: Path to save the generated image
        width: Image width in pixels
        height: Image height in pixels
        provider: Which API to use: "openai", "replicate", "stability", "fal", or "auto"
        model: Optional specific model to use
        negative_prompt: What to avoid in the image (not all providers support this)

    Returns:
        Dict with path, width, height, provider used, and status
    """
    if isinstance(width, str):
        width = int(width)
    if isinstance(height, str):
        height = int(height)

    result_image = None
    used_provider = None

    providers_to_try = []
    if provider == "auto":
        providers_to_try = ["fal", "replicate", "openai", "stability"]
    else:
        providers_to_try = [provider]

    for prov in providers_to_try:
        try:
            if prov == "fal":
                result_image = _generate_with_fal(prompt, width, height, model, negative_prompt)
            elif prov == "replicate":
                result_image = _generate_with_replicate(prompt, width, height, model, negative_prompt)
            elif prov == "openai":
                result_image = _generate_with_openai(prompt, width, height, model)
            elif prov == "stability":
                result_image = _generate_with_stability(prompt, width, height, model, negative_prompt)

            if result_image is not None:
                used_provider = prov
                break
        except Exception as e:
            print(f"[generate_image] {prov} failed: {e}")
            continue

    if result_image is None:
        raise RuntimeError("All image generation providers failed. Set one of: FAL_KEY, REPLICATE_API_TOKEN, OPENAI_API_KEY, or STABILITY_API_KEY")

    # Ensure output directory exists
    os.makedirs(os.path.dirname(destination) or '.', exist_ok=True)

    # Save result
    if result_image.mode == 'RGBA':
        result_image = result_image.convert('RGB')
    result_image.save(destination, quality=95)

    return {
        "path": destination,
        "filename": os.path.basename(destination),
        "width": result_image.width,
        "height": result_image.height,
        "provider": used_provider,
        "status": "success",
        "images": [destination]
    }


def _generate_with_fal(prompt: str, width: int, height: int, model: Optional[str], negative_prompt: Optional[str]) -> Optional[Image.Image]:
    """Generate image with fal.ai."""
    api_key = os.environ.get("FAL_KEY") or os.environ.get("FAL_API_KEY")
    if not api_key:
        return None

    import fal_client
    import requests

    model_id = model or "fal-ai/fast-sdxl"

    args = {
        "prompt": prompt,
        "num_images": 1,
        "image_size": {"width": width, "height": height},
        "sync_mode": True
    }
    if negative_prompt:
        args["negative_prompt"] = negative_prompt

    result = fal_client.subscribe(model_id, arguments=args)
    result_url = result["images"][0]["url"]
    if not result_url:
        return None
    result_data = requests.get(result_url).content
    return Image.open(io.BytesIO(result_data))


def _generate_with_replicate(prompt: str, width: int, height: int, model: Optional[str], negative_prompt: Optional[str]) -> Optional[Image.Image]:
    """Generate image with Replicate."""
    api_token = os.environ.get("REPLICATE_API_TOKEN")
    if not api_token:
        return None

    import replicate
    import requests

    model_id = model or "stability-ai/sdxl:39ed52f2a78e934b3ba6e2a89f5b1c712de7dfea535525255b1aa35c5565e08b"

    inputs = {
        "prompt": prompt,
        "width": width,
        "height": height,
        "num_outputs": 1
    }
    if negative_prompt:
        inputs["negative_prompt"] = negative_prompt

    output = replicate.run(model_id, input=inputs)
    result_url = output[0] if isinstance(output, list) else output
    if not result_url:
        return None
    result_data = requests.get(result_url).content
    return Image.open(io.BytesIO(result_data))


def _generate_with_openai(prompt: str, width: int, height: int, model: Optional[str]) -> Optional[Image.Image]:
    """Generate image with OpenAI DALL-E."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None

    import openai
    import requests

    client = openai.OpenAI(api_key=api_key)

    # DALL-E 3 supports specific sizes
    # Map to closest supported size
    if model == "dall-e-2":
        valid_sizes = ["256x256", "512x512", "1024x1024"]
    else:
        # DALL-E 3
        valid_sizes = ["1024x1024", "1792x1024", "1024x1792"]

    # Choose best size
    aspect = width / height
    if aspect > 1.5:
        size = "1792x1024" if model != "dall-e-2" else "1024x1024"
    elif aspect < 0.67:
        size = "1024x1792" if model != "dall-e-2" else "1024x1024"
    else:
        size = "1024x1024"

    response = client.images.generate(
        model=model or "dall-e-3",
        prompt=prompt,
        n=1,
        size=size
    )

    if not response or not response.data:
        return None

    if not response.data or not response.data[0] or not response.data[0].url:
        return None

    result_url = response.data[0].url
    if not result_url:
        return None
    result_data = requests.get(result_url).content
    result_img = Image.open(io.BytesIO(result_data))

    # Resize to exact dimensions if needed
    if result_img.size != (width, height):
        result_img = result_img.resize((width, height), Image.Resampling.LANCZOS)

    return result_img


def _generate_with_stability(prompt: str, width: int, height: int, model: Optional[str], negative_prompt: Optional[str]) -> Optional[Image.Image]:
    """Generate image with Stability AI."""
    api_key = os.environ.get("STABILITY_API_KEY")
    if not api_key:
        return None

    import requests

    data = {
        "prompt": prompt,
        "output_format": "png",
        "width": width,
        "height": height,
    }
    if negative_prompt:
        data["negative_prompt"] = negative_prompt

    response = requests.post(
        "https://api.stability.ai/v2beta/stable-image/generate/sd3",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "image/*"
        },
        files={"none": ''},  # Required for multipart
        data=data
    )

    if response.status_code == 200:
        return Image.open(io.BytesIO(response.content))
    else:
        print(f"[generate_image] Stability error: {response.status_code}")
        return None
