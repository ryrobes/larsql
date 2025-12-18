const request = require('supertest');
const express = require('express');

describe('API Endpoints', () => {
  let app;
  let mockQueueManager;
  let mockSession;

  beforeEach(() => {
    // Create a fresh Express app
    app = express();
    app.use(express.json());

    // Mock session
    mockSession = {
      clientId: 'test-client',
      testId: 'test-test',
      firebase: {
        log: jest.fn(),
        error: jest.fn(),
        warn: jest.fn()
      },
      initialize: jest.fn().mockResolvedValue({ success: true, sessionId: 'test-123' }),
      executeCommand: jest.fn().mockResolvedValue({ success: true }),
      end: jest.fn().mockResolvedValue({ success: true })
    };

    // Mock queue manager
    mockQueueManager = {
      setSession: jest.fn(),
      startProcessing: jest.fn(),
      enqueue: jest.fn().mockResolvedValue({ success: true, message: 'Queued' }),
      getStatus: jest.fn().mockReturnValue({
        currentState: {
          isProcessing: false,
          queueLength: 0,
          phase: 'idle'
        },
        queued: [],
        recentlyCompleted: []
      })
    };

    // Set up global mocks
    global.currentPlaywrightSession = mockSession;
  });

  afterEach(() => {
    delete global.currentPlaywrightSession;
    jest.clearAllMocks();
  });

  describe('POST /execute-batch', () => {
    beforeEach(() => {
      // Add the execute-batch endpoint
      app.post('/execute-batch', async (req, res) => {
        try {
          const { commands } = req.body;
          if (!commands || !Array.isArray(commands)) {
            return res.status(400).json({
              error: 'Invalid commands format',
              details: 'Commands must be an array of command arrays'
            });
          }

          // Validate each command in the batch
          for (const command of commands) {
            if (!Array.isArray(command)) {
              return res.status(400).json({
                error: 'Invalid command format',
                details: 'Each command must be an array'
              });
            }
          }

          // Queue each command
          for (const command of commands) {
            await mockQueueManager.enqueue('execute', { command });
          }

          res.json({
            success: true,
            message: `Queued ${commands.length} commands for execution`,
            queuedCommands: commands.length
          });

        } catch (error) {
          res.status(500).json({
            success: false,
            error: error.message
          });
        }
      });
    });

    it('should queue multiple commands successfully', async () => {
      const commands = [
        ['click', '.button1'],
        ['wait', 2],
        ['type', '#input', 'test text']
      ];

      const response = await request(app)
        .post('/execute-batch')
        .send({ commands });

      expect(response.status).toBe(200);
      expect(response.body.success).toBe(true);
      expect(response.body.queuedCommands).toBe(3);
      expect(mockQueueManager.enqueue).toHaveBeenCalledTimes(3);
    });

    it('should validate commands is an array', async () => {
      const response = await request(app)
        .post('/execute-batch')
        .send({ commands: 'not-an-array' });

      expect(response.status).toBe(400);
      expect(response.body.error).toBe('Invalid commands format');
    });

    it('should validate each command is an array', async () => {
      const response = await request(app)
        .post('/execute-batch')
        .send({ 
          commands: [
            ['click', '.button'],
            'not-an-array'
          ]
        });

      expect(response.status).toBe(400);
      expect(response.body.details).toBe('Each command must be an array');
    });

    it('should handle empty commands array', async () => {
      const response = await request(app)
        .post('/execute-batch')
        .send({ commands: [] });

      expect(response.status).toBe(200);
      expect(response.body.queuedCommands).toBe(0);
      expect(mockQueueManager.enqueue).not.toHaveBeenCalled();
    });
  });

  describe('GET /status', () => {
    beforeEach(() => {
      app.get('/status', async (req, res) => {
        const status = mockQueueManager.getStatus();
        status.heartbeat = Date.now();
        status.hasSession = !!global.currentPlaywrightSession;
        status.pid = process.pid;
        
        res.json(status);
      });
    });

    it('should return current status', async () => {
      const response = await request(app)
        .get('/status');

      expect(response.status).toBe(200);
      expect(response.body.heartbeat).toBeDefined();
      expect(response.body.hasSession).toBe(true);
      expect(response.body.pid).toBe(process.pid);
      expect(response.body.currentState).toBeDefined();
    });

    it('should show no session when none exists', async () => {
      delete global.currentPlaywrightSession;
      
      const response = await request(app)
        .get('/status');

      expect(response.body.hasSession).toBe(false);
    });
  });

  describe('POST /reset', () => {
    beforeEach(() => {
      app.post('/reset', async (req, res) => {
        const { clientId, testId } = req.body;

        if (!clientId || !testId) {
          return res.status(400).json({
            success: false,
            error: 'Client ID and Test ID are required'
          });
        }

        const session = global.currentPlaywrightSession;
        if (!session) {
          return res.status(400).json({
            success: false,
            error: 'No active session'
          });
        }

        // Mock reset functionality
        session.clientId = clientId;
        session.testId = testId;

        res.json({
          success: true,
          message: 'Session reset successfully',
          sessionId: 'new-session-id'
        });
      });
    });

    it('should reset session with new IDs', async () => {
      const response = await request(app)
        .post('/reset')
        .send({ 
          clientId: 'new-client',
          testId: 'new-test'
        });

      expect(response.status).toBe(200);
      expect(response.body.success).toBe(true);
      expect(mockSession.clientId).toBe('new-client');
      expect(mockSession.testId).toBe('new-test');
    });

    it('should require both client and test IDs', async () => {
      const response = await request(app)
        .post('/reset')
        .send({ clientId: 'new-client' });

      expect(response.status).toBe(400);
      expect(response.body.error).toBe('Client ID and Test ID are required');
    });

    it('should fail if no active session', async () => {
      delete global.currentPlaywrightSession;
      
      const response = await request(app)
        .post('/reset')
        .send({ 
          clientId: 'new-client',
          testId: 'new-test'
        });

      expect(response.status).toBe(400);
      expect(response.body.error).toBe('No active session');
    });
  });
});