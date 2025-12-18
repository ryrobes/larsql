const FirestoreManager = require('../src/utils/firestoreUtils');
const fs = require('fs').promises;
const path = require('path');

// Mock fs.promises
jest.mock('fs', () => ({
  promises: {
    writeFile: jest.fn(),
    unlink: jest.fn()
  }
}));

describe('FirestoreManager', () => {
  let manager;

  beforeEach(() => {
    manager = new FirestoreManager('test-client', 'test-test', 'test-session');
    jest.clearAllMocks();
  });

  describe('constructor', () => {
    it('should initialize with in-memory storage', () => {
      expect(manager.clientId).toBe('test-client');
      expect(manager.testId).toBe('test-test');
      expect(manager._sessionId).toBe('test-session');
      expect(manager.db).toBeNull(); // No Firestore connection
      expect(manager.sessionData).toBeDefined();
      expect(manager.sessionData['client-id']).toBe('test-client');
      expect(manager.sessionData.running).toBe(true);
    });
  });

  describe('initialize', () => {
    it('should mark as initialized', async () => {
      expect(manager.initialized).toBe(false);
      await manager.initialize();
      expect(manager.initialized).toBe(true);
    });

    it('should process buffered operations', async () => {
      const mockOp = jest.fn().mockResolvedValue('result');
      manager.bufferedOperations.push(mockOp);
      
      await manager.initialize();
      
      expect(mockOp).toHaveBeenCalled();
      expect(manager.bufferedOperations).toHaveLength(0);
    });
  });

  describe('_executeOrBuffer', () => {
    it('should execute immediately if initialized', async () => {
      await manager.initialize();
      
      const operation = jest.fn().mockResolvedValue('result');
      const result = await manager._executeOrBuffer(operation);
      
      expect(operation).toHaveBeenCalled();
      expect(result).toBe('result');
    });

    it('should buffer operation if not initialized', async () => {
      const operation = jest.fn().mockResolvedValue('result');
      const promise = manager._executeOrBuffer(operation);
      
      expect(operation).not.toHaveBeenCalled();
      expect(manager.bufferedOperations).toHaveLength(1);
      
      await manager.initialize();
      const result = await promise;
      
      expect(operation).toHaveBeenCalled();
      expect(result).toBe('result');
    });
  });

  describe('sessionId management', () => {
    it('should update sessionId', () => {
      manager.sessionId = 'new-session';
      expect(manager._sessionId).toBe('new-session');
      expect(manager.sessionData['session-id']).toBe('new-session');
    });

    it('should update sessionId without logging', () => {
      // The actual implementation doesn't log when sessionId changes
      manager.sessionId = 'different-session';
      
      expect(manager.sessionId).toBe('different-session');
      expect(manager.sessionData['session-id']).toBe('different-session');
    });
  });

  describe('setPhase', () => {
    it('should update phase in session data', async () => {
      await manager.initialize();
      await manager.setPhase('testing', { detail: 'value' });
      
      expect(manager.sessionData.currentPhase).toBe('testing');
      expect(manager.sessionData.phaseDetails).toEqual({ detail: 'value' });
      expect(manager.sessionData['phase-history']).toBeDefined();
      expect(manager.sessionData['phase-history']['phase_0']).toMatchObject({
        phase: 'testing',
        details: { detail: 'value' }
      });
    });
  });

  describe('addCommand', () => {
    it('should add command to session data', async () => {
      await manager.initialize();
      
      const command = ['click', '.button'];
      const result = { success: true };
      const artifacts = { screenshot: 'data' };
      
      await manager.addCommand(command, result, artifacts);
      
      expect(Object.keys(manager.sessionData.commands)).toHaveLength(1);
      const commandKey = Object.keys(manager.sessionData.commands)[0];
      expect(manager.sessionData.commands[commandKey].command).toBe('click .button');
      expect(manager.sessionData.commands[commandKey].commandArray).toEqual(command);
      expect(manager.sessionData.commands[commandKey].result).toEqual(result);
      expect(manager.sessionData.commands[commandKey].artifacts).toEqual(artifacts);
    });
  });

  describe('setSessionData', () => {
    it('should merge data into session data', async () => {
      await manager.initialize();
      
      await manager.setSessionData({
        customField: 'value',
        anotherField: 123
      });
      
      expect(manager.sessionData.customField).toBe('value');
      expect(manager.sessionData.anotherField).toBe(123);
    });
  });

  describe('setSessionData', () => {
    it('should format job_json correctly', async () => {
      await manager.initialize();
      
      await manager.setSessionData({
        job_json: {
          commands: ['click .button', 'wait 2', 'type input text']
        }
      });
      
      expect(manager.sessionData.job_json).toEqual({
        commands: {
          command_0: 'click .button',
          command_1: 'wait 2',
          command_2: 'type input text'
        }
      });
    });
  });

  describe('writeToFirestore', () => {
    it('should write session data to JSON file', async () => {
      await manager.initialize();
      
      const result = await manager.writeToFirestore();
      
      expect(result).toBe(true);
      expect(fs.writeFile).toHaveBeenCalled();
      expect(fs.unlink).toHaveBeenCalled();
      
      // Check the file path used
      const writeCall = fs.writeFile.mock.calls[0];
      expect(writeCall[0]).toMatch(/test-session_raw\.json$/);
      expect(JSON.parse(writeCall[1])).toMatchObject({
        'client-id': 'test-client',
        'test-id': 'test-test',
        'session-id': 'test-session'
      });
    });

    it('should handle write errors', async () => {
      fs.writeFile.mockRejectedValueOnce(new Error('Write failed'));
      const consoleSpy = jest.spyOn(console, 'error').mockImplementation();
      
      const result = await manager.writeToFirestore();
      
      expect(result).toBe(false);
      expect(consoleSpy).toHaveBeenCalledWith(
        'Failed to save session data JSON:',
        expect.any(Error)
      );
      
      consoleSpy.mockRestore();
    });
  });

  describe('cleanupSession', () => {
    it('should mark session as ended', async () => {
      await manager.initialize();
      
      const result = await manager.cleanupSession();
      
      expect(result).toBe(true);
      expect(manager.sessionData.running).toBe(false);
      expect(manager.sessionData.status).toBe('ended');
      expect(manager.sessionData.endTime).toBeDefined();
    });
  });

  describe('waitForPendingOperations', () => {
    it('should resolve immediately (no-op)', async () => {
      await manager.initialize();
      
      const startTime = Date.now();
      await manager.waitForPendingOperations();
      const duration = Date.now() - startTime;
      
      // Should resolve immediately as it's a no-op
      expect(duration).toBeLessThan(10);
    });
  });
});