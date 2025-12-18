const { StabilityDetector } = require('../src/stability');
const CircularBuffer = require('../src/stability/CircularBuffer');

describe('StabilityDetector', () => {
  let mockPage;
  let detector;
  let options;

  beforeEach(() => {
    // Create a minimal valid 1x1 pixel PNG buffer using base64
    // This is a known-good 1x1 transparent PNG
    const validPngBuffer = Buffer.from(
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==',
      'base64'
    );

    // Mock Playwright page
    mockPage = {
      screenshot: jest.fn().mockResolvedValue(validPngBuffer)
    };

    // Default options
    options = {
      enabled: true,
      waitTime: 2,
      sensitivity: 0.5,
      timeout: 10,
      interval: 500,
      frameCount: 4,
      downscaleWidth: 100
    };

    detector = new StabilityDetector(mockPage, options);
  });

  describe('constructor', () => {
    it('should initialize with provided options', () => {
      expect(detector.options).toEqual(options);
      expect(detector.isRunning).toBe(false);
      expect(detector.screenshots).toBeInstanceOf(CircularBuffer);
    });

    it('should calculate buffer size from frameCount', () => {
      const customDetector = new StabilityDetector(mockPage, { ...options, frameCount: 10 });
      expect(customDetector.screenshots.size).toBe(10);
    });
  });

  describe('start/stop', () => {
    it('should start and stop detection', async () => {
      await detector.start();
      expect(detector.isRunning).toBe(true);
      expect(detector.screenshotInterval).toBeDefined();

      await detector.stop();
      expect(detector.isRunning).toBe(false);
      expect(detector.screenshotInterval).toBeNull();
    });

    it('should not start if already running', async () => {
      await detector.start();
      const interval1 = detector.screenshotInterval;
      
      await detector.start();
      const interval2 = detector.screenshotInterval;
      
      expect(interval1).toBe(interval2);
    });
  });

  describe('isDisabled', () => {
    it('should return true if not enabled', () => {
      const disabledDetector = new StabilityDetector(mockPage, { ...options, enabled: false });
      expect(disabledDetector.options.enabled).toBe(false);
    });

    it('should return false if enabled', () => {
      expect(detector.options.enabled).toBe(true);
    });
  });
});

describe('CircularBuffer', () => {
  let buffer;

  beforeEach(() => {
    buffer = new CircularBuffer(3);
  });

  describe('push', () => {
    it('should add items to buffer', () => {
      buffer.push('a');
      buffer.push('b');
      
      expect(buffer.getLength()).toBe(2);
      expect(buffer.getRecent(2)).toEqual(['b', 'a']);
    });

    it('should overwrite oldest item when full', () => {
      buffer.push('a');
      buffer.push('b');
      buffer.push('c');
      buffer.push('d'); // Should overwrite 'a'
      
      expect(buffer.getLength()).toBe(3);
      expect(buffer.getRecent(3)).toEqual(['d', 'c', 'b']);
    });
  });

  describe('clear', () => {
    it('should empty the buffer', () => {
      buffer.push('a');
      buffer.push('b');
      buffer.clear();
      
      expect(buffer.getLength()).toBe(0);
      expect(buffer.getRecent(1)).toEqual([undefined]);
    });
  });

  describe('getRecent', () => {
    it('should retrieve recent items in reverse order', () => {
      buffer.push('a');
      buffer.push('b');
      buffer.push('c');
      
      expect(buffer.getRecent(1)).toEqual(['c']);
      expect(buffer.getRecent(2)).toEqual(['c', 'b']);
      expect(buffer.getRecent(3)).toEqual(['c', 'b', 'a']);
    });

    it('should handle request for more items than available', () => {
      buffer.push('a');
      
      expect(buffer.getRecent(3)).toEqual(['a', undefined, undefined]);
    });
  });

  describe('isFull', () => {
    it('should return false when not full', () => {
      buffer.push('a');
      expect(buffer.isFull()).toBe(false);
    });

    it('should return true when full', () => {
      buffer.push('a');
      buffer.push('b');
      buffer.push('c');
      expect(buffer.isFull()).toBe(true);
    });
  });

});