const CircularBuffer = require('./CircularBuffer');
const { processScreenshot, compareScreenshots, getImageDimensions } = require('./imageComparison');
const chalk = require('chalk');
const sharp = require('sharp');

class StabilityDetector {
  /**
   * @param {import('playwright').Page} page - Playwright page instance
   * @param {import('./types').StabilityOptions} options - Configuration options
   */
  constructor(page, options = {}) {
    this.page = page;
    // Use passed options directly since defaults are handled by CLI args
    this.options = options;

    this.isRunning = false;
    this.lastChangeTime = Date.now();
    this.screenshotInterval = null;
    this.consecutiveFailures = 0;
    this.maxConsecutiveFailures = 5;
    this.screenshotInProgress = false;
    this.lastCaptureTime = 0; // Track last successful capture
    this.stabilityCheckInProgress = false; // Track if we're checking stability
    this.lastFrameCheckTime = 0; // Track when we last checked frames

    // Calculate buffer size based on frameCount
    const bufferSize = Math.max(this.options.frameCount, 2);
    this.screenshots = new CircularBuffer(bufferSize);

    // Track dimensions of processed images
    this.processedWidth = this.options.downscaleWidth;
    this.processedHeight = null;

    console.log(chalk.magenta('🐴 Stability:  Initialized with options:', JSON.stringify({
      enabled: this.options.enabled,
      waitTime: this.options.waitTime,
      sensitivity: this.options.sensitivity,
      timeout: this.options.timeout,
      interval: this.options.interval,
      frameCount: this.options.frameCount,
      downscaleWidth: this.options.downscaleWidth
    })));
  }

  /**
   * Start the stability detection process
   */
  async start() {
    if (this.isRunning) return;
    console.log(chalk.magenta('🐴 Stability:  Starting detection process'));
    this.isRunning = true;

    // Take initial screenshot to get dimensions
    const initialShot = await this.page.screenshot({ type: 'jpeg' });
    const dimensions = await getImageDimensions(initialShot);

    // Calculate new height maintaining aspect ratio
    this.processedHeight = Math.round(
      (dimensions.height * this.processedWidth) / dimensions.width
    );

    console.log(chalk.magenta('🐴 Stability:  Initial dimensions:', JSON.stringify({
      originalWidth: dimensions.width,
      originalHeight: dimensions.height,
      processedWidth: this.processedWidth,
      processedHeight: this.processedHeight
    })));

    // Process and store initial screenshot
    const processed = await processScreenshot(initialShot, this.processedWidth);

    // We already know the processed dimensions from the sharp resize operation
    // No need to verify them again since sharp guarantees these dimensions
    this.screenshots.push(processed);
    this.startScreenshotLoop();
  }

  /**
   * Stop the stability detection process
   */
  async stop() {
    console.log(chalk.magenta('🐴 Stability:  Stopping detection process'));
    this.isRunning = false;
    if (this.screenshotInterval) {
      clearInterval(this.screenshotInterval);
      this.screenshotInterval = null;
    }
    this.screenshots.clear();
    this.consecutiveFailures = 0;
    this.screenshotInProgress = false;
    this.stabilityCheckInProgress = false;

    // Wait for any in-progress operations to complete
    const waitStart = Date.now();
    while (this.screenshotInProgress && Date.now() - waitStart < 1000) {
      await new Promise(resolve => setTimeout(resolve, 50));
    }

    // Final cleanup
    this.screenshots.clear();
    this.lastCaptureTime = Date.now();
    console.log(chalk.magenta('🐴 Stability:  Detection process stopped'));
  }

  /**
   * Handle fatal error - stops detection, logs error, and terminates process
   * @private
   */
  async handleFatalError(error) {
    console.error(chalk.magenta('🐴 Stability:  Fatal error encountered:', JSON.stringify({
      error: error.message,
      stack: error.stack,
      time: new Date().toISOString()
    })));

    try {
      // Try to clean up gracefully
      await this.stop();
      console.error(chalk.magenta('🐴 Stability:  ⚠️ Stability check failed but continuing'));

      // Give a small delay for logs to flush
      await new Promise(resolve => setTimeout(resolve, 500));
    } catch (cleanupError) {
      // If cleanup fails, just log it
      console.error(chalk.magenta('🐴 Stability:  Cleanup failed during error:', JSON.stringify({
        cleanupError: cleanupError.message,
        originalError: error.message
      })));
    }
  }

