from .base import simple_eddy
from ..logs import log_message
from ..config import get_config
import subprocess
import os

@simple_eddy
def linux_shell(command: str, timeout: int = 30) -> str:
    """
    Execute a shell command in a sandboxed Ubuntu Docker container.

    You have access to a full Ubuntu system with standard tools:
    - Python (python3), pip, curl, wget
    - File operations (cat, echo, ls, grep, etc.)
    - Package management (apt - but requires sudo)
    - Network tools (curl, wget, nc)

    Examples:
    - Run Python: python3 -c "print('hello')"
    - Install package: pip install requests (in container, ephemeral)
    - Curl API: curl https://api.example.com
    - File ops: echo 'data' > file.txt && cat file.txt

    Returns stdout/stderr from command execution.
    """
    try:
        import docker
    except ImportError:
        return "Error: docker package not installed. Run: pip install docker"

    container_name = "ubuntu-container"
    code_preview = command[:200] + "..." if len(command) > 200 else command
    log_message(None, "system", f"linux_shell executing: {code_preview}",
                metadata={"tool": "linux_shell", "command_length": len(command)})

    try:
        # Connect to Docker
        client = docker.from_env()

        # Get the container
        try:
            container = client.containers.get(container_name)
        except docker.errors.NotFound:
            return f"Error: Container '{container_name}' not found. Please start it first:\n" + \
                   f"docker run -d --name {container_name} ubuntu:latest sleep infinity"

        # Check if container is running
        if container.status != 'running':
            return f"Error: Container '{container_name}' is not running (status: {container.status})"

        # Execute command in container
        # Use array form to avoid shell escaping issues
        exec_result = container.exec_run(
            ["bash", "-c", command],  # Array form - no quote escaping needed!
            stdout=True,
            stderr=True,
            demux=False  # Combine stdout/stderr
        )

        exit_code = exec_result.exit_code
        output = exec_result.output.decode('utf-8') if exec_result.output else ""

        log_message(None, "system", f"linux_shell completed: exit_code={exit_code}, {len(output)} chars output",
                   metadata={"tool": "linux_shell", "exit_code": exit_code, "output_length": len(output)})

        # Return output with exit code info
        if exit_code != 0:
            return f"Exit code: {exit_code}\n\n{output}"

        return output if output else "(Command executed successfully with no output)"

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        error_msg = f"Error: {type(e).__name__}: {e}\n\nTraceback:\n{tb}"

        log_message(None, "system", f"linux_shell error: {type(e).__name__}: {e}",
                   metadata={"tool": "linux_shell", "error_type": type(e).__name__})

        return error_msg

@simple_eddy
def linux_shell_dangerous(command: str, timeout: int = 300) -> str:
    """
    Execute a shell command directly on the host system (NO DOCKER SANDBOX).

    WARNING: This runs commands directly on your machine from RVBBIT_ROOT.
    Use this for local tools that need access to the host environment
    (like rabbitize, which needs node_modules and localhost ports).

    Examples:
    - npx rabbitize --batch-url "..." --batch-commands='[...]'
    - npm install
    - Local scripts that need filesystem access

    Returns stdout/stderr from command execution.
    """
    code_preview = command[:200] + "..." if len(command) > 200 else command
    log_message(None, "system", f"linux_shell_dangerous executing: {code_preview}",
                metadata={"tool": "linux_shell_dangerous", "command_length": len(command)})

    try:
        # Run from RVBBIT_ROOT
        cwd = get_config().root_dir

        # Execute command directly on host
        result = subprocess.run(
            ["bash", "-c", command],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False  # Use array form for safety
        )

        exit_code = result.returncode
        output = result.stdout + result.stderr

        log_message(None, "system", f"linux_shell_dangerous completed: exit_code={exit_code}, {len(output)} chars output",
                   metadata={"tool": "linux_shell_dangerous", "exit_code": exit_code, "output_length": len(output)})

        # Return output with exit code info
        if exit_code != 0:
            return f"Exit code: {exit_code}\n\n{output}"

        return output if output else "(Command executed successfully with no output)"

    except subprocess.TimeoutExpired:
        error_msg = f"Error: Command timed out after {timeout} seconds"
        log_message(None, "system", f"linux_shell_dangerous timeout: {timeout}s",
                   metadata={"tool": "linux_shell_dangerous", "error_type": "TimeoutExpired"})
        return error_msg

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        error_msg = f"Error: {type(e).__name__}: {e}\n\nTraceback:\n{tb}"

        log_message(None, "system", f"linux_shell_dangerous error: {type(e).__name__}: {e}",
                   metadata={"tool": "linux_shell_dangerous", "error_type": type(e).__name__})

        return error_msg

