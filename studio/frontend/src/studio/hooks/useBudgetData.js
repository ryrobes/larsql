import { useState, useEffect, useRef, useCallback } from 'react';

/**
 * Hook to fetch and manage budget data for a session
 *
 * Polls periodically to get real-time enforcement events during cascade execution.
 * For live sessions, pass shouldPoll=true while the cascade is running.
 * For replay sessions, a single fetch is usually sufficient.
 *
 * @param {string} sessionId - The session ID to fetch budget data for
 * @param {boolean} shouldPoll - Whether to continuously poll for updates (default: true for first 60s)
 * @returns {Object} Budget data object with config, events, and metrics
 */
export function useBudgetData(sessionId, shouldPoll = true) {
  const [budgetData, setBudgetData] = useState({
    budgetConfig: null,
    events: [],
    usageHistory: [],  // Timeline of token usage (LLM calls + enforcement drops)
    totalEnforcements: 0,
    totalPruned: 0,
    currentUsage: null,
    loading: true,
    error: null
  });

  // Track polling state
  const pollIntervalRef = useRef(null);
  const pollCountRef = useRef(0);
  const MAX_POLLS = 300; // Stop polling after 300 attempts (10 minutes for long-running cascades)
  const POLL_INTERVAL = 2000; // Poll every 2 seconds

  const fetchBudgetData = useCallback(async () => {
    if (!sessionId || sessionId === 'null' || sessionId === 'undefined' || sessionId === '') {
      return null;
    }

    try {
      const response = await fetch(`/api/budget/${sessionId}`);

      if (!response.ok) {
        throw new Error(`Failed to fetch budget data: ${response.status}`);
      }

      return await response.json();
    } catch (err) {
      console.error('Budget data fetch failed:', err);
      throw err;
    }
  }, [sessionId]);

  useEffect(() => {
    // Don't fetch for invalid session IDs
    if (!sessionId || sessionId === 'null' || sessionId === 'undefined' || sessionId === '') {
      setBudgetData({
        budgetConfig: null,
        events: [],
        usageHistory: [],
        totalEnforcements: 0,
        totalPruned: 0,
        currentUsage: null,
        loading: false,
        error: null
      });
      return;
    }

    let mounted = true;
    pollCountRef.current = 0;

    const doFetch = async () => {
      try {
        const data = await fetchBudgetData();

        if (!mounted) return;

        // Handle null data (shouldn't happen if sessionId is valid, but be safe)
        if (!data) {
          setBudgetData(prev => ({
            ...prev,
            loading: false,
          }));
          return;
        }

        const newBudgetData = {
          budgetConfig: data.budget_config,
          events: data.enforcement_events || [],
          usageHistory: data.usage_history || [],
          totalEnforcements: data.total_enforcements || 0,
          totalPruned: data.total_tokens_pruned || 0,
          currentUsage: data.current_usage,
          loading: false,
          error: null
        };

        setBudgetData(newBudgetData);

      } catch (err) {
        console.error('[useBudgetData] Fetch error:', err);
        if (mounted) {
          setBudgetData(prev => ({
            ...prev,
            loading: false,
            error: err.message
          }));
        }
      }
    };

    // Initial fetch
    doFetch();

    // Start polling if shouldPoll is true
    if (shouldPoll) {
      pollIntervalRef.current = setInterval(() => {
        pollCountRef.current += 1;

        // Stop polling after max polls reached
        if (pollCountRef.current >= MAX_POLLS) {
          if (pollIntervalRef.current) {
            clearInterval(pollIntervalRef.current);
            pollIntervalRef.current = null;
          }
          return;
        }

        doFetch();
      }, POLL_INTERVAL);
    }

    return () => {
      mounted = false;
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
    };
  }, [sessionId, shouldPoll, fetchBudgetData]);

  // Stop/start polling when shouldPoll changes
  useEffect(() => {
    if (!shouldPoll && pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
  }, [shouldPoll]);

  return budgetData;
}
