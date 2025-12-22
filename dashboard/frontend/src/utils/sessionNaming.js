/**
 * Session ID naming system for RVBBIT/Windlass.
 *
 * Generates memorable session IDs using woodland creature themes.
 * Format: <adjective>-<creature>-<hash6>
 *
 * Examples:
 *   - quick-rabbit-a3f2e1
 *   - clever-fox-7b9d4c
 *   - misty-owl-e4c1f8
 */

const WOODLAND_ADJECTIVES = [
  // Speed/agility (rabbit-like)
  'quick', 'swift', 'nimble', 'fleet', 'agile', 'bouncy', 'zippy', 'speedy',
  // Intelligence
  'clever', 'wise', 'bright', 'sharp', 'keen', 'alert', 'cunning', 'smart',
  // Nature qualities
  'gentle', 'quiet', 'shy', 'bold', 'wild', 'free', 'playful', 'happy',
  // Forest atmosphere
  'mossy', 'leafy', 'shadowy', 'misty', 'dewy', 'frosty', 'sunlit', 'amber',
  // Character
  'brave', 'curious', 'friendly', 'fuzzy', 'cozy', 'spry', 'merry', 'noble',
  // Colors
  'silver', 'golden', 'russet', 'crimson', 'azure', 'emerald', 'ivory',
  // Seasons/time
  'dawn', 'dusk', 'spring', 'autumn', 'winter', 'summer', 'twilight',
];

const WOODLAND_CREATURES = [
  // Rabbits (featured for RVBBIT!)
  'rabbit', 'hare', 'bunny', 'cottontail', 'jackrabbit', 'snowshoe',
  // Small mammals
  'fox', 'squirrel', 'chipmunk', 'mouse', 'vole', 'hedgehog', 'badger',
  'ferret', 'weasel', 'otter', 'beaver', 'marmot', 'pika', 'shrew',
  // Deer family
  'deer', 'fawn', 'elk', 'moose', 'caribou', 'antelope',
  // Birds
  'owl', 'woodpecker', 'robin', 'wren', 'jay', 'thrush', 'finch',
  'hawk', 'falcon', 'eagle', 'sparrow', 'cardinal', 'chickadee',
  // Others
  'raccoon', 'porcupine', 'skunk', 'opossum', 'mole', 'mink',
  'lynx', 'bobcat', 'coyote', 'wolf', 'bear', 'boar'
];

/**
 * Simple hash function for browser (no crypto.subtle needed)
 */
function simpleHash(str) {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    const char = str.charCodeAt(i);
    hash = ((hash << 5) - hash) + char;
    hash = hash & hash; // Convert to 32bit integer
  }
  return Math.abs(hash).toString(16).padStart(6, '0').slice(0, 6);
}

/**
 * Generate a memorable woodland-themed session ID.
 *
 * @returns {string} Session ID like 'quick-rabbit-a3f2e1'
 */
export function generateWoodlandId() {
  const adj = WOODLAND_ADJECTIVES[Math.floor(Math.random() * WOODLAND_ADJECTIVES.length)];
  const creature = WOODLAND_CREATURES[Math.floor(Math.random() * WOODLAND_CREATURES.length)];

  // Generate short hash from timestamp + random
  const hashInput = `${adj}${creature}${Date.now()}${Math.random()}`;
  const shortHash = simpleHash(hashInput);

  return `${adj}-${creature}-${shortHash}`;
}

/**
 * Generate session ID with configurable style.
 *
 * @param {string} style - 'woodland' (default) or 'uuid' (legacy)
 * @returns {string} Session ID
 */
export function generateSessionId(style = 'woodland') {
  if (style === 'woodland') {
    return generateWoodlandId();
  } else if (style === 'uuid') {
    // Legacy format
    return `nb_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
  } else {
    return generateWoodlandId(); // Default to woodland
  }
}

/**
 * Auto-generate session ID using environment-configured style.
 * Checks localStorage for style preference, defaults to woodland.
 *
 * @returns {string} Session ID
 */
export function autoGenerateSessionId() {
  const style = localStorage.getItem('windlass_session_id_style') || 'woodland';
  return generateSessionId(style);
}
