/**
 * Efficient circular buffer implementation for managing screenshots
 */
class CircularBuffer {
  /**
   * @param {number} size - Maximum number of items to store
   */
  constructor(size) {
    this.size = size;
    this.buffer = new Array(size);
    this.writePos = 0;
    this.length = 0;
  }

  /**
   * Add an item to the buffer
   * @param {Buffer} item - Item to add
   */
  push(item) {
    this.buffer[this.writePos] = item;
    this.writePos = (this.writePos + 1) % this.size;
    this.length = Math.min(this.length + 1, this.size);
  }

  /**
   * Get the most recent items
   * @param {number} count - Number of recent items to get
   * @returns {Buffer[]} Array of most recent items
   */
  getRecent(count = 1) {
    const result = [];
    const itemCount = Math.min(count, this.length);

    for (let i = 0; i < itemCount; i++) {
      const pos = (this.size + this.writePos - 1 - i) % this.size;
      result.push(this.buffer[pos]);
    }

    return result;
  }

  /**
   * Clear the buffer
   */
  clear() {
    this.buffer = new Array(this.size);
    this.writePos = 0;
    this.length = 0;
  }

  /**
   * Get current number of items in buffer
   */
  getLength() {
    return this.length;
  }

  /**
   * Check if buffer is full
   */
  isFull() {
    return this.length === this.size;
  }
}

module.exports = CircularBuffer;