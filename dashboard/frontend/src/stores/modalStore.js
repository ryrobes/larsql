import { create } from 'zustand';

/**
 * Modal Store
 *
 * Manages modal dialogs with stack support (multiple modals).
 * Handles focus management, keyboard shortcuts, and backdrop clicks.
 */
const useModalStore = create((set, get) => ({
  // Stack of active modals (can have multiple)
  modals: [],

  // Open a modal
  openModal: (id, content, options = {}) => {
    const {
      size = 'md',           // 'sm' | 'md' | 'lg' | 'xl' | 'full'
      closeOnBackdrop = true,
      closeOnEscape = true,
      showClose = true,
    } = options;

    const modal = {
      id,
      content,
      size,
      closeOnBackdrop,
      closeOnEscape,
      showClose,
      createdAt: Date.now(),
    };

    set(state => ({
      modals: [...state.modals, modal]
    }));

    // Setup escape key handler if enabled
    if (closeOnEscape) {
      const handleEscape = (e) => {
        if (e.key === 'Escape') {
          const currentModals = get().modals;
          if (currentModals[currentModals.length - 1]?.id === id) {
            get().closeModal(id);
          }
        }
      };

      // Store handler for cleanup
      modal._escapeHandler = handleEscape;
      document.addEventListener('keydown', handleEscape);
    }

    return id;
  },

  // Close a modal by ID
  closeModal: (id) => {
    const modals = get().modals;
    const modal = modals.find(m => m.id === id);

    // Cleanup escape handler
    if (modal?._escapeHandler) {
      document.removeEventListener('keydown', modal._escapeHandler);
    }

    set(state => ({
      modals: state.modals.filter(m => m.id !== id)
    }));
  },

  // Close the topmost modal
  closeTopModal: () => {
    const modals = get().modals;
    if (modals.length > 0) {
      const topModal = modals[modals.length - 1];
      get().closeModal(topModal.id);
    }
  },

  // Close all modals
  closeAllModals: () => {
    const modals = get().modals;

    // Cleanup all escape handlers
    modals.forEach(modal => {
      if (modal._escapeHandler) {
        document.removeEventListener('keydown', modal._escapeHandler);
      }
    });

    set({ modals: [] });
  },
}));

/**
 * Hook for easy modal usage
 * @returns {Object} { openModal, closeModal, closeTopModal, closeAllModals }
 */
export const useModal = () => {
  const { openModal, closeModal, closeTopModal, closeAllModals } = useModalStore();
  return { openModal, closeModal, closeTopModal, closeAllModals };
};

export default useModalStore;
