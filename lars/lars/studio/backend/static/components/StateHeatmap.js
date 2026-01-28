/**
 * StateHeatmap Component
 * ======================
 * US state choropleth map showing sighting density.
 */

import React, { useState, useEffect, useCallback } from 'react';
import htm from 'htm';
import { CardSkeleton, CardError, CardEmpty } from './Card.js';
import { useFilters } from '../app.js';

const html = htm.bind(React.createElement);

// Simplified US state positions for a tile-based map
const STATE_GRID = {
    'AK': [0, 0], 'ME': [10, 0],
    'WA': [1, 1], 'MT': [2, 1], 'ND': [3, 1], 'MN': [4, 1], 'WI': [5, 1], 'MI': [6, 1], 'VT': [9, 1], 'NH': [10, 1],
    'OR': [1, 2], 'ID': [2, 2], 'WY': [3, 2], 'SD': [4, 2], 'IA': [5, 2], 'IL': [6, 2], 'IN': [7, 2], 'OH': [8, 2], 'PA': [9, 2], 'NY': [10, 2], 'MA': [11, 2],
    'CA': [1, 3], 'NV': [2, 3], 'UT': [3, 3], 'CO': [4, 3], 'NE': [4, 3], 'MO': [5, 3], 'KY': [7, 3], 'WV': [8, 3], 'VA': [9, 3], 'MD': [10, 3], 'NJ': [10, 3], 'CT': [11, 3], 'RI': [11, 3],
    'AZ': [2, 4], 'NM': [3, 4], 'KS': [4, 4], 'AR': [5, 4], 'TN': [6, 4], 'NC': [8, 4], 'SC': [9, 4], 'DC': [10, 4], 'DE': [10, 4],
    'OK': [4, 5], 'LA': [5, 5], 'MS': [6, 5], 'AL': [7, 5], 'GA': [8, 5],
    'TX': [4, 6], 'FL': [9, 6],
    'HI': [0, 7]
};

export function StateHeatmap({ endpoint }) {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [hoveredState, setHoveredState] = useState(null);
    
    let filters = { filters: {} };
    try {
        filters = useFilters();
    } catch (e) {
        // Context not available
    }

    const buildParams = useCallback(() => {
        const params = new URLSearchParams();
        if (filters.filters) {
            Object.entries(filters.filters).forEach(([key, value]) => {
                if (value !== null && value !== undefined && value !== '') {
                    params.set(key, value);
                }
            });
        }
        return params.toString();
    }, [filters.filters]);

    const fetchData = useCallback(async () => {
        if (!endpoint) return;
        
        setLoading(true);
        setError(null);
        
        try {
            const params = buildParams();
            const url = params ? `${endpoint}?${params}` : endpoint;
            const response = await fetch(url);
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            
            const result = await response.json();
            setData(result.data || result);
        } catch (err) {
            setError(err);
        } finally {
            setLoading(false);
        }
    }, [endpoint, buildParams]);

    useEffect(() => {
        fetchData();
    }, [fetchData]);

    useEffect(() => {
        const handleRefresh = () => fetchData();
        window.addEventListener('dashboard-refresh', handleRefresh);
        return () => window.removeEventListener('dashboard-refresh', handleRefresh);
    }, [fetchData]);

    if (loading) return html`<${CardSkeleton} lines=${5} />`;
    if (error) return html`<${CardError} error=${error} onRetry=${fetchData} />`;
    if (!data || data.length === 0) return html`<${CardEmpty} message="No state data available" />`;

    // Build state -> count map
    const stateData = {};
    let maxCount = 0;
    data.forEach(row => {
        if (row.state && row.sightings) {
            stateData[row.state] = row.sightings;
            maxCount = Math.max(maxCount, row.sightings);
        }
    });

    // Get color based on sighting count
    const getColor = (count) => {
        if (!count) return 'var(--bg-tertiary)';
        const intensity = count / maxCount;
        if (intensity > 0.8) return '#065f46'; // Dark green
        if (intensity > 0.6) return '#059669'; // Green
        if (intensity > 0.4) return '#10b981'; // Medium green
        if (intensity > 0.2) return '#34d399'; // Light green
        return '#6ee7b7'; // Very light green
    };

    // Create grid
    const gridRows = 8;
    const gridCols = 12;
    const cellSize = 'min(60px, 6vw)';

    return html`
        <div className="relative">
            <!-- Grid Container -->
            <div 
                className="grid gap-1 mx-auto"
                style=${{ 
                    gridTemplateColumns: `repeat(${gridCols}, ${cellSize})`,
                    gridTemplateRows: `repeat(${gridRows}, ${cellSize})`,
                    maxWidth: 'fit-content'
                }}
            >
                ${Object.entries(STATE_GRID).map(([state, [col, row]]) => {
                    const count = stateData[state] || 0;
                    const isHovered = hoveredState === state;
                    
                    return html`
                        <div
                            key=${state}
                            onMouseEnter=${() => setHoveredState(state)}
                            onMouseLeave=${() => setHoveredState(null)}
                            className="flex items-center justify-center text-xs font-bold cursor-pointer transition-all"
                            style=${
                                {
                                    gridColumn: col + 1,
                                    gridRow: row + 1,
                                    backgroundColor: getColor(count),
                                    color: count ? 'white' : 'var(--text-tertiary)',
                                    borderRadius: '4px',
                                    transform: isHovered ? 'scale(1.1)' : 'scale(1)',
                                    zIndex: isHovered ? 10 : 1,
                                    boxShadow: isHovered ? 'var(--shadow-lg)' : 'none',
                                }
                            }
                        >
                            ${state}
                        </div>
                    `;
                })}
            </div>

            <!-- Hover Tooltip -->
            ${hoveredState && html`
                <div 
                    className="absolute bottom-0 left-1/2 transform -translate-x-1/2 px-4 py-2 rounded-lg text-sm font-medium"
                    style=${{ 
                        backgroundColor: 'var(--bg-secondary)', 
                        border: '1px solid var(--border-primary)',
                        boxShadow: 'var(--shadow-md)',
                        color: 'var(--text-primary)'
                    }}
                >
                    ${hoveredState}: ${stateData[hoveredState] || 0} sightings
                </div>
            `}

            <!-- Legend -->
            <div className="flex items-center justify-center gap-2 mt-6 text-xs" style=${{ color: 'var(--text-secondary)' }}>
                <span>Fewer</span>
                ${['#6ee7b7', '#34d399', '#10b981', '#059669', '#065f46'].map((color, i) => html`
                    <div 
                        key=${i}
                        className="w-6 h-4 rounded"
                        style=${{ backgroundColor: color }}
                    />
                `)}
                <span>More</span>
            </div>
        </div>
    `;
}
