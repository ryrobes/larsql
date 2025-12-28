"""
Web search tools for LLM agents.

Provides integration with Brave Search API for web search capabilities.
"""

import json
import os
from typing import Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


def brave_web_search(
    query: str,
    count: int = 5,
    freshness: Optional[str] = None
) -> str:
    """
    Search the web using Brave Search API.

    Use this tool to find additional information when you need more context
    to make a confident decision. Useful for:
    - Identifying unknown brands or companies
    - Finding product information
    - Verifying claims or facts
    - Getting current information

    Args:
        query: The search query (e.g., "Sony electronics brand", "USB-C cable brands")
        count: Number of results to return (1-20, default: 5)
        freshness: Optional freshness filter - "pd" (past day), "pw" (past week),
                   "pm" (past month), "py" (past year), or None for any time

    Returns:
        JSON string with search results including:
        - title: Page title
        - url: Page URL
        - description: Snippet/description

    Example:
        >>> brave_web_search("Sony headphones brand official")
        Returns results about Sony as a headphones brand

        >>> brave_web_search("UGREEN USB-C cables", count=3)
        Returns top 3 results about UGREEN cables
    """
    api_key = os.environ.get("BRAVE_SEARCH_API_KEY")
    if not api_key:
        return json.dumps({
            "error": "BRAVE_SEARCH_API_KEY not set in environment",
            "hint": "Set BRAVE_SEARCH_API_KEY to use web search"
        })

    # Validate count
    count = max(1, min(20, count))

    # Build query parameters
    params = {
        "q": query,
        "count": count,
        "text_decorations": False,  # No bold markers
        "search_lang": "en",
    }

    if freshness:
        params["freshness"] = freshness

    url = f"https://api.search.brave.com/res/v1/web/search?{urlencode(params)}"

    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
        "X-Subscription-Token": api_key
    }

    try:
        request = Request(url, headers=headers)
        with urlopen(request, timeout=10) as response:
            raw_data = response.read()

            # Detect gzip by magic bytes (0x1f 0x8b) - more reliable than header
            if raw_data[:2] == b'\x1f\x8b':
                import gzip
                data = gzip.decompress(raw_data)
            else:
                # Try zlib/deflate if it looks compressed
                try:
                    import zlib
                    data = zlib.decompress(raw_data, zlib.MAX_WBITS | 16)
                except:
                    data = raw_data

            result = json.loads(data.decode("utf-8"))

            # Extract just the web results
            web_results = result.get("web", {}).get("results", [])

            # Simplify the output for LLM consumption
            simplified = []
            for r in web_results[:count]:
                simplified.append({
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "description": r.get("description", ""),
                })

            return json.dumps({
                "query": query,
                "results": simplified,
                "result_count": len(simplified)
            }, indent=2)

    except HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else ""
        return json.dumps({
            "error": f"Brave Search API error: {e.code}",
            "details": error_body[:500] if error_body else str(e)
        })
    except URLError as e:
        return json.dumps({
            "error": f"Network error: {str(e.reason)}"
        })
    except Exception as e:
        return json.dumps({
            "error": f"Search failed: {str(e)}"
        })


def is_available() -> bool:
    """Check if Brave Search is configured."""
    return bool(os.environ.get("BRAVE_SEARCH_API_KEY"))
