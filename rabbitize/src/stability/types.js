/**
 * @typedef {Object} StabilityOptions
 * @property {boolean} enabled - Whether stability detection is enabled
 * @property {number} waitTime - Seconds to wait for stability
 * @property {number} sensitivity - Difference threshold (0-1)
 * @property {number} timeout - Maximum seconds to wait
 * @property {number} interval - MS between captures (frameCount = waitTime/interval)
 * @property {number} frameCount - Calculated from waitTime/interval
 * @property {number} [downscaleWidth] - Width to downscale to for quick comparison
 */

module.exports = {};