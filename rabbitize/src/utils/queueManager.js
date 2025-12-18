const PlaywrightSession = require('../PlaywrightSession.js');
const SimpleLogger = require('./simpleLogger');

class QueueManager {
  constructor() {
    this.queue = [];
    this.completedCommands = [];
    this.currentSession = null;
    this.currentPhase = 'idle';
    this.isEnabled = false;
    this.isProcessing = false;
    this.previousUrl = null;
  }

  setSession(session) {
    this.currentSession = session;
    this.testId = session.testId;
    this.clientId = session.clientId;
    this.sessionStartTime = new Date();
    this.lastSession = null;
  }

  setOnSessionEndCallback(callback) {
    this.onSessionEnd = callback;
  }

  setOnCommandExecutedCallback(callback) {
    this.onCommandExecuted = callback;
  }

  setOnSessionStartCallback(callback) {
    this.onSessionStart = callback;
  }

  setOnQueueEmptyCallback(callback) {
    this.onQueueEmpty = callback;
  }

  startProcessing() {
    this.isEnabled = true;
    if (!this.sessionStartTime) {
      this.sessionStartTime = new Date();
    }
    this.processQueue();
  }

  async enqueue(type, payload) {
    const commandId = Date.now() + Math.random().toString(36).substring(7);
    const queueItem = {
      id: commandId,
      type,
      payload,
      status: 'queued',
      queuedAt: new Date().toISOString()
    };
    this.queue.push(queueItem);

    if (this.isEnabled && !this.isProcessing) {
      this.processQueue();
    }

    return {
      success: true,
      message: `${type} command queued`,
      commandId
    };
  }

  async processQueue() {
    if (!this.isEnabled || this.isProcessing || this.queue.length === 0 || !this.currentSession) {
      return;
    }

    this.isProcessing = true;

    while (this.queue.length > 0 && this.isEnabled) {
      const item = this.queue[0];
      item.status = 'processing';
      item.startedAt = new Date().toISOString();

      this.currentPhase = item.type;

      try {
        switch (item.type) {
          case 'execute':
            if (this.currentSession.firebase) {
              this.currentSession.firebase.log(`Executing command: ${JSON.stringify(item.payload.command)}`);
            }
            await this.currentSession.executeCommand(item.payload.command);
            
            // Update command count
            if (typeof this.onCommandExecuted === 'function') {
              this.onCommandExecuted(this.currentSession);
            }
            break;

          case 'end':
            const logger = this.currentSession.firebase;

            const isQuickCleanup = item.payload?.quickCleanup || false;

            if (isQuickCleanup) {
              await this.currentSession.quickEnd();
              this.previousUrl = this.currentSession.initialUrl;
              if (!this.queue.length) {
                this.isEnabled = false;
              }
            } else {
              await this.currentSession.end();
              this.isEnabled = false;
            }

            // Notify about session ending AFTER it actually ends
            if (this.currentSession && typeof this.onSessionEnd === 'function') {
              this.onSessionEnd(this.currentSession);
            }

            this.completedCommands = [];
            this.currentPhase = 'idle';
            this.currentSession = null;

            if (!isQuickCleanup && global.argv && global.argv.exitOnEnd) {
              if (logger) logger.log('exitOnEnd enabled, shutting down');
              process.exit(0);
            } else {
              if (logger) logger.log('Success, ready for new session');
            }
            break;

          case 'start':
            if (!item.payload.url && this.previousUrl) {
              item.payload.url = this.previousUrl;
            }
            const sessionTimestamp = new Date().toISOString().replace(/[:.]/g, '-');
            const newSession = new (require('../PlaywrightSession.js'))(sessionTimestamp, '', {
              showCommandOverlay: global.argv.showOverlay,
              createClipSegments: global.argv.clipSegments,
              clientId: global.argv.clientId,
              testId: global.argv.testId,
              enableLiveScreenshots: global.argv.liveScreenshots
            });

            this.currentSession = newSession;
            const initResult = await this.currentSession.initialize(item.payload.url || this.previousUrl);
            if (!initResult.success) {
              throw new Error('Failed to initialize session');
            }
            
            // Notify about new session start (for bootstrap mode)
            if (typeof this.onSessionStart === 'function') {
              this.onSessionStart(this.currentSession);
            }
            break;
        }

        item.status = 'completed';
        item.completedAt = new Date().toISOString();
        this.completedCommands.push(item);
      } catch (error) {
        item.status = 'failed';
        item.error = error.message;
        item.failedAt = new Date().toISOString();
        this.completedCommands.push(item);
        console.error(`Queue item ${item.id} failed:`, error);
        this.isEnabled = false;
        break;
      }

      this.queue.shift();
    }

    this.isProcessing = false;
    if (!this.queue.length) {
      this.currentPhase = 'idle';
      
      // Call queue empty callback if set
      if (typeof this.onQueueEmpty === 'function') {
        this.onQueueEmpty();
      }
    }
  }

  setFirebasePhase(phase, details = {}) {
    this.firebasePhase = { phase, details };
  }

  getStatus() {
    if (this.completedCommands.length > 50) {
      this.completedCommands = this.completedCommands.slice(-50);
    }

    const currentState = {
      isProcessing: this.isProcessing,
      queueLength: this.queue.length,
      phase: this.currentPhase,
      firebasePhase: this.firebasePhase,
      testId: this.testId,
      clientId: this.clientId,
      currentlyProcessing: this.isProcessing && this.queue[0] ? {
        type: this.queue[0].type,
        ...(this.queue[0].type === 'execute' && { command: this.queue[0].payload.command }),
        ...(this.queue[0].type === 'start' && { url: this.queue[0].payload.url })
      } : null
    };

    if (this.sessionStartTime) {
      currentState.startedAt = this.sessionStartTime.toISOString();
      currentState.secondsRunning = Math.floor((new Date() - this.sessionStartTime) / 1000);
    }

    if (!this.sessionStartTime && this.lastSession) {
      currentState.lastSession = this.lastSession;
    }

    return {
      currentState,
      queued: this.queue.map(item => ({
        type: item.type,
        status: item.status,
        queuedAt: item.queuedAt,
        ...(item.type === 'execute' && { command: item.payload.command }),
        ...(item.type === 'start' && { url: item.payload.url })
      })),
      recentlyCompleted: this.completedCommands.slice(-10).map(item => ({
        type: item.type,
        status: item.status,
        queuedAt: item.queuedAt,
        completedAt: item.completedAt,
        ...(item.status === 'failed' && { error: item.error }),
        ...(item.type === 'execute' && { command: item.payload.command }),
        ...(item.type === 'start' && { url: item.payload.url })
      })).reverse()
    };
  }
}

const queueManager = new QueueManager();
module.exports = queueManager;