"""
Blocking Cost Tracker - Synchronous cost fetching from OpenRouter

Replaces async cost tracking with immediate, blocking fetches.
Retries with exponential backoff if cost data not immediately available.
"""

import time
import requests
from typing import Optional, Dict, Any
from .config import get_config


def fetch_cost_blocking(request_id: str, max_wait_seconds: float = 10.0) -> Dict[str, Any]:
    """
    Fetch cost data from OpenRouter synchronously with retries.

    Args:
        request_id: OpenRouter request ID from LLM response
        max_wait_seconds: Maximum time to wait for cost data (default: 10s)

    Returns:
        dict with keys: cost, tokens_in, tokens_out, provider
        If cost data unavailable, returns None for cost/token fields

    Strategy:
        1. Try immediate fetch
        2. If not available, retry with exponential backoff
        3. Give up after max_wait_seconds
    """
    config = get_config()
    api_key = config.provider_api_key

    if not api_key:
        print("[WARN] No OpenRouter API key - cannot fetch cost")
        return {
            "cost": None,
            "tokens_in": 0,
            "tokens_out": 0,
            "tokens_reasoning": None,
            "provider": "unknown"
        }

    if not request_id:
        print("[WARN] No request ID - cannot fetch cost")
        return {
            "cost": None,
            "tokens_in": 0,
            "tokens_out": 0,
            "tokens_reasoning": None,
            "provider": "unknown"
        }

    headers = {"Authorization": f"Bearer {api_key}"}
    url = f"https://openrouter.ai/api/v1/generation?id={request_id}"

    start_time = time.time()
    attempt = 0
    wait_times = [0, 1, 2, 3, 4]  # Retry after 0s, 1s, 2s, 3s, 4s (total ~10s)

    while True:
        elapsed = time.time() - start_time

        if elapsed > max_wait_seconds:
            print(f"[WARN] Cost fetch timeout after {elapsed:.1f}s for request {request_id}")
            return {
                "cost": None,
                "tokens_in": 0,
                "tokens_out": 0,
                "tokens_reasoning": None,
                "provider": "unknown"
            }

        try:
            resp = requests.get(url, headers=headers, timeout=5)

            if resp.ok:
                data = resp.json().get("data", {})

                cost = data.get("total_cost", 0) or data.get("cost", 0)
                tokens_in = data.get("native_tokens_prompt", 0) or data.get("tokens_prompt", 0)
                tokens_out = data.get("native_tokens_completion", 0) or data.get("tokens_completion", 0)
                provider = data.get("provider", "unknown")

                # Extract reasoning/thinking tokens if available
                # OpenRouter may return these as native_tokens_reasoning or tokens_reasoning
                tokens_reasoning = (
                    data.get("native_tokens_reasoning") or
                    data.get("tokens_reasoning") or
                    data.get("reasoning_tokens") or
                    None
                )

                # Check if we have actual data (cost > 0 or tokens > 0)
                if cost > 0 or tokens_in > 0 or tokens_out > 0:
                    reasoning_msg = f", {tokens_reasoning} reasoning" if tokens_reasoning else ""
                    print(f"[Cost] Fetched for {request_id}: ${cost} ({tokens_in}+{tokens_out} tokens{reasoning_msg})")
                    return {
                        "cost": cost,
                        "tokens_in": tokens_in,
                        "tokens_out": tokens_out,
                        "tokens_reasoning": tokens_reasoning,
                        "provider": provider
                    }
                else:
                    # Data not ready yet, retry
                    if attempt < len(wait_times):
                        wait_time = wait_times[attempt]
                        print(f"[Cost] Data not ready, retrying in {wait_time}s... (attempt {attempt+1})")
                        time.sleep(wait_time)
                        attempt += 1
                        continue
                    else:
                        print(f"[WARN] No cost data after {attempt} attempts")
                        return {
                            "cost": None,
                            "tokens_in": 0,
                            "tokens_out": 0,
                            "tokens_reasoning": None,
                            "provider": provider or "unknown"
                        }
            elif resp.status_code == 404:
                # 404 means OpenRouter hasn't processed the data yet - RETRY!
                # This is the most common case when fetching immediately after a request
                if attempt < len(wait_times):
                    wait_time = wait_times[attempt]
                    if attempt == 0:
                        # First retry after 404 - use a longer delay
                        wait_time = max(wait_time, 2)
                    print(f"[Cost] Data not available yet (404), retrying in {wait_time}s... (attempt {attempt+1})")
                    time.sleep(wait_time)
                    attempt += 1
                    continue
                else:
                    print(f"[WARN] Cost data still unavailable after {attempt} retries (404)")
                    return {
                        "cost": None,
                        "tokens_in": 0,
                        "tokens_out": 0,
                        "tokens_reasoning": None,
                        "provider": "unknown"
                    }
            else:
                # Other HTTP errors (500, 503, etc.) - don't retry immediately
                print(f"[WARN] Cost API error: HTTP {resp.status_code}")
                return {
                    "cost": None,
                    "tokens_in": 0,
                    "tokens_out": 0,
                    "tokens_reasoning": None,
                    "provider": "unknown"
                }

        except Exception as e:
            print(f"[ERROR] Cost fetch failed: {e}")
            return {
                "cost": None,
                "tokens_in": 0,
                "tokens_out": 0,
                "tokens_reasoning": None,
                "provider": "unknown"
            }


def extract_provider_from_model(model: str) -> str:
    """
    Extract provider name from model string.

    Examples:
        "anthropic/claude-3.5-sonnet" -> "anthropic"
        "openai/gpt-4" -> "openai"
        "x-ai/grok-4.1-fast:free" -> "x-ai"
        "grok-4.1-fast:free" -> "unknown"
    """
    if not model:
        return "unknown"

    if "/" in model:
        return model.split("/")[0]

    return "unknown"
