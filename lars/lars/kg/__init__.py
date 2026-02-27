"""
Knowledge Graph subsystem for LARS.

Builds and maintains an entity graph over discovered database schemas,
enabling semantic understanding of the user's data landscape.

Tier 1 (deterministic): Runs during/after `lars sql crawl`.
  - Extracts connection, schema, table, column entities from crawl YAML.
  - Creates containment edges (connection → schema → table → column).
  - Detects likely FK relationships via naming heuristics.
  - Records column cardinality and pattern observations.

Tier 2+ (LLM): Runs during dreaming (scheduled cascades).
  - Semantic enrichment of entity descriptions.
  - Cross-database pattern detection.
  - Business domain inference.
  - Observation synthesis.
"""

from .extractor import extract_kg_from_crawl
from .dreamer import dream_tier2
from .embedder import embed_kg_entities, embed_kg_observations

__all__ = ["extract_kg_from_crawl", "dream_tier2", "embed_kg_entities", "embed_kg_observations"]
