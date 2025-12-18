/**
 * Theme Debugging Helper
 * Add this script to your HTML to debug theme issues
 */

// Monitor theme changes
const observer = new MutationObserver((mutations) => {
  mutations.forEach((mutation) => {
    if (mutation.type === 'attributes' && mutation.attributeName === 'data-theme') {
      console.warn('[Theme Debug] data-theme changed:', {
        oldValue: mutation.oldValue,
        newValue: document.documentElement.getAttribute('data-theme'),
        timestamp: new Date().toISOString()
      });
    }
  });
});

observer.observe(document.documentElement, {
  attributes: true,
  attributeOldValue: true,
  attributeFilter: ['data-theme']
});

// Monitor localStorage changes
const originalSetItem = localStorage.setItem;
localStorage.setItem = function(key, value) {
  if (key === 'rabbitize-theme') {
    console.log('[Theme Debug] localStorage theme saved:', value);
  }
  originalSetItem.apply(this, arguments);
};

// Log current theme state
console.log('[Theme Debug] Initial state:', {
  dataTheme: document.documentElement.getAttribute('data-theme'),
  localStorage: localStorage.getItem('rabbitize-theme'),
  primaryColor: getComputedStyle(document.documentElement).getPropertyValue('--color-primary')
});

// Check for conflicting scripts
window.addEventListener('load', () => {
  console.log('[Theme Debug] Page fully loaded, checking final theme state:', {
    dataTheme: document.documentElement.getAttribute('data-theme'),
    localStorage: localStorage.getItem('rabbitize-theme'),
    primaryColor: getComputedStyle(document.documentElement).getPropertyValue('--color-primary')
  });
});