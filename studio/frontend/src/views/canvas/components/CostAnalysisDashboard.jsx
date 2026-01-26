/**
 * CostAnalysisDashboard - Cost analysis rendered as a Hyper dashboard
 *
 * This component generates SQL that creates a cost analysis dashboard
 * using the same rendering infrastructure as regular Hyper queries.
 * This is the "build the tool with the tool" approach.
 *
 * Panels:
 * 1. Cost Waterfall (Mermaid) - Flow from estimate to actual
 * 2. Estimate vs Actual (Plotly bar) - Per-operator comparison
 * 3. Token Breakdown (Plotly donut) - Input vs output tokens
 * 4. Cache Effectiveness (Plotly gauge) - Overall cache hit rate
 * 5. Operator Details (Table) - Detailed breakdown
 * 6. Optimization Hints (Text) - Suggestions
 */

import React, { useMemo } from 'react';
import CanvasRenderer from './CanvasRenderer';
import './CostAnalysisDashboard.css';

/**
 * Generate the cost waterfall Mermaid diagram
 */
function generateWaterfallMermaid(explainData, actualCostData) {
  const operators = [];

  // Collect all operators from explain data
  explainData?.forEach((explain) => {
    (explain.operations || []).forEach(op => {
      operators.push({
        name: op.function,
        estimated: op.estimated_cost || 0,
        calls: op.estimated_llm_calls || 0,
        cacheRate: op.cache_hit_rate || 0,
      });
    });
    (explain.aggregates || []).forEach(agg => {
      operators.push({
        name: agg.function,
        estimated: agg.estimated_cost || 0,
        calls: agg.estimated_groups || 0,
        cacheRate: 0,
      });
    });
  });

  // Match with actual costs if available
  const actualOperators = actualCostData?.operators || [];
  operators.forEach(op => {
    const actual = actualOperators.find(a =>
      a.cascade_id?.includes(op.name.toLowerCase()) ||
      op.name.toLowerCase().includes(a.cascade_id?.split('_').pop() || '')
    );
    if (actual) {
      op.actual = actual.cost || 0;
    }
  });

  // Build Mermaid diagram
  const totalEstimated = operators.reduce((sum, op) => sum + op.estimated, 0);
  const totalActual = actualCostData?.total_cost || 0;

  let mermaid = `graph TD
    subgraph Estimated
    EST["💰 Estimated<br/>$${totalEstimated.toFixed(4)}"]
    end
`;

  operators.forEach((op, idx) => {
    const nodeId = `OP${idx}`;
    const estCost = op.estimated.toFixed(4);
    mermaid += `    EST --> ${nodeId}["${op.name}<br/>$${estCost}"]
`;
  });

  if (totalActual > 0) {
    mermaid += `
    subgraph Actual
    ACT["✓ Actual<br/>$${totalActual.toFixed(4)}"]
    end
`;
    operators.forEach((op, idx) => {
      if (op.actual !== undefined) {
        mermaid += `    OP${idx} --> ACT
`;
      }
    });
  }

  return mermaid;
}

/**
 * Generate panel data for the cost analysis dashboard
 */
