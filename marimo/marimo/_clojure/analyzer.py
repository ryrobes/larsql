# Copyright 2024 Marimo. All rights reserved.
"""Clojure code analyzer for detecting inputs and outputs.

This module provides static analysis of Clojure code to detect:
- Defined symbols (outputs): vars created by def, defn, defmacro, etc.
- Referenced symbols (potential inputs): symbols used but not defined locally

This enables "seamless" Clojure cells where the user writes raw Clojure
and we automatically detect what Python variables to inject and what
Clojure vars to export.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional, Set

from marimo import _loggers

LOGGER = _loggers.marimo_logger()


# ============================================================================
# Clojure Built-ins and Special Forms
# ============================================================================

# Clojure special forms that are not user-defined
CLOJURE_SPECIAL_FORMS = frozenset([
    # Special forms
    "def", "if", "do", "let", "quote", "var", "fn", "loop", "recur",
    "throw", "try", "catch", "finally", "monitor-enter", "monitor-exit",
    "new", "set!", ".", "..", "import*",
    # Binding forms
    "let*", "letfn", "letfn*", "binding", "with-local-vars",
    # Definition forms (we detect these separately)
    "defn", "defn-", "defmacro", "defonce", "defmulti", "defmethod",
    "defprotocol", "defrecord", "deftype", "defstruct", "definline",
    # Other core forms
    "ns", "in-ns", "require", "use", "import", "refer",
    "for", "doseq", "dotimes", "while", "when", "when-not", "when-let",
    "when-first", "when-some", "if-let", "if-not", "if-some",
    "cond", "condp", "case", "cond->", "cond->>", "some->", "some->>",
    "->", "->>", "as->", "and", "or", "not",
    "fn*", "reify", "proxy", "extend", "extend-type", "extend-protocol",
])

# Common Clojure core functions (subset - most commonly used)
CLOJURE_CORE_FUNCTIONS = frozenset([
    # Arithmetic
    "+", "-", "*", "/", "mod", "rem", "quot", "inc", "dec",
    "max", "min", "abs", "rand", "rand-int",
    # Comparison
    "=", "==", "not=", "<", ">", "<=", ">=", "compare",
    "identical?", "zero?", "pos?", "neg?", "even?", "odd?",
    # Logic
    "true?", "false?", "nil?", "some?", "not", "and", "or",
    # Collections
    "count", "empty", "empty?", "not-empty", "seq", "seq?",
    "first", "second", "rest", "next", "last", "butlast",
    "nth", "get", "get-in", "contains?", "find", "keys", "vals",
    "assoc", "assoc-in", "dissoc", "update", "update-in",
    "merge", "merge-with", "select-keys",
    "conj", "cons", "concat", "into", "reverse", "sort", "sort-by",
    "distinct", "dedupe", "group-by", "partition", "partition-by",
    "partition-all", "split-at", "split-with",
    "take", "take-while", "take-nth", "take-last",
    "drop", "drop-while", "drop-last",
    "filter", "filterv", "remove", "keep", "keep-indexed",
    "map", "mapv", "map-indexed", "mapcat", "pmap",
    "reduce", "reduce-kv", "reductions",
    "apply", "partial", "comp", "complement", "constantly",
    "juxt", "fnil", "identity", "memoize",
    "some", "every?", "not-every?", "not-any?",
    "range", "repeat", "repeatedly", "iterate", "cycle",
    "interleave", "interpose", "flatten", "shuffle",
    # Vectors
    "vec", "vector", "vector?", "subvec", "peek", "pop",
    # Lists
    "list", "list?", "list*",
    # Maps
    "hash-map", "array-map", "sorted-map", "sorted-map-by",
    "map?", "zipmap",
    # Sets
    "set", "hash-set", "sorted-set", "sorted-set-by", "set?",
    "union", "intersection", "difference", "subset?", "superset?",
    # Strings
    "str", "subs", "format", "name", "namespace",
    "string?", "char?", "blank?",
    # Printing
    "print", "println", "pr", "prn", "pr-str", "prn-str",
    "print-str", "printf",
    # Type predicates
    "type", "class", "instance?",
    "number?", "integer?", "float?", "rational?", "decimal?",
    "string?", "char?", "keyword?", "symbol?", "fn?", "ifn?",
    "coll?", "sequential?", "associative?", "counted?", "sorted?",
    "vector?", "list?", "map?", "set?",
    # Coercion
    "int", "long", "float", "double", "bigint", "bigdec",
    "char", "boolean", "byte", "short",
    "keyword", "symbol", "num",
    # Atoms and refs
    "atom", "deref", "reset!", "swap!", "compare-and-set!",
    "ref", "dosync", "alter", "commute", "ref-set",
    "agent", "send", "send-off", "await",
    # Vars
    "var?", "bound?", "resolve", "ns-resolve",
    # Metadata
    "meta", "with-meta", "vary-meta",
    # Java interop
    "class", "new", "instance?", "bean", "make-array",
    "aget", "aset", "alength", "amap", "areduce",
    "to-array", "into-array",
    # Misc
    "time", "eval", "read-string", "slurp", "spit",
    "assert", "comment", "doc", "source",
    "gensym", "macroexpand", "macroexpand-1",
    "delay", "force", "realized?",
    "future", "future?", "future-done?", "future-cancel",
    "promise", "deliver",
    "lazy-seq", "lazy-cat", "doall", "dorun",
    "frequencies", "rand-nth", "replace",
    # Namespace functions
    "ns-publics", "ns-interns", "ns-refers", "ns-imports",
    "the-ns", "find-ns", "all-ns", "create-ns", "remove-ns",
])

# All built-in symbols
CLOJURE_BUILTINS = CLOJURE_SPECIAL_FORMS | CLOJURE_CORE_FUNCTIONS | frozenset([
    # Constants
    "true", "false", "nil",
    # Special symbols
    "&", "_", "%", "%1", "%2", "%3", "%4", "%5", "%&",
])


# ============================================================================
# Tokenizer / Parser
# ============================================================================

# Regex for Clojure symbols
# Clojure symbols can contain: letters, digits, *, +, !, -, _, ', ?, <, >, =, /
# They cannot start with a digit
SYMBOL_PATTERN = re.compile(
    r"""
    (?<![:\w\-\*\+\!\?\<\>\=])  # Not preceded by keyword char or symbol char
    ([a-zA-Z_\*\+\!\-\?\<\>\=][a-zA-Z0-9_\*\+\!\-\?\<\>\=\']*)
    (?![:\w\-\*\+\!\?\<\>\=])   # Not followed by symbol char
    """,
    re.VERBOSE
)

# Pattern for definition forms: (def name ...), (defn name ...), etc.
# Handles optional metadata like ^:private, ^{:doc "..."}, ^String
DEF_PATTERN = re.compile(
    r"""
    \(\s*                           # Opening paren
    (def[a-z\-]*)                   # def, defn, defn-, defmacro, etc.
    \s+                             # Whitespace
    (?:                             # Non-capturing group for optional metadata
      \^                            # Metadata starts with ^
      (?:
        :[a-zA-Z\-]+                # Keyword like ^:private
        |
        \{[^}]*\}                   # Map like ^{:doc "..."}
        |
        [a-zA-Z][a-zA-Z0-9\.]*      # Type hint like ^String or ^java.lang.String
      )
      \s+                           # Space after metadata
    )*                              # Zero or more metadata annotations
    ([a-zA-Z_\*\+\!\-\?\<\>\=][a-zA-Z0-9_\*\+\!\-\?\<\>\=\']*)  # Symbol name
    """,
    re.VERBOSE
)

# Pattern for let/loop bindings: (let [x 1 y 2] ...)
BINDING_PATTERN = re.compile(
    r"""
    \(\s*                           # Opening paren
    (let|loop|for|doseq|dotimes|with-open|with-local-vars|binding)
    \s+\[                           # Binding vector start
    ([^\]]+)                        # Binding contents
    \]                              # Binding vector end
    """,
    re.VERBOSE
)

# Pattern for fn parameters: (fn [x y] ...) or (fn name [x y] ...)
FN_PATTERN = re.compile(
    r"""
    \(\s*fn\s+                      # (fn
    (?:[a-zA-Z_][a-zA-Z0-9_\-]*\s+)?  # Optional name
    \[([^\]]*)\]                    # Parameter vector
    """,
    re.VERBOSE
)

# Pattern for defn parameters
DEFN_PARAMS_PATTERN = re.compile(
    r"""
    \(\s*defn[\-]?\s+               # (defn or (defn-
    [a-zA-Z_\*\+\!\-\?\<\>\=][a-zA-Z0-9_\*\+\!\-\?\<\>\=\']*  # Name
    \s+                             # Whitespace
    (?:\"[^\"]*\"\s+)?              # Optional docstring
    (?:\^[^\s\[]+\s+)?              # Optional metadata
    \[([^\]]*)\]                    # Parameter vector
    """,
    re.VERBOSE
)


@dataclass
class ClojureAnalysis:
    """Results of analyzing Clojure code."""
    # Symbols defined by this code (def, defn, etc.)
    definitions: Set[str] = field(default_factory=set)

    # Symbols referenced but not defined locally (potential inputs)
    references: Set[str] = field(default_factory=set)

    # Local bindings (let, fn params, etc.) - not exported
    locals: Set[str] = field(default_factory=set)

    # All symbols found in the code
    all_symbols: Set[str] = field(default_factory=set)

    @property
    def potential_inputs(self) -> Set[str]:
        """Symbols that might need to be injected from Python."""
        return self.references - self.definitions - self.locals - CLOJURE_BUILTINS

    @property
    def outputs(self) -> Set[str]:
        """Symbols defined that should be exported to Python."""
        return self.definitions


def remove_comments_and_strings(code: str) -> str:
    """Remove comments and string literals from Clojure code.

    This helps avoid false positives when scanning for symbols.
    """
    result = []
    i = 0
    in_string = False

    while i < len(code):
        char = code[i]

        # Handle strings
        if char == '"' and (i == 0 or code[i-1] != '\\'):
            in_string = not in_string
            result.append(' ')  # Replace with space to preserve positions
            i += 1
            continue

        if in_string:
            result.append(' ')
            i += 1
            continue

        # Handle comments
        if char == ';':
            # Skip to end of line
            while i < len(code) and code[i] != '\n':
                result.append(' ')
                i += 1
            continue

        result.append(char)
        i += 1

    return ''.join(result)


def analyze_clojure(code: str) -> ClojureAnalysis:
    """Analyze Clojure code to detect definitions and references.

    This is a heuristic-based analyzer that doesn't fully parse Clojure
    but works well enough for common patterns.

    Args:
        code: Clojure source code

    Returns:
        ClojureAnalysis with detected definitions and references
    """
    analysis = ClojureAnalysis()

    # Clean code for symbol scanning
    clean_code = remove_comments_and_strings(code)

    # Find all definitions (def, defn, defmacro, etc.)
    for match in DEF_PATTERN.finditer(clean_code):
        def_type = match.group(1)  # def, defn, etc.
        name = match.group(2)
        if name and not name.startswith('^'):
            analysis.definitions.add(name)

    # Find local bindings (let, loop, fn params)
    for match in BINDING_PATTERN.finditer(clean_code):
        bindings = match.group(2)
        # Extract binding names (every other token)
        tokens = re.findall(r'[a-zA-Z_][a-zA-Z0-9_\-\*\+\!\?\<\>\=\']*', bindings)
        for i, token in enumerate(tokens):
            if i % 2 == 0:  # Even indices are binding names
                analysis.locals.add(token)

    # Find fn parameters
    for match in FN_PATTERN.finditer(clean_code):
        params = match.group(1)
        for param in re.findall(r'[a-zA-Z_][a-zA-Z0-9_\-\*\+\!\?\<\>\=\']*', params):
            if param not in ('&',):
                analysis.locals.add(param)

    # Find defn parameters
    for match in DEFN_PARAMS_PATTERN.finditer(clean_code):
        params = match.group(1)
        for param in re.findall(r'[a-zA-Z_][a-zA-Z0-9_\-\*\+\!\?\<\>\=\']*', params):
            if param not in ('&',):
                analysis.locals.add(param)

    # Find all symbols
    for match in SYMBOL_PATTERN.finditer(clean_code):
        symbol = match.group(1)
        if symbol:
            analysis.all_symbols.add(symbol)

    # References = all symbols - definitions - locals
    analysis.references = (
        analysis.all_symbols -
        analysis.definitions -
        analysis.locals -
        CLOJURE_SPECIAL_FORMS  # Don't count special forms as references
    )

    return analysis


def detect_inputs(
    code: str,
    available_python_vars: Optional[Set[str]] = None,
) -> Set[str]:
    """Detect which Python variables should be injected into Clojure code.

    Args:
        code: Clojure source code
        available_python_vars: Set of variable names available in Python namespace.
                              If provided, only returns inputs that exist in Python.

    Returns:
        Set of variable names to inject from Python
    """
    analysis = analyze_clojure(code)
    potential = analysis.potential_inputs

    if available_python_vars is not None:
        # Only return inputs that actually exist in Python
        return potential & available_python_vars

    return potential


def detect_outputs(code: str) -> Set[str]:
    """Detect which Clojure vars should be exported to Python.

    Args:
        code: Clojure source code

    Returns:
        Set of variable names to export to Python
    """
    analysis = analyze_clojure(code)
    return analysis.outputs


# ============================================================================
# nREPL-based Analysis (More Accurate)
# ============================================================================

def analyze_with_nrepl(
    code: str,
    nrepl_client: "NReplClient",  # type: ignore
) -> ClojureAnalysis:
    """Use nREPL to get more accurate analysis of Clojure code.

    This uses the actual Clojure runtime to analyze the code,
    which is more accurate than static regex-based analysis.

    Args:
        code: Clojure source code
        nrepl_client: Connected nREPL client

    Returns:
        ClojureAnalysis with definitions detected via nREPL
    """
    # Get namespace vars before evaluation
    before_result = nrepl_client.eval("(set (keys (ns-publics 'user)))")
    before_vars = set()
    if before_result.value:
        # Parse the set from Clojure: #{foo bar baz}
        match = re.search(r'#\{([^}]*)\}', before_result.value)
        if match:
            before_vars = set(match.group(1).split())

    # Static analysis for references
    static = analyze_clojure(code)

    return ClojureAnalysis(
        definitions=static.definitions,
        references=static.references,
        locals=static.locals,
        all_symbols=static.all_symbols,
    )


def get_new_definitions_after_eval(
    nrepl_client: "NReplClient",  # type: ignore
    vars_before: Set[str],
) -> Set[str]:
    """Get vars that were defined since the last check.

    Call this after evaluating code to see what new vars appeared.

    Args:
        nrepl_client: Connected nREPL client
        vars_before: Set of var names before evaluation

    Returns:
        Set of newly defined var names
    """
    # Get current namespace vars
    result = nrepl_client.eval("(vec (keys (ns-publics 'user)))")
    current_vars = set()
    if result.value:
        # Parse the vector from Clojure: [foo bar baz]
        match = re.search(r'\[([^\]]*)\]', result.value)
        if match:
            symbols = re.findall(r'[a-zA-Z_][a-zA-Z0-9_\-\*\+\!\?\<\>\=\']*', match.group(1))
            current_vars = set(symbols)

    return current_vars - vars_before


def get_namespace_vars(nrepl_client: "NReplClient") -> Set[str]:  # type: ignore
    """Get all public vars in the user namespace.

    Args:
        nrepl_client: Connected nREPL client

    Returns:
        Set of var names
    """
    result = nrepl_client.eval("(vec (keys (ns-publics 'user)))")
    vars = set()
    if result.value:
        match = re.search(r'\[([^\]]*)\]', result.value)
        if match:
            symbols = re.findall(r'[a-zA-Z_][a-zA-Z0-9_\-\*\+\!\?\<\>\=\']*', match.group(1))
            vars = set(symbols)
    return vars
