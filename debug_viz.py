#!/usr/bin/env python3
"""
Debug script to test sub-cascade loading.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'windlass'))

from windlass.visualizer import load_sub_cascade_mermaid
from windlass.config import get_config

def test_load():
    """Test loading sub-cascade mermaid."""

    session_id = "test_sub_cascade_viz"

    print("Testing load_sub_cascade_mermaid():")
    print()

    for idx in range(3):
        sub_session_id = f"{session_id}_sub_{idx}"
        print(f"Attempting to load: {sub_session_id}")

        result = load_sub_cascade_mermaid(sub_session_id)

        if result:
            print(f"✓ Loaded {len(result)} chars")
            print("First 200 chars:")
            print(result[:200])
        else:
            print("❌ Failed to load")

        print()

if __name__ == "__main__":
    test_load()
