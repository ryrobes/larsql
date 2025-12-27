import { useState, useEffect } from 'react';

/**
 * Hook to fetch and manage budget data for a session
 *
 * @param {string} sessionId - The session ID to fetch budget data for
 * @returns {Object} Budget data object with config, events, and metrics
 */
export function useBudgetData(sessionId) {
  const [budgetData, setBudgetData] = useState({
    budgetConfig: null,
    events: [],
    totalEnforcements: 0,
    totalPruned: 0,
    currentUsage: null,
    loading: true,
    error: null
  });

  useEffect(() => {
    // Don't fetch for invalid session IDs
    if (!sessionId || sessionId === 'null' || sessionId === 'undefined' || sessionId === '') {
      setBudgetData({
        budgetConfig: null,
        events: [],
        totalEnforcements: 0,
        totalPruned: 0,
        currentUsage: null,
        loading: false,
        error: null
      });
      return;
    }

    let mounted = true;

    const fetchBudgetData = async () => {
      try {
        const response = await fetch(`/api/budget/${sessionId}`);

        if (!response.ok) {
          throw new Error(`Failed to fetch budget data: ${response.status}`);
        }

        const data = await response.json();

        if (mounted) {
          setBudgetData({
            budgetConfig: data.budget_config,
            events: data.enforcement_events || [],
            totalEnforcements: data.total_enforcements || 0,
            totalPruned: data.total_tokens_pruned || 0,
            currentUsage: data.current_usage,
            loading: false,
            error: null
          });
        }
      } catch (err) {
        console.error('Budget data fetch failed:', err);
        if (mounted) {
          setBudgetData(prev => ({
            ...prev,
            loading: false,
            error: err.message
          }));
        }
      }
    };

    fetchBudgetData();

    return () => {
      mounted = false;
    };
  }, [sessionId]);

  return budgetData;
}