function generateDashboardPanels(explainData, actualCostData, callerId) {
  const panels = [];

  // Collect all operators
  const operators = [];
  let totalEstimatedCost = 0;
  let _totalEstimatedCalls = 0; // Used for future display
  let totalCacheHits = 0;
  let totalCacheTotal = 0;
  const hints = [];

  explainData?.forEach((explain) => {
    totalEstimatedCost += explain.estimatedCost || 0;
    _totalEstimatedCalls += explain.estimatedCalls || 0;

    (explain.operations || []).forEach(op => {
      operators.push({
        type: 'scalar',
        name: op.function,
        estimated_cost: op.estimated_cost || 0,
        calls: op.estimated_llm_calls || 0,
        cache_hits: op.cache_hits || 0,
        cache_total: op.cache_total || op.distinct_count || 0,
        cache_rate: op.cache_hit_rate || 0,
        model: op.model || 'default',
      });
      totalCacheHits += op.cache_hits || 0;
      totalCacheTotal += op.cache_total || op.distinct_count || 0;
    });

    (explain.aggregates || []).forEach(agg => {
      operators.push({
        type: 'aggregate',
        name: agg.function,
        estimated_cost: agg.estimated_cost || 0,
        calls: agg.estimated_groups || 0,
        cache_hits: 0,
        cache_total: 0,
        cache_rate: 0,
        model: agg.model || 'default',
      });
    });

    (explain.hints || []).forEach(h => {
      if (!hints.includes(h)) hints.push(h);
    });
  });

  const _totalActualCost = actualCostData?.total_cost || 0; // Used in future panels
  const actualOperators = actualCostData?.operators || [];
  const overallCacheRate = totalCacheTotal > 0 ? totalCacheHits / totalCacheTotal : 0;

  // Panel 1: Cost Summary Cards (using Plotly indicator)
  panels.push({
    name: 'Cost Summary',
    position: { col: 1, row: 1, width: 2, height: 1 },
    hide_title: false,
    hide_border: false,
    columns: ['format', 'config', 'label', 'value', 'delta', 'suffix'],
    data: [
      {
        format: 'plotly',
        config: {
          type: 'indicator',
          mode: 'number+delta',
          value: 'value',
          title: 'label',
          delta: { reference: 'delta' },
          number: { prefix: '$', valueformat: '.4f' },
        },
        label: 'Estimated Cost',
        value: totalEstimatedCost,
        delta: null,
        suffix: '',
      }
    ],
  });

  // Panel 2: Estimate vs Actual Bar Chart
  if (operators.length > 0) {
    const chartData = operators.map(op => {
      const actual = actualOperators.find(a =>
        a.cascade_id?.toLowerCase().includes(op.name.toLowerCase().replace('semantic_', ''))
      );
      return {
        operator: op.name.replace('semantic_', '').substring(0, 12),
        estimated: op.estimated_cost,
        actual: actual?.cost || 0,
      };
    });

    panels.push({
      name: 'Estimate vs Actual',
      position: { col: 1, row: 2, width: 1, height: 1 },
      hide_title: false,
      hide_border: false,
      columns: ['format', 'config', 'operator', 'estimated', 'actual'],
      data: chartData.map(d => ({
        format: 'vega-lite',
        config: {
          mark: 'bar',
          encoding: {
            x: { field: 'operator', type: 'nominal', axis: { labelAngle: -45 } },
            y: { field: 'value', type: 'quantitative', title: 'Cost ($)' },
            color: { field: 'type', type: 'nominal', legend: { title: 'Type' } },
            xOffset: { field: 'type' },
          },
          transform: [
            { fold: ['estimated', 'actual'], as: ['type', 'value'] }
          ],
          width: 'container',
          height: 200,
        },
        ...d,
      })),
    });
  }

  // Panel 3: Token Breakdown Donut
  if (actualCostData?.total_tokens_in > 0 || actualCostData?.total_tokens_out > 0) {
    panels.push({
      name: 'Token Usage',
      position: { col: 2, row: 2, width: 1, height: 1 },
      hide_title: false,
      hide_border: false,
      columns: ['format', 'config', 'type', 'tokens'],
      data: [
        {
          format: 'plotly',
          config: {
            type: 'pie',
            values: 'tokens',
            labels: 'type',
            hole: 0.4,
            title: 'Token Distribution',
          },
          type: 'Input',
          tokens: actualCostData?.total_tokens_in || 0,
        },
        {
          format: 'plotly',
          config: {
            type: 'pie',
            values: 'tokens',
            labels: 'type',
            hole: 0.4,
            title: 'Token Distribution',
          },
          type: 'Output',
          tokens: actualCostData?.total_tokens_out || 0,
        },
      ],
    });
  }

  // Panel 4: Cache Effectiveness Gauge
  panels.push({
    name: 'Cache Hit Rate',
    position: { col: 1, row: 3, width: 1, height: 1 },
    hide_title: false,
    hide_border: false,
    columns: ['format', 'config', 'value'],
    data: [{
      format: 'plotly',
      config: {
        type: 'indicator',
        mode: 'gauge+number',
        value: 'value',
        title: { text: 'Cache Hit Rate' },
        gauge: {
          axis: { range: [0, 100] },
          bar: { color: overallCacheRate > 0.5 ? '#22c55e' : '#eab308' },
          steps: [
            { range: [0, 50], color: 'rgba(239, 68, 68, 0.2)' },
            { range: [50, 80], color: 'rgba(234, 179, 8, 0.2)' },
            { range: [80, 100], color: 'rgba(34, 197, 94, 0.2)' },
          ],
        },
        number: { suffix: '%' },
      },
      value: Math.round(overallCacheRate * 100),
    }],
  });

  // Panel 5: Operator Details Table
  if (operators.length > 0) {
    panels.push({
      name: 'Operator Details',
      position: { col: 2, row: 3, width: 1, height: 1 },
      hide_title: false,
      hide_border: false,
      columns: ['Operator', 'Type', 'Est. Cost', 'Calls', 'Cache %', 'Model'],
      data: operators.map(op => ({
        'Operator': op.name,
        'Type': op.type,
        'Est. Cost': `$${op.estimated_cost.toFixed(4)}`,
        'Calls': op.calls,
        'Cache %': `${Math.round(op.cache_rate * 100)}%`,
        'Model': op.model.split('/').pop(),
      })),
    });
  }

  // Panel 6: Optimization Hints
  if (hints.length > 0) {
    panels.push({
      name: 'Optimization Hints',
      position: { col: 1, row: 4, width: 2, height: 1 },
      hide_title: false,
      hide_border: false,
      columns: ['format', 'content'],
      data: [{
        format: 'markdown',
        content: hints.map(h => `- ${h}`).join('\n'),
      }],
    });
  }

  // Panel 7: Mermaid Waterfall (if we have operators)
  if (operators.length > 0 && operators.length <= 5) {
    const mermaidCode = generateWaterfallMermaid(explainData, actualCostData);
    panels.push({
      name: 'Cost Flow',
      position: { col: 1, row: 5, width: 2, height: 1 },
      hide_title: false,
      hide_border: false,
      columns: ['format', 'config', 'content'],
      data: [{
        format: 'mermaid',
        config: { theme: 'dark' },
        content: mermaidCode,
      }],
    });
  }

  return panels;
}

