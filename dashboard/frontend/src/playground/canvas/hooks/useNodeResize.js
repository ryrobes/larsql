import { useCallback, useEffect, useRef } from 'react';
import usePlaygroundStore from '../../stores/playgroundStore';

// Grid size must match PlaygroundCanvas snapGrid
const GRID_SIZE = 16;

/**
 * useNodeResize - Custom hook for node resize functionality
 *
 * Enables dragging the bottom-right corner to resize nodes.
 * Prevents node dragging while resizing using React Flow's 'nodrag' class
 * and pointer event handling. Snaps to grid for consistency with node movement.
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

    const { startX, startY, startWidth, startHeight } = resizeState.current;

    // Calculate new dimensions
    const deltaX = e.clientX - startX;
    const deltaY = e.clientY - startY;

    // Snap to grid, then clamp to min/max
    const rawWidth = startWidth + deltaX;
    const rawHeight = startHeight + deltaY;
    const snappedWidth = snapToGrid(rawWidth);
    const snappedHeight = snapToGrid(rawHeight);
    const newWidth = Math.min(maxWidth, Math.max(minWidth, snappedWidth));
    const newHeight = Math.min(maxHeight, Math.max(minHeight, snappedHeight));

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

    resizeState.current = {
      isResizing: true,
      startX: e.clientX,
      startY: e.clientY,
      startWidth: currentWidth,
      startHeight: currentHeight,
    };

    // Set cursor during resize
    document.body.style.cursor = 'nwse-resize';
    document.body.style.userSelect = 'none';
  }, [minWidth, minHeight]);

  return { onResizeStart };
}
