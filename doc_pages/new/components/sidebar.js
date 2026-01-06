// Sidebar Component
// Renders the documentation navigation sidebar

export function renderSidebar(navData, currentPage) {
  const sections = navData.sections || [];

  return `
    <aside class="sidebar">
      <nav>
        ${sections.map(section => `
          <div class="sidebar-section">
            <h4 class="sidebar-title">${section.title}</h4>
            <ul class="sidebar-links">
              ${section.items.map(item => `
                <li>
                  <a href="#${item.id}"
                     class="${currentPage === item.id ? 'active' : ''}"
                     data-link
                     data-page="${item.id}">
                    ${item.title}
                  </a>
                </li>
              `).join('')}
            </ul>
          </div>
        `).join('')}
      </nav>
    </aside>
  `;
}

// Update active state in sidebar
export function updateSidebarActive(pageId) {
  document.querySelectorAll('.sidebar-links a').forEach(link => {
    if (link.dataset.page === pageId) {
      link.classList.add('active');
    } else {
      link.classList.remove('active');
    }
  });
}
