import { useState, useEffect, useRef, useCallback } from 'react';
import { useToast } from '../components';

/**
 * Hook to fetch and manage OpenRouter credit balance data.
 *
 * Polls periodically to track credit usage in real-time.
 * Triggers low balance warnings via toast notifications.
 *
 * @param {Object} options - Configuration options
 * @param {boolean} options.enabled - Whether to fetch credits (default: true)
 * @param {number} options.pollInterval - Polling interval in ms (default: 60000)
 * @param {number} options.lowBalanceThreshold - Balance threshold for warning (default: 5.0)
 * @returns {Object} Credits data object with balance, analytics, and status
 */
export function useCredits(options = {}) {
  const {
    enabled = true,
    pollInterval = 60000, // 60 seconds default
    lowBalanceThreshold = 5.0,
  } = options;

  const [creditsData, setCreditsData] = useState({
    balance: null,
    totalCredits: null,
    totalUsage: null,
    burnRate1h: null,
    burnRate24h: null,
    burnRate7d: null,
    runwayDays: null,
    delta24h: null,
    lowBalanceWarning: false,
    lastUpdated: null,
    snapshotCount24h: null,
    loading: true,
    error: null,
  });

  const { showToast } = useToast();
  const pollIntervalRef = useRef(null);
  const prevLowBalanceRef = useRef(false);
  const hasShownWarningRef = useRef(false);

  const fetchCredits = useCallback(async (forceRefresh = false) => {
    try {
      const url = forceRefresh
        ? 'http://localhost:5050/api/credits?refresh=true'
        : 'http://localhost:5050/api/credits';

      const response = await fetch(url);

      if (!response.ok) {
        throw new Error(`Failed to fetch credits: ${response.status}`);
      }

      return await response.json();
    } catch (err) {
      console.error('[useCredits] Fetch error:', err);
      throw err;
    }
  }, []);

  const refetch = useCallback(async (forceRefresh = false) => {
    try {
      setCreditsData(prev => ({ ...prev, loading: true, error: null }));
      const data = await fetchCredits(forceRefresh);

      if (data.error) {
        setCreditsData(prev => ({
          ...prev,
          loading: false,
          error: data.error,
        }));
        return;
      }

      const newData = {
        balance: data.balance,
        totalCredits: data.total_credits,
        totalUsage: data.total_usage,
        burnRate1h: data.burn_rate_1h,
        burnRate24h: data.burn_rate_24h,
        burnRate7d: data.burn_rate_7d,
        runwayDays: data.runway_days,
        delta24h: data.delta_24h,
        lowBalanceWarning: data.low_balance_warning || (data.balance !== null && data.balance < lowBalanceThreshold),
        lastUpdated: data.last_updated,
        snapshotCount24h: data.snapshot_count_24h,
        loading: false,
        error: null,
      };

      setCreditsData(newData);

      // Check for low balance transition (only warn once per session)
      const isLowNow = newData.lowBalanceWarning;
      const wasLowBefore = prevLowBalanceRef.current;

      if (isLowNow && !wasLowBefore && !hasShownWarningRef.current && newData.balance !== null) {
        hasShownWarningRef.current = true;
        // showToast signature: (message, options) - not a single object
        showToast(
          `Low OpenRouter Balance: $${newData.balance.toFixed(2)}. Consider topping up.`,
          { type: 'warning', duration: 10000 }
        );
      }

      prevLowBalanceRef.current = isLowNow;

    } catch (err) {
      setCreditsData(prev => ({
        ...prev,
        loading: false,
        error: err.message,
      }));
    }
  }, [fetchCredits, lowBalanceThreshold, showToast]);

  // Initial fetch and polling
  useEffect(() => {
    if (!enabled) {
      setCreditsData(prev => ({
        ...prev,
        loading: false,
      }));
      return;
    }

    // Initial fetch
    refetch();

    // Start polling
    pollIntervalRef.current = setInterval(() => {
      refetch();
    }, pollInterval);

    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
    };
  }, [enabled, pollInterval, refetch]);

  return {
    ...creditsData,
    refetch: () => refetch(true), // Force refresh when manually called
  };
}

export default useCredits;
