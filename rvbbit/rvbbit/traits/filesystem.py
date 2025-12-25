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
