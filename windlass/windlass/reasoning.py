"""
Reasoning Token Configuration Parser

Parses model strings with reasoning configuration embedded using :: delimiter.
This avoids clashing with OpenRouter's single-: suffixes like :free, :thinking, etc.

Syntax:
    provider/model[:variant][::reasoning_spec[::flags]]

Where reasoning_spec is one of:
    - effort level: high, medium, low, xhigh, minimal, none
    - token budget: 16000 (pure number)
    - effort with budget: high(16000)
    - enable keywords: on, true, auto, enabled

Where flags are:
    - exclude: hide reasoning from response

Examples:
    xai/grok-4::high                           # effort=high
    xai/grok-4::16000                          # max_tokens=16000
    xai/grok-4::high(16000)                    # effort + budget hint
    xai/grok-4::on                             # enable with defaults
    xai/grok-4::high::exclude                  # effort + hide reasoning
    xai/grok-4:free::high(8000)                # OpenRouter :free + reasoning
    anthropic/claude-3.7-sonnet:thinking::16000::exclude

See: https://openrouter.ai/docs/guides/best-practices/reasoning-tokens
"""

import re
from dataclasses import dataclass, field
from typing import Optional, Tuple, Dict, Any


# Valid effort levels per OpenRouter docs
EFFORT_LEVELS = frozenset({"xhigh", "high", "medium", "low", "minimal", "none"})

# Keywords that just enable reasoning with provider defaults
ENABLE_KEYWORDS = frozenset({"on", "true", "auto", "enabled"})

# Boolean flags that can appear after ::
FLAGS = frozenset({"exclude"})


@dataclass
class ReasoningConfig:
    """
    Configuration for reasoning/thinking tokens.

    Attributes:
        enabled: Whether reasoning is enabled (always True if config exists)
        effort: Effort level (xhigh, high, medium, low, minimal, none)
        max_tokens: Explicit token budget for reasoning
        exclude: If True, hide reasoning content from response
    """
    enabled: bool = True
    effort: Optional[str] = None
    max_tokens: Optional[int] = None
    exclude: bool = False

    def to_api_dict(self) -> Dict[str, Any]:
        """
        Convert to dict suitable for OpenRouter API's reasoning parameter.

        Note: OpenRouter/Anthropic only allows ONE of effort or max_tokens.
        When both are specified (e.g., "high(6000)"), max_tokens takes precedence
        as it's more explicit. The effort level is treated as a "hint" for
        interpreting the token budget.

        Returns dict like:
            {"effort": "high"}
            {"max_tokens": 16000}
            {"max_tokens": 6000, "exclude": true}  # effort ignored when max_tokens present
        """
        result = {}

        # IMPORTANT: OpenRouter only allows ONE of effort or max_tokens
        # max_tokens takes precedence when both specified (more explicit)
        if self.max_tokens is not None:
            result["max_tokens"] = self.max_tokens
        elif self.effort and self.effort != "none":
            result["effort"] = self.effort
        elif self.effort == "none":
            # Explicitly disable
            result["effort"] = "none"

        if self.exclude:
            result["exclude"] = True

        # If nothing specified but enabled, just signal enabled
        if not result and self.enabled:
            result["enabled"] = True

        return result

    def __repr__(self) -> str:
        parts = []
        if self.effort:
            parts.append(f"effort={self.effort}")
        if self.max_tokens:
            parts.append(f"max_tokens={self.max_tokens}")
        if self.exclude:
            parts.append("exclude=True")
        return f"ReasoningConfig({', '.join(parts) or 'enabled'})"


def parse_model_with_reasoning(model_str: str) -> Tuple[str, Optional[ReasoningConfig]]:
    """
    Parse model string and extract reasoning configuration.

    Uses :: as delimiter to separate our config from the model name,
    avoiding clashes with OpenRouter's : suffixes (:free, :thinking, etc).

    Args:
        model_str: Full model string, e.g. "xai/grok-4:free::high(8000)::exclude"

    Returns:
        Tuple of (clean_model, reasoning_config)
        - clean_model: Model string to pass to API (e.g. "xai/grok-4:free")
        - reasoning_config: ReasoningConfig if :: found, None otherwise

    Examples:
        >>> parse_model_with_reasoning("xai/grok-4")
        ("xai/grok-4", None)

        >>> parse_model_with_reasoning("xai/grok-4::high")
        ("xai/grok-4", ReasoningConfig(effort="high"))

        >>> parse_model_with_reasoning("xai/grok-4:free::high(8000)")
        ("xai/grok-4:free", ReasoningConfig(effort="high", max_tokens=8000))

        >>> parse_model_with_reasoning("xai/grok-4::16000::exclude")
        ("xai/grok-4", ReasoningConfig(max_tokens=16000, exclude=True))
    """
    if not model_str:
        return model_str, None

    # Split on :: to separate model from our reasoning config
    parts = model_str.split("::")

    if len(parts) == 1:
        # No :: found, no reasoning config
        return model_str, None

    # Everything before first :: is the model (preserves :free, :thinking etc)
    model = parts[0]

    # Everything after is reasoning config
    reasoning_parts = parts[1:]

    config = ReasoningConfig()
    spec_parsed = False

    for part in reasoning_parts:
        part_lower = part.lower().strip()

        if not part_lower:
            continue

        # Check if it's a known flag
        if part_lower in FLAGS:
            if part_lower == "exclude":
                config.exclude = True
            continue

        # If we haven't parsed the main spec yet, this should be it
        if not spec_parsed:
            spec_parsed = True

            # Pattern: word(number) or word or number
            # Examples: high, high(8000), 16000
            match = re.match(r'^([a-zA-Z]+)(?:\((\d+)\))?$', part_lower)

            if match:
                word, tokens = match.groups()

                if word in EFFORT_LEVELS:
                    config.effort = word
                    if tokens:
                        config.max_tokens = int(tokens)
                elif word in ENABLE_KEYWORDS:
                    # Just enable with defaults, no specific effort
                    pass
                else:
                    # Unknown word - could be typo, log warning but continue
                    print(f"[WARN] Unknown reasoning effort level: {word}, ignoring")

            elif part_lower.isdigit():
                # Pure number = max_tokens only
                config.max_tokens = int(part_lower)
            else:
                print(f"[WARN] Could not parse reasoning spec: {part}, ignoring")

    return model, config


def format_model_with_reasoning(model: str, config: Optional[ReasoningConfig]) -> str:
    """
    Reconstruct a model string with reasoning config.
    Inverse of parse_model_with_reasoning.

    Useful for logging the "requested" model string.
    """
    if config is None:
        return model

    parts = [model]

    # Build reasoning spec
    if config.effort:
        if config.max_tokens:
            parts.append(f"{config.effort}({config.max_tokens})")
        else:
            parts.append(config.effort)
    elif config.max_tokens:
        parts.append(str(config.max_tokens))
    elif config.enabled:
        parts.append("on")

    # Add flags
    if config.exclude:
        parts.append("exclude")

    return "::".join(parts)
