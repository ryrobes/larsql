const queueManager = require('../src/utils/queueManager');

describe('QueueManager', () => {
  let mockSession;

  beforeEach(() => {
    // Reset queue manager state
    queueManager.queue = [];
    queueManager.completedCommands = [];
    queueManager.currentSession = null;
    queueManager.currentPhase = 'idle';
    queueManager.isEnabled = false;
    queueManager.isProcessing = false;
    
    // Create mock session
    mockSession = {
      clientId: 'test-client',
      testId: 'test-test',
      firebase: {
        log: jest.fn(),
        error: jest.fn()
      },
      executeCommand: jest.fn().mockResolvedValue({ success: true }),
      end: jest.fn().mockResolvedValue({ success: true }),
      quickEnd: jest.fn().mockResolvedValue({ success: true }),
      initialize: jest.fn().mockResolvedValue({ success: true }),
      initialUrl: 'https://test.com'
    };
  });

  describe('setSession', () => {
    it('should set the current session', () => {
      queueManager.setSession(mockSession);
      
      expect(queueManager.currentSession).toBe(mockSession);
      expect(queueManager.testId).toBe('test-test');
      expect(queueManager.clientId).toBe('test-client');
      expect(queueManager.sessionStartTime).toBeDefined();
    });
  });

  describe('enqueue', () => {
    it('should add items to the queue', async () => {
      const result = await queueManager.enqueue('execute', { command: ['click', '.button'] });
      
      expect(result.success).toBe(true);
      expect(result.message).toBe('execute command queued');
      expect(result.commandId).toBeDefined();
      expect(queueManager.queue.length).toBe(1);
      expect(queueManager.queue[0].type).toBe('execute');
    });

    it('should generate unique command IDs', async () => {
      const result1 = await queueManager.enqueue('execute', { command: ['click', '.btn1'] });
      const result2 = await queueManager.enqueue('execute', { command: ['click', '.btn2'] });
      
      expect(result1.commandId).not.toBe(result2.commandId);
    });

    it('should not process if not enabled', async () => {
      queueManager.setSession(mockSession);
      await queueManager.enqueue('execute', { command: ['click', '.button'] });
      
      expect(mockSession.executeCommand).not.toHaveBeenCalled();
    });
  });

  describe('processQueue', () => {
    beforeEach(() => {
      queueManager.setSession(mockSession);
      queueManager.startProcessing();
    });

    it('should process execute commands', async () => {
      await queueManager.enqueue('execute', { command: ['click', '.button'] });
      
      // Wait for processing
      await new Promise(resolve => setTimeout(resolve, 100));
      
      expect(mockSession.executeCommand).toHaveBeenCalledWith(['click', '.button']);
      expect(queueManager.queue.length).toBe(0);
      expect(queueManager.completedCommands.length).toBe(1);
    });

    it('should process multiple commands in sequence', async () => {
      await queueManager.enqueue('execute', { command: ['click', '.btn1'] });
      await queueManager.enqueue('execute', { command: ['click', '.btn2'] });
      
      await new Promise(resolve => setTimeout(resolve, 100));
      
      expect(mockSession.executeCommand).toHaveBeenCalledTimes(2);
      expect(mockSession.executeCommand).toHaveBeenNthCalledWith(1, ['click', '.btn1']);
      expect(mockSession.executeCommand).toHaveBeenNthCalledWith(2, ['click', '.btn2']);
    });

    it('should handle command failures', async () => {
      mockSession.executeCommand.mockResolvedValueOnce({ success: false, error: 'Failed' });
      
      await queueManager.enqueue('execute', { command: ['click', '.button'] });
      await new Promise(resolve => setTimeout(resolve, 100));
      
      expect(queueManager.completedCommands[0].status).toBe('completed');
      // Queue manager continues processing even on failures
      expect(queueManager.isEnabled).toBe(true);
    });

    it('should process end command', async () => {
      await queueManager.enqueue('end', {});
      await new Promise(resolve => setTimeout(resolve, 100));
      
      expect(mockSession.end).toHaveBeenCalled();
      expect(queueManager.currentSession).toBeNull();
      expect(queueManager.isEnabled).toBe(false);
    });

    it('should process quick end command', async () => {
      await queueManager.enqueue('end', { quickCleanup: true });
      await new Promise(resolve => setTimeout(resolve, 100));
      
      expect(mockSession.quickEnd).toHaveBeenCalled();
      expect(mockSession.end).not.toHaveBeenCalled();
      expect(queueManager.previousUrl).toBe('https://test.com');
    });
  });

  describe('getStatus', () => {
    it('should return current queue status', () => {
      queueManager.setSession(mockSession);
      queueManager.enqueue('execute', { command: ['click', '.button'] });
      
      const status = queueManager.getStatus();
      
      expect(status.currentState.isProcessing).toBe(false);
      expect(status.currentState.queueLength).toBe(1);
      expect(status.currentState.phase).toBe('idle');
      expect(status.currentState.testId).toBe('test-test');
      expect(status.currentState.clientId).toBe('test-client');
      expect(status.queued.length).toBe(1);
    });

    it('should include session timing info', () => {
      queueManager.setSession(mockSession);
      queueManager.startProcessing();
      
      const status = queueManager.getStatus();
      
      expect(status.currentState.startedAt).toBeDefined();
      expect(status.currentState.secondsRunning).toBeDefined();
    });

    it('should limit completed commands history', () => {
      // Add 60 completed commands
      for (let i = 0; i < 60; i++) {
        queueManager.completedCommands.push({
          type: 'execute',
          status: 'completed',
          queuedAt: new Date().toISOString(),
          payload: { command: ['click', `.button${i}`] }
        });
      }
      
      const status = queueManager.getStatus();
      
      // Should be limited to 50
      expect(queueManager.completedCommands.length).toBe(50);
    });
  });

  describe('setFirebasePhase', () => {
    it('should set firebase phase', () => {
      queueManager.setFirebasePhase('testing', { detail: 'value' });
      
      const status = queueManager.getStatus();
      expect(status.currentState.firebasePhase).toEqual({
        phase: 'testing',
        details: { detail: 'value' }
      });
    });
  });
});