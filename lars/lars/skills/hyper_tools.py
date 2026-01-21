"""
HyperSQL verification tools.

Provides tools for verifying HyperSQL dashboard SQL by rendering it
in a headless browser and capturing screenshots.
"""

import asyncio
import base64
import os
from typing import Optional
from .base import simple_eddy
import re


@simple_eddy
def verify_hyper(
    sql: str,
    base_url: Optional[str] = None,
    timeout_seconds: int = 30,
    wait_for_render: float = 3.0,
) -> dict:
    """
    Verify HyperSQL dashboard by rendering it in a headless browser.

    Loads the /hyper page, injects the SQL into the Monaco editor,
    executes it, waits for rendering, and captures a screenshot.
    Returns the screenshot and any errors found.

    Use this tool to verify that generated HyperSQL SQL renders correctly
    before returning it to the user. If errors are found, analyze the
    screenshot and error messages to fix the SQL.

    Args:
        sql: The HyperSQL SQL to execute and verify
        base_url: Base URL of the LARS studio server (default: http://localhost:5050)
        timeout_seconds: Maximum time to wait for page load
        wait_for_render: Seconds to wait for charts/panels to render after execution

    Returns:
        dict with:
          - success: bool - Whether dashboard rendered without visible errors
          - screenshot: str - Base64-encoded PNG of the rendered dashboard
          - errors: list[str] - Any error messages found in the DOM
          - page_title: str - The page title after render
    """
    # Run async function in sync context
    # Create a new event loop if we're in a thread without one (e.g., Flask)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # We're inside an async context - can't use run_until_complete
        # Create a new loop in a thread
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(
                asyncio.run,
                _verify_hyper_async(sql, base_url, timeout_seconds, wait_for_render)
            )
            return future.result()
    else:
        # No running loop - create one
        return asyncio.run(
            _verify_hyper_async(sql, base_url, timeout_seconds, wait_for_render)
        )


def _compress_screenshot(png_bytes: bytes, max_width: int = 1280, quality: int = 65) -> tuple[bytes, str]:
    """
    Compress a screenshot to reduce token usage.

    - Resizes to max_width (maintaining aspect ratio)
    - Tries JPEG compression, uses whichever is smaller
    - Returns (compressed_bytes, mime_type)
    """
    try:
        from PIL import Image
        import io

        # Load PNG
        img = Image.open(io.BytesIO(png_bytes))
        original_size = img.size

        # Resize if wider than max_width
        if img.width > max_width:
            ratio = max_width / img.width
            new_height = int(img.height * ratio)
            img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)

        # Convert to RGB for JPEG (doesn't support alpha)
        img_rgb = img.convert('RGB') if img.mode in ('RGBA', 'P') else img

        # Try JPEG compression
        jpeg_buffer = io.BytesIO()
        img_rgb.save(jpeg_buffer, format='JPEG', quality=quality, optimize=True)
        jpeg_bytes = jpeg_buffer.getvalue()

        # Also get resized PNG for comparison
        png_buffer = io.BytesIO()
        img.save(png_buffer, format='PNG', optimize=True)
        resized_png_bytes = png_buffer.getvalue()

        # Use whichever is smaller
        if len(jpeg_bytes) < len(resized_png_bytes):
            return jpeg_bytes, 'image/jpeg'
        else:
            return resized_png_bytes, 'image/png'

    except ImportError:
        # PIL not available, return original
        return png_bytes, 'image/png'
    except Exception:
        # Any error, return original
        return png_bytes, 'image/png'


