#!/usr/bin/env python3
"""
Glass Terminal Editor Widget
============================

A widget that embeds a terminal editor (nano/vim/etc) within the Glass widget system
using PTY (pseudo-terminal) for true terminal emulation.

Features:
- Full terminal emulation via PTY
- Real-time output capture and rendering
- Keyboard input forwarding
- File change monitoring
- Configurable editor (nano, vim, etc)
"""

import os
import pty
import select
import subprocess
import threading
import time
import tempfile
import fcntl
import termios
import struct
from pathlib import Path
from typing import Optional, Callable, List, Tuple
from collections import deque

from .looking_glass import AbsoluteGlassPanel
from textual.app import App
from textual import events
from textual.reactive import reactive
from rich.segment import Segment
from rich.style import Style as RichStyle
from textual.strip import Strip
import asyncio


class GlassTerminalEditor(AbsoluteGlassPanel):
    """A glass widget that embeds a terminal editor via PTY"""
    
    def __init__(
        self,
        editor: str = "nano",
        file_path: Optional[str] = None,
        on_save: Optional[Callable[[str], None]] = None,
        title: str = "SQL Editor",
        border: bool = True,
        show_title: bool = True,
        **kwargs
    ):
        """
        Initialize the terminal editor widget.
        
        Args:
            editor: Editor command (nano, vim, etc)
            file_path: Path to file to edit (creates temp file if None)
            on_save: Callback when file is saved
            title: Widget title
            border: Show border
            show_title: Show title in border
            **kwargs: Standard glass widget parameters
        """
        # Initialize parent with empty content
        super().__init__(content='', title=title, border=border, show_title=show_title, **kwargs)
        
        self.editor = editor
        self.on_save_callback = on_save
        
        # Store initial dimensions from kwargs
        self._init_width = kwargs.get('width', 80)
        self._init_height = kwargs.get('height', 24)
        
        # Create or use file
        if file_path:
            self.file_path = Path(file_path)
            self._temp_file = None
        else:
            # Create temp file
            self._temp_file = tempfile.NamedTemporaryFile(
                mode='w', suffix='.sql', delete=False
            )
            self._temp_file.write("-- Write your SQL here\n")
            self._temp_file.flush()
            self.file_path = Path(self._temp_file.name)
        
        # PTY and process management
        self.master_fd = None
        self.slave_fd = None
        self.process = None
        self._running = False
        
        # Terminal buffer
        self.terminal_lines = deque(maxlen=1000)  # Keep last 1000 lines
        self.cursor_x = 0
        self.cursor_y = 0
        self._last_file_mtime = None
        
        # Threading
        self._reader_thread = None
        self._monitor_thread = None
        
        # Terminal size
        self._terminal_cols = 80
        self._terminal_rows = 24
        
        # ANSI state tracking
        self._ansi_buffer = ""
        self._in_escape_sequence = False
        
        # Input buffer for handling escape sequences
        self._input_buffer = []
        
        # Focus state
        self._has_focus = True  # Default to focused when created
        
    def on_mount(self):
        """Start the terminal editor when widget is mounted"""
        # Glass widgets don't call super().on_mount()
        # Log for debugging
        if self.app:
            self.app.log(f"GlassTerminalEditor mounted with editor={self.editor}, file={self.file_path}")
        # Delay starting editor to ensure widget is fully initialized
        if self.app:
            # Use set_timer instead of call_later for delayed execution
            self.app.set_timer(0.1, self._start_editor)
        
    def on_unmount(self):
        """Clean up when widget is unmounted"""
        self._stop_editor()
        # Glass widgets don't call super().on_unmount()
        
    def _start_editor(self):
        """Start the editor process in a PTY"""
        if self._running:
            return
            
        try:
            # Create PTY
            self.master_fd, self.slave_fd = pty.openpty()
            
            # Set terminal size based on widget size
            self._update_terminal_size()
            
            # Make master non-blocking
            flags = fcntl.fcntl(self.master_fd, fcntl.F_GETFL)
            fcntl.fcntl(self.master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            
            # Start editor process
            env = os.environ.copy()
            env['TERM'] = 'xterm-256color'
            env['LINES'] = str(self._terminal_rows)
            env['COLUMNS'] = str(self._terminal_cols)
            
            self.process = subprocess.Popen(
                [self.editor, str(self.file_path)],
                stdin=self.slave_fd,
                stdout=self.slave_fd,
                stderr=self.slave_fd,
                env=env,
                preexec_fn=os.setsid
            )
            
            self._running = True
            
            if self.app:
                self.app.log(f"Started {self.editor} process with PID {self.process.pid}")
            
            # Store initial file modification time
            if self.file_path.exists():
                self._last_file_mtime = self.file_path.stat().st_mtime
            
            # Start reader thread
            self._reader_thread = threading.Thread(target=self._read_pty_output)
            self._reader_thread.daemon = True
            self._reader_thread.start()
            
            # Start file monitor thread
            self._monitor_thread = threading.Thread(target=self._monitor_file_changes)
            self._monitor_thread.daemon = True
            self._monitor_thread.start()
            
        except Exception as e:
            self.app.log.error(f"Failed to start editor: {e}")
            self._running = False
            
    def _stop_editor(self):
        """Stop the editor process"""
        self._running = False
        
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except:
                try:
                    self.process.kill()
                except:
                    pass
                    
        if self.master_fd:
            try:
                os.close(self.master_fd)
            except:
                pass
                
        if self.slave_fd:
            try:
                os.close(self.slave_fd)
            except:
                pass
                
        # Clean up temp file if we created one
        if self._temp_file and self.file_path.exists():
            try:
                os.unlink(self.file_path)
            except:
                pass
                
    def _update_terminal_size(self):
        """Update PTY size based on widget dimensions"""
        # Get dimensions from parameters or size
        if hasattr(self, 'size') and self.size:
            cols = self.size.width
            rows = self.size.height
        else:
            # Use the parameters passed during creation
            cols = getattr(self, '_init_width', 80)
            rows = getattr(self, '_init_height', 24)
            
        # Account for borders
        cols = cols - 2 if self.border else cols
        rows = rows - 2 if self.border else rows
        
        # Account for title
        if self.border and self.show_title and self.title:
            rows -= 1
            
        self._terminal_cols = max(1, cols)
        self._terminal_rows = max(1, rows)
        
        if self.app:
            self.app.log(f"Terminal size: {self._terminal_cols}x{self._terminal_rows}")
        
        # Update PTY size if running
        if self.master_fd:
            try:
                fcntl.ioctl(
                    self.master_fd,
                    termios.TIOCSWINSZ,
                    struct.pack('HHHH', self._terminal_rows, self._terminal_cols, 0, 0)
                )
            except:
                pass
                
    def _read_pty_output(self):
        """Read output from PTY in a separate thread"""
        if self.app:
            self.app.log("PTY reader thread started")
        
        while self._running:
            try:
                # Use select with timeout
                r, _, _ = select.select([self.master_fd], [], [], 0.1)
                if r:
                    data = os.read(self.master_fd, 4096)
                    if data:
                        # Log raw data for debugging
                        if self.app:
                            self.app.log(f"PTY output: {len(data)} bytes")
                        # Process the terminal output
                        self._process_terminal_output(data.decode('utf-8', errors='replace'))
                        # Request UI refresh
                        if self.app:
                            self.app.call_from_thread(self.refresh)
            except OSError as e:
                # PTY closed
                if self.app:
                    self.app.log(f"PTY closed: {e}")
                break
            except Exception as e:
                if self.app:
                    self.app.log.error(f"Error reading PTY: {e}")
                break
                
        if self.app:
            self.app.log("PTY reader thread ended")
                
    def _process_terminal_output(self, data: str):
        """Process raw terminal output including ANSI escape sequences"""
        # For now, just append to buffer
        # In a real implementation, we'd parse ANSI sequences properly
        lines = data.split('\n')
        for line in lines[:-1]:
            self.terminal_lines.append(line)
        # Handle partial line
        if lines[-1]:
            if self.terminal_lines:
                self.terminal_lines[-1] += lines[-1]
            else:
                self.terminal_lines.append(lines[-1])
                
        # Debug log
        if self.app:
            self.app.log(f"Terminal output processed: {len(lines)} lines, total buffer: {len(self.terminal_lines)}")
            # Log first few lines for debugging
            if len(self.terminal_lines) > 0:
                self.app.log(f"First line: {repr(self.terminal_lines[0][:50]) if self.terminal_lines[0] else 'empty'}")
                
    def _monitor_file_changes(self):
        """Monitor file for changes and trigger save callback"""
        while self._running:
            try:
                if self.file_path.exists():
                    current_mtime = self.file_path.stat().st_mtime
                    if self._last_file_mtime and current_mtime > self._last_file_mtime:
                        # File was modified
                        content = self.file_path.read_text()
                        if self.on_save_callback:
                            # Call from main thread
                            if self.app:
                                self.app.call_from_thread(
                                    lambda: self.on_save_callback(content)
                                )
                    self._last_file_mtime = current_mtime
                time.sleep(0.5)  # Check every 500ms
            except Exception as e:
                if self.app:
                    self.app.log.error(f"Error monitoring file: {e}")
                
    def on_key(self, event: events.Key) -> None:
        """Forward key events to the PTY"""
        # Only process if we have focus
        if not self._has_focus:
            return
            
        if not self._running or not self.master_fd:
            return
            
        try:
            # Build key sequence
            key_sequence = ""
            
            # Handle special keys
            if event.key == "ctrl+c":
                key_sequence = "\x03"
            elif event.key == "ctrl+x":
                key_sequence = "\x18"
            elif event.key == "ctrl+o":
                key_sequence = "\x0f"
            elif event.key == "ctrl+s":
                key_sequence = "\x13"
            elif event.key == "ctrl+w":
                key_sequence = "\x17"
            elif event.key == "ctrl+k":
                key_sequence = "\x0b"
            elif event.key == "ctrl+u":
                key_sequence = "\x15"
            elif event.key == "ctrl+a":
                key_sequence = "\x01"
            elif event.key == "ctrl+e":
                key_sequence = "\x05"
            elif event.key == "escape":
                key_sequence = "\x1b"
            elif event.key == "enter":
                key_sequence = "\r"
            elif event.key == "tab":
                key_sequence = "\t"
            elif event.key == "backspace":
                key_sequence = "\x7f"
            elif event.key == "delete":
                key_sequence = "\x1b[3~"
            elif event.key == "up":
                key_sequence = "\x1b[A"
            elif event.key == "down":
                key_sequence = "\x1b[B"
            elif event.key == "right":
                key_sequence = "\x1b[C"
            elif event.key == "left":
                key_sequence = "\x1b[D"
            elif event.key == "home":
                key_sequence = "\x1b[H"
            elif event.key == "end":
                key_sequence = "\x1b[F"
            elif event.key == "pageup":
                key_sequence = "\x1b[5~"
            elif event.key == "pagedown":
                key_sequence = "\x1b[6~"
            elif len(event.key) == 1:
                # Regular character
                key_sequence = event.key
                
            # Send to PTY
            if key_sequence:
                os.write(self.master_fd, key_sequence.encode('utf-8'))
                
        except Exception as e:
            if self.app:
                self.app.log.error(f"Error sending key to PTY: {e}")
            
    def render_line(self, y: int) -> Strip:
        """Render a line with glass effects."""
        # Debug first few renders
        if not hasattr(self, '_render_count'):
            self._render_count = 0
        self._render_count += 1
        if self._render_count < 100 and y == 0 and self.app:  # Only log first line, first 100 renders
            self.app.log(f"Rendering line {y}, terminal has {len(self.terminal_lines)} lines, size={self.size if hasattr(self, 'size') else 'no size'}")
        
        # Ensure we have size
        if not hasattr(self, 'size') or not self.size:
            return Strip([Segment(" " * 80)])
            
        # Let parent handle border and title
        if self.border:
            # Check if this is a border/title line
            if y == 0 or y == self.size.height - 1:
                return super().render_line(y)
            elif y == 1 and self.show_title and self.title:
                return super().render_line(y)
            
            # Calculate content line index
            content_y = y - 2 if (self.show_title and self.title) else y - 1
            viewport_height = self.size.height - 2
            if self.show_title and self.title:
                viewport_height -= 1
        else:
            content_y = y
            viewport_height = self.size.height
            
        # Check if we're within the content area
        if content_y < 0 or content_y >= viewport_height:
            return super().render_line(y)
            
        # Get terminal line
        if content_y < len(self.terminal_lines):
            line_text = list(self.terminal_lines)[content_y]
        else:
            line_text = ""
            
        # Render with glass effect
        # Ensure we have a size
        if not hasattr(self, 'size') or not self.size:
            # Return empty line if no size yet
            return Strip([Segment(" " * 80)])
            
        width = self.size.width - (2 if self.border else 0)
        segments = []
        
        # Use precomputed glass colors if available
        if self._precomputed_colors is not None and y < self._precomputed_colors.shape[0]:
            for x in range(width):
                # Get character
                char = line_text[x] if x < len(line_text) else ' '
                
                # Get glass color
                actual_x = x + (1 if self.border else 0)
                if actual_x < self._precomputed_colors.shape[1]:
                    color = self._precomputed_colors[y, actual_x]
                    bg_hex = f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"
                else:
                    bg_hex = self.overlay_color
                
                # Create style - white text on glass background
                style = RichStyle(bgcolor=bg_hex, color="white", bold=True)
                segments.append(Segment(char, style))
        else:
            # Fallback rendering without glass colors
            for x in range(width):
                char = line_text[x] if x < len(line_text) else ' '
                style = RichStyle(bgcolor=self.overlay_color, color="white", bold=True)
                segments.append(Segment(char, style))
        
        return Strip(segments)
        
    def get_content(self) -> str:
        """Get current file content"""
        if self.file_path.exists():
            return self.file_path.read_text()
        return ""
        
    def set_content(self, content: str):
        """Set file content"""
        self.file_path.write_text(content)
        if self.file_path.exists():
            self._last_file_mtime = self.file_path.stat().st_mtime
            
    def set_focus(self, focused: bool):
        """Set focus state"""
        self._has_focus = focused
        
    def on_click(self, event) -> None:
        """Handle mouse clicks to set focus"""
        self.set_focus(True)