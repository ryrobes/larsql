const SimpleLogger = require('../src/utils/simpleLogger');
const chalk = require('chalk');

// Mock chalk to avoid color codes in tests
jest.mock('chalk', () => ({
  cyan: jest.fn(text => text),
  red: jest.fn(text => text),
  yellow: jest.fn(text => text),
  gray: jest.fn(text => text),
  blue: jest.fn(text => text)
}));

describe('SimpleLogger', () => {
  let logger;
  let consoleLogSpy, consoleErrorSpy, consoleWarnSpy, consoleDebugSpy;

  beforeEach(() => {
    logger = new SimpleLogger('test-client', 'test-test', 'test-session');
    
    // Spy on console methods
    consoleLogSpy = jest.spyOn(console, 'log').mockImplementation();
    consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation();
    consoleWarnSpy = jest.spyOn(console, 'warn').mockImplementation();
    consoleDebugSpy = jest.spyOn(console, 'debug').mockImplementation();
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  describe('constructor', () => {
    it('should initialize with provided values', () => {
      expect(logger.clientId).toBe('test-client');
      expect(logger.testId).toBe('test-test');
      expect(logger.sessionId).toBe('test-session');
      expect(logger._identifier).toBe('[test-client/test-test]');
    });

    it('should handle default values', () => {
      const defaultLogger = new SimpleLogger();
      expect(defaultLogger.clientId).toBe('unknown-client');
      expect(defaultLogger.testId).toBe('unknown-test');
      expect(defaultLogger.sessionId).toBeNull();
    });
  });

  describe('logging methods', () => {
    it('should log messages with identifier', () => {
      logger.log('test message');
      expect(consoleLogSpy).toHaveBeenCalledWith('[test-client/test-test]', 'test message');
    });

    it('should error messages with identifier', () => {
      logger.error('error message');
      expect(consoleErrorSpy).toHaveBeenCalledWith('[test-client/test-test]', 'error message');
    });

    it('should warn messages with identifier', () => {
      logger.warn('warning message');
      expect(consoleWarnSpy).toHaveBeenCalledWith('[test-client/test-test]', 'warning message');
    });

    it('should debug messages with identifier', () => {
      logger.debug('debug message');
      expect(consoleDebugSpy).toHaveBeenCalledWith('[test-client/test-test]', 'debug message');
    });

    it('should handle multiple arguments', () => {
      logger.log('message', 'with', 'multiple', 'args');
      expect(consoleLogSpy).toHaveBeenCalledWith('[test-client/test-test]', 'message', 'with', 'multiple', 'args');
    });
  });

  describe('sessionId management', () => {
    it('should update sessionId', () => {
      logger.updateSessionId('new-session');
      expect(logger.sessionId).toBe('new-session');
    });

    it('should not update if sessionId is the same', () => {
      logger.sessionId = 'current';
      logger.updateSessionId('current');
      expect(logger.sessionId).toBe('current');
    });
  });

  describe('phase management', () => {
    it('should set phase silently', () => {
      logger.setPhase('testing');
      expect(logger.currentPhase).toBe('testing');
      expect(consoleLogSpy).not.toHaveBeenCalled();
    });

    it('should set running state silently', () => {
      logger.setRunningState(true);
      expect(consoleLogSpy).not.toHaveBeenCalled();
    });
  });

  describe('no-op methods', () => {
    it('should return promises for async no-ops', async () => {
      await expect(logger.cleanupExistingSession()).resolves.toBeUndefined();
      await expect(logger.setCommandStatus(0, 'success')).resolves.toBeUndefined();
      await expect(logger.flush()).resolves.toBeUndefined();
    });

    it('should return input path for upload methods', async () => {
      const result = await logger.uploadFile('/local/path', '/remote/path');
      expect(result).toBe('/local/path');
    });

    it('should return null for getLatestScreenshotUrl', () => {
      expect(logger.getLatestScreenshotUrl()).toBeNull();
    });
  });

  describe('path methods', () => {
    it('should generate base path correctly', () => {
      expect(logger.getBasePath()).toBe('clients/test-client/test-test/test-session');
    });

    it('should throw error if sessionId not set', () => {
      const noSessionLogger = new SimpleLogger('client', 'test');
      expect(() => noSessionLogger.getBasePath()).toThrow('SessionId not set');
    });

    it('should generate metrics base path', () => {
      expect(logger.getMetricsBasePath()).toBe('clients/test-client/test-test/test-session/metrics');
    });
  });

  describe('mock database', () => {
    it('should provide mock db object', () => {
      const db = logger.db;
      expect(db).toBeDefined();
      expect(typeof db.ref).toBe('function');
    });

    it('should return chainable ref methods', async () => {
      const ref = logger.db.ref('test/path');
      await expect(ref.set({})).resolves.toBeUndefined();
      await expect(ref.update({})).resolves.toBeUndefined();
      await expect(ref.push({})).resolves.toBeUndefined();
      await expect(ref.remove()).resolves.toBeUndefined();
    });

    it('should handle .on and .off methods', () => {
      const ref = logger.db.ref('test/path');
      const callback = jest.fn();
      const result = ref.on('value', callback);
      expect(result).toBe(callback);
      
      ref.off('value', callback);
      // No error thrown
    });

    it('should handle child references', async () => {
      const ref = logger.db.ref('test/path');
      const child = ref.child('subpath');
      
      const callback = jest.fn();
      child.on('value', callback);
      child.off('value', callback);
      
      const snapshot = await child.once('value');
      expect(snapshot.exists()).toBe(false);
      expect(snapshot.val()).toBeNull();
    });
  });

  describe('recordError', () => {
    it('should log errors with context', async () => {
      const error = new Error('Test error');
      await logger.recordError(error, 'test-context');
      expect(consoleErrorSpy).toHaveBeenCalledWith('[test-client/test-test]', 'Error in test-context:', error);
    });
  });
});