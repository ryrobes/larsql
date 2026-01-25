/**
 * useQueryViewZones - Manage Monaco View Zones for query action bars
 *
 * Creates rich React components above each query block
 */

import { useEffect, useRef } from 'react';
import ReactDOM from 'react-dom/client';
import QueryActionBar from '../components/QueryActionBar';

export function useQueryViewZones({
  editorRef,
  monacoRef,
  queries,
  queryExplains,
  onRunSoloQuery,
}) {
  const viewZonesRef = useRef([]);
  const reactRootsRef = useRef([]);

  useEffect(() => {
    if (!editorRef.current || !monacoRef.current || !queries || queries.length === 0) {
      return;
    }

    const editor = editorRef.current;
    const monaco = monacoRef.current;

    // Clear old view zones
    if (viewZonesRef.current.length > 0) {
      editor.changeViewZones((changeAccessor) => {
        viewZonesRef.current.forEach(zoneId => {
          changeAccessor.removeZone(zoneId);
        });
      });
      viewZonesRef.current = [];
    }

    // Cleanup old React roots
    reactRootsRef.current.forEach(root => {
      try {
        root.unmount();
      } catch (e) {
        console.debug('[viewzone] Failed to unmount root:', e);
      }
    });
    reactRootsRef.current = [];

    // Create new view zones for each query
    editor.changeViewZones((changeAccessor) => {
      queries.forEach((query, idx) => {
        // Create DOM node for this view zone
        const domNode = document.createElement('div');
        domNode.className = 'query-viewzone-container';
        domNode.style.width = '100%';

        // Get explain data for this query
        const queryHash = require('../utils/querySplitter').hashQuery(query.text);
        const explain = queryExplains?.get?.(queryHash);

        // Render React component into DOM node
        const root = ReactDOM.createRoot(domNode);
        root.render(
          <QueryActionBar
            query={query}
            explain={explain}
            onRunSolo={() => {
              console.log('[viewzone] Play button clicked for query', idx);
              onRunSoloQuery(query, idx);
            }}
          />
        );

        reactRootsRef.current.push(root);

        // Add view zone ABOVE the query
        // Important: Monaco View Zones render BETWEEN lines, pushing content down
        const zoneId = changeAccessor.addZone({
          afterLineNumber: query.startLine - 1,
          heightInPx: 24, // Compact height
          domNode: domNode,
          suppressMouseDown: false,
        });

        viewZonesRef.current.push(zoneId);
      });
    });

    // Force layout recalculation after adding zones
    setTimeout(() => {
      editor.layout();
    }, 0);

    // Cleanup on unmount
    return () => {
      if (viewZonesRef.current.length > 0 && editor) {
        try {
          editor.changeViewZones((changeAccessor) => {
            viewZonesRef.current.forEach(zoneId => {
              changeAccessor.removeZone(zoneId);
            });
          });
        } catch (e) {
          console.debug('[viewzone] Cleanup failed:', e);
        }
      }

      reactRootsRef.current.forEach(root => {
        try {
          root.unmount();
        } catch (e) {
          console.debug('[viewzone] Unmount failed:', e);
        }
      });
    };
  }, [editorRef, monacoRef, queries, queryExplains, onRunSoloQuery]);
}
