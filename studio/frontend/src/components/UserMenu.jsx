/**
 * UserMenu - Floating user account button with dropdown menu
 *
 * Features:
 * - Circular avatar showing user's initial
 * - Dropdown menu with account options
 * - Logout functionality
 * - Future: gravatar support
 */
import React, { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Icon } from '@iconify/react';
import { useAuthStore } from '../stores/authStore';
import './UserMenu.css';

function UserMenu() {
  const navigate = useNavigate();
  const { user, logout, authEnabled } = useAuthStore();
  const [isOpen, setIsOpen] = useState(false);
  const menuRef = useRef(null);

  // Close menu when clicking outside
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setIsOpen(false);
      }
    };

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [isOpen]);

  // Close menu on Escape
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape' && isOpen) {
        setIsOpen(false);
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen]);

  const handleLogout = async () => {
    setIsOpen(false);
    await logout();
    navigate('/login');
  };

  const toggleMenu = () => {
    setIsOpen(!isOpen);
  };

  // Don't render if auth is disabled or no user
  if (!authEnabled || !user) {
    return null;
  }

  // Get user initial for avatar
  const getInitial = () => {
    if (user.display_name) {
      return user.display_name[0].toUpperCase();
    }
    if (user.username) {
      return user.username[0].toUpperCase();
    }
    return 'U';
  };

  return (
    <div className={`user-menu ${isOpen ? 'open' : ''}`} ref={menuRef}>
      {/* Avatar button */}
      <button
        className="user-menu-button"
        onClick={toggleMenu}
        title={user.display_name || user.username}
      >
        <span className="user-avatar">
          {getInitial()}
        </span>
      </button>

      {/* Dropdown menu */}
      {isOpen && (
        <div className="user-menu-dropdown">
          {/* User info header */}
          <div className="user-menu-header">
            <span className="user-menu-name">
              {user.display_name || user.username}
            </span>
            <span className="user-menu-username">
              @{user.username}
            </span>
          </div>

          <div className="user-menu-divider" />

          {/* Menu items */}
          <button className="user-menu-item" onClick={handleLogout}>
            <Icon icon="mdi:logout" width="16" />
            <span>Sign out</span>
          </button>
        </div>
      )}
    </div>
  );
}

export default UserMenu;
