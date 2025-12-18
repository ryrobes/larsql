const request = require('supertest');
const express = require('express');
const PlaywrightSession = require('../src/PlaywrightSession');
const http = require('http');
const fs = require('fs');

// Mock PlaywrightSession
jest.mock('../src/PlaywrightSession');

describe('Server', () => {
  let app;
  let server;
  let session;
  let mockSession;
  let mockFirebase;

  beforeEach(async () => {
    // Clear all mocks
    jest.clearAllMocks();

    // Setup mock implementation with more realistic behavior
    PlaywrightSession.mockImplementation(() => ({
      initialized: false,
      initialize: jest.fn().mockImplementation(() => {
        this.initialized = true;
        return Promise.resolve({ success: true, sessionId: 'test-123' });
      }),
      executeCommand: jest.fn().mockImplementation(() => {
        return Promise.resolve({
          success: false,
          error: 'Session not initialized'
        });
      }),
      end: jest.fn().mockImplementation(() => {
        return Promise.resolve({ success: false });
      }),
      browser: null,
      idleTimer: null
    }));

    app = express();
    app.use(express.json());

    session = new PlaywrightSession('test-123', 'test-sessions', {
      showCommandOverlay: true
    });

    app.post('/start', async (req, res) => {
      try {
        const { url } = req.body;
        const result = await session.initialize(url);
        res.json(result);
      } catch (error) {
        res.status(500).json({ error: error.message });
      }
    });

    app.post('/execute', async (req, res) => {
      try {
        const { command } = req.body;
        const result = await session.executeCommand(command);
        res.json(result);
      } catch (error) {
        res.status(500).json({ error: error.message });
      }
    });

    app.post('/end', async (req, res) => {
      try {
        const result = await session.end();
        res.json(result);
      } catch (error) {
        res.status(500).json({ error: error.message });
      }
    });

    server = http.createServer(app);
    await new Promise(resolve => {
      server.listen(0, () => resolve());
    });

    // Mock Firebase
    mockFirebase = {
      log: jest.fn(),
      error: jest.fn(),
      setSessionType: jest.fn(),
      setRunningState: jest.fn(),
      saveCommandResult: jest.fn()
    };

    // Mock PlaywrightSession
    mockSession = {
      initialize: jest.fn().mockResolvedValue({ success: true }),
      executeCommand: jest.fn().mockResolvedValue({ success: true }),
      end: jest.fn().mockResolvedValue({ success: true }),
      firebase: mockFirebase
    };
  });

  afterEach(async () => {
    if (server && server.listening) {
      await new Promise((resolve) => server.close(resolve));
    }
  });

  test('POST /start initializes session', async () => {
    const response = await request(app)
      .post('/start')
      .send({ url: 'https://rvbbit.com' });

    expect(response.statusCode).toBe(200);
    expect(response.body).toHaveProperty('sessionId');
    expect(response.body.success).toBe(true);
  });

  test('POST /execute fails without session', async () => {
    const response = await request(server)
      .post('/execute')
      .send({ command: [':move-mouse', ':to', 100, 200] });

    expect(response.status).toBe(200);
    expect(response.body.success).toBe(false);
    expect(response.body.error).toBe('Session not initialized');
  });

  test('POST /end fails without session', async () => {
    const response = await request(server)
      .post('/end')
      .send({});

    expect(response.status).toBe(200);
    expect(response.body.success).toBe(false);
  });

  // Batch Mode tests removed - Firebase batch loading no longer supported
});