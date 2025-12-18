const path = require('path');
const fsPromises = require('fs').promises;

class FirestoreManager {
    constructor(clientId, testId, sessionId) {
        this.clientId = clientId;
        this.testId = testId;
        this._sessionId = sessionId;
        // Completely remove Firestore initialization
        this.db = null;
        this.bucket = null;
        this.pendingOperations = new Set();
        this.initialized = false;
        this.bufferedOperations = [];

        // Initialize in-memory data store
        this.sessionData = {
            'client-id': this.clientId,
            'test-id': this.testId,
            'session-id': this._sessionId,
            commands: {},
            metrics: [],
            'phase-history': {},
            logs: [],
            running: true,
            startTime: new Date().toISOString()
        };
    }

    // Initialize the manager - must be called before any operations
    async initialize() {
        this.initialized = true;
        // Process any buffered operations in order
        for (const op of this.bufferedOperations) {
            await op();
        }
        this.bufferedOperations = [];
    }

    // Buffer or execute an operation based on initialization state
    async _executeOrBuffer(operation) {
        if (!this.initialized) {
            return new Promise(resolve => {
                this.bufferedOperations.push(async () => {
                    const result = await operation();
                    resolve(result);
                });
            });
        }
        return await operation();
    }

    // Getter/Setter for sessionId
    get sessionId() {
        return this._sessionId;
    }

    set sessionId(value) {
        this._sessionId = value;
        this.sessionData['session-id'] = value;
    }

    // Get reference to our single collection (stubbed)
    getRunHistoryCollection() {
        // Return a stub object that does nothing
        return {
            doc: () => ({
                set: async () => {},
                delete: async () => {}
            })
        };
    }

    // Track pending operations (now just resolves immediately)
    _trackOperation(promise) {
        return Promise.resolve();
    }

    // Wait for all pending operations (now just resolves immediately)
    async waitForPendingOperations() {
        return Promise.resolve();
    }

    // Format job_json for Firestore
    _formatJobJson(job_json) {
        if (!job_json) return null;

        const formatted = { ...job_json };
        if (Array.isArray(formatted.commands)) {
            formatted.commands = formatted.commands.reduce((acc, command, index) => {
                const commandValue = Array.isArray(command) ? command.join(' ') : command;
                acc[`command_${index}`] = commandValue;
                return acc;
            }, {});
        }
        return formatted;
    }

    // Update session data in memory
    async setSessionData(data) {
        return this._executeOrBuffer(async () => {
            try {
                const formattedData = { ...data };
                if (formattedData.job_json) {
                    formattedData.job_json = this._formatJobJson(formattedData.job_json);
                }
                Object.assign(this.sessionData, formattedData);
                return true;
            } catch (error) {
                console.error('Failed to set session data:', error);
                return false;
            }
        });
    }

    // Add command to memory
    async addCommand(command, result, artifacts) {
        return this._executeOrBuffer(async () => {
            try {
                const formattedCommand = Array.isArray(command) ? command.join(' ') : command;
                const commandData = {
                    command: formattedCommand,
                    commandArray: command,
                    result,
                    artifacts,
                    timestamp: new Date().toISOString()
                };

                const commandIndex = Object.keys(this.sessionData.commands).length;
                this.sessionData.commands[`command_${commandIndex}`] = commandData;
                return true;
            } catch (error) {
                console.error('Failed to add command:', error);
                return false;
            }
        });
    }

    // Update phase in memory
    async setPhase(phase, details = {}) {
        return this._executeOrBuffer(async () => {
            try {
                this.sessionData.currentPhase = phase;
                this.sessionData.phaseDetails = details;

                const phaseIndex = Object.keys(this.sessionData['phase-history']).length;
                this.sessionData['phase-history'][`phase_${phaseIndex}`] = {
                    phase,
                    details,
                    timestamp: new Date().toISOString()
                };

                return true;
            } catch (error) {
                console.error('Failed to set phase:', error);
                return false;
            }
        });
    }

    // Add metrics to memory
    async addMetrics(metrics) {
        return this._executeOrBuffer(async () => {
            try {
                this.sessionData.metrics.push({
                    ...metrics,
                    timestamp: new Date().toISOString()
                });
                return true;
            } catch (error) {
                console.error('Failed to add metrics:', error);
                return false;
            }
        });
    }

    // Get current session data from memory
    async getSessionData() {
        return this.sessionData;
    }

    // Get commands from memory
    async getSessionCommands() {
        return Object.values(this.sessionData.commands);
    }

    // Update running state in memory
    async setRunningState(isRunning) {
        try {
            this.sessionData.running = isRunning;
            if (!isRunning) {
                this.sessionData.endTime = new Date().toISOString();
            }
            return true;
        } catch (error) {
            console.error('Failed to set running state:', error);
            return false;
        }
    }

    // Add log entry to memory
    async log(level, message, data = null) {
        return this._executeOrBuffer(async () => {
            try {
                const logEntry = {
                    level,
                    message,
                    data,
                    timestamp: new Date().toISOString()
                };
                this.sessionData.logs.push(logEntry);
                return true;
            } catch (error) {
                console.error('Failed to add log:', error);
                return false;
            }
        });
    }

    // Convenience methods for different log levels
    async debug(message, data = null) {
        return this.log('debug', message, data);
    }

    async info(message, data = null) {
        return this.log('info', message, data);
    }

    async warn(message, data = null) {
        return this.log('warn', message, data);
    }

    async error(message, data = null) {
        return this.log('error', message, data);
    }

    // Write everything to Firestore (completely disabled)
    async writeToFirestore() {
        try {
            // Ensure session-id is current
            this.sessionData['session-id'] = this.sessionId;

            // Save raw JSON file to storage
            const rawJsonContent = JSON.stringify(this.sessionData, null, 2);
            const tempFilePath = path.join(process.cwd(), `${this.sessionId}_raw.json`);

            await fsPromises.writeFile(tempFilePath, rawJsonContent);

            // Skip storage upload - keeping data local only

            // Clean up temp file
            await fsPromises.unlink(tempFilePath);

            return true;
        } catch (error) {
            console.error('Failed to save session data JSON:', error);
            return false;
        }
    }

    // Clean up session (Firestore operations disabled)
    async cleanupSession() {
        return this._executeOrBuffer(async () => {
            try {
                this.sessionData.running = false;
                this.sessionData.endTime = new Date().toISOString();
                this.sessionData.status = 'ended';

                // Still save the final session data JSON
                await this.writeToFirestore();
                return true;
            } catch (error) {
                console.error('Failed to cleanup session:', error);
                return false;
            }
        });
    }
}

module.exports = FirestoreManager;