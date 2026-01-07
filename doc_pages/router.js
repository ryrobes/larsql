// Simple client-side router for documentation SPA
// Uses hash-based routing for simplicity and static hosting compatibility

class Router {
  constructor(options = {}) {
    this.contentElement = options.contentElement || '#docs-content';
    this.contentPath = options.contentPath || 'content/';
    this.defaultPage = options.defaultPage || 'overview';
    this.onNavigate = options.onNavigate || (() => {});
    this.cache = new Map();

    // Bind hash change handler
    window.addEventListener('hashchange', () => this.handleRoute());

    // Handle initial route
    this.handleRoute();
  }

  getCurrentPage() {
    const hash = window.location.hash.slice(1); // Remove #
    return hash || this.defaultPage;
  }

  async handleRoute() {
    const pageId = this.getCurrentPage();
    await this.loadPage(pageId);
  }

  async loadPage(pageId) {
    const contentEl = document.querySelector(this.contentElement);
    if (!contentEl) return;

    // Show loading state
    contentEl.innerHTML = '<div class="loading">Loading</div>';

    try {
      let html;

      // Check cache first
      if (this.cache.has(pageId)) {
        html = this.cache.get(pageId);
      } else {
        // Fetch content
        const response = await fetch(`${this.contentPath}${pageId}.html`);

        if (!response.ok) {
          throw new Error(`Page not found: ${pageId}`);
        }

        html = await response.text();
        this.cache.set(pageId, html);
      }

      // Render content
      contentEl.innerHTML = html;

      // Scroll to top
      window.scrollTo(0, 0);

      // Handle anchor links within content
      this.setupInternalLinks(contentEl);

      // Scroll to hash anchor if present (e.g., #page-id#section)
      this.scrollToAnchor();

      // Notify listeners
      this.onNavigate(pageId);

    } catch (error) {
      console.error('Error loading page:', error);
      contentEl.innerHTML = `
        <div class="docs-content">
          <h1>Page Not Found</h1>
          <p class="lead">The requested page could not be found.</p>
          <p><a href="#overview" data-link>Return to Overview</a></p>
        </div>
      `;
    }
  }

  setupInternalLinks(container) {
    // Convert relative links to hash links
    container.querySelectorAll('a[href^="./"], a[href^="../"]').forEach(link => {
      const href = link.getAttribute('href');
      // Extract page name from href like "./core-concepts.html" or "../landing_page/..."
      if (href.includes('.html') && !href.includes('/')) {
        const pageName = href.replace('./', '').replace('.html', '');
        link.setAttribute('href', `#${pageName}`);
        link.setAttribute('data-link', '');
      }
    });
  }

  scrollToAnchor() {
    // Handle anchors like #page-id#section or just scroll to element by id
    const hash = window.location.hash;
    if (hash.includes('#', 1)) {
      const anchor = hash.split('#')[2];
      if (anchor) {
        const element = document.getElementById(anchor);
        if (element) {
          element.scrollIntoView({ behavior: 'smooth' });
        }
      }
    }
  }

  navigate(pageId) {
    window.location.hash = pageId;
  }
}

export default Router;
