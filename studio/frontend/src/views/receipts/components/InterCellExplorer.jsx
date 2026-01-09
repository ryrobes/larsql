import React, { useState, useEffect, useMemo } from 'react';
import { Icon } from '@iconify/react';
import { VideoLoader } from '../../../components';
import './InterCellExplorer.css';

const InterCellExplorer = ({ sessionId }) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedCell, setSelectedCell] = useState(null);
  const [selectedBudget, setSelectedBudget] = useState(null);
  const [sortBy, setSortBy] = useState('rank'); // 'rank', 'score', 'tokens'
  const [showOnlyIncluded, setShowOnlyIncluded] = useState(false);

  // Fetch budget simulation data
  useEffect(() => {
    if (!sessionId) return;

    const fetchData = async () => {
      setLoading(true);
      try {
        const res = await fetch(
          `http://localhost:5050/api/context-assessment/budget-simulation/${sessionId}`
        );
        if (!res.ok) throw new Error('Failed to fetch budget simulation data');
        const json = await res.json();
        setData(json);

        // Auto-select first cell and budget
        if (json.cells?.length > 0) {
          const firstCell = json.cells[0];
          if (!selectedCell) {
            setSelectedCell(firstCell.cell_name);
          }
          // Auto-select middle budget value
          if (firstCell.budgets?.length > 0 && !selectedBudget) {
            const middleIdx = Math.floor(firstCell.budgets.length / 2);
            setSelectedBudget(firstCell.budgets[middleIdx].budget);
          }
        }
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [sessionId]);

  // Extract available budgets from current cell
  const availableBudgets = useMemo(() => {
    if (!data?.cells || !selectedCell) return [];
    const cell = data.cells.find(c => c.cell_name === selectedCell);
    return cell?.budgets?.map(b => b.budget).sort((a, b) => a - b) || [];
  }, [data, selectedCell]);

  // Get current cell's data at selected budget
  const currentCellData = useMemo(() => {
    if (!data?.cells || !selectedCell) return null;

    const cell = data.cells.find(c => c.cell_name === selectedCell);
    if (!cell?.budgets) return null;

    const budgetData = cell.budgets.find(b => b.budget === selectedBudget);
    return budgetData;
  }, [data, selectedCell, selectedBudget]);

  // Sort and filter messages
  const displayMessages = useMemo(() => {
    if (!currentCellData?.messages) return [];

    let msgs = [...currentCellData.messages];

    if (showOnlyIncluded) {
      msgs = msgs.filter(m => m.would_include);
    }

    switch (sortBy) {
      case 'score':
        msgs.sort((a, b) => b.score - a.score);
        break;
      case 'tokens':
        msgs.sort((a, b) => b.tokens - a.tokens);
        break;
      case 'rank':
      default:
        msgs.sort((a, b) => a.rank - b.rank);
    }

    return msgs;
  }, [currentCellData, sortBy, showOnlyIncluded]);

  // Calculate summary stats
  const summaryStats = useMemo(() => {
    if (!currentCellData) return null;

    const included = currentCellData.messages.filter(m => m.would_include);
    const excluded = currentCellData.messages.filter(m => !m.would_include);
    const actuallyIncluded = currentCellData.messages.filter(m => m.was_included);
    const wouldPrune = actuallyIncluded.filter(m => !m.would_include);

    return {
      totalMessages: currentCellData.messages.length,
      includedCount: included.length,
      excludedCount: excluded.length,
      tokensIncluded: included.reduce((sum, m) => sum + m.tokens, 0),
      tokensExcluded: excluded.reduce((sum, m) => sum + m.tokens, 0),
      wouldPruneCount: wouldPrune.length,
      wouldPruneTokens: wouldPrune.reduce((sum, m) => sum + m.tokens, 0)
    };
  }, [currentCellData]);

  const getScoreColor = (score) => {
    if (score >= 70) return '#34d399';
    if (score >= 40) return '#fbbf24';
    return '#f87171';
  };

  if (loading) {
    return (
      <div className="inter-cell-explorer loading">
        <VideoLoader size="small" message="Loading budget simulation..." />
      </div>
    );
  }

  if (error) {
    return (
      <div className="inter-cell-explorer error">
        <Icon icon="mdi:alert-circle" width={24} />
        <span>{error}</span>
      </div>
    );
  }

  if (!data?.cells?.length) {
    return (
      <div className="inter-cell-explorer empty">
        <Icon icon="mdi:swap-horizontal" width={32} />
        <span>No inter-cell context data available</span>
      </div>
    );
  }

  return (
    <div className="inter-cell-explorer">
      {/* Header with cell selector */}
      <div className="explorer-header">
        <div className="cell-selector">
          <label>Target Cell:</label>
          <select
            value={selectedCell || ''}
            onChange={(e) => setSelectedCell(e.target.value)}
          >
            {data.cells.map(cell => (
              <option key={cell.cell_name} value={cell.cell_name}>
                {cell.cell_name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Budget Selector */}
      {availableBudgets.length > 0 && (
        <div className="budget-selector">
          <div className="budget-header">
            <span className="budget-label">Token Budget</span>
            <span className="budget-value">
              {selectedBudget?.toLocaleString() || '—'} tokens
            </span>
          </div>
          <div className="budget-buttons">
            {availableBudgets.map(budget => (
              <button
                key={budget}
                className={selectedBudget === budget ? 'active' : ''}
                onClick={() => setSelectedBudget(budget)}
              >
                {budget >= 1000 ? `${budget / 1000}k` : budget}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Summary Stats */}
      {summaryStats && (
        <div className="budget-summary">
          <div className="summary-stat included">
            <div className="stat-icon">
              <Icon icon="mdi:check-circle" width={16} />
            </div>
            <div className="stat-content">
              <span className="stat-value">{summaryStats.includedCount}</span>
              <span className="stat-label">included</span>
              <span className="stat-tokens">{summaryStats.tokensIncluded.toLocaleString()} tokens</span>
            </div>
          </div>

          <div className="summary-stat excluded">
            <div className="stat-icon">
              <Icon icon="mdi:close-circle" width={16} />
            </div>
            <div className="stat-content">
              <span className="stat-value">{summaryStats.excludedCount}</span>
              <span className="stat-label">excluded</span>
              <span className="stat-tokens">{summaryStats.tokensExcluded.toLocaleString()} tokens</span>
            </div>
          </div>

          {summaryStats.wouldPruneCount > 0 && (
            <div className="summary-stat savings">
              <div className="stat-icon">
                <Icon icon="mdi:content-cut" width={16} />
              </div>
              <div className="stat-content">
                <span className="stat-value">{summaryStats.wouldPruneCount}</span>
                <span className="stat-label">would prune</span>
                <span className="stat-tokens">{summaryStats.wouldPruneTokens.toLocaleString()} tokens saved</span>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Filters and Sort */}
      <div className="explorer-controls">
        <div className="sort-controls">
          <label>Sort by:</label>
          <div className="sort-buttons">
            <button
              className={sortBy === 'rank' ? 'active' : ''}
              onClick={() => setSortBy('rank')}
            >
              Rank
            </button>
            <button
              className={sortBy === 'score' ? 'active' : ''}
              onClick={() => setSortBy('score')}
            >
              Score
            </button>
            <button
              className={sortBy === 'tokens' ? 'active' : ''}
              onClick={() => setSortBy('tokens')}
            >
              Tokens
            </button>
          </div>
        </div>

        <label className="filter-checkbox">
          <input
            type="checkbox"
            checked={showOnlyIncluded}
            onChange={(e) => setShowOnlyIncluded(e.target.checked)}
          />
          <span>Only show included</span>
        </label>
      </div>

      {/* Messages List */}
      <div className="messages-list">
        {displayMessages.map((msg, idx) => (
          <div
            key={`${msg.content_hash}-${idx}`}
            className={`message-row ${msg.would_include ? 'included' : 'excluded'} ${msg.was_included && !msg.would_include ? 'would-prune' : ''}`}
          >
            <div className="message-rank">
              #{msg.rank}
            </div>

            <div className="message-status">
              {msg.would_include ? (
                <Icon icon="mdi:check-circle" width={16} className="status-included" />
              ) : (
                <Icon icon="mdi:close-circle" width={16} className="status-excluded" />
              )}
            </div>

            <div className="message-role">
              <span className={`role-badge ${msg.role}`}>
                {msg.role}
              </span>
            </div>

            <div className="message-content">
              <div className="message-source">
                from <strong>{msg.source_cell}</strong>
              </div>
              <div className="message-preview">
                {msg.preview}
              </div>
            </div>

            <div className="message-score">
              <div
                className="score-bar"
                style={{
                  width: `${msg.score}%`,
                  background: getScoreColor(msg.score)
                }}
              />
              <span className="score-value" style={{ color: getScoreColor(msg.score) }}>
                {Math.round(msg.score)}
              </span>
            </div>

            <div className="message-tokens">
              <span className="token-count">{msg.tokens.toLocaleString()}</span>
              <span className="token-label">tokens</span>
            </div>

            <div className="message-cumulative">
              <span className="cumulative-count">{msg.cumulative_tokens.toLocaleString()}</span>
              <span className="cumulative-label">cumulative</span>
            </div>

            {msg.was_included && !msg.would_include && (
              <div className="prune-badge">
                <Icon icon="mdi:content-cut" width={12} />
                would prune
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
};

export default InterCellExplorer;
