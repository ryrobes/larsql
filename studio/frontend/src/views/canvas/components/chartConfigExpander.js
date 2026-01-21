/**
 * chartConfigExpander.js
 *
 * Processes chart config objects for Vega-Lite or Plotly specs.
 * Supports BOTH full specs and shorthand notation.
 *
 * Input format from SQL:
 *   SELECT
 *     'vega-lite' as format,
 *     {mark: 'bar', x: 'month', y: 'revenue'} as config,  -- shorthand
 *     month,
 *     revenue
 *   FROM sales;
 *
 * Or full spec (data gets injected automatically):
 *   SELECT
 *     'vega-lite' as format,
 *     {
 *       mark: {type: 'bar', cornerRadius: 4},
 *       encoding: {
 *         x: {field: 'month', type: 'ordinal', axis: {labelAngle: -45}},
 *         y: {field: 'revenue', type: 'quantitative', title: 'Revenue ($)'}
 *       }
 *     } as config,
 *     month,
 *     revenue
 *   FROM sales;
 *
 * The expander detects which format is used and handles accordingly.
 */

/**
 * Extract chart metadata and data from SQL result rows
 * @param {Array} rows - Array of row objects from SQL query
 * @returns {Object} { format, config, data, dataColumns }
 */
export function extractChartData(rows) {
  if (!Array.isArray(rows) || rows.length === 0) {
    return null;
  }

  const firstRow = rows[0];

  // Check if this is the new data-driven format
  if (!firstRow.format || !firstRow.config) {
    return null;
  }

  const format = firstRow.format;
  const config = typeof firstRow.config === 'string'
    ? JSON.parse(firstRow.config)
    : firstRow.config;

  // Extract data columns (everything except format and config)
  const dataColumns = Object.keys(firstRow).filter(k => k !== 'format' && k !== 'config');

  // Build data array without format/config columns
  const data = rows.map(row => {
    const dataRow = {};
    for (const col of dataColumns) {
      dataRow[col] = row[col];
    }
    return dataRow;
  });

  return { format, config, data, dataColumns };
}

/**
 * Check if config is a full Vega-Lite spec (vs shorthand)
 * Full specs have 'encoding' object or '$schema'
 */
function isFullVegaLiteSpec(config) {
  return config.encoding || config.$schema || config.layer || config.hconcat || config.vconcat;
}

/**
 * Process Vega-Lite config - handles both full specs and shorthand
 *
 * FULL SPEC: Pass through as-is, just inject data
 *   {
 *     mark: {type: 'bar', cornerRadius: 4},
 *     encoding: {
 *       x: {field: 'month', type: 'ordinal', axis: {labelAngle: -45}},
 *       y: {field: 'revenue', type: 'quantitative'}
 *     }
 *   }
 *
 * SHORTHAND: Expanded to full spec
 *   { mark: 'bar', x: 'month', y: 'revenue' }
 *   { mark: 'line', x: 'date', y: 'value', color: 'category' }
 *   { type: 'pie', theta: 'value', color: 'category' }
 *
 * @param {Object} config - Config object (full or shorthand)
 * @param {Array} data - Data rows
 * @returns {Object} Full Vega-Lite spec with data injected
 */
