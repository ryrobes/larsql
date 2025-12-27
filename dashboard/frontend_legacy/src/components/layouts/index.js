/**
 * Layout Components Index
 *
 * All layout types for the generative UI system.
 */

export { default as TwoColumnLayout } from './TwoColumnLayout';
export { default as GridLayout } from './GridLayout';
export { default as SidebarLayout } from './SidebarLayout';

// Layout type to component mapping
export const LAYOUT_COMPONENTS = {
  'two-column': 'TwoColumnLayout',
  'three-column': 'GridLayout',
  'grid': 'GridLayout',
  'sidebar-left': 'SidebarLayout',
  'sidebar-right': 'SidebarLayout',
};
