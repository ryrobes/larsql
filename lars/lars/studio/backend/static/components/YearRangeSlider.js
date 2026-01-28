/**
 * YearRangeSlider Component
 * ==========================
 * Dual slider for selecting year range.
 */

import React, { useState, useEffect } from 'react';
import htm from 'htm';
const html = htm.bind(React.createElement);

export function YearRangeSlider({
    startValue,
    endValue,
    onStartChange,
    onEndChange,
    className = '',
}) {
    const [minYear, setMinYear] = useState(1900);
    const [maxYear, setMaxYear] = useState(2024);
    const [loading, setLoading] = useState(true);

    // Fetch year range from API
    useEffect(() => {
        fetch('/api/filters/year-range')
            .then(r => r.json())
            .then(data => {
                setMinYear(data.min_year || 1900);
                setMaxYear(data.max_year || 2024);
            })
            .catch(console.error)
            .finally(() => setLoading(false));
    }, []);

    const currentStart = startValue || minYear;
    const currentEnd = endValue || maxYear;

    return html`
        <div className=${`flex flex-col gap-1 ${className}`}>
            <label className="text-sm font-medium" style=${{ color: 'var(--text-secondary)' }}>
                Year Range
            </label>
            
            ${loading ? html`
                <div className="px-3 py-2 text-sm" style=${{ color: 'var(--text-secondary)' }}>
                    Loading...
                </div>
            ` : html`
                <div className="flex flex-col gap-2">
                    <!-- Display current range -->
                    <div className="flex items-center gap-2 text-sm" style=${{ color: 'var(--text-primary)' }}>
                        <span className="font-medium">${currentStart}</span>
                        <span style=${{ color: 'var(--text-tertiary)' }}>to</span>
                        <span className="font-medium">${currentEnd}</span>
                    </div>

                    <!-- Sliders container -->
                    <div className="flex items-center gap-3">
                        <!-- Start year slider -->
                        <div className="flex-1 flex items-center gap-2">
                            <span className="text-xs" style=${{ color: 'var(--text-tertiary)' }}>From</span>
                            <input
                                type="range"
                                min=${minYear}
                                max=${maxYear}
                                value=${currentStart}
                                onChange=${(e) => {
                                    const val = parseInt(e.target.value);
                                    if (val <= currentEnd) {
                                        onStartChange(val);
                                    }
                                }}
                                className="flex-1 h-2 rounded-lg appearance-none cursor-pointer"
                                style=${
                                    {
                                        background: `linear-gradient(to right, var(--bg-tertiary) 0%, var(--accent-primary) ${((currentStart - minYear) / (maxYear - minYear)) * 100}%, var(--accent-primary) ${((currentEnd - minYear) / (maxYear - minYear)) * 100}%, var(--bg-tertiary) 100%)`,
                                    }
                                }
                            />
                        </div>

                        <!-- End year slider -->
                        <div className="flex-1 flex items-center gap-2">
                            <span className="text-xs" style=${{ color: 'var(--text-tertiary)' }}>To</span>
                            <input
                                type="range"
                                min=${minYear}
                                max=${maxYear}
                                value=${currentEnd}
                                onChange=${(e) => {
                                    const val = parseInt(e.target.value);
                                    if (val >= currentStart) {
                                        onEndChange(val);
                                    }
                                }}
                                className="flex-1 h-2 rounded-lg appearance-none cursor-pointer"
                                style=${
                                    {
                                        background: `linear-gradient(to right, var(--bg-tertiary) 0%, var(--accent-primary) ${((currentStart - minYear) / (maxYear - minYear)) * 100}%, var(--accent-primary) ${((currentEnd - minYear) / (maxYear - minYear)) * 100}%, var(--bg-tertiary) 100%)`,
                                    }
                                }
                            />
                        </div>
                    </div>

                    <!-- Reset button -->
                    ${(startValue || endValue) && html`
                        <button
                            onClick=${() => {
                                onStartChange(null);
                                onEndChange(null);
                            }}
                            className="text-xs self-start"
                            style=${{ color: 'var(--accent-primary)' }}
                        >
                            Reset to all years
                        </button>
                    `}
                </div>
            `}
        </div>

        <style>
            input[type="range"]::-webkit-slider-thumb {
                appearance: none;
                width: 16px;
                height: 16px;
                border-radius: 50%;
                background: var(--accent-primary);
                cursor: pointer;
                border: 2px solid white;
                box-shadow: 0 1px 3px rgba(0,0,0,0.3);
            }
            
            input[type="range"]::-moz-range-thumb {
                width: 16px;
                height: 16px;
                border-radius: 50%;
                background: var(--accent-primary);
                cursor: pointer;
                border: 2px solid white;
                box-shadow: 0 1px 3px rgba(0,0,0,0.3);
            }
        </style>
    `;
}
