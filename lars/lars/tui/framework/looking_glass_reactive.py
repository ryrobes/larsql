#!/usr/bin/env python3
"""
Looking Glass Reactive - Enhanced reactive framework for terminal UIs
=====================================================================

Extends the base Looking Glass library with:
- Redux-style state management
- Widget reconciliation engine
- Performance tracking
- Fast widget operations
- Action dispatch system

This provides the "machinery" for building reactive apps while keeping
application code focused on business logic.
"""

import hashlib
import math
import copy
import time
from collections import deque
from dataclasses import dataclass
from typing import Dict, List, Any, Optional, Callable, Union, Tuple
import os
from typing import Optional

# Check if we're in headless mode
HEADLESS_MODE = os.environ.get('REACTIVE_HEADLESS', 'false').lower() == 'true'

if HEADLESS_MODE:
    # Headless mode - provide minimal implementations
    from .looking_glass import App as LookingGlassApp

    class AbsoluteGlassWidget:
        def __init__(self, *args, **kwargs): pass

    class AbsoluteGlassPanel(AbsoluteGlassWidget):
        pass

    class UltraFastTrueColorBackground(AbsoluteGlassWidget):
        pass

    class AbsoluteGlassConnectionCanvas(AbsoluteGlassWidget):
        pass

    class Segment:
        def __init__(self, text, style=None):
            self.text = text
            self.style = style

    class RichStyle:
        def __init__(self, **kwargs): pass

    class Strip:
        pass

    # Mock glass widget classes
    class GlassNativeContainer:
        pass

    class GlassScrollableContainer:
        pass

    class GlassTextEditor:
        pass

    class GlassTerminalEditor:
        pass

    class GlassNanoEditor:
        pass

    class GlassPromptToolkitEditor:
        pass

else:
    # Normal mode - import everything
    from .looking_glass import (
        LookingGlassApp, AbsoluteGlassWidget, AbsoluteGlassPanel,
        UltraFastTrueColorBackground, AbsoluteGlassConnectionCanvas
    )
    from rich.segment import Segment
    from rich.style import Style as RichStyle
    from textual.strip import Strip
    from .glass_native_container import GlassNativeContainer
    from .glass_scrollable_container import GlassScrollableContainer
    from .glass_text_editor import GlassTextEditor
    from .glass_terminal_editor import GlassTerminalEditor
    from .glass_nano_editor import GlassNanoEditor
    from .glass_prompt_toolkit_editor import GlassPromptToolkitEditor

# These imports are used in both modes but may fail in headless
if not HEADLESS_MODE:
    # Only import glass modules in normal mode
    from .glass_plot_container import GlassPlotContainer, GlassPlotextDirect
    from .glass_plot_container_color import GlassPlotextDirectColor
    from .glass_plot_container_ansi import GlassPlotextAnsi
    from .glass_plot_container_clean import GlassPlotextClean
    from .glass_plot_container_fixed import GlassPlotextFixed
    from .glass_plot_minimal import GlassPlotextMinimal
    from .glass_plot_textual import GlassPlotextTextual
    from .glass_plot_simple import GlassPlotextSimple
else:
    # Create mock classes for headless mode
    GlassPlotContainer = type('GlassPlotContainer', (), {})
    GlassPlotextDirect = type('GlassPlotextDirect', (), {})
    GlassPlotextDirectColor = type('GlassPlotextDirectColor', (), {})
    GlassPlotextAnsi = type('GlassPlotextAnsi', (), {})
    GlassPlotextClean = type('GlassPlotextClean', (), {})
    GlassPlotextFixed = type('GlassPlotextFixed', (), {})
    GlassPlotextMinimal = type('GlassPlotextMinimal', (), {})
    GlassPlotextTextual = type('GlassPlotextTextual', (), {})
    GlassPlotextSimple = type('GlassPlotextSimple', (), {})

if not HEADLESS_MODE:
    from .glass_plot_final import GlassPlotextFinal
    from .glass_figlet_widget import GlassFigletWidget
    from .glass_ansi_panel import GlassAnsiPanel
    from .glass_live_widget import LiveDataGlassWidget, LiveFPSCounter
    from textual.app import ComposeResult
    from textual.events import MouseDown, MouseUp
else:
    # Mock classes for headless mode
    GlassPlotextFinal = type('GlassPlotextFinal', (), {})
    GlassFigletWidget = type('GlassFigletWidget', (), {})
    GlassAnsiPanel = type('GlassAnsiPanel', (), {})
    LiveDataGlassWidget = type('LiveDataGlassWidget', (), {})
    LiveFPSCounter = type('LiveFPSCounter', (), {})
    ComposeResult = list

    class MouseDown:
        pass

    class MouseUp:
        pass


# ==============================================================================
# ACTION SYSTEM
# ==============================================================================

@dataclass
class Action:
    """Redux-style action for state changes"""
    type: str
    payload: Any = None


# ==============================================================================
# REACTIVE BASE CLASS
# ==============================================================================

