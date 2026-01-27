/**
 * Filter Components
 * =================
 * Data-driven filter components for dashboards.
 */

import React, { useState, useEffect, useRef } from 'react';
import htm from 'htm';
const html = htm.bind(React.createElement);

/**
 * Filter container with optional clear button
 */
export function Filters({ children, onClear = null }) {
    return html`
        <div className="flex flex-wrap items-end gap-4">
            ${children}
            ${onClear && html`
                <button
                    onClick=${onClear}
                    className="px-3 py-2 text-sm rounded-md transition-colors btn-ghost"
                >
                    Clear all
                </button>
            `}
        </div>
    `;
}

/**
 * Dropdown filter with static or API-loaded options
 */
export function FilterDropdown({
    label,
    value,
    onChange,
    options: staticOptions = null,
    endpoint = null,
    placeholder = 'Select...',
    allowEmpty = true,
    emptyLabel = 'All',
    className = '',
}) {
    const [options, setOptions] = useState(staticOptions || []);
    const [loading, setLoading] = useState(!!endpoint);

    // Load options from API
    useEffect(() => {
        if (!endpoint) return;
        
        setLoading(true);
        fetch(endpoint)
            .then(r => r.json())
            .then(data => {
                const opts = Array.isArray(data) ? data : (data.data || []);
                setOptions(opts);
            })
            .catch(console.error)
            .finally(() => setLoading(false));
    }, [endpoint]);

    // Update if static options change
    useEffect(() => {
        if (staticOptions) setOptions(staticOptions);
    }, [staticOptions]);

    // Normalize options to { value, label } format
    const normalizedOptions = options.map(opt => 
        typeof opt === 'string' ? { value: opt, label: opt } : opt
    );

    return html`
        <div className=${`flex flex-col gap-1 ${className}`}>
            ${label && html`
                <label className="text-sm font-medium" style=${{ color: 'var(--text-secondary)' }}>${label}</label>
            `}
            <select
                value=${value || ''}
                onChange=${(e) => onChange(e.target.value || null)}
                disabled=${loading}
                className="px-3 py-2 rounded-md shadow-sm text-sm min-w-[150px] disabled:opacity-50 disabled:cursor-wait"
                style=${{
                    backgroundColor: 'var(--bg-input)',
                    border: '1px solid var(--border-primary)',
                    color: 'var(--text-primary)',
                }}
            >
                ${allowEmpty && html`
                    <option value="">${loading ? 'Loading...' : emptyLabel}</option>
                `}
                ${normalizedOptions.map(opt => html`
                    <option key=${opt.value} value=${opt.value}>
                        ${opt.label}
                    </option>
                `)}
            </select>
        </div>
    `;
}

/**
 * Date range filter
 */
export function FilterDateRange({
    label,
    startValue,
    endValue,
    onStartChange,
    onEndChange,
    minDate = null,
    maxDate = null,
    className = '',
}) {
    return html`
        <div className=${`flex flex-col gap-1 ${className}`}>
            ${label && html`
                <label className="text-sm font-medium" style=${{ color: 'var(--text-secondary)' }}>${label}</label>
            `}
            <div className="flex items-center gap-2">
                <input
                    type="date"
                    value=${startValue || ''}
                    onChange=${(e) => onStartChange(e.target.value || null)}
                    min=${minDate}
                    max=${endValue || maxDate}
                    className="px-3 py-2 rounded-md shadow-sm text-sm"
                    style=${{
                        backgroundColor: 'var(--bg-input)',
                        border: '1px solid var(--border-primary)',
                        color: 'var(--text-primary)',
                    }}
                />
                <span style=${{ color: 'var(--text-tertiary)' }}>to</span>
                <input
                    type="date"
                    value=${endValue || ''}
                    onChange=${(e) => onEndChange(e.target.value || null)}
                    min=${startValue || minDate}
                    max=${maxDate}
                    className="px-3 py-2 rounded-md shadow-sm text-sm"
                    style=${{
                        backgroundColor: 'var(--bg-input)',
                        border: '1px solid var(--border-primary)',
                        color: 'var(--text-primary)',
                    }}
                />
            </div>
        </div>
    `;
}

/**
 * Month range filter (YYYY-MM format)
 * Use this when your data is aggregated by month.
 */
export function FilterMonthRange({
    label,
    startValue,
    endValue,
    onStartChange,
    onEndChange,
    minDate = null,
    maxDate = null,
    className = '',
}) {
    return html`
        <div className=${`flex flex-col gap-1 ${className}`}>
            ${label && html`
                <label className="text-sm font-medium" style=${{ color: 'var(--text-secondary)' }}>${label}</label>
            `}
            <div className="flex items-center gap-2">
                <input
                    type="month"
                    value=${startValue || ''}
                    onChange=${(e) => onStartChange(e.target.value || null)}
                    min=${minDate}
                    max=${endValue || maxDate}
                    className="px-3 py-2 rounded-md shadow-sm text-sm"
                    style=${{
                        backgroundColor: 'var(--bg-input)',
                        border: '1px solid var(--border-primary)',
                        color: 'var(--text-primary)',
                    }}
                />
                <span style=${{ color: 'var(--text-tertiary)' }}>to</span>
                <input
                    type="month"
                    value=${endValue || ''}
                    onChange=${(e) => onEndChange(e.target.value || null)}
                    min=${startValue || minDate}
                    max=${maxDate}
                    className="px-3 py-2 rounded-md shadow-sm text-sm"
                    style=${{
                        backgroundColor: 'var(--bg-input)',
                        border: '1px solid var(--border-primary)',
                        color: 'var(--text-primary)',
                    }}
                />
            </div>
        </div>
    `;
}

/**
 * Search/text filter with debounce
 */
export function FilterSearch({
    label,
    value,
    onChange,
    placeholder = 'Search...',
    debounceMs = 300,
    className = '',
}) {
    const [localValue, setLocalValue] = useState(value || '');
    const timeoutRef = useRef(null);

    // Sync with external value
    useEffect(() => {
        setLocalValue(value || '');
    }, [value]);

    const handleChange = (newValue) => {
        setLocalValue(newValue);
        
        // Debounce the onChange callback
        if (timeoutRef.current) {
            clearTimeout(timeoutRef.current);
        }
        timeoutRef.current = setTimeout(() => {
            onChange(newValue || null);
        }, debounceMs);
    };

    return html`
        <div className=${`flex flex-col gap-1 ${className}`}>
            ${label && html`
                <label className="text-sm font-medium" style=${{ color: 'var(--text-secondary)' }}>${label}</label>
            `}
            <div className="relative">
                <input
                    type="text"
                    value=${localValue}
                    onChange=${(e) => handleChange(e.target.value)}
                    placeholder=${placeholder}
                    className="pl-9 pr-3 py-2 rounded-md shadow-sm text-sm w-full min-w-[200px]"
                    style=${{
                        backgroundColor: 'var(--bg-input)',
                        border: '1px solid var(--border-primary)',
                        color: 'var(--text-primary)',
                    }}
                />
                <svg 
                    className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4"
                    style=${{ color: 'var(--text-tertiary)' }}
                    fill="none" 
                    stroke="currentColor" 
                    viewBox="0 0 24 24"
                >
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth=${2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                </svg>
            </div>
        </div>
    `;
}
