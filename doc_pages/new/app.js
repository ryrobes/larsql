// RVBBIT Documentation - Main Application
// SPA-style documentation with shared components

import { renderHeader } from './components/header.js';
import { renderSidebar, updateSidebarActive } from './components/sidebar.js';
import { renderFooter } from './components/footer.js';
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

      console.log('RVBBIT Docs initialized');

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
    this.currentPage = window.location.hash.slice(1) || 'overview';

    // Build the shell
    pageEl.innerHTML = `
      ${renderHeader(this.navData, this.currentPage)}
      <div class="container full">
        <div class="docs-layout">
          ${renderSidebar(this.navData, this.currentPage)}
          <main class="docs-content" id="docs-content">
            <div class="loading">Loading</div>
          </main>
        </div>
      </div>
      ${renderFooter()}
    `;
  }

  onPageChange(pageId) {
    this.currentPage = pageId;
    updateSidebarActive(pageId);

    // Update document title
    const pageTitle = this.getPageTitle(pageId);
    document.title = pageTitle ? `${pageTitle} - RVBBIT Documentation` : 'RVBBIT Documentation';
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
      const link = e.target.closest('a[data-link]');
      if (link) {
        const href = link.getAttribute('href');
        if (href && href.startsWith('#')) {
          e.preventDefault();
          this.router.navigate(href.slice(1));
        }
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
