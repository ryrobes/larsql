/**
 * API Configuration
 *
 * Derives the API base URL from the current window location,
 * allowing the frontend to work when served from any host.
 */

function getApiBaseUrl() {
  // If explicitly set via environment variable, use that
  if (process.env.REACT_APP_API_URL) {
    return process.env.REACT_APP_API_URL;
  }

  // In production/remote: use the same origin the page was served from
  // The backend serves both the frontend and API on the same port
  if (typeof window !== 'undefined') {
    return window.location.origin;
  }

  // Fallback for SSR or tests
  return 'http://localhost:5050';
}

export const API_BASE_URL = getApiBaseUrl();
export const API_STUDIO_URL = `${API_BASE_URL}/api/studio`;
