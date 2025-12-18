/* Copyright 2024 Marimo. All rights reserved. */

import { acceptCompletion, autocompletion } from "@codemirror/autocomplete";
import { insertTab } from "@codemirror/commands";
import type { Extension } from "@codemirror/state";
import { keymap } from "@codemirror/view";
import { loadLanguage } from "@uiw/codemirror-extensions-langs";
import type { CellId } from "@/core/cells/ids";
import type { PlaceholderType } from "@/core/codemirror/config/types";
import type {
  CompletionConfig,
  DiagnosticsConfig,
  LSPConfig,
} from "@/core/config/config-schema";
import type { HotkeyProvider } from "@/core/hotkeys/hotkeys";
import type { LanguageAdapter } from "../types";

/**
 * Metadata stored for Clojure cells.
 * In auto mode (default), inputs/outputs are auto-detected from the Clojure code.
 */
export interface ClojureLanguageAdapterMetadata {
  /** Explicit inputs (only used if auto=false) */
  inputs: string[];
  /** Explicit outputs (only used if auto=false) */
  outputs: string[];
  /** Whether auto-detection is enabled (default: true) */
  auto: boolean;
}

/**
 * Regular expression to match mo.clj() calls.
 * Captures:
 * - Group 1: The Clojure code inside """ quotes
 * - Group 2: The Clojure code inside ''' quotes
 */
