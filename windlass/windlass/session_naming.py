"""
Session ID naming system for RVBBIT/Windlass.

Generates memorable session IDs using woodland creature themes.
Format: <adjective>-<creature>-<hash6>

Examples:
  - quick-rabbit-a3f2e1
  - clever-fox-7b9d4c
  - misty-owl-e4c1f8
"""
import random
import hashlib
import time
from typing import Literal

# Woodland-themed adjectives (rabbit/forest vibes)
WOODLAND_ADJECTIVES = [
    # Speed/agility (rabbit-like)
    'quick', 'swift', 'nimble', 'fleet', 'agile', 'bouncy', 'zippy', 'speedy',
    # Intelligence
    'clever', 'wise', 'bright', 'sharp', 'keen', 'alert', 'cunning', 'smart',
    # Nature qualities
    'gentle', 'quiet', 'shy', 'bold', 'wild', 'free', 'playful', 'happy',
    # Forest atmosphere
    'mossy', 'leafy', 'shadowy', 'misty', 'dewy', 'frosty', 'sunlit', 'amber',
    # Character
    'brave', 'curious', 'friendly', 'fuzzy', 'cozy', 'spry', 'merry', 'noble',
    # Colors
    'silver', 'golden', 'russet', 'crimson', 'azure', 'emerald', 'ivory',
    # Seasons/time
    'dawn', 'dusk', 'spring', 'autumn', 'winter', 'summer', 'twilight',
]

# Woodland creatures (emphasizing rabbits, but diverse)
WOODLAND_CREATURES = [
    # Rabbits (featured for RVBBIT!)
    'rabbit', 'hare', 'bunny', 'cottontail', 'jackrabbit', 'snowshoe',
    # Small mammals
    'fox', 'squirrel', 'chipmunk', 'mouse', 'vole', 'hedgehog', 'badger',
    'ferret', 'weasel', 'otter', 'beaver', 'marmot', 'pika', 'shrew',
    # Deer family
    'deer', 'fawn', 'elk', 'moose', 'caribou', 'antelope',
    # Birds
    'owl', 'woodpecker', 'robin', 'wren', 'jay', 'thrush', 'finch',
    'hawk', 'falcon', 'eagle', 'sparrow', 'cardinal', 'chickadee',
    # Others
    'raccoon', 'porcupine', 'skunk', 'opossum', 'mole', 'mink',
    'lynx', 'bobcat', 'coyote', 'wolf', 'bear', 'boar'
]


def generate_woodland_id(seed: str = None) -> str:
    """
    Generate a memorable woodland-themed session ID.

    Format: <adjective>-<creature>-<hash6>

    Args:
        seed: Optional seed for deterministic generation (useful for testing)

    Returns:
        Session ID like 'quick-rabbit-a3f2e1'

    Examples:
        >>> generate_woodland_id()
        'clever-fox-7b9d4c'
        >>> generate_woodland_id()
        'misty-owl-e4c1f8'
    """
    if seed:
        # Deterministic for testing
        random.seed(seed)

    adj = random.choice(WOODLAND_ADJECTIVES)
    creature = random.choice(WOODLAND_CREATURES)

    # Generate short hash from timestamp + random
    hash_input = f"{adj}{creature}{time.time()}{random.random()}"
    short_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:6]

    return f"{adj}-{creature}-{short_hash}"


def generate_session_id(
    style: Literal['woodland', 'uuid', 'coolname'] = 'woodland',
    seed: str = None
) -> str:
    """
    Generate a session ID with configurable style.

    Args:
        style: ID generation style
            - 'woodland': Adjective-creature-hash (default for RVBBIT)
            - 'uuid': Legacy nb_<uuid> format
            - 'coolname': Uses coolname library (if installed)
        seed: Optional seed for deterministic generation

    Returns:
        Session ID string

    Examples:
        >>> generate_session_id('woodland')
        'quick-rabbit-a3f2e1'
        >>> generate_session_id('uuid')
        'nb_a3f2e1b9c4d5'
    """
    if style == 'woodland':
        return generate_woodland_id(seed)

    elif style == 'coolname':
        try:
            from coolname import generate_slug
            slug = generate_slug(2)
            # Add short hash for uniqueness
            hash_input = f"{slug}{time.time()}{random.random()}"
            short_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:6]
            return f"{slug}-{short_hash}"
        except ImportError:
            # Fallback to woodland if coolname not installed
            return generate_woodland_id(seed)

    elif style == 'uuid':
        # Legacy format
        import uuid
        return f"nb_{uuid.uuid4().hex[:12]}"

    else:
        raise ValueError(f"Unknown session ID style: {style}")


def get_session_id_style() -> str:
    """
    Get session ID style from environment variable.

    Checks WINDLASS_SESSION_ID_STYLE (defaults to 'woodland')

    Returns:
        'woodland', 'uuid', or 'coolname'
    """
    import os
    style = os.getenv('WINDLASS_SESSION_ID_STYLE', 'woodland').lower()

    if style not in ('woodland', 'uuid', 'coolname'):
        print(f"[Warning] Invalid WINDLASS_SESSION_ID_STYLE='{style}', using 'woodland'")
        return 'woodland'

    return style


# Convenience function for automatic style detection
def auto_generate_session_id() -> str:
    """
    Generate session ID using style from environment variable.

    Respects WINDLASS_SESSION_ID_STYLE env var (default: woodland)

    Returns:
        Session ID string
    """
    style = get_session_id_style()
    return generate_session_id(style)


if __name__ == '__main__':
    # Demo
    print("Woodland Session IDs:")
    for _ in range(10):
        print(f"  {generate_woodland_id()}")

    print("\nUUID Style:")
    for _ in range(3):
        print(f"  {generate_session_id('uuid')}")
