import base64
import os
import shutil
import sys
from io import BytesIO
from typing import Optional

try:
    from PIL import Image
except ImportError:
    Image = None


def _detect_terminal() -> str:
    """Return a simple capability string: 'kitty', 'iterm2', or 'ansi'."""
    term = os.environ.get("TERM", "").lower()
    term_program = os.environ.get("TERM_PROGRAM", "")
    if "kitty" in term or os.environ.get("KITTY_INSTALLATION_DIR"):
        return "kitty"
    if term_program == "iTerm.app":
        return "iterm2"
    return "ansi"


def _get_terminal_size() -> tuple[int, int]:
    """Return terminal size as (columns, rows)."""
    try:
        size = shutil.get_terminal_size()
        return size.columns, size.lines
    except OSError:
        return 80, 24


def _resize_for_terminal(img: Image.Image, max_cols: int, use_half_blocks: bool = True) -> Image.Image:
    """
    Resize image to fit inside max_cols terminal columns.
    If use_half_blocks is True, treat each terminal char as 1x2 pixels (█ trick).
    """
    w, h = img.size
    target_width = max(1, max_cols)

    if use_half_blocks:
        aspect = h / w
        target_height_chars = int(aspect * target_width * 0.5)
        target_height = max(1, target_height_chars * 2)
    else:
        aspect = h / w
        target_height = max(1, int(aspect * target_width))

    return img.resize((target_width, target_height), Image.LANCZOS)


def _render_ansi_truecolor(img: Image.Image) -> str:
    """
    Render image as truecolor ANSI using foreground+background with '▀' to encode two pixels per cell.
    """
    img = img.convert("RGB")
    w, h = img.size

    out_lines = []
    for y in range(0, h, 2):
        line_parts = []
        for x in range(w):
            r1, g1, b1 = img.getpixel((x, y))
            if y + 1 < h:
                r2, g2, b2 = img.getpixel((x, y + 1))
            else:
                r2, g2, b2 = r1, g1, b1
            line_parts.append(
                f"\033[38;2;{r1};{g1};{b1}m\033[48;2;{r2};{g2};{b2}m▀"
            )
        line_parts.append("\033[0m")
        out_lines.append("".join(line_parts))
    return "\n".join(out_lines)


def _encode_image_base64(img: Image.Image, fmt: str = "PNG") -> str:
    buf = BytesIO()
    img.save(buf, format=fmt)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _render_kitty(img: Image.Image, cols: Optional[int] = None, rows: Optional[int] = None) -> str:
    """
    Render an image using Kitty's graphics protocol.
    Docs: https://sw.kovidgoyal.net/kitty/graphics-protocol/
    """
    img = img.convert("RGBA")
    data_b64 = _encode_image_base64(img, fmt="PNG")
    params = [
        "a=T",  # transmit and display
        "f=100",  # preserve aspect ratio
        "t=d",  # data follows
        f"s={img.width}",  # pixel width
        f"v={img.height}",  # pixel height
    ]
    if cols:
        params.append(f"c={cols}")
    if rows:
        params.append(f"r={rows}")

    # Chunk to avoid terminals echoing giant payloads
    chunk_size = 4096
    chunks = [data_b64[i:i + chunk_size] for i in range(0, len(data_b64), chunk_size)]
    sequences = []
    for i, chunk in enumerate(chunks):
        chunk_params = list(params)
        if i < len(chunks) - 1:
            chunk_params.append("m=1")  # more chunks follow
        sequences.append(f"\033_G{','.join(chunk_params)};{chunk}\033\\")
    return "".join(sequences)


def _render_iterm2(img: Image.Image) -> str:
    """
    Render inline image in iTerm2.
    Docs: https://iterm2.com/documentation-images.html
    """
    img = img.convert("RGBA")
    data_b64 = _encode_image_base64(img, fmt="PNG")
    return f"\033]1337;File=inline=1;width=auto;height=auto;preserveAspectRatio=1:{data_b64}\a"


def render_image_in_terminal(path: str, max_width: Optional[int] = None, force_mode: Optional[str] = None) -> None:
    """
    High-level renderer that picks terminal capability and displays an image.
    force_mode: 'kitty', 'iterm2', or 'ansi' (auto-detect if None)
    """
    if Image is None:
        raise ImportError("Pillow is required for image rendering. Install with `pip install pillow`.")

    if not os.path.exists(path):
        raise FileNotFoundError(f"Image not found: {path}")

    with Image.open(path) as image:
        img = image.copy()

    term_mode = force_mode or _detect_terminal()
    cols, rows = _get_terminal_size()
    width_limit = max_width if max_width is not None else cols
    width_limit = max(1, min(width_limit, cols))

    if term_mode == "kitty":
        # Fit into visible grid using cell counts; shrink columns if height would overflow.
        max_cols, max_rows = cols, rows
        target_cols = min(width_limit, max_cols)
        # Approximate terminal cell aspect ratio (~2:1 height:width) for height check only.
        aspect = img.height / img.width if img.width else 1
        estimated_rows = aspect * target_cols * 0.5
        if estimated_rows > max_rows and estimated_rows > 0:
            scale = max_rows / estimated_rows
            target_cols = max(1, int(target_cols * scale))

        # Send near-native size to Kitty, only clamp if extremely large to avoid huge payloads.
        max_pixels = 2_000_000  # safety cap (~1600x1250)
        pixel_count = img.width * img.height
        if pixel_count > max_pixels:
            # Downscale proportionally toward the target cols without going below it.
            scale = (max_pixels / pixel_count) ** 0.5
            scaled_width = max(target_cols, int(img.width * scale))
            resized = _resize_for_terminal(img, scaled_width, use_half_blocks=False)
        else:
            resized = img

        sys.stdout.write(_render_kitty(resized, cols=target_cols, rows=None))
        sys.stdout.flush()
    elif term_mode == "iterm2":
        resized = _resize_for_terminal(img, width_limit, use_half_blocks=False)
        sys.stdout.write(_render_iterm2(resized))
        sys.stdout.flush()
    else:
        resized = _resize_for_terminal(img, width_limit, use_half_blocks=True)
        ansi = _render_ansi_truecolor(resized)
        print(ansi)
