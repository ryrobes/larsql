/**
 * Unified role configuration across all Studio components
 * Shared by: SessionMessagesLog, ContextMatrixView, ContextExplorerSidebar
 */

export const ROLE_CONFIG = {
  assistant: {
    icon: 'mdi:robot-outline',
    color: '#a78bfa',
    label: 'Assistant',
    matrixColor: '#a78bfa'
  },
  user: {
    icon: 'mdi:account-outline',
    color: '#34d399',
    label: 'User',
    matrixColor: '#60a5fa' // Keep existing blue for matrix
  },
  system: {
    icon: 'mdi:cog-outline',
    color: '#fbbf24',
    label: 'System',
    matrixColor: '#a78bfa'
  },
  tool: {
    icon: 'mdi:wrench-outline',
    color: '#60a5fa',
    label: 'Tool',
    matrixColor: '#fbbf24'
  },
  tool_call: {
    icon: 'mdi:arrow-right-bold',
    color: '#60a5fa',
    label: 'Tool Call',
    matrixColor: '#60a5fa'
  },
  cell_start: {
    icon: 'mdi:play-circle-outline',
    color: '#34d399',
    label: 'Cell Start',
    matrixColor: '#34d399'
  },
  cell_complete: {
    icon: 'mdi:check-circle-outline',
    color: '#34d399',
    label: 'Cell Complete',
    matrixColor: '#34d399'
  },
  structure: {
    icon: 'mdi:shape-outline',
    color: '#a78bfa',
    label: 'Structure',
    matrixColor: '#a78bfa'
  },
  error: {
    icon: 'mdi:alert-circle-outline',
    color: '#f87171',
    label: 'Error',
    matrixColor: '#f87171'
  },
  evaluator: {
    icon: 'mdi:scale-balance',
    color: '#f472b6',
    label: 'Evaluator',
    matrixColor: '#f472b6'
  },
  ward: {
    icon: 'mdi:shield-outline',
    color: '#fb923c',
    label: 'Ward',
    matrixColor: '#fb923c'
  },
};

// Matrix-only colors (for backwards compatibility)
export const MATRIX_ROLE_COLORS = Object.fromEntries(
  Object.entries(ROLE_CONFIG).map(([key, val]) => [key, val.matrixColor])
);

// Default fallback
export const DEFAULT_ROLE_CONFIG = {
  icon: 'mdi:help-circle-outline',
  color: '#64748b',
  label: 'Unknown',
  matrixColor: '#666666'
};