@simple_eddy
def run_code(code: str, language: str = "python") -> str:
    """
    Executes Python code in a sandboxed Docker container.

    The code is executed in an isolated Ubuntu container with Python installed.
    All standard library modules are available.

    For multi-line code, just provide the complete script.
    For imports, include them at the top of your code.

    Returns stdout/stderr from execution.
    """
    # Delegate to linux_shell with python3 -c
    # Escape single quotes in code for shell safety
    escaped_code = code.replace("'", "'\"'\"'")

    # Use heredoc for clean multi-line code execution
    command = f"python3 << 'RVBBIT_EOF'\n{code}\nRVBBIT_EOF"

    log_message(None, "system", f"run_code delegating to linux_shell: {len(code)} chars",
                metadata={"tool": "run_code", "code_length": len(code), "language": language})

    result = linux_shell(command)

    # Add context about what ran
    if result and not result.startswith("Error:"):
        return result
    else:
        return result

@simple_eddy
def take_screenshot(url: str) -> str:
    """
    Takes a screenshot of a URL using Playwright.
    Returns path to screenshot.
    """
    # Requires playwright install
    # from playwright.sync_api import sync_playwright
    # with sync_playwright() as p:
    #    browser = p.chromium.launch()
    #    page = browser.new_page()
    #    page.goto(url)
    #    path = f"screenshot_{url.replace('/', '_')}.png"
    #    page.screenshot(path=path)
    #    browser.close()
    # return path
    return "Screenshot placeholder: Playwright not installed."


