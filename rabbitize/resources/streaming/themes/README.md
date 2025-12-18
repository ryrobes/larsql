# Rabbitize Theme System

## Overview

The Rabbitize theme system provides a flexible, CSS variable-based theming architecture that allows users to switch between different dark mode themes while maintaining consistency across the application.

## Available Themes

### 1. **Cyberpunk** (Default)
- **Colors**: Neon cyan (#0ff), magenta (#f0f), yellow (#ff0)
- **Vibe**: Digital rain, neon lights, futuristic hacker aesthetic
- **Best for**: Night coding sessions, dramatic presentations

### 2. **GitHub Dark**
- **Colors**: Blue (#58a6ff), purple (#bc8cff), orange (#f0883e)
- **Vibe**: Familiar GitHub interface, professional developer feel
- **Best for**: Daily development work, team collaborations

### 3. **Matrix Terminal**
- **Colors**: Classic green (#00ff00) monochrome
- **Vibe**: Old-school terminal, phosphor CRT monitor
- **Best for**: Focused coding, minimal distractions

### 4. **Synthwave Retro**
- **Colors**: Hot pink (#ff006e), purple (#8338ec), gold (#ffbe0b)
- **Vibe**: 80s nostalgia, Miami Vice, neon sunset
- **Best for**: Creative sessions, evening work

### 5. **Deep Ocean**
- **Colors**: Cyan (#00d9ff), ocean blue (#0096c7), aqua (#90e0ef)
- **Vibe**: Underwater tranquility, submarine depths
- **Best for**: Long sessions, reduced eye strain

## Features

- **Smooth Transitions**: Elegant theme switching with fade effects
- **Persistent Preferences**: Saves selected theme to localStorage
- **Keyboard Shortcut**: `Ctrl/Cmd + Shift + T` to cycle themes
- **Responsive Design**: Desktop dropdown and mobile dot switcher
- **No Build Required**: Pure CSS/JS implementation

## Implementation

### 1. Include Theme Files

Add these files to your HTML in order:

```html
<!-- Theme variables (required) -->
<link rel="stylesheet" href="/resources/streaming/themes/theme-variables.css">

<!-- Your existing CSS files -->
<link rel="stylesheet" href="/resources/streaming/cyberpunk.css">

<!-- Theme switcher UI (optional) -->
<link rel="stylesheet" href="/resources/streaming/themes/theme-switcher.css">

<!-- Before closing </body> -->
<script src="/resources/streaming/themes/theme-switcher.js"></script>
```

### 2. Convert Colors to Variables

Replace hard-coded colors with CSS variables:

```css
/* Before */
color: #0ff;
background: #000;
border: 1px solid #0ff;

/* After */
color: var(--color-primary);
background: var(--bg-base);
border: 1px solid var(--border-primary);
```

### 3. CSS Variable Reference

#### Core Colors
- `--color-primary`: Main brand color
- `--color-secondary`: Secondary brand color
- `--color-accent`: Accent/highlight color
- `--color-success`: Success states
- `--color-warning`: Warning states
- `--color-error`: Error states

#### Backgrounds
- `--bg-base`: Main background (#000 in cyberpunk)
- `--bg-surface`: Card/panel backgrounds
- `--bg-surface-2` to `--bg-surface-4`: Elevated surfaces

#### Text
- `--text-primary`: Main text color
- `--text-secondary`: Secondary text
- `--text-muted`: De-emphasized text
- `--text-disabled`: Disabled state text

#### Borders
- `--border-primary`: Primary borders
- `--border-secondary`: Secondary borders
- `--border-muted`: Subtle borders

#### Effects
- `--glow-primary`: Primary glow effect
- `--glow-secondary`: Secondary glow
- `--glow-accent`: Accent glow
- `--overlay-dark`: Dark overlays
- `--overlay-light`: Light overlays

## Adding New Themes

1. Add theme definition to `theme-variables.css`:

```css
[data-theme="your-theme"] {
  --color-primary: #yourcolor;
  --color-secondary: #yourcolor;
  /* ... all other variables ... */
}
```

2. Add theme to `theme-switcher.js`:

```javascript
this.themes = [
  // ... existing themes ...
  {
    id: 'your-theme',
    name: 'Your Theme',
    description: 'Your theme description',
    colors: ['your-1', 'your-2', 'your-3']
  }
];
```

3. Add color swatches to `theme-switcher.css`:

```css
.theme-dot[data-theme="your-theme"],
.color-dot.your-1 { background: #yourcolor; }
.color-dot.your-2 { background: #yourcolor; }
.color-dot.your-3 { background: #yourcolor; }
```

## Best Practices

1. **Use Semantic Names**: Use `--color-primary` not `--color-cyan`
2. **Maintain Contrast**: Ensure text remains readable in all themes
3. **Test All States**: Check hover, active, disabled states
4. **Consider Context**: Some colors have meaning (red = error)
5. **Smooth Transitions**: Theme switching should feel fluid

## Troubleshooting

### Theme not applying?
- Check that `theme-variables.css` is loaded first
- Verify no inline styles override variables
- Check browser console for errors

### Colors look wrong?
- Some colors may need opacity adjustments per theme
- Use the color mapping guide in `cyberpunk-themed.css`

### Performance issues?
- The `.theme-transitioning` class disables transitions during switch
- Consider reducing transition properties if needed

## Browser Support

- Chrome/Edge: Full support
- Firefox: Full support
- Safari: Full support (14+)
- Mobile: Full support with responsive design

## Color Mapping Quick Reference

| Original Color | CSS Variable |
|----------------|--------------|
| #0ff | var(--color-primary) |
| #f0f | var(--color-secondary) |
| #ff0 | var(--color-accent) |
| #0f0 | var(--color-success) |
| #f00 | var(--color-error) |
| #000 | var(--bg-base) |
| #1a1a1a | var(--bg-surface-2) |
| #fff | var(--text-primary) |
| #666 | var(--text-muted) |

## Demo

View the theme demo at: `/resources/streaming/themes/theme-demo.html`

This page showcases all theme colors, components, and effects.