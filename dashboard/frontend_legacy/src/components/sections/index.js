/**
 * Section Components Index
 *
 * All UI section types for the generative UI system.
 */

// New rich content sections
export { default as ImageSection } from './ImageSection';
export { default as DataTableSection } from './DataTableSection';
export { default as CodeSection } from './CodeSection';
export { default as CardGridSection } from './CardGridSection';
export { default as ComparisonSection } from './ComparisonSection';
export { default as AccordionSection } from './AccordionSection';
export { default as TabsSection } from './TabsSection';

// Section type to component mapping
export const SECTION_COMPONENTS = {
  image: 'ImageSection',
  data_table: 'DataTableSection',
  code: 'CodeSection',
  card_grid: 'CardGridSection',
  comparison: 'ComparisonSection',
  accordion: 'AccordionSection',
  tabs: 'TabsSection',
};
