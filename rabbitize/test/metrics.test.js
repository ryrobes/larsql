// test/metrics.test.js
const { getResourceMetrics } = require('../src/utils/metrics');

describe('Resource Metrics', () => {
  const mockPage = {
    context: () => ({
      newCDPSession: () => ({
        send: jest.fn().mockResolvedValue({
          metrics: [
            { name: 'ScriptDuration', value: 0.1 },
            { name: 'TaskDuration', value: 0.2 }
          ]
        })
      })
    }),
    evaluate: jest.fn().mockResolvedValue({
      usedJSHeapSize: 1000000,
      totalJSHeapSize: 2000000,
      jsHeapSizeLimit: 4000000
    })
  };

  test('returns structured metrics object', async () => {
    const metrics = await getResourceMetrics(mockPage);
    expect(metrics).toHaveProperty('memory');
    expect(metrics).toHaveProperty('cpu');
    expect(metrics).toHaveProperty('timestamp');
  });
});

