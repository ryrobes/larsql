import { useState, useEffect, useCallback } from 'react';
import { API_BASE_URL } from '../../config/api';

/**
 * useRunningSessions - Hook for polling running cascade sessions
 *
 * Polls /api/running-sessions periodically and returns active sessions.
 *
 * @param {number} pollInterval - Polling interval in ms (default: 5000)
 * @returns {Object} { sessions, isLoading, error, refresh }
 */
const useRunningSessions = (pollInterval = 5000) => {
  const [sessions, setSessions] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);

  const fetchSessions = useCallback(async () => {
    try {
      setIsLoading(true);
      const response = await fetch(`${API_BASE_URL}/api/running-sessions`);
      const data = await response.json();

      if (data.error) {
        setError(data.error);
        setSessions([]);
      } else {
        // Filter to only show running sessions (not completed)
        const runningSessions = (data.sessions || []).filter(s => s.status === 'running');
        setSessions(runningSessions);
        setError(null);
      }
    } catch (err) {
      setError(err.message);
      setSessions([]);
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Poll for updates
  useEffect(() => {
    // Fetch immediately on mount
    fetchSessions();

    // Poll at interval
    const interval = setInterval(fetchSessions, pollInterval);

    return () => clearInterval(interval);
  }, [fetchSessions, pollInterval]);

  return {
    sessions,
    isLoading,
    error,
    refresh: fetchSessions,
    count: sessions.length,
  };
};

export default useRunningSessions;
