/**
 * Calliope Bridge - Screenshot capture for Calliope visual validation
 *
 * DO NOT MODIFY - This file enables Calliope to capture screenshots.
 * It is framework-agnostic and works with React, HTMX, or any other setup.
 */

(function() {
    'use strict';

    window.addEventListener('message', async (event) => {
        if (event.data?.type === 'CALLIOPE_SCREENSHOT_REQUEST') {
            try {
                if (typeof html2canvas !== 'function') {
                    throw new Error('html2canvas not loaded');
                }

                const canvas = await html2canvas(document.body, {
                    backgroundColor: '#0a0a0f',
                    scale: 1,
                    logging: false,
                    useCORS: true,
                });
                const dataUrl = canvas.toDataURL('image/png');

                window.parent.postMessage({
                    type: 'CALLIOPE_SCREENSHOT_RESPONSE',
                    requestId: event.data.requestId,
                    screenshot: dataUrl,
                }, '*');
            } catch (err) {
                console.error('Calliope screenshot capture failed:', err);
                window.parent.postMessage({
                    type: 'CALLIOPE_SCREENSHOT_RESPONSE',
                    requestId: event.data.requestId,
                    error: err.message,
                }, '*');
            }
        }
    });
})();
