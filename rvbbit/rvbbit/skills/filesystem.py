"""
Filesystem operations for agent autonomy.

Basic file operations: read, write, list, append.
These operate on the local filesystem with safety guards.
"""

import os
from pathlib import Path
from typing import Optional
from .base import simple_eddy
from ..logs import log_message


def _safe_path(path: str) -> str:
    """
    Resolve path and perform basic safety checks.
    Returns absolute path string.
    """
    # Expand user home directory
    expanded = os.path.expanduser(path)
    # Resolve to absolute path
    resolved = os.path.abspath(expanded)
    return resolved


def _check_path_safety(path: str) -> Optional[str]:
    """
    Check for obviously dangerous paths.
    Returns error message if unsafe, None if safe.
    """
    resolved = _safe_path(path)

    # Block writes to critical system directories
    dangerous_prefixes = [
        '/etc/', '/bin/', '/sbin/', '/usr/bin/', '/usr/sbin/',
        '/boot/', '/proc/', '/sys/', '/dev/',
    ]

    for prefix in dangerous_prefixes:
        if resolved.startswith(prefix):
            return f"Error: Cannot modify system path: {prefix}"

    return None


@simple_eddy
def read_file(path: str, encoding: str = "utf-8") -> str:
    """
    Read the contents of a file.

    Args:
        path: Path to the file (absolute or relative). Supports ~ for home directory.
        encoding: Text encoding (default: utf-8). Use 'binary' for raw bytes as hex.

    Returns:
        File contents as string, or error message.

    Examples:
        - Read text file: read_file("/home/user/notes.txt")
        - Read with encoding: read_file("data.csv", encoding="latin-1")
        - Read home file: read_file("~/documents/file.txt")
    """
    resolved = _safe_path(path)

    log_message(None, "system", f"read_file: {resolved}",
                metadata={"tool": "read_file", "path": resolved})

    if not os.path.exists(resolved):
        return f"Error: File not found: {resolved}"

    if not os.path.isfile(resolved):
        return f"Error: Path is not a file: {resolved}"

    try:
        if encoding == "binary":
            with open(resolved, "rb") as f:
                content = f.read()
            # Return hex representation for binary files
            if len(content) > 10000:
                return f"Binary file ({len(content)} bytes). First 1000 bytes as hex:\n{content[:1000].hex()}"
            return f"Binary file ({len(content)} bytes) as hex:\n{content.hex()}"
        else:
            with open(resolved, "r", encoding=encoding) as f:
                content = f.read()

            # Truncate very large files with notice
            if len(content) > 100000:
                return f"File truncated (total {len(content)} chars). First 100000 chars:\n{content[:100000]}"

            return content

    except UnicodeDecodeError as e:
        return f"Error: Cannot decode file with {encoding} encoding. Try encoding='binary' or encoding='latin-1'. Details: {e}"
    except PermissionError:
        return f"Error: Permission denied reading: {resolved}"
    except Exception as e:
        return f"Error reading file: {type(e).__name__}: {e}"


@simple_eddy
def write_file(path: str, content: str, encoding: str = "utf-8") -> str:
    """
    Write content to a file, creating directories if needed.

    WARNING: This will overwrite existing files without confirmation.

    Args:
        path: Path to the file (absolute or relative). Supports ~ for home directory.
        content: The text content to write.
        encoding: Text encoding (default: utf-8).

    Returns:
        Success message with bytes written, or error message.

    Examples:
        - Write new file: write_file("/tmp/output.txt", "Hello World")
        - Write with path: write_file("~/notes/idea.md", "# My Idea\\n...")
    """
    resolved = _safe_path(path)

    # Safety check
    safety_error = _check_path_safety(resolved)
    if safety_error:
        return safety_error

    log_message(None, "system", f"write_file: {resolved} ({len(content)} chars)",
                metadata={"tool": "write_file", "path": resolved, "content_length": len(content)})

    try:
        # Create parent directories if they don't exist
        parent = os.path.dirname(resolved)
        if parent and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)
            log_message(None, "system", f"write_file: created directory {parent}",
                        metadata={"tool": "write_file", "created_dir": parent})

        with open(resolved, "w", encoding=encoding) as f:
            bytes_written = f.write(content)

        return f"Successfully wrote {bytes_written} characters to {resolved}"

    except PermissionError:
        return f"Error: Permission denied writing to: {resolved}"
    except Exception as e:
        return f"Error writing file: {type(e).__name__}: {e}"


@simple_eddy
def append_file(path: str, content: str, encoding: str = "utf-8") -> str:
    """
    Append content to an existing file, or create if it doesn't exist.

    Args:
        path: Path to the file (absolute or relative). Supports ~ for home directory.
        content: The text content to append.
        encoding: Text encoding (default: utf-8).

    Returns:
        Success message, or error message.

    Examples:
        - Append to log: append_file("/tmp/app.log", "New entry\\n")
        - Add to notes: append_file("~/notes.txt", "\\n- New item")
    """
    resolved = _safe_path(path)

    # Safety check
    safety_error = _check_path_safety(resolved)
    if safety_error:
        return safety_error

    log_message(None, "system", f"append_file: {resolved} ({len(content)} chars)",
                metadata={"tool": "append_file", "path": resolved, "content_length": len(content)})

    try:
        # Create parent directories if they don't exist
        parent = os.path.dirname(resolved)
        if parent and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)

        with open(resolved, "a", encoding=encoding) as f:
            f.write(content)

        return f"Successfully appended {len(content)} characters to {resolved}"

    except PermissionError:
        return f"Error: Permission denied writing to: {resolved}"
    except Exception as e:
        return f"Error appending to file: {type(e).__name__}: {e}"


