# /// script
# requires-python = ">=3.11"
# ///
"""
Clojure Integration Example

This notebook demonstrates the Clojure integration in Marimo,
showing how Python and Clojure cells can share variables reactively.

Requirements:
- Clojure CLI tools installed (https://clojure.org/guides/install_clojure)
- nREPL will be started automatically on first use
"""

import marimo

__generated_with = "0.10.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    return (mo,)


@app.cell(hide_code=True)
def _(mo):
    mo.md("""
    # Clojure Integration in Marimo

    This notebook demonstrates how to use Clojure code in Marimo notebooks
    with full reactivity support between Python and Clojure cells.

    ## How it works

    The `mo.clj()` function executes Clojure code via an nREPL server.

    **Auto Mode (Recommended)**: Just use `auto=True` and write raw Clojure code.
    Inputs/outputs are auto-detected from your code!

    **Explicit Mode**: Manually specify `inputs` and `outputs` for full control.

    When input variables change, Clojure cells automatically re-execute!
    """)
    return


@app.cell
def _(mo):
    # Python cell: Define some values
    x = mo.ui.slider(1, 100, value=10, label="x")
    y = mo.ui.slider(1, 100, value=20, label="y")
    mo.hstack([x, y])
    return x, y


@app.cell
def _(mo, x, y):
    # Clojure cell with auto mode - inputs/outputs auto-detected!
    # x and y are automatically detected as inputs (referenced Python vars)
    # sum, product, ratio are automatically detected as outputs (def forms)
    result = mo.clj("""
    ; Clojure code that uses Python variables x and y
    (def sum (+ x y))
    (def product (* x y))
    (def ratio (/ (float x) y))

    ; Return a Clojure map with our calculations
    {:sum sum
     :product product
     :ratio ratio
     :message (str "x=" x ", y=" y)}
    """, auto=True)
    return product, ratio, result, sum


@app.cell
def _(mo, product, ratio, sum):
    # Python cell: Use values computed in Clojure
    mo.md(f"""
    ## Results from Clojure

    The Clojure cell computed:
    - **sum** = {sum}
    - **product** = {product}
    - **ratio** = {ratio:.4f}

    Try moving the sliders above - the Clojure cell will re-execute
    and these values will update automatically!
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    ## More Clojure Examples

    Let's explore some Clojure features:
    """)
    return


@app.cell
def _(mo):
    # Clojure: Working with collections (auto mode detects all defs)
    # Note: Use underscores in var names for Python compatibility
    collections_result = mo.clj("""
    ; Clojure has great collection manipulation
    (def numbers [1 2 3 4 5 6 7 8 9 10])

    ; Map, filter, reduce
    (def doubled (mapv #(* 2 %) numbers))
    (def evens (filterv even? numbers))
    (def total (reduce + numbers))

    ; Threading macros for readable pipelines
    (def odd_squares_sum
      (->> numbers
           (filter odd?)
           (map #(* % %))
           (reduce +)))

    {:numbers numbers
     :doubled doubled
     :evens evens
     :total total
     :sum-of-odd-squares odd_squares_sum}
    """, auto=True)
    return collections_result, doubled, evens, numbers, odd_squares_sum, total


@app.cell
def _(collections_result, doubled, evens, mo, total):
    mo.md(f"""
    ### Collection Operations

    Original: `[1 2 3 4 5 6 7 8 9 10]`

    - **Doubled**: `{doubled}`
    - **Evens**: `{evens}`
    - **Total**: `{total}`

    Full result: `{collections_result}`
    """)
    return


@app.cell
def _(mo):
    # Clojure: Functional programming patterns (auto mode)
    # Note: Use underscores for Python-compatible export names
    func_result = mo.clj("""
    ; Higher-order functions
    (defn make_adder [n]
      (fn [x] (+ x n)))

    (def add_10 (make_adder 10))
    (def add_100 (make_adder 100))

    ; Using our functions
    {:add-10-to-5 (add_10 5)
     :add-100-to-5 (add_100 5)
     :composed ((comp add_10 add_100) 5)}
    """, auto=True)
    return add_10, add_100, func_result, make_adder


@app.cell
def _(func_result, mo):
    mo.md(f"""
    ### Functional Programming

    Created `add-10` and `add-100` functions using closures:

    Result: `{func_result}`
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    ## Integration Notes

    - **Auto Mode**: Use `auto=True` for automatic input/output detection
      - Inputs: Python vars referenced in your Clojure code are auto-injected
      - Outputs: All `def`/`defn` forms are auto-exported to Python
    - **Naming**: Use underscores (not hyphens) in var names for Python compatibility
    - The nREPL server starts automatically on first `mo.clj()` call
    - Clojure vars persist across cells (global namespace)
    - Data is automatically converted between Python and Clojure:
      - Python `list` ↔ Clojure `vector`
      - Python `dict` ↔ Clojure `map`
      - Python `set` ↔ Clojure `set`
      - Python `None` ↔ Clojure `nil`
    """)
    return


if __name__ == "__main__":
    app.run()
