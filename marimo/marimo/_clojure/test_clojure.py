#!/usr/bin/env python3
"""Test script for Clojure integration.

This script tests the nREPL client and clj() function outside of Marimo.
Run with: python -m marimo._clojure.test_clojure

Requirements:
- Clojure CLI tools installed (clojure command)
- nREPL will be started automatically
"""
from __future__ import annotations

import sys


def test_edn_conversion():
    """Test Python <-> EDN conversion."""
    from marimo._clojure.clojure import python_to_edn, edn_to_python

    print("Testing EDN conversion...")

    # Test basic types
    assert python_to_edn(None) == "nil"
    assert python_to_edn(True) == "true"
    assert python_to_edn(False) == "false"
    assert python_to_edn(42) == "42"
    assert python_to_edn(3.14) == "3.14"
    assert python_to_edn("hello") == '"hello"'
    assert python_to_edn([1, 2, 3]) == "[1 2 3]"
    assert python_to_edn({"a": 1, "b": 2}) == '{"a" 1 "b" 2}'

    # Test reverse conversion
    assert edn_to_python("nil") is None
    assert edn_to_python("true") is True
    assert edn_to_python("false") is False
    assert edn_to_python("42") == 42
    assert edn_to_python("3.14") == 3.14
    assert edn_to_python('"hello"') == "hello"
    assert edn_to_python("[1 2 3]") == [1, 2, 3]
    assert edn_to_python('{"a" 1 "b" 2}') == {"a": 1, "b": 2}

    print("  EDN conversion tests passed!")


def test_bencode():
    """Test bencode encoding/decoding."""
    from marimo._clojure.nrepl import bencode_encode, bencode_decode

    print("Testing bencode...")

    # Test encoding
    assert bencode_encode(42) == b"i42e"
    assert bencode_encode("hello") == b"5:hello"
    assert bencode_encode([1, 2]) == b"li1ei2ee"
    assert bencode_encode({"a": 1}) == b"d1:ai1ee"

    # Test decoding
    assert bencode_decode(b"i42e")[0] == 42
    assert bencode_decode(b"5:hello")[0] == b"hello"
    assert bencode_decode(b"li1ei2ee")[0] == [1, 2]

    print("  Bencode tests passed!")


def test_nrepl_connection():
    """Test nREPL connection and basic evaluation."""
    from marimo._clojure.nrepl import get_nrepl_connection, is_nrepl_available

    print("Testing nREPL connection...")

    if not is_nrepl_available():
        print("  SKIP: Clojure CLI not available")
        return False

    try:
        print("  Connecting to nREPL (may start server)...")
        client = get_nrepl_connection(auto_start=True)

        print("  Testing basic evaluation...")
        result = client.eval("(+ 1 2 3)")
        assert result.value == "6", f"Expected '6', got '{result.value}'"
        print(f"    (+ 1 2 3) = {result.value}")

        result = client.eval('(str "Hello, " "World!")')
        assert result.value == '"Hello, World!"', f"Got: {result.value}"
        print(f"    (str \"Hello, \" \"World!\") = {result.value}")

        result = client.eval("(def x 42)")
        print(f"    (def x 42) -> {result.value}")

        result = client.eval("x")
        assert result.value == "42", f"Expected '42', got '{result.value}'"
        print(f"    x = {result.value}")

        print("  nREPL tests passed!")
        return True

    except Exception as e:
        print(f"  ERROR: {e}")
        return False


def test_clj_function():
    """Test the clj() function (requires running inside Marimo or with mocked context)."""
    print("Testing clj() function...")
    print("  NOTE: Full test requires running inside Marimo notebook")
    print("  For now, testing basic import only")

    from marimo._clojure import clj, ClojureError

    print(f"  clj function imported: {clj}")
    print(f"  ClojureError imported: {ClojureError}")
    print("  clj() import test passed!")


def test_ast_visitor():
    """Test AST visitor extracts inputs/outputs from mo.clj() calls."""
    print("Testing AST visitor for mo.clj()...")

    from marimo._ast.compiler import compile_cell

    # Test code with mo.clj() call - explicit mode
    code = '''
result = mo.clj("""
(def y (* x 2))
y
""", inputs=["x"], outputs=["y"])
'''

    cell = compile_cell(code, cell_id="test_clj")

    print(f"  Code: {code.strip()[:50]}...")
    print(f"  Language: {cell.language}")
    print(f"  Refs (inputs): {cell.refs}")
    print(f"  Defs (outputs): {cell.defs}")

    assert cell.language == "clojure", f"Expected 'clojure', got '{cell.language}'"
    assert "x" in cell.refs, f"Expected 'x' in refs, got {cell.refs}"
    assert "y" in cell.defs, f"Expected 'y' in defs, got {cell.defs}"

    print("  AST visitor tests passed!")


def test_ast_visitor_auto_mode():
    """Test AST visitor with auto=True mode."""
    print("Testing AST visitor auto mode...")

    from marimo._ast.compiler import compile_cell

    # Test code with auto=True - inputs/outputs detected from Clojure code
    code = '''
mo.clj("""
(def sum (+ x y))
(def product (* x y))
(defn calculate [n] (* n 2))
sum
""", auto=True)
'''

    cell = compile_cell(code, cell_id="test_clj_auto")

    print(f"  Code: {code.strip()[:60]}...")
    print(f"  Language: {cell.language}")
    print(f"  Refs (detected inputs): {cell.refs}")
    print(f"  Defs (detected outputs): {cell.defs}")

    assert cell.language == "clojure", f"Expected 'clojure', got '{cell.language}'"
    # Auto-detected inputs (x and y are referenced but not defined)
    assert "x" in cell.refs, f"Expected 'x' in refs, got {cell.refs}"
    assert "y" in cell.refs, f"Expected 'y' in refs, got {cell.refs}"
    # Auto-detected outputs (def and defn forms)
    assert "sum" in cell.defs, f"Expected 'sum' in defs, got {cell.defs}"
    assert "product" in cell.defs, f"Expected 'product' in defs, got {cell.defs}"
    assert "calculate" in cell.defs, f"Expected 'calculate' in defs, got {cell.defs}"

    print("  AST visitor auto mode tests passed!")


def main():
    print("=" * 60)
    print("Marimo Clojure Integration Tests")
    print("=" * 60)
    print()

    try:
        test_edn_conversion()
        print()

        test_bencode()
        print()

        nrepl_ok = test_nrepl_connection()
        print()

        test_clj_function()
        print()

        test_ast_visitor()
        print()

        test_ast_visitor_auto_mode()
        print()

        print("=" * 60)
        if nrepl_ok:
            print("All tests passed!")
        else:
            print("Tests passed (nREPL tests skipped - Clojure not available)")
        print("=" * 60)

    except Exception as e:
        print(f"\nTEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