  /**
   * Wait for the page to stabilize
   * @throws {Error} If timeout is exceeded or fatal error occurs
   */
  async waitForStability() {
    if (!this.isRunning) {
      console.log(chalk.magenta('🐴 Stability:  Not running, starting detection'));
      await this.start();
    }

    this.stabilityCheckInProgress = true;
    // console.log(chalk.magenta('🐴 Stability:  Starting stability check'));

    const startTime = Date.now();
    const timeoutMs = this.options.timeout * 1000;
    let lastFrameTime = startTime;
    let stableFrameCount = 0;
    let lastCheckedFrameCount = 0;
    let noProgressCount = 0;
    let lastProgressTime = Date.now();
    const maxNoProgress = 10;
    const progressTimeoutMs = this.options.interval * 3;

    try {
      while (true) {
        // Check if we're still running (might be stopped due to command failure)
        if (!this.isRunning) {
          throw new Error('Stability detection stopped due to command failure');
        }

        const elapsedMs = Date.now() - startTime;
        const timeSinceProgress = Date.now() - lastProgressTime;

        // Check timeout - but don't terminate, just warn and return
        if (elapsedMs > timeoutMs) {
          console.log(chalk.yellow('🐴 Stability:  Timeout exceeded - proceeding anyway:', JSON.stringify({
            elapsed: elapsedMs,
            timeout: timeoutMs,
            stableFrames: stableFrameCount,
            totalFrames: this.screenshots.getLength()
          })));
          return true; // Return success to allow command to continue
        }

        // Check if we have at least 2 frames to compare
        if (this.screenshots.getLength() >= 2) {
          const recentFrames = this.screenshots.getRecent(2);
          const timeSinceLastCheck = Date.now() - this.lastFrameCheckTime;

          // Only do comparison if enough time has passed
          if (timeSinceLastCheck >= this.options.interval) {
            this.lastFrameCheckTime = Date.now();
            lastProgressTime = Date.now();

            try {
              const hasDiff = await compareScreenshots(
                recentFrames[0],
                recentFrames[1],
                recentFrames[0].width,
                recentFrames[0].height,
                this.options.sensitivity
              );

              if (hasDiff) {
                // console.log(chalk.magenta('🐴 Stability:  Detected change in frames:', JSON.stringify({
                //   elapsedMs,
                //   stableFrameCount,
                //   totalFrames: this.screenshots.getLength()
                // })));
                stableFrameCount = 0;
                lastFrameTime = Date.now();
                lastProgressTime = Date.now();
              } else {
                stableFrameCount++;
                lastFrameTime = Date.now();
                lastProgressTime = Date.now();
                // console.log(chalk.magenta('🐴 Stability:  Frame stable:', JSON.stringify({
                //   stableFrameCount,
                //   needed: this.options.frameCount,
                //   elapsedMs,
                //   timeSinceLastCheck
                // })));

                if (stableFrameCount >= this.options.frameCount) {
                  console.log(chalk.black.bgHex('#fc0fc0').bold('🎠 Stability:  STABILITY ACHIEVED:', JSON.stringify({
                    elapsedMs,
                    stableFrames: stableFrameCount,
                    averageInterval: elapsedMs / stableFrameCount
                  })));

                  // Wait for any in-progress captures to complete
                  const waitStart = Date.now();
                  while (this.screenshotInProgress && Date.now() - waitStart < 1000) {
                    await new Promise(resolve => setTimeout(resolve, 50));
                  }

                  // Clear the buffer and pause captures briefly
                  this.screenshots.clear();
                  this.lastCaptureTime = Date.now();

                  // Ensure we've fully cleaned up before returning
                  await new Promise(resolve => setTimeout(resolve, Math.min(200, this.options.interval / 2)));
                  return true;
                }
              }
            } catch (error) {
              console.error(chalk.magenta('🐴 Stability:  Comparison failed:', JSON.stringify({
                error: error.message,
                stack: error.stack
              })));
              throw error;
            }
          }
        } else {
          // console.log(chalk.magenta('🐴 Stability:  Waiting for more frames:', JSON.stringify({
          //   current: this.screenshots.getLength(),
          //   needed: 2,
          //   stableFrameCount,
          //   requiredStableFrames: this.options.frameCount,
          //   elapsedMs,
          //   timeSinceProgress
          // })));
        }

        // Check if we're making progress in getting frames
        if (this.screenshots.getLength() === lastCheckedFrameCount) {
          if (timeSinceProgress >= progressTimeoutMs) {
            noProgressCount++;
            if (noProgressCount >= maxNoProgress) {
              console.log(chalk.yellow('🐴 Stability:  No progress in getting new frames - proceeding anyway:', JSON.stringify({
                frameCount: this.screenshots.getLength(),
                noProgressIntervals: noProgressCount,
                timeSinceProgress,
                elapsedMs
              })));
              // Don't throw error - just proceed like timeout
              return true; // Return success to allow command to continue
            }
          }
        } else {
          noProgressCount = 0;
          lastProgressTime = Date.now();
          // console.log(chalk.magenta('🐴 Stability:  Progress detected:', JSON.stringify({
          //   previousFrames: lastCheckedFrameCount,
          //   currentFrames: this.screenshots.getLength(),
          //   timeSinceLastProgress: timeSinceProgress
          // })));
        }
        lastCheckedFrameCount = this.screenshots.getLength();

        // Use a shorter wait time to check more frequently
        await new Promise(resolve => setTimeout(resolve, Math.min(100, this.options.interval / 2)));
      }
    } finally {
      // Ensure we've fully cleaned up
      this.stabilityCheckInProgress = false;
      // console.log(chalk.magenta('🐴 Stability:  Stability check completed'));

      // Wait for any pending operations to complete
      await new Promise(resolve => setTimeout(resolve, Math.min(100, this.options.interval / 2)));
    }
  }

