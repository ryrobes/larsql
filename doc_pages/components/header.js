// Header Component
// Renders the shared navigation header

export function renderHeader(navData, currentPage) {
  const externalLinks = navData.externalLinks || [];

  return `
    <header>
      <div class="container">
        <nav class="nav">
          <a href="#overview" class="brand" data-link>
            <span class="brand-text">RVBBIT</span>
          </a>
          <div class="nav-actions">
            <a href="#overview" class="active" data-link>Docs</a>
            ${externalLinks.map(link => `
              <a href="${link.url}" ${link.url.startsWith('http') ? 'target="_blank" rel="noopener"' : ''}>
                ${link.title}
              </a>
            `).join('')}
            <a href="https://github.com/ryrobes/rvbbit" class="btn" target="_blank" rel="noopener">
              <iconify-icon icon="mdi:github"></iconify-icon>
              GitHub
            </a>
          </div>
        </nav>
      </div>
    </header>
  `;
}
