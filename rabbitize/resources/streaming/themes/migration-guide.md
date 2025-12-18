# Theme System Migration Guide

## Overview
This guide explains how to migrate the existing Rabbitize CSS to use the new theme system based on CSS custom properties (variables).

## 1. Include Theme Files

Add these lines to your HTML files:

```html
<!-- Theme variables (load first) -->
<link rel="stylesheet" href="themes/theme-variables.css">

<!-- Theme switcher styles -->
<link rel="stylesheet" href="themes/theme-switcher.css">

<!-- Your existing styles (load after theme variables) -->
<link rel="stylesheet" href="cyberpunk.css">
<link rel="stylesheet" href="flow-builder.css">

<!-- Theme switcher script -->
<script src="themes/theme-switcher.js"></script>
```

## 2. Color Variable Mappings

Replace hardcoded colors with CSS variables:

### Primary Colors
- `#0ff` → `var(--color-primary)`
- `#f0f` → `var(--color-secondary)`
- `#ff0` → `var(--color-accent)`

### Status Colors
- `#0f0` → `var(--color-success)`
- `#ff0` → `var(--color-warning)`
- `#f00` or `#ff0066` → `var(--color-error)`

### Background Colors
- `#000` → `var(--bg-base)`
- `#0a0a0a` → `var(--bg-surface-1)`
- `#1a1a1a` → `var(--bg-surface-2)`
- `#2a2a2a` → `var(--bg-surface-3)`
- `#333` → `var(--bg-surface-4)`

### Text Colors
- `#fff` → `var(--text-primary)`
- `#ccc` → `var(--text-secondary)`
- `#888` → `var(--text-muted)`
- `#666` → `var(--text-faint)`

### Border Colors
- `#0ff` (for borders) → `var(--border-primary)`
- `#333` (for borders) → `var(--border-secondary)`
- `#666` (for borders) → `var(--border-muted)`

### Transparency/Overlays
- `rgba(0, 255, 255, 0.05)` → `var(--overlay-light)`
- `rgba(0, 255, 255, 0.1)` → `var(--overlay-medium)`
- `rgba(0, 255, 255, 0.2)` → `var(--overlay-heavy)`

### Glow Effects
- `0 0 20px rgba(0, 255, 255, 0.8)` → `var(--glow-primary)`
- `0 0 20px rgba(255, 0, 255, 0.8)` → `var(--glow-secondary)`
- `0 0 20px rgba(255, 255, 0, 0.8)` → `var(--glow-accent)`

## 3. Example Conversions

### Before:
```css
.header {
    border: 2px solid #0ff;
    background: rgba(0, 255, 255, 0.05);
}

h1 {
    color: #0ff;
    text-shadow: 0 0 20px rgba(0, 255, 255, 0.8);
}

.action-link:hover {
    background: #0ff;
    color: #000;
    box-shadow: 0 0 20px rgba(0, 255, 255, 0.5);
}
```

### After:
```css
.header {
    border: 2px solid var(--border-primary);
    background: var(--overlay-light);
}

h1 {
    color: var(--color-primary);
    text-shadow: var(--glow-primary);
}

.action-link:hover {
    background: var(--color-primary);
    color: var(--text-on-primary);
    box-shadow: var(--glow-primary);
}
```

## 4. Special Cases

### Timing Chart Colors
Replace specific timing colors with their variables:
```css
/* Before */
.timing-bar[data-command=":move-mouse"] { background: #0ff; }

/* After */
.timing-bar[data-command=":move-mouse"] { background: var(--timing-move-mouse); }
```

### Dynamic RGBA Values
For cases where you need dynamic opacity:
```css
/* Use CSS custom properties with opacity */
.element {
    background: var(--color-primary);
    opacity: 0.5;
}

/* Or use color-mix() for modern browsers */
.element {
    background: color-mix(in srgb, var(--color-primary) 50%, transparent);
}
```

## 5. Testing Themes

After migration, test each theme:

1. Open your application
2. Click the theme switcher (🎨 icon in top-right)
3. Try each theme and verify:
   - All text is readable
   - Interactive elements have proper hover states
   - Status indicators use appropriate colors
   - No hardcoded colors remain

## 6. Adding Custom Themes

To add a new theme:

1. Add theme variables to `theme-variables.css`:
```css
[data-theme="my-theme"] {
    --color-primary: #yourcolor;
    /* ... all other variables ... */
}
```

2. Add theme to `theme-switcher.js`:
```javascript
themes: [
    // ... existing themes ...
    {
        id: 'my-theme',
        name: 'My Theme',
        description: 'Description of theme'
    }
]
```

3. Add color preview dots in `theme-switcher.css`:
```css
.theme-option[data-theme="my-theme"] .theme-color-dot:nth-child(1) { background: #color1; }
.theme-option[data-theme="my-theme"] .theme-color-dot:nth-child(2) { background: #color2; }
.theme-option[data-theme="my-theme"] .theme-color-dot:nth-child(3) { background: #color3; }
```

## 7. Performance Considerations

- CSS variables are computed at runtime, but modern browsers handle this efficiently
- Theme switching adds minimal overhead
- Variables are scoped to `:root` or `[data-theme]` for optimal performance

## 8. Browser Support

CSS custom properties are supported in all modern browsers:
- Chrome 49+
- Firefox 31+
- Safari 9.1+
- Edge 15+

For older browsers, consider providing fallbacks:
```css
.element {
    color: #0ff; /* Fallback */
    color: var(--color-primary);
}
```