  /**
   * Start the screenshot capture loop
   * @private
   */
  startScreenshotLoop() {
    if (this.screenshotInterval) {
      clearInterval(this.screenshotInterval);
    }

    const captureWithBackoff = async () => {
      // Skip if not running or if we've hit a fatal error
      if (!this.isRunning) {
        console.log(chalk.magenta('🐴 Stability:  Screenshot loop stopped'));
        if (this.screenshotInterval) {
          clearInterval(this.screenshotInterval);
          this.screenshotInterval = null;
        }
        return;
      }

      const timeSinceLastCapture = Date.now() - this.lastCaptureTime;
      if (this.screenshotInProgress ||
          timeSinceLastCapture < this.options.interval) {
        // console.log(chalk.magenta('🐴 Stability:  Skipping screenshot:', JSON.stringify({
        //   reason: this.screenshotInProgress ? 'capture in progress' : 'interval not elapsed',
        //   timeSinceLastCapture,
        //   requiredInterval: this.options.interval
        // })));
        return;
      }

      try {
        this.screenshotInProgress = true;
        //console.log(chalk.magenta('🐴 Stability:  Starting screenshot capture'));

        // Add a small random delay to reduce conflicts with main screenshot process
        await new Promise(resolve => setTimeout(resolve, Math.random() * 50));

        const screenshot = await this.page.screenshot({
          type: 'jpeg',
          timeout: 5000
        });
        const processed = await processScreenshot(screenshot, this.processedWidth);
        this.screenshots.push(processed);
        this.lastCaptureTime = Date.now();

        // console.log(chalk.magenta('🐴 Stability:  Captured new frame:', JSON.stringify({
        //   bufferSize: this.screenshots.getLength(),
        //   timestamp: this.lastCaptureTime,
        //   timeSinceLastCapture
        // })));

        this.consecutiveFailures = 0;
      } catch (error) {
        this.consecutiveFailures++;
        console.error(chalk.magenta('🐴 Stability:  Screenshot capture failed:', error));

        if (this.consecutiveFailures >= this.maxConsecutiveFailures) {
          console.error(chalk.yellow(`🐴 Stability:  Too many consecutive screenshot failures (${this.consecutiveFailures}), but continuing anyway`));
          // Don't call handleFatalError - just reset and continue
          this.consecutiveFailures = 0;
          this.screenshotInProgress = false;
          return;
        }

        const backoffMs = Math.min(1000 * Math.pow(2, this.consecutiveFailures - 1), 10000);
        console.log(chalk.magenta('🐴 Stability:  Applying backoff before retry:', JSON.stringify({
          backoffMs,
          consecutiveFailures: this.consecutiveFailures
        })));
        await new Promise(resolve => setTimeout(resolve, backoffMs));
      } finally {
        this.screenshotInProgress = false;
      }
    };

    // Check more frequently but respect the capture interval
    const checkInterval = Math.max(100, Math.floor(this.options.interval / 2));
    this.screenshotInterval = setInterval(captureWithBackoff, checkInterval);
    console.log(chalk.magenta('🐴 Stability:  Started screenshot loop:', JSON.stringify({
      checkInterval,
      captureInterval: this.options.interval
    })));
  }
}

module.exports = StabilityDetector;