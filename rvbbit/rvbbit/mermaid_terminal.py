import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from rvbbit.terminal_image import render_image_in_terminal


class MermaidRenderError(RuntimeError):
    pass


def _ensure_mmdc() -> str:
    repo_root = Path(__file__).resolve().parents[1]
    frontend_mmdc = repo_root / "extras" / "ui" / "frontend" / "node_modules" / ".bin" / "mmdc"

    takes = [
        str(frontend_mmdc),
        shutil.which("mmdc"),
    ]

    mmdc_path = next((c for c in takes if c and os.path.exists(c)), None)
    if not mmdc_path:
        raise MermaidRenderError(
            "Mermaid CLI (`mmdc`) not found. Install with `npm --prefix dashboard/frontend install @mermaid-js/mermaid-cli` (or add it to PATH)."
        )
    return mmdc_path


def render_mermaid_content_to_png(mermaid_content: str, output_path: Optional[Path] = None) -> Path:
    """
    Render mermaid text to a PNG using mermaid-cli (mmdc).
    Returns the output Path.
    """
    mmdc = _ensure_mmdc()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        input_file = tmpdir_path / "diagram.mmd"
        input_file.write_text(mermaid_content, encoding="utf-8")

        out_path = Path(output_path) if output_path else tmpdir_path / "diagram.png"

        cmd = [
            mmdc,
            "-i",
            str(input_file),
            "-o",
            str(out_path),
            "-b",
            "transparent",
        ]

        try:
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as e:
            raise MermaidRenderError(
                f"Mermaid CLI failed ({e.returncode}): {e.stderr.decode('utf-8', errors='ignore')[:400]}"
            )

        # If caller provided an output_path outside the temp dir, file already there.
        if output_path:
            return out_path

        # Copy to a temp file the caller can read after the temp dir context ends
        final_tmp = Path(tempfile.mkstemp(suffix=".png")[1])
        out_path.replace(final_tmp)
        return final_tmp


def render_mermaid_file_to_png(mermaid_path: Path, output_path: Optional[Path] = None) -> Path:
    content = Path(mermaid_path).read_text(encoding="utf-8")
    return render_mermaid_content_to_png(content, output_path=output_path)


def render_mermaid_in_terminal(
    mermaid_source: str,
    max_width: Optional[int] = None,
    force_mode: Optional[str] = None,
    is_path: bool = False,
) -> None:
    """
    Render mermaid (string or file) to PNG and display in the terminal using the terminal image renderer.
    """
    if is_path or os.path.exists(mermaid_source):
        png_path = render_mermaid_file_to_png(Path(mermaid_source))
    else:
        png_path = render_mermaid_content_to_png(mermaid_source)

    try:
        render_image_in_terminal(str(png_path), max_width=max_width, force_mode=force_mode)
    finally:
        try:
            os.remove(png_path)
        except OSError:
            pass
