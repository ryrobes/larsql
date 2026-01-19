#!/usr/bin/env python3
"""
Build markdown versions of HTML doc pages for content negotiation.

Usage:
    python build_markdown.py           # Build all
    python build_markdown.py --clean   # Remove generated .md files
    python build_markdown.py --watch   # Watch for changes and rebuild

The generated .md files sit alongside .html files and are served
when clients request Accept: text/markdown.
"""

import re
import sys
import html
from pathlib import Path
from html.parser import HTMLParser
from typing import Optional

# Files/directories to process
DOC_ROOT = Path(__file__).parent
CONTENT_DIR = DOC_ROOT / "content"
OUTPUT_SUFFIX = ".md"

# Root-level HTML files to also convert
# Note: docs.html is excluded because docs.md is hand-curated (docs.html is a JS shell)
ROOT_HTML_FILES = ["index.html"]


class HTMLToMarkdown(HTMLParser):
    """Convert semantic HTML to clean markdown."""

    def __init__(self):
        super().__init__()
        self.output = []
        self.current_text = []
        self.tag_stack = []
        self.list_stack = []  # Track nested lists: [('ul', 0), ('ol', 1)]
        self.in_code_block = False
        self.code_lang = ""
        self.in_table = False
        self.table_rows = []
        self.current_row = []
        self.is_header_row = False
        self.skip_content = False  # Skip iconify-icon, etc.
        self.link_href = None
        self.in_pre = False
        self.in_info_box = False
        self.info_box_type = ""
        self.in_info_box_title = False
        self.info_box_title_text = ""
        self.in_toc = False
        self.toc_title_seen = False

    def flush_text(self):
        """Flush accumulated text to output."""
        text = "".join(self.current_text).strip()
        if text and not self.skip_content:
            # If in info box, prefix lines with >
            if self.in_info_box and not self.in_info_box_title:
                lines = text.split('\n')
                text = '\n> '.join(lines)
            self.output.append(text)
        self.current_text = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)

        # Skip certain elements entirely
        if tag in ("iconify-icon", "script", "style"):
            self.skip_content = True
            self.tag_stack.append((tag, "skip"))
            return

        # Track tag for proper closing
        self.tag_stack.append((tag, attrs_dict))

        # Headings
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.flush_text()
            level = int(tag[1])
            self.output.append("\n" + "#" * level + " ")

        # Paragraphs
        elif tag == "p":
            self.flush_text()
            if self.in_info_box:
                self.output.append("\n> ")
            else:
                self.output.append("\n\n")

        # Links
        elif tag == "a":
            self.link_href = attrs_dict.get("href", "")
            self.current_text.append("[")

        # Bold/Strong
        elif tag in ("strong", "b"):
            self.current_text.append("**")

        # Italic/Em
        elif tag in ("em", "i"):
            self.current_text.append("*")

        # Inline code
        elif tag == "code" and not self.in_pre:
            self.current_text.append("`")

        # Code blocks
        elif tag == "pre":
            self.flush_text()
            self.in_pre = True
            # Check if it's a mermaid diagram
            classes = attrs_dict.get("class", "")
            if "mermaid" in classes:
                self.code_lang = "mermaid"

        elif tag == "div":
            classes = attrs_dict.get("class", "")

            # Code block container - extract language
            if "code-block" in classes:
                self.in_code_block = True

            elif "code-block-header" in classes:
                pass  # Will extract lang from child span

            elif "code-block-lang" in classes:
                # The text content will be the language
                pass

            elif "code-block-content" in classes:
                pass

            # Info box title (check BEFORE info-box since it's a substring)
            elif "info-box-title" in classes or "callout-title" in classes:
                self.in_info_box_title = True
                self.info_box_title_text = ""

            # Info boxes / callouts
            elif "info-box" in classes or "callout" in classes:
                self.flush_text()
                self.in_info_box = True
                box_type = "NOTE"
                if "tip" in classes:
                    box_type = "TIP"
                elif "warning" in classes:
                    box_type = "WARNING"
                elif "note" in classes:
                    box_type = "NOTE"
                elif "callout-info" in classes:
                    box_type = "INFO"
                self.info_box_type = box_type
                # Don't emit yet - wait for title

            # TOC - render as a list
            elif "toc" in classes:
                self.flush_text()
                self.in_toc = True
                self.toc_title_seen = False

            elif "toc-title" in classes:
                self.skip_content = True  # Skip "On This Page" text

            # Feature grids - just flow through
            elif "feature-grid" in classes or "feature-card" in classes:
                self.flush_text()
                self.output.append("\n\n")

            # Expandable sections
            elif "expandable-section" in classes:
                pass

        # Lists
        elif tag == "ul":
            self.flush_text()
            self.list_stack.append(("ul", 0))
            prefix = "> " if self.in_info_box else ""
            self.output.append(f"\n{prefix}")

        elif tag == "ol":
            self.flush_text()
            self.list_stack.append(("ol", 0))
            prefix = "> " if self.in_info_box else ""
            self.output.append(f"\n{prefix}")

        elif tag == "li":
            self.flush_text()
            indent = "  " * (len(self.list_stack) - 1)
            prefix = "> " if self.in_info_box else ""
            if self.list_stack:
                list_type, count = self.list_stack[-1]
                if list_type == "ul":
                    self.output.append(f"{prefix}{indent}- ")
                else:
                    self.list_stack[-1] = (list_type, count + 1)
                    self.output.append(f"{prefix}{indent}{count + 1}. ")

        # Tables
        elif tag == "table":
            self.flush_text()
            self.in_table = True
            self.table_rows = []
            self.output.append("\n\n")

        elif tag == "thead":
            self.is_header_row = True

        elif tag == "tbody":
            self.is_header_row = False

        elif tag == "tr":
            self.current_row = []

        elif tag in ("th", "td"):
            pass

        # Details/Summary (expandable)
        elif tag == "details":
            self.flush_text()
            self.output.append("\n\n<details>\n")

        elif tag == "summary":
            self.output.append("<summary>")

        # Line breaks
        elif tag == "br":
            self.current_text.append("\n")

        # Spans with special classes
        elif tag == "span":
            classes = attrs_dict.get("class", "")
            # Code block language indicator
            if "code-block-lang" in classes:
                pass  # Will capture text as language
            # Syntax highlighting spans - just pass through text
            elif classes in ("kw", "fn", "str", "cmt", "num", "key"):
                pass

    def handle_endtag(self, tag):
        if not self.tag_stack:
            return

        # Pop from stack
        start_tag, start_attrs = self.tag_stack.pop()

        # Handle skip mode
        if start_attrs == "skip":
            if tag == start_tag:
                self.skip_content = False
            return

        if self.skip_content:
            return

        # Headings
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.flush_text()
            self.output.append("\n\n")

        # Paragraphs
        elif tag == "p":
            self.flush_text()
            if self.in_info_box:
                self.output.append("\n> ")
            else:
                self.output.append("\n")

        # Links
        elif tag == "a":
            self.current_text.append(f"]({self.link_href})")
            self.link_href = None

        # Bold/Strong
        elif tag in ("strong", "b"):
            self.current_text.append("**")

        # Italic/Em
        elif tag in ("em", "i"):
            self.current_text.append("*")

        # Inline code
        elif tag == "code" and not self.in_pre:
            self.current_text.append("`")

        # Code blocks
        elif tag == "pre":
            self.in_pre = False
            code_content = "".join(self.current_text)
            self.current_text = []

            # Clean up the code - remove HTML syntax highlighting spans
            code_content = self._clean_code(code_content)

            lang = self.code_lang or ""
            self.output.append(f"\n```{lang}\n{code_content}\n```\n")
            self.code_lang = ""

        elif tag == "div":
            classes = start_attrs.get("class", "") if isinstance(start_attrs, dict) else ""

            if "code-block" in classes:
                self.in_code_block = False

            # Info box title (check BEFORE info-box since it's a substring)
            elif "info-box-title" in classes or "callout-title" in classes:
                self.in_info_box_title = False
                # Now emit the info box header with the captured title
                title = self.info_box_title_text.strip()
                # Combine type with title if both exist
                if title and self.info_box_type:
                    header = f"{self.info_box_type}: {title}"
                elif title:
                    header = title
                else:
                    header = self.info_box_type or "NOTE"
                self.output.append(f"\n\n> **{header}**\n>\n> ")

            # Info boxes / callouts
            elif "info-box" in classes or "callout" in classes:
                self.flush_text()
                self.in_info_box = False
                self.output.append("\n\n")

            elif "toc-title" in classes:
                self.skip_content = False

            elif "toc" in classes:
                self.flush_text()
                self.in_toc = False
                self.output.append("\n\n")

        # Lists
        elif tag == "ul" or tag == "ol":
            self.flush_text()
            if self.list_stack:
                self.list_stack.pop()
            prefix = "> " if self.in_info_box and not self.list_stack else ""
            self.output.append(f"\n{prefix}")

        elif tag == "li":
            self.flush_text()
            prefix = "> " if self.in_info_box else ""
            self.output.append(f"\n{prefix}")

        # Tables
        elif tag == "table":
            self._render_table()
            self.in_table = False

        elif tag == "tr":
            if self.current_row:
                self.table_rows.append((self.is_header_row, self.current_row))
            self.current_row = []

        elif tag in ("th", "td"):
            cell_text = "".join(self.current_text).strip()
            self.current_text = []
            self.current_row.append(cell_text)

        # Details/Summary
        elif tag == "details":
            self.flush_text()
            self.output.append("\n</details>\n")

        elif tag == "summary":
            self.flush_text()
            self.output.append("</summary>\n\n")

        # Span with code-block-lang - capture as language
        elif tag == "span":
            classes = start_attrs.get("class", "") if isinstance(start_attrs, dict) else ""
            if "code-block-lang" in classes:
                lang_text = "".join(self.current_text).strip().lower()
                self.current_text = []
                # Map display names to markdown lang hints
                lang_map = {
                    "bash": "bash",
                    "sql": "sql",
                    "python": "python",
                    "yaml": "yaml",
                    "json": "json",
                    "javascript": "javascript",
                    "config": "",
                    "directory structure": "",
                    "common commands": "bash",
                }
                self.code_lang = lang_map.get(lang_text, lang_text)

    def handle_data(self, data):
        if self.skip_content:
            return
        # Capture info box title text
        if self.in_info_box_title:
            self.info_box_title_text += data
            return
        self.current_text.append(data)

    def handle_entityref(self, name):
        if self.skip_content:
            return
        char = html.unescape(f"&{name};")
        self.current_text.append(char)

    def handle_charref(self, name):
        if self.skip_content:
            return
        if name.startswith('x'):
            char = chr(int(name[1:], 16))
        else:
            char = chr(int(name))
        self.current_text.append(char)

    def _clean_code(self, code: str) -> str:
        """Remove any remaining HTML artifacts from code."""
        # The code might still have HTML entities
        code = html.unescape(code)
        # Strip leading/trailing whitespace per line, preserve structure
        lines = code.split('\n')
        # Remove empty lines at start/end
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        return '\n'.join(lines)

    def _render_table(self):
        """Render accumulated table rows as markdown."""
        if not self.table_rows:
            return

        # Find max columns
        max_cols = max(len(row) for _, row in self.table_rows)

        # Render header
        headers = []
        body_rows = []

        for is_header, cells in self.table_rows:
            # Pad cells to max_cols
            cells = cells + [""] * (max_cols - len(cells))
            if is_header:
                headers.extend(cells)
            else:
                body_rows.append(cells)

        # If no explicit header, use first row
        if not headers and body_rows:
            headers = body_rows.pop(0)

        # Calculate column widths
        col_widths = [len(h) for h in headers]
        for row in body_rows:
            for i, cell in enumerate(row):
                col_widths[i] = max(col_widths[i], len(cell))

        # Render
        def format_row(cells):
            return "| " + " | ".join(
                cell.ljust(col_widths[i]) for i, cell in enumerate(cells)
            ) + " |"

        self.output.append(format_row(headers) + "\n")
        self.output.append("|" + "|".join("-" * (w + 2) for w in col_widths) + "|\n")

        for row in body_rows:
            self.output.append(format_row(row) + "\n")

        self.output.append("\n")

    def get_markdown(self) -> str:
        """Get final markdown output."""
        self.flush_text()
        result = "".join(self.output)

        # Clean up excessive newlines
        result = re.sub(r'\n{4,}', '\n\n\n', result)

        # Clean up list formatting
        result = re.sub(r'\n\n+(-|\d+\.)', r'\n\1', result)

        # Clean up empty blockquote lines
        result = re.sub(r'\n> \n> \n', r'\n> \n', result)

        # Remove duplicate > > patterns
        result = re.sub(r'^> > ', '> ', result, flags=re.MULTILINE)

        return result.strip() + '\n'


