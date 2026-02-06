#!/usr/bin/env python3
"""
Glass Prompt Toolkit Editor Widget
==================================

A glass widget that embeds prompt_toolkit's TextArea editor.
This provides a full-featured editor with syntax highlighting,
multiple cursors, and vi/emacs bindings.
"""

from .looking_glass import AbsoluteGlassPanel
from textual.strip import Strip, Segment
from rich.style import Style as RichStyle
from typing import Optional, Callable
from pathlib import Path
import tempfile
import asyncio

from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document
from prompt_toolkit.lexers import PygmentsLexer
from prompt_toolkit.widgets import TextArea
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.application import Application
from prompt_toolkit.layout import Layout, HSplit, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.formatted_text import HTML

try:
    from pygments.lexers.sql import SqlLexer
    from pygments.lexers.data import JsonLexer, YamlLexer
except ImportError:
    SqlLexer = None
    JsonLexer = None
    YamlLexer = None


class GlassPromptToolkitEditor(AbsoluteGlassPanel):
    """
    A glass widget that uses prompt_toolkit's TextArea for editing.
    
    Features:
    - Syntax highlighting for SQL
    - Vi and Emacs key bindings
    - Multiple cursors
    - Search and replace
    - Undo/redo
    """
    
    def __init__(self,
                 file_path: Optional[str] = None,
                 initial_text: Optional[str] = None,
                 on_save: Optional[Callable[[str], None]] = None,
                 title: str = "SQL Editor - Ctrl+S Save | Ctrl+X Exit",
                 syntax: str = "sql",
                 **kwargs):
        """Initialize the editor."""
        # Use initial_text if provided, otherwise load from file
        if initial_text is not None:
            content = initial_text
            self.file_path = Path(file_path) if file_path else None
            self._temp_file = None
        elif file_path:
            self.file_path = Path(file_path)
            self._temp_file = None
            if self.file_path.exists():
                content = self.file_path.read_text()
            else:
                content = ""
        else:
            # Create temp file with sample SQL
            self._temp_file = tempfile.NamedTemporaryFile(
                mode='w', suffix='.sql', delete=False
            )
            sample_sql = """-- SQL Editor with Syntax Highlighting
SELECT 
    customer_id,
    COUNT(*) as order_count,
    SUM(total_amount) as revenue
FROM orders
WHERE order_date >= '2024-01-01'
GROUP BY customer_id
HAVING COUNT(*) > 5
ORDER BY revenue DESC;
"""
            self._temp_file.write(sample_sql)
            self._temp_file.flush()
            self.file_path = Path(self._temp_file.name)
            content = sample_sql
            
        # Initialize parent
        super().__init__(content='', title=title, **kwargs)
        
        self.on_save_callback = on_save
        self._has_focus = True
        self._content = content
        self._lines = content.splitlines()
        self._cursor_row = 0
        self._cursor_col = 0
        self._modified = False
        self._mouse_selecting = False
        self._selection_start = None
        self._syntax = syntax  # Store syntax type for highlighting
        
        # Create prompt_toolkit text area with appropriate syntax highlighter
        lexer = None
        if syntax == "sql" and SqlLexer:
            lexer = PygmentsLexer(SqlLexer)
        elif syntax == "json" and JsonLexer:
            lexer = PygmentsLexer(JsonLexer)
        elif syntax == "yaml" and YamlLexer:
            lexer = PygmentsLexer(YamlLexer)
        
        self.text_area = TextArea(
            text=content,
            lexer=lexer,
            scrollbar=False,  # We'll handle scrolling
            line_numbers=False,  # We'll draw our own
            wrap_lines=False,
            multiline=True,
            focusable=True,
        )
        
        # Set up key bindings
        self.kb = KeyBindings()
        
        @self.kb.add(Keys.ControlS)
        def _(event):
            """Save file."""
            self.save_file()
            
        @self.kb.add(Keys.ControlX)
        def _(event):
            """Exit editor."""
            self.exit_editor()
            
        # The text area handles most editing operations internally
        
    def save_file(self):
        """Save content to file."""
        content = self.text_area.text
        self.file_path.write_text(content)
        self._modified = False
        
        if self.on_save_callback:
            self.on_save_callback(content)
            
        # Update title to show saved
        if hasattr(self, 'title'):
            if "[Modified]" in self.title:
                self.title = self.title.replace("[Modified] ", "")
                
    def exit_editor(self):
        """Exit the editor."""
        if self._modified:
            self.save_file()
            
        # Toggle editor off
        if hasattr(self.app, 'dispatch'):
            from looking_glass_reactive import Action
            self.app.dispatch(Action('TOGGLE_SQL_EDITOR'))
            
    def render_line(self, y: int) -> Strip:
        """Render a line from the text area with syntax highlighting."""
        # Handle border and title
        if self.border:
            if y == 0 or y == self.size.height - 1:
                return super().render_line(y)
            elif y == 1 and self.show_title and self.title:
                return super().render_line(y)
                
        # Reserve bottom line for status
        if y == self.size.height - 2 and self.border:
            # Status line
            doc = self.text_area.document
            status = f" Line {doc.cursor_position_row + 1}, Col {doc.cursor_position_col + 1} | SQL Mode "
            if self._modified:
                status = "[Modified] " + status
            
            segments = []
            width = self.size.width - (2 if self.border else 0)
            
            # Create inverted status bar
            for i, char in enumerate(status[:width]):
                segments.append(Segment(char, RichStyle(color="black", bgcolor="white")))
            # Pad the rest
            for i in range(len(status), width):
                segments.append(Segment(" ", RichStyle(color="black", bgcolor="white")))
            
            return Strip(segments)
                
        # Calculate content area
        if self.border:
            content_y = y - 2 if (self.show_title and self.title) else y - 1
            content_start = 2 if (self.show_title and self.title) else 1
        else:
            content_y = y
            content_start = 0
            
        # Get viewport dimensions
        width = self.size.width - (2 if self.border else 0)
        height = self.size.height - (3 if self.border else 1)  # Reserve for status line
        if self.show_title and self.title and self.border:
            height -= 1
            
        # Ensure we have valid dimensions
        if width <= 0 or height <= 0:
            return Strip([])
            
        # Get document from text area
        document = self.text_area.document
        lines = document.lines
        
        # Get cursor position
        cursor_row = document.cursor_position_row
        cursor_col = document.cursor_position_col
        
        # Simple scrolling to keep cursor visible
        scroll_offset = 0
        if cursor_row >= height:
            scroll_offset = cursor_row - height + 1
            
        # Get the line to render
        line_idx = content_y + scroll_offset
        
        if 0 <= content_y < height and line_idx < len(lines):
            line_text = lines[line_idx]
            cursor_on_line = (line_idx == cursor_row)
        else:
            line_text = ""
            cursor_on_line = False
            
        # Render with line numbers and syntax highlighting
        segments = []
        
        # Calculate line number width (at least 4 digits)
        line_num_width = max(4, len(str(len(lines))))
        line_num_separator = " │ "
        total_line_num_width = line_num_width + len(line_num_separator)
        
        # Render line number
        if content_y < height and line_idx < len(lines):
            line_num_str = str(line_idx + 1).rjust(line_num_width)
        else:
            line_num_str = " " * line_num_width
            
        # Add line number with muted color using glass background
        if self._precomputed_colors is not None and y < self._precomputed_colors.shape[0]:
            # Render line numbers with glass colors
            x_offset = 1 if self.border else 0  # Start at 1 if we have a border
            for char in line_num_str:
                if x_offset < self._precomputed_colors.shape[1]:
                    color = self._precomputed_colors[y, x_offset]
                    bg_hex = f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"
                else:
                    bg_hex = self.overlay_color
                segments.append(Segment(char, RichStyle(color="#606060", bgcolor=bg_hex)))
                x_offset += 1
            for char in line_num_separator:
                if x_offset < self._precomputed_colors.shape[1]:
                    color = self._precomputed_colors[y, x_offset]
                    bg_hex = f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"
                else:
                    bg_hex = self.overlay_color
                segments.append(Segment(char, RichStyle(color="#404040", bgcolor=bg_hex)))
                x_offset += 1
        else:
            # Fallback without glass colors
            for char in line_num_str:
                segments.append(Segment(char, RichStyle(color="#606060", bgcolor=self.overlay_color)))
            for char in line_num_separator:
                segments.append(Segment(char, RichStyle(color="#404040", bgcolor=self.overlay_color)))
        
        # Get syntax highlighting colors based on language
        if self._syntax == 'yaml':
            # YAML color scheme
            syntax_colors = {
                'key': '#9CDCFE',        # Light blue for keys
                'string': '#CE9178',     # Orange for strings
                'number': '#B5CEA8',     # Light green for numbers
                'boolean': '#569CD6',    # Blue for true/false
                'comment': '#6A9955',    # Green for comments
                'operator': '#D4D4D4',   # Light gray for operators
                'list_marker': '#DCDCAA', # Yellow for - list markers
                'anchor': '#C586C0',     # Purple for anchors/aliases
                'default': '#D4D4D4'     # Default light gray
            }
        elif self._syntax == 'json':
            # JSON color scheme
            syntax_colors = {
                'key': '#9CDCFE',        # Light blue for keys
                'string': '#CE9178',     # Orange for strings
                'number': '#B5CEA8',     # Light green for numbers
                'boolean': '#569CD6',    # Blue for true/false
                'null': '#569CD6',       # Blue for null
                'bracket': '#FFD700',    # Gold for brackets
                'default': '#D4D4D4'     # Default light gray
            }
        else:
            # SQL color scheme (default)
            syntax_colors = {
                'keyword': '#569CD6',     # Blue for SELECT, FROM, WHERE, etc.
                'string': '#CE9178',      # Orange for strings
                'number': '#B5CEA8',      # Light green for numbers
                'comment': '#6A9955',     # Green for comments
                'operator': '#D4D4D4',    # Light gray for operators
                'function': '#DCDCAA',    # Yellow for functions
                'identifier': '#9CDCFE',  # Light blue for identifiers
                'default': '#D4D4D4'      # Default light gray
            }
        
        # SQL keywords for SQL syntax
        sql_keywords = {'SELECT', 'FROM', 'WHERE', 'JOIN', 'ON', 'AS', 'AND', 'OR', 'NOT', 
                       'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'TABLE', 'DROP', 'ALTER',
                       'GROUP', 'BY', 'ORDER', 'HAVING', 'LIMIT', 'OFFSET', 'UNION',
                       'DISTINCT', 'COUNT', 'SUM', 'AVG', 'MAX', 'MIN', 'CASE', 'WHEN', 'THEN'}
        
        # Render the line content with syntax highlighting
        text_width = width - total_line_num_width
        if self._precomputed_colors is not None and y < self._precomputed_colors.shape[0]:
            # Parse line based on syntax type
            words = []
            
            if self._syntax == 'yaml':
                # YAML-specific parsing
                # Check for comment
                if '#' in line_text:
                    comment_pos = line_text.index('#')
                    # Check if # is inside a string
                    in_string = False
                    for i in range(comment_pos):
                        if line_text[i] in '"\'':
                            in_string = not in_string
                    if not in_string:
                        # Split into pre-comment and comment
                        pre_comment = line_text[:comment_pos]
                        comment = line_text[comment_pos:]
                        line_text = pre_comment
                        # We'll add comment at the end
                        
                # Check for list marker at start
                stripped = line_text.lstrip()
                indent = len(line_text) - len(stripped)
                if indent > 0:
                    words.append((' ' * indent, 'space'))
                
                if stripped.startswith('- '):
                    words.append(('- ', 'list_marker'))
                    line_text = line_text[indent + 2:]
                else:
                    line_text = line_text[indent:]
                
                # Check for key: value pattern
                if ':' in line_text and not line_text.strip().startswith('"') and not line_text.strip().startswith("'"):
                    colon_pos = line_text.index(':')
                    key_part = line_text[:colon_pos]
                    rest = line_text[colon_pos:]
                    
                    # Key part
                    words.append((key_part, 'key'))
                    words.append((':', 'operator'))
                    
                    # Value part
                    value = rest[1:].strip() if len(rest) > 1 else ""
                    if value:
                        if value.startswith(' '):
                            words.append((' ', 'space'))
                            value = value[1:]
                        
                        # Determine value type
                        if value.startswith('"') or value.startswith("'"):
                            words.append((value, 'string'))
                        elif value in ['true', 'false', 'yes', 'no', 'on', 'off']:
                            words.append((value, 'boolean'))
                        elif value.replace('.', '').replace('-', '').isdigit():
                            words.append((value, 'number'))
                        elif value == 'null' or value == '~':
                            words.append((value, 'null'))
                        else:
                            # Could be unquoted string or reference
                            words.append((value, 'string'))
                else:
                    # Just a value or continuation
                    if line_text:
                        if line_text.startswith('"') or line_text.startswith("'"):
                            words.append((line_text, 'string'))
                        else:
                            words.append((line_text, 'default'))
                
                # Add comment if exists
                if 'comment' in locals():
                    words.append((comment, 'comment'))
                    
            else:
                # Original SQL/generic parsing
                current_word = ""
                in_string = False
                string_char = None
                
                for i, char in enumerate(line_text):
                    if not in_string and char in '"\'':
                        if current_word:
                            words.append((current_word, 'identifier'))
                            current_word = ""
                        in_string = True
                        string_char = char
                        current_word = char
                    elif in_string:
                        current_word += char
                        if char == string_char and (i == 0 or line_text[i-1] != '\\'):
                            words.append((current_word, 'string'))
                            current_word = ""
                            in_string = False
                    elif char.isspace():
                        if current_word:
                            # Check if it's a keyword
                            if self._syntax == 'sql' and current_word.upper() in sql_keywords:
                                words.append((current_word, 'keyword'))
                            elif current_word.isdigit():
                                words.append((current_word, 'number'))
                            else:
                                words.append((current_word, 'identifier'))
                            current_word = ""
                        words.append((char, 'space'))
                    elif char in '(),;=<>+-*/':
                        if current_word:
                            if self._syntax == 'sql' and current_word.upper() in sql_keywords:
                                words.append((current_word, 'keyword'))
                            else:
                                words.append((current_word, 'identifier'))
                            current_word = ""
                        words.append((char, 'operator'))
                    else:
                        current_word += char
                        
                if current_word:
                    if self._syntax == 'sql' and current_word.upper() in sql_keywords:
                        words.append((current_word, 'keyword'))
                    else:
                        words.append((current_word, 'identifier'))
            
            # Render with syntax colors
            x_pos = 0
            for word, word_type in words:
                for char in word:
                    if x_pos < text_width:
                        # Get glass background color
                        # Account for line numbers and border
                        actual_x = x_pos + total_line_num_width + (1 if self.border else 0)
                        if actual_x < self._precomputed_colors.shape[1]:
                            color = self._precomputed_colors[y, actual_x]
                            bg_hex = f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"
                        else:
                            bg_hex = self.overlay_color
                        
                        # Check if this is cursor position
                        is_cursor = cursor_on_line and x_pos == cursor_col and self._has_focus
                        
                        # Apply syntax color
                        if word_type == 'space':
                            fg_color = syntax_colors.get('default', '#D4D4D4')
                        else:
                            fg_color = syntax_colors.get(word_type, syntax_colors.get('default', '#D4D4D4'))
                        
                        if is_cursor:
                            style = RichStyle(bgcolor="white", color="black", bold=True)
                        else:
                            style = RichStyle(bgcolor=bg_hex, color=fg_color)
                        
                        segments.append(Segment(char, style))
                        x_pos += 1
                        
            # Pad remaining space
            while x_pos < text_width:
                # Account for line numbers and border
                actual_x = x_pos + total_line_num_width + (1 if self.border else 0)
                if actual_x < self._precomputed_colors.shape[1]:
                    color = self._precomputed_colors[y, actual_x]
                    bg_hex = f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"
                else:
                    bg_hex = self.overlay_color
                segments.append(Segment(' ', RichStyle(bgcolor=bg_hex)))
                x_pos += 1
        else:
            # Fallback rendering without glass colors
            # First render line numbers
            for char in line_num_str:
                segments.append(Segment(char, RichStyle(color="#606060", bgcolor=self.overlay_color)))
            for char in line_num_separator:
                segments.append(Segment(char, RichStyle(color="#404040", bgcolor=self.overlay_color)))
                
            # Then render text content
            for x in range(text_width):
                char = line_text[x] if x < len(line_text) else ' '
                is_cursor = cursor_on_line and x == cursor_col and self._has_focus
                
                if is_cursor:
                    style = RichStyle(bgcolor="white", color="black", bold=True)
                else:
                    style = RichStyle(bgcolor=self.overlay_color, color="#D4D4D4")
                
                segments.append(Segment(char, style))
        
        return Strip(segments)
        
    def on_key(self, event) -> None:
        """Handle key events by forwarding to prompt_toolkit."""
        if not self._has_focus:
            return
            
        # Check for keys we don't want to handle - let them bubble up
        if event.key in ['ctrl+e']:  # Add other global shortcuts here as needed
            return
            
        key = event.key
        doc = self.text_area.document
        
        # Map Textual keys to prompt_toolkit
        if key == "ctrl+s":
            self.save_file()
        elif key == "ctrl+x":
            self.exit_editor()
        elif key == "up":
            # Move cursor up
            lines = doc.lines
            row = doc.cursor_position_row
            col = doc.cursor_position_col
            
            if row > 0:
                # Calculate position in previous line
                prev_line_len = len(lines[row - 1])
                new_col = min(col, prev_line_len)
                # Calculate absolute position
                pos = sum(len(lines[i]) + 1 for i in range(row - 1)) + new_col
                self.text_area.document = Document(doc.text, pos)
        elif key == "down":
            # Move cursor down
            lines = doc.lines
            row = doc.cursor_position_row
            col = doc.cursor_position_col
            
            if row < len(lines) - 1:
                # Calculate position in next line
                next_line_len = len(lines[row + 1])
                new_col = min(col, next_line_len)
                # Calculate absolute position
                pos = sum(len(lines[i]) + 1 for i in range(row + 1)) + new_col
                self.text_area.document = Document(doc.text, pos)
        elif key == "left":
            if doc.cursor_position > 0:
                self.text_area.document = Document(doc.text, doc.cursor_position - 1)
        elif key == "right":
            if doc.cursor_position < len(doc.text):
                self.text_area.document = Document(doc.text, doc.cursor_position + 1)
        elif key == "home":
            # Move to start of line
            row = doc.cursor_position_row
            pos = sum(len(doc.lines[i]) + 1 for i in range(row))
            self.text_area.document = Document(doc.text, pos)
        elif key == "end":
            # Move to end of line
            row = doc.cursor_position_row
            pos = sum(len(doc.lines[i]) + 1 for i in range(row)) + len(doc.lines[row])
            self.text_area.document = Document(doc.text, pos)
        elif key == "enter":
            # Insert newline
            pos = doc.cursor_position
            text = doc.text
            self.text_area.text = text[:pos] + '\n' + text[pos:]
            self.text_area.document = Document(self.text_area.text, pos + 1)
            self._modified = True
        elif key == "backspace":
            if doc.cursor_position > 0:
                pos = doc.cursor_position
                text = doc.text
                self.text_area.text = text[:pos-1] + text[pos:]
                self.text_area.document = Document(self.text_area.text, pos - 1)
                self._modified = True
        elif key == "delete":
            pos = doc.cursor_position
            text = doc.text
            if pos < len(text):
                self.text_area.text = text[:pos] + text[pos+1:]
                self.text_area.document = Document(self.text_area.text, pos)
                self._modified = True
        elif key == "tab":
            pos = doc.cursor_position
            text = doc.text
            self.text_area.text = text[:pos] + '    ' + text[pos:]
            self.text_area.document = Document(self.text_area.text, pos + 4)
            self._modified = True
        # Handle printable characters including space
        elif hasattr(event, 'character') and event.character:
            # Use the character from the event if available
            char = event.character
            pos = doc.cursor_position
            text = doc.text
            self.text_area.text = text[:pos] + char + text[pos:]
            self.text_area.document = Document(self.text_area.text, pos + 1)
            self._modified = True
        elif key == "space":
            # Handle space explicitly
            pos = doc.cursor_position
            text = doc.text
            self.text_area.text = text[:pos] + ' ' + text[pos:]
            self.text_area.document = Document(self.text_area.text, pos + 1)
            self._modified = True
            
        else:
            # Don't handle other keys - let them bubble up to parent
            # This allows global shortcuts like Ctrl+E to work
            pass
            
        # Update title if modified
        if self._modified and hasattr(self, 'title'):
            if "[Modified]" not in self.title:
                self.title = "[Modified] " + self.title
                
        self.refresh()
        
    def on_mount(self):
        """Initialize when mounted."""
        self._has_focus = True
        
    def on_click(self, event) -> None:
        """Handle mouse clicks to position cursor."""
        self._has_focus = True
        
        # Get click position relative to widget
        x = event.x
        y = event.y
        
        # Account for border if present
        if self.border:
            x -= 1
            y -= 1
            # Also account for title if shown
            if self.show_title and self.title:
                y -= 1
        
        # Calculate line number width
        lines = self.text_area.document.lines
        line_num_width = max(4, len(str(len(lines))))
        line_num_separator_width = 3  # " │ "
        total_line_num_width = line_num_width + line_num_separator_width
        
        # Adjust x for line numbers
        text_x = x - total_line_num_width
        
        # Get scroll offset
        doc = self.text_area.document
        cursor_row = doc.cursor_position_row
        height = self.size.height - (3 if self.border else 1)  # Reserve for status line
        if self.show_title and self.title and self.border:
            height -= 1
        
        # Calculate scroll offset
        scroll_offset = 0
        if cursor_row >= height:
            scroll_offset = cursor_row - height + 1
        
        # Calculate which line was clicked
        clicked_line = y + scroll_offset
        
        # Bounds check
        if clicked_line < 0 or clicked_line >= len(lines):
            return
        if text_x < 0:
            # Clicked on line numbers, just select the line
            text_x = 0
        
        # Get the line that was clicked
        line_text = lines[clicked_line] if clicked_line < len(lines) else ""
        
        # Calculate column position (clamp to line length)
        clicked_col = min(text_x, len(line_text))
        if clicked_col < 0:
            clicked_col = 0
        
        # Calculate absolute position in document
        new_position = sum(len(lines[i]) + 1 for i in range(clicked_line)) + clicked_col
        
        # Update cursor position
        if new_position <= len(doc.text):
            self.text_area.document = Document(doc.text, new_position)
            self._cursor_row = clicked_line
            self._cursor_col = clicked_col
            self.refresh()
    
    def on_mouse_down(self, event) -> None:
        """Handle mouse button press for selection."""
        self._mouse_selecting = True
        self._selection_start = None
        # Process the click to position cursor
        self.on_click(event)
        # Store selection start position
        if hasattr(self.text_area, 'document'):
            self._selection_start = self.text_area.document.cursor_position
    
    def on_mouse_move(self, event) -> None:
        """Handle mouse drag for text selection."""
        if not self._mouse_selecting or self._selection_start is None:
            return
        
        # Calculate position from mouse coordinates (similar to on_click)
        x = event.x
        y = event.y
        
        # Account for border if present
        if self.border:
            x -= 1
            y -= 1
            if self.show_title and self.title:
                y -= 1
        
        # Calculate line number width
        lines = self.text_area.document.lines
        line_num_width = max(4, len(str(len(lines))))
        total_line_num_width = line_num_width + 3  # " │ "
        
        # Adjust x for line numbers
        text_x = x - total_line_num_width
        if text_x < 0:
            text_x = 0
        
        # Get scroll offset
        doc = self.text_area.document
        cursor_row = doc.cursor_position_row
        height = self.size.height - (3 if self.border else 1)
        if self.show_title and self.title and self.border:
            height -= 1
        
        scroll_offset = 0
        if cursor_row >= height:
            scroll_offset = cursor_row - height + 1
        
        # Calculate which line was dragged to
        target_line = y + scroll_offset
        
        # Bounds check
        if target_line < 0:
            target_line = 0
        elif target_line >= len(lines):
            target_line = len(lines) - 1
        
        # Get the line and calculate column
        line_text = lines[target_line] if target_line < len(lines) else ""
        target_col = min(text_x, len(line_text))
        
        # Calculate absolute position
        new_position = sum(len(lines[i]) + 1 for i in range(target_line)) + target_col
        
        # Create selection by setting document with selection
        if new_position <= len(doc.text):
            # Create new document with selection
            from prompt_toolkit.document import Document
            self.text_area.document = Document(
                doc.text, 
                cursor_position=new_position,
                selection=(self._selection_start, new_position) if self._selection_start is not None else None
            )
            self.refresh()
    
    def on_mouse_up(self, event) -> None:
        """Handle mouse button release."""
        self._mouse_selecting = False
        
    def set_focus(self, focused: bool) -> None:
        """Set focus state."""
        self._has_focus = focused
        if hasattr(self, 'refresh'):
            self.refresh()
        
    def get_text(self) -> str:
        """Get the current text content."""
        return self.text_area.text
    
    def update_content(self, new_content: str) -> None:
        """Update the editor content with new text."""
        if new_content != self.text_area.text:
            self.text_area.text = new_content
            self._content = new_content
            self._lines = new_content.splitlines()
            # Reset cursor to beginning
            self._cursor_row = 0
            self._cursor_col = 0
            # Update document
            self.text_area.document = Document(new_content, 0)
            # Mark as not modified since this is external content update
            self._modified = False
            # Update title if needed
            if hasattr(self, 'title') and "[Modified]" in self.title:
                self.title = self.title.replace("[Modified] ", "")
            # Refresh display
            if hasattr(self, 'refresh'):
                self.refresh()