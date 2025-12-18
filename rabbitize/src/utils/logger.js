class Logger {
  constructor(firebase) {
    this.firebase = firebase;
    this.pendingLogs = [];  // Track pending log operations
  }

  async log(...args) {
    const promise = this.firebase.log(...args);
    this.pendingLogs.push(promise);
    await promise;
  }

  async error(...args) {
    const promise = this.firebase.error(...args);
    this.pendingLogs.push(promise);
    await promise;
  }

  async warn(...args) {
    const promise = this.firebase.warn(...args);
    this.pendingLogs.push(promise);
    await promise;
  }

  async debug(...args) {
    const promise = this.firebase.debug(...args);
    this.pendingLogs.push(promise);
    await promise;
  }

  // New method to wait for all pending logs
  async flush() {
    await Promise.all(this.pendingLogs);
    this.pendingLogs = [];
  }
}

module.exports = Logger;