@simple_eddy
def list_files(path: str = ".", pattern: str = "*", recursive: bool = False) -> str:
    """
    List files and directories at a path.

    Args:
        path: Directory path to list (default: current directory). Supports ~ for home.
        pattern: Glob pattern to filter results (default: "*" for all).
                 Examples: "*.py", "*.txt", "test_*"
        recursive: If True, search recursively in subdirectories (default: False).

    Returns:
        Formatted listing of files/directories, or error message.

    Examples:
        - List current dir: list_files()
        - List home: list_files("~")
        - Find Python files: list_files(".", "*.py")
        - Recursive search: list_files("/project", "*.js", recursive=True)
    """
    resolved = _safe_path(path)

    log_message(None, "system", f"list_files: {resolved} (pattern={pattern}, recursive={recursive})",
                metadata={"tool": "list_files", "path": resolved, "pattern": pattern, "recursive": recursive})

    if not os.path.exists(resolved):
        return f"Error: Path not found: {resolved}"

    if not os.path.isdir(resolved):
        return f"Error: Path is not a directory: {resolved}"

    try:
        p = Path(resolved)

        if recursive:
            matches = list(p.rglob(pattern))
        else:
            matches = list(p.glob(pattern))

        # Sort: directories first, then files, both alphabetically
        dirs = sorted([m for m in matches if m.is_dir()])
        files = sorted([m for m in matches if m.is_file()])

        lines = []
        lines.append(f"Directory: {resolved}")
        lines.append(f"Pattern: {pattern}" + (" (recursive)" if recursive else ""))
        lines.append(f"Found: {len(dirs)} directories, {len(files)} files")
        lines.append("")

        # List directories
        if dirs:
            lines.append("Directories:")
            for d in dirs[:100]:  # Limit to 100
                rel_path = d.relative_to(resolved) if d != p else d.name
                lines.append(f"  📁 {rel_path}/")
            if len(dirs) > 100:
                lines.append(f"  ... and {len(dirs) - 100} more directories")

        # List files with sizes
        if files:
            lines.append("\nFiles:")
            for f in files[:200]:  # Limit to 200
                rel_path = f.relative_to(resolved)
                size = f.stat().st_size
                size_str = _format_size(size)
                lines.append(f"  📄 {rel_path} ({size_str})")
            if len(files) > 200:
                lines.append(f"  ... and {len(files) - 200} more files")

        if not dirs and not files:
            lines.append("(no matches found)")

        return "\n".join(lines)

    except PermissionError:
        return f"Error: Permission denied accessing: {resolved}"
    except Exception as e:
        return f"Error listing directory: {type(e).__name__}: {e}"


@simple_eddy
def file_info(path: str) -> str:
    """
    Get detailed information about a file or directory.

    Args:
        path: Path to the file or directory. Supports ~ for home directory.

    Returns:
        Detailed file information including size, timestamps, permissions.

    Examples:
        - Get file info: file_info("/etc/passwd")
        - Check directory: file_info("~/projects")
    """
    resolved = _safe_path(path)

    log_message(None, "system", f"file_info: {resolved}",
                metadata={"tool": "file_info", "path": resolved})

    if not os.path.exists(resolved):
        return f"Error: Path not found: {resolved}"

    try:
        import stat
        from datetime import datetime

        st = os.stat(resolved)

        info = []
        info.append(f"Path: {resolved}")
        info.append(f"Type: {'Directory' if os.path.isdir(resolved) else 'File'}")
        info.append(f"Size: {_format_size(st.st_size)} ({st.st_size} bytes)")

        # Timestamps
        mtime = datetime.fromtimestamp(st.st_mtime).isoformat()
        atime = datetime.fromtimestamp(st.st_atime).isoformat()
        ctime = datetime.fromtimestamp(st.st_ctime).isoformat()
        info.append(f"Modified: {mtime}")
        info.append(f"Accessed: {atime}")
        info.append(f"Created: {ctime}")

        # Permissions (Unix-style)
        mode = st.st_mode
        perms = stat.filemode(mode)
        info.append(f"Permissions: {perms}")

        # Owner (if available)
        try:
            import pwd
            import grp
            owner = pwd.getpwuid(st.st_uid).pw_name
            group = grp.getgrgid(st.st_gid).gr_name
            info.append(f"Owner: {owner}:{group}")
        except (ImportError, KeyError):
            info.append(f"Owner UID: {st.st_uid}, GID: {st.st_gid}")

        # For directories, count contents
        if os.path.isdir(resolved):
            try:
                contents = os.listdir(resolved)
                num_files = sum(1 for c in contents if os.path.isfile(os.path.join(resolved, c)))
                num_dirs = sum(1 for c in contents if os.path.isdir(os.path.join(resolved, c)))
                info.append(f"Contents: {num_files} files, {num_dirs} directories")
            except PermissionError:
                info.append("Contents: (permission denied)")

        return "\n".join(info)

    except PermissionError:
        return f"Error: Permission denied accessing: {resolved}"
    except Exception as e:
        return f"Error getting file info: {type(e).__name__}: {e}"


