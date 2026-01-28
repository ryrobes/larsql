"""
Calliope verification tools.

Provides tools for capturing screenshots of running Calliope kits
and validating that they match user requirements.
"""

from typing import Optional
from .base import simple_eddy


# Subprocess script for screenshot capture - runs in isolated process to avoid pybind11 issues
_CAPTURE_SCRIPT = '''
import sys
import json
import base64
import time

def compress_screenshot(png_bytes, max_width=1280, quality=65):
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(png_bytes))
        if img.width > max_width:
            ratio = max_width / img.width
            new_height = int(img.height * ratio)
            img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
        img_rgb = img.convert('RGB') if img.mode in ('RGBA', 'P') else img
        jpeg_buffer = io.BytesIO()
        img_rgb.save(jpeg_buffer, format='JPEG', quality=quality, optimize=True)
        jpeg_bytes = jpeg_buffer.getvalue()
        png_buffer = io.BytesIO()
        img.save(png_buffer, format='PNG', optimize=True)
        resized_png_bytes = png_buffer.getvalue()
        if len(jpeg_bytes) < len(resized_png_bytes):
            return jpeg_bytes, 'image/jpeg'
        return resized_png_bytes, 'image/png'
    except:
        return png_bytes, 'image/png'

def main():
    args = json.loads(sys.argv[1])
    port = args['port']
    timeout_seconds = args.get('timeout_seconds', 30)
    wait_for_render = args.get('wait_for_render', 3.0)

    url = f"http://localhost:{port}"
    console_messages = []
    console_errors = []

    from playwright.sync_api import sync_playwright

    playwright = None
    browser = None

    try:
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()

        def handle_console(msg):
            text = msg.text[:500] if len(msg.text) > 500 else msg.text
            if msg.type in ('error', 'warning'):
                console_errors.append(f"[{msg.type.upper()}] {text}")
            console_messages.append(f"[{msg.type}] {text}")

        def handle_page_error(error):
            console_errors.append(f"[PAGE ERROR] {str(error)[:500]}")

        page.on('console', handle_console)
        page.on('pageerror', handle_page_error)

        page.goto(url, timeout=timeout_seconds * 1000)

        try:
            page.wait_for_selector('#root > *, body > *', timeout=10000)
        except:
            pass

        time.sleep(wait_for_render)

        dom_errors = page.evaluate("""() => {
            const errors = [];
            document.querySelectorAll('[class*="error"], [class*="Error"], .error-message').forEach(el => {
                const text = el.textContent?.trim();
                if (text && text.length < 500 && text.toLowerCase().includes('error')) {
                    errors.push(text);
                }
            });
            document.querySelectorAll('.api-error, .fetch-error, .load-error').forEach(el => {
                const text = el.textContent?.trim();
                if (text && text.length < 500) errors.push(text);
            });
            return errors;
        }""")

        all_errors = dom_errors + console_errors
        screenshot_bytes = page.screenshot(type='png', full_page=False)
        compressed_bytes, mime_type = compress_screenshot(screenshot_bytes)
        screenshot_b64 = f"data:{mime_type};base64,{base64.b64encode(compressed_bytes).decode('utf-8')}"
        page_title = page.title()

        result = {
            "success": len(all_errors) == 0,
            "screenshot": screenshot_b64,
            "errors": all_errors,
            "console_log": console_messages[-50:],
            "page_title": page_title,
        }
    except Exception as e:
        result = {
            "success": False,
            "screenshot": "",
            "errors": [f"Browser automation error: {str(e)}"],
            "console_log": console_messages[-50:] if console_messages else [],
            "page_title": "",
        }
    finally:
        if browser:
            try: browser.close()
            except: pass
        if playwright:
            try: playwright.stop()
            except: pass

    print(json.dumps(result))

if __name__ == '__main__':
    main()
'''


@simple_eddy
def capture_kit_screenshot(
    port: int,
    timeout_seconds: int = 30,
    wait_for_render: float = 3.0,
) -> dict:
    """
    Capture a screenshot of a running Calliope kit dashboard.

    Navigates to the kit's URL, waits for it to render, and captures a screenshot.
    Returns the screenshot and any errors found in the DOM.

    Args:
        port: The port the kit is running on (e.g., 15602)
        timeout_seconds: Maximum time to wait for page load
        wait_for_render: Seconds to wait for charts/components to render

    Returns:
        dict with:
          - success: bool - Whether dashboard loaded without visible errors
          - screenshot: str - Base64-encoded image of the rendered dashboard
          - errors: list[str] - Any error messages found in the DOM
          - page_title: str - The page title after render
    """
    import subprocess
    import json
    import sys

    args = json.dumps({
        'port': port,
        'timeout_seconds': timeout_seconds,
        'wait_for_render': wait_for_render,
    })

    try:
        # Run Playwright in a completely isolated subprocess to avoid pybind11 conflicts
        result = subprocess.run(
            [sys.executable, '-c', _CAPTURE_SCRIPT, args],
            capture_output=True,
            text=True,
            timeout=timeout_seconds + 30,  # Extra time for browser startup
        )

        if result.returncode != 0:
            return {
                "success": False,
                "screenshot": "",
                "errors": [f"Subprocess error: {result.stderr[:1000]}"],
                "console_log": [],
                "page_title": "",
            }

        return json.loads(result.stdout)

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "screenshot": "",
            "errors": ["Screenshot capture timed out"],
            "console_log": [],
            "page_title": "",
        }
    except Exception as e:
        return {
            "success": False,
            "screenshot": "",
            "errors": [f"Screenshot capture failed: {str(e)}"],
            "console_log": [],
            "page_title": "",
        }


@simple_eddy
def validate_kit_visual(
    port: int,
    user_request: str,
    annotated_screenshot: Optional[str] = None,
) -> dict:
    """
    Validate that a kit's visual output matches the user's request.

    This is a placeholder that captures a screenshot and returns it along
    with the request for an LLM to judge. The actual judgment happens in
    the validator cascade.

    Args:
        port: The port the kit is running on
        user_request: What the user asked for
        annotated_screenshot: Optional base64 screenshot with user's annotations

    Returns:
        dict with:
          - screenshot: str - Base64 screenshot of current kit state
          - user_request: str - What the user asked for
          - annotated_screenshot: str - User's annotated screenshot (if provided)
          - errors: list[str] - Any DOM errors found
    """
    # Capture the current state
    result = capture_kit_screenshot(port=port)

    return {
        "screenshot": result.get("screenshot", ""),
        "user_request": user_request,
        "annotated_screenshot": annotated_screenshot or "",
        "errors": result.get("errors", []),
        "capture_success": result.get("success", False),
    }
