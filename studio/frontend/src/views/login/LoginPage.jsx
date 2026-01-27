/**
 * LoginPage - Authentication login form
 *
 * Simple login form that authenticates against LARS backend.
 * Redirects to main app on successful login.
 */
import React, { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useAuthStore } from '../../stores/authStore';
import './LoginPage.css';

const LoginPage = () => {
  const navigate = useNavigate();
  const location = useLocation();

  // Auth store
  const {
    login,
    isAuthenticated,
    isLoading,
    error,
    clearError,
    checkAuth,
    authEnabled,
  } = useAuthStore();

  // Form state
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');

  // Get redirect destination from location state or default to home
  const from = location.state?.from?.pathname || '/';

  // Check auth status on mount
  useEffect(() => {
    checkAuth();
  }, [checkAuth]);

  // Redirect if already authenticated
  useEffect(() => {
    if (isAuthenticated) {
      navigate(from, { replace: true });
    }
  }, [isAuthenticated, navigate, from]);

  // Clear errors when inputs change
  useEffect(() => {
    if (error) {
      clearError();
    }
  }, [username, password]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSubmit = async (e) => {
    e.preventDefault();

    if (!username.trim()) {
      return;
    }

    const result = await login(username.trim(), password);

    if (result.success) {
      navigate(from, { replace: true });
    }
  };

  // If auth is not enabled, redirect immediately
  useEffect(() => {
    if (authEnabled === false) {
      navigate(from, { replace: true });
    }
  }, [authEnabled, navigate, from]);

  return (
    <div className="login-page">
      <div className="login-container">
        <div className="login-header">
          <h1 className="login-title">LARS</h1>
          <p className="login-subtitle">Sign in to continue</p>
        </div>

        <form className="login-form" onSubmit={handleSubmit}>
          {error && (
            <div className="login-error">
              {error}
            </div>
          )}

          <div className="login-field">
            <label htmlFor="username">Username</label>
            <input
              id="username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="Enter username"
              autoComplete="username"
              autoFocus
              disabled={isLoading}
            />
          </div>

          <div className="login-field">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter password or API key"
              autoComplete="current-password"
              disabled={isLoading}
            />
          </div>

          <button
            type="submit"
            className="login-button"
            disabled={isLoading || !username.trim()}
          >
            {isLoading ? 'Signing in...' : 'Sign In'}
          </button>
        </form>

        <div className="login-footer">
          <p className="login-hint">
            Default credentials: <code>admin</code> / <code>admin</code>
          </p>
        </div>
      </div>
    </div>
  );
};

export default LoginPage;
