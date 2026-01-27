/**
 * LARS Dashboard — Frontend
 * =========================
 * React app using htm (JSX-like syntax, no build step needed).
 *
 * Architecture
 * ------------
 * SetupProvider  → Calls /api/setup once, shows loading until ready
 * FilterProvider → Holds filter state, passes to all components
 * Dashboard      → Layout with KPIs, Charts, Grid
 *
 * Components (in /components/)
 * ----------------------------
 * - KPICard:  Single metric display
 * - Chart:    Line/bar/area/pie via Recharts, fetches from endpoint
 * - DataGrid: AG Grid table, fetches from endpoint
 * - Card:     Container with title
 * - Filters:  FilterDropdown, FilterMonthRange, FilterSearch
 *
 * Data Flow
 * ---------
 * Components with `endpoint` prop automatically:
 * 1. Read filters from FilterContext
 * 2. Build query string from filter state
 * 3. Fetch endpoint?start_date=...&category=...
 * 4. Re-fetch when filters change
 */

import React, { useState, useEffect, createContext, useContext } from 'react';
import { createRoot } from 'react-dom/client';
import htm from 'htm';

// Bind htm to React.createElement
const html = htm.bind(React.createElement);

// Components
import { Layout } from './components/Layout.js';
import { Card } from './components/Card.js';
import { KPICard } from './components/KPICard.js';
import { Chart } from './components/Chart.js';
import { DataGrid } from './components/DataGrid.js';
import { Filters, FilterDropdown, FilterDateRange, FilterMonthRange, FilterSearch } from './components/Filters.js';

// =============================================================================
// Setup Context (tracks whether sample data has been initialized)
// =============================================================================

const SetupContext = createContext({ ready: false });

export function useSetup() {
    return useContext(SetupContext);
}

function SetupProvider({ children }) {
    const [ready, setReady] = useState(false);
    const [error, setError] = useState(null);

    useEffect(() => {
        // Run setup once on page load to initialize sample data
        fetch('/api/setup', { method: 'POST' })
            .then(r => {
                if (!r.ok) throw new Error(`Setup failed: ${r.status}`);
                return r.json();
            })
            .then(() => setReady(true))
            .catch(err => {
                console.error('Setup error:', err);
                setError(err);
                // Still mark ready so UI renders (with potential errors)
                setReady(true);
            });
    }, []);

    if (!ready) {
        return html`
            <div className="min-h-screen flex items-center justify-center" style=${{ backgroundColor: 'var(--bg-primary)' }}>
                <div className="text-center">
                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 mx-auto mb-4" style=${{ borderColor: 'var(--accent-primary)' }}></div>
                    <p style=${{ color: 'var(--text-secondary)' }}>Initializing dashboard...</p>
                </div>
            </div>
        `;
    }

    return html`
        <${SetupContext.Provider} value=${{ ready, error }}>
            ${children}
        <//>
    `;
}

// =============================================================================
// Filter Context (shared filter state across components)
// =============================================================================

const FilterContext = createContext({});

export function useFilters() {
    return useContext(FilterContext);
}

// Export html for components to use
export { html };

function FilterProvider({ children }) {
    // NOTE: Filter keys must match backend API parameter names (snake_case)
    const [filters, setFilters] = useState({
        start_date: null,
        end_date: null,
        category: null,
        search: '',
    });

    const updateFilter = (key, value) => {
        setFilters(prev => ({ ...prev, [key]: value }));
    };

    const clearFilters = () => {
        setFilters({
            start_date: null,
            end_date: null,
            category: null,
            search: '',
        });
    };

    return html`
        <${FilterContext.Provider} value=${{ filters, updateFilter, clearFilters }}>
            ${children}
        <//>
    `;
}

// =============================================================================
// Main Dashboard
// =============================================================================

