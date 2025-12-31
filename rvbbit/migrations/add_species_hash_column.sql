-- Migration: Add species_hash column to unified_logs table
-- Date: 2025-12-10
-- Description: Adds species_hash column for prompt evolution tracking (Cell 1 of Sextant evolution)
--
-- species_hash captures the "DNA" of a prompt template - the instructions, soundings config,
-- and rules that define how prompts are generated. This enables comparing prompts across
-- runs that use the same template, filtering out apples-to-oranges comparisons.

-- Add species_hash column (nullable string for the 16-char hex hash)
ALTER TABLE unified_logs
ADD COLUMN IF NOT EXISTS species_hash Nullable(String);

-- Add bloom filter index for fast species_hash filtering in Sextant queries
ALTER TABLE unified_logs
ADD INDEX IF NOT EXISTS idx_species_hash species_hash TYPE bloom_filter GRANULARITY 1;

-- Verify the changes
SELECT
    name,
    type
FROM system.columns
WHERE table = 'unified_logs'
  AND name = 'species_hash';
