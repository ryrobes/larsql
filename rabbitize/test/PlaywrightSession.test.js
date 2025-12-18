// test/PlaywrightSession.test.js
// First set up the mocks without external references
jest.mock('fs/promises', () => ({
  mkdir: jest.fn().mockResolvedValue(undefined),
  writeFile: jest.fn().mockResolvedValue(undefined),
  copyFile: jest.fn().mockResolvedValue(undefined)
}));

// Mock the metrics module
jest.mock('../src/utils/metrics', () => ({
  getResourceMetrics: jest.fn().mockResolvedValue({
    timestamp: Date.now(),
    jsHeapSize: 1000000,
    jsHeapUsedSize: 800000,
    jsHeapTotalSize: 2000000,
    totalJSHeapSize: 2000000,
    usedJSHeapSize: 800000,
    resourceCount: 10,
    documents: 1,
    frames: 1,
    jsEventListeners: 20,
    nodes: 100,
    layoutCount: 5,
    recalcStyleCount: 3,
    layoutDuration: 0.5,
    recalcStyleDuration: 0.3,
    scriptDuration: 1.0,
    taskDuration: 2.0,
    nodeCount: 100
  })
}));

// Mock playwright
jest.mock('playwright', () => ({
  chromium: {
    launch: jest.fn().mockResolvedValue({
      newContext: jest.fn().mockResolvedValue({
        newPage: jest.fn().mockResolvedValue({
          goto: jest.fn().mockResolvedValue(null),
          evaluate: jest.fn().mockResolvedValue(null),
          waitForTimeout: jest.fn().mockResolvedValue(null),
          mouse: {
            move: jest.fn().mockResolvedValue(null),
            click: jest.fn().mockResolvedValue(null)
          },
          on: jest.fn(),
          url: jest.fn().mockResolvedValue('https://ryrob.es'),
          title: jest.fn().mockResolvedValue('Test Page'),
          screenshot: jest.fn().mockResolvedValue(null)
        })
      }),
      close: jest.fn().mockResolvedValue(null)
    })
  }
}));

const express = require('express');
const request = require('supertest');
const PlaywrightSession = require('../src/PlaywrightSession');
const net = require('net');

// Utility function to get a random available port
const getAvailablePort = () => {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on('error', reject);
    server.listen(0, () => {
      const port = server.address().port;
      server.close(() => {
        resolve(port);
      });
    });
  });
};

jest.mock('../src/PlaywrightSession');

describe('Batch Command Execution', () => {
  let app;
  let server;
  let port;
  let mockSession;

  beforeEach(async () => {
    port = await getAvailablePort();
    app = express();
    app.use(express.json());

    // Create a fresh mock for each test
    mockSession = new PlaywrightSession('test-session', 'test/sessions');

    // Setup mock implementations
    mockSession.initialize = jest.fn().mockResolvedValue({ success: true });
    mockSession.executeCommand = jest.fn().mockImplementation(async (command) => {
      if (command[0] === ':invalid-command') {
        return { success: false, error: 'Invalid command' };
      }
      return { success: true, state: {} };
    });
    mockSession.end = jest.fn().mockResolvedValue({ success: true });

    // Add the endpoints
    app.post('/start', async (req, res) => {
      const result = await mockSession.initialize(req.body.url);
      res.json(result);
    });

    app.post('/execute', async (req, res) => {
      const result = await mockSession.executeCommand(req.body.command);
      res.json(result);
    });

    app.post('/execute-batch', async (req, res) => {
      const { commands } = req.body;
      if (!commands || !Array.isArray(commands)) {
        return res.status(400).json({
          error: 'Invalid commands format',
          details: 'Commands must be an array of command arrays'
        });
      }

      const results = [];
      for (const command of commands) {
        if (!Array.isArray(command)) {
          return res.status(400).json({
            error: 'Invalid command format',
            details: 'Each command must be an array'
          });
        }

        const result = await mockSession.executeCommand(command);
        results.push({ command, ...result });
        if (!result.success) {
          return res.json({
            success: false,
            error: `Batch stopped due to command failure: ${result.error}`,
            completedCommands: results
          });
        }
      }
      res.json({ success: true, results });
    });

    app.post('/end', async (req, res) => {
      const result = await mockSession.end();
      res.json(result);
    });

    server = app.listen(port);
  });

  afterEach(async () => {
    await new Promise(resolve => server.close(resolve));
    jest.clearAllMocks();
  });

  it('should execute a batch of commands successfully', async () => {
    // Start session
    await request(app)
      .post('/start')
      .send({ url: 'https://ryrob.es' })
      .expect(200);

    // Execute batch of commands
    const response = await request(app)
      .post('/execute-batch')
      .send({
        commands: [
          [':move-mouse', ':to', 100, 200],
          [':click'],
          [':wait', 1]
        ]
      })
      .expect(200);

    expect(response.body.success).toBe(true);
    expect(response.body.results).toHaveLength(3);
    expect(response.body.results[0].command).toEqual([':move-mouse', ':to', 100, 200]);
    expect(response.body.results[1].command).toEqual([':click']);
    expect(response.body.results[2].command).toEqual([':wait', 1]);
    expect(mockSession.executeCommand).toHaveBeenCalledTimes(3);
  });

  it('should handle invalid batch format', async () => {
    await request(app)
      .post('/execute-batch')
      .send({ commands: 'not-an-array' })
      .expect(400)
      .expect(res => {
        expect(res.body.error).toBe('Invalid commands format');
      });
  });

  it('should handle invalid command format in batch', async () => {
    await request(app)
      .post('/execute-batch')
      .send({
        commands: [
          [':move-mouse', ':to', 100, 200],
          'not-an-array'
        ]
      })
      .expect(400)
      .expect(res => {
        expect(res.body.error).toBe('Invalid command format');
      });
  });

  it('should stop batch execution on first failure', async () => {
    // Start session
    await request(app)
      .post('/start')
      .send({ url: 'https://ryrob.es' })
      .expect(200);

    // Execute batch with invalid command
    const response = await request(app)
      .post('/execute-batch')
      .send({
        commands: [
          [':move-mouse', ':to', 100, 200],
          [':invalid-command'],
          [':wait', 1]
        ]
      })
      .expect(200);

    expect(response.body.success).toBe(false);
    expect(response.body.completedCommands).toHaveLength(2);
    expect(response.body.error).toContain('Batch stopped due to command failure');
    expect(mockSession.executeCommand).toHaveBeenCalledTimes(2);
  });

  it('should work alongside single command execution', async () => {
    // Start session
    await request(app)
      .post('/start')
      .send({ url: 'https://ryrob.es' })
      .expect(200);

    // Execute single command
    await request(app)
      .post('/execute')
      .send({ command: [':move-mouse', ':to', 100, 200] })
      .expect(200);

    // Execute batch
    const batchResponse = await request(app)
      .post('/execute-batch')
      .send({
        commands: [
          [':click'],
          [':wait', 1]
        ]
      })
      .expect(200);

    expect(batchResponse.body.success).toBe(true);
    expect(batchResponse.body.results).toHaveLength(2);

    // Execute another single command
    await request(app)
      .post('/execute')
      .send({ command: [':move-mouse', ':to', 300, 400] })
      .expect(200);

    // Verify total number of commands executed
    expect(mockSession.executeCommand).toHaveBeenCalledTimes(4);
  });
});