/**
 * Rabbitize Theme Switcher
 * Manages theme switching with localStorage persistence
 */

class ThemeSwitcher {
  constructor() {
    this.themes = [
      {
        id: 'cyberpunk',
        name: 'Cyberpunk',
        description: 'Neon lights & digital rain',
        colors: ['cyberpunk-1', 'cyberpunk-2', 'cyberpunk-3']
      },
      {
        id: 'github-dark',
        name: 'GitHub Dark',
        description: 'Familiar developer vibes',
        colors: ['github-1', 'github-2', 'github-3']
      },
      {
        id: 'matrix',
        name: 'Matrix Terminal',
        description: 'Follow the white rabbit',
        colors: ['matrix-1', 'matrix-2', 'matrix-3']
      },
      {
        id: 'synthwave',
        name: 'Synthwave Retro',
        description: '80s neon aesthetic',
        colors: ['synthwave-1', 'synthwave-2', 'synthwave-3']
      },
      {
        id: 'ocean',
        name: 'Deep Ocean',
        description: 'Calming aquatic depths',
        colors: ['ocean-1', 'ocean-2', 'ocean-3']
      }
    ];
    
    this.currentTheme = this.loadTheme();
    this.initialized = false;
    this.init();
  }
  
  init() {
    // Wait for CSS to be fully loaded before applying theme
    this.ensureCSSLoaded().then(() => {
      // Apply saved theme
      this.applyTheme(this.currentTheme, true);
      
      // Create theme switcher UI
      this.createThemeSwitcher();
      
      // Update UI to reflect current theme
      this.updateUI();
      
      // Add keyboard shortcut (Ctrl/Cmd + Shift + T)
      document.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'T') {
          e.preventDefault();
          this.cycleTheme();
        }
      });
      
