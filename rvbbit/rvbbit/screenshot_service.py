"""
Screenshot Service - Server-side rendering of HTMX/Plotly/Vega-Lite content

Uses Playwright to render HTML in a headless browser and capture screenshots.
Provides thumbnails for artifacts and visual records of checkpoint interactions.
"""
import os
import asyncio
import threading
from typing import Optional
from pathlib import Path


class ScreenshotService:
    """
    Service for capturing screenshots of HTML content using Playwright.

    Runs async in background thread to avoid blocking cascade execution.
    Browser instance is reused across captures for performance.
    """

    def __init__(self):
        self._browser = None
        self._context = None
        self._loop = None
        self._thread = None
        self._queue = asyncio.Queue() if hasattr(asyncio, 'Queue') else None

    async def _ensure_browser(self):
        """Ensure Playwright browser is initialized."""
        if self._browser is not None:
            return

        try:
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()

            # Launch Chromium in headless mode
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-dev-shm-usage']  # Docker-friendly
            )

            # Create persistent context with dark theme
            self._context = await self._browser.new_context(
                viewport={'width': 1200, 'height': 800},
                color_scheme='dark',
                device_scale_factor=2  # Retina for crisp screenshots
            )

            print("[Screenshots] Playwright browser initialized")

        except ImportError:
            print("[Screenshots] ERROR: Playwright not installed. Run: pip install playwright && playwright install chromium")
            raise
        except Exception as e:
            print(f"[Screenshots] ERROR: Failed to initialize Playwright: {e}")
            raise

    async def capture_html_async(
        self,
        html: str,
        output_path: str,
        wait_for_charts: bool = True,
        wait_seconds: float = 3.0
    ) -> bool:
        """
        Render HTML and capture screenshot (async).

        Args:
            html: Complete HTML document to render
            output_path: Where to save screenshot
            wait_for_charts: If True, wait for Plotly/Vega-Lite to finish
            wait_seconds: How long to wait for rendering (default 3s)

        Returns:
            True if successful, False otherwise
        """
        try:
            await self._ensure_browser()

            # Create new page
            page = await self._context.new_page()

            try:
                # Set HTML content
                await page.set_content(html, wait_until='networkidle', timeout=10000)

                # Wait for visualization libraries if needed
                if wait_for_charts:
                    # Wait for Plotly charts
                    try:
                        await page.wait_for_function(
                            "typeof Plotly !== 'undefined' && Plotly._redrawCount !== undefined",
                            timeout=2000
                        )
                    except:
                        pass  # Plotly might not be used

                    # Wait for Vega-Lite
                    try:
                        await page.wait_for_function(
                            "typeof vegaEmbed !== 'undefined'",
                            timeout=2000
                        )
                    except:
                        pass  # Vega might not be used

                    # Additional wait for charts to finish rendering
                    await asyncio.sleep(wait_seconds)

                # Ensure output directory exists
                os.makedirs(os.path.dirname(output_path), exist_ok=True)

                # Capture screenshot
                await page.screenshot(path=output_path, full_page=True)

                print(f"[Screenshots] Captured: {output_path}")
                return True

            finally:
                await page.close()

        except Exception as e:
            print(f"[Screenshots] ERROR: Failed to capture screenshot: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def capture_pdf_async(
        self,
        html: str,
        output_path: str,
        wait_for_charts: bool = True,
        wait_seconds: float = 3.0
    ) -> bool:
        """
        Render HTML and capture as PDF (async).

        Args:
            html: Complete HTML document to render
            output_path: Where to save PDF
            wait_for_charts: If True, wait for Plotly/Vega-Lite to finish
            wait_seconds: How long to wait for rendering (default 3s)

        Returns:
            True if successful, False otherwise
        """
        try:
            await self._ensure_browser()

            # Create new page
            page = await self._context.new_page()

            try:
                # Set HTML content
                await page.set_content(html, wait_until='networkidle', timeout=10000)

                # Wait for visualization libraries if needed
                if wait_for_charts:
                    # Wait for Plotly charts
                    try:
                        await page.wait_for_function(
                            "typeof Plotly !== 'undefined' && Plotly._redrawCount !== undefined",
                            timeout=2000
                        )
                    except:
                        pass  # Plotly might not be used

                    # Wait for Vega-Lite
                    try:
                        await page.wait_for_function(
                            "typeof vegaEmbed !== 'undefined'",
                            timeout=2000
                        )
                    except:
                        pass  # Vega might not be used

                    # Additional wait for charts to finish rendering
                    await asyncio.sleep(wait_seconds)

                # Ensure output directory exists
                os.makedirs(os.path.dirname(output_path), exist_ok=True)

                # Capture as PDF
                await page.pdf(
                    path=output_path,
                    format='A4',
                    print_background=True,
                    margin={'top': '0.5in', 'bottom': '0.5in', 'left': '0.5in', 'right': '0.5in'}
                )

                print(f"[Screenshots] PDF captured: {output_path}")
                return True

            finally:
                await page.close()

        except Exception as e:
            print(f"[Screenshots] ERROR: Failed to capture PDF: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def capture_pdfs_and_merge(
        self,
        html_contents: list,
        output_path: str,
        wait_for_charts: bool = True,
        wait_seconds: float = 2.0
    ) -> bool:
        """
        Render multiple HTML documents and merge into a single PDF.

        Args:
            html_contents: List of (title, html) tuples
            output_path: Where to save merged PDF
            wait_for_charts: If True, wait for Plotly/Vega-Lite to finish
            wait_seconds: How long to wait for each page rendering

        Returns:
            True if successful, False otherwise
        """
        import tempfile
        try:
            from pypdf import PdfMerger
        except ImportError:
            print("[Screenshots] ERROR: pypdf not installed. Run: pip install pypdf")
            return False

        temp_pdfs = []
        merger = PdfMerger()

        try:
            await self._ensure_browser()

            for i, (title, html) in enumerate(html_contents):
                # Create temp file for each PDF
                temp_fd, temp_path = tempfile.mkstemp(suffix='.pdf')
                os.close(temp_fd)
                temp_pdfs.append(temp_path)

                # Capture PDF
                success = await self.capture_pdf_async(
                    html=html,
                    output_path=temp_path,
                    wait_for_charts=wait_for_charts,
                    wait_seconds=wait_seconds
                )

                if success:
                    merger.append(temp_path)
                    print(f"[Screenshots] Added PDF {i+1}/{len(html_contents)}: {title}")
                else:
                    print(f"[Screenshots] WARNING: Failed to capture PDF for: {title}")

            # Ensure output directory exists
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            # Write merged PDF
            merger.write(output_path)
            merger.close()

            print(f"[Screenshots] Merged PDF saved: {output_path}")
            return True

        except Exception as e:
            print(f"[Screenshots] ERROR: Failed to merge PDFs: {e}")
            import traceback
            traceback.print_exc()
            return False

        finally:
            # Cleanup temp files
            for temp_path in temp_pdfs:
                try:
                    os.unlink(temp_path)
                except:
                    pass

    def capture_htmx_render(
        self,
        html: str,
        session_id: str,
        cell_name: str,
        candidate_index: Optional[int] = None,
        render_type: str = "htmx",
        unique_id: Optional[str] = None
    ):
        """
        Capture screenshot of HTMX render.

        Path strategy:
        - With unique_id: /images/{session}/{cell}/{render_type}_{unique_id}.png (unique, never overwrites)
        - With candidate (no unique_id): /images/{session}/{cell}/{render_type}_s{N}.png (overwrites per candidate)
        - No candidate, no unique_id: /images/{session}/{cell}/{render_type}_latest.png (overwrites)

        Args:
            html: Complete HTML document to render
            session_id: Session identifier
            cell_name: Cell/cell name
            candidate_index: Optional candidate index for parallel candidates
            render_type: Type prefix for filename (default "htmx")
            unique_id: Optional unique identifier (e.g., checkpoint_id) for persistent screenshots

        Queues screenshot task to run in background thread.
        Returns immediately - screenshot happens asynchronously.
        """
        from .config import get_config

        cfg = get_config()
        image_dir = cfg.image_dir

        # Build path - unique_id takes precedence for persistent screenshots
        if unique_id:
            # Unique ID provided - create a unique, non-overwriting screenshot
            # Truncate to 12 chars for reasonable filename length
            filename = f"{render_type}_{unique_id[:12]}.png"
        elif candidate_index is not None:
            filename = f"{render_type}_s{candidate_index}.png"
        else:
            filename = f"{render_type}_latest.png"

        output_path = os.path.join(
            image_dir,
            session_id,
            cell_name,
            filename
        )

        if unique_id:
            print(f"[Screenshots] Queuing HTMX screenshot (unique): {output_path}")
        else:
            print(f"[Screenshots] Queuing HTMX screenshot (overwrites): {output_path}")

        # Queue async capture
        self._queue_capture(html, output_path)

        return output_path

    def capture_artifact_sync(
        self,
        artifact_id: str,
        html: str
    ):
        """
        Capture screenshot of artifact for gallery thumbnail (non-blocking, sync wrapper).

        Queues screenshot task to run in background thread.
        Returns immediately - screenshot happens asynchronously.
        """
        from .config import get_config

        cfg = get_config()
        image_dir = cfg.image_dir

        # Build path: /images/artifacts/{artifact_id}.png
        output_path = os.path.join(
            image_dir,
            "artifacts",
            f"{artifact_id}.png"
        )

        print(f"[Screenshots] Queuing artifact screenshot: {output_path}")

        # Queue async capture
        self._queue_capture(html, output_path)

        return output_path

    def _queue_capture(self, html: str, output_path: str):
        """Queue a screenshot capture task."""
        # Start background thread if not running
        if self._thread is None or not self._thread.is_alive():
            self._start_worker_thread()

        # Add to queue
        try:
            # Create new event loop if needed
            if self._loop is None:
                return  # Worker thread will create it

            # Queue the task
            asyncio.run_coroutine_threadsafe(
                self._process_capture(html, output_path),
                self._loop
            )
        except Exception as e:
            print(f"[Screenshots] Failed to queue capture: {e}")

    def _start_worker_thread(self):
        """Start background worker thread for async screenshot processing."""
        def worker():
            # Create event loop for this thread
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)

            print("[Screenshots] Worker thread started")

            # Keep loop running
            self._loop.run_forever()

        self._thread = threading.Thread(target=worker, daemon=True)
        self._thread.start()

    async def _process_capture(self, html: str, output_path: str):
        """Process a screenshot capture task."""
        try:
            await self.capture_html_async(html, output_path, wait_for_charts=True, wait_seconds=3.0)
        except Exception as e:
            print(f"[Screenshots] Capture failed for {output_path}: {e}")

    async def cleanup(self):
        """Clean up browser resources."""
        if self._browser:
            await self._browser.close()
            await self._playwright.stop()
            self._browser = None
            self._context = None
            print("[Screenshots] Browser closed")


# Global singleton
_screenshot_service: Optional[ScreenshotService] = None
_service_lock = threading.Lock()


def get_screenshot_service() -> ScreenshotService:
    """Get the global screenshot service singleton."""
    global _screenshot_service

    if _screenshot_service is None:
        with _service_lock:
            if _screenshot_service is None:
                _screenshot_service = ScreenshotService()

    return _screenshot_service