async def _verify_hyper_async(
    sql: str,
    base_url: Optional[str],
    timeout_seconds: int,
    wait_for_render: float,
) -> dict:
    """Async implementation of verify_hyper."""
    from lars.browser import BrowserSession

    # Default base URL - use 5550 for React dev server, 5050 for production
    if base_url is None:
        base_url = os.environ.get("LARS_STUDIO_URL", "http://localhost:5550")

    session = None
    try:
        # Create browser session
        # Use full 1080p viewport so all dashboard elements render properly
        # Compression step will resize to 1280px for token savings
        session = BrowserSession(
            session_id="hyper_verify",
            cell_name="visual_check",
            viewport=(1920, 1080),
            headless=True,
        )

        # Initialize and navigate to /hyper
        await session.initialize(
            f"{base_url}/hyper",
            timeout=timeout_seconds * 1000
        )

        # Wait for Monaco editor to be ready
        try:
            await session.page.wait_for_selector('.monaco-editor', timeout=10000)
        except Exception as e:
            return {
                "success": False,
                "screenshot": "",
                "errors": [f"Monaco editor not found: {e}"],
                "page_title": await session.page.title(),
            }

        # Inject SQL into Monaco editor
        inject_result = await session.page.evaluate("""
            (sql) => {
                // Try multiple ways to find the Monaco editor instance
                const editor = window.monacoEditor ||
                               window.hyperSqlMonaco ||
                               window.editor;

                if (!editor) {
                    return { success: false, error: 'Monaco editor instance not found on window' };
                }

                try {
                    // Set the SQL content
                    const model = editor.getModel();
                    if (!model) {
                        return { success: false, error: 'Editor model not found' };
                    }
                    model.setValue(sql);
                    return { success: true };
                } catch (e) {
                    return { success: false, error: e.message };
                }
            }
        """, sql)

        if not inject_result.get("success"):
            return {
                "success": False,
                "screenshot": "",
                "errors": [f"Failed to inject SQL: {inject_result.get('error', 'unknown error')}"],
                "page_title": await session.page.title(),
            }

        # Trigger execution by clicking the Run button (more reliable than Ctrl+Enter)
        run_btn = await session.page.query_selector('button:has-text("Run")')
        if run_btn:
            await run_btn.click()
        else:
            # Fallback to keyboard shortcut
            await session.page.keyboard.press("Control+Enter")

        # Wait for rendering to complete
        await asyncio.sleep(wait_for_render)

        # Check for error indicators in the DOM
        errors = await session.page.evaluate("""
            () => {
                const errors = [];

                // Check for panel error states
                const errorPanels = document.querySelectorAll(
                    '.panel-error, .error-message, [data-error="true"], .query-error'
                );
                errorPanels.forEach(el => {
                    const text = el.textContent?.trim();
                    if (text && text.length < 500) {
                        errors.push(text);
                    }
                });

                // Check for SQL error display
                const sqlErrors = document.querySelectorAll('.sql-error, .execution-error');
                sqlErrors.forEach(el => {
                    const text = el.textContent?.trim();
                    if (text && text.length < 500) {
                        errors.push(text);
                    }
                });

                // Check for toast/notification errors
                const toasts = document.querySelectorAll('.toast-error, .notification-error');
                toasts.forEach(el => {
                    const text = el.textContent?.trim();
                    if (text) {
                        errors.push(text);
                    }
                });

                return errors;
            }
        """)

        # Capture screenshot and compress to reduce token usage
        # Playwright captures PNG, then we resize and optionally convert to JPEG
        screenshot_bytes = await session.page.screenshot(
            type='png',
            full_page=False,  # Just viewport
        )

        # Compress: resize to 1280px wide, use JPEG if smaller
        # This typically reduces 50k+ tokens to ~10-15k tokens
        compressed_bytes, mime_type = _compress_screenshot(screenshot_bytes, max_width=1280, quality=65)

        # Create data URL with appropriate mime type
        screenshot_b64 = f"data:{mime_type};base64,{base64.b64encode(compressed_bytes).decode('utf-8')}"

        # Get page title for context
        page_title = await session.page.title()

        # Determine success - no errors found
        success = len(errors) == 0

        return {
            "success": success,
            "screenshot": screenshot_b64,
            "errors": errors,
            "page_title": page_title,
        }

    except Exception as e:
        return {
            "success": False,
            "screenshot": "",
            "errors": [f"Browser automation error: {str(e)}"],
            "page_title": "",
        }

    finally:
        if session:
            try:
                await session.close()
            except Exception:
                pass  # Ignore cleanup errors


