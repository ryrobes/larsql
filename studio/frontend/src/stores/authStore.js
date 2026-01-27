/**
 * Authentication Store
 *
 * Manages authentication state and token storage for LARS Studio.
 * Uses localStorage for token persistence across page refreshes.
 */

import { create } from 'zustand';
import { API_BASE_URL } from '../config/api';

// Storage key for auth token
const TOKEN_KEY = 'lars_auth_token';
const USER_KEY = 'lars_auth_user';

// Helper to get stored token
const getStoredToken = () => {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
};

// Helper to get stored user
const getStoredUser = () => {
  try {
    const userJson = localStorage.getItem(USER_KEY);
    return userJson ? JSON.parse(userJson) : null;
  } catch {
    return null;
  }
};

// Helper to store auth data
const storeAuthData = (token, user) => {
  try {
    if (token) {
      localStorage.setItem(TOKEN_KEY, token);
    } else {
      localStorage.removeItem(TOKEN_KEY);
    }
    if (user) {
      localStorage.setItem(USER_KEY, JSON.stringify(user));
    } else {
      localStorage.removeItem(USER_KEY);
    }
  } catch (e) {
    console.warn('Failed to store auth data:', e);
  }
};

// Clear auth data
const clearAuthData = () => {
  try {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  } catch (e) {
    console.warn('Failed to clear auth data:', e);
  }
};

/**
 * Auth store using Zustand
 */
export const useAuthStore = create((set, get) => ({
  // State
  token: getStoredToken(),
  user: getStoredUser(),
  isAuthenticated: !!getStoredToken(),
  isLoading: false,
  error: null,
  authEnabled: true, // Assume auth is enabled until we check

  // Actions
  login: async (username, password) => {
    set({ isLoading: true, error: null });

    try {
      const response = await fetch(`${API_BASE_URL}/api/auth/login`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ username, password }),
      });

      const data = await response.json();

      if (!response.ok || !data.success) {
        set({
          isLoading: false,
          error: data.error || 'Login failed'
        });
        return { success: false, error: data.error };
      }

      // Store token and user
      storeAuthData(data.token, data.user);

      set({
        token: data.token,
        user: data.user,
        isAuthenticated: true,
        isLoading: false,
        error: null,
        authEnabled: !data.message?.includes('disabled'),
      });

      return { success: true };
    } catch (e) {
      set({
        isLoading: false,
        error: e.message || 'Network error'
      });
      return { success: false, error: e.message };
    }
  },

  logout: async () => {
    try {
      // Call logout endpoint (optional, mainly for future server-side invalidation)
      await fetch(`${API_BASE_URL}/api/auth/logout`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${get().token}`,
        },
      });
    } catch (e) {
      // Ignore errors - logout is primarily client-side
    }

    // Clear local state
    clearAuthData();
    set({
      token: null,
      user: null,
      isAuthenticated: false,
      error: null,
    });
  },

  checkAuth: async () => {
    const token = get().token;

    if (!token) {
      // No token - check if auth is even enabled
      try {
        const response = await fetch(`${API_BASE_URL}/api/auth/status`);
        const data = await response.json();

        set({ authEnabled: data.enabled });

        // If auth is disabled, treat as authenticated anonymous
        if (!data.enabled) {
          set({
            isAuthenticated: true,
            user: {
              user_id: 'anonymous',
              username: 'anonymous',
              display_name: 'Anonymous',
              is_admin: false,
            },
          });
        }
      } catch (e) {
        // Assume auth disabled if status endpoint fails
        set({ authEnabled: false, isAuthenticated: true });
      }
      return;
    }

    // Validate existing token
    try {
      const response = await fetch(`${API_BASE_URL}/api/auth/me`, {
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      });

      const data = await response.json();

      if (data.authenticated) {
        set({
          user: data.user,
          isAuthenticated: true,
          authEnabled: data.auth_enabled,
        });
      } else if (!data.auth_enabled) {
        // Auth is disabled - allow access
        set({
          isAuthenticated: true,
          authEnabled: false,
          user: data.user,
        });
      } else {
        // Token is invalid - clear it
        clearAuthData();
        set({
          token: null,
          user: null,
          isAuthenticated: false,
          authEnabled: true,
        });
      }
    } catch (e) {
      // Network error - keep current state
      console.warn('Auth check failed:', e);
    }
  },

  clearError: () => set({ error: null }),
}));

/**
 * Get auth headers for API requests.
 *
 * Usage:
 *   fetch(url, {
 *     headers: {
 *       ...getAuthHeaders(),
 *       'Content-Type': 'application/json',
 *     },
 *   });
 */
export const getAuthHeaders = () => {
  const token = getStoredToken();
  if (token) {
    return { 'Authorization': `Bearer ${token}` };
  }
  return {};
};

/**
 * Authenticated fetch wrapper.
 * Automatically includes auth headers.
 *
 * Usage:
 *   const response = await authFetch('/api/sql/execute', {
 *     method: 'POST',
 *     body: JSON.stringify({ query: 'SELECT 1' }),
 *   });
 */
export const authFetch = async (url, options = {}) => {
  const fullUrl = url.startsWith('http') ? url : `${API_BASE_URL}${url}`;

  const headers = {
    ...getAuthHeaders(),
    ...options.headers,
  };

  // Add Content-Type for POST/PUT if body is present and not FormData
  if (options.body && !(options.body instanceof FormData)) {
    headers['Content-Type'] = headers['Content-Type'] || 'application/json';
  }

  return fetch(fullUrl, {
    ...options,
    headers,
  });
};

export default useAuthStore;
