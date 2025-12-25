"""
Token budget enforcement for RVBBIT cascades.

Prevents context explosion by tracking token usage and enforcing limits
with multiple strategies (sliding_window, prune_oldest, summarize, fail).
"""

from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

# Try to import tiktoken for accurate token counting
try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False
    logger.warning("tiktoken not available, using approximate token counting")


class TokenBudgetExceeded(Exception):
    """Raised when token budget is exceeded with 'fail' strategy."""
    def __init__(self, status: Dict[str, Any]):
        self.status = status
        super().__init__(f"Token budget exceeded: {status['current']}/{status['limit']} tokens")


class TokenBudgetManager:
    """
    Manages token budgets for cascade contexts.

    Tracks token usage and enforces limits using configurable strategies.
    """

    def __init__(self, config, model: str):
        """
        Initialize token budget manager.

        Args:
            config: TokenBudgetConfig instance
            model: Model name for encoding selection
        """
        self.config = config
        self.model = model

        # Initialize token encoder
        if TIKTOKEN_AVAILABLE:
            try:
                self.encoding = tiktoken.encoding_for_model(self._normalize_model(model))
            except KeyError:
                # Fallback to cl100k_base for unknown models
                logger.warning(f"Unknown model {model}, using cl100k_base encoding")
                self.encoding = tiktoken.get_encoding("cl100k_base")
        else:
            self.encoding = None

        self.current_usage = 0

    def _normalize_model(self, model: str) -> str:
        """Normalize model name for tiktoken."""
        # OpenRouter format: provider/model -> model
        if '/' in model:
            model = model.split('/')[-1]

        # Map common models to tiktoken names
        model_map = {
            'gpt-4': 'gpt-4',
            'gpt-4-turbo': 'gpt-4',
            'gpt-3.5-turbo': 'gpt-3.5-turbo',
            'claude': 'gpt-4',  # Use GPT-4 encoding as approximation
            'gemini': 'gpt-4',
        }

        for key, value in model_map.items():
            if key in model.lower():
                return value

        # Default to gpt-4 for unknown models
        return 'gpt-4'

    def count_tokens(self, messages: List[Dict]) -> int:
        """
        Count tokens in message list.

        Args:
            messages: List of message dicts with role/content/tool_calls

        Returns:
            Total token count
        """
        if not messages:
            return 0

        total = 0

        for msg in messages:
            # Count message overhead (~4 tokens per message)
            total += 4

            # Count content
            content = msg.get("content")
            if content:
                if isinstance(content, str):
                    total += self._count_text(content)
                elif isinstance(content, list):
                    # Multi-modal content (text + images)
                    for item in content:
                        if isinstance(item, dict):
                            if item.get("type") == "text":
                                total += self._count_text(item.get("text", ""))
                            elif item.get("type") == "image_url":
                                # Images are expensive - rough estimate
                                total += 765  # Average for medium images

            # Count tool calls
            if msg.get("tool_calls"):
                tool_str = str(msg["tool_calls"])
                total += self._count_text(tool_str)

        return total

    def _count_text(self, text: str) -> int:
        """Count tokens in text string."""
        if not text:
            return 0

        if self.encoding:
            return len(self.encoding.encode(text))
        else:
            # Fallback: rough approximation (1 token ≈ 4 chars)
            return len(text) // 4

    def check_budget(self, messages: List[Dict]) -> Dict[str, Any]:
        """
        Check if within budget, return status.

        Args:
            messages: Current message list

        Returns:
            Dict with current usage, limit, percentage, warnings
        """
        current = self.count_tokens(messages)
        available = self.config.max_total - self.config.reserve_for_output

        status = {
            "current": current,
            "limit": available,
            "percentage": current / available if available > 0 else 1.0,
            "over_budget": current > available,
            "warning": current > (available * self.config.warning_threshold)
        }

        self.current_usage = current
        return status

    def enforce_budget(self, messages: List[Dict]) -> List[Dict]:
        """
        Prune messages to fit within budget.

        Args:
            messages: Current message list

        Returns:
            Pruned message list

        Raises:
            TokenBudgetExceeded: If strategy is 'fail' and over budget
        """
        status = self.check_budget(messages)

        if not status["over_budget"]:
            return messages

        # Execute strategy
        if self.config.strategy == "sliding_window":
            return self._sliding_window(messages)
        elif self.config.strategy == "prune_oldest":
            return self._prune_oldest(messages)
        elif self.config.strategy == "summarize":
            return self._summarize(messages)
        elif self.config.strategy == "fail":
            raise TokenBudgetExceeded(status)
        else:
            logger.warning(f"Unknown strategy {self.config.strategy}, using sliding_window")
            return self._sliding_window(messages)

    def _sliding_window(self, messages: List[Dict]) -> List[Dict]:
        """
        Keep most recent messages that fit.

        Always preserves:
        - System message (first)
        - Most recent messages that fit in budget
        """
        if not messages:
            return []

        # Always preserve system message if present
        preserved = []
        start_idx = 0
        if messages[0].get("role") == "system":
            preserved.append(messages[0])
            start_idx = 1

        # Calculate available tokens
        available = self.config.max_total - self.config.reserve_for_output
        current = self.count_tokens(preserved)

        # Work backwards from most recent
        recent_msgs = []
        for msg in reversed(messages[start_idx:]):
            msg_tokens = self.count_tokens([msg])
            if current + msg_tokens <= available:
                recent_msgs.insert(0, msg)
                current += msg_tokens
            else:
                # Can't fit any more
                break

        preserved.extend(recent_msgs)

        pruned_count = len(messages) - len(preserved)
        if pruned_count > 0:
            logger.info(f"Token budget: pruned {pruned_count} messages (kept {len(preserved)}, {current}/{available} tokens)")

        return preserved

    def _prune_oldest(self, messages: List[Dict]) -> List[Dict]:
        """
        Remove oldest messages until within budget.

        Preserves:
        - System message
        - Error messages
        - Last 3 turns
        """
        if not messages:
            return []

        critical_indices = self._find_critical_messages(messages)
        available = self.config.max_total - self.config.reserve_for_output

        # Start with all indices
        kept_indices = list(range(len(messages)))
        current = self.count_tokens(messages)

        # Remove oldest non-critical messages
        for i in range(len(messages)):
            if current <= available:
                break

            if i in critical_indices:
                continue

            # Remove this message
            if i in kept_indices:
                kept_indices.remove(i)
                # Recalculate tokens
                kept_messages = [messages[j] for j in kept_indices]
                current = self.count_tokens(kept_messages)

        result = [messages[i] for i in sorted(kept_indices)]
        pruned_count = len(messages) - len(result)

        if pruned_count > 0:
            logger.info(f"Token budget: pruned {pruned_count} oldest messages (kept {len(result)}, {current}/{available} tokens)")

        return result

    def _find_critical_messages(self, messages: List[Dict]) -> set:
        """Find indices of critical messages to preserve."""
        critical = set()

        # System message
        if messages and messages[0].get("role") == "system":
            critical.add(0)

        # Last 3 turns (user + assistant pairs)
        turn_count = 0
        for i in reversed(range(len(messages))):
            if messages[i].get("role") in ["user", "assistant"]:
                critical.add(i)
                if messages[i].get("role") == "assistant":
                    turn_count += 1
                if turn_count >= 3:
                    break

        # Messages with errors
        for i, msg in enumerate(messages):
            content = str(msg.get("content", "")).lower()
            if "error" in content or "exception" in content:
                critical.add(i)

        # Messages with routing decisions
        for i, msg in enumerate(messages):
            if msg.get("tool_calls"):
                for tc in msg.get("tool_calls", []):
                    if isinstance(tc, dict):
                        func_name = tc.get("function", {}).get("name") if isinstance(tc.get("function"), dict) else None
                        if func_name == "route_to":
                            critical.add(i)

        return critical

    def _summarize(self, messages: List[Dict]) -> List[Dict]:
        """
        Summarize old context using cheap model.

        Splits messages into old (to summarize) and recent (to keep),
        generates summary, and returns combined context.
        """
        if not messages:
            return []

        # Keep last 10 messages, summarize the rest
        split_index = max(1, len(messages) - 10)  # Keep at least system message

        old_messages = messages[:split_index]
        recent_messages = messages[split_index:]

        # Don't summarize if old section is too small
        if len(old_messages) < 5:
            return self._sliding_window(messages)

        # Generate summary using configured model
        summary_prompt = self._build_summary_prompt(old_messages)

        try:
            from .agent import Agent

            summarizer_config = self.config.summarizer or {}
            summarizer_model = summarizer_config.get("model", "google/gemini-2.5-flash-lite")

            summarizer = Agent(model=summarizer_model, system_prompt="You are a concise summarizer.")
            response = summarizer.run(input_message=summary_prompt)

            summary_content = response.get("content", "")

            # Create summary message
            summary_msg = {
                "role": "system",
                "content": f"CONTEXT SUMMARY (compressed from {len(old_messages)} messages):\n{summary_content}"
            }

            # Return: system + summary + recent
            result = [messages[0]] if messages[0].get("role") == "system" else []
            result.append(summary_msg)
            result.extend(recent_messages)

            tokens_saved = self.count_tokens(old_messages) - self.count_tokens([summary_msg])
            logger.info(f"Token budget: summarized {len(old_messages)} messages (saved ~{tokens_saved} tokens)")

            return result

        except Exception as e:
            logger.error(f"Token budget: summarization failed: {e}, falling back to sliding_window")
            return self._sliding_window(messages)

    def _build_summary_prompt(self, messages: List[Dict]) -> str:
        """Build prompt for summarization model."""
        target_size = self.config.summarizer.get("target_size", 2000) if self.config.summarizer else 2000

        formatted = self._format_messages_for_summary(messages)

        return f"""Summarize this conversation history in approximately {target_size} tokens.

Focus on:
1. Key decisions made
2. Important findings from tools
3. Errors encountered
4. Current state/progress

Be extremely concise. Omit pleasantries and explanations.

Conversation:
{formatted}

Summary:"""

    def _format_messages_for_summary(self, messages: List[Dict]) -> str:
        """Format messages for summarization."""
        lines = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")

            # Truncate long content
            if isinstance(content, str):
                content = content[:500] + "..." if len(content) > 500 else content
            elif isinstance(content, dict):
                content = str(content)[:500]

            lines.append(f"[{role}]: {content}")

        return "\n".join(lines)
