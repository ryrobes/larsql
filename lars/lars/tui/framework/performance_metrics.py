#!/usr/bin/env python3
"""
Performance Metrics Module for Looking Glass
============================================

Provides performance tracking and monitoring capabilities for Looking Glass applications.
Tracks frame times, FPS, CPU usage, memory usage, widget updates, and more.
"""

from dataclasses import dataclass
from collections import deque
from typing import Dict, List, Optional
import hashlib
import json


@dataclass
class PerformanceMetrics:
    """Container for performance metrics with history"""
    frame_times: deque  # ms
    fps_values: deque
    cpu_usage: deque  # percentage
    memory_usage: deque  # MB
    widget_counts: deque
    dom_changes: deque  # (added, removed, updated)
    reconcile_times: deque  # ms
    reconcile_counts: deque  # number of reconciliations
    ansi_parse_times: deque  # ms
    widget_update_counts: dict  # widget_id -> update count
    timestamps: deque  # For x-axis

    def __init__(self, max_history: int = 300):
        """Initialize with max history length (5 minutes at 60fps)"""
        self.frame_times = deque(maxlen=max_history)
        self.fps_values = deque(maxlen=max_history)
        self.cpu_usage = deque(maxlen=max_history)
        self.memory_usage = deque(maxlen=max_history)
        self.widget_counts = deque(maxlen=max_history)
        self.dom_changes = deque(maxlen=max_history)
        self.reconcile_times = deque(maxlen=max_history)
        self.reconcile_counts = deque(maxlen=max_history)
        self.ansi_parse_times = deque(maxlen=max_history)
        self.widget_update_counts = {}
        self.timestamps = deque(maxlen=max_history)

        # For 10-second FPS averages
        self.fps_10s_averages = deque(maxlen=100)  # Store last 100 x 10-second averages (~16.7 minutes)
        self.fps_values_processed = 0  # Track how many FPS values have been processed into 10s chunks

        # For audio-style decay effect in progress bars
        self.decay_history = {
            'frame_time': deque(maxlen=20),  # Last 20 values for smooth decay
            'cpu_usage': deque(maxlen=20),
            'memory_usage': deque(maxlen=20),
            'fps': deque(maxlen=20),
        }


def compute_data_hash(data) -> str:
    """Compute hash of data for plot caching"""
    return hashlib.md5(json.dumps(data, sort_keys=True).encode()).hexdigest()