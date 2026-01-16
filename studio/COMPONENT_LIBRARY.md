# Lars Component Library

Shared, reusable components for the Lars Dashboard. All components follow the cyberpunk/Tron design system with consistent styling, animations, and behavior.

## Installation

```javascript
import { Button, Card, Badge, StatusDot, RichTooltip } from '../components';
```

---

## Components

### Button

Reusable button with multiple variants and states.

**Variants:**
- `primary` - Bright cyan, high emphasis (main actions)
- `secondary` - Transparent/bordered, low emphasis (default)
- `ghost` - Minimal, no border (tertiary actions)
- `tool` - Purple accent (tool-related actions)
- `danger` - Red/pink (destructive actions)
- `success` - Green (positive actions)

**Sizes:** `sm`, `md`, `lg`

**Props:**
- `variant`: Button style variant
- `size`: Button size
- `icon`: Iconify icon ID
- `iconPosition`: 'left' | 'right'
- `loading`: Show spinner
- `disabled`: Disable button
- `active`: Active state styling
- `className`: Additional CSS classes

**Examples:**
```jsx
<Button variant="primary" icon="mdi:play">
  Run Cascade
</Button>

<Button variant="secondary" loading>
  Saving...
</Button>

<Button variant="tool" icon="mdi:wrench" />

<Button variant="danger" icon="mdi:delete">
  Delete
</Button>
```

---

### Badge

Small status/count indicator badges.

**Variants:**
- `status` - Pill-shaped status badge (uppercase text)
- `count` - Circular/pill numeric badge
- `label` - Text label badge (default)
- `icon` - Icon-only circular badge

**Colors:** `cyan`, `purple`, `green`, `yellow`, `red`, `blue`, `gray`

**Sizes:** `sm`, `md`, `lg`

**Props:**
- `variant`: Badge style variant
- `color`: Badge color
- `icon`: Optional Iconify icon
- `size`: Badge size
- `glow`: Add glow effect
- `pulse`: Add pulse animation
- `className`: Additional CSS classes

**Examples:**
```jsx
<Badge variant="status" color="green">Success</Badge>
<Badge variant="count" color="red" glow>5</Badge>
<Badge variant="icon" icon="mdi:check" color="green" />
<Badge color="purple" pulse>Running</Badge>
```

---

### StatusDot

Small colored dot for indicating state.

**Statuses:** `running`, `success`, `error`, `warning`, `pending`, `info`

**Sizes:** `sm` (6px), `md` (8px), `lg` (10px)

**Props:**
- `status`: Dot status/color
- `size`: Dot size
- `pulse`: Add pulse animation
- `glow`: Add glow effect
- `className`: Additional CSS classes

**Examples:**
```jsx
<StatusDot status="running" pulse glow />
<StatusDot status="success" />
<StatusDot status="error" size="lg" />
```

---

### Card

Container component with glass morphism effects.

**Variants:**
- `default` - Standard card with border
- `glass` - Glass morphism with blur
- `flat` - No border, minimal
- `outlined` - Just border, no background

**Padding:** `none`, `sm`, `md`, `lg`, `xl`

**Props:**
- `variant`: Card style variant
- `padding`: Internal padding
- `hover`: Enable hover effect (lift + glow)
- `className`: Additional CSS classes

**Examples:**
```jsx
<Card variant="glass" padding="md">
  <h3>Title</h3>
  <p>Content</p>
</Card>

<Card variant="default" hover onClick={handleClick}>
  Clickable card
</Card>

<Card variant="outlined" padding="lg">
  Large padded card
</Card>
```

---

### RichTooltip

Advanced tooltip with rich content support.

**Features:**
- Portal-based rendering (appears above all content)
- Auto-positioning with viewport detection
- Supports any React content
- Delay before showing
- Arrow indicators

**Placement:** `top`, `bottom`, `left`, `right`

**Props:**
- `content`: React node to show in tooltip
- `placement`: Tooltip position
- `delay`: Delay before showing (ms)
- `disabled`: Disable tooltip
- `className`: Additional CSS classes

**Pre-built Content:**
- `RunningCascadeTooltipContent` - For running cascade metadata
- `SimpleTooltipContent` - For simple text tooltips
- `Tooltip` - Wrapper for simple text tooltips