export function expandVegaLiteConfig(config, data) {
  // FULL SPEC: just inject data and schema
  if (isFullVegaLiteSpec(config)) {
    return {
      $schema: 'https://vega.github.io/schema/vega-lite/v5.json',
      data: { values: data },
      ...config,
    };
  }

  // SHORTHAND: expand to full spec
  const { mark, type, x, y, color, size, theta, opacity, title, ...rest } = config;

  // Handle pie/donut charts (arc mark)
  if (type === 'pie' || type === 'donut' || type === 'arc') {
    const spec = {
      $schema: 'https://vega.github.io/schema/vega-lite/v5.json',
      data: { values: data },
      mark: {
        type: 'arc',
        innerRadius: type === 'donut' ? 50 : 0,
      },
      encoding: {},
    };

    if (theta) {
      spec.encoding.theta = expandEncodingChannel(theta, data, 'quantitative');
    }
    if (color) {
      spec.encoding.color = expandEncodingChannel(color, data, 'nominal');
    }
    if (title) {
      spec.title = title;
    }

    return { ...spec, ...rest };
  }

  // Standard x/y charts
  const spec = {
    $schema: 'https://vega.github.io/schema/vega-lite/v5.json',
    data: { values: data },
    mark: mark || 'bar',
    encoding: {},
  };

  // Build encoding - supports both shorthand ('fieldname') and full ({field, type, ...})
  if (x) {
    spec.encoding.x = expandEncodingChannel(x, data);
  }
  if (y) {
    spec.encoding.y = expandEncodingChannel(y, data);
  }
  if (color) {
    spec.encoding.color = expandEncodingChannel(color, data);
  }
  if (size) {
    spec.encoding.size = expandEncodingChannel(size, data, 'quantitative');
  }
  if (opacity !== undefined) {
    if (typeof opacity === 'number') {
      // Static opacity on mark
      spec.mark = typeof spec.mark === 'string'
        ? { type: spec.mark, opacity }
        : { ...spec.mark, opacity };
    } else {
      spec.encoding.opacity = expandEncodingChannel(opacity, data, 'quantitative');
    }
  }
  if (title) {
    spec.title = title;
  }

  // Merge any additional config (allows partial overrides)
  return { ...spec, ...rest };
}

/**
 * Expand an encoding channel - handles both shorthand and full format
 * Shorthand: 'fieldname' -> {field: 'fieldname', type: inferred}
 * Full: {field: 'fieldname', type: 'quantitative', ...} -> pass through
 */
function expandEncodingChannel(value, data, defaultType = null) {
  if (typeof value === 'string') {
    return { field: value, type: defaultType || inferType(value, data) };
  }
  // Already a full encoding object - pass through
  return value;
}

/**
 * Infer Vega-Lite type from data values
 */
function inferType(field, data) {
  if (!data || data.length === 0) return 'nominal';

  const sample = data[0][field];

  if (typeof sample === 'number') {
    return 'quantitative';
  }
  if (sample instanceof Date || (typeof sample === 'string' && !isNaN(Date.parse(sample)) && sample.includes('-'))) {
    return 'temporal';
  }
  return 'nominal';
}

/**
 * Check if config is a full Plotly spec (vs shorthand)
 * Full specs have 'data' array already defined
 */
function isFullPlotlySpec(config) {
  return Array.isArray(config.data);
}

/**
 * Process Plotly config - handles both full specs and shorthand
 *
 * FULL SPEC: Pass through, optionally inject data into traces
 *   {
 *     data: [{
 *       type: 'bar',
 *       marker: {color: 'rgba(0,229,255,0.8)'},
 *       // x and y can reference column names to auto-fill
 *     }],
 *     layout: {title: 'My Chart', barmode: 'group'}
 *   }
 *
 * SHORTHAND: Expanded to full spec
 *   { type: 'bar', x: 'month', y: 'revenue' }
 *   { type: 'scatter', x: 'date', y: 'value', color: 'category', mode: 'lines+markers' }
 *   { type: 'pie', values: 'amount', labels: 'category' }
 *
 * @param {Object} config - Config object (full or shorthand)
 * @param {Array} data - Data rows
 * @returns {Object} Full Plotly spec { data: [...], layout: {...} }
 */
