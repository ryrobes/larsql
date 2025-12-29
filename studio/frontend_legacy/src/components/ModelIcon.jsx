import React from 'react';
import { Icon } from '@iconify/react';
import './ModelIcon.css';

/**
 * ModelIcon - Displays provider icon for a given model ID
 *
 * Features:
 * - Extracts provider from model ID (e.g., "anthropic/claude-opus" -> "anthropic")
 * - Maps providers to appropriate icons
 * - Fallback to generic robot icon for unknown providers
 * - Consistent sizing and styling
 *
 * Usage:
 *   <ModelIcon modelId="anthropic/claude-opus-4.5" size={16} />
 *   <ModelIcon modelId="google/gemini-2.5-flash" />
 */

// Provider to icon mapping
// Using iconify icons for consistency with the dashboard
const PROVIDER_ICONS = {
  // Major providers
  'anthropic': 'simple-icons:anthropic',
  'openai': 'simple-icons:openai',
  'google': 'simple-icons:google',
  'google-ai': 'simple-icons:google',
  'gemini': 'simple-icons:google',

  // Meta/Facebook
  'meta': 'simple-icons:meta',
  'meta-llama': 'simple-icons:meta',
  'facebook': 'simple-icons:meta',

  // Microsoft/Azure
  'microsoft': 'simple-icons:microsoft',
  'azure': 'simple-icons:microsoftazure',

  // Cloud providers
  'aws': 'simple-icons:amazonaws',
  'amazon': 'simple-icons:amazonaws',
  'cohere': 'mdi:cloud',

  // AI companies
  'mistral': 'mdi:creation',
  'mistralai': 'mdi:creation',
  'deepseek': 'mdi:brain-frozen',
  'x-ai': 'simple-icons:x',
  'xai': 'simple-icons:x',
  'nvidia': 'simple-icons:nvidia',
  'databricks': 'simple-icons:databricks',

  // Chinese providers
  'zhipu': 'mdi:compass-outline',
  'z-ai': 'mdi:compass-outline',
  'minimax': 'mdi:cube-outline',
  'xiaomi': 'simple-icons:xiaomi',
  'qwen': 'mdi:chip',
  'alibaba': 'simple-icons:alibaba',

  // Open source/local
  'ollama': 'mdi:llama',
  'perplexity': 'mdi:magnify-expand',
  'huggingface': 'simple-icons:huggingface',
  'together': 'mdi:account-group-outline',
  'together-ai': 'mdi:account-group-outline',
  'replicate': 'mdi:repeat',

  // Specialty
  'openrouter': 'mdi:router',
  'ai21': 'mdi:atom',
  'aleph': 'mdi:alpha',
  'allenai': 'mdi:school',
  'mancer': 'mdi:wizard-hat',
  'neversleep': 'mdi:sleep-off',
  'nex-agi': 'mdi:robot-excited',
  'nousresearch': 'mdi:flask-outline',
  'gryphe': 'mdi:griffin',
  'undi95': 'mdi:creation',
  'teknium': 'mdi:robot-industrial',
  'sao10k': 'mdi:sword',
  'koboldai': 'mdi:creation-outline',
  'pygmalionai': 'mdi:text-box-multiple-outline',

  // Fallback
  'default': 'mdi:robot-outline',
};

/**
 * Get provider from model ID
 * Examples:
 *   "anthropic/claude-opus-4.5" -> "anthropic"
 *   "google/gemini-2.5-flash" -> "google"
 *   "meta-llama/llama-3.3-70b" -> "meta-llama"
 */
function getProvider(modelId) {
  if (!modelId || typeof modelId !== 'string') return 'default';

  const parts = modelId.split('/');
  if (parts.length < 2) return 'default';

  return parts[0].toLowerCase();
}

/**
 * Get icon for a provider
 */
function getProviderIcon(provider) {
  return PROVIDER_ICONS[provider] || PROVIDER_ICONS.default;
}

/**
 * Get color for a provider
 */
function getProviderColor(provider) {
  const colors = {
    anthropic: '#d97757',
    openai: '#10a37f',
    google: '#4285f4',
    meta: '#0668e1',
    'meta-llama': '#0668e1',
    microsoft: '#00a4ef',
    azure: '#0078d4',
    'x-ai': '#1da1f2',
    nvidia: '#76b900',
    mistral: '#ff7000',
    mistralai: '#ff7000',
    deepseek: '#6366f1',
    default: '#64748b',
  };

  return colors[provider] || colors.default;
}

/**
 * ModelIcon component
 */
function ModelIcon({
  modelId,
  size = 14,
  className = '',
  showTooltip = false,
  style = {}
}) {
  const provider = getProvider(modelId);
  const icon = getProviderIcon(provider);
  const color = getProviderColor(provider);

  const title = showTooltip ? `Provider: ${provider}` : undefined;

  return (
    <Icon
      icon={icon}
      width={size}
      height={size}
      className={`model-icon ${className}`}
      style={{ color, ...style }}
      title={title}
    />
  );
}

/**
 * Hook to get model metadata
 */
export function useModelMetadata(modelId) {
  const provider = getProvider(modelId);
  const icon = getProviderIcon(provider);
  const color = getProviderColor(provider);

  return {
    provider,
    icon,
    color,
  };
}

export default ModelIcon;
export { getProvider, getProviderIcon, getProviderColor };
