/**
 * DataGrid Component
 * ==================
 * Wrapper around AG Grid with data fetching and common patterns.
 */

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import htm from 'htm';
import { AgGridReact } from 'ag-grid-react';
import { CardSkeleton, CardError, CardEmpty } from './Card.js';
import { useFilters } from '../app.js';

const html = htm.bind(React.createElement);

export function DataGrid({
    // Data source
    endpoint = null,
    data: staticData = null,
    
    // Column definitions
    columns = [],
    
    // Grid options
    pagination = true,
    pageSize = 25,
    sortable = true,
    filterable = true,
    resizable = true,
    
    // Selection
    selectable = false,
    onSelectionChange = null,
    
    // Styling
    height = '100%',
    theme = 'ag-theme-lars ag-theme-alpine',
    
    // Row click handler
    onRowClick = null,
}) {
    const [rowData, setRowData] = useState(staticData);
    const [loading, setLoading] = useState(!staticData);
    const [error, setError] = useState(null);
    
    let filters = { filters: {} };
    try {
        filters = useFilters();
    } catch (e) {
        // Context not available
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
            setRowData(result.data || result);
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

    // Default column definition
    const defaultColDef = useMemo(() => ({
        sortable,
        filter: filterable,
        resizable,
        minWidth: 80,
    }), [sortable, filterable, resizable]);

    // Grid options
    const gridOptions = useMemo(() => ({
        pagination,
        paginationPageSize: pageSize,
        paginationPageSizeSelector: [10, 25, 50, 100],
        rowSelection: selectable ? 'multiple' : undefined,
        onSelectionChanged: selectable ? (event) => {
            const selected = event.api.getSelectedRows();
            onSelectionChange?.(selected);
        } : undefined,
        onRowClicked: onRowClick ? (event) => {
            onRowClick(event.data);
        } : undefined,
        suppressCellFocus: true,
        animateRows: true,
    }), [pagination, pageSize, selectable, onSelectionChange, onRowClick]);

    // Render states
    if (loading) return html`<${GridSkeleton} height=${height} />`;
    if (error) return html`<${CardError} error=${error} onRetry=${fetchData} />`;
    if (!rowData || rowData.length === 0) return html`<${CardEmpty} message="No data to display" />`;

    return html`
        <div className=${theme} style=${{ height, width: '100%' }}>
            <${AgGridReact}
                rowData=${rowData}
                columnDefs=${columns}
                defaultColDef=${defaultColDef}
                ...${gridOptions}
            />
        </div>
    `;
}

// Loading skeleton for grids
function GridSkeleton({ height }) {
    return html`
        <div className="animate-pulse" style=${{ height }}>
            <!-- Header -->
            <div className="flex gap-4 p-3 border-b" style=${{ backgroundColor: 'var(--bg-tertiary)', borderColor: 'var(--border-primary)' }}>
                ${[1, 2, 3, 4, 5].map(i => html`
                    <div key=${i} className="h-4 rounded flex-1" style=${{ backgroundColor: 'var(--border-primary)' }} />
                `)}
            </div>
            <!-- Rows -->
            ${[1, 2, 3, 4, 5, 6, 7, 8].map(i => html`
                <div key=${i} className="flex gap-4 p-3 border-b" style=${{ borderColor: 'var(--border-primary)' }}>
                    ${[1, 2, 3, 4, 5].map(j => html`
                        <div key=${j} className="h-4 rounded flex-1" style=${{ backgroundColor: 'var(--bg-tertiary)' }} />
                    `)}
                </div>
            `)}
        </div>
    `;
}