@simple_eddy
def curl_text(url: str, max_length: int = 10000) -> str:
    """
    Fetch a URL and extract readable text content.

    Handles:
    - HTTP/HTTPS requests with redirects
    - HTML to text conversion (no BeautifulSoup required!)
    - Error handling (404, timeouts, etc.)
    - Content truncation to reasonable length

    Args:
        url: URL to fetch (http://, https://, or t.co shortlinks)
        max_length: Maximum characters to return (default 10000)

    Returns:
        Readable text extracted from the page, or error message if fetch fails

    Examples:
        curl_text("https://example.com/article")
        curl_text("https://t.co/abc123")
    """
    import requests
    import re

    # Clean URL
    url = url.strip()
    if not url:
        return "ERROR: No URL provided"

    # Ensure http/https prefix
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    try:
        # Fetch URL with redirects, timeout, and user agent
        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; RVBBIT/1.0; +https://github.com/rvbbit)'
        }

        response = requests.get(
            url,
            headers=headers,
            timeout=10,
            allow_redirects=True,
            verify=True
        )

        # Check status
        if response.status_code != 200:
            return f"ERROR: HTTP {response.status_code} - {response.reason}"

        # Get content type
        content_type = response.headers.get('Content-Type', '').lower()

        # Handle different content types
        if 'application/json' in content_type:
            # JSON content - pretty print
            try:
                import json
                data = response.json()
                text = json.dumps(data, indent=2)
            except:
                text = response.text

        elif 'text/plain' in content_type:
            # Plain text - use as-is
            text = response.text

        elif 'text/html' in content_type or 'application/xhtml' in content_type:
            # HTML - extract readable text using simple regex (no dependencies!)
            html = response.text

            # Remove script, style, and nav elements
            html = re.sub(r'<script[^>]*?>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
            html = re.sub(r'<style[^>]*?>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
            html = re.sub(r'<nav[^>]*?>.*?</nav>', '', html, flags=re.DOTALL | re.IGNORECASE)
            html = re.sub(r'<footer[^>]*?>.*?</footer>', '', html, flags=re.DOTALL | re.IGNORECASE)
            html = re.sub(r'<header[^>]*?>.*?</header>', '', html, flags=re.DOTALL | re.IGNORECASE)

            # Remove all HTML tags
            text = re.sub(r'<[^>]+>', '', html)

            # Decode HTML entities
            import html as html_module
            text = html_module.unescape(text)

            # Clean up whitespace
            text = re.sub(r'\s+', ' ', text)
            text = text.strip()

        else:
            # Unknown content type
            return f"ERROR: Unsupported content type: {content_type}"

        # Truncate to max length
        if len(text) > max_length:
            text = text[:max_length] + f"\n\n[Truncated - original was {len(text)} chars]"

        # Return empty string if no useful text extracted
        if not text or len(text.strip()) < 10:
            return "ERROR: No readable text extracted from URL"

        return text

    except requests.exceptions.Timeout:
        return "ERROR: Request timed out after 10 seconds"
    except requests.exceptions.TooManyRedirects:
        return "ERROR: Too many redirects"
    except requests.exceptions.SSLError as e:
        return f"ERROR: SSL verification failed: {e}"
    except requests.exceptions.ConnectionError as e:
        return f"ERROR: Connection failed: {e}"
    except requests.exceptions.RequestException as e:
        return f"ERROR: Request failed: {e}"
    except Exception as e:
        return f"ERROR: Unexpected error: {type(e).__name__}: {e}"


@simple_eddy
def fetch_url_with_browser(url: str, max_length: int = 10000, wait_seconds: float = 3.0) -> str:
    """
    Fetch a URL using Playwright headless browser (handles JavaScript).
    
    CRITICAL: Creates a new browser instance for EACH call and properly closes it
    to prevent orphaned chrome processes. Synchronous wrapper around async Playwright.
    
    Handles:
    - JavaScript-heavy sites (SPAs, dynamic content)
    - Redirects and authentication
    - Wait for page load and dynamic content
    - Text extraction from rendered DOM
    - Proper cleanup (GUARANTEED browser shutdown)
    
    Args:
        url: URL to fetch
        max_length: Maximum characters to return (default 10000)
        wait_seconds: How long to wait for JS rendering (default 3.0)
    
    Returns:
        Readable text from rendered page, or error message
        
    Examples:
        fetch_url_with_browser("https://example.com")
        fetch_url_with_browser("https://twitter.com/user/status/123")
    """
    import asyncio
    
    # Clean URL
    url = url.strip()
    if not url:
        return "ERROR: No URL provided"
    
    # Ensure http/https prefix
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    
    async def _fetch_async():
        """Async implementation with guaranteed cleanup."""
        playwright = None
        browser = None
        page = None
        
        try:
            from playwright.async_api import async_playwright
            
            # Start Playwright
            playwright = await async_playwright().start()
            
            # Launch browser (new instance for this fetch)
            browser = await playwright.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-gpu',
                    '--disable-software-rasterizer',
                    '--single-process'  # Minimize process spawning
                ]
            )
            
            # Create context (ephemeral, will be destroyed)
            context = await browser.new_context(
                viewport={'width': 1280, 'height': 720},
                user_agent='Mozilla/5.0 (compatible; RVBBIT/1.0; +https://github.com/rvbbit)'
            )
            
            # Create page
            page = await context.new_page()
            
            # Navigate with timeout (45 seconds for slow/JS-heavy sites)
            await page.goto(url, wait_until='networkidle', timeout=45000)
            
            # Wait for dynamic content
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)
            
            # Extract text from body
            text = await page.evaluate('''() => {
                // Remove script, style, nav, footer, header
                const elementsToRemove = document.querySelectorAll('script, style, nav, footer, header, aside, .ad, .advertisement');
                elementsToRemove.forEach(el => el.remove());
                
                // Get text from body
                const body = document.body;
                if (!body) return '';
                
                // Use innerText which respects display:none and gives cleaner output
                return body.innerText || body.textContent || '';
            }''')
            
            # Clean up whitespace
            import re
            text = re.sub(r'\s+', ' ', text)
            text = text.strip()
            
            # Truncate
            if len(text) > max_length:
                text = text[:max_length] + f"\n\n[Truncated - original was {len(text)} chars]"
            
            if not text or len(text) < 10:
                return "ERROR: No readable text extracted from page"
            
            return text
            
        except ImportError:
            return "ERROR: Playwright not installed. Run: pip install playwright && playwright install chromium"
        except asyncio.TimeoutError:
            return "ERROR: Page load timeout after 45 seconds"
        except Exception as e:
            return f"ERROR: {type(e).__name__}: {str(e)[:200]}"
            
        finally:
            # CRITICAL: Cleanup in reverse order (guaranteed execution)
            # Close page first
            if page:
                try:
                    await page.close()
                except Exception as e:
                    print(f"[fetch_url] Warning: Failed to close page: {e}")

            # Close context to kill all pages
            if browser:
                try:
                    # Get all contexts and close them
                    contexts = browser.contexts
                    for ctx in contexts:
                        try:
                            await ctx.close()
                        except:
                            pass
                except:
                    pass

            # Close browser (kills chrome process)
            if browser:
                try:
                    await browser.close()
                    # Wait a moment for process to die
                    await asyncio.sleep(0.5)
                except Exception as e:
                    print(f"[fetch_url] Warning: Failed to close browser: {e}")

            # Stop playwright
            if playwright:
                try:
                    await playwright.stop()
                except Exception as e:
                    print(f"[fetch_url] Warning: Failed to stop playwright: {e}")
    
    # Run async function synchronously
    try:
        # Check if we're in an async context
        try:
            loop = asyncio.get_running_loop()
            # We're in an async context, run in thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, _fetch_async())
                return future.result(timeout=60)  # 60s to allow for 45s page load + cleanup
        except RuntimeError:
            # No running loop, we can use asyncio.run directly
            return asyncio.run(_fetch_async())
    except Exception as e:
        return f"ERROR: Async execution failed: {e}"
