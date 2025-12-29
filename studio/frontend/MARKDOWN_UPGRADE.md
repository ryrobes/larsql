# Markdown Upgrade Guide

## New RichMarkdown Component

All markdown rendering has been upgraded to use the comprehensive `RichMarkdown` component.

### What's Supported Now

✅ **GitHub Flavored Markdown (GFM)**
- Tables
- Strikethrough (`~~text~~`)
- Task lists (`- [ ] todo`)
- Autolinks

✅ **LaTeX Math**
- Inline: `$x^2 + y^2 = z^2$`
- Block/Display: `$$\frac{a}{b}$$`
- All LaTeX commands: `\sqrt`, `\sum`, `\int`, `\alpha`, etc.

✅ **Code Syntax Highlighting**
- 200+ languages supported
- Automatic language detection
- Dark theme optimized

✅ **Emoji Shortcuts**
- `:smile:` → 😄
- `:rocket:` → 🚀
- `:heart:` → ❤️

✅ **Safe HTML**
- Sanitized by default
- `<details>` and `<summary>` for collapsible sections
- Tables, images, etc.

✅ **Enhanced Typography**
- Footnotes
- Smart quotes
- Proper heading anchors

### Usage

**Simple (replaces old ReactMarkdown):**

```jsx
import RichMarkdown from './RichMarkdown';

// Old way:
<ReactMarkdown remarkPlugins={[remarkGfm]}>
  {content}
</ReactMarkdown>

// New way:
<RichMarkdown>
  {content}
</RichMarkdown>
```

**Everything is automatic** - no plugins to configure!

### Components Updated

- ✅ `DebugMessageRenderer.js` - Full LLM output rendering
- ⏳ `InstanceCard.js` - Cascade descriptions
- ⏳ `InstancesView.js` - Instance details
- ⏳ `HotOrNotView.js` - Preference comparisons
- ⏳ `AudibleModal.js` - Audio transcripts
- ⏳ `SoundingComparison.js` - Sounding outputs
- ⏳ `ComparisonSection.js` - UI sections
- ⏳ `AccordionSection.js` - Collapsible content
- ⏳ `DynamicUI.js` - Dynamic UI elements
- ⏳ `CardGridSection.js` - Card grids
- ⏳ `ParametersCard.js` - Parameter display
- ⏳ `SoundingsExplorer.js` - Soundings explorer

### Example: Math in LLM Output

When an LLM outputs:

```
The quadratic formula is $x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}$

For display math:

$$
\int_{-\infty}^{\infty} e^{-x^2} dx = \sqrt{\pi}
$$
```

It will render beautifully with proper LaTeX formatting! 🎯

### Styling

All styling is in `RichMarkdown.css` - optimized for:
- Dark theme
- LLM-generated content
- Code-heavy documents
- Mathematical notation
- Mobile responsive
