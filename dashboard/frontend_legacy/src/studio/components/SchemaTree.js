import React from 'react';
import { Icon } from '@iconify/react';
import useStudioQueryStore from '../stores/studioQueryStore';
import './SchemaTree.css';

// Type badge colors
const TYPE_COLORS = {
  'VARCHAR': '#a78bfa',
  'TEXT': '#a78bfa',
  'CHAR': '#a78bfa',
  'INTEGER': '#60a5fa',
  'BIGINT': '#60a5fa',
  'SMALLINT': '#60a5fa',
  'INT': '#60a5fa',
  'DOUBLE': '#2dd4bf',
  'FLOAT': '#2dd4bf',
  'DECIMAL': '#2dd4bf',
  'NUMERIC': '#2dd4bf',
  'BOOLEAN': '#fbbf24',
  'BOOL': '#fbbf24',
  'DATE': '#f472b6',
  'TIMESTAMP': '#f472b6',
  'TIME': '#f472b6',
  'JSON': '#34d399',
  'JSONB': '#34d399',
  'BLOB': '#94a3b8',
  'BINARY': '#94a3b8'
};

function getTypeColor(type) {
  if (!type) return '#64748b';
  const baseType = type.toUpperCase().split('(')[0].trim();
  return TYPE_COLORS[baseType] || '#64748b';
}

function formatRowCount(count) {
  if (count >= 1000000) return `${(count / 1000000).toFixed(1)}M`;
  if (count >= 1000) return `${(count / 1000).toFixed(1)}K`;
  return count?.toString() || '0';
}

