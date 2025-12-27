import React, { useState, useEffect, useCallback } from 'react';
import { Icon } from '@iconify/react';
import './CompactResearchTree.css';

/**
 * CompactResearchTree - Indented tree showing research session branches
 *
 * File-explorer style tree that's compact and readable in narrow sidebar
 * Shows lineage via indentation, highlights current path
 */
function CompactResearchTree({ sessionId, currentSessionId }) {
  const [treeData, setTreeData] = useState(null);
  const [error, setError] = useState(null);
  const [collapsed, setCollapsed] = useState(false);
  const [expandedNodes, setExpandedNodes] = useState(new Set());

  // Fetch tree structure
  const fetchTree = useCallback(async () => {
    if (!sessionId) return;

    try {
      console.log('[CompactTree] Fetching tree for session:', sessionId);
      const res = await fetch(`http://localhost:5001/api/research-sessions/tree/${sessionId}`);
      const data = await res.json();

      console.log('[CompactTree] Tree response:', data);

      if (data.error) {
        console.log('[CompactTree] API error (might be new session):', data.error);
        setError(null);
        setTreeData(null);
      } else if (data.tree) {
        console.log('[CompactTree] Tree loaded');
        setTreeData(data);

        // Auto-expand nodes in current path
        const pathNodes = new Set();
        findPathToNode(data.tree, currentSessionId, pathNodes);
        setExpandedNodes(pathNodes);
      } else {
        setTreeData(null);
      }
    } catch (err) {
      console.error('[CompactTree] Fetch error:', err);
      setError(err.message);
    }
  }, [sessionId, currentSessionId]);

  useEffect(() => {
    if (sessionId) {
      fetchTree();
    }
  }, [sessionId, fetchTree]);

  // Find path from root to target node
  const findPathToNode = (node, targetId, pathSet) => {
    if (!node) return false;

    if (node.session_id === targetId) {
      pathSet.add(node.session_id);
      return true;
    }

    if (node.children) {
      for (const child of node.children) {
        if (findPathToNode(child, targetId, pathSet)) {
          pathSet.add(node.session_id);
          return true;
        }
      }
    }

    return false;
  };

  const toggleNode = (nodeId) => {
    setExpandedNodes(prev => {
      const next = new Set(prev);
      if (next.has(nodeId)) {
        next.delete(nodeId);
      } else {
        next.add(nodeId);
      }
      return next;
    });
  };

  const handleNavigate = (sessionId) => {
    window.location.hash = `#/cockpit/${sessionId}`;
  };

  if (error) {
    return (
      <div className="compact-tree-error">
        <Icon icon="mdi:alert-circle" width="16" />
        <span>Failed to load tree</span>
      </div>
    );
  }

  if (!treeData || !treeData.tree) {
    return null;
  }

  const hasBranches = treeData.tree.children?.length > 0 || treeData.tree.parent_session_id;

  return (
    <div className="compact-research-tree">
      <div
        className="tree-header"
        onClick={() => setCollapsed(!collapsed)}
      >
        <Icon icon={hasBranches ? "mdi:source-fork" : "mdi:source-commit"} width="18" />
        <span>{hasBranches ? 'Research Tree' : 'Session'}</span>
        {countTotalNodes(treeData.tree) > 1 && (
          <span className="node-count">{countTotalNodes(treeData.tree)}</span>
        )}
        <Icon
          icon={collapsed ? 'mdi:chevron-down' : 'mdi:chevron-up'}
          width="18"
          style={{ marginLeft: 'auto' }}
        />
      </div>

      {!collapsed && (
        <div className="tree-content">
          <TreeNode
            node={treeData.tree}
            currentSessionId={currentSessionId}
            expandedNodes={expandedNodes}
            onToggle={toggleNode}
            onNavigate={handleNavigate}
            level={0}
          />
        </div>
      )}
    </div>
  );
}

/**
 * TreeNode - Recursive node component
 */
function TreeNode({ node, currentSessionId, expandedNodes, onToggle, onNavigate, level }) {
  const isCurrent = node.session_id === currentSessionId;
  const hasChildren = node.children && node.children.length > 0;
  const isExpanded = expandedNodes.has(node.session_id);

  return (
    <>
      <div
        className={`tree-node ${isCurrent ? 'current' : ''} ${hasChildren ? 'has-children' : ''}`}
        style={{ paddingLeft: `${level * 16}px` }}
      >
        {/* Expand/collapse icon */}
        {hasChildren && (
          <Icon
            icon={isExpanded ? 'mdi:chevron-down' : 'mdi:chevron-right'}
            width="16"
            className="expand-icon"
            onClick={(e) => {
              e.stopPropagation();
              onToggle(node.session_id);
            }}
          />
        )}
        {!hasChildren && <span className="node-spacer" />}

        {/* Status dot */}
        <div className={`node-dot ${isCurrent ? 'current' : node.status}`} />

        {/* Node content */}
        <div
          className="node-content"
          onClick={() => onNavigate(node.session_id)}
        >
          <div className="node-title">
            {node.title?.length > 35 ? node.title.substring(0, 35) + '...' : node.title || node.session_id?.slice(0, 12)}
            {isCurrent && <span className="current-badge">YOU</span>}
          </div>

          {(node.total_cost > 0 || node.total_turns > 0) && (
            <div className="node-stats">
              {node.total_cost > 0 && (
                <span className="stat cost">
                  <Icon icon="mdi:currency-usd" width="10" />
                  ${node.total_cost.toFixed(3)}
                </span>
              )}
              {node.total_turns > 0 && (
                <span className="stat turns">
                  <Icon icon="mdi:counter" width="10" />
                  {node.total_turns}
                </span>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Children (if expanded) */}
      {hasChildren && isExpanded && (
        <div className="tree-children">
          {node.children.map((child, idx) => (
            <TreeNode
              key={child.session_id || idx}
              node={child}
              currentSessionId={currentSessionId}
              expandedNodes={expandedNodes}
              onToggle={onToggle}
              onNavigate={onNavigate}
              level={level + 1}
            />
          ))}
        </div>
      )}
    </>
  );
}

// Helper to count nodes
function countTotalNodes(node) {
  if (!node) return 0;
  return 1 + (node.children || []).reduce((sum, child) => sum + countTotalNodes(child), 0);
}

export default CompactResearchTree;
