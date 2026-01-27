/**
 * Chart Component
 * ===============
 * Wrapper around Recharts with data fetching, loading states, and common patterns.
 */

import React, { useState, useEffect, useCallback } from 'react';
import htm from 'htm';
import {
    LineChart, Line,
    BarChart, Bar,
    AreaChart, Area,
    PieChart, Pie, Cell,
    XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer
} from 'recharts';
import { CardSkeleton, CardError, CardEmpty } from './Card.js';
import { useFilters } from '../app.js';

const html = htm.bind(React.createElement);

// Default color palette
const COLORS = ['#3b82f6', '#ef4444', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899', '#06b6d4', '#84cc16'];

export function Chart({
    // Data source (provide one)
    endpoint = null,      // API endpoint to fetch from
    data: staticData = null,  // Or pass data directly
    
    // Chart type
    type = 'line',        // 'line' | 'bar' | 'area' | 'pie'
    
    // Data mapping
    xKey = 'x',           // Key for x-axis
    yKeys = [{ key: 'y', color: COLORS[0], name: 'Value' }],  // Array of { key, color, name }
    
    // Pie chart specific
    nameKey = 'name',     // For pie charts
    valueKey = 'value',   // For pie charts
    
    // Display options
    height = 300,
    showGrid = true,
    showLegend = true,
    showTooltip = true,
    stacked = false,
}) {
    const [data, setData] = useState(staticData);
    const [loading, setLoading] = useState(!staticData);
    const [error, setError] = useState(null);
    
    let filters = { filters: {} };
    try {
        filters = useFilters();
    } catch (e) {
        // Context not available, use empty filters
    }

    // Build query params from filters
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

    // Fetch data
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

    // Initial fetch and refetch on filter change
    useEffect(() => {
        if (endpoint) {
            fetchData();
        }
    }, [fetchData]);

    // Listen for refresh events
    useEffect(() => {
        const handleRefresh = () => fetchData();
        window.addEventListener('dashboard-refresh', handleRefresh);
        return () => window.removeEventListener('dashboard-refresh', handleRefresh);
    }, [fetchData]);

    // Render states
    if (loading) return html`<${ChartSkeleton} height=${height} />`;
    if (error) return html`<${CardError} error=${error} onRetry=${fetchData} />`;
    if (!data || data.length === 0) return html`<${CardEmpty} message="No data to display" />`;

    // Common props for responsive container
    const containerProps = {
        width: '100%',
        height: height,
    };

    // Render the appropriate chart type
    switch (type) {
        case 'bar':
            return html`
                <${ResponsiveContainer} ...${containerProps}>
                    <${BarChart} data=${data}>
                        ${showGrid && html`<${CartesianGrid} strokeDasharray="3 3" stroke="#334155" />`}
                        <${XAxis} dataKey=${xKey} tick=${{ fontSize: 12, fill: 'var(--text-secondary)' }} />
                        <${YAxis} tick=${{ fontSize: 12, fill: 'var(--text-secondary)' }} />
                        ${showTooltip && html`<${Tooltip} contentStyle=${{ backgroundColor: 'var(--bg-secondary)', border: '1px solid var(--border-primary)' }} />`}
                        ${showLegend && html`<${Legend} />`}
                        ${yKeys.map((yConfig, i) => html`
                            <${Bar}
                                key=${yConfig.key}
                                dataKey=${yConfig.key}
                                name=${yConfig.name || yConfig.key}
                                fill=${yConfig.color || COLORS[i % COLORS.length]}
                                stackId=${stacked ? 'stack' : undefined}
                            />
                        `)}
                    <//>
                <//>
            `;

        case 'area':
            return html`
                <${ResponsiveContainer} ...${containerProps}>
                    <${AreaChart} data=${data}>
                        ${showGrid && html`<${CartesianGrid} strokeDasharray="3 3" stroke="#334155" />`}
                        <${XAxis} dataKey=${xKey} tick=${{ fontSize: 12, fill: 'var(--text-secondary)' }} />
                        <${YAxis} tick=${{ fontSize: 12, fill: 'var(--text-secondary)' }} />
                        ${showTooltip && html`<${Tooltip} contentStyle=${{ backgroundColor: 'var(--bg-secondary)', border: '1px solid var(--border-primary)' }} />`}
                        ${showLegend && html`<${Legend} />`}
                        ${yKeys.map((yConfig, i) => html`
                            <${Area}
                                key=${yConfig.key}
                                type="monotone"
                                dataKey=${yConfig.key}
                                name=${yConfig.name || yConfig.key}
                                fill=${yConfig.color || COLORS[i % COLORS.length]}
                                stroke=${yConfig.color || COLORS[i % COLORS.length]}
                                fillOpacity=${0.3}
                                stackId=${stacked ? 'stack' : undefined}
                            />
                        `)}
                    <//>
                <//>
            `;

        case 'pie':
            return html`
                <${ResponsiveContainer} ...${containerProps}>
                    <${PieChart}>
                        <${Pie}
                            data=${data}
                            dataKey=${valueKey}
                            nameKey=${nameKey}
                            cx="50%"
                            cy="50%"
                            outerRadius=${Math.min(height, 300) / 3}
                            label=${({ name, percent }) => `${name}: ${(percent * 100).toFixed(0)}%`}
                            labelLine=${false}
                        >
                            ${data.map((_, index) => html`
                                <${Cell} key=${index} fill=${COLORS[index % COLORS.length]} />
                            `)}
                        <//>
                        ${showTooltip && html`<${Tooltip} />`}
                        ${showLegend && html`<${Legend} />`}
                    <//>
                <//>
            `;

        case 'line':
        default:
            return html`
                <${ResponsiveContainer} ...${containerProps}>
                    <${LineChart} data=${data}>
                        ${showGrid && html`<${CartesianGrid} strokeDasharray="3 3" stroke="#334155" />`}
                        <${XAxis} dataKey=${xKey} tick=${{ fontSize: 12, fill: 'var(--text-secondary)' }} />
                        <${YAxis} tick=${{ fontSize: 12, fill: 'var(--text-secondary)' }} />
                        ${showTooltip && html`<${Tooltip} contentStyle=${{ backgroundColor: 'var(--bg-secondary)', border: '1px solid var(--border-primary)' }} />`}
                        ${showLegend && html`<${Legend} />`}
                        ${yKeys.map((yConfig, i) => html`
                            <${Line}
                                key=${yConfig.key}
                                type="monotone"
                                dataKey=${yConfig.key}
                                name=${yConfig.name || yConfig.key}
                                stroke=${yConfig.color || COLORS[i % COLORS.length]}
                                strokeWidth=${2}
                                dot=${{ r: 3 }}
                                activeDot=${{ r: 5 }}
                            />
                        `)}
                    <//>
                <//>
            `;
    }
}

// Loading skeleton for charts
function ChartSkeleton({ height }) {
    return html`
        <div className="animate-pulse" style=${{ height }}>
            <div className="h-full rounded flex items-end justify-around p-4 gap-2" style=${{ backgroundColor: 'var(--bg-tertiary)' }}>
                ${[40, 65, 45, 80, 55, 70, 50, 75, 60, 85, 55, 70].map((h, i) => html`
                    <div 
                        key=${i} 
                        className="rounded-t w-full"
                        style=${{ height: `${h}%`, backgroundColor: 'var(--border-primary)' }}
                    />
                `)}
            </div>
        </div>
    `;
}
