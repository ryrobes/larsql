#!/usr/bin/env python3
"""
Glass Native Container - Wraps native Textual widgets in Looking Glass
====================================================================

This module provides a container that allows native Textual widgets to
participate in the Looking Glass reactive system with glass morphism effects.
"""

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Button, Input, Label, Static, TextArea, Switch, ProgressBar
from textual.containers import Container
from textual.events import Click
from textual import on
from .looking_glass import AbsoluteGlassPanel
from typing import Dict, Any, Optional, Type, Union, Callable
import importlib


class GlassNativeContainer(AbsoluteGlassPanel):
    """
    Container that wraps native Textual widgets with glass morphism effects.
    
    This allows native widgets to:
    - Participate in the glass morphism rendering
    - Use absolute positioning
    - Be managed by the reactive system
    """
    
    def __init__(
        self,
        widget_class: Union[str, Type[Widget]],
        widget_props: Optional[Dict[str, Any]] = None,
        on_change: Optional[Callable] = None,
        *args,
        **kwargs
    ):
        """
        Initialize the container with a native widget.
        
        Args:
            widget_class: Either a widget class or string name (e.g., 'Button')
            widget_props: Properties to pass to the native widget
            on_change: Callback for when widget value changes
            *args, **kwargs: Passed to AbsoluteGlassPanel
        """
        # Store widget info
        self._widget_class = widget_class
        self._widget_props = widget_props or {}
        self._native_widget = None
        self._on_change = on_change
        
        # Extract title from kwargs if not provided
        if 'title' not in kwargs and isinstance(widget_class, str):
            # Use widget class name as default title
            kwargs['title'] = f'{widget_class} Widget'
        
        # Set empty content since native widget will render
        kwargs['content'] = ''
        
        # Initialize parent
        super().__init__(*args, **kwargs)
        
    def compose(self) -> ComposeResult:
        """Compose the native widget inside the container."""
        # Get widget class
        if isinstance(self._widget_class, str):
            widget_cls = self._get_widget_class(self._widget_class)
        else:
            widget_cls = self._widget_class
            
        # Create the native widget with provided properties
        self._native_widget = widget_cls(**self._widget_props)
        
        # Give widgets unique IDs to prevent recreation
        if not hasattr(self._native_widget, 'id') or not self._native_widget.id:
            self._native_widget.id = f"native_{self.id}_{widget_cls.__name__}"
        
        # Apply styling to make it fill the container
        # Special handling for different widget types
        if isinstance(self._native_widget, Input):
            # Input needs special care to work properly
            if self.border:
                self._native_widget.styles.width = "100%"
                self._native_widget.styles.height = 3  # Fixed height for input
                self._native_widget.styles.margin = (1, 1, 0, 1)
            else:
                self._native_widget.styles.width = "100%"
                self._native_widget.styles.height = 3
                self._native_widget.styles.margin = 0
        elif isinstance(self._native_widget, TextArea):
            # TextArea fills available space
            if self.border:
                self._native_widget.styles.width = "100%"
                self._native_widget.styles.height = "100%"
                self._native_widget.styles.margin = (1, 1, 1, 1)
            else:
                self._native_widget.styles.width = "100%"
                self._native_widget.styles.height = "100%"
                self._native_widget.styles.margin = 0
        else:
            # Other widgets
            if self.border:
                # With border, we need to account for 2 chars width and 2 chars height
                self._native_widget.styles.width = "100%"
                self._native_widget.styles.height = "100%"
                self._native_widget.styles.margin = (1, 1, 1, 1)  # top, right, bottom, left
            else:
                self._native_widget.styles.width = "100%"
                self._native_widget.styles.height = "100%"
                self._native_widget.styles.margin = 0
        
        self._native_widget.styles.padding = 0
        
        yield self._native_widget
    
    def _get_widget_class(self, class_name: str) -> Type[Widget]:
        """Get widget class from string name."""
        # Map of common widget names to classes
        widget_map = {
            'Button': Button,
            'Input': Input,
            'Label': Label,
            'Static': Static,
            'TextArea': TextArea,
            'Switch': Switch,
            'ProgressBar': ProgressBar,
        }
        
        if class_name in widget_map:
            return widget_map[class_name]
        
        # Try to import from textual.widgets
        try:
            module = importlib.import_module('textual.widgets')
            return getattr(module, class_name)
        except (ImportError, AttributeError):
            raise ValueError(f"Unknown widget class: {class_name}")
    
    def update_content(self, content: Any):
        """Update the native widget's content if applicable."""
        if not self._native_widget:
            return
            
        # Different widgets have different ways to update content
        if isinstance(self._native_widget, (Label, Static)):
            self._native_widget.update(content)
        elif isinstance(self._native_widget, Button):
            self._native_widget.label = content
        elif isinstance(self._native_widget, Input):
            # For Input widgets, only update if the value actually changed
            # to avoid disrupting user typing
            if self._native_widget.value != content:
                # Store cursor position
                cursor_position = getattr(self._native_widget, 'cursor_position', 0)
                # Update value
                self._native_widget.value = content
                # Try to restore cursor position
                if hasattr(self._native_widget, 'cursor_position'):
                    self._native_widget.cursor_position = min(cursor_position, len(content))
        elif isinstance(self._native_widget, TextArea):
            # For TextArea, don't update content to avoid cursor issues
            # TextArea should manage its own state
            pass
        elif isinstance(self._native_widget, ProgressBar):
            if isinstance(content, (int, float)):
                self._native_widget.update(progress=content)
    
    def update_props(self, props: Dict[str, Any]):
        """Update native widget properties."""
        if not self._native_widget:
            return
            
        for key, value in props.items():
            if hasattr(self._native_widget, key):
                setattr(self._native_widget, key, value)
    
    def get_native_widget(self) -> Optional[Widget]:
        """Get the wrapped native widget instance."""
        return self._native_widget
    
    def on_key(self, event):
        """Handle key events - check for ESC to release focus."""
        if event.key == "escape":
            # Blur the native widget if it has focus
            if self._native_widget and hasattr(self._native_widget, 'has_focus') and self._native_widget.has_focus:
                if hasattr(self._native_widget, 'blur'):
                    self._native_widget.blur()
                # Let parent know focus was released
                if self._on_change:
                    self._on_change('focus_released', None)
                # Stop event propagation
                event.stop()
                return
        
        # For TextArea, don't capture all keys - let some bubble up
        if isinstance(self._native_widget, TextArea) and event.key == "escape":
            event.stop()
            if hasattr(self.app, 'blur_current_widget'):
                self.app.blur_current_widget()
    
    # Event handlers for native widgets
    @on(Button.Pressed)
    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events."""
        if self._on_change and isinstance(self._native_widget, Button):
            self._on_change('button_pressed', event.button)
    
    @on(Input.Changed)
    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle input change events."""
        if self._on_change and isinstance(self._native_widget, Input):
            self._on_change('input_changed', event.value)
    
    @on(Switch.Changed)
    def on_switch_changed(self, event: Switch.Changed) -> None:
        """Handle switch toggle events."""
        if self._on_change and isinstance(self._native_widget, Switch):
            self._on_change('switch_changed', event.value)
    
    @on(TextArea.Changed)
    def on_textarea_changed(self, event: TextArea.Changed) -> None:
        """Handle textarea change events."""
        if self._on_change and isinstance(self._native_widget, TextArea):
            self._on_change('textarea_changed', event.text_area.text)