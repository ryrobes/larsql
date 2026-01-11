// Footer Component
// Renders the shared footer

export function renderFooter() {
  const year = new Date().getFullYear();

  return `
    <footer>
      <div class="container">
        <p>
          RVBBIT &copy; ${year} |
          <a href="https://github.com/ryrobes/rvbbit" target="_blank" rel="noopener">GitHub</a> |
          <a href="https://github.com/ryrobes/rvbbit/issues" target="_blank" rel="noopener">Report Issues</a>
        </p>
      </div>
    </footer>
  `;
}