const CLJ_PATTERN =
  /^\s*(?:\w+\s*=\s*)?mo\.clj\(\s*(?:f)?(?:"""([\s\S]*?)"""|'''([\s\S]*?)''')/;

/**
 * Check if auto=True is present in the call.
 */
const AUTO_PATTERN = /auto\s*=\s*True/;

/**
 * Regular expression to extract inputs parameter.
 */
const INPUTS_PATTERN = /inputs\s*=\s*\[([\s\S]*?)\]/;

/**
 * Regular expression to extract outputs parameter.
 */
const OUTPUTS_PATTERN = /outputs\s*=\s*\[([\s\S]*?)\]/;

/**
 * Parse a list of string literals from Python array syntax.
 */
function parseStringList(content: string): string[] {
  const matches = content.match(/["']([^"']+)["']/g);
  if (!matches) {
    return [];
  }
  return matches.map((m) => m.slice(1, -1));
}

/**
 * Language adapter for Clojure.
 *
 * Transforms between:
 * - Display: Raw Clojure code (what the user sees and edits)
 * - Storage: mo.clj(\"\"\"...\"\"\", auto=True) or mo.clj(..., inputs=[...], outputs=[...])
 *
 * By default, uses auto=True mode which automatically detects inputs/outputs
 * from the Clojure code at compile time using static analysis.
 */
export class ClojureLanguageAdapter
  implements LanguageAdapter<ClojureLanguageAdapterMetadata>
{
  readonly type = "clojure";

  get defaultMetadata(): ClojureLanguageAdapterMetadata {
    return {
      inputs: [],
      outputs: [],
      auto: true, // Auto mode by default
    };
  }

  get defaultCode(): string {
    // Default to auto mode - user just writes Clojure code
    return 'mo.clj("""\n; Clojure code here\n(def x (+ 1 2))\nx\n""", auto=True)';
  }

  /**
   * Transform Python code (with mo.clj wrapper) to display format (raw Clojure).
   * The user only sees the Clojure code, not the mo.clj() wrapper.
   */
  transformIn(
    pythonCode: string,
  ): [
    clojureCode: string,
    offset: number,
    metadata: ClojureLanguageAdapterMetadata,
  ] {
    const match = pythonCode.match(CLJ_PATTERN);
    if (!match) {
      return [pythonCode, 0, this.defaultMetadata];
    }

    // Extract Clojure code from either """ or ''' quotes
    const clojureCode = match[1] || match[2] || "";

    // Check if auto mode is enabled
    const isAuto = AUTO_PATTERN.test(pythonCode);

    // Extract explicit inputs (only relevant if not in auto mode)
    const inputsMatch = pythonCode.match(INPUTS_PATTERN);
    const inputs = inputsMatch ? parseStringList(inputsMatch[1]) : [];

    // Extract explicit outputs (only relevant if not in auto mode)
    const outputsMatch = pythonCode.match(OUTPUTS_PATTERN);
    const outputs = outputsMatch ? parseStringList(outputsMatch[1]) : [];

    // Calculate offset (position where Clojure code starts)
    const beforeCode = pythonCode.slice(0, pythonCode.indexOf(clojureCode));
    const offset = beforeCode.length;

    return [
      clojureCode,
      offset,
      {
        inputs,
        outputs,
        auto: isAuto,
      },
    ];
  }

  /**
   * Transform Clojure code back to Python (with mo.clj wrapper).
   * Wraps the raw Clojure code the user wrote in mo.clj().
   */
  transformOut(
    code: string,
    metadata: ClojureLanguageAdapterMetadata,
  ): [string, number] {
    const parts: string[] = [];

    if (metadata.auto) {
      // Auto mode - just add auto=True, inputs/outputs are detected at compile time
      parts.push("auto=True");
    } else {
      // Explicit mode - add inputs/outputs
      if (metadata.inputs.length > 0) {
        const inputsList = metadata.inputs.map((i) => `"${i}"`).join(", ");
        parts.push(`inputs=[${inputsList}]`);
      }

      if (metadata.outputs.length > 0) {
        const outputsList = metadata.outputs.map((o) => `"${o}"`).join(", ");
        parts.push(`outputs=[${outputsList}]`);
      }
    }

    const kwargs = parts.length > 0 ? `, ${parts.join(", ")}` : "";

    // Wrap in mo.clj()
    const pythonCode = `mo.clj("""${code}"""${kwargs})`;

    // Calculate offset
    const offset = 'mo.clj("""'.length;

    return [pythonCode, offset];
  }

  /**
   * Check if the code is a Clojure cell.
   */
  isSupported(pythonCode: string): boolean {
    // Check for mo.clj() wrapper
    if (CLJ_PATTERN.test(pythonCode)) {
      return true;
    }

    // Also support raw Clojure-like code starting with (
    // This is a heuristic - actual detection might need refinement
    const trimmed = pythonCode.trim();
    if (
      trimmed.startsWith("(") &&
      !trimmed.startsWith("(lambda") &&
      !trimmed.includes("=")
    ) {
      // Looks like Lisp/Clojure
      return false; // For now, require explicit mo.clj() wrapper
    }

    return false;
  }

  /**
   * Get CodeMirror extensions for Clojure editing.
   */
  getExtension(
    _cellId: CellId,
    _completionConfig: CompletionConfig,
    _hotkeys: HotkeyProvider,
    _placeholderType: PlaceholderType,
    _lspConfig: LSPConfig & { diagnostics: DiagnosticsConfig },
  ): Extension[] {
    // Load Clojure syntax highlighting
    const clojureLang = loadLanguage("clojure");

    const extensions: Extension[] = [
      keymap.of([
        {
          key: "Tab",
          run: (cm) => {
            return acceptCompletion(cm) || insertTab(cm);
          },
          preventDefault: true,
        },
      ]),
      autocompletion({
        defaultKeymap: false,
        activateOnTyping: true,
        override: [
          // Basic Clojure keywords completion
          clojureKeywordCompletion,
        ],
      }),
    ];

    // Add Clojure language support if available
    if (clojureLang) {
      extensions.unshift(clojureLang);
    }

    return extensions;
  }
}

/**
 * Basic Clojure keyword completion source.
 */
import type { CompletionContext, CompletionResult } from "@codemirror/autocomplete";

function clojureKeywordCompletion(
  context: CompletionContext,
): CompletionResult | null {
  const word = context.matchBefore(/[\w\-\+\*\/\?\!\<\>\=]+/);
  if (!word || (word.from === word.to && !context.explicit)) {
    return null;
  }

  const keywords = [
    // Core forms
    { label: "def", type: "keyword", info: "Define a var" },
    { label: "defn", type: "keyword", info: "Define a function" },
    { label: "defmacro", type: "keyword", info: "Define a macro" },
    { label: "let", type: "keyword", info: "Local bindings" },
    { label: "fn", type: "keyword", info: "Anonymous function" },
    { label: "if", type: "keyword", info: "Conditional" },
    { label: "when", type: "keyword", info: "When conditional" },
    { label: "cond", type: "keyword", info: "Multiple conditions" },
    { label: "case", type: "keyword", info: "Case expression" },
    { label: "do", type: "keyword", info: "Execute expressions" },
    { label: "loop", type: "keyword", info: "Loop construct" },
    { label: "recur", type: "keyword", info: "Recursion" },
    { label: "quote", type: "keyword", info: "Quote form" },
    { label: "var", type: "keyword", info: "Get var" },
    { label: "throw", type: "keyword", info: "Throw exception" },
    { label: "try", type: "keyword", info: "Try/catch" },
    { label: "catch", type: "keyword", info: "Catch exception" },
    { label: "finally", type: "keyword", info: "Finally block" },
    // Common functions
    { label: "map", type: "function", info: "Map over collection" },
    { label: "filter", type: "function", info: "Filter collection" },
    { label: "reduce", type: "function", info: "Reduce collection" },
    { label: "apply", type: "function", info: "Apply function" },
    { label: "partial", type: "function", info: "Partial application" },
    { label: "comp", type: "function", info: "Function composition" },
    { label: "identity", type: "function", info: "Identity function" },
    { label: "constantly", type: "function", info: "Constant function" },
    { label: "first", type: "function", info: "First element" },
    { label: "rest", type: "function", info: "Rest of collection" },
    { label: "cons", type: "function", info: "Construct list" },
    { label: "conj", type: "function", info: "Conjoin to collection" },
    { label: "assoc", type: "function", info: "Associate in map" },
    { label: "dissoc", type: "function", info: "Dissociate from map" },
    { label: "get", type: "function", info: "Get from collection" },
    { label: "get-in", type: "function", info: "Get nested value" },
    { label: "assoc-in", type: "function", info: "Associate nested value" },
    { label: "update", type: "function", info: "Update value in map" },
    { label: "update-in", type: "function", info: "Update nested value" },
    { label: "merge", type: "function", info: "Merge maps" },
    { label: "into", type: "function", info: "Into collection" },
    { label: "concat", type: "function", info: "Concatenate" },
    { label: "flatten", type: "function", info: "Flatten nested" },
    { label: "distinct", type: "function", info: "Distinct values" },
    { label: "sort", type: "function", info: "Sort collection" },
    { label: "sort-by", type: "function", info: "Sort by function" },
    { label: "group-by", type: "function", info: "Group by function" },
    { label: "partition", type: "function", info: "Partition collection" },
    { label: "take", type: "function", info: "Take n elements" },
    { label: "drop", type: "function", info: "Drop n elements" },
    { label: "take-while", type: "function", info: "Take while predicate" },
    { label: "drop-while", type: "function", info: "Drop while predicate" },
    { label: "range", type: "function", info: "Range of numbers" },
    { label: "repeat", type: "function", info: "Repeat value" },
    { label: "repeatedly", type: "function", info: "Repeatedly call fn" },
    { label: "iterate", type: "function", info: "Iterate function" },
    { label: "str", type: "function", info: "Convert to string" },
    { label: "pr-str", type: "function", info: "Print to string" },
    { label: "println", type: "function", info: "Print with newline" },
    { label: "prn", type: "function", info: "Print readable" },
    { label: "format", type: "function", info: "Format string" },
    { label: "count", type: "function", info: "Count elements" },
    { label: "empty?", type: "function", info: "Check if empty" },
    { label: "nil?", type: "function", info: "Check if nil" },
    { label: "some?", type: "function", info: "Check if not nil" },
    { label: "not", type: "function", info: "Boolean not" },
    { label: "and", type: "keyword", info: "Boolean and" },
    { label: "or", type: "keyword", info: "Boolean or" },
    { label: "true", type: "constant", info: "Boolean true" },
    { label: "false", type: "constant", info: "Boolean false" },
    { label: "nil", type: "constant", info: "Nil value" },
    // Threading macros
    { label: "->", type: "keyword", info: "Thread first" },
    { label: "->>", type: "keyword", info: "Thread last" },
    { label: "as->", type: "keyword", info: "Thread as" },
    { label: "some->", type: "keyword", info: "Some thread first" },
    { label: "some->>", type: "keyword", info: "Some thread last" },
    { label: "cond->", type: "keyword", info: "Conditional thread" },
    { label: "cond->>", type: "keyword", info: "Conditional thread last" },
  ];

  return {
    from: word.from,
    options: keywords,
  };
}
