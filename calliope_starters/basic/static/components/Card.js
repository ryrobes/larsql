/**
 * Card Component
 * ==============
 * Container for dashboard widgets. Handles title, loading, and error states.
 */

import React from 'react';
import htm from 'htm';
const html = htm.bind(React.createElement);

export function Card({
    title = null,
    subtitle = null,
    actions = null,
    className = '',
    children
}) {
    return html`
        <div
            className=${`rounded-lg flex flex-col ${className}`}
            style=${{
                backgroundColor: 'var(--bg-secondary)',
                border: '1px solid var(--border-primary)',
                boxShadow: 'var(--shadow-sm)',
            }}
        >
            ${(title || actions) && html`
                <div
                    className="px-4 py-3 flex items-center justify-between flex-shrink-0"
                    style=${{ borderBottom: '1px solid var(--border-primary)' }}
                >
                    <div>
                        ${title && html`
                            <h3
                                className="font-medium"
                                style=${{ color: 'var(--text-primary)' }}
                            >
                                ${title}
                            </h3>
                        `}
                        ${subtitle && html`
                            <p
                                className="text-sm mt-0.5"
                                style=${{ color: 'var(--text-secondary)' }}
                            >
                                ${subtitle}
                            </p>
                        `}
                    </div>
                    ${actions && html`
                        <div className="flex items-center gap-2">
                            ${actions}
                        </div>
                    `}
                </div>
            `}
            <div className="p-4 flex-1 min-h-0">
                ${children}
            </div>
        </div>
    `;
}

/**
 * Loading skeleton for cards
 */
export function CardSkeleton({ lines = 3 }) {
    return html`
        <div className="space-y-3">
            ${Array.from({ length: lines }).map((_, i) => html`
                <div 
                    key=${i} 
                    className="h-4 rounded skeleton"
                    style=${{ width: `${70 + Math.random() * 30}%` }}
                />
            `)}
        </div>
    `;
}

/**
 * Error state for cards
 */
export function CardError({ error, onRetry = null }) {
    return html`
        <div className="text-center py-8">
            <div style=${{ color: 'var(--color-error)' }} className="mb-2">
                <svg className="w-8 h-8 mx-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth=${2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
            </div>
            <p className="text-sm" style=${{ color: 'var(--text-secondary)' }}>
                ${error?.message || 'Something went wrong'}
            </p>
            ${onRetry && html`
                <button 
                    onClick=${onRetry}
                    className="mt-3 text-sm"
                    style=${{ color: 'var(--accent-primary)' }}
                >
                    Try again
                </button>
            `}
        </div>
    `;
}

/**
 * Empty state for cards
 */
export function CardEmpty({ message = "No data available" }) {
    return html`
        <div className="text-center py-8">
            <svg 
                className="w-8 h-8 mx-auto mb-2" 
                fill="none" 
                stroke="currentColor" 
                viewBox="0 0 24 24"
                style=${{ color: 'var(--text-tertiary)' }}
            >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth=${2} d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
            </svg>
            <p className="text-sm" style=${{ color: 'var(--text-secondary)' }}>${message}</p>
        </div>
    `;
}
