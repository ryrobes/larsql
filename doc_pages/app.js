// LARS Documentation - Main Application
// SPA-style documentation with shared components

import { renderSidebar, updateSidebarActive } from './components/sidebar.js';
import Router from './router.js';

class DocsApp {
  constructor() {
    this.navData = null;
    this.router = null;
    this.currentPage = 'overview';
  }

  async init() {
    try {
      // Load navigation data
      await this.loadNavData();

      // Render shell components
      this.renderShell();

      // Initialize router
      this.router = new Router({
        contentElement: '#docs-content',
        contentPath: 'content/',
        defaultPage: 'overview',
        onNavigate: (pageId) => this.onPageChange(pageId)
      });

      // Setup global link handlers
      this.setupLinkHandlers();

      console.log('LARS Docs initialized');

    } catch (error) {
      console.error('Failed to initialize docs:', error);
      this.showError('Failed to load documentation. Please try refreshing the page.');
    }
  }

  async loadNavData() {
    const response = await fetch('nav.json');
    if (!response.ok) {
      throw new Error('Failed to load navigation data');
    }
    this.navData = await response.json();
  }

  renderShell() {
    const pageEl = document.querySelector('.page');
    if (!pageEl) return;

    // Get current page from hash
    this.currentPage = window.location.hash.slice(1).split('#')[0] || 'overview';

    // Build the shell - sidebar + main content only (no header)
    pageEl.innerHTML = `
      ${renderSidebar(this.navData, this.currentPage)}
      <main class="main-content" id="docs-content">
        <div class="loading">Loading</div>
      </main>
    `;
  }

  updateSidebar() {
    // Re-render sidebar to show/hide sub-sections for current page
    const sidebar = document.querySelector('.toc-sidebar');
    if (sidebar) {
      const newSidebar = document.createElement('div');
      newSidebar.innerHTML = renderSidebar(this.navData, this.currentPage);
      sidebar.replaceWith(newSidebar.firstElementChild);
    }
  }

  onPageChange(pageId) {
    this.currentPage = pageId;

    // Re-render sidebar to show sub-sections for new page
    this.updateSidebar();

    // Update document title
    const pageTitle = this.getPageTitle(pageId);
    document.title = pageTitle ? `${pageTitle} - LARS Documentation` : 'LARS Documentation';

    // Scroll to top of content
    const content = document.getElementById('docs-content');
    if (content) {
      content.scrollTop = 0;
    }

    // Scroll window to top too
    window.scrollTo(0, 0);
  }

  getPageTitle(pageId) {
    for (const section of this.navData.sections) {
      for (const item of section.items) {
        if (item.id === pageId) {
          return item.title;
        }
      }
    }
    return null;
  }

  setupLinkHandlers() {
    // Delegate click events for navigation links
    document.addEventListener('click', (e) => {
      // Handle page navigation links
      const pageLink = e.target.closest('a[data-link]');
      if (pageLink) {
        const href = pageLink.getAttribute('href');
        if (href && href.startsWith('#')) {
          e.preventDefault();
          const pageId = href.slice(1).split('#')[0];
          this.router.navigate(pageId);
        }
        return;
      }

      // Handle section anchor links
      const sectionLink = e.target.closest('a[data-section-link]');
      if (sectionLink) {
        e.preventDefault();
        const anchor = sectionLink.dataset.anchor;
        this.scrollToAnchor(anchor);

        // Update URL without triggering navigation
        const currentPage = this.currentPage;
        history.replaceState(null, '', `#${currentPage}#${anchor}`);

        // Update active section in sidebar
        this.updateActiveSectionLink(anchor);
      }
    });
  }

  scrollToAnchor(anchor) {
    const element = document.getElementById(anchor);
    if (element) {
      // Scroll into view with some offset for the fixed position
      const offset = 20;
      const elementPosition = element.getBoundingClientRect().top;
      const offsetPosition = elementPosition + window.pageYOffset - offset;

      window.scrollTo({
        top: offsetPosition,
        behavior: 'smooth'
      });
    }
  }

  updateActiveSectionLink(anchor) {
    document.querySelectorAll('.toc-sublink').forEach(link => {
      if (link.dataset.anchor === anchor) {
        link.classList.add('active');
      } else {
        link.classList.remove('active');
      }
    });
  }

  showError(message) {
    const pageEl = document.querySelector('.page');
    if (pageEl) {
      pageEl.innerHTML = `
        <div style="display: flex; align-items: center; justify-content: center; min-height: 100vh; padding: 20px; text-align: center;">
          <div>
            <h1 style="color: var(--cyan);">Error</h1>
            <p style="color: var(--muted);">${message}</p>
            <button onclick="location.reload()" class="btn">Refresh Page</button>
          </div>
        </div>
      `;
    }
  }
}

// Initialize app when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
  const app = new DocsApp();
  app.init();
});

export default DocsApp;