const CostAnalysisDashboard = ({
  explainData,
  actualCostData,
  callerId,
  sourceTabName,
}) => {
  // Generate dashboard panels from cost data
  const panels = useMemo(() => {
    // Convert Map to array if needed
    const explainArray = explainData instanceof Map
      ? Array.from(explainData.values())
      : (Array.isArray(explainData) ? explainData : []);

    return generateDashboardPanels(explainArray, actualCostData, callerId);
  }, [explainData, actualCostData, callerId]);

  // If no data, show empty state
  if (!explainData || (explainData instanceof Map && explainData.size === 0)) {
    return (
      <div className="cost-analysis-empty">
        <div className="cost-analysis-empty-content">
          <span className="cost-analysis-empty-icon">📊</span>
          <h3>No Cost Data</h3>
          <p>Run a query with semantic operators to see cost analysis.</p>
        </div>
      </div>
    );
  }

  // Render using CanvasRenderer (same as regular Hyper dashboards)
  return (
    <div className="cost-analysis-dashboard">
      <div className="cost-analysis-header">
        <h2>Cost Analysis</h2>
        {sourceTabName && (
          <span className="cost-analysis-source">
            from "{sourceTabName}"
          </span>
        )}
        {callerId && (
          <span className="cost-analysis-caller-id" title={callerId}>
            {callerId.substring(0, 20)}...
          </span>
        )}
      </div>

      <div className="cost-analysis-content">
        <CanvasRenderer
          data={[]}
          columns={[]}
          isCanvas={false}
          canvasData={null}
          isMultiPanel={true}
          multiPanelData={panels}
          onInteraction={() => {}}
        />
      </div>
    </div>
  );
};

export default CostAnalysisDashboard;
