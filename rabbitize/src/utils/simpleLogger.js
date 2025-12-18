const chalk = require('chalk');

/**
 * Simple logger that replaces FirebaseManager for local logging
 */
class SimpleLogger {
  constructor(clientId = 'unknown-client', testId = 'unknown-test', sessionId = null) {
    this.clientId = clientId;
    this.testId = testId;
    this._sessionId = sessionId;
    this._identifier = `[${this.clientId}/${this.testId}]`;
    this.currentPhase = null;
  }

  get sessionId() {
    return this._sessionId;
  }

  set sessionId(value) {
    this._sessionId = value;
  }

  updateSessionId(newSessionId) {
    if (this._sessionId === newSessionId) return;
    this._sessionId = newSessionId;
  }

  // Basic logging methods
  log(...args) {
    console.log(`${chalk.cyan(this._identifier)}`, ...args);
  }

  error(...args) {
    console.error(`${chalk.red(this._identifier)}`, ...args);
  }

  warn(...args) {
    console.warn(`${chalk.yellow(this._identifier)}`, ...args);
  }

  debug(...args) {
    console.debug(`${chalk.gray(this._identifier)}`, ...args);
  }

  info(...args) {
    console.log(`${chalk.blue(this._identifier)}`, ...args);
  }

  // Phase management
  setPhase(phase, details = {}) {
    this.currentPhase = phase;

    // Write status.json file for external process tracking
    if (this._sessionId && global.currentPlaywrightSession) {
      try {
        const sessionDir = `rabbitize-runs/${this.clientId}/${this.testId}/${this._sessionId}`;
        const statusPath = `${sessionDir}/status.json`;

        // Determine actual status based on completion flag and phase
        let sessionStatus = 'active';
        if (global.currentPlaywrightSession.isFullyComplete || phase === 'complete' || phase === 'completed') {
          sessionStatus = 'finished';
        } else if (!global.currentPlaywrightSession.browser && phase !== 'ending_session' &&
                   !phase.includes('converting') && !phase.includes('processing') &&
                   !phase.includes('creating') && !phase.includes('detecting') &&
                   !phase.includes('uploading')) {
          // Only mark as finished if browser is closed AND we're not in a processing phase
          sessionStatus = 'finished';
        }

        const status = {
          phase: phase,
          status: sessionStatus,
          startTime: global.currentPlaywrightSession.startTime || Date.now(),
          lastUpdate: Date.now(),
          commandCount: global.currentPlaywrightSession.totalCommands || global.currentPlaywrightSession.commandHistory?.length || 0,
          commandsExecuted: global.currentPlaywrightSession.commandCounter || 0,
          currentCommand: global.currentPlaywrightSession.currentCommand || null,
          currentCommandIndex: global.currentPlaywrightSession.commandCounter || 0,
          pid: process.pid,
          hostname: require('os').hostname(),
          errors: global.currentPlaywrightSession.errors || [],
          videoProcessing: phase.includes('converting') || phase.includes('processing'),
          clientId: this.clientId,
          testId: this.testId,
          sessionId: this._sessionId,
          initialUrl: global.currentPlaywrightSession.initialUrl || null,
          port: global.argv?.port || 3037,
          totalCommands: global.currentPlaywrightSession.totalCommands || 0
        };

        // Ensure directory exists
        const fs = require('fs');
        const path = require('path');
        fs.mkdirSync(path.dirname(statusPath), { recursive: true });

        // Write status file atomically
        const tmpPath = `${statusPath}.tmp`;
        fs.writeFileSync(tmpPath, JSON.stringify(status, null, 2));
        fs.renameSync(tmpPath, statusPath);
      } catch (error) {
        // Silent fail - don't break the flow just because status writing failed
        console.error('Failed to write status.json:', error.message);
      }
    }

    // Notify about phase change if callback is set
    if (typeof global.onPhaseChange === 'function' && global.currentPlaywrightSession) {
      global.onPhaseChange(global.currentPlaywrightSession, phase);
    }
  }

  setRunningState(state) {
    // Silent - no logging
  }

  // Methods that need to exist but do nothing
  async cleanupExistingSession() {}
  async setCommandStatus(index, status) {}
  async saveCommandResult(command, result, metadata) {}
  async uploadFile(localPath, remotePath) { return localPath; }
  async uploadFileWithRetry(localPath, remotePath) { return localPath; }
  async uploadLatestScreenshot(screenshotPath) {}
  async uploadSessionSummary(summaryPath) { return summaryPath; }
  async setSessionPath(path, value) {}
  async updateSessionPath(path, value) {}
  async pushToSessionPath(path, value) {}
  async setMetricsPath(path, value) {}
  async setLatestScreenshotUrl(url) {}
  async updateLiveStats(stats) {}
  async updateWorkerStatus(status) {}
  async setSessionMetadata(metadata) {}
  async setSessionType(type) {}
  async setInitialUrl(url) {}
  async setJobJson(jobJson) {}
  async waitForUploads() {}
  async waitForPendingOperations() {}
  async waitForPendingUploads() {}
  async flush() { return Promise.resolve(); }

  async recordError(error, context) {
    this.error(`Error in ${context}:`, error);
  }

  getLatestScreenshotUrl() {
    return null;
  }

  getBasePath() {
    if (!this._sessionId) {
      throw new Error('SessionId not set');
    }
    return `clients/${this.clientId}/${this.testId}/${this._sessionId}`;
  }

  getMetricsBasePath() {
    return this.getBasePath() + '/metrics';
  }

  // Maintain some properties for compatibility
  get firebaseEnabled() {
    return false;
  }

  get db() {
    // Return a mock db object for compatibility
    return {
      ref: (path) => ({
        set: async () => {},
        update: async () => {},
        push: async () => {},
        once: async () => ({ exists: () => false, val: () => null }),
        remove: async () => {},
        on: (event, callback) => {
          // No-op - no real-time updates in local mode
          // Return a function that can be used with .off()
          return callback;
        },
        off: (event, callback) => {
          // No-op - no listeners to remove
        },
        child: (childPath) => ({
          on: (event, callback) => callback,
          off: (event, callback) => {},
          once: async () => ({ exists: () => false, val: () => null })
        })
      })
    };
  }
}

module.exports = SimpleLogger;