**Examples:**
```jsx
<RichTooltip
  content={<div>Custom content</div>}
  placement="right"
>
  <button>Hover me</button>
</RichTooltip>

<Tooltip label="Save File" shortcut="⌘S">
  <button>Save</button>
</Tooltip>

<RichTooltip
  content={
    <RunningCascadeTooltipContent
      cascadeId="my_cascade"
      sessionId="sess_123"
      ageSeconds={45}
    />
  }
>
  <div>Hover for details</div>
</RichTooltip>
```

---

## Design Tokens

All components use CSS variables from `src/styles/variables.css`:

### Colors
```css
--color-accent-cyan: #00e5ff       /* Primary actions */
--color-accent-purple: #a78bfa     /* Tools, context */
--color-accent-green: #34d399      /* Success */
--color-accent-yellow: #fbbf24     /* Warning */
--color-accent-pink: #ff006e       /* Error, danger */
```

### Spacing
```css
--space-xs: 4px
--space-sm: 8px
--space-md: 12px
--space-lg: 16px
--space-xl: 24px
```

### Shadows
```css
--shadow-md: 0 4px 12px rgba(0, 0, 0, 0.4)
--shadow-glow-cyan: 0 0 12px rgba(0, 229, 255, 0.4)
--shadow-glow-green: 0 0 12px rgba(52, 211, 153, 0.4)
```

---

## Animations

Components use shared animations from `src/styles/animations.css`:

### Keyframes
- `pulse` - Opacity pulse
- `pulse-glow` - Pulse with glow effect
- `spin` - Rotation
- `fade-in` - Fade in
- `scale-in` - Scale + fade in
- `slide-in-*` - Slide from direction

### Utility Classes
```css
.animate-pulse        /* Apply pulse animation */
.animate-pulse-glow   /* Pulse with glow */
.animate-spin         /* Spin animation */
.animate-fade-in      /* Fade in on mount */
```

---

## Best Practices

### When to Use Each Component

**Button:**
- User actions (save, run, delete, etc.)
- Navigation actions
- Form submissions
- Dialogs/modals

**Badge:**
- Status indicators (running, success, error)
- Count displays (5 items, 3 errors)
- Small labels (model name, file type)
- Metadata chips

**StatusDot:**
- Minimal status indicators
- Connection status
- Running state indicators
- List item states

**Card:**
- Content containers
- List items
- Panels and sections
- Modals and dialogs

**RichTooltip:**
- Hover metadata
- Help text
- Keyboard shortcuts
- Complex tooltips with multiple fields

---

## Creating New Components

When extracting a new shared component:

1. **Create directory:** `src/components/MyComponent/`
2. **Create files:**
   - `MyComponent.jsx` - Component logic
   - `MyComponent.css` - Component styles (use CSS variables!)
   - `index.js` - Export wrapper
3. **Add to index:** Update `src/components/index.js`
4. **Document:** Add section to this file
5. **Test:** Verify in multiple contexts

### Component Template

```jsx
// MyComponent.jsx
import React from 'react';
import './MyComponent.css';

const MyComponent = ({
  variant = 'default',
  size = 'md',
  className = '',
  ...props
}) => {
  const classes = [
    'wl-mycomponent',
    `wl-mycomponent-${variant}`,
    `wl-mycomponent-${size}`,
    className,
  ].filter(Boolean).join(' ');

  return <div className={classes} {...props} />;
};

export default MyComponent;
```

```css
/* MyComponent.css */
.wl-mycomponent {
  /* Use CSS variables */
  background-color: var(--color-bg-card);
  color: var(--color-text-primary);
  border-radius: var(--radius-md);
  transition: all var(--transition-normal);
}
```

---

## Component Naming Convention

All shared components use `wl-` prefix to avoid conflicts:
- Class names: `wl-button`, `wl-badge`, `wl-card`
- Modifiers: `wl-button-primary`, `wl-badge-sm`
- States: `wl-button-active`, `wl-button-loading`

This prevents collisions with existing CSS and makes it clear which components are part of the shared library.

---

**Last Updated:** 2025-12-24
**Components:** Button, Badge, StatusDot, Card, RichTooltip
**Status:** Ready for use in all views
