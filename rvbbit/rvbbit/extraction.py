"""
Output extraction for structured content capture.

Enables scratchpad patterns where reasoning is captured in tags
and extracted to state variables for cleaner phase handoffs.
"""

import re
import json
from typing import Any, Optional
import logging

logger = logging.getLogger(__name__)


class ExtractionError(Exception):
    """Raised when required extraction fails."""
    pass


class OutputExtractor:
    """Extract structured content from phase outputs."""

    def extract(self, content: str, config) -> Optional[Any]:
        """
        Extract content based on pattern.

        Args:
            content: Text to extract from
            config: OutputExtractionConfig instance

        Returns:
            Extracted content (str, dict, or None)

        Raises:
            ExtractionError: If required extraction fails
        """
        # Find match
        match = re.search(config.pattern, content, re.DOTALL | re.IGNORECASE)

        if not match:
            if config.required:
                raise ExtractionError(f"Required pattern not found: {config.pattern}")
            return None

        # Extract matched group (first capture group or full match)
        extracted = match.group(1) if match.groups() else match.group(0)
        extracted = extracted.strip()

        # Format based on type
        if config.format == "json":
            try:
                return json.loads(extracted)
            except json.JSONDecodeError as e:
                if config.required:
                    raise ExtractionError(f"Invalid JSON: {e}")
                logger.warning(f"Failed to parse JSON, returning as text: {e}")
                return extracted

        elif config.format == "code":
            # Extract code blocks (remove markdown)
            code_match = re.search(r'```(?:\w+)?\n(.*?)```', extracted, re.DOTALL)
            return code_match.group(1) if code_match else extracted

        else:  # text
            return extracted

    def has_pattern(self, content: str, pattern: str) -> bool:
        """
        Check if pattern exists in content.

        Args:
            content: Text to search
            pattern: Regex pattern

        Returns:
            True if pattern found
        """
        return bool(re.search(pattern, content, re.DOTALL | re.IGNORECASE))
