/**
 * AuthGuard - Protects routes that require authentication
 *
 * Checks auth status and redirects to login if not authenticated.
 * Shows loading state while checking auth.
 */
import React, { useEffect, useState } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuthStore } from '../stores/authStore';
import { VideoLoader } from './index';

const AuthGuard = ({ children }) => {
  const location = useLocation();
  const {
    isAuthenticated,
    authEnabled,
    checkAuth,
  } = useAuthStore();

  const [isChecking, setIsChecking] = useState(true);

  // Check auth on mount
  useEffect(() => {
    const doCheck = async () => {
      await checkAuth();
      setIsChecking(false);
    };
    doCheck();
  }, [checkAuth]);

  // Show loading while checking
  if (isChecking) {
    return (
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: '100vw',
        height: '100vh',
        background: 'var(--color-bg-primary)',
      }}>
        <VideoLoader size="large" message="Checking authentication..." />
      </div>
    );
  }

  // If auth is disabled, allow access
  if (authEnabled === false) {
    return children;
  }

  // If not authenticated, redirect to login
  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  // Authenticated - render children
  return children;
};

export default AuthGuard;