def convert_html_to_markdown(html_content: str) -> str:
    """Convert HTML content to markdown."""
    parser = HTMLToMarkdown()
    parser.feed(html_content)
    return parser.get_markdown()


def build_markdown_file(html_path: Path) -> Optional[Path]:
    """Convert a single HTML file to markdown."""
    md_path = html_path.with_suffix(OUTPUT_SUFFIX)

    try:
        html_content = html_path.read_text(encoding='utf-8')
        md_content = convert_html_to_markdown(html_content)
        md_path.write_text(md_content, encoding='utf-8')
        return md_path
    except Exception as e:
        print(f"  ERROR: {html_path.name}: {e}")
        return None


def build_all():
    """Build markdown for all HTML files in content directory and root."""
    if not CONTENT_DIR.exists():
        print(f"Content directory not found: {CONTENT_DIR}")
        sys.exit(1)

    # Gather all HTML files to process
    html_files = list(CONTENT_DIR.glob("*.html"))

    # Add root-level HTML files
    for filename in ROOT_HTML_FILES:
        root_file = DOC_ROOT / filename
        if root_file.exists():
            html_files.append(root_file)

    if not html_files:
        print("No HTML files found")
        return

    print(f"Building markdown for {len(html_files)} files...")

    success = 0
    for html_path in sorted(html_files):
        md_path = build_markdown_file(html_path)
        if md_path:
            # Show relative path for clarity
            rel_path = html_path.relative_to(DOC_ROOT) if DOC_ROOT in html_path.parents or html_path.parent == DOC_ROOT else html_path
            rel_md = md_path.relative_to(DOC_ROOT) if DOC_ROOT in md_path.parents or md_path.parent == DOC_ROOT else md_path
            print(f"  {rel_path} -> {rel_md}")
            success += 1

    print(f"\nDone: {success}/{len(html_files)} files converted")