@simple_eddy
def valid_hyper(content: str = None, text: str = None, execute: bool = True, **kwargs) -> dict:
    """
    Validate that content looks like HyperSQL dashboard SQL.

    Two-phase validation:
    1. Structural checks: --- PANEL comments and SELECT statements
    2. Execution check: Actually run queries through the rewriter pipeline

    Use this as a loop_until validator to ensure the agent produces
    actual HyperSQL before exiting.

    Args:
        content: The content to validate (passed by ward system)
        text: Alternative parameter name (for direct calls)
        execute: If True, actually execute queries to check for SQL errors (default: True)
        **kwargs: Ignore other arguments (like images)

    Returns:
        dict with:
          - valid: bool - Whether it looks like valid HyperSQL
          - reason: str - Why it failed (if invalid)
          - panel_count: int - Number of panels found
          - sql_errors: list[str] - Any SQL execution errors (if execute=True)
    """
    # Accept either 'content' or 'text' parameter
    input_text = content or text

    # Handle case where content might be a dict or list (e.g., multimodal content)
    if isinstance(input_text, (list, dict)):
        # Try to extract text from structured content
        if isinstance(input_text, list):
            # Multimodal content - extract text parts
            text_parts = []
            for item in input_text:
                if isinstance(item, str):
                    text_parts.append(item)
                elif isinstance(item, dict) and item.get('type') == 'text':
                    text_parts.append(item.get('text', ''))
            input_text = '\n'.join(text_parts)
        elif isinstance(input_text, dict):
            # Try common keys
            input_text = input_text.get('text') or input_text.get('content') or input_text.get('sql') or str(input_text)

    if not input_text or not isinstance(input_text, str):
        return {
            "valid": False,
            "reason": "No text provided or text is not a string",
            "panel_count": 0,
            "sql_errors": [],
        }

    # Strip markdown code fences if present
    clean_text = input_text.strip()
    if clean_text.startswith('```sql'):
        clean_text = clean_text[6:]
    elif clean_text.startswith('```'):
        clean_text = clean_text[3:]
    if clean_text.endswith('```'):
        clean_text = clean_text[:-3]
    clean_text = clean_text.strip()

    # Check for PANEL comments
    panel_pattern = r'---\s*PANEL\s+'
    panels = re.findall(panel_pattern, clean_text, re.IGNORECASE)
    panel_count = len(panels)

    if panel_count == 0:
        return {
            "valid": False,
            "reason": "No --- PANEL comments found",
            "panel_count": 0,
            "sql_errors": [],
        }

    # Check for SELECT statements
    select_pattern = r'\bSELECT\b'
    selects = re.findall(select_pattern, clean_text, re.IGNORECASE)

    if len(selects) == 0:
        return {
            "valid": False,
            "reason": "No SELECT statements found",
            "panel_count": panel_count,
            "sql_errors": [],
        }

    # Phase 2: Execute queries to check for SQL errors
    if execute:
        sql_errors = _execute_hyper_queries(clean_text)
        if sql_errors:
            return {
                "valid": False,
                "reason": f"SQL execution errors: {sql_errors[0]}",
                "panel_count": panel_count,
                "sql_errors": sql_errors,
            }

    # Looks valid!
    return {
        "valid": True,
        "reason": f"Found {panel_count} panels with {len(selects)} SELECT statements",
        "panel_count": panel_count,
        "sql_errors": [],
    }