class ReactiveGlassApp(LookingGlassApp):
    """
    Base class for reactive Looking Glass applications.

    Provides:
    - State management with dispatch/reducer pattern
    - Automatic widget reconciliation
    - Performance tracking
    - Fast widget operations
    - Background management tied to state
    - CSS merge for data-driven styling

    CSS Merge Feature:
    ==================
    Add a 'css_merge' key to any widget definition to apply CSS styles:

    {
        'id': 'my_widget',
        'type': 'panel',
        'content': 'Hello',
        'css_merge': {
            'color': 'yellow',              # Text color
            'background': '$panel-lighten-1', # Background (supports Textual variables)
            'border': 'double red',         # Border style
            'padding': '1 2',               # Padding (top/bottom left/right)
            'text_align': 'center',         # Text alignment
            'text_style': 'bold italic',    # Text style
            'width': '50%',                 # Override width via CSS
            'height': '10',                 # Override height via CSS
            'margin': '1',                  # Margin
            'border_title_align': 'center', # Border title alignment
            'opacity': '0.8',               # Opacity
            'display': 'none',              # Hide widget
        }
    }

    CSS properties support:
    - Dynamic values based on state
    - Textual CSS variables (e.g., $panel, $primary)
    - All standard Textual CSS properties
    - Snake_case or kebab-case (text_align or text-align)

    The CSS merge is applied after glass morphism properties, allowing
    fine-grained control over widget appearance while maintaining the
    glass effects.
    """

    def __init__(self, background_image: str = None, background_darken: float = 0.2):
        super().__init__(background_darken=background_darken)

        # Store background settings
        self._initial_background_image = background_image
        self._initial_background_darken = background_darken

        # State management
        self.state = self.create_initial_state()
        self._mounted_widgets = {}
        self._last_background = None
        self._positions_dirty = False
        self._connections_dirty = True
        self._widget_definitions = []
        self._connection_canvas = None

        # Virtual DOM for efficient updates
        self._virtual_dom = {}  # id -> widget definition
        self._dom_dirty = set()  # Set of widget IDs that need updating

        # Focus management
        self._focused_widget_id = None
        self._focus_stack = []

        # Performance tracking
        self._frame_times = deque(maxlen=60)
        self._last_render_time = time.time()  # Initialize to current time like the working version
        self._render_count = 0
        self._enable_performance_tracking = True

        # Fixed frame rate mode
        self._fixed_fps_mode = False
        self._target_fps = 60  # Default target
        self._frame_timer = None

        # Interactive features
        self._selected_widget_id = None
        self._hovered_widget_id = None

        # Hover throttling
        self._last_hover_check_time = 0
        self._hover_throttle_interval = 0.005  # 5ms = 200 checks per second max

        # Drag and drop state
        self._dragging_widget_id = None
        self._drag_start_mouse_x = 0
        self._drag_start_mouse_y = 0
        self._drag_start_widget_x = 0
        self._drag_start_widget_y = 0
        self._drag_offset_x = 0
        self._drag_offset_y = 0

        # Double-click attach drag mode
        self._attached_widget_id = None
        self._attach_offset_x = 0
        self._attach_offset_y = 0
        self._last_mouse_x = 0
        self._last_mouse_y = 0

        # Resize mode
        self._resize_mode = False
        self._resize_widget_id = None
        self._resize_original_width = 0
        self._resize_original_height = 0
        self._resize_start_mouse_x = 0
        self._resize_start_mouse_y = 0

        # Debug log for visualization
        self._debug_log = []
        self._max_debug_lines = 20

        # Reconciliation control
        self._reconciliation_paused = False
        self._pending_widget_updates = {}  # Store updates during pause
        self._resume_reconciliation_timer = None

        # Internal widget position/size overrides
        self._widget_overrides = {}  # widget_id -> {x, y, width, height}

        # Click event tracking for debugging
        self._last_click_time = 0
        self._click_count = 0

        # Context menu state
        self._context_menu_state = {
            'visible': False,
            'x': 0,
            'y': 0,
            'target_widget_id': None,
            'target_mouse_x': 0,
            'target_mouse_y': 0,
            'items': [],
            'selected_index': 0,
        }
        self._context_menu_visible = False  # Track visibility for Y-offset compensation

        # Clear debug log file on startup
        # try:
        #     with open('looking_glass_debug.log', 'w') as f:
        #         f.write(f"=== Looking Glass Debug Log Started at {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        # except:
        #     pass

    def debug_log(self, message: str):
        """Add a debug message that will be visible in state - NO FILE I/O TO AVOID BLOCKING"""
        timestamp = time.strftime("%H:%M:%S.%f")[:-3]  # Include milliseconds
        full_message = f"[{timestamp}] {message}"

        # Add to in-memory log
        self._debug_log.append(full_message)
        # Keep only last N lines
        if len(self._debug_log) > self._max_debug_lines:
            self._debug_log = self._debug_log[-self._max_debug_lines:]
        # Update state so it's visible
        self.state['_debug_log'] = self._debug_log.copy()

        # DISABLED: File I/O - this was blocking the event loop!
        # try:
        #     with open('looking_glass_debug.log', 'a') as f:
        #         f.write(full_message + '\n')
        #         f.flush()  # Ensure immediate write
        # except Exception as e:
        #     # Don't let logging errors break the app
        #     pass

    def _resume_reconciliation(self):
        """Resume reconciliation after a delay"""
        # Clear cached widget definitions
        if hasattr(self, '_cached_widget_definitions'):
            delattr(self, '_cached_widget_definitions')

        # Ensure all interactive states are cleared
        if self._attached_widget_id or self._resize_widget_id:
            self.debug_log(f"WARNING: Interactive state still active during resume - attached: {self._attached_widget_id}, resize: {self._resize_widget_id}")
            self._attached_widget_id = None
            self._resize_widget_id = None
            self._resize_mode = False
            self.state['_attached_widget'] = None
            self.state['_resize_widget'] = None

        self._reconciliation_paused = False
        self.debug_log("Reconciliation resumed")
        self._resume_reconciliation_timer = None
        # Force a full render now that reconciliation is resumed
        self.render_ui()

    def is_interactive_operation_active(self) -> bool:
        """Check if drag or resize operation is active"""
        return bool(self._attached_widget_id or self._resize_mode)

    def _apply_widget_overrides(self, widgets: List[Dict]):
        """Apply internal position/size overrides to widgets"""
        for widget in widgets:
            widget_id = widget.get('id')
            if widget_id and widget_id in self._widget_overrides:
                overrides = self._widget_overrides[widget_id]
                # Apply position overrides
                if 'x' in overrides:
                    widget['x'] = overrides['x']
                if 'y' in overrides:
                    widget['y'] = overrides['y']
                # Apply size overrides
                if 'width' in overrides:
                    widget['width'] = overrides['width']
                if 'height' in overrides:
                    widget['height'] = overrides['height']

    # ===========================================================================
    # ABSTRACT METHODS - Override in subclasses
    # ===========================================================================

    def create_initial_state(self) -> Dict:
        """
        Override to provide initial application state.

        Returns:
            Dict containing initial state
        """
        state = {
            # Background settings (can be changed reactively)
            '_background_image': self._initial_background_image,
            '_background_darken': self._initial_background_darken,
        }
        return state

    def reducer(self, state: Dict, action: Action) -> Dict:
        """
        Override to handle state transformations.

        Args:
            state: Current state
            action: Action to process

        Returns:
            New state (should be immutable - don't modify input)
        """
        # Handle internal performance updates
        if action.type == '__UPDATE_PERFORMANCE__':
            import copy
            new_state = copy.deepcopy(state)
            new_state['fps'] = action.payload['fps']
            new_state['frame_time'] = action.payload['frame_time']
            return new_state

        # Handle background change action
        elif action.type == '__SET_BACKGROUND__':
            import copy
            new_state = copy.deepcopy(state)
            if 'path' in action.payload:
                new_state['_background_image'] = action.payload['path']
                # Load the new background immediately
                self.load_background(action.payload['path'])
            if 'darken' in action.payload:
                new_state['_background_darken'] = action.payload['darken']
                self.background_darken = action.payload['darken']
                # Reload background with new darkening
                if new_state.get('_background_image'):
                    self.load_background(new_state['_background_image'])
            return new_state

        # Default: return unchanged
        return state

    def create_widgets(self) -> List[Dict]:
        """
        Override to create widget definitions from current state.

        Returns:
            List of widget definition dictionaries
        """
        return []

    # ===========================================================================
    # LIFECYCLE HOOKS - Optional overrides
    # ===========================================================================

    def on_state_changed(self, old_state: Dict, new_state: Dict):
        """
        Called after state changes. Override for side effects.

        Args:
            old_state: Previous state
            new_state: Current state
        """
        # Update color palette in state if it's available
        if hasattr(self, 'color_palette'):
            new_state['_color_palette'] = self.color_palette

    def should_track_performance(self) -> bool:
        """
        Override to control performance tracking.

        Returns:
            True to enable FPS tracking
        """
        return self._enable_performance_tracking

    def get_performance_update_interval(self) -> float:
        """
        Override to control how often performance stats update.

        Returns:
            Interval in seconds
        """
        return 0.5

    def _preprocess_padding_for_widgets(self, widgets: List[Dict]) -> List[Dict]:
        """
        Preprocess widgets to wrap those that need padding in panels.

        This is a simple solution that wraps widgets that don't natively support
        padding in a borderless panel that does.
        """
        # Widget types that already handle padding properly (or need special handling)
        padding_aware_types = ['panel', 'text_editor', 'terminal_editor', 'nano_editor',
                               'prompt_toolkit_editor', 'scrollable', 'rich_dsl']

        processed = []
        for widget_def in widgets:
            padding = widget_def.get('padding', 0)
            widget_type = widget_def.get('type', 'widget')

            # If no padding or widget already handles it, keep as-is
            if padding == 0 or widget_type in padding_aware_types:
                processed.append(widget_def)
                continue

            # For basic widgets that can be wrapped in a panel
            if widget_type == 'widget':
                # Create a panel wrapper
                wrapped = {
                    'id': widget_def.get('id', 'wrapped'),
                    'type': 'panel',
                    'title': '',  # No title for clean look
                    'border': False,  # No border
                    'show_title': False,
                    'padding': padding,
                    'content': widget_def.get('content', ''),
                    # Copy all positioning and styling
                    'x': widget_def.get('x', 0),
                    'y': widget_def.get('y', 0),
                    'width': widget_def.get('width', 30),
                    'height': widget_def.get('height', 10),
                    'sticky_x': widget_def.get('sticky_x'),
                    'sticky_y': widget_def.get('sticky_y'),
                    'z_index': widget_def.get('z_index', 0),
                    'overlay_color': widget_def.get('overlay_color', 'blue'),
                    'blend_opacity': widget_def.get('blend_opacity', 0.5),
                    'darken_factor': widget_def.get('darken_factor', 0.0),
                    'blur': widget_def.get('blur', 2),
                    'css_merge': widget_def.get('css_merge'),
                }
                processed.append(wrapped)
            else:
                # For other widget types (plots, figlets, rich_dsl, etc), just pass through
                # without padding support for now
                processed.append(widget_def)

        return processed

    # ===========================================================================
    # CORE REACTIVE SYSTEM
    # ===========================================================================

    def compose(self) -> ComposeResult:
        """Only yield the background - widgets are managed dynamically"""
        yield UltraFastTrueColorBackground(id="background")

    def load_background(self, image_path: Optional[str] = None, use_transition: bool = True):
        """Override to use our custom background from state if no path provided"""
        # If no path provided, check our state
        if image_path is None and hasattr(self, 'state'):
            custom_bg = self.state.get('_background_image')
            if custom_bg:
                image_path = custom_bg

        # Call parent's load_background with the path
        # Note: Parent class has transitions disabled, so use_transition is ignored
        super().load_background(image_path, use_transition=use_transition)

        # Clear all render caches when background changes
        self._clear_all_render_caches()

    def _clear_all_render_caches(self):
        """Clear all render caches when background changes"""
        # Clear background widget's cache (already done in update_ansi_ultra)

        # Only clear if widgets are mounted
        if hasattr(self, '_mounted_widgets'):
            # Clear all mounted glass widget caches
            for widget_id, widget in self._mounted_widgets.items():
                if hasattr(widget, '_strip_cache'):
                    widget._strip_cache = {}

                # Some widgets might have other caches
                if hasattr(widget, '_render_cache'):
                    widget._render_cache = {}

                if hasattr(widget, '_blend_cache'):
                    widget._blend_cache = {}

                # Force widget refresh
                if hasattr(widget, 'refresh'):
                    widget.refresh()

        # Also clear any cached widgets that might not be mounted yet
        if hasattr(self, '_widget_cache'):
            self._widget_cache = {}

        # Force full re-render if system is initialized
        if hasattr(self, '_any_widget_changed'):
            self._any_widget_changed = True
            self.render_ui()

    def on_mount(self):
        """Initialize the reactive system"""
        # Let parent do its initialization - our overridden load_background will handle custom bg
        super().on_mount()

        self.call_after_refresh(self.render_ui)

        # Trigger a second render after initial mount to ensure connections
        # are rendered after widgets have their regions set
        self.call_after_refresh(self._ensure_initial_connections)

        # Start performance monitoring if enabled
        if self.should_track_performance():
            interval = self.get_performance_update_interval()
            self.state['_debug_perf_timer_interval'] = interval
            self.state['_debug_perf_timer_enabled'] = True
            self._perf_timer = self.set_interval(
                interval,
                self._update_performance_stats
            )
            # Force an initial render to start collecting frame times
            self.call_after_refresh(self.render_ui)
        else:
            self.state['_debug_perf_timer_enabled'] = False

        # Start fixed FPS mode if enabled
        if self._fixed_fps_mode:
            self._start_fixed_fps_mode()

        # Store absolute widgets for position updates
        self._absolute_widgets = []

    def _ensure_initial_connections(self):
        """Ensure connections are rendered after initial widget mounting"""
        # Force connections to be dirty so they get re-rendered
        self._connections_dirty = True
        # Trigger another render to update connections with proper widget regions
        self.render_ui()

    def dispatch(self, action: Action):
        """
        Dispatch an action through the reducer and trigger re-render.

        Args:
            action: Action to dispatch
        """
        # Log action if debugging
        self.log(f"Action: {action.type} {action.payload}")

        # Get new state from reducer
        old_state = self.state
        self.state = self.reducer(old_state, action)

        # Call hook for side effects
        if self.state != old_state:
            self.on_state_changed(old_state, self.state)

        # Trigger re-render
        self.render_ui()

    def render_ui(self):
        """Core render cycle with performance tracking"""

        # Sanity check: ensure we don't have conflicting states
        if self._attached_widget_id and self._resize_widget_id:
            self.debug_log(f"ERROR: Both drag and resize active! attached={self._attached_widget_id}, resize={self._resize_widget_id}")
            # Clear both to recover
            self._attached_widget_id = None
            self._resize_widget_id = None
            self._resize_mode = False
            self._reconciliation_paused = False
            self.state['_attached_widget'] = None
            self.state['_resize_widget'] = None
            if hasattr(self, '_cached_widget_definitions'):
                delattr(self, '_cached_widget_definitions')

        # Track frame time
        self._track_frame_time()
        # Debug: write to a widget to see if this is being called
        if hasattr(self, '_debug_render_count'):
            self._debug_render_count += 1
        else:
            self._debug_render_count = 1

        # Time each phase for diagnostics
        start_time = time.time()

        # Check for background changes
        self._check_background_change()
        bg_time = time.time()

        # Get widget definitions from app
        # During interactive operations (drag/resize), reuse cached definitions for performance
        if self._reconciliation_paused and hasattr(self, '_cached_widget_definitions'):
            # Use shallow copy to avoid blocking - widget defs are usually safe to share
            widgets = [w.copy() for w in self._cached_widget_definitions]
        else:
            widgets = self.create_widgets()
            # Apply padding preprocessing automatically
            widgets = self._preprocess_padding_for_widgets(widgets)
            # Cache for next frame during interactive operations
            if self._reconciliation_paused:
                # Use shallow copy for caching to avoid blocking
                self._cached_widget_definitions = [w.copy() for w in widgets]

        # Debug log widget state before overrides
        if self._debug_render_count % 50 == 0:  # Log every 50th render to avoid spam
            self.debug_log(f"\n=== RENDER #{self._debug_render_count} - PRE-OVERRIDE WIDGET STATE ===")
            for widget in widgets:
                if 'id' in widget:
                    self.debug_log(f"{widget['id']}: x={widget.get('x')}, y={widget.get('y')}, from create_widgets()")

        # Apply internal widget overrides FIRST (positions, sizes, states)
        # This ensures dragged widgets start from their current position, not original
        self._apply_widget_overrides(widgets)

        # Apply attached widget position override AFTER overrides
        if self._attached_widget_id:
            for widget in widgets:
                if widget.get('id') == self._attached_widget_id:
                    # Override position with mouse position
                    widget['x'] = self._last_mouse_x - self._attach_offset_x
                    widget['y'] = self._last_mouse_y - self._attach_offset_y
                    # Ensure within bounds
                    if hasattr(self, 'size') and self.size:
                        widget['x'] = max(0, min(widget['x'], self.size.width - widget.get('width', 10)))
                        widget['y'] = max(0, min(widget['y'], self.size.height - widget.get('height', 5)))
                    # Force update by adding a timestamp
                    widget['_force_update'] = time.time()
                    # Also update virtual DOM immediately - but avoid deep copy
                    if self._attached_widget_id in self._virtual_dom:
                        self._virtual_dom[self._attached_widget_id]['x'] = widget['x']
                        self._virtual_dom[self._attached_widget_id]['y'] = widget['y']
                        self._virtual_dom[self._attached_widget_id]['_force_update'] = widget['_force_update']
                    break

        # Apply resize mode size override AFTER overrides
        elif self._resize_mode and self._resize_widget_id:
            for widget in widgets:
                if widget.get('id') == self._resize_widget_id:
                    # Calculate new size based on mouse movement
                    delta_x = self._last_mouse_x - self._resize_start_mouse_x
                    delta_y = self._last_mouse_y - self._resize_start_mouse_y

                    widget['width'] = max(10, self._resize_original_width + delta_x)
                    widget['height'] = max(3, self._resize_original_height + delta_y)

                    # Add visual indicator that we're resizing
                    if widget.get('title'):
                        widget['title'] = widget['title'] + ' [RESIZING]'
                    # Force update by adding a timestamp
                    widget['_force_update'] = time.time()
                    # Also update virtual DOM immediately
                    if self._resize_widget_id in self._virtual_dom:
                        self._virtual_dom[self._resize_widget_id]['width'] = widget['width']
                        self._virtual_dom[self._resize_widget_id]['height'] = widget['height']
                        self._virtual_dom[self._resize_widget_id]['_force_update'] = widget['_force_update']
                    break

        # Debug log widget state after overrides
        if self._debug_render_count % 50 == 0:  # Log every 50th render to avoid spam
            self.debug_log(f"\n=== RENDER #{self._debug_render_count} - POST-OVERRIDE WIDGET STATE ===")
            for widget in widgets:
                if 'id' in widget:
                    self.debug_log(f"{widget['id']}: x={widget.get('x')}, y={widget.get('y')}, after overrides")
            self.debug_log(f"Widget overrides: {self._widget_overrides}")

        # Inject selection state into widget definitions
        # This ensures proper dirty tracking when selection changes
        for widget in widgets:
            widget_id = widget.get('id')
            if widget_id:
                widget['_selected'] = (widget_id == self._selected_widget_id)
                widget['_hovered'] = (widget_id == self._hovered_widget_id)

                # CRITICAL: Inject transition frame hash for vDOM detection during transitions
                if self.is_transition_active():
                    # Check if mounted widget has a transition data_hash
                    if widget_id in self._mounted_widgets:
                        mounted_widget = self._mounted_widgets[widget_id]
                        if hasattr(mounted_widget, 'data_hash'):
                            # Propagate the transition hash to widget definition
                            widget['data_hash'] = mounted_widget.data_hash
                            widget['_transition_frame'] = True

        self._widget_definitions = widgets
        create_time = time.time()

        # Store timing info
        self.state['_debug_bg_time'] = (bg_time - start_time) * 1000
        self.state['_debug_create_time'] = (create_time - bg_time) * 1000

        # Generate individual connection line widgets if we have connections
        if self._has_connections(widgets):
            connection_widgets = self._generate_connection_line_widgets(widgets)
            # Add connection widgets with lower z-index so they appear behind regular widgets
            widgets = connection_widgets + widgets

        # Always include context menu in widget list (visible or hidden)
        if hasattr(self, '_context_menu_state'):
            if self._context_menu_state['visible']:
                menu_def = self._create_context_menu_widget()
                if menu_def:
                    widgets.append(menu_def)
            else:
                # Context menu should be hidden - add off-screen definition
                widgets.append({
                    'id': 'context_menu',
                    'type': 'rich_dsl',
                    'content': 'Hidden',
                    'x': 9999,
                    'y': 9999,
                    'width': 10,
                    'height': 1,
                    'overlay_color': 'darkblue',
                    'blend_opacity': 0.1,
                    '_context_menu': True
                })

        # Sort widgets by Y then X position before reconciling
        # Context menu ALWAYS goes LAST to avoid Y-cascade issues
        def sort_key(w):
            if w.get('id') == 'context_menu':
                return (999999, 999999)  # Always last

            # OLD
            # return (w.get('y', 0), w.get('x', 0))

            # TEST ! 7.25.25.0947
            # Handle string positions (like 'bottom-X')
            y = w.get('y', 0)
            x = w.get('x', 0)

            # Convert string positions to large numbers for sorting
            if isinstance(y, str):
                if y.startswith('bottom-'):
                    # Put bottom widgets near the end (but before context menu)
                    y = 99900 - int(y.replace('bottom-', ''))
                else:
                    y = 99000  # Other string positions

            if isinstance(x, str):
                if x.startswith('right-'):
                    x = 99900 - int(x.replace('right-', ''))
                else:
                    x = 0  # Left align by default

            return (y, x)

        sorted_widgets = sorted(widgets, key=sort_key)
        sort_time = time.time()

        # Reconcile DOM for all widgets (INCLUDING context menu)
        self._reconcile_widgets(sorted_widgets)
        reconcile_time = time.time()

        # Store timing info
        self.state['_debug_sort_time'] = (sort_time - create_time) * 1000
        self.state['_debug_reconcile_time'] = (reconcile_time - sort_time) * 1000

        # Update positions if needed
        if self._positions_dirty:
            if hasattr(self, '_update_all_positions'):
                self._update_all_positions()
            self._positions_dirty = False
            # After positions are updated, connections need updating too
            self._connections_dirty = True

        # Update connections after widgets have been positioned
        if self._connections_dirty:
            self._update_connections()
            self._connections_dirty = False

        # Context menu is now handled in main widget flow above
        # self._update_context_menu()

        # Force screen refresh
        # self.screen.refresh()
        pass

        # Store total render time
        end_time = time.time()
        self.state['_debug_total_render_time'] = (end_time - start_time) * 1000

    def _has_connections(self, widgets):
        """Check if any widgets have parent_of relationships"""
        return any(w.get('parent_of') for w in widgets)

    # ===========================================================================
    # CONNECTION MANAGEMENT
    # ===========================================================================

    def _update_connections(self):
        """Update connections - now handled by individual line widgets"""
        # Connections are now generated as individual widgets in render_ui
        # This method is kept for compatibility but does nothing
        pass

    def _ensure_initial_connections(self):
        """Ensure connections are rendered after initial mount"""
        self._connections_dirty = True
        self.render_ui()

    def _pre_allocate_context_menu(self):
        """Pre-allocate context menu widget off-screen to avoid Y-cascade issues"""
        # Create a hidden context menu off-screen
        menu_def = {
            'id': 'context_menu',
            'type': 'panel',
            'title': '',
            'content': ['Pre-allocated'],
            'x': 9999,  # Hide to the right
            'y': 9999,  # Hide below viewport
            'width': 10,
            'height': 1,
            'overlay_color': 'darkblue',
            'blend_opacity': 0.1,
            'z_index': 9999,
            '_floating': True,
            '_context_menu': True
        }
        # Add it once at startup
        self._add_widget(menu_def)
        self.log("Pre-allocated context menu widget off-screen")

    def _calculate_connections(self, widget_data: List[Dict]) -> List[Dict]:
        """Calculate connection data for the canvas."""
        connections = []

        # First pass: collect widget positions
        widget_positions = {}
        for widget_def in widget_data:
            widget_id = widget_def.get('id')
            if widget_id:
                # Check if widget is already mounted and has a region
                if widget_id in self._mounted_widgets:
                    widget = self._mounted_widgets[widget_id]
                    if hasattr(widget, 'region') and widget.region:
                        # Use actual rendered position from region
                        widget_positions[widget_id] = {
                            'x': widget.region.x,
                            'y': widget.region.y,
                            'width': widget.region.width,
                            'height': widget.region.height
                        }
                        self.log(f"Widget {widget_id} has region: x={widget.region.x}, y={widget.region.y}")
                        continue

                # Fall back to definition positions
                width = widget_def.get('width', 20)
                height = widget_def.get('height', 5)
                if isinstance(width, str):
                    width = 20  # Default for now
                if isinstance(height, str):
                    height = 5  # Default for now

                widget_positions[widget_id] = {
                    'x': widget_def.get('x', 0),
                    'y': widget_def.get('y', 0),
                    'width': width,
                    'height': height
                }

        # Second pass: generate connections
        for widget_def in widget_data:
            parent_id = widget_def.get('id')
            children = widget_def.get('parent_of', [])

            if not parent_id or not children:
                continue

            # Ensure children is a list
            if isinstance(children, str):
                children = [children]

            parent_pos = widget_positions.get(parent_id)
            if not parent_pos:
                continue

            for child_id in children:
                child_pos = widget_positions.get(child_id)
                if not child_pos:
                    continue

                # Get connection styling
                conn_style = widget_def.get('connection_style', {})

                # Calculate centers
                px = parent_pos['x'] + parent_pos['width'] // 2
                py = parent_pos['y'] + parent_pos['height'] // 2
                cx = child_pos['x'] + child_pos['width'] // 2
                cy = child_pos['y'] + child_pos['height'] // 2

                # Apply any user-specified offset
                y_offset = conn_style.get('y_offset', 0)
                py += y_offset
                cy += y_offset

                # Add connection
                connections.append({
                    'start': (px, py),
                    'end': (cx, cy),
                    'style': conn_style.get('line_style', 'solid'),
                    'color': conn_style.get('color', 'cyan'),
                    'opacity': conn_style.get('opacity', 0.3)
                })

        return connections

    def _generate_connection_line_widgets(self, widget_data: List[Dict]) -> List[Dict]:
        """
        Generate connection line widgets using smart path routing that avoids obstacles.
        """
        # Try stable Manhattan routing first (proper connected lines)
        try:
            from stable_manhattan_connections import generate_stable_manhattan_connections
            return generate_stable_manhattan_connections(widget_data)
        except ImportError:
            pass

        # Try fixed segment approach for widget stability
        try:
            from fixed_segment_connections import generate_fixed_segment_connections
            return generate_fixed_segment_connections(widget_data)
        except ImportError:
            pass

        # Try single canvas approach
        try:
            from single_canvas_connections import generate_single_canvas_connections
            return generate_single_canvas_connections(widget_data)
        except ImportError:
            pass

        # Fall back to other implementations
        try:
            from smart_path_routing import generate_smart_path_connections
            return generate_smart_path_connections(widget_data)
        except ImportError:
            try:
                from simple_clean_routing import generate_simple_clean_connections
                return generate_simple_clean_connections(widget_data)
            except ImportError:
                try:
                    from better_connection_routing import generate_smart_connections
                    return generate_smart_connections(widget_data)
                except ImportError:
                    # Fall back to original implementation
                    return self._generate_connection_line_widgets_original(widget_data)

    def _generate_connection_line_widgets_original(self, widget_data: List[Dict]) -> List[Dict]:
        """
        Generate individual line segment widgets for connections.
        This is more efficient than using a full-page canvas as only
        the actual line pixels are rendered.
        """
        connection_widgets = []
        conn_index = 0

        # First pass: collect widget positions
        widget_positions = {}
        for widget_def in widget_data:
            widget_id = widget_def.get('id')
            if widget_id:
                # Check if widget is already mounted and has a region
                if widget_id in self._mounted_widgets:
                    widget = self._mounted_widgets[widget_id]
                    if hasattr(widget, 'region') and widget.region:
                        # Use actual rendered position from region
                        widget_positions[widget_id] = {
                            'x': widget.region.x,
                            'y': widget.region.y,
                            'width': widget.region.width,
                            'height': widget.region.height
                        }
                        continue

                # Fall back to definition positions
                width = widget_def.get('width', 20)
                height = widget_def.get('height', 5)
                if isinstance(width, str):
                    width = 20  # Default for percentage widths
                if isinstance(height, str):
                    height = 5  # Default for percentage heights

                widget_positions[widget_id] = {
                    'x': widget_def.get('x', 0),
                    'y': widget_def.get('y', 0),
                    'width': width,
                    'height': height
                }

        # Second pass: generate connection line segments
        for widget_def in widget_data:
            parent_id = widget_def.get('id')
            children = widget_def.get('parent_of', [])

            if not parent_id or not children:
                continue

            # Ensure children is a list
            if isinstance(children, str):
                children = [children]

            parent_pos = widget_positions.get(parent_id)
            if not parent_pos:
                continue

            for child_id in children:
                child_pos = widget_positions.get(child_id)
                if not child_pos:
                    continue

                # Get connection styling
                conn_style = widget_def.get('connection_style', {})
                line_style = conn_style.get('line_style', 'solid')
                line_color = conn_style.get('color', 'cyan')
                line_opacity = conn_style.get('opacity', 0.3)
                z_index = conn_style.get('z_index', 50)

                # Simple routing: always go from parent center to child center
                # using L-shaped paths

                px = parent_pos['x'] + parent_pos['width'] // 2
                py = parent_pos['y'] + parent_pos['height'] // 2
                cx = child_pos['x'] + child_pos['width'] // 2
                cy = child_pos['y'] + child_pos['height'] // 2

                # Simple L-shaped routing
                # Horizontal first, then vertical

                # Horizontal segment
                if px != cx:
                    width = abs(cx - px)
                    if width > 0:
                        connection_widgets.append({
                            'id': f'conn_{parent_id}_{child_id}_h_{px}_{py}',
                            'type': 'line_segment',
                            'direction': 'horizontal',
                            'line_style': line_style,
                            'x': min(px, cx),
                            'y': py,
                            'width': width,
                            'height': 1,
                            'overlay_color': line_color,
                            'blend_opacity': line_opacity,
                            'z_index': z_index,
                            'border': False,
                            '_connection': True,
                            '_is_connection': True,
                            'css_merge': {
                                'color': line_color
                            }
                        })

                    # Vertical segment at child X
                    if py != cy:
                        start_y = min(py, cy)
                        height = abs(cy - py)
                        if height > 0:
                            connection_widgets.append({
                                'id': f'conn_{parent_id}_{child_id}_v_{cx}_{start_y}',
                                'type': 'line_segment',
                                'direction': 'vertical',
                                'line_style': line_style,
                                'x': cx,
                                'y': start_y,
                                'width': 1,
                                'height': height,
                                'overlay_color': line_color,
                                'blend_opacity': line_opacity,
                                'z_index': z_index,
                                'border': False,
                                '_connection': True,
                                '_is_connection': True,
                                'css_merge': {
                                    'color': line_color
                                }
                            })

        return connection_widgets

    def _get_line_char(self, style: str, direction: str) -> str:
        """Get the appropriate line character for a style and direction."""
        line_chars = {
            'solid': {'horizontal': '─', 'vertical': '│', 'corner': '┼'},
            'double': {'horizontal': '═', 'vertical': '║', 'corner': '╬'},
            'thick': {'horizontal': '━', 'vertical': '┃', 'corner': '╋'},
            'block': {'horizontal': '█', 'vertical': '█', 'corner': '█'},
            'dashed': {'horizontal': '╌', 'vertical': '╎', 'corner': '┼'},
            'dotted': {'horizontal': '┄', 'vertical': '┆', 'corner': '┼'}
        }
        chars = line_chars.get(style, line_chars['solid'])
        return chars.get(direction, '?')

    def _generate_connection_widgets(self, widget_data: List[Dict]) -> List[Dict]:
        """Generate improved connection widget definitions with proper colors and smooth lines."""
        try:
            from improved_connections import generate_improved_connection_widgets

            connection_widgets = []

            # Create widget map
            widget_map = {w['id']: w for w in widget_data if 'id' in w}

            # Process each widget that has parent_of relationships
            for widget_def in widget_data:
                if not widget_def.get('parent_of'):
                    continue

                child_ids = widget_def['parent_of']
                if isinstance(child_ids, str):
                    child_ids = [child_ids]

                conn_style = widget_def.get('connection_style', {})

                # Generate improved connections
                new_connections = generate_improved_connection_widgets(
                    widget_def, child_ids, widget_map, conn_style
                )
                connection_widgets.extend(new_connections)

            self.log(f"Generated {len(connection_widgets)} improved connection segments")
            return connection_widgets

        except ImportError:
            # Fallback to old method if improved module not available
            self.log("Falling back to old connection generator")
            return self._generate_connection_widgets_OLD(widget_data)

    def _generate_connection_widgets_OLD(self, widget_data: List[Dict]) -> List[Dict]:
        """Generate connection widget definitions based on parent_of relationships."""
        connection_widgets = []

        # Debug log
        self.log(f"Generating connections for {len(widget_data)} widgets")

        # First pass: collect widget positions
        widget_positions = {}

        for widget_def in widget_data:
            widget_id = widget_def.get('id')
            if widget_id:
                # Check if widget is already mounted and has a region
                if widget_id in self._mounted_widgets:
                    widget = self._mounted_widgets[widget_id]
                    if hasattr(widget, 'region') and widget.region:
                        # Use actual rendered position from region
                        widget_positions[widget_id] = {
                            'x': widget.region.x,
                            'y': widget.region.y,
                            'width': widget.region.width,
                            'height': widget.region.height,
                            'use_region': True
                        }
                        self.log(f"Using region for {widget_id}: x={widget.region.x}, y={widget.region.y}")
                        continue

                # Fall back to definition positions
                width = widget_def.get('width', 20)
                height = widget_def.get('height', 5)
                if isinstance(width, str):
                    width = 20  # Default for now
                if isinstance(height, str):
                    height = 5  # Default for now

                widget_positions[widget_id] = {
                    'x': widget_def.get('x', 0),
                    'y': widget_def.get('y', 0),
                    'width': width,
                    'height': height,
                    'use_region': False
                }

        # Second pass: generate connections
        for widget_def in widget_data:
            parent_id = widget_def.get('id')
            children = widget_def.get('parent_of', [])

            if not parent_id or not children:
                continue

            # Ensure children is a list
            if isinstance(children, str):
                children = [children]

            parent_pos = widget_positions.get(parent_id)
            if not parent_pos:
                continue

            for child_id in children:
                child_pos = widget_positions.get(child_id)
                if not child_pos:
                    continue

                # Get connection styling
                conn_style = widget_def.get('connection_style', {})

                # Calculate centers
                px = parent_pos['x'] + parent_pos['width'] // 2
                py = parent_pos['y'] + parent_pos['height'] // 2
                cx = child_pos['x'] + child_pos['width'] // 2
                cy = child_pos['y'] + child_pos['height'] // 2

                # If we're using regions, positions are already correct
                # If we're using definitions, we need to apply cumulative offsets
                if not parent_pos.get('use_region', False) or not child_pos.get('use_region', False):
                    # We're using definition positions, which need offset adjustment
                    # The connection lines themselves will be positioned with offsets too
                    # So we don't need to adjust the positions here
                    pass

                # Apply any additional user-specified offset
                y_offset = conn_style.get('y_offset', 0)
                py += y_offset
                cy += y_offset
                line_style = conn_style.get('line_style', 'solid')
                line_color = conn_style.get('color', 'cyan')
                line_opacity = conn_style.get('opacity', 0.3)
                line_darken = conn_style.get('darken', 0.5)
                z_index = conn_style.get('z_index', 5)

                # Generate unique IDs with coordinates to avoid conflicts
                h_id = f'connection_{parent_id}_{child_id}_h_{px}_{py}_{cx}'
                v_id = f'connection_{parent_id}_{child_id}_v_{cx}_{py}_{cy}'

                # Horizontal segment
                if px != cx:
                    connection_widgets.append({
                        'id': h_id,
                        'type': 'line_segment',
                        'direction': 'horizontal',
                        'line_style': line_style,
                        'x': min(px, cx),
                        'y': py,
                        'width': abs(cx - px),
                        'height': 1,
                        'z_index': z_index,
                        'overlay_color': line_color,
                        'blend_opacity': line_opacity,
                        'darken_factor': line_darken,
                        '_is_connection': True,  # Special flag for positioning system
                        'css_merge': {
                            'color': line_color  # Ensure color is applied via CSS
                        }
                    })

                # Vertical segment
                if py != cy:
                    connection_widgets.append({
                        'id': v_id,
                        'type': 'line_segment',
                        'direction': 'vertical',
                        'line_style': line_style,
                        'x': cx,
                        'y': min(py, cy),
                        'width': 1,
                        'height': abs(cy - py),
                        'z_index': z_index,
                        'overlay_color': line_color,
                        'blend_opacity': line_opacity,
                        'darken_factor': line_darken,
                        '_is_connection': True,  # Special flag for positioning system
                        'css_merge': {
                            'color': line_color  # Ensure color is applied via CSS
                        }
                    })

        self.log(f"Generated {len(connection_widgets)} connection segments")
        return connection_widgets

    # ===========================================================================
    # WIDGET RECONCILIATION ENGINE
    # ===========================================================================

    def _diff_widget_definitions(self, new_widgets: List[Dict]) -> Dict[str, str]:
        """
        Diff new widget definitions against virtual DOM.
        Returns a dict of widget_id -> change_type

        Change types:
        - 'added': Widget is new
        - 'removed': Widget was removed
        - 'updated': Widget properties changed
        - 'unchanged': Widget is the same
        """
        changes = {}
        new_widget_map = {w['id']: w for w in new_widgets}

        # Check for removed widgets
        for widget_id in self._virtual_dom:
            if widget_id not in new_widget_map:
                changes[widget_id] = 'removed'
                self._dom_dirty.add(widget_id)

        # Check for new or changed widgets
        for widget in new_widgets:
            widget_id = widget['id']
            old_widget = self._virtual_dom.get(widget_id)

            if old_widget is None:
                changes[widget_id] = 'added'
                self._dom_dirty.add(widget_id)
            else:
                # Deep compare key properties that affect rendering
                if self._widget_changed(old_widget, widget):
                    changes[widget_id] = 'updated'
                    self._dom_dirty.add(widget_id)
                else:
                    changes[widget_id] = 'unchanged'

        return changes

    def _widget_changed(self, old: Dict, new: Dict) -> bool:
        """Check if widget properties that affect rendering have changed"""
        # Properties that trigger re-render
        render_props = [
            'x', 'y', 'width', 'height', 'content', 'title',
            'overlay_color', 'blend_opacity', 'darken_factor',
            'css_merge', 'border_css_merge', 'title_css_merge',
            'z_index', 'border', 'show_title', 'padding',
            'sticky_x', 'sticky_y',  # Alignment properties
            'plot_data',  # For GlassPlotextDirect widgets
            'text',       # For GlassFigletWidget
            'font',       # For GlassFigletWidget
            'template_config',  # For GlassTemplateWidget
            'widget_props',     # For GlassNativeContainer
            'content_lines',    # For GlassScrollableContainer
            'initial_text',     # For GlassPromptToolkitEditor
            '_selected',        # Selection state
            '_hovered'          # Hover state
        ]

        # Check for force update flag
        if new.get('_force_update') != old.get('_force_update'):
            return True

        for prop in render_props:
            # Deep comparison for complex properties
            if prop == 'plot_data':
                # For plot data, use data hash if provided
                old_plot = old.get('plot_data', {})
                new_plot = new.get('plot_data', {})

                # If either has a data_hash, use that for comparison
                old_hash = old_plot.get('data_hash')
                new_hash = new_plot.get('data_hash')
                if old_hash or new_hash:
                    if old_hash != new_hash:
                        return True
                else:
                    # Fallback to full comparison for backward compatibility
                    # Quick checks first
                    if old_plot.get('type') != new_plot.get('type'):
                        return True
                    if old_plot.get('title') != new_plot.get('title'):
                        return True

                    # For data arrays, just check if they're different references
                    # (assume if someone set new data, it changed)
                    for key in ['x', 'y', 'data']:
                        if key in new_plot and key in old_plot:
                            # If the lists are different objects, assume changed
                            if new_plot[key] is not old_plot[key]:
                                return True
                        elif key in new_plot or key in old_plot:
                            # One has the key, the other doesn't
                            return True

            elif prop in ['widget_props', 'template_config']:
                # Use id() comparison first for performance, fallback to string comparison
                old_val = old.get(prop, {})
                new_val = new.get(prop, {})
                if old_val is new_val:
                    continue  # Same object, definitely unchanged
                # Quick type check before expensive string conversion
                if type(old_val) != type(new_val):
                    return True
                # Only do expensive string conversion if needed
                if str(old_val) != str(new_val):
                    return True
            else:
                if old.get(prop) != new.get(prop):
                    return True

        # Check if content changed (handle list content)
        old_content = old.get('content', '')
        new_content = new.get('content', '')

        # Normalize content to string for comparison
        if isinstance(old_content, list):
            old_content = '\n'.join(str(item) for item in old_content)
        if isinstance(new_content, list):
            new_content = '\n'.join(str(item) for item in new_content)

        if old_content != new_content:
            return True

        return False

    def _reconcile_widgets(self, widget_data: List[Dict]):
        """
        Reconcile current widgets with desired state.
        Uses virtual DOM diffing to efficiently update only what changed.
        """
        # PERFORMANCE: Track if ANYTHING changed
        self._any_widget_changed = False

        # If reconciliation is paused and we're in interactive mode, only update the active widget
        if self._reconciliation_paused:
            # Process the widget being dragged/resized OR the context menu
            active_widget_id = self._attached_widget_id or self._resize_widget_id

            # Also check if context menu needs updating
            if self._context_menu_state.get('visible', False):
                # Find and update context menu
                for item in widget_data:
                    if isinstance(item, list):
                        for w in item:
                            if w and w.get('id') == 'context_menu':
                                if 'context_menu' in self._mounted_widgets:
                                    self._update_widget('context_menu', w)
                                else:
                                    self._add_widget(w)
                                self._virtual_dom['context_menu'] = copy.deepcopy(w)
                                break
                    elif item and item.get('id') == 'context_menu':
                        if 'context_menu' in self._mounted_widgets:
                            self._update_widget('context_menu', item)
                        else:
                            self._add_widget(item)
                        self._virtual_dom['context_menu'] = copy.deepcopy(item)
                        break

            if active_widget_id:
                # Find the active widget in the new data
                active_widget = None
                for item in widget_data:
                    if isinstance(item, list):
                        for w in item:
                            if w and w.get('id') == active_widget_id:
                                active_widget = w
                                break
                    elif item and item.get('id') == active_widget_id:
                        active_widget = item
                        break

                if active_widget:
                    # Verify the widget still exists and is the same one
                    if active_widget_id in self._mounted_widgets:
                        mounted_widget = self._mounted_widgets[active_widget_id]
                        # Check if it's actually mounted
                        if not mounted_widget.parent:
                            self.debug_log(f"WARNING: Widget {active_widget_id} exists but not mounted!")
                            # Remove from mounted widgets
                            del self._mounted_widgets[active_widget_id]
                            # Re-add it
                            self._add_widget(active_widget)
                        else:
                            # Update normally
                            self._update_widget(active_widget_id, active_widget)
                    else:
                        # Widget doesn't exist yet, add it
                        self.debug_log(f"WARNING: Active widget {active_widget_id} not in mounted widgets!")
                        self._add_widget(active_widget)
                    # Update virtual DOM with new state
                    self._virtual_dom[active_widget_id] = copy.deepcopy(active_widget)
                else:
                    self.debug_log(f"ERROR: Could not find active widget {active_widget_id} in widget data!")
            return

        # Flatten any nested lists
        flat_widgets = []
        for item in widget_data:
            if isinstance(item, list):
                flat_widgets.extend(item)
            elif item is not None:
                flat_widgets.append(item)

        # Separate live widgets from normal widgets
        normal_widgets = []
        live_widgets = []

        for widget in flat_widgets:
            if widget.get('live_mode', False):
                live_widgets.append(widget)
            else:
                normal_widgets.append(widget)

        # Store live widgets for direct updates (but don't reconcile them)
        if not hasattr(self, '_live_widgets'):
            self._live_widgets = {}

        for live_widget in live_widgets:
            widget_id = live_widget.get('id')
            if widget_id:
                # Create live widget if it doesn't exist
                if widget_id not in self._mounted_widgets:
                    self._add_widget(live_widget)
                # Store for direct updates
                self._live_widgets[widget_id] = live_widget

        # Continue with normal reconciliation for non-live widgets
        flat_widgets = normal_widgets

        # Diff against virtual DOM
        changes = self._diff_widget_definitions(flat_widgets)

        # Count changes for debugging
        added = sum(1 for c in changes.values() if c == 'added')
        removed = sum(1 for c in changes.values() if c == 'removed')
        updated = sum(1 for c in changes.values() if c == 'updated')

        # Count connection widgets separately
        conn_widgets = [w for w in flat_widgets if w.get('_connection')]
        conn_changes = {wid: change for wid, change in changes.items()
                        if any(w['id'] == wid and w.get('_connection') for w in flat_widgets)}

        # Store debug info
        updated_ids = [wid for wid, change in changes.items() if change == 'updated']
        self.state['_debug_dom_changes'] = {
            'added': added,
            'removed': removed,
            'updated': updated,
            'updated_ids': updated_ids,  # Track which widgets were updated
            'unchanged': sum(1 for c in changes.values() if c == 'unchanged'),
            'total': len(changes),
            'connections': len(conn_widgets),
            'conn_updated': sum(1 for c in conn_changes.values() if c == 'updated')
        }

        # Process changes
        ansi_render_time = 0  # Track ANSI rendering time
        for widget_id, change_type in changes.items():
            if change_type == 'removed':
                self._remove_widget(widget_id)
                del self._virtual_dom[widget_id]
                self._any_widget_changed = True
            elif change_type == 'added':
                widget_def = next(w for w in flat_widgets if w['id'] == widget_id)
                ansi_start = time.time()
                self._add_widget(widget_def)
                ansi_render_time += (time.time() - ansi_start)
                # Shallow copy instead of deep copy to avoid blocking
                self._virtual_dom[widget_id] = widget_def.copy()
                self._any_widget_changed = True
            elif change_type == 'updated':
                widget_def = next(w for w in flat_widgets if w['id'] == widget_id)
                ansi_start = time.time()
                self._update_widget(widget_id, widget_def)
                ansi_render_time += (time.time() - ansi_start)
                # Shallow copy instead of deep copy to avoid blocking
                self._virtual_dom[widget_id] = widget_def.copy()
                self._any_widget_changed = True

        # Store ANSI rendering time
        self.state['_debug_ansi_render_time'] = ansi_render_time * 1000  # Convert to ms

        # Clear dirty set after processing
        self._dom_dirty.clear()

    def _create_widget(self, definition: Dict) -> Union[AbsoluteGlassWidget, AbsoluteGlassPanel, GlassNativeContainer, GlassScrollableContainer, GlassTextEditor, GlassTerminalEditor, GlassPlotContainer, GlassPlotextDirect, GlassPlotextDirectColor, GlassPlotextAnsi, GlassPlotextClean, GlassPlotextFixed, GlassPlotextMinimal, GlassPlotextTextual, GlassPlotextSimple, GlassPlotextFinal, GlassFigletWidget, GlassAnsiPanel]:
        """Create a widget instance from definition"""
        widget_type = definition.get('type', 'widget')

        # Common parameters
        params = {
            'x': definition.get('x', 0),
            'y': definition.get('y', 0),
            'width': definition.get('width', 30),
            'height': definition.get('height', 10),
            'sticky_x': definition.get('sticky_x'),
            'sticky_y': definition.get('sticky_y'),
            'z_index': definition.get('z_index', 0),
            'overlay_color': definition.get('overlay_color', 'blue'),
            'blend_opacity': definition.get('blend_opacity', 0.5),
            'darken_factor': definition.get('darken_factor', 0.0),
            'blur': definition.get('blur', 2)  # Default blur of 2
        }

        # Add ID if provided
        if 'id' in definition:
            params['id'] = definition['id']

        # Create appropriate widget type
        if widget_type == 'text_editor':
            # Glass text editor
            widget = GlassTextEditor(
                initial_text=definition.get('initial_text', ''),
                title=definition.get('title', ''),
                border=definition.get('border', False),
                padding=definition.get('padding', 2),
                **params
            )
        elif widget_type == 'terminal_editor':
            # Terminal editor widget (nano/vim)
            on_save = definition.get('on_save')
            widget = GlassTerminalEditor(
                editor=definition.get('editor', 'nano'),
                file_path=definition.get('file_path'),
                on_save=on_save,
                title=definition.get('title', 'SQL Editor'),
                border=definition.get('border', True),
                show_title=definition.get('show_title', True),
                padding=definition.get('padding', 0),
                **params
            )
        elif widget_type == 'nano_editor':
            # Nano-style editor (built-in)
            on_save = definition.get('on_save')
            widget = GlassNanoEditor(
                file_path=definition.get('file_path'),
                on_save=on_save,
                title=definition.get('title', 'SQL Editor - ^O Save | ^X Exit'),
                padding=definition.get('padding', 0),
                **params
            )
        elif widget_type == 'prompt_toolkit_editor':
            # Prompt toolkit editor with syntax highlighting
            on_save = definition.get('on_save')
            initial_text = definition.get('initial_text')
            widget = GlassPromptToolkitEditor(
                file_path=definition.get('file_path'),
                initial_text=initial_text,
                on_save=on_save,
                title=definition.get('title', 'SQL Editor - Ctrl+S Save | Ctrl+X Exit'),
                syntax=definition.get('syntax', 'sql'),
                # border=definition.get('border', False),
                # padding=definition.get('padding', 0),
                **params
            )
        elif widget_type == 'scrollable':
            # Scrollable container
            widget = GlassScrollableContainer(
                content_lines=definition.get('content_lines', []),
                scroll_x=definition.get('scroll_x', False),
                scroll_y=definition.get('scroll_y', True),
                title=definition.get('title', ''),
                border=definition.get('border', True),
                padding=definition.get('padding', 0),
                **params
            )
        elif widget_type == 'native':
            # Native widget container with event callback
            on_change = definition.get('on_change')
            if on_change is None and hasattr(self, '_handle_native_change'):
                # Use default handler if available
                widget_id = definition.get('id')
                def on_change(event_type, value): return self._handle_native_change(widget_id, event_type, value)

            widget = GlassNativeContainer(
                widget_class=definition.get('widget_class', 'Button'),
                widget_props=definition.get('widget_props', {}),
                on_change=on_change,
                title=definition.get('title', ''),
                border=definition.get('border', True),
                padding=definition.get('padding', 0),
                **params
            )
        elif widget_type == 'plot':
            # Textual-plotext wrapper
            widget = GlassPlotContainer(
                plot_data=definition.get('plot_data', {}),
                title=definition.get('title', ''),
                border=definition.get('border', True),
                padding=definition.get('padding', 0),
                **params
            )
        elif widget_type == 'plot_direct':
            # Direct plotext rendering (no colors)
            widget = GlassPlotextDirect(
                plot_data=definition.get('plot_data', {}),
                title=definition.get('title', ''),
                border=definition.get('border', True),
                padding=definition.get('padding', 0),
                **params
            )
        elif widget_type == 'plot_direct_color':
            # Direct plotext rendering with ANSI color support (final version)
            widget = GlassPlotextFinal(
                plot_data=definition.get('plot_data', {}),
                title=definition.get('title', ''),
                border=definition.get('border', True),
                padding=definition.get('padding', 0),
                **params
            )
        elif widget_type == 'figlet':
            # Glass figlet widget
            widget = GlassFigletWidget(
                text=definition.get('text', ''),
                font=definition.get('font', 'slant'),
                justify=definition.get('justify', 'auto'),
                width_mode=definition.get('width_mode', 'default'),
                padding=definition.get('padding', 0),
                **params
            )
        elif widget_type == 'ansi_panel':
            # ANSI-aware panel widget
            widget = GlassAnsiPanel(
                content=definition.get('content', ''),
                title=definition.get('title', ''),
                border=definition.get('border', True),
                show_title=definition.get('show_title', True),
                padding=definition.get('padding', 0),
                **params
            )
        elif widget_type == 'rich_dsl':
            # Glass Rich DSL widget
            from .glass_rich_dsl_widget import GlassRichDSLWidget
            widget = GlassRichDSLWidget(
                content=definition.get('content', ''),
                justify=definition.get('justify', 'left'),
                title=definition.get('title', ''),
                border=definition.get('border', False),
                show_title=definition.get('show_title', True),
                padding=definition.get('padding', 0),
                **params
            )
        elif widget_type == 'template':
            # Generic template widget - using fixed version
            from .glass_template_widget_fixed import GlassTemplateWidgetFixed
            widget = GlassTemplateWidgetFixed(
                template_name=definition.get('template', 'text'),
                template_config=definition.get('template_config', {}),
                padding=definition.get('padding', 0),
                **params
            )
        elif widget_type == 'connection_segment':
            # Fixed connection segment (for widget stability)
            from .looking_glass import AbsoluteGlassLineSegment
            # Use content if provided, otherwise use line style
            content = definition.get('content', '')
            if not content:
                line_style = definition.get('line_style', 'solid')
                direction = definition.get('direction', 'horizontal')
                content = self._get_line_char(line_style, direction)

            widget = AbsoluteGlassLineSegment(
                content=content,
                direction=definition.get('direction', 'horizontal'),
                line_style=definition.get('line_style', 'solid'),
                **params
            )
        elif widget_type == 'connection_canvas':
            # Single canvas for entire connection path
            # AbsoluteGlassPanel is already imported at module level
            # Render the path data as content
            path_data = definition.get('_path_data', {})
            grid = path_data.get('grid', [])
            content = '\n'.join(''.join(row) for row in grid)

            widget = AbsoluteGlassPanel(
                content=content,
                title=definition.get('title', ''),
                border=definition.get('border', False),
                padding=definition.get('padding', 0),
                **params
            )
        elif widget_type == 'line_segment':
            # Connection line segment (legacy)
            from .looking_glass import AbsoluteGlassLineSegment
            # Don't pass content - let the widget generate it based on dimensions
            
            widget = AbsoluteGlassLineSegment(
                direction=definition.get('direction', 'horizontal'),
                line_style=definition.get('line_style', 'solid'),
                **params
            )
        elif widget_type == 'smooth_line':
            # Smooth line with half-blocks and proper colors
            try:
                from .glass_smooth_line import AbsoluteGlassSmoothLine
                widget = AbsoluteGlassSmoothLine(
                    direction=definition.get('direction', 'horizontal'),
                    line_style=definition.get('line_style', 'block'),
                    smooth_char=definition.get('char'),
                    arrow_end=definition.get('_arrow_end', False),
                    corner_type=definition.get('_corner_type'),
                    segment_type=definition.get('_segment_type'),
                    **params
                )
            except ImportError:
                # Fallback to regular line segment
                from .looking_glass import AbsoluteGlassLineSegment
                widget = AbsoluteGlassLineSegment(
                    direction=definition.get('direction', 'horizontal'),
                    line_style=definition.get('line_style', 'solid'),
                    **params
                )
        elif widget_type == 'live_data':
            # Live data widget that updates directly to terminal
            widget = LiveDataGlassWidget(**params)
        elif widget_type == 'live_fps':
            # Live FPS counter widget
            widget = LiveFPSCounter(**params)
        elif widget_type == 'connection_canvas':
            # Special canvas for connections
            widget = AbsoluteGlassConnectionCanvas(**params)
        elif widget_type == 'panel':
            widget = AbsoluteGlassPanel(
                title=definition.get('title', ''),
                content=definition.get('content', ''),
                border=definition.get('border', True),
                show_title=definition.get('show_title', True),
                padding=definition.get('padding', 0),
                **params
            )
        else:
            widget = AbsoluteGlassWidget(
                content=definition.get('content', ''),
                padding=definition.get('padding', 0),
                **params
            )

        widget.classes = "blend-widget"

        # Mark connection widgets so they can be excluded from cumulative positioning
        if definition.get('_is_connection'):
            widget._is_connection = True

        # Mark floating widgets (like context menus) to exclude from Y-cascade
        if definition.get('_floating'):
            widget._floating = True

        # Apply title_color and border_color if provided
        if hasattr(widget, '_title_color'):
            title_color = definition.get('title_color')
            if title_color is not None:
                widget._title_color = title_color

        if hasattr(widget, '_border_color'):
            border_color = definition.get('border_color')
            if border_color is not None:
                widget._border_color = border_color

        # Apply CSS merge if provided
        self._apply_css_merge(widget, definition)

        # Patch the render_line method to support CSS
        self._patch_widget_render_for_css(widget)

        return widget

    def _add_widget(self, definition: Dict):
        """Add a new widget to the screen"""
        widget_id = definition.get('id')
        if not widget_id:
            return

        # Create widget
        widget = self._create_widget(definition)
        self._mounted_widgets[widget_id] = widget

        # Ensure widget has proper absolute position attributes
        if hasattr(widget, 'abs_x') and hasattr(widget, 'abs_y'):
            widget.abs_x = definition.get('x', 0)
            widget.abs_y = definition.get('y', 0)

        # Handle auto-focus for widgets
        # Check if widget should auto-focus either by type or can_focus method
        auto_focus = False

        # Legacy: auto-focus editor types
        if definition.get('type') in ['text_editor', 'nano_editor', 'prompt_toolkit_editor', 'terminal_editor']:
            auto_focus = True
        # New way: check if widget declares it wants auto-focus
        elif hasattr(widget, 'auto_focus') and widget.auto_focus:
            auto_focus = True

        if auto_focus:
            # Auto-focus using centralized method
            self.set_widget_focus(widget_id)

        # Apply selection style if this widget is selected
        self._apply_selection_style(widget, widget_id)

        # Apply hover style if this widget is hovered
        if widget_id == self._hovered_widget_id:
            self._apply_hover_style(widget, widget_id, True)

        # Mount to screen
        self.mount(widget)

        # Track in absolute widgets list
        if not hasattr(self, '_absolute_widgets'):
            self._absolute_widgets = []
        if not hasattr(self, '_compose_order'):
            self._compose_order = []

        # Mark that positions and connections need updating
        self._positions_dirty = True
        self._connections_dirty = True

        self._absolute_widgets.append(widget)

        # For floating widgets, ensure they're always at the end of compose order
        if hasattr(widget, '_floating') and widget._floating:
            # Don't add to compose_order yet, we'll add them at the end
            if not hasattr(self, '_floating_widgets'):
                self._floating_widgets = []
            self._floating_widgets.append(widget)
        else:
            self._compose_order.append(widget)
            # Sort widgets by Y position, but context menu ALWAYS goes last

            def sort_key(w):
                if hasattr(w, 'id') and w.id == 'context_menu':
                    # Context menu always sorts to the very end
                    return (999999, 999999)
                else:
                    return (getattr(w, 'abs_y', 0), getattr(w, 'abs_x', 0))

            self._compose_order.sort(key=sort_key)

        # Always ensure floating widgets are at the end
        if hasattr(self, '_floating_widgets'):
            # Remove any floating widgets that might be in compose_order
            self._compose_order = [w for w in self._compose_order
                                   if not (hasattr(w, '_floating') and w._floating)]
            # Add all floating widgets at the end
            self._compose_order.extend(self._floating_widgets)

        # Log compose order for debugging
        self.log(f"Compose order after add: {[getattr(w, 'id', 'unknown') for w in self._compose_order]}")

        # Share image data if available
        if hasattr(self, '_image_array') and self._image_array is not None:
            if hasattr(widget, 'set_image_data'):
                widget.set_image_data(self._image_array)

        self._positions_dirty = True

        # Force immediate position update for this widget
        self._update_widget_position_directly(widget, definition)

        # Call update all positions to fix Textual's offset issues
        if hasattr(self, '_update_all_positions'):
            self._update_all_positions()

        # Log for debugging template widgets
        if definition.get('type') == 'template':
            self.log(f"Added template widget {widget_id} at position ({definition.get('x')}, {definition.get('y')}) with size ({definition.get('width')}, {definition.get('height')})")

    def _update_widget_position_directly(self, widget, definition: Dict):
        """Update a widget's position directly, bypassing Textual's layout system"""
        # Just mark positions as dirty - we'll override the update method
        self._positions_dirty = True

    def _remove_widget(self, widget_id: str):
        """Remove a widget from the screen"""
        widget = self._mounted_widgets.get(widget_id)
        if not widget:
            return

        # Remove from tracking lists
        if hasattr(self, '_absolute_widgets') and widget in self._absolute_widgets:
            self._absolute_widgets.remove(widget)
        if hasattr(self, '_compose_order') and widget in self._compose_order:
            self._compose_order.remove(widget)
        # Also remove from floating widgets list if it's there
        if hasattr(self, '_floating_widgets') and widget in self._floating_widgets:
            self._floating_widgets.remove(widget)

        # Remove from DOM
        widget.remove()

        # Remove from mounted widgets
        del self._mounted_widgets[widget_id]

        self._positions_dirty = True

    def _update_widget(self, widget_id: str, definition: Dict):
        """Update an existing widget with new properties"""
        widget = self._mounted_widgets.get(widget_id)
        if not widget:
            return

        position_changed = False

        # Update position
        if hasattr(widget, 'abs_x') and hasattr(widget, 'abs_y'):
            new_x = definition.get('x')
            new_y = definition.get('y')

            if new_x is not None and widget.abs_x != new_x:
                widget.abs_x = new_x
                position_changed = True
            if new_y is not None and widget.abs_y != new_y:
                widget.abs_y = new_y
                position_changed = True

        # Update dimensions
        if hasattr(widget, 'abs_width') and hasattr(widget, 'abs_height'):
            new_width = definition.get('width')
            new_height = definition.get('height')

            if new_width is not None:
                # Convert to string if needed (to support percentages)
                widget.abs_width = str(new_width)
                position_changed = True  # Size changes need position recalc too
            if new_height is not None:
                widget.abs_height = str(new_height)
                position_changed = True

        # Handle scrollable container updates
        if isinstance(widget, GlassScrollableContainer):
            # Update content lines
            new_content_lines = definition.get('content_lines')
            if new_content_lines is not None:
                widget.update_content(new_content_lines)
        # Handle native widget updates
        elif isinstance(widget, GlassNativeContainer):
            # Update native widget content if provided
            new_content = definition.get('content')
            if new_content is not None:
                widget.update_content(new_content)

            # Update native widget properties - but be careful with Input and TextArea widgets
            new_props = definition.get('widget_props')
            if new_props:
                # For Input and TextArea widgets, don't update text/value props to avoid disrupting typing
                native_widget = widget.get_native_widget()
                if native_widget and native_widget.__class__.__name__ in ['Input', 'TextArea']:
                    # Filter out 'value' and 'text' from props to avoid feedback loop
                    filtered_props = {k: v for k, v in new_props.items() if k not in ['value', 'text']}
                    if filtered_props:
                        widget.update_props(filtered_props)
                else:
                    widget.update_props(new_props)
        # Handle plot updates
        elif isinstance(widget, (GlassPlotextDirect, GlassPlotextFinal)):
            # Update plot data
            new_plot_data = definition.get('plot_data')
            if new_plot_data:
                widget.update_plot(new_plot_data)
        # Handle figlet updates
        elif isinstance(widget, GlassFigletWidget):
            # Update text
            new_text = definition.get('text')
            if new_text is not None:
                widget.update_text(new_text)
            # Update font
            new_font = definition.get('font')
            if new_font is not None:
                widget.update_font(new_font)
        # Handle template widget updates
        elif hasattr(widget, 'template_name'):  # Duck typing for GlassTemplateWidget
            # Update template config
            new_template_config = definition.get('template_config')
            if new_template_config is not None:
                widget.template_config = new_template_config
            # Update template name if changed
            new_template_name = definition.get('template')
            if new_template_name is not None and widget.template_name != new_template_name:
                widget.template_name = new_template_name
            # Force update to ensure template re-renders
            if hasattr(widget, 'force_update'):
                widget.force_update()
                # Fixed widget updates automatically on property change
        # Handle prompt toolkit editor updates
        elif isinstance(widget, GlassPromptToolkitEditor):
            # Update content if initial_text has changed
            new_initial_text = definition.get('initial_text')
            if new_initial_text is not None and hasattr(widget, 'update_content'):
                widget.update_content(new_initial_text)
            # Update title if changed
            new_title = definition.get('title')
            if new_title is not None and hasattr(widget, 'title'):
                widget.title = new_title
        else:
            # Update content for regular widgets
            new_content = definition.get('content')
            if new_content is not None:
                # Let the widget handle list vs string conversion
                widget.content = new_content

        # Update title if panel
        if hasattr(widget, 'title'):
            new_title = definition.get('title')
            if new_title is not None:
                widget.title = new_title

        # Update padding if supported
        if hasattr(widget, 'padding'):
            new_padding = definition.get('padding')
            if new_padding is not None:
                widget.padding = new_padding

        # Update visual properties
        if hasattr(widget, 'overlay_color'):
            new_color = definition.get('overlay_color')
            if new_color and widget.overlay_color != new_color:
                widget.overlay_color = new_color

        if hasattr(widget, 'blend_opacity'):
            new_opacity = definition.get('blend_opacity')
            if new_opacity is not None and widget.blend_opacity != new_opacity:
                widget.blend_opacity = new_opacity

        # Apply title_color and border_color if provided
        if hasattr(widget, '_title_color'):
            new_title_color = definition.get('title_color')
            if new_title_color is not None:
                widget._title_color = new_title_color

        if hasattr(widget, '_border_color'):
            new_border_color = definition.get('border_color')
            if new_border_color is not None:
                widget._border_color = new_border_color

        # Apply CSS merge if provided - check if CSS has changed
        old_css = getattr(widget, '_css_styles', {}).copy() if hasattr(widget, '_css_styles') else {}
        old_border_css = getattr(widget, '_border_css', {}).copy() if hasattr(widget, '_border_css') else {}
        old_title_css = getattr(widget, '_title_css', {}).copy() if hasattr(widget, '_title_css') else {}

        self._apply_css_merge(widget, definition)

        # Check if any CSS has changed
        new_css = getattr(widget, '_css_styles', {})
        new_border_css = getattr(widget, '_border_css', {})
        new_title_css = getattr(widget, '_title_css', {})

        css_changed = (old_css != new_css or
                       old_border_css != new_border_css or
                       old_title_css != new_title_css)

        if css_changed:
            # CSS changed - the patched render method will automatically
            # pick up the new values since it reads from widget._css_styles etc.
            widget_id = widget.id if hasattr(widget, 'id') else 'unknown'
            self.log(f"CSS changed for widget {widget_id}: {new_css}")

        # Apply selection style
        self._apply_selection_style(widget, widget_id)

        # Apply hover style
        if widget_id == self._hovered_widget_id:
            self._apply_hover_style(widget, widget_id, True)

        # Track what actually changed to avoid unnecessary refreshes
        needs_refresh = False
        needs_layout = False

        # Content changes always need refresh (for widgets that have content)
        if hasattr(widget, 'content'):
            new_content_value = definition.get('content')
            if new_content_value is not None and str(widget.content) != str(new_content_value):
                needs_refresh = True

        # Title changes need refresh
        if hasattr(widget, 'title') and new_title is not None and widget.title != new_title:
            needs_refresh = True

        # Visual property changes need refresh
        if (hasattr(widget, 'overlay_color') and new_color and widget.overlay_color != new_color) or \
           (hasattr(widget, 'blend_opacity') and new_opacity is not None and widget.blend_opacity != new_opacity) or \
           (hasattr(widget, 'darken_factor') and definition.get('darken_factor') is not None and widget.darken_factor != definition.get('darken_factor')):
            needs_refresh = True

        # CSS changes need refresh
        if css_changed:
            needs_refresh = True

        # Position/size changes need layout update
        if position_changed:
            needs_layout = True
            needs_refresh = True  # Position changes also need visual refresh

        # Selection/hover changes need refresh
        if widget_id == self._selected_widget_id or widget_id == self._hovered_widget_id:
            needs_refresh = True

        # Only refresh if something actually changed
        if needs_refresh:
            widget.refresh(layout=needs_layout)

        # Mark positions dirty if changed
        if position_changed:
            self._positions_dirty = True
            self._connections_dirty = True
            # Immediately update position for this specific widget
            if hasattr(self, '_update_single_widget_position'):
                self._update_single_widget_position(widget)

    def _update_single_widget_position(self, widget):
        """Update position for a single widget without full reconciliation"""
        if not hasattr(widget, 'abs_x') or not hasattr(widget, 'abs_y'):
            return

        # Calculate the widget's absolute position
        if hasattr(self, 'size') and self.size:
            container_width = self.size.width
            container_height = self.size.height
        else:
            container_width = 100  # fallback
            container_height = 40   # fallback

        # Use the widget's calculate_position method if available
        if hasattr(widget, 'calculate_position'):
            x, y, width, height = widget.calculate_position(container_width, container_height)

            # Apply the position using Textual's styles
            if hasattr(widget, 'styles'):
                widget.styles.offset = (x, y)
                widget.styles.width = width
                widget.styles.height = height

    # ===========================================================================
    # FAST WIDGET OPERATIONS
    # ===========================================================================

    def move_widget_fast(self, widget_id: str, direction: str,
                         speed: int = 1, update_state_callback: Optional[Callable] = None):
        """
        Move a widget without remounting for smooth animation.

        Args:
            widget_id: ID of widget to move
            direction: 'up', 'down', 'left', 'right'
            speed: Number of units to move
            update_state_callback: Optional callback to update state
        """
        widget = self._mounted_widgets.get(widget_id)
        if not widget or not hasattr(widget, 'abs_x'):
            return

        # Get current position
        current_x = widget.abs_x
        current_y = widget.abs_y

        # Calculate new position
        new_x = current_x
        new_y = current_y

        if direction == 'up':
            new_y = max(0, current_y - speed)
        elif direction == 'down':
            new_y = current_y + speed
        elif direction == 'left':
            new_x = max(0, current_x - speed)
        elif direction == 'right':
            new_x = current_x + speed

        # Update widget position directly
        widget.abs_x = new_x
        widget.abs_y = new_y

        # Update positions
        if hasattr(self, '_update_all_positions'):
            self._update_all_positions()

        # Call state update callback if provided
        if update_state_callback:
            update_state_callback(new_x, new_y)

        # Refresh widget
        widget.refresh()

    # ===========================================================================
    # BACKGROUND MANAGEMENT
    # ===========================================================================

    def _check_background_change(self):
        """Check if background should change based on state"""
        # Override this to implement custom background logic
        # Example: check self.state.get('selected_background')
        pass

    def load_background_from_state(self, state_key: str = 'selected_background'):
        """
        Load background based on state value.

        Args:
            state_key: Key in state containing background name
        """
        bg_name = self.state.get(state_key)
        if bg_name and bg_name != self._last_background:
            if bg_name == 'default':
                self.load_background(None)
            else:
                self.load_background(bg_name)
            self._last_background = bg_name

    def set_background(self, image_path: str = None, darken: float = None):
        """
        Reactively change the background image and/or darkening.

        This is a convenience method that dispatches the proper action.

        Args:
            image_path: Path to background image (None for default pattern)
            darken: Darkening factor (0.0-1.0)

        Example:
            # In your app:
            self.set_background('sunset.png', darken=0.3)
            self.set_background(darken=0.5)  # Just change darkening
        """
        payload = {}
        if image_path is not None:
            payload['path'] = image_path
        if darken is not None:
            payload['darken'] = darken

        if payload:
            self.dispatch(Action('__SET_BACKGROUND__', payload))

    # ===========================================================================
    # PERFORMANCE TRACKING
    # ===========================================================================

    def _track_frame_time(self):
        """Track frame rendering time"""
        current_time = time.time()
        # Skip the first frame
        if self._render_count > 0:
            frame_time = current_time - self._last_render_time
            # Only track reasonable frame times (ignore very long pauses)
            if frame_time < 1.0:  # Less than 1 second
                self._frame_times.append(frame_time)
                # Debug: Store in state
                self.state['_debug_frame_tracked'] = True
                self.state['_debug_frame_time'] = frame_time
                self.state['_debug_frame_count'] = len(self._frame_times)
        self._last_render_time = current_time
        self._render_count += 1
        self.state['_debug_render_count'] = self._render_count

    def _update_performance_stats(self):
        """Update performance statistics in state"""
        # Debug: Mark that we were called
        self.state['_debug_perf_stats_called'] = True

        if not self._frame_times:
            self.state['_debug_perf_stats_empty'] = True
            return

        # Calculate statistics
        avg_frame_time = sum(self._frame_times) / len(self._frame_times)
        fps = 1.0 / avg_frame_time if avg_frame_time > 0 else 0
        frame_time_ms = avg_frame_time * 1000

        # Debug: Store calculated values
        self.state['_debug_calc_fps'] = fps
        self.state['_debug_calc_frame_time'] = frame_time_ms

        # Only update if performance stats are being displayed
        if self._should_render_performance():
            # Dispatch internal action to update performance stats
            # This maintains proper state immutability
            self.dispatch(Action('__UPDATE_PERFORMANCE__', {
                'fps': fps,
                'frame_time': frame_time_ms
            }))

    def _should_render_performance(self) -> bool:
        """
        Override to control when performance updates trigger re-render.

        Returns:
            True if performance updates should trigger render
        """
        return True

    def get_performance_stats(self) -> Dict[str, float]:
        """
        Get current performance statistics.

        Returns:
            Dict with 'fps' and 'frame_time' keys
        """
        if not self._frame_times:
            return {'fps': 0.0, 'frame_time': 0.0}

        avg_frame_time = sum(self._frame_times) / len(self._frame_times)
        return {
            'fps': 1.0 / avg_frame_time if avg_frame_time > 0 else 0,
            'frame_time': avg_frame_time * 1000
        }

    # ===========================================================================
    # CSS MERGE FUNCTIONALITY
    # ===========================================================================

    def _apply_css_merge(self, widget: Any, definition: Dict):
        """
        Apply CSS styles from the css_merge dictionary to a widget.

        Since glass widgets use custom rendering, we store CSS properties
        directly on the widget for use in render_line methods.

        Args:
            widget: The widget to apply styles to
            definition: Widget definition that may contain css_merge
        """
        css_merge = definition.get('css_merge')
        if not css_merge or not isinstance(css_merge, dict):
            # Clear any existing CSS if no css_merge provided
            if hasattr(widget, '_css_styles'):
                widget._css_styles = {}
            return

        # Store CSS styles directly on the widget
        widget._css_styles = css_merge.copy()

        # Parse specific properties for easier access during rendering
        widget._text_color = css_merge.get('color', 'white')
        widget._text_style = css_merge.get('text_style', '')
        widget._text_align = css_merge.get('text_align', 'left')

        # Debug log (without modifying widget content)
        if css_merge:
            widget_id = widget.id if hasattr(widget, 'id') else 'unknown'
            self.log(f"Applied CSS to widget {widget_id}: color={widget._text_color}, bold={getattr(widget, '_text_bold', False)}")

        # Parse text style flags
        text_style = widget._text_style.lower() if widget._text_style else ''
        widget._text_bold = 'bold' in text_style
        widget._text_italic = 'italic' in text_style
        widget._text_underline = 'underline' in text_style
        widget._text_reverse = 'reverse' in text_style
        widget._text_strike = 'strike' in text_style

        # Border styles (for panels)
        widget._border_style = css_merge.get('border', '')
        widget._border_color = None
        if widget._border_style:
            # Parse border: "style color" format
            parts = widget._border_style.split()
            if len(parts) > 1:
                widget._border_color = parts[1]
                widget._border_style = parts[0]

        # Apply border CSS merge if it's a panel
        border_css_merge = definition.get('border_css_merge')
        if border_css_merge and hasattr(widget, '_border_css'):
            widget._border_css = border_css_merge.copy()
            self.log(f"Applied border CSS to widget {widget_id}: {border_css_merge}")

        # Apply title CSS merge if it's a panel
        title_css_merge = definition.get('title_css_merge')
        if title_css_merge and hasattr(widget, '_title_css'):
            widget._title_css = title_css_merge.copy()
            self.log(f"Applied title CSS to widget {widget_id}: {title_css_merge}")

    # ===========================================================================
    # INTERACTIVE FEATURES
    # ===========================================================================

    def on_mouse_down(self, event: MouseDown):
        """Handle mouse down for drag start and right-click context menu"""
        # Debug log to see what button is pressed
        self.log(f"Mouse down: button={event.button}, shift={event.shift}, ctrl={event.ctrl}, meta={event.meta}")

        # Check for right-click first
        # Standard mouse buttons: 1=left, 2=middle, 3=right
        # BUT some systems/terminals report differently
        # Try both button 2 and 3 for right-click (terminal-dependent)
        if event.button in (2, 3):  # Right or middle mouse button
            self._handle_right_click(event)
            # Set a flag to ignore the next click event
            self._ignore_next_click = True
            return

        # Get the widget that was clicked
        clicked_widget = event.widget
        clicked_widget_id = None

        # Find which of our mounted widgets was clicked
        if clicked_widget:
            for widget_id, widget in self._mounted_widgets.items():
                if widget == clicked_widget:
                    clicked_widget_id = widget_id
                    break

            # If not found directly, check parents
            if not clicked_widget_id:
                parent = clicked_widget.parent
                while parent and not clicked_widget_id:
                    for widget_id, widget in self._mounted_widgets.items():
                        if widget == parent:
                            clicked_widget_id = widget_id
                            break
                    parent = parent.parent if hasattr(parent, 'parent') else None

        # Skip background and system widgets
        if clicked_widget_id in ['background', 'connection_canvas', None]:
            return

        # Check if we clicked on a panel's title area
        widget = self._mounted_widgets.get(clicked_widget_id)
        if widget and hasattr(widget, 'border') and widget.border and hasattr(widget, 'title'):
            # The event coordinates should be relative to the widget
            local_y = event.y

            self.debug_log(f"MouseDown on {clicked_widget_id}: y={local_y}, title='{widget.title}'")

            if local_y == 0 and widget.title:  # Title is on the first row
                # Start dragging with mouse capture
                self.capture_mouse()
                self._dragging_widget_id = clicked_widget_id
                self._drag_start_mouse_x = event.screen_x
                self._drag_start_mouse_y = event.screen_y

                # Get current widget position
                widget_def = self._get_widget_definition(clicked_widget_id)
                if widget_def:
                    self._drag_start_widget_x = widget_def.get('x', 0)
                    self._drag_start_widget_y = widget_def.get('y', 0)
                else:
                    self._drag_start_widget_x = getattr(widget, 'abs_x', 0)
                    self._drag_start_widget_y = getattr(widget, 'abs_y', 0)

                # Store in state for debugging
                self.state['_dragging'] = {
                    'widget_id': clicked_widget_id,
                    'start_mouse': (self._drag_start_mouse_x, self._drag_start_mouse_y),
                    'start_widget': (self._drag_start_widget_x, self._drag_start_widget_y)
                }

                self.debug_log(f"DRAG START: {clicked_widget_id} from ({self._drag_start_widget_x}, {self._drag_start_widget_y})")
                self.debug_log("Mouse captured!")
                self.render_ui()

    def on_mouse_up(self, event):
        """Handle mouse up to stop dragging"""
        # If we just right-clicked, ignore this mouse up
        if hasattr(self, '_ignore_next_click') and self._ignore_next_click:
            # Don't clear the flag here, we need it for on_click too
            return

        if self._dragging_widget_id:
            self.debug_log(f"DRAG STOP: {self._dragging_widget_id}")

            # Release mouse capture
            self.release_mouse()

            # Clear dragging state
            self._dragging_widget_id = None
            self._drag_start_mouse_x = 0
            self._drag_start_mouse_y = 0
            self._drag_start_widget_x = 0
            self._drag_start_widget_y = 0

            # Clear state debug info
            if '_dragging' in self.state:
                del self.state['_dragging']

            # Trigger a final render to ensure position is correct
            self.render_ui()

    def on_click(self, event):
        """Handle mouse clicks for widget selection and double-click drag"""
        # Don't ignore clicks when context menu is visible - we need them to select items
        if not self._context_menu_state.get('visible', False):
            # Check if we should ignore this click (from right-click)
            if hasattr(self, '_ignore_next_click') and self._ignore_next_click:
                self._ignore_next_click = False
                return

        # Check if we clicked on the context menu
        if self._context_menu_state['visible']:
            clicked_widget = event.widget
            clicked_widget_id = None

            # Find which widget was clicked
            if clicked_widget:
                for widget_id, widget in self._mounted_widgets.items():
                    if widget == clicked_widget:
                        clicked_widget_id = widget_id
                        break

                # If not found directly, it might be a child of a mounted widget
                if not clicked_widget_id:
                    parent = clicked_widget.parent
                    while parent:
                        for widget_id, widget in self._mounted_widgets.items():
                            if widget == parent:
                                clicked_widget_id = widget_id
                                break
                        if clicked_widget_id:
                            break
                        parent = parent.parent if hasattr(parent, 'parent') else None

            # Check if we clicked within the context menu bounds
            if clicked_widget_id == 'context_menu' or self._is_click_in_context_menu(event):
                # Calculate which item was clicked based on Y position
                menu = self._context_menu_state

                # Get the click position relative to the menu
                menu_x = menu['x']
                menu_y = menu['y']

                # Calculate relative Y position
                click_y = event.screen_y if hasattr(event, 'screen_y') else event.y
                relative_y = click_y - menu_y

                # Account for border and padding
                item_index = relative_y - 1  # Subtract 1 for top border

                # Find the actual item (skip dividers)
                actual_index = 0
                for i, item in enumerate(menu['items']):
                    if item_index == actual_index:
                        # Check if it's a divider (string or dict with divider=True)
                        is_divider = (isinstance(item, str) and item == 'divider') or (isinstance(item, dict) and item.get('divider'))
                        if not is_divider:
                            self._handle_context_menu_click(i)
                        break
                    # Count all items including dividers for positioning
                    actual_index += 1

                return
            else:
                # Clicked outside menu, hide it
                self._hide_context_menu()
                self.render_ui()
                return

        # Debug current state
        current_time = time.time()
        time_since_last = current_time - self._last_click_time
        self._last_click_time = current_time
        self._click_count += 1

        self.debug_log(f"\n=== CLICK EVENT #{self._click_count} ===")
        self.debug_log(f"Time since last click: {time_since_last:.3f}s")
        self.debug_log(f"Click position: ({getattr(event, 'x', 'N/A')}, {getattr(event, 'y', 'N/A')})")
        self.debug_log(f"Screen position: ({getattr(event, 'screen_x', 'N/A')}, {getattr(event, 'screen_y', 'N/A')})")
        self.debug_log(f"Event widget: {event.widget}")
        self.debug_log(f"Event widget ID: {getattr(event.widget, 'id', 'NO_ID')}")
        self.debug_log(f"Current attached: {self._attached_widget_id}")
        self.debug_log(f"Current resize: {self._resize_widget_id}")
        self.debug_log(f"Resize mode: {getattr(self, '_resize_mode', False)}")
        self.debug_log(f"Reconciliation paused: {self._reconciliation_paused}")
        self.debug_log(f"Event chain: {getattr(event, 'chain', 'N/A')}")
        self.debug_log(f"Mounted widgets: {list(self._mounted_widgets.keys())}")
        self.debug_log(f"Virtual DOM keys: {list(self._virtual_dom.keys()) if hasattr(self, '_virtual_dom') else 'N/A'}")
        self.debug_log(f"Widget overrides: {self._widget_overrides}")

        # Safety check: if we're in the middle of processing another click, bail out
        if hasattr(self, '_processing_click') and self._processing_click:
            self.debug_log("WARNING: Already processing a click, ignoring this one")
            return

        self._processing_click = True
        try:
            self._handle_click_internal(event)
        finally:
            self._processing_click = False

    def _handle_click_internal(self, event):
        """Internal click handler with proper cleanup"""
        clicked_widget = event.widget
        clicked_widget_id = None

        # Check if the clicked widget is one of our mounted widgets
        if clicked_widget:
            # First check if it's directly in our mounted widgets
            for widget_id, widget in self._mounted_widgets.items():
                if widget == clicked_widget:
                    clicked_widget_id = widget_id
                    break

            # If not found, it might be a child widget, so traverse up
            if not clicked_widget_id:
                parent = clicked_widget.parent
                while parent and not clicked_widget_id:
                    for widget_id, widget in self._mounted_widgets.items():
                        if widget == parent:
                            clicked_widget_id = widget_id
                            break
                    parent = parent.parent if hasattr(parent, 'parent') else None

        # Skip background and system widgets
        if clicked_widget_id in ['background', 'connection_canvas']:
            clicked_widget_id = None

        if clicked_widget_id:
            widget_def = self._get_widget_definition(clicked_widget_id)

            # Check for double-click to enable drag mode
            if hasattr(event, 'chain') and event.chain == 2:
                # Double-click - check if widget is draggable
                if widget_def and widget_def.get('draggable', True):
                    # Check if click is in lower-right corner (4x4 char area)
                    widget_x = widget_def.get('x', 0)
                    widget_y = widget_def.get('y', 0)
                    widget_width = widget_def.get('width', 20)
                    widget_height = widget_def.get('height', 5)

                    # Calculate relative click position within widget
                    click_x = event.screen_x - widget_x if hasattr(event, 'screen_x') else 0
                    click_y = event.screen_y - widget_y if hasattr(event, 'screen_y') else 0

                    # Check if click is in lower-right corner (4x4 area)
                    in_resize_area = (click_x >= widget_width - 4 and
                                      click_y >= widget_height - 4)

                    if in_resize_area:
                        # Enable resize mode
                        if self._resize_widget_id == clicked_widget_id:
                            # Detach if already resizing
                            self.debug_log(f"Stopping resize of {clicked_widget_id}")
                            self._resize_mode = False
                            self._resize_widget_id = None
                            self.state['_resize_widget'] = None
                            self._reconciliation_paused = False
                            # Clear cache immediately
                            if hasattr(self, '_cached_widget_definitions'):
                                delattr(self, '_cached_widget_definitions')
                            self.debug_log("Cleared resize state")
                        else:
                            # Start resize mode
                            self.debug_log(f"Starting resize of {clicked_widget_id}")
                            self._resize_mode = True
                            self._resize_widget_id = clicked_widget_id
                            self.state['_resize_widget'] = clicked_widget_id
                            self._resize_original_width = widget_width
                            self._resize_original_height = widget_height
                            self._resize_start_mouse_x = event.screen_x if hasattr(event, 'screen_x') else 0
                            self._resize_start_mouse_y = event.screen_y if hasattr(event, 'screen_y') else 0
                            # Pause reconciliation for performance
                            self._reconciliation_paused = True
                            self.debug_log("Paused reconciliation for resize")
                    else:
                        # Normal move mode
                        if self._attached_widget_id == clicked_widget_id:
                            # Detach if already attached
                            self.debug_log(f"Detaching widget {clicked_widget_id}")
                            self._attached_widget_id = None
                            self.state['_attached_widget'] = None
                            self._reconciliation_paused = False
                            # Clear cache immediately
                            if hasattr(self, '_cached_widget_definitions'):
                                delattr(self, '_cached_widget_definitions')
                            self.debug_log("Cleared drag state")
                        else:
                            # Attach widget
                            self.debug_log(f"Attaching widget {clicked_widget_id}")
                            self.debug_log(f"Current state - attached: {self._attached_widget_id}, resize: {self._resize_widget_id}, paused: {self._reconciliation_paused}")
                            self.debug_log(f"Widget def: x={widget_x}, y={widget_y}, w={widget_width}, h={widget_height}")

                            # Clear any stale cache first
                            if hasattr(self, '_cached_widget_definitions'):
                                self.debug_log("Clearing stale cache before new attach")
                                delattr(self, '_cached_widget_definitions')

                            self._attached_widget_id = clicked_widget_id
                            self.state['_attached_widget'] = clicked_widget_id

                            # Calculate offset from mouse to widget position
                            if hasattr(event, 'screen_x'):
                                self._attach_offset_x = event.screen_x - widget_x
                                self._attach_offset_y = event.screen_y - widget_y
                            else:
                                self._attach_offset_x = 0
                                self._attach_offset_y = 0
                            # Pause reconciliation for performance
                            self._reconciliation_paused = True
                            self.debug_log("Paused reconciliation for drag")

                    self.render_ui()
                    return
            else:
                # Single click
                if self._attached_widget_id:
                    # Drop the attached widget
                    dropping_widget_id = self._attached_widget_id  # Store before clearing
                    self.debug_log(f"Dropping widget {dropping_widget_id}")
                    self.debug_log(f"Drop state - attached: {self._attached_widget_id}, resize: {self._resize_widget_id}, paused: {self._reconciliation_paused}")
                    self.debug_log(f"Mouse position: ({self._last_mouse_x}, {self._last_mouse_y})")
                    self.debug_log(f"Attach offset: ({self._attach_offset_x}, {self._attach_offset_y})")

                    # Update the widget's position in definitions
                    if dropping_widget_id in self._virtual_dom:
                        new_x = self._last_mouse_x - self._attach_offset_x
                        new_y = self._last_mouse_y - self._attach_offset_y

                        # Ensure within bounds
                        if hasattr(self, 'size') and self.size:
                            new_x = max(0, min(new_x, self.size.width - 10))
                            new_y = max(0, min(new_y, self.size.height - 5))

                        # Update position in virtual DOM
                        self._virtual_dom[self._attached_widget_id]['x'] = new_x
                        self._virtual_dom[self._attached_widget_id]['y'] = new_y

                        self.debug_log(f"Dropped at ({new_x}, {new_y})")

                        # Store position override internally
                        if dropping_widget_id not in self._widget_overrides:
                            self._widget_overrides[dropping_widget_id] = {}
                        self._widget_overrides[dropping_widget_id]['x'] = new_x
                        self._widget_overrides[dropping_widget_id]['y'] = new_y

                        # Dispatch an action to update the position in app state if handler exists
                        if hasattr(self, 'on_widget_drop'):
                            self.on_widget_drop(dropping_widget_id, new_x, new_y)

                    # Clear ALL drag-related state
                    self._attached_widget_id = None
                    self.state['_attached_widget'] = None
                    self._reconciliation_paused = False  # Clear this immediately
                    self.debug_log("Cleared all drag state")
                    self.debug_log(f"Final state check - attached: {self._attached_widget_id}, resize: {self._resize_widget_id}, paused: {self._reconciliation_paused}")

                    # Clear cache immediately on drop
                    if hasattr(self, '_cached_widget_definitions'):
                        delattr(self, '_cached_widget_definitions')

                    # Cancel any pending timer
                    if self._resume_reconciliation_timer:
                        self._resume_reconciliation_timer.stop()
                        self._resume_reconciliation_timer = None

                    # Force immediate render to show final position
                    self.render_ui()
                    return

                elif self._resize_mode and self._resize_widget_id:
                    # Finish resize
                    resizing_widget_id = self._resize_widget_id  # Store before clearing
                    self.debug_log(f"Finishing resize of {resizing_widget_id}")
                    self.debug_log(f"Resize state - attached: {self._attached_widget_id}, resize: {self._resize_widget_id}, paused: {self._reconciliation_paused}")

                    if resizing_widget_id in self._virtual_dom:
                        # Calculate new size based on mouse movement
                        delta_x = self._last_mouse_x - self._resize_start_mouse_x
                        delta_y = self._last_mouse_y - self._resize_start_mouse_y

                        new_width = max(10, self._resize_original_width + delta_x)
                        new_height = max(3, self._resize_original_height + delta_y)

                        # Update size in virtual DOM
                        self._virtual_dom[self._resize_widget_id]['width'] = new_width
                        self._virtual_dom[self._resize_widget_id]['height'] = new_height

                        self.debug_log(f"Resized to {new_width}x{new_height}")

                        # Store size override internally
                        if self._resize_widget_id not in self._widget_overrides:
                            self._widget_overrides[self._resize_widget_id] = {}
                        self._widget_overrides[self._resize_widget_id]['width'] = new_width
                        self._widget_overrides[self._resize_widget_id]['height'] = new_height

                        # Also get position for the handler
                        widget_x = self._virtual_dom[self._resize_widget_id].get('x', 0)
                        widget_y = self._virtual_dom[self._resize_widget_id].get('y', 0)

                        # Call handler if exists
                        if hasattr(self, 'on_widget_move_resize'):
                            self.on_widget_move_resize(self._resize_widget_id, widget_x, widget_y, new_width, new_height)

                    # Clear ALL resize-related state
                    self._resize_mode = False
                    self._resize_widget_id = None
                    self.state['_resize_widget'] = None
                    self._reconciliation_paused = False  # Clear this immediately
                    self.debug_log("Cleared all resize state")
                    self.debug_log(f"Final state check - attached: {self._attached_widget_id}, resize: {self._resize_widget_id}, paused: {self._reconciliation_paused}")

                    # Clear cache immediately on drop
                    if hasattr(self, '_cached_widget_definitions'):
                        delattr(self, '_cached_widget_definitions')

                    # Cancel any pending timer
                    if self._resume_reconciliation_timer:
                        self._resume_reconciliation_timer.stop()
                        self._resume_reconciliation_timer = None

                    # Force immediate render to show final size
                    self.render_ui()
                    return

                # Handle normal selection
                if widget_def and widget_def.get('selectable', True):
                    # Update selected widget
                    self._selected_widget_id = clicked_widget_id
                    # Also update state so apps can track selection
                    self.state['selected_widget'] = clicked_widget_id
                    self.render_ui()  # Re-render to show selection
                    return

                # Handle focusable widgets (like editors)
                # Check if widget can focus either by definition or by having can_focus method
                widget_obj = self._mounted_widgets.get(clicked_widget_id)
                can_focus = False

                # Check widget definition first
                if widget_def and widget_def.get('focusable', False):
                    can_focus = True
                # Then check if widget has can_focus method
                elif widget_obj and hasattr(widget_obj, 'can_focus') and callable(widget_obj.can_focus):
                    can_focus = widget_obj.can_focus()

                if can_focus:
                    # Use centralized focus management
                    self.set_widget_focus(clicked_widget_id)
                    # Also call on_click if the widget has it
                    if widget_obj and hasattr(widget_obj, 'on_click'):
                        widget_obj.on_click(event)
                    self.debug_log(f"Set focus to widget {clicked_widget_id}")
                    self.render_ui()
                    return

        # Clicked on background or non-selectable area
        self.debug_log(f"Click on background - attached: {self._attached_widget_id}, resize: {self._resize_widget_id}")

        # Clear focus from any focused widget using centralized method
        if self._focused_widget_id:
            self.debug_log(f"Clearing focus from widget {self._focused_widget_id}")
            self.set_widget_focus(None)

        # If we have an attached widget, drop it
        if self._attached_widget_id:
            self.debug_log(f"Dropping attached widget {self._attached_widget_id} on background click")

            # Clear ALL drag-related state
            self._attached_widget_id = None
            self.state['_attached_widget'] = None
            self._reconciliation_paused = False

            # Clear cache immediately
            if hasattr(self, '_cached_widget_definitions'):
                delattr(self, '_cached_widget_definitions')

            # Cancel any pending timer
            if self._resume_reconciliation_timer:
                self._resume_reconciliation_timer.stop()
                self._resume_reconciliation_timer = None

        # If we're in resize mode, cancel it
        if self._resize_mode and self._resize_widget_id:
            self.debug_log(f"Canceling resize of widget {self._resize_widget_id} on background click")

            # Clear ALL resize-related state
            self._resize_mode = False
            self._resize_widget_id = None
            self.state['_resize_widget'] = None
            self._reconciliation_paused = False

            # Clear cache immediately
            if hasattr(self, '_cached_widget_definitions'):
                delattr(self, '_cached_widget_definitions')

            # Cancel any pending timer
            if self._resume_reconciliation_timer:
                self._resume_reconciliation_timer.stop()
                self._resume_reconciliation_timer = None

        # Deselect any selected widget
        self._selected_widget_id = None
        self.state['selected_widget'] = None

        self.render_ui()

    def on_mouse_move(self, event):
        """Handle mouse movement for hover detection and dragging"""
        # Store mouse position for attached widget
        self._last_mouse_x = event.screen_x if hasattr(event, 'screen_x') else event.x
        self._last_mouse_y = event.screen_y if hasattr(event, 'screen_y') else event.y

        # Track hover over context menu items
        if self._context_menu_state['visible']:
            menu = self._context_menu_state  # Define menu at the outer scope
            if self._is_click_in_context_menu(event):
                # Calculate which item is being hovered
                menu_y = menu['y']
                hover_y = event.screen_y if hasattr(event, 'screen_y') else event.y
                relative_y = hover_y - menu_y - 1  # -1 for border

                # Update selected index based on hover
                if 0 <= relative_y < len(menu['items']):
                    old_index = menu.get('selected_index', -1)
                    menu['selected_index'] = relative_y
                    # Re-render if selection changed
                    if old_index != relative_y:
                        self.render_ui()
            else:
                # Clear selection when not hovering over menu
                if menu.get('selected_index', -1) >= 0:
                    menu['selected_index'] = -1
                    self.render_ui()

        # Log mouse moves during drag/resize operations
        if self._attached_widget_id or self._resize_widget_id:
            self.debug_log(f"MOUSE_MOVE during operation - pos: ({self._last_mouse_x}, {self._last_mouse_y}), attached: {self._attached_widget_id}, resize: {self._resize_widget_id}")

        # Validate widget still exists before continuing
        if self._attached_widget_id:
            if self._attached_widget_id not in self._mounted_widgets:
                self.debug_log(f"WARNING: Attached widget {self._attached_widget_id} no longer exists, clearing state")
                self._attached_widget_id = None
                self.state['_attached_widget'] = None
                self._reconciliation_paused = False
                if hasattr(self, '_cached_widget_definitions'):
                    delattr(self, '_cached_widget_definitions')
            else:
                # Check if the widget is actually still mounted
                widget = self._mounted_widgets[self._attached_widget_id]
                if not widget.parent:
                    self.debug_log(f"WARNING: Attached widget {self._attached_widget_id} exists but not mounted!")
                    self._attached_widget_id = None
                    self.state['_attached_widget'] = None
                    self._reconciliation_paused = False
                    if hasattr(self, '_cached_widget_definitions'):
                        delattr(self, '_cached_widget_definitions')

        if self._resize_widget_id and self._resize_widget_id not in self._mounted_widgets:
            self.debug_log(f"WARNING: Resize widget {self._resize_widget_id} no longer exists, clearing state")
            self._resize_mode = False
            self._resize_widget_id = None
            self.state['_resize_widget'] = None
            self._reconciliation_paused = False
            if hasattr(self, '_cached_widget_definitions'):
                delattr(self, '_cached_widget_definitions')

        # Handle attached widget movement
        if self._attached_widget_id:
            # Let Textual handle render timing naturally
            self.render_ui()
            return  # Skip hover detection while moving attached widget

        # Handle resize mode
        elif self._resize_mode and self._resize_widget_id:
            # Let Textual handle render timing naturally
            self.render_ui()
            return  # Skip hover detection while resizing

        # Handle dragging first (mouse capture mode)
        if self._dragging_widget_id:
            self.debug_log(f"MouseMove during drag: ({event.screen_x}, {event.screen_y})")
            # Calculate new position based on mouse movement
            delta_x = event.screen_x - self._drag_start_mouse_x
            delta_y = event.screen_y - self._drag_start_mouse_y

            new_x = self._drag_start_widget_x + delta_x
            new_y = self._drag_start_widget_y + delta_y

            # Ensure position stays within screen bounds
            if hasattr(self, 'size') and self.size:
                new_x = max(0, min(new_x, self.size.width - 10))
                new_y = max(0, min(new_y, self.size.height - 5))

            # Update widget position in widget definitions
            for widget_def in self._widget_definitions:
                if widget_def.get('id') == self._dragging_widget_id:
                    widget_def['x'] = new_x
                    widget_def['y'] = new_y
                    # Also update the virtual DOM
                    if self._dragging_widget_id in self._virtual_dom:
                        self._virtual_dom[self._dragging_widget_id]['x'] = new_x
                        self._virtual_dom[self._dragging_widget_id]['y'] = new_y
                    break

            # Update debug info in state
            self.state['_dragging'] = {
                'widget_id': self._dragging_widget_id,
                'current_pos': (new_x, new_y),
                'delta': (delta_x, delta_y)
            }

            # Force re-render to update widget position
            self.render_ui()
            return  # Skip hover detection while dragging

        # Throttle hover checks to avoid performance issues
        current_time = time.time()
        time_since_last_check = current_time - self._last_hover_check_time

        if time_since_last_check < self._hover_throttle_interval:
            # Skip this check, too soon since last one
            return

        self._last_hover_check_time = current_time

        # Use screen coordinates to find widget at position
        # This gives us the actual widget under the mouse at app level
        screen_x = event.screen_x if hasattr(event, 'screen_x') else event.x
        screen_y = event.screen_y if hasattr(event, 'screen_y') else event.y

        # Get the widget at screen position
        widget_at_pos = self.get_widget_at(screen_x, screen_y)
        hovered_widget = None
        hovered_widget_id = None

        # get_widget_at returns (widget, region) tuple
        if widget_at_pos and isinstance(widget_at_pos, tuple):
            hovered_widget, region = widget_at_pos
        elif widget_at_pos:
            hovered_widget = widget_at_pos

        # Debug info
        debug_info = {
            'mouse_x': screen_x,
            'mouse_y': screen_y,
            'local_x': event.x,
            'local_y': event.y,
            'hovered_widget': str(hovered_widget) if hovered_widget else 'None',
            'widget_id_attr': getattr(hovered_widget, 'id', 'no_id') if hovered_widget else 'None',
        }

        # Check if the hovered widget is one of our mounted widgets
        if hovered_widget:
            # Check if it's directly in our mounted widgets
            for widget_id, widget in self._mounted_widgets.items():
                if widget == hovered_widget:
                    hovered_widget_id = widget_id
                    break

            # If not found, it might be a child widget, so traverse up
            if not hovered_widget_id:
                parent = hovered_widget.parent if hasattr(hovered_widget, 'parent') else None
                while parent and not hovered_widget_id:
                    for widget_id, widget in self._mounted_widgets.items():
                        if widget == parent:
                            hovered_widget_id = widget_id
                            break
                    parent = parent.parent if hasattr(parent, 'parent') else None

        # Skip background and system widgets
        if hovered_widget_id in ['background', 'connection_canvas']:
            hovered_widget_id = None

        # Store debug info in state
        self.state['_hover_debug'] = {
            'hovered_widget_id': hovered_widget_id,
            'debug': debug_info,
            'throttle_info': {
                'time_since_last': time_since_last_check,
                'throttle_interval': self._hover_throttle_interval
            }
        }

        # Check if hover state changed
        if hovered_widget_id != self._hovered_widget_id:
            # Remove hover style from previously hovered widget
            if self._hovered_widget_id:
                prev_widget = self._mounted_widgets.get(self._hovered_widget_id)
                if prev_widget:
                    self._apply_hover_style(prev_widget, self._hovered_widget_id, False)

            # Update hover state
            self._hovered_widget_id = hovered_widget_id
            self.state['hovered_widget'] = hovered_widget_id

            # Apply hover style to newly hovered widget
            if hovered_widget_id:
                widget = self._mounted_widgets.get(hovered_widget_id)
                if widget:
                    self._apply_hover_style(widget, hovered_widget_id, True)

            # Re-render to show hover changes
            self.render_ui()

    def on_key(self, event):
        """Handle keyboard events"""
        if event.key == "escape":
            # First check if context menu is visible
            if self._context_menu_state['visible']:
                self._hide_context_menu()
                self.render_ui()
                return

            # Dump complete state before clearing
            self.debug_log("\n=== ESC PRESSED - DUMPING COMPLETE STATE ===")
            self.debug_log("=== Internal State Variables ===")
            self.debug_log(f"_attached_widget_id: {self._attached_widget_id}")
            self.debug_log(f"_resize_widget_id: {self._resize_widget_id}")
            self.debug_log(f"_resize_mode: {getattr(self, '_resize_mode', False)}")
            self.debug_log(f"_selected_widget_id: {self._selected_widget_id}")
            self.debug_log(f"_hovered_widget_id: {self._hovered_widget_id}")
            self.debug_log(f"_reconciliation_paused: {self._reconciliation_paused}")
            self.debug_log(f"_last_mouse_x: {getattr(self, '_last_mouse_x', 'N/A')}")
            self.debug_log(f"_last_mouse_y: {getattr(self, '_last_mouse_y', 'N/A')}")
            self.debug_log(f"_attach_offset_x: {getattr(self, '_attach_offset_x', 'N/A')}")
            self.debug_log(f"_attach_offset_y: {getattr(self, '_attach_offset_y', 'N/A')}")

            self.debug_log("\n=== Widget Overrides ===")
            for widget_id, overrides in self._widget_overrides.items():
                self.debug_log(f"{widget_id}: {overrides}")

            self.debug_log("\n=== Virtual DOM ===")
            if hasattr(self, '_virtual_dom'):
                for widget_id, vdom_data in self._virtual_dom.items():
                    self.debug_log(f"{widget_id}: x={vdom_data.get('x')}, y={vdom_data.get('y')}, w={vdom_data.get('width')}, h={vdom_data.get('height')}")

            self.debug_log("\n=== Widget Definitions ===")
            if hasattr(self, '_widget_definitions'):
                for widget_def in self._widget_definitions:
                    if 'id' in widget_def:
                        self.debug_log(f"{widget_def['id']}: x={widget_def.get('x')}, y={widget_def.get('y')}, w={widget_def.get('width')}, h={widget_def.get('height')}")

            self.debug_log("\n=== Mounted Widgets ===")
            self.debug_log(f"Count: {len(self._mounted_widgets)}")
            for widget_id in self._mounted_widgets:
                self.debug_log(f"- {widget_id}")

            # Clear ALL state
            self.debug_log("\n=== CLEARING ALL STATE ===")

            # Cancel any active operations
            if self._attached_widget_id:
                self.debug_log(f"Cancelling drag of {self._attached_widget_id}")
            if self._resize_mode:
                self.debug_log(f"Cancelling resize of {self._resize_widget_id}")

            # Clear all drag/resize state
            self._attached_widget_id = None
            self.state['_attached_widget'] = None
            self._resize_mode = False
            self._resize_widget_id = None
            self.state['_resize_widget'] = None
            self._reconciliation_paused = False

            # Clear selection
            if self._selected_widget_id:
                self.debug_log(f"Deselecting {self._selected_widget_id}")
            self._selected_widget_id = None
            self.state['selected_widget'] = None

            # Clear cache
            if hasattr(self, '_cached_widget_definitions'):
                delattr(self, '_cached_widget_definitions')
                self.debug_log("Cleared widget definition cache")

            # Clear any pending timers
            if hasattr(self, '_resume_reconciliation_timer') and self._resume_reconciliation_timer:
                self._resume_reconciliation_timer.stop()
                self._resume_reconciliation_timer = None
                self.debug_log("Cleared reconciliation timer")

            self.debug_log("=== STATE CLEARED ===\n")
            self.render_ui()
            return

        # Handle WASD movement and Shift+WASD resizing for selected widget
        elif self._selected_widget_id:
            widget_def = self._get_widget_definition(self._selected_widget_id)
            if widget_def and widget_def.get('draggable', True):
                handled = False

                # Get current position and size
                x = widget_def.get('x', 0)
                y = widget_def.get('y', 0)
                width = widget_def.get('width', 20)
                height = widget_def.get('height', 5)

                # Movement keys (WASD)
                if event.key == "w":  # Up
                    y = max(0, y - 1)
                    handled = True
                elif event.key == "s":  # Down
                    y = y + 1
                    handled = True
                elif event.key == "a":  # Left
                    x = max(0, x - 1)
                    handled = True
                elif event.key == "d":  # Right
                    x = x + 1
                    handled = True

                # Resize keys (Shift+WASD)
                elif event.key == "W":  # Shift+W - Decrease height
                    height = max(3, height - 1)
                    handled = True
                elif event.key == "S":  # Shift+S - Increase height
                    height = height + 1
                    handled = True
                elif event.key == "A":  # Shift+A - Decrease width
                    width = max(10, width - 1)
                    handled = True
                elif event.key == "D":  # Shift+D - Increase width
                    width = width + 1
                    handled = True

                if handled:
                    # Ensure position stays within bounds
                    if hasattr(self, 'size') and self.size:
                        x = max(0, min(x, self.size.width - width))
                        y = max(0, min(y, self.size.height - height))

                    # Update position/size in virtual DOM
                    if self._selected_widget_id in self._virtual_dom:
                        self._virtual_dom[self._selected_widget_id]['x'] = x
                        self._virtual_dom[self._selected_widget_id]['y'] = y
                        self._virtual_dom[self._selected_widget_id]['width'] = width
                        self._virtual_dom[self._selected_widget_id]['height'] = height

                    # Store overrides internally
                    if self._selected_widget_id not in self._widget_overrides:
                        self._widget_overrides[self._selected_widget_id] = {}
                    self._widget_overrides[self._selected_widget_id]['x'] = x
                    self._widget_overrides[self._selected_widget_id]['y'] = y
                    self._widget_overrides[self._selected_widget_id]['width'] = width
                    self._widget_overrides[self._selected_widget_id]['height'] = height

                    # Call handler if exists
                    if hasattr(self, 'on_widget_move_resize'):
                        self.on_widget_move_resize(self._selected_widget_id, x, y, width, height)
                    elif hasattr(self, 'on_widget_drop'):
                        # Fallback to drop handler for backward compatibility
                        self.on_widget_drop(self._selected_widget_id, x, y)

                    self.debug_log(f"Moved/resized {self._selected_widget_id} to ({x},{y}) size ({width}x{height})")
                    self.render_ui()
                    return  # Consume the event

        # Forward key events to focused widget
        # Glass widgets bypass Textual's normal focus system, so we need to
        # manually forward keys to the focused widget
        if self._focused_widget_id and self._focused_widget_id in self._mounted_widgets:
            widget = self._mounted_widgets[self._focused_widget_id]
            # Check if this is a widget that can handle key events
            if hasattr(widget, 'on_key') and hasattr(widget, '_has_focus') and widget._has_focus:
                # Forward the key event to the widget
                widget.on_key(event)
                return  # Consume the event

    def _get_widget_definition(self, widget_id: str) -> Optional[Dict]:
        """Get the widget definition for a given widget ID"""
        # CRITICAL: We need to return the widget WITH overrides applied
        # because the drag calculation needs to know the CURRENT position

        # First, try to get the original definition from create_widgets
        original_widgets = self.create_widgets()
        for widget_def in original_widgets:
            if widget_def.get('id') == widget_id:
                result = copy.deepcopy(widget_def)
                # Apply any overrides to get the CURRENT position
                if widget_id in self._widget_overrides:
                    result.update(self._widget_overrides[widget_id])
                return result

        # Fallback to virtual DOM if not found in create_widgets
        if widget_id in self._virtual_dom:
            return copy.deepcopy(self._virtual_dom[widget_id])

        # Last fallback to current definitions
        if hasattr(self, '_widget_definitions'):
            for widget_def in self._widget_definitions:
                if widget_def.get('id') == widget_id:
                    return copy.deepcopy(widget_def)

        return None

    def _apply_selection_style(self, widget: Any, widget_id: str):
        """Apply selection visual to a widget"""
        if widget_id == self._selected_widget_id:
            # Store original blur if not already stored
            if not hasattr(widget, '_original_blur'):
                widget._original_blur = getattr(widget, 'blur', 2)

            # Set blur to 8 for selected widget (more dramatic glass effect)
            if hasattr(widget, 'blur'):
                widget.blur = 8

            # Add "*" to title if it has one
            if hasattr(widget, 'title') and widget.title:
                if not hasattr(widget, '_original_title'):
                    widget._original_title = widget.title
                # Only add * if not already there
                if not widget.title.startswith('* '):
                    widget.title = f"* {widget.title}"

            # Also make the title bold and bright
            if hasattr(widget, '_title_css'):
                if not hasattr(widget, '_original_title_css'):
                    widget._original_title_css = widget._title_css.copy() if widget._title_css else {}
                widget._title_css = widget._title_css or {}
                widget._title_css['color'] = '#00ff00'
                widget._title_css['text_style'] = 'bold'

            self.log(f"Applied selection style to {widget_id}")
        else:
            # Restore original styles if previously selected
            if hasattr(widget, '_original_blur'):
                widget.blur = widget._original_blur
                delattr(widget, '_original_blur')

            if hasattr(widget, '_original_title'):
                widget.title = widget._original_title
                delattr(widget, '_original_title')

            if hasattr(widget, '_original_title_css'):
                widget._title_css = widget._original_title_css
                delattr(widget, '_original_title_css')

    def _apply_hover_style(self, widget: Any, widget_id: str, is_hovered: bool):
        """Apply or remove hover visual to a widget"""
        if is_hovered:
            # Store original values if not already stored
            if not hasattr(widget, '_hover_original_opacity'):
                widget._hover_original_opacity = getattr(widget, 'blend_opacity', 0.5)

            # Subtle hover effect - slightly increase opacity
            if hasattr(widget, 'blend_opacity'):
                # Don't override selection opacity if selected
                if widget_id != self._selected_widget_id:
                    widget.blend_opacity = min(1.0, widget._hover_original_opacity + 0.1)

            # Add hover indicator to border CSS if not selected
            if widget_id != self._selected_widget_id:
                # Initialize _border_css if it doesn't exist (for panels)
                if not hasattr(widget, '_border_css'):
                    widget._border_css = {}

                if not hasattr(widget, '_hover_original_border_css'):
                    widget._hover_original_border_css = widget._border_css.copy() if widget._border_css else {}

                widget._border_css = widget._border_css or {}
                widget._border_css['color'] = '#00aaff'  # Light blue for hover
                widget._border_css['text_style'] = 'bold'
        else:
            # Restore original styles if previously hovered
            if hasattr(widget, '_hover_original_opacity'):
                # Only restore if not selected
                if widget_id != self._selected_widget_id:
                    widget.blend_opacity = widget._hover_original_opacity
                delattr(widget, '_hover_original_opacity')

            if hasattr(widget, '_hover_original_border_css'):
                if widget_id != self._selected_widget_id:
                    widget._border_css = widget._hover_original_border_css
                delattr(widget, '_hover_original_border_css')

    def _update_all_positions(self):
        """Update all widget positions, handling floating widgets specially"""
        if not self.size:
            return

        # First pass: calculate true positions for all widgets
        widget_positions = {}
        for widget in self._absolute_widgets:
            x, y, width, height = widget.calculate_position(self.size.width, self.size.height)
            widget_positions[widget] = (x, y, width, height)

        # Sort by z-index for render order
        self._absolute_widgets.sort(key=lambda w: w.z_index)

        # Second pass: apply positions
        # Track where Textual is placing widgets (cumulative)
        textual_y = 0

        for i, widget in enumerate(self._compose_order):
            if widget in widget_positions:
                x, y, width, height = widget_positions[widget]

                # Floating widgets get absolute positioning without Y-cascade
                if hasattr(widget, '_floating') and widget._floating:
                    widget.styles.offset = (x, y)
                    widget.styles.width = width
                    widget.styles.height = height
                    # IMPORTANT: Don't update textual_y for floating widgets!
                    continue  # Skip the rest of the loop
                else:
                    # Regular widgets participate in Y-cascade
                    # Calculate offset: where we want it - where Textual put it
                    offset_y = y - textual_y
                    widget.styles.offset = (x, offset_y)

                    # Update where Textual will place the next widget
                    textual_y += height

                widget.styles.width = width
                widget.styles.height = height

                if hasattr(self, 'log'):
                    is_floating = hasattr(widget, '_floating') and widget._floating
                    widget_id = getattr(widget, 'id', 'unknown')
                    self.log(f"Widget {i} {widget_id} (floating={is_floating}): want y={y}, textual_y={textual_y - height if not is_floating else 'N/A'}, offset={widget.styles.offset}, height={height}")

    # ===========================================================================
    # FOCUS MANAGEMENT
    # ===========================================================================

    def set_widget_focus(self, widget_id: Optional[str]):
        """
        Set focus to a specific widget or clear focus.

        Args:
            widget_id: Widget ID to focus, or None to clear focus
        """
        # Clear focus from current widget
        if self._focused_widget_id and self._focused_widget_id in self._mounted_widgets:
            old_widget = self._mounted_widgets[self._focused_widget_id]
            if hasattr(old_widget, 'on_blur'):
                old_widget.on_blur()
            if hasattr(old_widget, '_has_focus'):
                old_widget._has_focus = False

        # Set new focus
        self._focused_widget_id = widget_id

        if widget_id and widget_id in self._mounted_widgets:
            widget = self._mounted_widgets[widget_id]
            if hasattr(widget, 'on_focus'):
                widget.on_focus()
            if hasattr(widget, '_has_focus'):
                widget._has_focus = True

            # Add to focus stack
            if widget_id in self._focus_stack:
                self._focus_stack.remove(widget_id)
            self._focus_stack.append(widget_id)

    def get_focused_widget_id(self) -> Optional[str]:
        """Get the currently focused widget ID"""
        return self._focused_widget_id

    def focus_next(self):
        """Focus the next focusable widget"""
        focusable_widgets = []
        for widget_id, widget in self._mounted_widgets.items():
            widget_def = self._get_widget_definition(widget_id)
            if widget_def and widget_def.get('focusable', False):
                focusable_widgets.append(widget_id)

        if not focusable_widgets:
            return

        if not self._focused_widget_id:
            # Focus first widget
            self.set_widget_focus(focusable_widgets[0])
        else:
            # Focus next widget
            try:
                current_index = focusable_widgets.index(self._focused_widget_id)
                next_index = (current_index + 1) % len(focusable_widgets)
                self.set_widget_focus(focusable_widgets[next_index])
            except ValueError:
                # Current focus not in list, focus first
                self.set_widget_focus(focusable_widgets[0])

    def focus_previous(self):
        """Focus the previous focusable widget"""
        focusable_widgets = []
        for widget_id, widget in self._mounted_widgets.items():
            widget_def = self._get_widget_definition(widget_id)
            if widget_def and widget_def.get('focusable', False):
                focusable_widgets.append(widget_id)

        if not focusable_widgets:
            return

        if not self._focused_widget_id:
            # Focus last widget
            self.set_widget_focus(focusable_widgets[-1])
        else:
            # Focus previous widget
            try:
                current_index = focusable_widgets.index(self._focused_widget_id)
                prev_index = (current_index - 1) % len(focusable_widgets)
                self.set_widget_focus(focusable_widgets[prev_index])
            except ValueError:
                # Current focus not in list, focus last
                self.set_widget_focus(focusable_widgets[-1])

    def _patch_widget_render_for_css(self, widget: Any):
        """
        Patch a widget's render_line method to support CSS styles.

        This wraps the original render_line to modify the RichStyle
        objects based on stored CSS properties.
        """
        # Check if widget has render_line method
        if not hasattr(widget, 'render_line'):
            self.log(f"Widget {widget.id if hasattr(widget, 'id') else 'unknown'} has no render_line method")
            return

        # Check if we've already patched this widget
        if hasattr(widget, '_original_render_line'):
            # Already patched - the current render_line is our wrapper
            # No need to wrap again
            return

        # Store the original render_line method
        original_render_line = widget.render_line
        widget._original_render_line = original_render_line

        def css_aware_render_line(y: int) -> Strip:
            # Get the original strip - use the stored original method
            strip = widget._original_render_line(y)

            # If no CSS styles, return original
            if not hasattr(widget, '_css_styles') or not widget._css_styles:
                return strip

            # DEBUG: Log what CSS we're applying for sparkline
            # (Removed print - Textual swallows it)

            # Access segments - try different methods based on what's available
            segments = []
            if hasattr(strip, '_segments'):
                segments = strip._segments
            else:
                # If no _segments, iterate over strip
                segments = list(strip)

            # Modify segments based on CSS
            modified_segments = []

            for segment in segments:
                text = segment.text
                original_style = segment.style or RichStyle()

                # Create new style based on CSS properties
                style_kwargs = {}

                # Background color (preserve glass effect if already set)
                if original_style.bgcolor:
                    style_kwargs['bgcolor'] = original_style.bgcolor

                # Text color - ALWAYS apply if CSS specifies it
                text_color = getattr(widget, '_text_color', 'white')

                # DEBUG for sparkline - removed (Textual swallows prints)

                # Apply text color from CSS (even if it's white - to override defaults)
                if text_color:
                    # Handle color values that might need conversion
                    color_map = {
                        'black': '#000000',
                        'gray': '#808080',
                        'red': '#ff0000',
                        'green': '#00ff00',
                        'blue': '#0000ff',
                        'yellow': '#ffff00',
                        'cyan': '#00ffff',
                        'magenta': '#ff00ff',
                        'orange': '#ffa500',
                        'purple': '#800080',
                        'darkcyan': '#008b8b',
                        'darkblue': '#00008b',
                        'darkgreen': '#006400',
                        'darkred': '#8b0000',
                        'lightblue': '#add8e6',
                        'pink': '#ffc0cb',
                        'brown': '#a52a2a'
                    }
                    if text_color in color_map:
                        text_color = color_map[text_color]
                    style_kwargs['color'] = text_color

                # Text styles
                if getattr(widget, '_text_bold', False):
                    style_kwargs['bold'] = True
                elif hasattr(original_style, 'bold') and original_style.bold:
                    style_kwargs['bold'] = True

                if getattr(widget, '_text_italic', False):
                    style_kwargs['italic'] = True

                if getattr(widget, '_text_underline', False):
                    style_kwargs['underline'] = True

                if getattr(widget, '_text_reverse', False):
                    style_kwargs['reverse'] = True

                if getattr(widget, '_text_strike', False):
                    style_kwargs['strike'] = True

                new_style = RichStyle(**style_kwargs)
                modified_segments.append(Segment(text, new_style))

            return Strip(modified_segments)

        # Replace the render_line method
        widget.render_line = css_aware_render_line

        # Debug log
        if hasattr(widget, '_css_styles') and widget._css_styles:
            self.log(f"Patched render_line for widget {widget.id if hasattr(widget, 'id') else 'unknown'}")

    # ===========================================================================
    # PERFORMANCE UTILITIES
    # ===========================================================================

    def get_performance_color(self, value: float, history: List[float] = None,
                              thresholds: Dict[str, float] = None) -> str:
        """
        Get a color based on performance metrics using adaptive thresholds.

        Args:
            value: Current value to evaluate
            history: Historical values for percentile-based coloring
            thresholds: Optional fixed thresholds {'good': 50, 'ok': 100}

        Returns:
            Hex color string
        """
        if history and len(history) >= 10:
            # Use percentile-based adaptive coloring
            sorted_history = sorted(history)
            p25 = sorted_history[int(len(sorted_history) * 0.25)]
            p75 = sorted_history[int(len(sorted_history) * 0.75)]

            # Check if performance is very stable
            range_size = p75 - p25
            median = sorted_history[int(len(sorted_history) * 0.50)]

            if range_size < median * 0.05:
                # Stable performance - use recent trend
                recent_avg = sum(history[-10:]) / 10

                if value < recent_avg * 0.98:
                    return '#00ff00'  # Green
                elif value > recent_avg * 1.02:
                    return '#ffaa00'  # Orange
                else:
                    return '#ffff00'  # Yellow
            else:
                # Normal percentile-based coloring
                if value <= p25:
                    return '#00ff00'  # Green
                elif value >= p75:
                    return '#ff0000'  # Red
                else:
                    # Gradient in middle range
                    ratio = (value - p25) / (p75 - p25)
                    if ratio < 0.5:
                        # Green to yellow
                        red = int(255 * ratio * 2)
                        return f'#{red:02x}ff00'
                    else:
                        # Yellow to red
                        green = int(255 * (2 - ratio * 2))
                        return f'#ff{green:02x}00'

        elif thresholds:
            # Use provided thresholds
            if value < thresholds.get('good', 50):
                return '#00ff00'  # Green
            elif value < thresholds.get('ok', 100):
                return '#ffff00'  # Yellow
            else:
                return '#ff0000'  # Red
        else:
            # Default thresholds
            if value < 50:
                ratio = value / 50.0
                red = int(255 * ratio)
                return f'#{red:02x}ff00'
            elif value < 100:
                ratio = (value - 50) / 50.0
                green = int(255 * (1 - ratio))
                return f'#ff{green:02x}00'
            else:
                return '#ff0000'

    def create_sparkline(self, values: List[float], width: int = 20) -> str:
        """
        Create a mini sparkline using Unicode block characters.

        Args:
            values: List of values to visualize
            width: Maximum width in characters

        Returns:
            Unicode sparkline string
        """
        if not values or len(values) < 2:
            return ''

        # Unicode block elements for sparkline
        blocks = ' ▁▂▃▄▅▆▇█'

        # Take last 'width' values
        data = values[-width:] if len(values) > width else values

        # Find min and max for scaling
        min_val = min(data)
        max_val = max(data)

        if max_val == min_val:
            # All values are the same
            return blocks[4] * len(data)

        # Scale values to 0-8 range
        sparkline = ''
        for val in data:
            scaled = int(((val - min_val) / (max_val - min_val)) * 8)
            sparkline += blocks[scaled]

        return sparkline

    # ===========================================================================
    # ANIMATION AND DYNAMIC PROPERTIES
    # ===========================================================================

    def animate_widget(self, widget_id: str, properties: Dict[str, Any],
                       duration: float = 1.0, easing: str = 'linear'):
        """
        Animate widget properties over time.

        Args:
            widget_id: Widget to animate
            properties: Target property values
            duration: Animation duration in seconds
            easing: Easing function name
        """
        # TODO: Implement smooth animations
        # For now, just update immediately
        widget_def = {'id': widget_id}
        widget_def.update(properties)
        self._update_widget(widget_id, widget_def)

    def calculate_dynamic_property(self, base_value: Union[int, float],
                                   factor: float, variation: float = 0.2) -> Union[int, float]:
        """
        Calculate a dynamic property value based on a factor.

        Args:
            base_value: Base value
            factor: Factor (0.0 to 1.0)
            variation: Maximum variation as percentage

        Returns:
            Dynamic value
        """
        variation_amount = base_value * variation * factor
        return base_value + (int(variation_amount) if isinstance(base_value, int) else variation_amount)

    # ===========================================================================
    # WIDGET COMPOSITION HELPERS
    # ===========================================================================

    def compose_page(self, page_name: str, widgets: List[Dict],
                     header: Optional[Dict] = None,
                     navigation: Optional[Dict] = None,
                     modal: Optional[Dict] = None) -> List[Dict]:
        """
        Compose a standard page layout.

        Args:
            page_name: Name of the page
            widgets: Main content widgets
            header: Optional header widget
            navigation: Optional navigation widget
            modal: Optional modal overlay

        Returns:
            Complete widget list
        """
        composed = []

        # Add standard components
        if header:
            composed.append(header)
        if navigation:
            composed.append(navigation)

        # Add main content
        composed.extend(widgets)

        # Add modal last (highest z-index)
        if modal:
            composed.append(modal)

        return composed

    def filter_widgets_by_page(self, widgets: List[Dict], page: str) -> List[Dict]:
        """
        Filter widgets to only show those for the current page.

        Args:
            widgets: All widgets
            page: Current page name

        Returns:
            Filtered widget list
        """
        return [w for w in widgets if w.get('page', 'all') in ['all', page]]

    # ===========================================================================
    # DATA-DRIVEN WIDGET PATTERNS
    # ===========================================================================

    # ===========================================================================
    # CONTEXT MENU SYSTEM
    # ===========================================================================

    def _update_context_menu(self):
        """Update context menu widget - just move it on/off screen instead of adding/removing"""
        # Check if we already have a context menu widget mounted
        existing_menu = self._mounted_widgets.get('context_menu')

        if self._context_menu_state['visible']:
            # Need to show context menu
            menu_def = self._create_context_menu_widget()
            if menu_def:
                if existing_menu:
                    # Just update the existing menu (position and content)
                    self._update_widget('context_menu', menu_def)
                else:
                    # First time - add it (this should only happen once)
                    self._add_widget(menu_def)
        else:
            # Need to hide context menu - move it off screen instead of removing
            if existing_menu:
                # Move off-screen instead of removing
                off_screen_def = {
                    'id': 'context_menu',
                    'type': 'panel',
                    'title': '',
                    'content': ['Hidden'],
                    'x': 9999,  # Also hide to the right
                    'y': 9999,  # Hide below viewport
                    'width': 10,
                    'height': 1,
                    'overlay_color': 'darkblue',
                    'blend_opacity': 0.1,
                    '_context_menu': True
                }
                self._update_widget('context_menu', off_screen_def)

    def _handle_right_click(self, event: MouseDown):
        """Handle right-click to show context menu"""
        # Find widget under cursor
        clicked_widget = event.widget
        clicked_widget_id = None

        # Find which of our mounted widgets was clicked
        if clicked_widget:
            for widget_id, widget in self._mounted_widgets.items():
                if widget == clicked_widget:
                    clicked_widget_id = widget_id
                    break

            # If not found directly, check parents
            if not clicked_widget_id:
                parent = clicked_widget.parent
                while parent and not clicked_widget_id:
                    for widget_id, widget in self._mounted_widgets.items():
                        if widget == parent:
                            clicked_widget_id = widget_id
                            break
                    parent = parent.parent if hasattr(parent, 'parent') else None

        # If we couldn't find the widget by reference, try by position
        if not clicked_widget_id and hasattr(event, 'screen_x') and hasattr(event, 'screen_y'):
            # Check each mounted widget's bounds
            for widget_id, widget in self._mounted_widgets.items():
                if widget_id in ['background', 'connection_canvas', 'context_menu']:
                    continue
                # Get widget's screen position
                if hasattr(widget, 'offset') and hasattr(widget, 'region'):
                    region = widget.region
                    if region.contains(event.screen_x, event.screen_y):
                        clicked_widget_id = widget_id
                        break

        # Check if we clicked on background/empty space
        is_background = clicked_widget_id in ['background', 'connection_canvas', None]

        if is_background:
            # Build context menu for empty space
            # Pass the mouse position in the widget definition so apps can use it
            menu_items = self.build_context_menu(None, {
                'type': 'background',
                'mouse_x': event.screen_x if hasattr(event, 'screen_x') else event.x,
                'mouse_y': event.screen_y if hasattr(event, 'screen_y') else event.y
            })
            if menu_items:
                # Update CREATE_WIDGET actions with the actual mouse position
                for item in menu_items:
                    # Skip divider strings
                    if isinstance(item, str):
                        continue
                    if item.get('id') == 'create_widget' and item.get('action'):
                        item['action'].payload = {
                            'x': event.screen_x if hasattr(event, 'screen_x') else event.x,
                            'y': event.screen_y if hasattr(event, 'screen_y') else event.y
                        }

                self._show_context_menu(
                    event.screen_x if hasattr(event, 'screen_x') else event.x,
                    event.screen_y if hasattr(event, 'screen_y') else event.y,
                    None,
                    menu_items
                )
        else:
            # Build context menu for specific widget
            widget_def = self._get_widget_definition(clicked_widget_id)
            if widget_def:
                menu_items = self.build_context_menu(clicked_widget_id, widget_def)
                if menu_items:
                    self._show_context_menu(
                        event.screen_x if hasattr(event, 'screen_x') else event.x,
                        event.screen_y if hasattr(event, 'screen_y') else event.y,
                        clicked_widget_id,
                        menu_items
                    )

    def _show_context_menu(self, x: int, y: int, widget_id: str, items: List[Dict]):
        """Show the context menu at the given position"""

        self._context_menu_state = {
            'visible': True,
            'x': x,
            'y': y,
            'target_widget_id': widget_id,
            'target_mouse_x': x,
            'target_mouse_y': y,
            'items': items,
            'selected_index': 0,
        }

        # Update state for apps to track
        self.state['context_menu'] = self._context_menu_state.copy()

        self.render_ui()

        # Pause reconciliation AFTER the menu is rendered and in place
        self._reconciliation_paused = True
        self.debug_log("Paused reconciliation for context menu")

    def _hide_context_menu(self):
        """Hide the context menu"""
        self._context_menu_state['visible'] = False
        self.state['context_menu'] = {'visible': False}

        # Resume reconciliation after context menu is hidden
        self._reconciliation_paused = False
        self.debug_log("Resumed reconciliation after context menu")

    def build_context_menu(self, widget_id: str, widget_def: Dict) -> List[Dict]:
        """
        Build context menu items for a widget.
        Override this in your app to customize the menu.

        Args:
            widget_id: ID of the widget that was right-clicked (None for background)
            widget_def: Widget definition dictionary with all widget properties

        Returns:
            List of menu item dictionaries
        """
        # Check if widget has custom menu items defined
        if widget_def and widget_def.get('context_menu'):
            return self._build_custom_menu(widget_def['context_menu'], widget_id, widget_def)

        # Check for menu builders by widget type
        menu_builder = self.get_context_menu_builder(widget_def.get('type') if widget_def else 'background')
        if menu_builder:
            return menu_builder(widget_id, widget_def)

        # Default implementation - provide standard items
        return create_context_menu_actions(widget_id, widget_def.get('type', 'widget') if widget_def else None)

    def get_context_menu_builder(self, widget_type: str):
        """
        Get context menu builder for a specific widget type.
        Override this to provide type-specific menus.

        Returns a function that takes (widget_id, widget_def) and returns menu items.
        """
        # Default: return None to use standard menu
        return None

    def _build_custom_menu(self, menu_config: Union[List, Dict], widget_id: str, widget_def: Dict) -> List[Dict]:
        """Build menu from widget's context_menu configuration"""
        if isinstance(menu_config, list):
            # Direct list of menu items
            items = []
            for item in menu_config:
                if isinstance(item, str) and item == 'divider':
                    items.append({'divider': True})
                elif isinstance(item, dict):
                    # Process menu item
                    menu_item = item.copy()
                    # Replace action strings with Action objects
                    if 'action' in menu_item and isinstance(menu_item['action'], str):
                        # Parse action string like "DELETE_WIDGET" or "CUSTOM_ACTION:payload"
                        action_parts = menu_item['action'].split(':', 1)
                        action_type = action_parts[0]
                        action_payload = action_parts[1] if len(action_parts) > 1 else widget_id
                        menu_item['action'] = Action(action_type, action_payload)
                    items.append(menu_item)
            return items
        elif isinstance(menu_config, dict):
            # Menu configuration with templates
            template = menu_config.get('template', 'default')
            if template == 'default':
                return create_context_menu_actions(widget_id, widget_def.get('type'))
            elif template == 'custom':
                return self._build_custom_menu(menu_config.get('items', []), widget_id, widget_def)
            # Add more templates as needed
        return []

    def get_context_menu_style(self) -> Dict:
        """
        Get context menu styling configuration.
        Override this in your app to customize menu appearance.

        Returns:
            Dictionary with style options:
            - overlay_color: Base overlay color
            - blend_opacity: Base opacity
            - border_color: Border color
            - hover_bg_color: Background color when hovering
            - hover_text_style: Text style when hovering (e.g. 'bold white')
            - danger_color: Color for danger items
            - disabled_color: Color for disabled items
        """
        return {
            'overlay_color': 'darkblue',
            'blend_opacity': 0.9,
            'border_color': 'cyan',
            'hover_bg_color': 'blue',
            'hover_text_style': 'bold white',
            'danger_color': 'red',
            'disabled_color': 'dim',
        }

    def _create_context_menu_widget(self) -> Optional[Dict]:
        """Generate the context menu widget from state"""
        if not self._context_menu_state['visible']:
            return None

        menu = self._context_menu_state
        style = self.get_context_menu_style()

        # Build content lines with hover highlighting
        content_lines = []
        for i, item in enumerate(menu['items']):
            # Handle string dividers
            if isinstance(item, str) and item == 'divider':
                content_lines.append('─' * 30)
                continue
            elif isinstance(item, dict) and item.get('divider'):
                content_lines.append('─' * 30)
                continue

            # Check if this item is hovered
            is_selected = (i == menu.get('selected_index') or
                           self.state.get('hovered_widget') == f"context_menu_item_{i}")

            # Build item text
            icon = item.get('icon', '')
            label = item.get('label', '')
            if icon:
                text = f"{icon} {label}"
            else:
                text = f"  {label}"  # Indent for alignment

            # Apply hover effect with background
            if is_selected:
                text = f"▶ {text}"
                # Add background color for better visibility
                hover_style = style.get('hover_text_style', 'bold white')
                hover_bg = style.get('hover_bg_color', 'blue')
                text = f"[{hover_style} on {hover_bg}]{text}[/{hover_style} on {hover_bg}]"
            else:
                text = f"  {text}"
                # Apply normal styling
                if item.get('danger'):
                    danger_color = style.get('danger_color', 'red')
                    text = f"[{danger_color}]{text}[/{danger_color}]"
                elif not item.get('enabled', True):
                    disabled_color = style.get('disabled_color', 'dim')
                    text = f"[{disabled_color}]{text}[/{disabled_color}]"

            content_lines.append(text)

        # Calculate menu position (ensure it fits on screen)
        menu_x = menu['x']
        menu_y = menu['y']
        menu_width = max(len(self._strip_rich_markup(line)) for line in content_lines) + 6
        menu_height = len(content_lines) + 2

        # Adjust position if menu would go off-screen
        if hasattr(self, 'size') and self.size:
            if menu_x + menu_width > self.size.width:
                menu_x = max(0, self.size.width - menu_width)
            if menu_y + menu_height > self.size.height:
                menu_y = max(0, self.size.height - menu_height)

        widget_def = {
            'id': 'context_menu',
            'type': 'rich_dsl',  # Use rich_dsl to properly render Rich markup
            'content': '\n'.join(content_lines),  # Join lines for rich_dsl
            'x': menu_x,
            'y': menu_y,
            'width': menu_width,
            'height': menu_height,
            'overlay_color': style.get('overlay_color', 'darkblue'),
            'blend_opacity': style.get('blend_opacity', 0.9),
            'z_index': 9999,  # Always on top
            'border': True,
            'padding': 1,
            'css_merge': {
                'color': 'white',
            },
            'border_css_merge': {
                'color': style.get('border_color', 'cyan'),
                'text_style': 'bold'
            },
            '_context_menu': True  # Special marker for context menu
        }

        return widget_def

    def _strip_rich_markup(self, text: str) -> str:
        """Strip Rich markup from text for length calculation"""
        import re
        return re.sub(r'\[.*?\]', '', text)

    def _handle_context_menu_click(self, index: int):
        """Handle click on a context menu item"""
        menu = self._context_menu_state
        if menu['visible'] and 0 <= index < len(menu['items']):
            item = menu['items'][index]
            # Skip string dividers
            if isinstance(item, str):
                return
            if not item.get('divider') and item.get('enabled', True):
                # Execute the item's action
                action = item.get('action')
                if action:
                    self.dispatch(action)
                # Hide menu after action
                self._hide_context_menu()
                self.render_ui()

    def _get_context_menu_height(self) -> int:
        """Get the height of the context menu when visible"""
        if hasattr(self, '_context_menu_state') and self._context_menu_state.get('visible'):
            # Calculate menu height from items
            menu_items = self._context_menu_state.get('items', [])
            return len(menu_items) + 2  # +2 for borders
        return 0

    def _is_click_in_context_menu(self, event) -> bool:
        """Check if a click event is within the context menu bounds"""
        if not self._context_menu_state['visible']:
            return False

        menu = self._context_menu_state
        click_x = event.screen_x if hasattr(event, 'screen_x') else event.x
        click_y = event.screen_y if hasattr(event, 'screen_y') else event.y

        # Get menu bounds
        menu_x = menu['x']
        menu_y = menu['y']

        # Calculate menu dimensions
        menu_items = menu['items']
        menu_width = max(len(self._strip_rich_markup(self._format_menu_item(item, False)))
                         for item in menu_items if isinstance(item, dict) and not item.get('divider')) + 6
        menu_height = len(menu_items) + 2

        # Check if click is within bounds
        return (menu_x <= click_x < menu_x + menu_width and
                menu_y <= click_y < menu_y + menu_height)

    def _format_menu_item(self, item: Dict, is_selected: bool) -> str:
        """Format a menu item for display"""
        if item.get('divider'):
            return '─' * 20

        # Build the item text
        icon = item.get('icon', '')
        label = item.get('label', '')
        text = f"{icon} {label}" if icon else label

        # Add selection indicator
        if is_selected:
            text = f"▶ {text}"
        else:
            text = f"  {text}"

        # Apply hover effect with background using style from the app
        style = getattr(self, '_context_menu_style_cache', None)
        if not style:
            # Cache the style so we don't call get_context_menu_style repeatedly
            style = self._context_menu_style_cache = self.get_context_menu_style() if hasattr(self, 'get_context_menu_style') else {
                'hover_text_style': 'bold white',
                'hover_bg_color': 'blue',
                'danger_color': 'red',
                'disabled_color': 'dim'
            }

        if is_selected:
            # Add background color for better visibility
            hover_style = style.get('hover_text_style', 'bold white')
            hover_bg = style.get('hover_bg_color', 'blue')
            text = f"[{hover_style} on {hover_bg}]{text}[/{hover_style} on {hover_bg}]"
        else:
            # Apply normal styling
            if item.get('danger'):
                danger_color = style.get('danger_color', 'red')
                text = f"[{danger_color}]{text}[/{danger_color}]"
            elif not item.get('enabled', True):
                disabled_color = style.get('disabled_color', 'dim')
                text = f"[{disabled_color}]{text}[/{disabled_color}]"

        return text