      this.initialized = true;
      console.log('[ThemeSwitcher] Initialization complete');
    });
  }
  
  ensureCSSLoaded() {
    return new Promise((resolve) => {
      console.log('[ThemeSwitcher] Waiting for CSS to load...');
      
      // Check if CSS custom properties are available
      const checkCSS = () => {
        const testEl = document.documentElement;
        const computedStyle = getComputedStyle(testEl);
        const primaryColor = computedStyle.getPropertyValue('--color-primary').trim();
        
        // If we have a value for the CSS variable, CSS is loaded
        if (primaryColor) {
          console.log(`[ThemeSwitcher] CSS loaded! Primary color: ${primaryColor}`);
          resolve();
        } else {
          // Try again in 50ms
          setTimeout(checkCSS, 50);
        }
      };
      
      // Start checking
      checkCSS();
    });
  }
  
  loadTheme() {
    const saved = localStorage.getItem('rabbitize-theme');
    console.log(`[ThemeSwitcher] Loaded theme from storage: ${saved || 'none (using default: cyberpunk)'}`);
    return saved || 'cyberpunk';
  }
  
  saveTheme(themeId) {
    localStorage.setItem('rabbitize-theme', themeId);
  }
  
  applyTheme(themeId, skipTransition = false) {
    const root = document.documentElement;
    
    console.log(`[ThemeSwitcher] Applying theme: ${themeId}, skipTransition: ${skipTransition}`);
    
    // For initial load, apply theme immediately without transition
    if (skipTransition) {
      // Always set data-theme attribute, even for cyberpunk
      root.setAttribute('data-theme', themeId);
      this.currentTheme = themeId;
      this.saveTheme(themeId);
      
      // Ensure the theme is applied by forcing a reflow
      void root.offsetHeight;
      
      console.log(`[ThemeSwitcher] Theme applied immediately: ${themeId}`);
      return;
    }
    
    // Add transition class
    root.classList.add('theme-transitioning');
    
    // Show overlay
    const overlay = document.querySelector('.theme-transition-overlay');
    if (overlay) {
      overlay.classList.add('active');
    }
    
    // Apply theme after a brief delay
    setTimeout(() => {
      // Always set data-theme attribute, even for cyberpunk
      root.setAttribute('data-theme', themeId);
      
      this.currentTheme = themeId;
      this.saveTheme(themeId);
      this.updateUI();
      
      // Remove transition class
      setTimeout(() => {
        root.classList.remove('theme-transitioning');
        if (overlay) {
          overlay.classList.remove('active');
        }
      }, 300);
    }, 150);
  }
  
  cycleTheme() {
    const currentIndex = this.themes.findIndex(t => t.id === this.currentTheme);
    const nextIndex = (currentIndex + 1) % this.themes.length;
    this.applyTheme(this.themes[nextIndex].id);
  }
  
  createThemeSwitcher() {
    const container = document.createElement('div');
    container.className = 'theme-switcher';
    container.innerHTML = `
      <!-- Transition Overlay -->
      <div class="theme-transition-overlay"></div>
      
      <!-- Desktop Dropdown -->
      <div class="theme-dropdown" id="theme-dropdown">
        <button class="theme-dropdown-toggle" id="theme-toggle">
          <span class="theme-icon"></span>
          <span class="theme-name">${this.getCurrentTheme().name}</span>
          <span class="dropdown-arrow">▼</span>
        </button>
        <div class="theme-dropdown-menu">
          ${this.themes.map(theme => `
            <div class="theme-option ${theme.id === this.currentTheme ? 'active' : ''}" 
                 data-theme="${theme.id}">
              <div class="theme-preview">
                ${theme.colors.map(color => `<div class="color-dot ${color}"></div>`).join('')}
              </div>
              <div>
                <div class="theme-name">${theme.name}</div>
                <div class="theme-description">${theme.description}</div>
              </div>
            </div>
          `).join('')}
        </div>
      </div>
      
      <!-- Mobile Dots -->
      <div class="theme-dots">
        ${this.themes.map(theme => `
          <div class="theme-dot ${theme.id === this.currentTheme ? 'active' : ''}" 
               data-theme="${theme.id}"
               title="${theme.name}">
          </div>
        `).join('')}
      </div>
    `;
    
    document.body.appendChild(container);
    
    // Event listeners
    this.setupEventListeners();
  }
  
  setupEventListeners() {
    // Desktop dropdown toggle
    const toggle = document.getElementById('theme-toggle');
    const dropdown = document.getElementById('theme-dropdown');
    
    toggle.addEventListener('click', (e) => {
      e.stopPropagation();
      dropdown.classList.toggle('active');
    });
    
    // Close dropdown when clicking outside
    document.addEventListener('click', (e) => {
      if (!dropdown.contains(e.target)) {
        dropdown.classList.remove('active');
      }
    });
    
    // Theme option clicks
    document.querySelectorAll('.theme-option').forEach(option => {
      option.addEventListener('click', () => {
        const themeId = option.getAttribute('data-theme');
        this.applyTheme(themeId);
        dropdown.classList.remove('active');
      });
    });
    
    // Mobile dot clicks
    document.querySelectorAll('.theme-dot').forEach(dot => {
      dot.addEventListener('click', () => {
        const themeId = dot.getAttribute('data-theme');
        this.applyTheme(themeId);
      });
    });
  }
  
  updateUI() {
    const currentTheme = this.getCurrentTheme();
    
    // Update dropdown
    const toggleName = document.querySelector('.theme-dropdown-toggle .theme-name');
    if (toggleName) {
      toggleName.textContent = currentTheme.name;
    }
    
    // Update active states
    document.querySelectorAll('.theme-option').forEach(option => {
      option.classList.toggle('active', option.getAttribute('data-theme') === this.currentTheme);
    });
    
    document.querySelectorAll('.theme-dot').forEach(dot => {
      dot.classList.toggle('active', dot.getAttribute('data-theme') === this.currentTheme);
    });
  }
  
  getCurrentTheme() {
    return this.themes.find(t => t.id === this.currentTheme) || this.themes[0];
  }
}

// Initialize when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    console.log('[ThemeSwitcher] Initializing on DOMContentLoaded');
    window.themeSwitcher = new ThemeSwitcher();
  });
} else {
  console.log('[ThemeSwitcher] Initializing immediately (DOM already loaded)');
  window.themeSwitcher = new ThemeSwitcher();
}