def _format_size(size: int) -> str:
    """Format byte size as human-readable string."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != 'B' else f"{size} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


# Supported image extensions for read_image
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.tiff', '.tif'}


@simple_eddy
def read_image(path: str) -> dict:
    """
    Read an image file for vision model processing.

    The image will be automatically encoded and injected into the LLM conversation
    as a multi-modal message. The runner handles resizing (max 1280px) and encoding.

    Args:
        path: Path to the image file (absolute or relative). Supports ~ for home directory.
              Supported formats: PNG, JPG, JPEG, GIF, WEBP, BMP, TIFF.

    Returns:
        Image data structure that the runner will process into a vision message.

    Examples:
        - Read a product photo: read_image("/data/products/item_001.jpg")
        - Read from home: read_image("~/screenshots/screenshot.png")
        - Analyze a chart: read_image("./charts/sales_q4.png")
    """
    resolved = _safe_path(path)

    log_message(None, "system", f"read_image: {resolved}",
                metadata={"tool": "read_image", "path": resolved})

    if not os.path.exists(resolved):
        return {"error": f"Image not found: {resolved}"}

    if not os.path.isfile(resolved):
        return {"error": f"Path is not a file: {resolved}"}

    # Check extension
    ext = os.path.splitext(resolved)[1].lower()
    if ext not in IMAGE_EXTENSIONS:
        return {"error": f"Unsupported image format: {ext}. Supported: {', '.join(sorted(IMAGE_EXTENSIONS))}"}

    # Get file size for the content message
    size = os.path.getsize(resolved)
    size_str = _format_size(size)

    # Return standard image protocol - runner handles encoding and injection
    return {
        "content": f"Loaded image: {os.path.basename(resolved)} ({size_str})",
        "images": [resolved]
    }


@simple_eddy
def edit_file(path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    """
    Perform surgical edits on a file by replacing specific text.

    This is safer than write_file for making targeted changes - it finds and replaces
    specific text rather than overwriting the entire file.

    Args:
        path: Path to the file (absolute or relative). Supports ~ for home directory.
        old_string: The exact text to find and replace. Must be unique in the file
                    unless replace_all=True.
        new_string: The text to replace old_string with. Can be empty to delete text.
        replace_all: If True, replace ALL occurrences. If False (default), the old_string
                     must appear exactly once in the file (safety check).

    Returns:
        Success message with number of replacements, or error message.

    Examples:
        - Fix a typo: edit_file("doc.md", "teh", "the")
        - Update version: edit_file("package.json", '"version": "1.0.0"', '"version": "1.1.0"')
        - Delete a line: edit_file("config.py", "DEBUG = True\\n", "")
        - Replace all: edit_file("code.py", "old_func", "new_func", replace_all=True)
    """
    resolved = _safe_path(path)

    # Safety check
    safety_error = _check_path_safety(resolved)
    if safety_error:
        return safety_error

    if not os.path.exists(resolved):
        return f"Error: File not found: {resolved}"

    if not os.path.isfile(resolved):
        return f"Error: Path is not a file: {resolved}"

    log_message(None, "system", f"edit_file: {resolved} (old={len(old_string)} chars, new={len(new_string)} chars, replace_all={replace_all})",
                metadata={"tool": "edit_file", "path": resolved, "old_len": len(old_string), "new_len": len(new_string), "replace_all": replace_all})

    try:
        # Read current content
        with open(resolved, "r", encoding="utf-8") as f:
            content = f.read()

        # Count occurrences
        count = content.count(old_string)

        if count == 0:
            # Provide helpful context for debugging
            preview = old_string[:100] + "..." if len(old_string) > 100 else old_string
            return f"Error: old_string not found in file.\nSearched for: {repr(preview)}\nFile: {resolved}"

        if count > 1 and not replace_all:
            return f"Error: old_string appears {count} times in file. Use replace_all=True to replace all occurrences, or provide a more specific/unique string."

        # Perform replacement
        new_content = content.replace(old_string, new_string) if replace_all else content.replace(old_string, new_string, 1)

        # Write back
        with open(resolved, "w", encoding="utf-8") as f:
            f.write(new_content)

        replacements = count if replace_all else 1
        log_message(None, "system", f"edit_file: success, {replacements} replacement(s)",
                    metadata={"tool": "edit_file", "path": resolved, "replacements": replacements})

        return f"Successfully edited {resolved}: {replacements} replacement(s) made."

    except UnicodeDecodeError as e:
        return f"Error: Cannot read file as UTF-8. Details: {e}"
    except PermissionError:
        return f"Error: Permission denied editing: {resolved}"
    except Exception as e:
        return f"Error editing file: {type(e).__name__}: {e}"


@simple_eddy
def search_files(
    pattern: str,
    path: str = ".",
    file_pattern: str | None = None,
    context_lines: int = 2,
    max_results: int = 50,
    case_sensitive: bool = True
) -> str:
    """
    Search for text patterns in files using ripgrep (rg) or fallback to grep.

    This is the primary tool for exploring codebases - find where functions are defined,
    where variables are used, grep through logs, etc.

    Args:
        pattern: Regex pattern to search for. Supports full regex syntax.
                 Examples: "def main", "import.*json", "TODO|FIXME", "class\\s+\\w+"
        path: Directory to search in (default: current directory). Supports ~ for home.
        file_pattern: Optional glob to filter files. Examples: "*.py", "*.{js,ts}", "*.md"
        context_lines: Number of lines to show before/after each match (default: 2).
        max_results: Maximum number of matches to return (default: 50).
        case_sensitive: If False, search case-insensitively (default: True).

    Returns:
        Formatted search results with file paths, line numbers, and context.

    Examples:
        - Find function: search_files("def process_data", "src/")
        - Find imports: search_files("import requests", file_pattern="*.py")
        - Find TODOs: search_files("TODO|FIXME|HACK", context_lines=0)
        - Case insensitive: search_files("error", "logs/", case_sensitive=False)
    """
    import subprocess
    import shutil

    resolved = _safe_path(path)

    if not os.path.exists(resolved):
        return f"Error: Path not found: {resolved}"

    log_message(None, "system", f"search_files: {resolved} pattern={pattern[:50]}",
                metadata={"tool": "search_files", "path": resolved, "pattern": pattern, "file_pattern": file_pattern})

    # Build command - prefer ripgrep, fallback to grep
    rg_path = shutil.which("rg")
    grep_path = shutil.which("grep")

    if rg_path:
        # Use ripgrep (faster, better defaults)
        cmd = [
            rg_path,
            "--line-number",
            "--with-filename",
            f"--context={context_lines}",
            f"--max-count={max_results}",
            "--color=never",
            "--heading",
            "--no-ignore-vcs",  # Search in .gitignore'd files too
        ]

        if not case_sensitive:
            cmd.append("--ignore-case")

        if file_pattern:
            cmd.extend(["--glob", file_pattern])

        cmd.append(pattern)
        cmd.append(resolved)

    elif grep_path:
        # Fallback to grep
        cmd = [
            grep_path,
            "-r",  # Recursive
            "-n",  # Line numbers
            "-H",  # Always show filename
            f"-C{context_lines}",  # Context lines
        ]

        if not case_sensitive:
            cmd.append("-i")

        if file_pattern:
            cmd.extend(["--include", file_pattern])

        cmd.append(pattern)
        cmd.append(resolved)

    else:
        return "Error: Neither ripgrep (rg) nor grep found. Install ripgrep for best results: https://github.com/BurntSushi/ripgrep"

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=resolved if os.path.isdir(resolved) else os.path.dirname(resolved)
        )

        output = result.stdout

        # ripgrep returns exit code 1 for "no matches" which isn't an error
        if result.returncode == 1 and not output and not result.stderr:
            return f"No matches found for pattern: {pattern}"

        if result.returncode > 1:
            return f"Error: Search failed: {result.stderr}"

        if not output:
            return f"No matches found for pattern: {pattern}"

        # Truncate if too long
        lines = output.split('\n')
        if len(lines) > 500:
            output = '\n'.join(lines[:500]) + f"\n\n... truncated ({len(lines)} total lines)"

        # Add summary header
        match_count = len([l for l in lines if l.strip() and not l.startswith('--')])
        header = f"Search: {pattern}\nPath: {resolved}\nMatches: ~{match_count} lines\n{'='*60}\n\n"

        return header + output

    except subprocess.TimeoutExpired:
        return "Error: Search timed out after 30 seconds. Try a more specific pattern or path."
    except Exception as e:
        return f"Error: Search failed: {type(e).__name__}: {e}"


@simple_eddy
def tree(path: str = ".", max_depth: int = 3, show_hidden: bool = False) -> str:
    """
    Display directory structure as a tree.

    Useful for understanding project layout before diving into specific files.

    Args:
        path: Root directory to display (default: current directory).
        max_depth: Maximum depth to traverse (default: 3). Use -1 for unlimited.
        show_hidden: If True, include hidden files/directories (default: False).

    Returns:
        ASCII tree representation of the directory structure.

    Examples:
        - Project overview: tree("~/myproject")
        - Deep dive: tree("src/", max_depth=5)
        - Include hidden: tree(".", show_hidden=True)
    """
    resolved = _safe_path(path)

    if not os.path.exists(resolved):
        return f"Error: Path not found: {resolved}"

    if not os.path.isdir(resolved):
        return f"Error: Path is not a directory: {resolved}"

    log_message(None, "system", f"tree: {resolved} (max_depth={max_depth})",
                metadata={"tool": "tree", "path": resolved, "max_depth": max_depth})

    lines = [resolved]
    _tree_recursive(resolved, "", lines, max_depth, 0, show_hidden)

    # Truncate if too large
    if len(lines) > 500:
        lines = lines[:500]
        lines.append(f"\n... truncated (>500 entries)")

    return '\n'.join(lines)


def _tree_recursive(dir_path: str, prefix: str, lines: list, max_depth: int, current_depth: int, show_hidden: bool):
    """Helper for tree() - recursively build tree representation."""
    if max_depth != -1 and current_depth >= max_depth:
        return

    if len(lines) > 500:  # Safety limit
        return

    try:
        entries = sorted(os.listdir(dir_path))
    except PermissionError:
        lines.append(f"{prefix}[permission denied]")
        return

    # Filter hidden files if needed
    if not show_hidden:
        entries = [e for e in entries if not e.startswith('.')]

    # Separate dirs and files
    dirs = [e for e in entries if os.path.isdir(os.path.join(dir_path, e))]
    files = [e for e in entries if os.path.isfile(os.path.join(dir_path, e))]

    # Sort: directories first, then files
    all_entries = dirs + files

    for i, entry in enumerate(all_entries):
        is_last = (i == len(all_entries) - 1)
        connector = "└── " if is_last else "├── "
        entry_path = os.path.join(dir_path, entry)

        if os.path.isdir(entry_path):
            lines.append(f"{prefix}{connector}📁 {entry}/")
            extension = "    " if is_last else "│   "
            _tree_recursive(entry_path, prefix + extension, lines, max_depth, current_depth + 1, show_hidden)
        else:
            size = _format_size(os.path.getsize(entry_path))
            lines.append(f"{prefix}{connector}📄 {entry} ({size})")


@simple_eddy
def get_image_info(path: str) -> dict:
    """
    Get detailed information about an image file including dimensions and aspect ratio.

    Useful for filtering images by size, aspect ratio, or format before processing.

    Args:
        path: Path to the image file (absolute or relative). Supports ~ for home directory.
              Supported formats: PNG, JPG, JPEG, GIF, WEBP, BMP, TIFF.

    Returns:
        Dict with image metadata:
            - path: Absolute path to the image
            - width: Image width in pixels
            - height: Image height in pixels
            - aspect_ratio: Width/height ratio (e.g., 1.778 for 16:9)
            - aspect_name: Common name if recognized ("16:9", "4:3", "1:1", etc.)
            - is_16x9: Boolean for quick 16:9 check (with 1% tolerance)
            - format: Image format (PNG, JPEG, etc.)
            - mode: Color mode (RGB, RGBA, L, etc.)
            - file_size: File size in bytes
            - file_size_human: Human-readable file size

    Examples:
        - Check single image: get_image_info("/photos/image.jpg")
        - In a cascade: Use with list_files to filter by aspect ratio
    """
    resolved = _safe_path(path)

    log_message(None, "system", f"get_image_info: {resolved}",
                metadata={"tool": "get_image_info", "path": resolved})

    if not os.path.exists(resolved):
        return {"error": f"Image not found: {resolved}"}

    if not os.path.isfile(resolved):
        return {"error": f"Path is not a file: {resolved}"}

    # Check extension
    ext = os.path.splitext(resolved)[1].lower()
    if ext not in IMAGE_EXTENSIONS:
        return {"error": f"Unsupported image format: {ext}. Supported: {', '.join(sorted(IMAGE_EXTENSIONS))}"}

    try:
        from PIL import Image

        with Image.open(resolved) as img:
            width, height = img.size
            img_format = img.format
            mode = img.mode

        # Calculate aspect ratio
        aspect_ratio = width / height if height > 0 else 0

        # Identify common aspect ratios (with 1% tolerance)
        aspect_names = {
            16/9: "16:9",
            9/16: "9:16",
            4/3: "4:3",
            3/4: "3:4",
            1.0: "1:1",
            21/9: "21:9",
            3/2: "3:2",
            2/3: "2:3",
        }

        aspect_name = None
        for ratio, name in aspect_names.items():
            if abs(aspect_ratio - ratio) / ratio < 0.01:  # 1% tolerance
                aspect_name = name
                break

        if not aspect_name:
            # Generate approximate ratio
            from math import gcd
            g = gcd(width, height)
            aspect_name = f"{width//g}:{height//g}"

        # Check if 16:9 (with tolerance)
        is_16x9 = abs(aspect_ratio - (16/9)) / (16/9) < 0.01

        file_size = os.path.getsize(resolved)

        return {
            "path": resolved,
            "filename": os.path.basename(resolved),
            "width": width,
            "height": height,
            "aspect_ratio": round(aspect_ratio, 4),
            "aspect_name": aspect_name,
            "is_16x9": is_16x9,
            "format": img_format,
            "mode": mode,
            "file_size": file_size,
            "file_size_human": _format_size(file_size)
        }

    except ImportError:
        return {"error": "PIL/Pillow not installed. Run: pip install Pillow"}
    except Exception as e:
        return {"error": f"Error reading image: {type(e).__name__}: {e}"}


@simple_eddy
def read_images(paths: list, max_images: int = 10) -> dict:
    """
    Read multiple image files for vision model processing.

    All images will be automatically encoded and injected into the LLM conversation
    as a multi-modal message. The runner handles resizing and encoding.

    Args:
        paths: List of paths to image files. Supports ~ for home directory.
               Can also be a single path string (converted to list).
        max_images: Maximum number of images to load (default: 10).
                    Vision models have context limits, so this prevents overload.

    Returns:
        Image data structure that the runner will process into vision messages.
        Includes list of successfully loaded images and any errors.

    Examples:
        - Load specific images: read_images(["/photos/img1.jpg", "/photos/img2.png"])
        - Load from list: read_images(outputs.filtered_images)
    """
    # Handle single path as string
    if isinstance(paths, str):
        paths = [paths]

    if not isinstance(paths, list):
        return {"error": f"paths must be a list, got {type(paths).__name__}"}

    log_message(None, "system", f"read_images: {len(paths)} paths (max={max_images})",
                metadata={"tool": "read_images", "path_count": len(paths), "max_images": max_images})

    loaded_images = []
    errors = []

    for path in paths[:max_images]:
        resolved = _safe_path(path)

        if not os.path.exists(resolved):
            errors.append({"path": path, "error": "File not found"})
            continue

        if not os.path.isfile(resolved):
            errors.append({"path": path, "error": "Not a file"})
            continue

        # Check extension
        ext = os.path.splitext(resolved)[1].lower()
        if ext not in IMAGE_EXTENSIONS:
            errors.append({"path": path, "error": f"Unsupported format: {ext}"})
            continue

        loaded_images.append(resolved)

    if not loaded_images:
        return {
            "error": "No valid images found",
            "errors": errors,
            "images": []
        }

    # Build summary
    skipped = len(paths) - max_images if len(paths) > max_images else 0
    summary_parts = [f"Loaded {len(loaded_images)} image(s)"]
    if errors:
        summary_parts.append(f"{len(errors)} failed")
    if skipped > 0:
        summary_parts.append(f"{skipped} skipped (max_images={max_images})")

    return {
        "content": ". ".join(summary_parts),
        "images": loaded_images,
        "loaded_count": len(loaded_images),
        "error_count": len(errors),
        "errors": errors if errors else None
    }


@simple_eddy
def list_images(
    path: str = ".",
    recursive: bool = False,
    filter_aspect: str | None = None,
    min_width: int | None = None,
    min_height: int | None = None
) -> dict:
    """
    List image files in a directory with optional filtering.

    Combines list_files with get_image_info for efficient image discovery.

    Args:
        path: Directory to search (default: current directory).
        recursive: If True, search subdirectories (default: False).
        filter_aspect: Filter by aspect ratio. Options:
            - "16:9" or "landscape_wide": Only 16:9 images
            - "not_16:9" or "not_landscape_wide": Exclude 16:9 images
            - "4:3": Only 4:3 images
            - "1:1" or "square": Only square images
            - "porskill": Height > width
            - "landscape": Width > height
        min_width: Minimum width in pixels (optional).
        min_height: Minimum height in pixels (optional).

    Returns:
        Dict with:
            - images: List of image info dicts (same as get_image_info output)
            - paths: List of just the paths (for easy use with read_images)
            - count: Total matching images
            - filtered_out: Count of images that didn't match filters

    Examples:
        - List all images: list_images("/photos")
        - Find non-16:9 images: list_images("/photos", filter_aspect="not_16:9")
        - Find large images: list_images("/photos", min_width=1920, recursive=True)
    """
    resolved = _safe_path(path)

    log_message(None, "system", f"list_images: {resolved} (recursive={recursive}, filter={filter_aspect})",
                metadata={"tool": "list_images", "path": resolved, "filter_aspect": filter_aspect})

    if not os.path.exists(resolved):
        return {"error": f"Path not found: {resolved}"}

    if not os.path.isdir(resolved):
        return {"error": f"Path is not a directory: {resolved}"}

    try:
        from PIL import Image
    except ImportError:
        return {"error": "PIL/Pillow not installed. Run: pip install Pillow"}

    # Find all image files
    p = Path(resolved)
    all_images = []

    for ext in IMAGE_EXTENSIONS:
        pattern = f"*{ext}"
        if recursive:
            all_images.extend(p.rglob(pattern))
            # Also check uppercase
            all_images.extend(p.rglob(pattern.upper()))
        else:
            all_images.extend(p.glob(pattern))
            all_images.extend(p.glob(pattern.upper()))

    # Remove duplicates and sort
    all_images = sorted(set(all_images))

    matching_images = []
    filtered_out = 0

    for img_path in all_images:
        try:
            with Image.open(img_path) as img:
                width, height = img.size
                img_format = img.format
                mode = img.mode
        except Exception:
            continue

        aspect_ratio = width / height if height > 0 else 0

        # Apply filters
        if filter_aspect:
            filter_lower = filter_aspect.lower()
            is_16x9 = abs(aspect_ratio - (16/9)) / (16/9) < 0.01
            is_4x3 = abs(aspect_ratio - (4/3)) / (4/3) < 0.01
            is_square = abs(aspect_ratio - 1.0) < 0.01

            if filter_lower in ("16:9", "landscape_wide") and not is_16x9:
                filtered_out += 1
                continue
            if filter_lower in ("not_16:9", "not_landscape_wide") and is_16x9:
                filtered_out += 1
                continue
            if filter_lower == "4:3" and not is_4x3:
                filtered_out += 1
                continue
            if filter_lower in ("1:1", "square") and not is_square:
                filtered_out += 1
                continue
            if filter_lower == "porskill" and width >= height:
                filtered_out += 1
                continue
            if filter_lower == "landscape" and width <= height:
                filtered_out += 1
                continue

        if min_width and width < min_width:
            filtered_out += 1
            continue
        if min_height and height < min_height:
            filtered_out += 1
            continue

        # Identify aspect name
        aspect_names = {16/9: "16:9", 9/16: "9:16", 4/3: "4:3", 3/4: "3:4", 1.0: "1:1", 21/9: "21:9", 3/2: "3:2"}
        aspect_name = None
        for ratio, name in aspect_names.items():
            if abs(aspect_ratio - ratio) / ratio < 0.01:
                aspect_name = name
                break

        file_size = img_path.stat().st_size

        matching_images.append({
            "path": str(img_path),
            "filename": img_path.name,
            "width": width,
            "height": height,
            "aspect_ratio": round(aspect_ratio, 4),
            "aspect_name": aspect_name,
            "is_16x9": abs(aspect_ratio - (16/9)) / (16/9) < 0.01,
            "format": img_format,
            "mode": mode,
            "file_size": file_size,
            "file_size_human": _format_size(file_size)
        })

    return {
        "images": matching_images,
        "paths": [img["path"] for img in matching_images],
        "count": len(matching_images),
        "filtered_out": filtered_out,
        "total_scanned": len(all_images)
    }


@simple_eddy
def save_image(
    source: str,
    destination: str,
    format: str | None = None,
    quality: int = 85,
    resize: str | None = None
) -> dict:
    """
    Save an image to the filesystem from various sources.

    Handles:
    - Base64 data URLs (e.g., from LLM image generation responses)
    - Local file paths (copy/convert)
    - HTTP/HTTPS URLs (download)

    Args:
        source: The image source. Can be:
            - Base64 data URL: "data:image/png;base64,iVBORw0KGgo..."
            - Local file path: "/path/to/image.png" or "~/photos/img.jpg"
            - HTTP URL: "https://example.com/image.png"
        destination: Where to save the image. Supports ~ for home directory.
            If a directory, generates filename. If a file path, uses that name.
        format: Output format (png, jpg, jpeg, webp, gif). Auto-detected from
            destination extension if not specified. Defaults to PNG.
        quality: JPEG/WebP quality (1-100). Default 85. Ignored for PNG/GIF.
        resize: Optional resize specification:
            - "WxH" (e.g., "1920x1080") - exact size
            - "W" (e.g., "1920") - width, maintain aspect ratio
            - "xH" (e.g., "x1080") - height, maintain aspect ratio

    Returns:
        Dict with:
            - path: Absolute path where image was saved
            - filename: Just the filename
            - width, height: Final dimensions
            - format: Output format used
            - file_size: Size in bytes
            - file_size_human: Human-readable size

    Examples:
        - Save base64 from LLM: save_image("data:image/png;base64,...", "/output/result.png")
        - Download from URL: save_image("https://example.com/img.jpg", "~/downloads/")
        - Convert format: save_image("/input/photo.png", "/output/photo.jpg", format="jpeg")
        - Resize: save_image("/input/large.png", "/output/thumb.png", resize="256x256")
    """
    import base64
    import re
    import uuid
    from datetime import datetime

    log_message(None, "system", f"save_image: {source[:50]}... -> {destination}",
                metadata={"tool": "save_image", "destination": destination})

    try:
        from PIL import Image
        import io
    except ImportError:
        return {"error": "PIL/Pillow not installed. Run: pip install Pillow"}

    # Resolve destination path
    dest_resolved = _safe_path(destination)

    # Safety check for destination
    safety_error = _check_path_safety(dest_resolved)
    if safety_error:
        return {"error": safety_error}

    # Determine if destination is a directory or file
    if os.path.isdir(dest_resolved) or dest_resolved.endswith('/'):
        # It's a directory - generate filename
        os.makedirs(dest_resolved, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        ext = format.lower() if format else 'png'
        if ext == 'jpeg':
            ext = 'jpg'
        filename = f"image_{timestamp}_{uuid.uuid4().hex[:6]}.{ext}"
        dest_path = os.path.join(dest_resolved, filename)
    else:
        # It's a file path
        dest_path = dest_resolved
        # Create parent directory if needed
        parent = os.path.dirname(dest_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        filename = os.path.basename(dest_path)

    # Determine output format
    if format:
        out_format = format.upper()
        if out_format == 'JPG':
            out_format = 'JPEG'
    else:
        # Detect from destination extension
        ext = os.path.splitext(dest_path)[1].lower()
        format_map = {
            '.png': 'PNG',
            '.jpg': 'JPEG',
            '.jpeg': 'JPEG',
            '.gif': 'GIF',
            '.webp': 'WEBP',
            '.bmp': 'BMP',
            '.tiff': 'TIFF',
            '.tif': 'TIFF'
        }
        out_format = format_map.get(ext, 'PNG')

    # Load image from source
    img = None

    # Case 1: Base64 data URL
    if source.startswith('data:'):
        # Parse data URL: data:image/png;base64,iVBORw0KGgo...
        match = re.match(r'data:image/[^;]+;base64,(.+)', source)
        if not match:
            return {"error": "Invalid base64 data URL format. Expected: data:image/TYPE;base64,DATA"}

        try:
            image_data = base64.b64decode(match.group(1))
            img = Image.open(io.BytesIO(image_data))
        except Exception as e:
            return {"error": f"Failed to decode base64 image: {e}"}

    # Case 2: HTTP/HTTPS URL
    elif source.startswith('http://') or source.startswith('https://'):
        try:
            import urllib.request
            import urllib.error

            # Download with timeout
            req = urllib.request.Request(source, headers={'User-Agent': 'RVBBIT/1.0'})
            with urllib.request.urlopen(req, timeout=30) as response:
                image_data = response.read()
            img = Image.open(io.BytesIO(image_data))
        except urllib.error.URLError as e:
            return {"error": f"Failed to download image: {e}"}
        except Exception as e:
            return {"error": f"Failed to load image from URL: {e}"}

    # Case 3: Local file path
    else:
        source_resolved = _safe_path(source)
        if not os.path.exists(source_resolved):
            return {"error": f"Source file not found: {source_resolved}"}
        if not os.path.isfile(source_resolved):
            return {"error": f"Source is not a file: {source_resolved}"}

        try:
            img = Image.open(source_resolved)
        except Exception as e:
            return {"error": f"Failed to open source image: {e}"}

    if img is None:
        return {"error": "Failed to load image from source"}

    # Handle resize if specified
    if resize:
        try:
            if 'x' in resize:
                parts = resize.lower().split('x')
                if parts[0] and parts[1]:
                    # Exact size: WxH
                    new_width = int(parts[0])
                    new_height = int(parts[1])
                elif parts[0]:
                    # Width only: W (e.g., "1920x" or "1920")
                    new_width = int(parts[0])
                    aspect = img.height / img.width
                    new_height = int(new_width * aspect)
                else:
                    # Height only: xH (e.g., "x1080")
                    new_height = int(parts[1])
                    aspect = img.width / img.height
                    new_width = int(new_height * aspect)
            else:
                # Just a number = width
                new_width = int(resize)
                aspect = img.height / img.width
                new_height = int(new_width * aspect)

            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        except Exception as e:
            return {"error": f"Failed to resize image: {e}"}

    # Convert mode if necessary for output format
    if out_format == 'JPEG' and img.mode in ('RGBA', 'LA', 'P'):
        # JPEG doesn't support transparency - convert to RGB with white background
        background = Image.new('RGB', img.size, (255, 255, 255))
        if img.mode == 'P':
            img = img.convert('RGBA')
        background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
        img = background
    elif out_format in ('PNG', 'WEBP', 'GIF') and img.mode == 'P':
        img = img.convert('RGBA')

    # Save the image
    try:
        save_kwargs = {}
        if out_format == 'JPEG':
            save_kwargs['quality'] = quality
            save_kwargs['optimize'] = True
        elif out_format == 'WEBP':
            save_kwargs['quality'] = quality
        elif out_format == 'PNG':
            save_kwargs['optimize'] = True

        img.save(dest_path, format=out_format, **save_kwargs)
    except Exception as e:
        return {"error": f"Failed to save image: {e}"}

    # Get final file info
    file_size = os.path.getsize(dest_path)

    return {
        "path": dest_path,
        "filename": filename,
        "width": img.width,
        "height": img.height,
        "format": out_format.lower(),
        "file_size": file_size,
        "file_size_human": _format_size(file_size),
        "content": f"Saved image: {filename} ({img.width}x{img.height}, {_format_size(file_size)})",
        "images": [dest_path]  # Standard protocol for image tools
    }


@simple_eddy
def copy_image(source: str, destination: str) -> dict:
    """
    Copy an image file to a new location without re-encoding.

    This is a simple file copy - use save_image if you need format conversion
    or resizing.

    Args:
        source: Path to source image file.
        destination: Destination path. If a directory, keeps original filename.

    Returns:
        Dict with path info and standard image protocol fields.

    Examples:
        - Copy to directory: copy_image("/photos/img.jpg", "/backup/")
        - Copy with new name: copy_image("/photos/img.jpg", "/backup/photo_backup.jpg")
    """
    import shutil

    source_resolved = _safe_path(source)
    dest_resolved = _safe_path(destination)

    log_message(None, "system", f"copy_image: {source_resolved} -> {dest_resolved}",
                metadata={"tool": "copy_image", "source": source_resolved, "destination": dest_resolved})

    if not os.path.exists(source_resolved):
        return {"error": f"Source file not found: {source_resolved}"}

    if not os.path.isfile(source_resolved):
        return {"error": f"Source is not a file: {source_resolved}"}

    # Check extension
    ext = os.path.splitext(source_resolved)[1].lower()
    if ext not in IMAGE_EXTENSIONS:
        return {"error": f"Source is not a supported image format: {ext}"}

    # Safety check for destination
    safety_error = _check_path_safety(dest_resolved)
    if safety_error:
        return {"error": safety_error}

    # Determine final destination path
    if os.path.isdir(dest_resolved) or dest_resolved.endswith('/'):
        os.makedirs(dest_resolved, exist_ok=True)
        filename = os.path.basename(source_resolved)
        dest_path = os.path.join(dest_resolved, filename)
    else:
        dest_path = dest_resolved
        parent = os.path.dirname(dest_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        filename = os.path.basename(dest_path)

    try:
        shutil.copy2(source_resolved, dest_path)
    except Exception as e:
        return {"error": f"Failed to copy image: {e}"}

    file_size = os.path.getsize(dest_path)

    # Get dimensions
    width, height = None, None
    try:
        from PIL import Image
        with Image.open(dest_path) as img:
            width, height = img.size
    except Exception:
        pass

    result = {
        "path": dest_path,
        "filename": filename,
        "file_size": file_size,
        "file_size_human": _format_size(file_size),
        "content": f"Copied image: {filename}",
        "images": [dest_path]
    }

    if width and height:
        result["width"] = width
        result["height"] = height

    return result
