import React from 'react';
import ReactDOM from 'react-dom/client';
import { RouterProvider } from 'react-router-dom';
import './index.css';
import './styles/index.css'; // Import global design system
import { router } from './routes';

// Suppress benign ResizeObserver error from React Flow
// This error occurs when resize callbacks can't be delivered in a single animation frame
// It's harmless but noisy - see: https://github.com/xyflow/xyflow/issues/3076
const resizeObserverErr = window.onerror;
window.onerror = (message, ...args) => {
  if (message?.includes?.('ResizeObserver loop')) {
    return true; // Suppress
  }
  return resizeObserverErr?.(message, ...args);
};

// Also suppress in error event listener (for the overlay)
window.addEventListener('error', (event) => {
  if (event.message?.includes?.('ResizeObserver loop')) {
    event.stopImmediatePropagation();
    event.preventDefault();
  }
});

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>
);