def clean_markdown():
    """Remove all generated .md files from content directory and root."""
    md_files = list(CONTENT_DIR.glob("*.md"))

    # Add root-level MD files (only auto-generated ones)
    for filename in ROOT_HTML_FILES:
        md_name = filename.replace(".html", ".md")
        root_md = DOC_ROOT / md_name
        if root_md.exists():
            md_files.append(root_md)

    # Note: docs.md is hand-curated and not cleaned

    if not md_files:
        print("No markdown files to clean")
        return

    print(f"Removing {len(md_files)} markdown files...")

    for md_path in md_files:
        md_path.unlink()
        rel_path = md_path.relative_to(DOC_ROOT) if DOC_ROOT in md_path.parents or md_path.parent == DOC_ROOT else md_path
        print(f"  Removed {rel_path}")

    print("Done")


def watch_and_build():
    """Watch for HTML changes and rebuild markdown."""
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        print("Install watchdog for --watch: pip install watchdog")
        sys.exit(1)

    class RebuildHandler(FileSystemEventHandler):
        def on_modified(self, event):
            if event.src_path.endswith('.html'):
                path = Path(event.src_path)
                print(f"\nRebuilding {path.name}...")
                build_markdown_file(path)

    observer = Observer()
    observer.schedule(RebuildHandler(), str(CONTENT_DIR), recursive=False)
    observer.start()

    print(f"Watching {CONTENT_DIR} for changes... (Ctrl+C to stop)")

    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    if "--clean" in sys.argv:
        clean_markdown()
    elif "--watch" in sys.argv:
        build_all()
        watch_and_build()
    else:
        build_all()