export function expandPlotlyConfig(config, data) {
  const getColumn = (field) => data.map(row => row[field]);

  // FULL SPEC: process traces, potentially filling in data references
  if (isFullPlotlySpec(config)) {
    const processedData = config.data.map(trace => {
      const processed = { ...trace };
      // If x/y/z are strings and match column names, fill with data
      if (typeof trace.x === 'string' && data[0]?.[trace.x] !== undefined) {
        processed.x = getColumn(trace.x);
      }
      if (typeof trace.y === 'string' && data[0]?.[trace.y] !== undefined) {
        processed.y = getColumn(trace.y);
      }
      if (typeof trace.z === 'string' && data[0]?.[trace.z] !== undefined) {
        processed.z = getColumn(trace.z);
      }
      if (typeof trace.values === 'string' && data[0]?.[trace.values] !== undefined) {
        processed.values = getColumn(trace.values);
      }
      if (typeof trace.labels === 'string' && data[0]?.[trace.labels] !== undefined) {
        processed.labels = getColumn(trace.labels);
      }
      return processed;
    });
    return {
      data: processedData,
      layout: config.layout || {},
    };
  }

  // SHORTHAND: expand to full spec
  const { type = 'bar', x, y, z, color, values, labels, mode, title, ...rest } = config;

  // Build trace based on chart type
  let trace = { type };

  switch (type) {
    case 'pie':
      trace.values = values ? getColumn(values) : [];
      trace.labels = labels ? getColumn(labels) : [];
      trace.hole = config.hole || 0; // 0 for pie, 0.4 for donut
      // Store original row data for click handling (maps label back to original columns)
      trace.customdata = data;
      break;

    case 'heatmap':
      trace.x = x ? getColumn(x) : [];
      trace.y = y ? getColumn(y) : [];
      trace.z = z ? getColumn(z) : [];
      trace.colorscale = config.colorscale || 'Viridis';
      break;

    case 'scatter':
    case 'scattergl':
      trace.x = x ? getColumn(x) : [];
      trace.y = y ? getColumn(y) : [];
      trace.mode = mode || 'markers';
      trace.customdata = data; // Store original row data for click handling
      if (color) {
        trace.marker = { color: getColumn(color) };
      }
      break;

    case 'bar':
    case 'line':
    default:
      trace.x = x ? getColumn(x) : [];
      trace.y = y ? getColumn(y) : [];
      trace.customdata = data; // Store original row data for click handling
      if (type === 'line') {
        trace.type = 'scatter';
        trace.mode = mode || 'lines';
      }
      if (color && typeof color === 'string') {
        // Group by color field for multiple traces
        const groups = groupByField(data, color);
        const traces = Object.entries(groups).map(([name, groupData]) => ({
          ...trace,
          name,
          x: x ? groupData.map(row => row[x]) : [],
          y: y ? groupData.map(row => row[y]) : [],
          customdata: groupData, // Store original row data for each trace
        }));
        return {
          data: traces,
          layout: {
            title: title || '',
            ...rest.layout,
          },
        };
      }
      break;
  }

  // Apply any remaining trace properties
  Object.assign(trace, rest.trace || {});

  return {
    data: [trace],
    layout: {
      title: title || '',
      ...rest.layout,
    },
  };
}

/**
 * Group data rows by a field value
 */
function groupByField(data, field) {
  const groups = {};
  for (const row of data) {
    const key = row[field];
    if (!groups[key]) {
      groups[key] = [];
    }
    groups[key].push(row);
  }
  return groups;
}

/**
 * Check if data uses the new SQL-native chart format
 * (has format, config, and at least one data column)
 */
export function isDataDrivenChart(data) {
  if (!Array.isArray(data) || data.length === 0) {
    return false;
  }

  const firstRow = data[0];
  const hasFormat = firstRow?.format === 'vega-lite' || firstRow?.format === 'plotly';
  const hasConfig = firstRow?.config !== undefined;
  const columnCount = Object.keys(firstRow || {}).length;

  // Must have format, config, and at least one data column
  return hasFormat && hasConfig && columnCount > 2;
}

/**
 * Process SQL-native chart data into panel-ready format
 */
export function processDataDrivenChart(data) {
  const extracted = extractChartData(data);
  if (!extracted) {
    return null;
  }

  const { format, config, data: chartData } = extracted;

  if (format === 'vega-lite') {
    return {
      format: 'vega-lite',
      spec: expandVegaLiteConfig(config, chartData),
    };
  } else if (format === 'plotly') {
    return {
      format: 'plotly',
      spec: expandPlotlyConfig(config, chartData),
    };
  }

  return null;
}
