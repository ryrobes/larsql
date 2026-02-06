"""
Looking Glass Reactive - Terminal UI Framework

A high-performance terminal UI framework with glass morphism effects
and Redux-style state management.

Core exports:
    ReactiveGlassApp - Base class for reactive TUI apps
    Action - Redux-style action for state updates
"""

from .looking_glass_reactive import ReactiveGlassApp, Action

__all__ = ['ReactiveGlassApp', 'Action']
