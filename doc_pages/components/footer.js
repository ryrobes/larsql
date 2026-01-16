// Footer Component
// Renders the shared footer

export function renderFooter() {
  const year = new Date().getFullYear();

  return `
    <footer>
      <div class="container">
        <p>
          LARS &copy; ${year} |
          <a href="https://github.com/ryrobes/lars" target="_blank" rel="noopener">GitHub</a> |
          <a href="https://github.com/ryrobes/lars/issues" target="_blank" rel="noopener">Report Issues</a>
        </p>
      </div>
    </footer>
  `;
}
