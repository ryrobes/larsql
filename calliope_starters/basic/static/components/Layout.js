/**
 * Layout Component
 * ================
 * Main page layout with header, theme toggle, optional sidebar, and content area.
 */

import React, { useState, useEffect } from 'react';
import htm from 'htm';
const html = htm.bind(React.createElement);

export function Layout({ 
    title = "Dashboard", 
    subtitle = null,
    filters = null,
    sidebar = null,
    children 
}) {
    const [sidebarOpen, setSidebarOpen] = useState(false);

    return html`
        <div className="min-h-screen" style=${{ backgroundColor: 'var(--bg-primary)' }}>
            <!-- Header -->
            <header className="header sticky top-0 z-10">
                <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
                    <div className="flex items-center justify-between h-16">
                        <!-- Left: Menu + Title -->
                        <div className="flex items-center gap-4">
                            ${sidebar && html`
                                <button 
                                    onClick=${() => setSidebarOpen(!sidebarOpen)}
                                    className="lg:hidden p-2 rounded-md btn-ghost"
                                >
                                    <${MenuIcon} />
                                </button>
                            `}
                            <div>
                                <h1 className="text-xl font-semibold" style=${{ color: 'var(--text-primary)' }}>
                                    ${title}
                                </h1>
                                ${subtitle && html`
                                    <p className="text-sm" style=${{ color: 'var(--text-secondary)' }}>
                                        ${subtitle}
                                    </p>
                                `}
                            </div>
                        </div>

                        <!-- Right: Actions -->
                        <div className="flex items-center gap-2">
                            <${RefreshButton} />
                            <${ThemeToggle} />
                        </div>
                    </div>

                    <!-- Filters Bar -->
                    ${filters && html`
                        <div className="py-3" style=${{ borderTop: '1px solid var(--border-primary)' }}>
                            ${filters}
                        </div>
                    `}
                </div>
            </header>

            <!-- Main Content -->
            <div className="flex">
                <!-- Sidebar (if provided) -->
                ${sidebar && html`
                    <aside 
                        className=${`
                            fixed lg:static inset-y-0 left-0 z-20
                            w-64 transform transition-transform duration-200
                            ${sidebarOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}
                        `}
                        style=${{ 
                            backgroundColor: 'var(--bg-secondary)', 
                            borderRight: '1px solid var(--border-primary)' 
                        }}
                    >
                        <div className="h-full overflow-y-auto p-4">
                            ${sidebar}
                        </div>
                    </aside>
                `}

                <!-- Content -->
                <main className="flex-1 p-4 sm:p-6 lg:p-8 max-w-7xl mx-auto w-full">
                    ${children}
                </main>
            </div>

            <!-- Mobile sidebar overlay -->
            ${sidebar && sidebarOpen && html`
                <div 
                    className="fixed inset-0 z-10 lg:hidden"
                    style=${{ backgroundColor: 'rgba(0, 0, 0, 0.5)' }}
                    onClick=${() => setSidebarOpen(false)}
                />
            `}
        </div>
    `;
}

// Menu icon for mobile
function MenuIcon() {
    return html`
        <svg 
            className="w-6 h-6" 
            fill="none" 
            stroke="currentColor" 
            viewBox="0 0 24 24"
            style=${{ color: 'var(--text-secondary)' }}
        >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth=${2} d="M4 6h16M4 12h16M4 18h16" />
        </svg>
    `;
}

// Refresh button that reloads data
function RefreshButton() {
    const [spinning, setSpinning] = useState(false);

    const handleRefresh = () => {
        setSpinning(true);
        window.dispatchEvent(new CustomEvent('dashboard-refresh'));
        setTimeout(() => setSpinning(false), 1000);
    };

    return html`
        <button 
            onClick=${handleRefresh}
            className="p-2 rounded-md btn-ghost"
            title="Refresh data"
        >
            <svg 
                className=${`w-5 h-5 ${spinning ? 'animate-spin' : ''}`}
                style=${{ color: 'var(--text-secondary)' }}
                fill="none" 
                stroke="currentColor" 
                viewBox="0 0 24 24"
            >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth=${2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
        </button>
    `;
}

// Theme toggle with sun/moon icons
function ThemeToggle() {
    const [theme, setTheme] = useState('dark');

    // Initialize from localStorage or default
    useEffect(() => {
        const saved = localStorage.getItem('theme');
        const initial = saved || 'dark';
        setTheme(initial);
        document.documentElement.setAttribute('data-theme', initial);
    }, []);

    const toggleTheme = () => {
        const newTheme = theme === 'dark' ? 'light' : 'dark';
        setTheme(newTheme);
        document.documentElement.setAttribute('data-theme', newTheme);
        localStorage.setItem('theme', newTheme);
    };

    return html`
        <button 
            onClick=${toggleTheme}
            className="theme-toggle"
            title=${`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
            aria-label="Toggle theme"
        >
            <!-- Sun icon (visible in dark mode, click to go light) -->
            <svg 
                className="icon-sun" 
                fill="none" 
                stroke="currentColor" 
                viewBox="0 0 24 24"
            >
                <path 
                    strokeLinecap="round" 
                    strokeLinejoin="round" 
                    strokeWidth=${2} 
                    d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" 
                />
            </svg>
            <!-- Moon icon (visible in light mode, click to go dark) -->
            <svg 
                className="icon-moon" 
                fill="none" 
                stroke="currentColor" 
                viewBox="0 0 24 24"
            >
                <path 
                    strokeLinecap="round" 
                    strokeLinejoin="round" 
                    strokeWidth=${2} 
                    d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" 
                />
            </svg>
        </button>
    `;
}
