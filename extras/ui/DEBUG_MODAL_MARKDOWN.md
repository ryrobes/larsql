# Debug Modal Markdown Rendering

## Update

Added markdown rendering with syntax highlighting to the Debug Modal!

## Features

### 1. Markdown Rendering for Messages

**Agent, assistant, user, system messages** now render as markdown with:
- ✅ Headers (H1, H2, H3) in purple gradient
- ✅ **Bold text** in pink
- ✅ *Italic text* in yellow
- ✅ Lists (bullets and numbered)
- ✅ Tables
- ✅ Blockquotes
- ✅ Links (blue, clickable)
- ✅ Inline `code` in blue with background

### 2. Syntax Highlighting for Code Blocks

**Markdown code blocks** automatically get syntax highlighting:

````markdown
```python
def hello():
    return "world"
```
````

**Renders with:**
- VS Code Dark Plus theme
- Language-specific highlighting (Python, JavaScript, JSON, etc.)
- Line numbers (optional)
- Copy button (optional)

### 3. Tool Call Arguments

**Tool call JSON** rendered with syntax highlighting:
```json
{
  "code": "print('hello')",
  "language": "python"
}
```

### 4. Tool Results

**Intelligent detection:**
- If content has `Traceback`, `def `, `import`, `Error:` → Renders as Python with syntax highlighting
- Otherwise → Plain text (for normal output)

**Examples:**

**Error with traceback:**
```python
Error: NameError: name 'foo' is not defined

Traceback:
  File "<string>", line 5, in <module>
NameError: name 'foo' is not defined
```
→ Rendered with Python syntax highlighting (red for errors, etc.)

**Normal output:**
```
Hello World
Sum: 42
Result: Success
```
→ Plain text

### 5. JSON Auto-Detection

**If content starts with `{` or `[`**, tries to parse and render as JSON with syntax highlighting.

---

## Libraries Used

1. **react-markdown** - Markdown parser and renderer
2. **remark-gfm** - GitHub Flavored Markdown support (tables, strikethrough, etc.)
3. **react-syntax-highlighter** - Code syntax highlighting with VS Code theme

---

## Styling

### Color Scheme (Dark Mode)

- **Headers:** Purple (#a78bfa)
- **Bold:** Pink (#f472b6)
- **Italic:** Yellow (#fbbf24)
- **Links:** Blue (#60a5fa)
- **Inline code:** Blue with dark background
- **Code blocks:** VS Code Dark Plus theme
- **Tables:** Dark headers with purple
- **Blockquotes:** Purple left border, gray italic text

### Code Blocks

- Dark background (#1a1a1a to #000)
- Syntax colors from VS Code Dark Plus
- Rounded corners (4px)
- Max height 400px with scroll for long code
- Proper font sizing (0.85rem)

---

## Examples of What You'll See

### Agent Message with Code

**Raw markdown:**
```markdown
I'll solve this with Python:

```python
def fibonacci(n):
    if n <= 1:
        return n
    return fibonacci(n-1) + fibonacci(n-2)
```

This uses recursion.
```

**Rendered:**
- "I'll solve this with Python:" as normal text
- Code block with Python syntax highlighting (keywords, functions, etc.)
- "This uses recursion." as normal text

### Tool Result with Error

**Raw:**
```
Error: NameError: name 'generate_fibonacci' is not defined

Traceback:
Traceback (most recent call last):
  File "<string>", line 29
  ...
```

**Rendered:**
- Python syntax highlighting
- Traceback in formatted colors
- Error type highlighted
- Line numbers visible

### Tool Call JSON

**Raw:**
```json
{"tool": "run_code", "arguments": {"code": "print('hello')", "language": "python"}}
```

**Rendered:**
- JSON syntax highlighting
- Colored keys, strings, values
- Proper indentation
- Easy to read

---

## Benefits

### Before (Plain Text)

- All content in monospace font
- No formatting
- Hard to read long messages
- Code not highlighted
- Markdown syntax visible (**, ##, etc.)

### After (Markdown + Syntax Highlighting)

- ✅ Formatted text with headers, bold, italic
- ✅ Code blocks with syntax highlighting
- ✅ Easy to read long messages
- ✅ Errors clearly highlighted
- ✅ Professional appearance
- ✅ JSON pretty-printed automatically

---

## Usage

Just open the Debug Modal on any instance - markdown rendering is automatic!

**It detects:**
- Agent/assistant/user/system messages → Render as markdown
- Tool results with code → Syntax highlight as Python
- JSON content → Syntax highlight as JSON
- Cost updates → Special format (unchanged)

---

## Files Modified

1. **`frontend/src/components/DebugModal.js`**
   - Added imports: react-markdown, remark-gfm, react-syntax-highlighter
   - Updated `renderContent()` with markdown rendering
   - Added code block syntax highlighting
   - Intelligent detection (markdown vs code vs JSON)

2. **`frontend/src/components/DebugModal.css`**
   - Added `.markdown-content` styles
   - Header, bold, italic, link colors
   - Table styling
   - Blockquote styling
   - Syntax highlighter overrides

3. **`package.json`** (auto-updated)
   - Added: react-markdown
   - Added: remark-gfm
   - Added: react-syntax-highlighter

---

## Testing

1. Start the UI: `cd extras/ui && ./start.sh`
2. Run a cascade with tool use
3. Open Debug Modal on the instance
4. **See:**
   - Agent messages rendered as markdown
   - Code blocks with syntax highlighting
   - Tool results formatted nicely
   - Errors highlighted in Python syntax
   - JSON pretty-printed

🎨 **Much more readable and professional!**
