import { useCallback, useEffect, useRef } from 'react';
import usePlaygroundStore from '../../stores/playgroundStore';

// Grid size must match PlaygroundCanvas snapGrid
const GRID_SIZE = 16;
const HEADER_HEIGHT = 32; // Approximate header height for image nodes
const FOOTER_HEIGHT = 28; // Approximate footer height for image nodes

/**
 * useNodeResize - Custom hook for node resize functionality
 *
 * Enables dragging the bottom-right corner to resize nodes.
 * Prevents node dragging while resizing using React Flow's 'nodrag' class
 * and pointer event handling. Snaps to grid for consistency with node movement.
 *
 * When a node has an aspectRatio set (e.g., image nodes), resizing maintains
 * the aspect ratio by adjusting height based on width changes.
 *
 * @param {string} nodeId - The node ID
 * @param {object} options - Configuration options
 * @param {number} options.minWidth - Minimum width (default: 150)
 * @param {number} options.minHeight - Minimum height (default: 100)
 * @param {number} options.maxWidth - Maximum width (default: 600)
 * @param {number} options.maxHeight - Maximum height (default: 600)
 */
export default function useNodeResize(nodeId, options = {}) {
  const {
    minWidth = 150,
    minHeight = 100,
    maxWidth = 600,
    maxHeight = 600,
  } = options;

  // Snap value to grid
  const snapToGrid = (value) => Math.round(value / GRID_SIZE) * GRID_SIZE;

  const updateNodeData = usePlaygroundStore((state) => state.updateNodeData);

  // Track resize state
  const resizeState = useRef({
    isResizing: false,
    startX: 0,
    startY: 0,
    startWidth: 0,
    startHeight: 0,
  });

  // Handle pointer/mouse move during resize
  const handlePointerMove = useCallback((e) => {
    if (!resizeState.current.isResizing) return;

    const { startX, startY, startWidth, startHeight, aspectRatio } = resizeState.current;

    // Calculate new dimensions
    const deltaX = e.clientX - startX;
    const deltaY = e.clientY - startY;

    let newWidth, newHeight;

    if (aspectRatio) {
      // Aspect-locked resizing for image nodes
      // Use width delta as primary driver
      const rawWidth = startWidth + deltaX;
      const snappedWidth = snapToGrid(rawWidth);
      newWidth = Math.min(maxWidth, Math.max(minWidth, snappedWidth));

      // Calculate height to maintain aspect ratio
      // Content height = width / aspectRatio, then add header/footer
      const contentHeight = newWidth / aspectRatio;
      const totalHeight = contentHeight + HEADER_HEIGHT + FOOTER_HEIGHT;
      const snappedHeight = snapToGrid(totalHeight);
      newHeight = Math.min(maxHeight, Math.max(minHeight, snappedHeight));
    } else {
      // Free resizing for non-image nodes
      const rawWidth = startWidth + deltaX;
      const rawHeight = startHeight + deltaY;
      const snappedWidth = snapToGrid(rawWidth);
      const snappedHeight = snapToGrid(rawHeight);
      newWidth = Math.min(maxWidth, Math.max(minWidth, snappedWidth));
      newHeight = Math.min(maxHeight, Math.max(minHeight, snappedHeight));
    }

    // Update node data
    updateNodeData(nodeId, {
      width: newWidth,
      height: newHeight,
    });
  }, [nodeId, updateNodeData, minWidth, minHeight, maxWidth, maxHeight, snapToGrid]);

  // Handle pointer/mouse up to stop resize
  const handlePointerUp = useCallback(() => {
    if (!resizeState.current.isResizing) return;

    resizeState.current.isResizing = false;
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
  }, []);

  // Attach/detach window listeners for both mouse and pointer events
  useEffect(() => {
    // Use pointer events (React Flow uses these internally)
    window.addEventListener('pointermove', handlePointerMove);
    window.addEventListener('pointerup', handlePointerUp);
    // Fallback to mouse events for broader compatibility
    window.addEventListener('mousemove', handlePointerMove);
    window.addEventListener('mouseup', handlePointerUp);

    return () => {
      window.removeEventListener('pointermove', handlePointerMove);
      window.removeEventListener('pointerup', handlePointerUp);
      window.removeEventListener('mousemove', handlePointerMove);
      window.removeEventListener('mouseup', handlePointerUp);
    };
  }, [handlePointerMove, handlePointerUp]);

  // Start resize on handle pointerdown
  // Note: The resize handle element MUST have className="nodrag" for React Flow
  const onResizeStart = useCallback((e) => {
    // Stop all event propagation
    e.stopPropagation();
    e.preventDefault();

    // Get current dimensions from the node element
    const nodeElement = e.target.closest('.react-flow__node');
    const currentWidth = nodeElement?.offsetWidth || minWidth;
    const currentHeight = nodeElement?.offsetHeight || minHeight;

    // Get aspect ratio from node data (if set, e.g., for image nodes)
    const nodeData = usePlaygroundStore.getState().nodes.find(n => n.id === nodeId)?.data;
    const aspectRatio = nodeData?.aspectRatio;

    resizeState.current = {
      isResizing: true,
      startX: e.clientX,
      startY: e.clientY,
      startWidth: currentWidth,
      startHeight: currentHeight,
      aspectRatio, // Will be undefined for non-image nodes
    };

    // Set cursor during resize
    document.body.style.cursor = 'nwse-resize';
    document.body.style.userSelect = 'none';
  }, [nodeId, minWidth, minHeight]);

  return { onResizeStart };
}