# ==============================================================================
# CONTEXT MENU HELPER FUNCTIONS
# ==============================================================================


def create_context_menu_actions(widget_id: str, widget_type: str) -> List[Dict]:
    """
    Create standard context menu items based on widget type.

    Args:
        widget_id: ID of the target widget (or None for background)
        widget_type: Type of the widget

    Returns:
        List of menu item dictionaries
    """
    # Special case for background/empty space
    if widget_id is None or widget_type == 'background':
        return [
            {
                'id': 'create_widget',
                'label': 'Create Widget',
                'icon': '➕',
                'action': Action('CREATE_WIDGET', {'x': 0, 'y': 0}),  # Position will be updated
            },
            {
                'id': 'paste',
                'label': 'Paste',
                'icon': '📋',
                'action': Action('PASTE_WIDGET'),
                'enabled': False,  # Could check clipboard state
            },
            {
                'divider': True
            },
            {
                'id': 'refresh',
                'label': 'Refresh',
                'icon': '🔄',
                'action': Action('REFRESH_UI'),
            },
            {
                'id': 'app_settings',
                'label': 'Settings',
                'icon': '⚙️',
                'action': Action('SHOW_SETTINGS'),
            }
        ]

    # Standard widget actions
    base_actions = [
        {
            'id': 'inspect',
            'label': 'Inspect Widget',
            'icon': '🔍',
            'action': Action('INSPECT_WIDGET', widget_id),
        },
        {
            'id': 'copy_id',
            'label': 'Copy Widget ID',
            'icon': '📋',
            'action': Action('COPY_TO_CLIPBOARD', widget_id),
        },
        {
            'divider': True
        }
    ]

    # Add type-specific actions
    if widget_type == 'panel':
        base_actions.extend([
            {
                'id': 'edit_content',
                'label': 'Edit Content',
                'icon': '✏️',
                'action': Action('EDIT_WIDGET_CONTENT', widget_id),
            },
            {
                'id': 'change_color',
                'label': 'Change Color',
                'icon': '🎨',
                'action': Action('CHANGE_WIDGET_COLOR', widget_id),
            }
        ])
    elif widget_type == 'plot_direct':
        base_actions.extend([
            {
                'id': 'export_data',
                'label': 'Export Chart Data',
                'icon': '💾',
                'action': Action('EXPORT_CHART', widget_id),
            },
            {
                'id': 'refresh_data',
                'label': 'Refresh Data',
                'icon': '🔄',
                'action': Action('REFRESH_CHART', widget_id),
            }
        ])

    # Common actions at the end
    base_actions.extend([
        {
            'divider': True
        },
        {
            'id': 'delete',
            'label': 'Delete',
            'icon': '🗑️',
            'action': Action('DELETE_WIDGET', widget_id),
            'danger': True
        }
    ])

    return base_actions

    def create_dynamic_widget(self, widget_type: str, base_id: str,
                              state_key: str, transform: Callable[[Any], Dict]) -> Optional[Dict]:
        """
        Create a widget that updates based on state values.

        Args:
            widget_type: Type of widget to create
            base_id: Base widget ID
            state_key: Key in state to monitor
            transform: Function to transform state value to widget properties

        Returns:
            Widget definition or None
        """
        value = self.state.get(state_key)
        if value is None:
            return None

        widget_def = transform(value)
        widget_def['id'] = base_id
        widget_def['type'] = widget_type

        return widget_def

    def create_performance_widget(self, widget_id: str, x: int, y: int,
                                  width: int = 30, height: int = 10) -> Dict:
        """
        Create a widget that automatically adapts to performance.

        Args:
            widget_id: Widget ID
            x, y: Position
            width, height: Base dimensions

        Returns:
            Widget definition with dynamic properties
        """
        frame_time = self.state.get('frame_time', 0)
        history = self.state.get('frametime_history', [])

        # Get adaptive color
        color = self.get_performance_color(frame_time, history)

        # Calculate dynamic properties based on performance
        if history and len(history) >= 10:
            sorted_history = sorted(history)
            p50 = sorted_history[len(sorted_history) // 2]
            factor = min(1.0, abs(frame_time - p50) / p50 if p50 > 0 else 0)
        else:
            factor = 0.0

        return {
            'id': widget_id,
            'type': 'panel',
            'title': 'Performance',
            'x': x,
            'y': y,
            'width': self.calculate_dynamic_property(width, factor, 0.2),
            'height': self.calculate_dynamic_property(height, factor, 0.2),
            'blend_opacity': 0.4 + (0.4 * factor),
            'css_merge': {
                'color': color,
                'text_style': 'bold' if factor > 0.5 else ''
            }
        }

    def create_animated_widget(self, widget_id: str, animation_type: str,
                               base_x: int, base_y: int, **kwargs) -> Dict:
        """
        Create a widget with built-in animation based on time/counters.

        Args:
            widget_id: Widget ID
            animation_type: 'pulse', 'breathe', 'slide', 'orbit'
            base_x, base_y: Base position
            **kwargs: Additional widget properties

        Returns:
            Widget definition with animated position
        """
        counter = self.state.get('counter', 0)
        time_factor = counter * 0.1  # Slow oscillation

        if animation_type == 'pulse':
            # Circular motion
            radius = kwargs.pop('radius', 3)
            x_offset = int(math.sin(time_factor) * radius)
            y_offset = int(math.cos(time_factor * 1.3) * radius * 0.5)
            x = base_x + x_offset
            y = base_y + y_offset

        elif animation_type == 'breathe':
            # Size changes
            x = base_x
            y = base_y
            base_width = kwargs.get('width', 30)
            base_height = kwargs.get('height', 10)
            scale = 1.0 + (math.sin(time_factor) * 0.2)
            kwargs['width'] = int(base_width * scale)
            kwargs['height'] = int(base_height * scale)

        elif animation_type == 'slide':
            # Horizontal sliding
            amplitude = kwargs.pop('amplitude', 10)
            x = base_x + int(math.sin(time_factor) * amplitude)
            y = base_y

        elif animation_type == 'orbit':
            # Elliptical orbit
            radius_x = kwargs.pop('radius_x', 5)
            radius_y = kwargs.pop('radius_y', 3)
            x = base_x + int(math.cos(time_factor) * radius_x)
            y = base_y + int(math.sin(time_factor) * radius_y)

        else:
            x = base_x
            y = base_y

        widget_def = {
            'id': widget_id,
            'type': kwargs.pop('type', 'panel'),
            'x': x,
            'y': y
        }
        widget_def.update(kwargs)

        return widget_def

    # ===========================================================================
    # UTILITY METHODS
    # ===========================================================================

    def get_widget(self, widget_id: str) -> Optional[Union[AbsoluteGlassWidget, AbsoluteGlassPanel]]:
        """
        Get a mounted widget by ID.

        Args:
            widget_id: Widget ID

        Returns:
            Widget instance or None
        """
        return self._mounted_widgets.get(widget_id)

    def update_widget_content(self, widget_id: str, content: Union[str, List[str]]):
        """
        Quick helper to update just widget content.

        Args:
            widget_id: Widget ID
            content: New content
        """
        widget = self._mounted_widgets.get(widget_id)
        if widget:
            if isinstance(content, list):
                widget.content = '\n'.join(content)
            else:
                widget.content = content
            widget.refresh()

    # ===========================================================================
    # FOCUS MANAGEMENT
    # ===========================================================================

    def set_widget_focus(self, widget_id: Optional[str]):
        """
        Centralized focus management - ensures only one widget has focus at a time.

        Args:
            widget_id: Widget to focus, or None to clear focus
        """
        # Blur previously focused widget
        if self._focused_widget_id and self._focused_widget_id != widget_id:
            old_widget = self._mounted_widgets.get(self._focused_widget_id)
            if old_widget:
                # Handle different widget types
                if hasattr(old_widget, 'set_focus'):
                    old_widget.set_focus(False)
                elif isinstance(old_widget, GlassNativeContainer):
                    native_widget = old_widget.get_native_widget()
                    if native_widget and hasattr(native_widget, 'blur'):
                        native_widget.blur()

        # Update focus tracking
        self._focused_widget_id = widget_id

        # Focus new widget
        if widget_id and widget_id in self._mounted_widgets:
            widget = self._mounted_widgets[widget_id]
            if widget:
                # Handle different widget types
                if hasattr(widget, 'set_focus'):
                    widget.set_focus(True)
                elif isinstance(widget, GlassNativeContainer):
                    native_widget = widget.get_native_widget()
                    if native_widget:
                        native_widget.focus()

    def focus_widget(self, widget_id: str):
        """
        Give focus to a widget (for backward compatibility).

        Args:
            widget_id: Widget to focus
        """
        # Store previous focus
        if self._focused_widget_id and self._focused_widget_id != widget_id:
            self._focus_stack.append(self._focused_widget_id)

        # Use centralized method
        self.set_widget_focus(widget_id)

    def blur_current_widget(self):
        """Remove focus from current widget."""
        if self._focused_widget_id:
            widget = self._mounted_widgets.get(self._focused_widget_id)
            if widget and isinstance(widget, GlassNativeContainer):
                native_widget = widget.get_native_widget()
                if native_widget and hasattr(native_widget, 'blur'):
                    native_widget.blur()

        # Pop from focus stack
        if self._focus_stack:
            self._focused_widget_id = self._focus_stack.pop()
        else:
            self._focused_widget_id = None

    def get_focused_widget_id(self) -> Optional[str]:
        """Get currently focused widget ID."""
        return self._focused_widget_id

    def is_widget_focused(self, widget_id: str) -> bool:
        """Check if a widget has focus."""
        return self._focused_widget_id == widget_id

    def get_dynamic_colors(self) -> Dict[str, str]:
        """
        Get dynamic colors extracted from the background image.

        Returns:
            Dict with keys like 'dominant', 'complementary', etc.
            Apps can use these for responsive theming.
            Always returns a valid dict with fallback colors if extraction fails.
        """
        # Default fallback colors
        fallback_colors = {
            'dominant': '#4a90e2',
            'complementary': '#e24a4a',
            'primary': '#4a90e2',
            'secondary': '#7ed321',
            'accent': '#f5a623',
            'light': '#7da5e8',
            'dark': '#356ba6',
            'analogous_1': '#4a90e2',
            'analogous_2': '#4ae290',
            'analogous_3': '#904ae2',
            'triadic_1': '#4a90e2',
            'triadic_2': '#e24a90',
            'triadic_3': '#90e24a',
        }

        try:
            # Try to get palette from state
            if not hasattr(self, 'state') or not self.state:
                return fallback_colors

            # Get palette from parent class (where it's actually extracted)
            palette = getattr(self, 'color_palette', {})

            if not palette:
                return fallback_colors

            # Create convenient aliases for common use cases
            return {
                'dominant': palette.get('dominant', fallback_colors['dominant']),
                'complementary': palette.get('complementary', fallback_colors['complementary']),
                'primary': palette['palette'][0] if palette.get('palette') and len(palette['palette']) > 0 else fallback_colors['primary'],
                'secondary': palette['palette'][1] if palette.get('palette') and len(palette['palette']) > 1 else fallback_colors['secondary'],
                'accent': palette['palette'][2] if palette.get('palette') and len(palette['palette']) > 2 else fallback_colors['accent'],
                'light': palette['light_variants'][0] if palette.get('light_variants') and len(palette['light_variants']) > 0 else fallback_colors['light'],
                'dark': palette['dark_variants'][0] if palette.get('dark_variants') and len(palette['dark_variants']) > 0 else fallback_colors['dark'],
                'analogous_1': palette['analogous'][0] if palette.get('analogous') and len(palette['analogous']) > 0 else fallback_colors['analogous_1'],
                'analogous_2': palette['analogous'][1] if palette.get('analogous') and len(palette['analogous']) > 1 else fallback_colors['analogous_2'],
                'analogous_3': palette['analogous'][2] if palette.get('analogous') and len(palette['analogous']) > 2 else fallback_colors['analogous_3'],
                'triadic_1': palette['triadic'][0] if palette.get('triadic') and len(palette['triadic']) > 0 else fallback_colors['triadic_1'],
                'triadic_2': palette['triadic'][1] if palette.get('triadic') and len(palette['triadic']) > 1 else fallback_colors['triadic_2'],
                'triadic_3': palette['triadic'][2] if palette.get('triadic') and len(palette['triadic']) > 2 else fallback_colors['triadic_3'],
            }
        except Exception as e:
            # If anything goes wrong, return fallback colors
            return fallback_colors

    def set_fixed_fps_mode(self, enabled: bool, target_fps: int = 60):
        """
        Enable or disable fixed frame rate mode.

        When enabled, the app will render at a consistent frame rate
        regardless of whether anything has changed. This uses more CPU
        but provides smoother animations and consistent performance.

        Args:
            enabled: True to enable fixed FPS mode
            target_fps: Target frames per second (default 60, max 120)
        """
        self._fixed_fps_mode = enabled
        self._target_fps = min(120, max(1, target_fps))  # Clamp between 1-120

        if enabled:
            self._start_fixed_fps_mode()
        else:
            self._stop_fixed_fps_mode()

    def _start_fixed_fps_mode(self):
        """Start the fixed frame rate timer"""
        if self._frame_timer:
            self._frame_timer.stop()

        # Calculate interval in seconds
        interval = 1.0 / self._target_fps

        # Create a timer that forces renders
        self._frame_timer = self.set_interval(interval, self._fixed_fps_render)

        self.log(f"Fixed FPS mode enabled: {self._target_fps} FPS (interval: {interval * 1000:.1f}ms)")
        self.state['_fixed_fps_mode'] = True
        self.state['_target_fps'] = self._target_fps

    def _stop_fixed_fps_mode(self):
        """Stop the fixed frame rate timer"""
        if self._frame_timer:
            self._frame_timer.stop()
            self._frame_timer = None

        self.log("Fixed FPS mode disabled")
        self.state['_fixed_fps_mode'] = False

    def _fixed_fps_render(self):
        """Force a render for fixed FPS mode"""
        # Call animation update if the app has one
        if hasattr(self, 'update_animations'):
            self.update_animations()

        # If there are dirty widgets, do a targeted render
        if self._dom_dirty:
            self.render_ui()
        else:
            # Otherwise just refresh the screen
            if hasattr(self, 'screen') and self.screen:
                # Mark screen as needing refresh
                self.screen._dirty_regions.clear()
                self.screen._dirty_regions.add(self.screen.region)

            # Just refresh existing widgets without reconciliation
            for widget in self.query("*"):
                widget.refresh()

            # Update frame tracking
            self._track_frame_time()

    def mark_widget_dirty(self, widget_id: str):
        """Mark a widget as needing update in the next render cycle"""
        self._dom_dirty.add(widget_id)

    def force_widget_update(self, widget_id: str):
        """Force a widget to update even if virtual DOM thinks it's unchanged"""
        self.mark_widget_dirty(widget_id)
        # Also mark in virtual DOM as needing update
        if widget_id in self._virtual_dom:
            # Add a timestamp to force change detection
            self._virtual_dom[widget_id]['_force_update'] = time.time()

    def update_widget_property(self, widget_id: str, prop: str, value: Any):
        """Update a single widget property and mark it dirty"""
        if widget_id in self._virtual_dom:
            self._virtual_dom[widget_id][prop] = value
            self.mark_widget_dirty(widget_id)

    def update_widget_position(self, widget_id: str, x: int, y: int):
        """Update a widget's position without full reconciliation"""
        # Update virtual DOM
        if widget_id in self._virtual_dom:
            self._virtual_dom[widget_id]['x'] = x
            self._virtual_dom[widget_id]['y'] = y
            self.mark_widget_dirty(widget_id)

        # For immediate feedback, also update the actual widget
        widget = self._mounted_widgets.get(widget_id)
        if widget and hasattr(widget, 'abs_x'):
            widget.abs_x = x
            widget.abs_y = y
            # Calculate actual screen position
            if hasattr(widget, '_calculate_actual_position'):
                widget._calculate_actual_position()
            widget.refresh()

    # ===========================================================================
    # LIVE WIDGET UPDATES - Direct terminal updates
    # ===========================================================================

    def update_live_widget(self, widget_id: str, **data):
        """Update a live widget immediately without reconciliation"""
        widget = self._mounted_widgets.get(widget_id)
        if not widget or not hasattr(widget, '_live_mode'):
            return False

        # Handle specific live widget types
        if isinstance(widget, LiveFPSCounter):
            fps = data.get('fps', 0)
            frame_time = data.get('frame_time', 0)
            widget.update_fps(fps, frame_time)
            return True
        elif isinstance(widget, LiveDataGlassWidget):
            content = data.get('content', '')
            widget.update_live(content)
            return True

        return False

    def update_live_fps(self, widget_id: str, fps: float, frame_time: float):
        """Convenience method to update live FPS counter"""
        return self.update_live_widget(widget_id, fps=fps, frame_time=frame_time)

    def update_live_content(self, widget_id: str, content: str):
        """Convenience method to update live content widget"""
        return self.update_live_widget(widget_id, content=content)

    async def on_unmount(self):
        """Clean up on unmount."""
        # Stop timers
        try:
            if hasattr(self, '_perf_timer'):
                self._perf_timer.stop()
            if hasattr(self, '_frame_timer') and self._frame_timer:
                self._frame_timer.stop()
        except Exception:
            # Ignore timer cleanup errors
            pass


# ==============================================================================
# HELPER COMPONENTS
# ==============================================================================

def compute_data_hash(data: Any) -> str:
    """
    Compute a hash for plot data to efficiently detect changes.

    Args:
        data: Data to hash (list, dict, etc)

    Returns:
        Hash string
    """
    if isinstance(data, (list, tuple)):
        # For lists/tuples, hash the length and first/last few elements
        if len(data) == 0:
            return "empty"
        elif len(data) < 10:
            # Small dataset - hash all
            return hashlib.md5(str(data).encode()).hexdigest()[:8]
        else:
            # Large dataset - hash length + sample
            sample = [len(data), data[0], data[1], data[-2], data[-1]]
            # Also sample middle
            mid = len(data) // 2
            sample.extend([data[mid - 1], data[mid], data[mid + 1]])
            return hashlib.md5(str(sample).encode()).hexdigest()[:8]
    else:
        # For other types, just hash the string representation
        return hashlib.md5(str(data).encode()).hexdigest()[:8]


def create_modal(state: Dict, modal_key: str = 'modal') -> Optional[Dict]:
    """
    Helper to create a modal widget from state.

    Args:
        state: Application state
        modal_key: Key in state containing modal data

    Returns:
        Widget definition or None
    """
    modal = state.get(modal_key)
    if not modal:
        return None

    content = modal.get('content', [])
    if isinstance(content, list):
        content = content + ['', '─' * 40, 'Press ESC to close']
    else:
        content = [content, '', '─' * 40, 'Press ESC to close']

    height = min(len(content) + 5, 25)

    return {
        'id': 'modal',
        'type': 'panel',
        'title': modal.get('title', 'Modal'),
        'content': content,
        'x': 0, 'y': 0,
        'width': modal.get('width', '60%'),
        'height': height,
        'sticky_x': 'center',
        'sticky_y': 'center',
        'overlay_color': modal.get('color', 'red'),
        'blend_opacity': modal.get('opacity', 0.9),
        'z_index': 1000
    }