function ConnectionNode({ connection }) {
  const {
    schemas,
    schemasLoading,
    schemasError,
    expandedNodes,
    toggleNodeExpanded,
    fetchSchema,
    isNodeExpanded
  } = useStudioQueryStore();

  const nodeId = `conn_${connection.name}`;
  const isExpanded = isNodeExpanded(nodeId);
  const isLoading = schemasLoading[connection.name];
  const error = schemasError[connection.name];
  const schema = schemas[connection.name];

  const handleToggle = () => {
    toggleNodeExpanded(nodeId);

    // Fetch schema if expanding and not loaded
    if (!isExpanded && !schema && !isLoading) {
      fetchSchema(connection.name);
    }
  };

  return (
    <div className="schema-tree-node">
      <div className="schema-tree-row schema-tree-connection" onClick={handleToggle}>
        <Icon
          icon={isExpanded ? 'mdi:chevron-down' : 'mdi:chevron-right'}
          className="schema-tree-chevron"
        />
        <Icon icon="mdi:database" className="schema-tree-icon connection-icon" />
        <span className="schema-tree-label">{connection.name}</span>
        <span className="schema-tree-badge">{connection.table_count}</span>
      </div>

      {isExpanded && (
        <div className="schema-tree-children">
          {isLoading && (
            <div className="schema-tree-loading">
              <Icon icon="mdi:loading" className="spin" />
              <span>Loading...</span>
            </div>
          )}
          {error && (
            <div className="schema-tree-error">{error}</div>
          )}
          {schema && schema.schemas?.map(s => (
            <SchemaNode
              key={s.name}
              schema={s}
              connectionName={connection.name}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function SchemaNode({ schema, connectionName }) {
  const { toggleNodeExpanded, isNodeExpanded } = useStudioQueryStore();

  const nodeId = `schema_${connectionName}_${schema.name}`;
  const isExpanded = isNodeExpanded(nodeId);

  // If schema name matches connection name, show tables directly
  const showSchemaLevel = schema.name !== connectionName;

  if (!showSchemaLevel) {
    // Render tables directly under connection
    return (
      <>
        {schema.tables?.map(table => (
          <TableNode
            key={table.name}
            table={table}
            connectionName={connectionName}
            schemaName={schema.name}
          />
        ))}
      </>
    );
  }

  return (
    <div className="schema-tree-node">
      <div className="schema-tree-row schema-tree-schema" onClick={() => toggleNodeExpanded(nodeId)}>
        <Icon
          icon={isExpanded ? 'mdi:chevron-down' : 'mdi:chevron-right'}
          className="schema-tree-chevron"
        />
        <Icon icon="mdi:folder" className="schema-tree-icon schema-icon" />
        <span className="schema-tree-label">{schema.name}</span>
        <span className="schema-tree-badge">{schema.tables?.length || 0}</span>
      </div>

      {isExpanded && (
        <div className="schema-tree-children">
          {schema.tables?.map(table => (
            <TableNode
              key={table.name}
              table={table}
              connectionName={connectionName}
              schemaName={schema.name}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function TableNode({ table, connectionName, schemaName }) {
  const { toggleNodeExpanded, isNodeExpanded, updateTab, activeTabId } = useStudioQueryStore();

  const nodeId = `table_${connectionName}_${schemaName}_${table.name}`;
  const isExpanded = isNodeExpanded(nodeId);

  const handleDoubleClick = (e) => {
    e.stopPropagation();
    // Insert table name into current editor
    const qualifiedName = table.qualified_name || `${connectionName}.${table.name}`;
    insertTextAtCursor(qualifiedName);
  };

  const insertTextAtCursor = (text) => {
    // Get current tab and append to SQL
    const state = useStudioQueryStore.getState();
    const tab = state.tabs.find(t => t.id === state.activeTabId);
    if (tab) {
      const currentSql = tab.sql || '';
      const newSql = currentSql + (currentSql && !currentSql.endsWith(' ') ? ' ' : '') + text;
      updateTab(activeTabId, { sql: newSql });
    }
  };

  return (
    <div className="schema-tree-node">
      <div
        className="schema-tree-row schema-tree-table"
        onClick={() => toggleNodeExpanded(nodeId)}
        onDoubleClick={handleDoubleClick}
        title="Double-click to insert table name"
      >
        <Icon
          icon={isExpanded ? 'mdi:chevron-down' : 'mdi:chevron-right'}
          className="schema-tree-chevron"
        />
        <Icon icon="mdi:table" className="schema-tree-icon table-icon" />
        <span className="schema-tree-label">{table.name}</span>
        <span className="schema-tree-row-count">{formatRowCount(table.row_count)}</span>
      </div>

      {isExpanded && table.columns && (
        <div className="schema-tree-children">
          {table.columns.map(col => (
            <ColumnNode
              key={col.name}
              column={col}
              onInsert={insertTextAtCursor}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function ColumnNode({ column, onInsert }) {
  const handleDoubleClick = (e) => {
    e.stopPropagation();
    onInsert(column.name);
  };

  const typeColor = getTypeColor(column.type);
  const shortType = column.type?.split('(')[0] || 'unknown';

  return (
    <div
      className="schema-tree-row schema-tree-column"
      onDoubleClick={handleDoubleClick}
      title={`${column.type}${column.nullable ? ' (nullable)' : ''}\nDouble-click to insert`}
    >
      <Icon icon="mdi:minus" className="schema-tree-chevron column-spacer" />
      <Icon icon="mdi:alpha-c-box" className="schema-tree-icon column-icon" />
      <span className="schema-tree-label">{column.name}</span>
      <span className="schema-tree-type" style={{ color: typeColor }}>
        {shortType}
      </span>
    </div>
  );
}

function SchemaTree() {
  const { connections, connectionsLoading, connectionsError } = useStudioQueryStore();

  if (connectionsLoading) {
    return (
      <div className="schema-tree-loading">
        <Icon icon="mdi:loading" className="spin" />
        <span>Loading connections...</span>
      </div>
    );
  }

  if (connectionsError) {
    return (
      <div className="schema-tree-error">
        {connectionsError}
      </div>
    );
  }

  if (connections.length === 0) {
    return (
      <div className="schema-tree-empty">
        No SQL connections configured.
        <br />
        Run <code>windlass sql chart</code> to index schemas.
      </div>
    );
  }

  return (
    <div className="schema-tree">
      {connections.map(conn => (
        <ConnectionNode key={conn.name} connection={conn} />
      ))}
    </div>
  );
}

export default SchemaTree;
