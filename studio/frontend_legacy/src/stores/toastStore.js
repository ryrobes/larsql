import { create } from 'zustand';

/**
 * Toast Store
 *
 * Manages toast notifications (success, error, warning, info messages).
 * Toasts auto-dismiss after a duration or can be manually closed.
 */
const useToastStore = create((set, get) => ({
  // Array of active toasts
  toasts: [],

  // Add a new toast
  showToast: (message, options = {}) => {
    const {
      type = 'info',        // 'success' | 'error' | 'warning' | 'info'
      duration = 4000,      // Auto-dismiss after ms (0 = no auto-dismiss)
      icon = null,          // Custom icon
      action = null,        // Optional action button { label, onClick }
    } = options;

    const id = `toast_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;

    const toast = {
      id,
      message,
      type,
      icon,
      action,
      createdAt: Date.now(),
    };

    set(state => ({
      toasts: [...state.toasts, toast]
    }));

    // Auto-dismiss after duration
    if (duration > 0) {
      setTimeout(() => {
        get().dismissToast(id);
      }, duration);
    }

    return id;
  },

  // Dismiss a toast by ID
  dismissToast: (id) => {
    set(state => ({
      toasts: state.toasts.filter(t => t.id !== id)
    }));
  },

  // Clear all toasts
  clearToasts: () => {
    set({ toasts: [] });
  },
}));

/**
 * Hook for easy toast usage
 * @returns {Object} { showToast, dismissToast, clearToasts }
 */
export const useToast = () => {
  const { showToast, dismissToast, clearToasts } = useToastStore();
  return { showToast, dismissToast, clearToasts };
};

export default useToastStore;
