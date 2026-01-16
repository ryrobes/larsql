-- Migration: Add AI-generated summary column to checkpoints
-- This allows us to display concise summaries instead of full cell_output

ALTER TABLE checkpoints
ADD COLUMN IF NOT EXISTS summary Nullable(String);