def _execute_hyper_queries(sql: str) -> list:
    """
    Execute HyperSQL queries through the full rewriter pipeline.

    Matches the execution path used by UI and PGwire:
    1. preprocess_deref_cascades() - handles @param_get, @param_set, etc.
    2. ensure_lazy_attach() - attaches external databases
    3. rewrite_lars_syntax() - rewrites LARS extended SQL

    Returns a list of error messages, or empty list if all queries succeed.
    """
    import duckdb
    import logging
    import uuid

    log = logging.getLogger(__name__)
    errors = []

    try:
        # Import the panel parser and rewriters
        from lars.studio.backend.sql_server_api import parse_multi_panel_query
        from lars.sql_rewriter import rewrite_lars_syntax
        from lars.sql_tools.database_manager import ensure_lazy_attach
        from lars.sql_tools.deref_preprocessor import preprocess_deref_cascades

        # Parse into setup SQL and panels
        parsed = parse_multi_panel_query(sql)
        if not parsed:
            # No panels found - shouldn't happen if we got here
            return ["No panels found in SQL"]

        # Create a fresh in-memory connection for validation
        conn = duckdb.connect(':memory:')

        # Create a dummy session context for deref preprocessing
        # Params will resolve to NULL (no params set), which is fine for validation
        validation_session_id = f"validation_{uuid.uuid4().hex[:8]}"
        session_context = {
            'session_id': validation_session_id,
            'protocol': 'validation',
            'database_name': 'memory',
            'user_name': '',
            'application_name': 'valid_hyper',
            'client_address': '',
            'caller_id': None,
        }

        # Register UDFs needed for semantic SQL (optional - may not be available)
        try:
            from lars.sql_tools.udf import register_lars_udf
            register_lars_udf(conn)
        except Exception as e:
            log.debug(f"UDF registration skipped: {e}")

        # Execute setup SQL first (CREATE TABLE, etc.)
        if parsed.get('setup'):
            setup_sql = parsed['setup']
            try:
                # Step 1: Deref preprocessing (@param_get, @param_set, etc.)
                setup_sql = preprocess_deref_cascades(setup_sql, session_context)
                # Step 2: Lazy attach for external databases
                ensure_lazy_attach(conn, setup_sql)
                # Step 3: Rewrite LARS syntax
                rewritten_setup = rewrite_lars_syntax(setup_sql, duckdb_conn=conn)
                conn.execute(rewritten_setup)
                log.debug(f"Setup SQL executed successfully")
            except Exception as e:
                error_msg = str(e)
                # Truncate long errors
                if len(error_msg) > 300:
                    error_msg = error_msg[:300] + "..."
                errors.append(f"Setup SQL error: {error_msg}")
                return errors  # Can't continue without setup

        # Execute each panel query
        for i, panel in enumerate(parsed.get('panels', [])):
            panel_name = panel.get('name', f'Panel {i+1}')
            panel_query = panel.get('query', '')

            if not panel_query.strip():
                continue

            try:
                # Step 1: Deref preprocessing (@param_get, @param_set, etc.)
                panel_query = preprocess_deref_cascades(panel_query, session_context)
                # Step 2: Lazy attach for external databases
                ensure_lazy_attach(conn, panel_query)
                # Step 3: Rewrite LARS syntax
                rewritten_query = rewrite_lars_syntax(panel_query, duckdb_conn=conn)

                # Execute (we don't need results, just checking for errors)
                conn.execute(rewritten_query).fetchall()
                log.debug(f"Panel '{panel_name}' executed successfully")

            except Exception as e:
                error_msg = str(e)
                # Truncate long errors
                if len(error_msg) > 300:
                    error_msg = error_msg[:300] + "..."
                errors.append(f"Panel '{panel_name}': {error_msg}")

        # Clean up
        try:
            conn.close()
        except:
            pass

    except ImportError as e:
        # If we can't import the needed modules, skip execution check
        log.warning(f"Skipping SQL execution check (missing imports): {e}")
        return []
    except Exception as e:
        # Catch-all for unexpected errors
        log.error(f"SQL execution check failed: {e}")
        errors.append(f"Execution check failed: {str(e)[:200]}")

    return errors
