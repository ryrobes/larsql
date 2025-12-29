import React, { useEffect, useRef, useState, useCallback } from 'react';
import * as d3 from 'd3';
import { Icon } from '@iconify/react';
import './ResearchTreeVisualization.css';

/**
 * ResearchTreeVisualization - D3 tree showing research session branches
 *
 * Displays parent session + all branches in an interactive tree
 * Highlights current path from root to current session
 * Click nodes to navigate between branches
 */
function ResearchTreeVisualization({ sessionId, currentSessionId }) {
  const svgRef = useRef(null);
  const [treeData, setTreeData] = useState(null);
  const [error, setError] = useState(null);
  const [collapsed, setCollapsed] = useState(false);

  // Fetch tree structure
  const fetchTree = useCallback(async () => {
    if (!sessionId) {
      console.log('[ResearchTree] No sessionId, skipping fetch');
      return;
    }

    try {
      console.log('[ResearchTree] Fetching tree for session:', sessionId);
      const res = await fetch(`http://localhost:5050/api/research-sessions/tree/${sessionId}`);
      const data = await res.json();

      console.log('[ResearchTree] Tree API response:', data);

      if (data.error) {
        console.log('[ResearchTree] API returned error (might be new session):', data.error);
        // Don't set as error - just return null tree (session might not be saved yet)
        setError(null);
        setTreeData(null);
      } else if (data.tree) {
        console.log('[ResearchTree] Loaded tree successfully:', data.tree);
        setTreeData(data);
      } else {
        console.log('[ResearchTree] No tree in response');
        setTreeData(null);
      }
    } catch (err) {
      console.error('[ResearchTree] Failed to fetch tree:', err);
      setError(err.message);
    }
  }, [sessionId]);

  useEffect(() => {
    console.log('[ResearchTree] useEffect triggered, sessionId:', sessionId);
    if (sessionId) {
      fetchTree();
    }
  }, [sessionId, fetchTree]);

  // Render D3 tree
  useEffect(() => {
    console.log('[ResearchTree] D3 render effect triggered', {
      hasTreeData: !!treeData,
      hasTree: !!treeData?.tree,
      hasSvgRef: !!svgRef.current,
      collapsed
    });

    if (!treeData || !treeData.tree || !svgRef.current || collapsed) {
      console.log('[ResearchTree] Skipping D3 render due to missing requirements');
      return;
    }

    console.log('[ResearchTree] Starting D3 render...');

    try {
      const svg = d3.select(svgRef.current);
      svg.selectAll('*').remove(); // Clear previous render

      const width = 280;  // Sidebar width
      const nodeWidth = 120; // Horizontal spacing between levels

      // Count total nodes to calculate height
      const countNodes = (node) => {
        if (!node) return 0;
        return 1 + (node.children || []).reduce((sum, child) => sum + countNodes(child), 0);
      };

      const totalNodes = countNodes(treeData.tree);
      const height = Math.max(totalNodes * nodeWidth, 150); // More vertical space

      console.log('[ResearchTree] SVG setup:', { width, height, totalNodes });

      svg.attr('viewBox', [0, 0, width, height]);

      const g = svg.append('g').attr('transform', 'translate(20, 30)');

      // Create VERTICAL tree layout (top to bottom)
      const treeLayout = d3.tree().size([width - 40, height - 60]);

      const root = d3.hierarchy(treeData.tree, d => d.children);
      const treeNodes = treeLayout(root);

      console.log('[ResearchTree] Tree nodes:', treeNodes.descendants().length);

      // Find path from root to current session
      const currentPath = new Set();
      const findPath = (node) => {
        if (node.data.session_id === currentSessionId) {
          currentPath.add(node.data.session_id);
          return true;
        }
        if (node.children) {
          for (const child of node.children) {
            if (findPath(child)) {
              currentPath.add(node.data.session_id);
              return true;
            }
          }
        }
        return false;
      };
      findPath(root);

      console.log('[ResearchTree] Current path nodes:', currentPath.size);

      // Draw links (edges) - VERTICAL
      g.selectAll('.link')
        .data(treeNodes.links())
        .join('path')
        .attr('class', 'link')
        .attr('d', d3.linkVertical()
          .x(d => d.x)  // Swapped!
          .y(d => d.y)  // Swapped!
        )
        .style('fill', 'none')
        .style('stroke', d => {
          // Highlight path to current session
          const isInPath = currentPath.has(d.source.data.session_id) && currentPath.has(d.target.data.session_id);
          return isInPath ? '#a78bfa' : '#333';
        })
        .style('stroke-width', d => {
          const isInPath = currentPath.has(d.source.data.session_id) && currentPath.has(d.target.data.session_id);
          return isInPath ? 3 : 1.5;
        })
        .style('opacity', d => {
          const isInPath = currentPath.has(d.source.data.session_id) && currentPath.has(d.target.data.session_id);
          return isInPath ? 1 : 0.4;
        });

      console.log('[ResearchTree] Drew', treeNodes.links().length, 'links');

      // Draw nodes - VERTICAL (swap x/y for positioning)
      const node = g.selectAll('.node')
        .data(treeNodes.descendants())
        .join('g')
        .attr('class', 'node')
        .attr('transform', d => `translate(${d.x},${d.y})`)  // Swapped for vertical!
        .style('cursor', 'pointer')
        .on('click', (event, d) => {
          // Navigate to this session
          console.log('[ResearchTree] Node clicked:', d.data.session_id);
          window.location.hash = `#/cockpit/${d.data.session_id}`;
        });

      // Node circles
      node.append('circle')
        .attr('r', d => {
          const isCurrent = d.data.session_id === currentSessionId;
          const isInPath = currentPath.has(d.data.session_id);
          return isCurrent ? 10 : isInPath ? 8 : 6;
        })
        .style('fill', d => {
          const isCurrent = d.data.session_id === currentSessionId;
          const isInPath = currentPath.has(d.data.session_id);

          if (isCurrent) return '#a78bfa';
          if (isInPath) return '#8b5cf6';
          return d.data.status === 'completed' ? '#10b981' : '#fbbf24';
        })
        .style('stroke', d => {
          const isCurrent = d.data.session_id === currentSessionId;
          return isCurrent ? '#e5e7eb' : '#0a0a0a';
        })
        .style('stroke-width', d => {
          const isCurrent = d.data.session_id === currentSessionId;
          return isCurrent ? 3 : 2;
        });

      // Pulsing effect for current node
      node.filter(d => d.data.session_id === currentSessionId)
        .select('circle')
        .attr('class', 'current-node-pulse');

      // Node labels - BELOW nodes for vertical layout
      node.append('text')
        .attr('dy', 25)  // Below the circle
        .attr('text-anchor', 'middle')  // Center the text
        .style('font-size', '10px')
        .style('fill', d => {
          const isCurrent = d.data.session_id === currentSessionId;
          const isInPath = currentPath.has(d.data.session_id);
          return isCurrent || isInPath ? '#e5e7eb' : '#9ca3af';
        })
        .style('font-weight', d => {
          const isCurrent = d.data.session_id === currentSessionId;
          return isCurrent ? 700 : 500;
        })
        .each(function(d) {
          // Word wrap for long titles
          const title = d.data.title || d.data.session_id;
          const words = title.split(' ');
          const maxWidth = 18; // Characters per line
          let line = '';
          let lineNumber = 0;
          const lineHeight = 12;

          for (const word of words) {
            const testLine = line + (line ? ' ' : '') + word;
            if (testLine.length > maxWidth && line) {
              d3.select(this).append('tspan')
                .attr('x', 0)
                .attr('dy', lineNumber === 0 ? 0 : lineHeight)
                .text(line);
              line = word;
              lineNumber++;
              if (lineNumber >= 2) break; // Max 2 lines
            } else {
              line = testLine;
            }
          }

          // Add final line
          if (line && lineNumber < 2) {
            d3.select(this).append('tspan')
              .attr('x', 0)
              .attr('dy', lineNumber === 0 ? 0 : lineHeight)
              .text(line.length > maxWidth ? line.substring(0, maxWidth) + '...' : line);
          }
        });

      // Cost badges - below labels
      node.filter(d => d.data.total_cost > 0)
        .append('text')
        .attr('dy', 55)  // Below the title
        .attr('text-anchor', 'middle')
        .style('font-size', '8px')
        .style('fill', '#10b981')
        .style('font-family', 'IBM Plex Mono, monospace')
        .text(d => `$${d.data.total_cost.toFixed(3)}`);

      console.log('[ResearchTree] Drew', treeNodes.descendants().length, 'nodes');

      console.log('[ResearchTree] ✓ D3 render complete');

    } catch (err) {
      console.error('[ResearchTree] D3 render error:', err);
      setError(err.message);
    }
  }, [treeData, currentSessionId, collapsed]);

  if (error) {
    return (
      <div className="tree-error">
        <Icon icon="mdi:alert-circle" width="18" />
        <span>Failed to load tree</span>
      </div>
    );
  }

  if (!treeData || !treeData.tree) {
    console.log('[ResearchTree] Rendering null - no tree data');
    return null; // No tree to show
  }

  // Count branches
  const hasBranches = treeData.tree.children?.length > 0 || treeData.tree.parent_session_id;

  console.log('[ResearchTree] Rendering tree', {
    hasBranches,
    childrenCount: treeData.tree.children?.length || 0,
    hasParent: !!treeData.tree.parent_session_id,
    treeData: treeData.tree
  });

  return (
    <div className="research-tree-container">
      <div
        className="tree-header"
        onClick={() => setCollapsed(!collapsed)}
      >
        <Icon icon={hasBranches ? "mdi:source-fork" : "mdi:source-commit"} width="18" />
        <span>{hasBranches ? 'Research Tree' : 'Session Flow'}</span>
        {countTotalNodes(treeData.tree) > 1 && (
          <div className="tree-badge">
            {countTotalNodes(treeData.tree)} sessions
          </div>
        )}
        <Icon
          icon={collapsed ? 'mdi:chevron-down' : 'mdi:chevron-up'}
          width="18"
          style={{ marginLeft: 'auto' }}
        />
      </div>

      {!collapsed && (
        <div className="tree-visualization">
          <svg ref={svgRef} className="tree-svg" />
        </div>
      )}
    </div>
  );
}

// Helper to count nodes
function countTotalNodes(node) {
  if (!node) return 0;
  return 1 + (node.children || []).reduce((sum, child) => sum + countTotalNodes(child), 0);
}

export default ResearchTreeVisualization;
