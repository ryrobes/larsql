// Sidebar Component
// Renders the documentation navigation sidebar matching v3 landing page style

export function renderSidebar(navData, currentPage) {
  const sections = navData.sections || [];
  const externalLinks = navData.externalLinks || [];

  return `
    <aside class="toc-sidebar">
      <!-- Brand/Logo -->
      <a href="index.html" class="toc-brand">
        <img src="assets/rvbbit-logo-square.png" alt="RVBBIT" class="toc-logo">
        <span>RVBBIT</span>
      </a>

      <!-- Navigation Groups -->
      <nav class="toc-nav">
        ${sections.map(section => `
          <div class="toc-group ${section.color || ''}">
            <div class="toc-group-label">
              <iconify-icon icon="${section.icon || 'mdi:folder'}"></iconify-icon>
              ${section.title}
            </div>
            ${section.items.map(item => `
              <a href="#${item.id}"
                 class="toc-link ${currentPage === item.id ? 'active' : ''}"
                 data-link
                 data-page="${item.id}">
                ${item.title}
              </a>
              ${item.sections && currentPage === item.id ? `
                <div class="toc-subsections">
                  ${item.sections.map(sub => `
                    <a href="#${item.id}#${sub.anchor}"
                       class="toc-sublink"
                       data-section-link
                       data-anchor="${sub.anchor}">
                      ${sub.title}
                    </a>
                  `).join('')}
                </div>
              ` : ''}
            `).join('')}
          </div>
        `).join('')}

        <!-- External Links -->
        <div class="toc-external-links">
          ${externalLinks.map(link => `
            <a href="${link.url}" class="toc-external-link" ${link.url.startsWith('http') ? 'target="_blank" rel="noopener"' : ''}>
              <iconify-icon icon="${link.icon || 'mdi:link'}"></iconify-icon>
              ${link.title}
            </a>
          `).join('')}
        </div>
      </nav>
    </aside>
  `;
}

// Update active state in sidebar
export function updateSidebarActive(pageId) {
  document.querySelectorAll('.toc-link').forEach(link => {
    if (link.dataset.page === pageId) {
      link.classList.add('active');
    } else {
      link.classList.remove('active');
    }
  });
}

// Get sections for a page from nav data
export function getPageSections(navData, pageId) {
  for (const section of navData.sections) {
    for (const item of section.items) {
      if (item.id === pageId && item.sections) {
        return item.sections;
      }
    }
  }
  return null;
}
