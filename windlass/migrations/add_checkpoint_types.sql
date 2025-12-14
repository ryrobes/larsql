-- Migration: Add new checkpoint types to the enum
-- This adds support for decision points and other HITL checkpoint types

ALTER TABLE checkpoints
MODIFY COLUMN checkpoint_type Enum8(
    'phase_input' = 1,
    'sounding_eval' = 2,
    'free_text' = 3,
    'choice' = 4,
    'multi_choice' = 5,
    'confirmation' = 6,
    'rating' = 7,
    'audible' = 8,
    'decision' = 9
);

-- Also add 'decision' to session_state blocked_type enum
ALTER TABLE session_state
MODIFY COLUMN blocked_type Nullable(Enum8(
    'signal' = 1,
    'hitl' = 2,
    'sensor' = 3,
    'approval' = 4,
    'checkpoint' = 5,
    'decision' = 6
));
