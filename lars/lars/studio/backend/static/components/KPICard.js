/**
 * KPI Card Component
 * ==================
 * Display a single KPI value with optional formatting and trend indicator.
 */

import React from 'react';
import htm from 'htm';
const html = htm.bind(React.createElement);

export function KPICard({ 
    title, 
    value, 
    format = 'number',
    trend = null,  // { value: 12.5, direction: 'up' | 'down' }
    subtitle = null,
    loading = false,
}) {
    // Format the value based on type
    const formatValue = (val) => {
        if (val === null || val === undefined) return '—';
        
        switch (format) {
            case 'currency':
                return new Intl.NumberFormat('en-US', {
                    style: 'currency',
                    currency: 'USD',
                    minimumFractionDigits: 0,
                    maximumFractionDigits: 0,
                }).format(val);
            
            case 'percent':
                return `${Number(val).toFixed(1)}%`;
            
            case 'decimal':
                return Number(val).toFixed(2);
            
            case 'text':
                return String(val);
            
            case 'number':
            default:
                return new Intl.NumberFormat('en-US').format(val);
        }
    };

    if (loading) {
        return html`
            <div 
                className="rounded-lg p-4"
                style=${{ 
                    backgroundColor: 'var(--bg-secondary)',
                    border: '1px solid var(--border-primary)',
                }}
            >
                <div className="h-4 rounded w-1/2 mb-3 skeleton"></div>
                <div className="h-8 rounded w-3/4 skeleton"></div>
            </div>
        `;
    }

    return html`
        <div 
            className="rounded-lg p-4 transition-shadow hover:shadow-md"
            style=${{ 
                backgroundColor: 'var(--bg-secondary)',
                border: '1px solid var(--border-primary)',
            }}
        >
            <p 
                className="text-sm font-medium truncate"
                style=${{ color: 'var(--text-secondary)' }}
            >
                ${title}
            </p>
            
            <div className="mt-2 flex items-baseline gap-2">
                <p 
                    className=${format === 'text' ? 'text-xl font-semibold' : 'text-2xl font-semibold'}
                    style=${{ color: 'var(--text-primary)' }}
                >
                    ${formatValue(value)}
                </p>
                
                ${trend && html`
                    <span 
                        className="inline-flex items-center text-sm font-medium"
                        style=${{ 
                            color: trend.direction === 'up' 
                                ? 'var(--color-success)' 
                                : 'var(--color-error)' 
                        }}
                    >
                        ${trend.direction === 'up' ? html`
                            <svg className="w-4 h-4 mr-0.5" fill="currentColor" viewBox="0 0 20 20">
                                <path fillRule="evenodd" d="M5.293 9.707a1 1 0 010-1.414l4-4a1 1 0 011.414 0l4 4a1 1 0 01-1.414 1.414L11 7.414V15a1 1 0 11-2 0V7.414L6.707 9.707a1 1 0 01-1.414 0z" clipRule="evenodd" />
                            </svg>
                        ` : html`
                            <svg className="w-4 h-4 mr-0.5" fill="currentColor" viewBox="0 0 20 20">
                                <path fillRule="evenodd" d="M14.707 10.293a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 111.414-1.414L9 12.586V5a1 1 0 012 0v7.586l2.293-2.293a1 1 0 011.414 0z" clipRule="evenodd" />
                            </svg>
                        `}
                        ${trend.value}%
                    </span>
                `}
            </div>
            
            ${subtitle && html`
                <p 
                    className="mt-1 text-sm"
                    style=${{ color: 'var(--text-secondary)' }}
                >
                    ${subtitle}
                </p>
            `}
        </div>
    `;
}