function Dashboard() {
    const { filters } = useFilters();
    const [kpis, setKpis] = useState(null);

    // Build query string from filters
    const buildQueryString = (filterObj) => {
        const params = new URLSearchParams();
        Object.entries(filterObj).forEach(([key, value]) => {
            if (value !== null && value !== undefined && value !== '') {
                params.set(key, value);
            }
        });
        const str = params.toString();
        return str ? `?${str}` : '';
    };

    // Fetch KPIs with filters
    useEffect(() => {
        const url = `/api/data/example-kpi${buildQueryString(filters)}`;
        fetch(url)
            .then(r => r.json())
            .then(setKpis)
            .catch(console.error);
    }, [filters]); // Refetch when filters change

    return html`
        <div className="space-y-6">
            <!-- KPI Row -->
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <${KPICard} 
                    title="Total Revenue" 
                    value=${kpis?.total_revenue} 
                    format="currency" 
                />
                <${KPICard} 
                    title="Total Orders" 
                    value=${kpis?.total_orders} 
                    format="number" 
                />
                <${KPICard} 
                    title="Avg Order Value" 
                    value=${kpis?.avg_order_value} 
                    format="currency" 
                />
                <${KPICard}
                    title="Profit Margin"
                    value=${kpis?.profit_margin}
                    format="percent"
                />
            </div>

            <!-- Charts Row -->
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <${Card} title="Revenue Over Time">
                    <${Chart} 
                        endpoint="/api/data/example-chart"
                        type="line"
                        xKey="month"
                        yKeys=${[
                            { key: 'revenue', color: '#3b82f6', name: 'Revenue' },
                            { key: 'costs', color: '#ef4444', name: 'Costs' },
                        ]}
                        height=${300}
                    />
                <//>

                <${Card} title="Revenue vs Costs">
                    <${Chart} 
                        endpoint="/api/data/example-chart"
                        type="bar"
                        xKey="month"
                        yKeys=${[
                            { key: 'revenue', color: '#3b82f6', name: 'Revenue' },
                            { key: 'costs', color: '#ef4444', name: 'Costs' },
                        ]}
                        height=${300}
                    />
                <//>
            </div>

            <!-- Data Grid -->
            <${Card} title="Recent Items" className="h-[500px]">
                <${DataGrid}
                    endpoint="/api/data/example-grid"
                    columns=${[
                        { field: 'id', headerName: 'ID', width: 80 },
                        { field: 'name', headerName: 'Name', flex: 1 },
                        { field: 'category', headerName: 'Category', width: 120 },
                        { field: 'status', headerName: 'Status', width: 100 },
                        { field: 'value', headerName: 'Value', width: 100, type: 'numericColumn' },
                        { field: 'created_at', headerName: 'Created', width: 120 },
                    ]}
                />
            <//>
        </div>
    `;
}

// =============================================================================
// Filter Bar
// =============================================================================

function DashboardFilters() {
    const { filters, updateFilter, clearFilters } = useFilters();

    return html`
        <${Filters} onClear=${clearFilters}>
            <${FilterMonthRange}
                label="Date Range"
                startValue=${filters.start_date}
                endValue=${filters.end_date}
                onStartChange=${(v) => updateFilter('start_date', v)}
                onEndChange=${(v) => updateFilter('end_date', v)}
                minDate="2024-01"
                maxDate="2024-12"
            />
            <${FilterDropdown}
                label="Category"
                value=${filters.category}
                endpoint="/api/filters/example-categories"
                onChange=${(v) => updateFilter('category', v)}
                emptyLabel="All Categories"
            />
            <${FilterSearch}
                label="Search"
                value=${filters.search}
                onChange=${(v) => updateFilter('search', v)}
                placeholder="Search items..."
            />
        <//>
    `;
}

// =============================================================================
// App Root
// =============================================================================

function App() {
    return html`
        <${SetupProvider}>
            <${FilterProvider}>
                <${Layout}
                    title="LARS Dashboard"
                    subtitle="Built with LARS semantic SQL"
                    filters=${html`<${DashboardFilters} />`}
                >
                    <${Dashboard} />
                <//>
            <//>
        <//>
    `;
}

// =============================================================================
// Mount
// =============================================================================

const root = createRoot(document.getElementById('root'));
root.render(html`<${App} />`);
