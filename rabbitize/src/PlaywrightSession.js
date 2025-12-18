// src/PlaywrightSession.js
const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');           // Regular fs for sync operations
const fsPromises = require('fs').promises;  // Promise-based fs for async operations
const { getResourceMetrics, writeStepMetric, writeBrowserDurationMetric } = require('./utils/metrics');
const DEFAULT_CONFIG = require('./utils/config');
const { exec } = require('child_process');
const util = require('util');
const execAsync = util.promisify(exec);
const FirestoreManager = require('./utils/firestoreUtils');
const Logger = require('./utils/logger');
const queueManager = require('./utils/queueManager');
const { quickEnd } = require('./sessionManagement/endSession');
const figlet = require('figlet');
const chalk = require('chalk');
const { spawn } = require('child_process');
const crypto = require('crypto');
const sharp = require('sharp');  // We'll need to add this dependency
const os = require('os');  // Added os require at the top

// Use require for node-fetch to avoid Jest issues
let fetch;
try {
  fetch = require('node-fetch');
} catch (err) {
  // Handle if node-fetch is not available
  console.error('Failed to load node-fetch:', err);
}

// Add at the top with other imports
const { StabilityDetector } = require('./stability');

process.on('SIGTERM', async () => {
  console.log('Received SIGTERM signal - attempting graceful shutdown...');
  try {
    const currentInstance = global.currentPlaywrightSession;
    if (currentInstance && currentInstance.firebase) {
      const terminationDetails = {
        reason: 'Process terminated (SIGTERM)',
        timestamp: Date.now(),
        lastCommand: currentInstance.commandCounter,
        memoryUsage: process.memoryUsage(),
        processUptime: process.uptime()
      };

      const basePath = currentInstance.firebase.getBasePath();
      // Log termination details locally
      console.log('Session terminated by SIGTERM signal', terminationDetails);
    }
  } catch (error) {
    console.error('Error during SIGTERM shutdown:', error);
  } finally {
    process.exit(1);
  }
});

process.on('SIGINT', async () => {
  console.log('Received SIGINT signal - attempting graceful shutdown...');
  try {
    const currentInstance = global.currentPlaywrightSession;
    if (currentInstance && currentInstance.firebase) {
      const terminationDetails = {
        reason: 'Process terminated (SIGINT)',
        timestamp: Date.now(),
        lastCommand: currentInstance.commandCounter,
        memoryUsage: process.memoryUsage(),
        processUptime: process.uptime()
      };

      const basePath = currentInstance.firebase.getBasePath();
      // Log termination details locally
      console.log('Session terminated by SIGINT signal', terminationDetails);
    }
  } catch (error) {
    console.error('Error during SIGINT shutdown:', error);
  } finally {
    process.exit(1);
  }
});



// Load and display the ANSI art
try {
  const ansiArt = fs.readFileSync(path.join(__dirname, '..', 'resources', '80masks.ansi'), 'utf8');
  // Convert escaped ANSI codes to actual ANSI escape sequences
  const processedArt = ansiArt.replace(/\\e/g, '\x1b');
  console.log(processedArt);
} catch (err) {
  // Silently ignore if file doesn't exist
}

console.log(chalk.magenta(figlet.textSync('RABBITIZE RUNNER', {
  font: 'Standard',
  horizontalLayout: 'default',
  verticalLayout: 'default'
})));

console.log(chalk.cyan('Using Playwright v'), require('playwright/package.json').version);


class PlaywrightSession {
  constructor(sessionId = null, basePath = '', options = {}) {
    global.currentPlaywrightSession = this;

    // Add debug logging for overlay settings
    // console.log('\n[DEBUG] PlaywrightSession constructor:');
    // console.log('options.showCommandOverlay:', options.showCommandOverlay);
    // console.log('options.showOverlay:', options.showOverlay);
    // console.log('global.argv?.showOverlay:', global.argv?.showOverlay);

    if (!options.clientId || !options.testId) {
      throw new Error('Client ID and Test ID are required');
    }

    // Store the passed sessionId for later use
    this.passedSessionId = sessionId;

    // Add commandCounter initialization
    this.commandCounter = 0;  // Initialize at 0
    this.processStartTime = Date.now();  // Add process start time tracking
    this.startTime = Date.now();  // Session start time
    this.currentCommand = null;  // Track current executing command
    this.errors = [];  // Track any errors
    this.commandHistory = [];  // Track all executed commands

    // Store basic info but don't create session ID yet
    this.clientId = options.clientId;
    this.testId = options.testId;
    this.batchCommands = options.batchCommands;
    this.batchJson = options.batchJson;

    // Track temporary session IDs for cleanup
    this.temporarySessionIds = new Set();
    
    // File handling configuration
    this.downloadPath = null;
    this.uploadFilePath = null;
    this.fileChooserPromise = null;

    // Store configuration but don't set up paths yet
    this.showCommandOverlay = options.showCommandOverlay ?? true;

    // Add debug logging after setting showCommandOverlay
    // console.log('[DEBUG] Final showCommandOverlay value:', this.showCommandOverlay);

    // Update this line to check global.argv.clipSegments first
    this.createClipSegments = global.argv?.clipSegments ?? options.createClipSegments ?? false;
    this.commandTimestamps = [];
    this.currentMouseX = undefined;
    this.currentMouseY = undefined;
    this.metricsInterval = null;
    this.metricsLog = [];
    this.colorPatterns = new Map();
    this.firebaseEnabled = false;  // Always false now
    this.firebase = options.firebase || null;  // Accept logger from options
    this.screenshotInterval = null;
    this.enableLiveScreenshots = options.enableLiveScreenshots ?? true;
    this.inactivityTimeout = null;
    this.INACTIVITY_LIMIT = 15 * 60 * 1000;
    this.zoomFactor = 6.0;
    this.zoomWindowSize = 300;
    this.currentPhase = null;

    // Store the original options for later
    this.originalBatchJson = options.batchJson || null;

    // Extract total commands from batchJson if available
    if (this.originalBatchJson) {
      if (Array.isArray(this.originalBatchJson)) {
        this.totalCommands = this.originalBatchJson.length;
      } else if (this.originalBatchJson.commands) {
        this.totalCommands = this.originalBatchJson.commands.length;
      }
    }

    // Don't initialize anything database-related until we know the session type
    this._sessionId = null;
    this.firebase = null;
    this.firestore = null;
    this.basePath = null;
    this.screenshotsPath = null;
    this.videoPath = null;
    this.domSnapshotsPath = null;
    this.initialized = false;

    this.executedCommands = [];
    this.initialUrl = null;

    // Buffer for early logs
    this.earlyLogs = [];

    // Add stability detector configuration
    this.stabilityOptions = {
      enabled: options.stability?.enabled ?? global.argv['stability-detection'],
      waitTime: options.stability?.waitTime ?? global.argv['stability-wait'],
      sensitivity: options.stability?.sensitivity ?? global.argv['stability-sensitivity'],
      timeout: options.stability?.timeout ?? global.argv['stability-timeout'],
      interval: options.stability?.interval ?? global.argv['stability-interval'],
      // Calculate frameCount based on waitTime and interval
      frameCount: Math.ceil(((options.stability?.waitTime ?? global.argv['stability-wait']) * 1000) / (options.stability?.interval ?? global.argv['stability-interval'])),
      downscaleWidth: options.stability?.downscaleWidth ?? 1000 // Keep hardcoded since not in CLI
    };

    // Counter for stability timeouts - used to auto-disable after threshold
    this.stabilityTimeoutCount = 0;
    this.stabilityTimeoutThreshold = options.stability?.timeoutThreshold ?? global.argv?.['stability-timeout-threshold'] ?? 1; // Auto-disable after this many consecutive timeouts

    console.log('🐴 Stability:  PlaywrightSession initialized with options:', {
      ...this.stabilityOptions,
      timeoutThreshold: this.stabilityTimeoutThreshold
    });

    this.stabilityDetector = null;

    // Track if session has fully completed (including post-processing)
    this.isFullyComplete = false;
  }

  // Add getter/setter for sessionId
  get sessionId() {
    return this._sessionId || null;
  }

  set sessionId(value) {
    this._sessionId = value;
    if (value) {
      // Update paths when sessionId changes
      this.basePath = path.join(process.cwd(), 'rabbitize-runs', this.clientId, this.testId, this.sessionId);
      this.screenshotsPath = path.join(this.basePath, 'screenshots');
      this.videoPath = path.join(this.basePath, 'video');
      this.domSnapshotsPath = path.join(this.basePath, 'dom_snapshots');
    }
  }

  async cleanupLocalFiles() {
    try {
      // Ensure rabbitize-runs exists first
      const runsDir = path.join(process.cwd(), 'rabbitize-runs');
      if (!fs.existsSync(runsDir)) {
        await fsPromises.mkdir(runsDir, { recursive: true });
        this.firebase.log('Created rabbitize-runs directory');
      }

      // Don't clean up existing directories - preserve historical runs
      // Just create the new directories for this session
      await fsPromises.mkdir(this.basePath, { recursive: true });
      await fsPromises.mkdir(this.screenshotsPath, { recursive: true });
      await fsPromises.mkdir(this.videoPath, { recursive: true });
      await fsPromises.mkdir(this.domSnapshotsPath, { recursive: true });

      this.firebase.log('Created fresh directories for new run');
    } catch (error) {
      this.firebase.warn('Error during local file cleanup:', error);
      // Continue execution even if cleanup fails
    }
  }

  generateColorPattern(command) {
    const commandType = Array.isArray(command) ? command[0] : command;

    if (this.colorPatterns.has(commandType)) {
      return this.colorPatterns.get(commandType);
    }

    // Generate unique color pattern for this command type
    // Using bright, distinct colors for better detection
    const pattern = [
      `rgb(${Math.floor(Math.random() * 128) + 128}, 0, 0)`,     // Red-ish
      `rgb(0, ${Math.floor(Math.random() * 128) + 128}, 0)`,     // Green-ish
      `rgb(0, 0, ${Math.floor(Math.random() * 128) + 128})`,     // Blue-ish
      `rgb(${Math.floor(Math.random() * 128) + 128}, ${Math.floor(Math.random() * 128) + 128}, 0)` // Yellow-ish
    ];

    this.colorPatterns.set(commandType, pattern);
    return pattern;
  }

  async setupPageElements() {
    if (!this.page) return;

    // console.log('[DEBUG] setupPageElements called:');
    // console.log('this.showCommandOverlay:', this.showCommandOverlay);

    try {
      await this.page.evaluate((sessionId) => {
        window._rabbitizeSessionId = sessionId;
        if (!window._rabbitizeInitialized) {
          const waitForBody = () => {
            if (document.body) {
              const style = document.createElement('style');
              style.textContent = `
                .mouse-pointer {
                  width: 20px;
                  height: 20px;
                  background: rgba(255, 0, 0, 0.5);
                  border: 2px solid red;
                  border-radius: 50%;
                  position: fixed;
                  pointer-events: none;
                  z-index: 999999;
                  transform: translate(-50%, -50%);
                  transition: all 50ms ease;
                }
                @keyframes rabbitize-ripple {
                  0% {
                    transform: translate(-50%, -50%) scale(1);
                    opacity: 1;
                  }
                  100% {
                    transform: translate(-50%, -50%) scale(4);
                    opacity: 0;
                  }
                }
                .command-overlay {
                  position: fixed !important;
                  bottom: 20px !important;
                  right: 20px !important;
                  background: rgba(0, 0, 0, 0.8) !important;
                  color: white !important;
                  padding: 10px !important;
                  border-radius: 5px !important;
                  font-family: monospace !important;
                  font-size: 26px !important;
                  font-weight: 700 !important;
                  z-index: 2147483647 !important;
                  pointer-events: none !important;
                  opacity: 1 !important;
                  max-width: 600px !important;
                  word-wrap: break-word !important;
                }
                .time-overlay {
                  position: fixed !important;
                  bottom: 20px !important;
                  left: 20px !important;
                  background: rgba(0, 0, 0, 0.8) !important;
                  color: white !important;
                  padding: 10px !important;
                  border-radius: 5px !important;
                  font-family: monospace !important;
                  font-size: 26px !important;
                  font-weight: 700 !important;
                  z-index: 2147483647 !important;
                  pointer-events: none !important;
                  opacity: 1 !important;
                }
              `;

              if (document.head) {
                document.head.appendChild(style);
              }

              const cursor = document.createElement('div');
              cursor.className = 'mouse-pointer';
              document.body.appendChild(cursor);
              window._cursor = cursor;

              const overlay = document.createElement('div');
              overlay.className = 'command-overlay';
              overlay.style.visibility = window._rabbitizeShowOverlay ? 'visible' : 'hidden';
              document.body.appendChild(overlay);
              window._commandOverlay = overlay;

              // Only create time overlay for interactive sessions
              if (window._rabbitizeSessionId === 'interactive') {
                const timeOverlay = document.createElement('div');
                timeOverlay.className = 'time-overlay';
                timeOverlay.style.visibility = window._rabbitizeShowOverlay ? 'visible' : 'hidden';
                document.body.appendChild(timeOverlay);
                window._timeOverlay = timeOverlay;

                // Start time update interval
                if (!window._timeInterval) {
                  window._timeInterval = setInterval(() => {
                    if (window._timeOverlay) {
                      const now = new Date();
                      const hours = String(now.getHours()).padStart(2, '0');
                      const minutes = String(now.getMinutes()).padStart(2, '0');
                      const seconds = String(now.getSeconds()).padStart(2, '0');
                      window._timeOverlay.textContent = `${hours}:${minutes}:${seconds}`;
                    }
                  }, 1000);
                }
              }

              // Add timecode corner
              const timecodeCorder = document.createElement('div');
              timecodeCorder.style.cssText = `
                position: fixed !important;
                bottom: 0 !important;
                right: 0 !important;
                width: 4px !important;
                height: 4px !important;
                z-index: 2147483647 !important;
                pointer-events: none !important;
                display: grid !important;
                grid-template: repeat(2, 2px) / repeat(2, 2px) !important;
                background: black !important;
                opacity: 1 !important;
              `;

              for (let i = 0; i < 4; i++) {
                const pixel = document.createElement('div');
                pixel.style.cssText = 'width: 2px !important; height: 2px !important;';
                timecodeCorder.appendChild(pixel);
              }

              document.body.appendChild(timecodeCorder);
              window._timecodeCorder = timecodeCorder;

              // Add click interceptor for target="_blank" links
              if (!window._blankLinkInterceptorAdded) {
                // Tracking for user-initiated clicks
                let userClickedLink = null;

                // Only intercept actual user clicks (not programmatic/automated clicks)
                document.addEventListener('click', (event) => {
                  const link = event.target.closest('a');
                  if (link &&
                      (link.target === '_blank' || link.getAttribute('rel') === 'noopener') &&
                      // Only handle actual user-initiated clicks
                      event.isTrusted) {

                    // Remember this was a user-initiated click
                    userClickedLink = link;

                    // Prevent the default action
                    event.preventDefault();

                    // Get the href attribute
                    const href = link.href;
                    if (href && !href.startsWith('javascript:')) {
                      // Navigate in the current window
                      window.location.href = href;
                    }

                    // Clear the reference after a short delay
                    setTimeout(() => {
                      userClickedLink = null;
                    }, 100);
                  }
                }, true);

                window._blankLinkInterceptorAdded = true;
              }

              window._rabbitizeInitialized = true;
            }
          };

          // Try immediately
          waitForBody();

          // Also set up a MutationObserver as fallback
          if (!document.body) {
            const observer = new MutationObserver((mutations, obs) => {
              if (document.body) {
                waitForBody();
                obs.disconnect();
              }
            });

            observer.observe(document.documentElement, {
              childList: true,
              subtree: true
            });
          }
        }
      }, this.sessionId);

      // Set overlay visibility state
      await this.page.evaluate((showOverlay) => {
        window._rabbitizeShowOverlay = showOverlay;
        if (window._commandOverlay) {
          window._commandOverlay.style.visibility = showOverlay ? 'visible' : 'hidden';
        }
        if (window._timeOverlay) {
          window._timeOverlay.style.visibility = showOverlay ? 'visible' : 'hidden';
        }
      }, this.showCommandOverlay);

    } catch (error) {
      // Log but don't throw - this allows initialization to continue
      this.firebase.debug('Setup page elements warning:', error);
    }

    // Reduced timeout since we have better DOM ready handling
    await this.page.waitForTimeout(50);
  }

  /**
   * Handles a navigation timeout by showing a custom timeout page
   * @param {string} url - The URL that failed to load
   * @param {number} timeoutMs - The timeout duration in milliseconds
   * @param {Error} error - The original timeout error
   */
  async handleNavigationTimeout(url, timeoutMs, error) {
    this.firebase.error(`Navigation timeout for URL: ${url}`, {
      timeout: timeoutMs,
      error: error.message
    });

    try {
      // Create a file URL to the timeout.html file
      const timeoutPagePath = path.join(process.cwd(), 'resources', 'timeout.html');
      const encodedUrl = encodeURIComponent(url);
      const timeoutSecs = Math.round(timeoutMs / 1000);
      const fileUrl = `file://${timeoutPagePath}?url=${encodedUrl}&timeout=${timeoutSecs}%20seconds`;

      // Navigate to the timeout page
      this.firebase.log('Showing timeout page:', fileUrl);
      await this.page.goto(fileUrl, { timeout: 5000 }).catch(e => {
        // If we can't even load the timeout page, log the error but don't throw
        this.firebase.error('Failed to load timeout page:', e);
      });

      // Update overlay to show the timeout
      await this.page.evaluate((errorUrl, timeoutSecs) => {
        if (window._commandOverlay) {
          window._commandOverlay.textContent = `Navigation timeout: ${errorUrl} (${timeoutSecs}s)`;
          window._commandOverlay.style.opacity = '1';
          window._commandOverlay.style.background = 'rgba(231, 76, 60, 0.9)';
        }
      }, url, timeoutSecs).catch(() => {});

      return {
        success: false,
        error: `Navigation timeout for ${url} (${timeoutSecs}s)`,
        isNavigationTimeout: true
      };
    } catch (timeoutHandlerError) {
      this.firebase.error('Failed to handle timeout:', timeoutHandlerError);
      return {
        success: false,
        error: `Navigation timeout for ${url} and failed to show timeout page`,
        originalError: error.message,
        handlerError: timeoutHandlerError.message
      };
    }
  }

  async initialize(url) {
    try {
      // Store current session ID if it exists (it might be temporary)
      const oldSessionId = this._sessionId;
      if (oldSessionId) {
        this.temporarySessionIds.add(oldSessionId);
      }

      // Determine session type and ID first
      if (this.passedSessionId) {
        // Use the passed sessionId if provided
        this._sessionId = this.passedSessionId;
      } else if (this.batchJson || this.batchCommands) {
        // For batch sessions, use SESSION_ID env var if available, otherwise create timestamp-based ID
        this._sessionId = global.argv?.['session-id'] || process.env.SESSION_ID || new Date().toISOString().replace(/[:.]/g, '-');
      } else {
        // For interactive sessions, use timestamp-based ID instead of 'interactive'
        this._sessionId = new Date().toISOString().replace(/[:.]/g, '-');
      }

      // Now that we have the session ID, initialize paths
      this.basePath = path.join(process.cwd(), 'rabbitize-runs', this.clientId, this.testId, this.sessionId);
      this.screenshotsPath = path.join(this.basePath, 'screenshots');
      this.videoPath = path.join(this.basePath, 'video');
      this.domSnapshotsPath = path.join(this.basePath, 'dom_snapshots');

      // Initialize logger if not already provided
      if (!this.firebase) {
        const SimpleLogger = require('./utils/simpleLogger');
        this.firebase = new SimpleLogger(this.clientId, this.testId, this.sessionId);
      } else {
        // Update session ID in existing logger
        this.firebase.updateSessionId(this.sessionId);
      }
      this.firestore = new FirestoreManager(this.clientId, this.testId, this.sessionId);

      // Initialize Firestore before any operations
      await this.firestore.initialize();

      // Mark as initialized
      this.initialized = true;

      // Clean up any temporary session before proceeding
      if (oldSessionId && oldSessionId !== this._sessionId) {
        await this.cleanupTemporarySession(oldSessionId);
      }

      // Now we can start logging
      console.log('🎮🕹️👾 🎮🕹️👾 🎮🕹️👾 🌐 🐇 🌐 🎮🕹️👾 🎮🕹️👾 🎮🕹️👾');

      // Only replay early logs for batch sessions
      if (this.batchJson || this.batchCommands) {
        for (const log of this.earlyLogs) {
          await this.log(log.level, log.message, log.data);
        }
      }
      this.earlyLogs = []; // Clear early logs

      await this.log('info', 'PlaywrightSession.initialize - Starting with URL:', url);
      this.initialUrl = url;

      await this.cleanupLocalFiles();

      // Add timeout to Firebase operations
      this.firebase.log('PlaywrightSession.initialize - Starting Firebase cleanup...');
      await Promise.race([
        this.firebase.cleanupExistingSession(),
        new Promise((_, reject) =>
          setTimeout(() => reject(new Error('Firebase cleanup timeout')), 50000)
        )
      ]).catch(error => {
        this.firebase.error('Firebase cleanup failed:', error);
        // Continue even if Firebase fails
      });
      this.firebase.log('PlaywrightSession.initialize - Firebase cleanup completed or skipped');

      // Extract and clean up options for Firebase
      const options = {
        clientId: this.clientId,
        testId: this.testId,
        showCommandOverlay: this.showCommandOverlay,
        createClipSegments: this.createClipSegments,
        batchCommands: !!this.batchCommands,
        batchJson: !!this.batchJson
      };

      // Add clean command line args (only full names, preserve objects)
      if (global.argv) {
        // Only add fields that have values
        const argOptions = {};
        const fields = ['hostname', 'port', 'showOverlay', 'clipSegments', 'processVideo', 'exitOnEnd', 'meta'];
        fields.forEach(field => {
          if (global.argv[field] !== undefined) {
            argOptions[field] = global.argv[field];
          }
        });

        // Add system-meta if it exists and isn't empty
        if (global.argv.systemMeta && Object.keys(global.argv.systemMeta).length > 0) {
          argOptions['system-meta'] = global.argv.systemMeta;
        }

        Object.assign(options, argOptions);
      }

      // Save initial options (no-op in local mode)
      await this.firebase.db.ref(`${this.firebase.getBasePath()}/options`).set(options);

      // Set initial states (no-op in local mode)
      try {
        await Promise.race([
          this.firebase.setRunningState(true),
          this.firebase.setSessionType(this.batchJson || this.batchCommands ? 'batched' : 'interactive'),
          this.firebase.setInitialUrl(url),
          new Promise((_, reject) =>
            setTimeout(() => reject(new Error('Firebase setState timeout')), 5000)
          )
        ]);
      } catch (error) {
        // Silently continue - these are no-ops anyway
      }

      // Continue with directory creation and browser launch
      await fsPromises.mkdir(this.screenshotsPath, { recursive: true });
      await fsPromises.mkdir(this.videoPath, { recursive: true });
      this.firebase.log('PlaywrightSession.initialize - Created directories');

      this.firebase.log('PlaywrightSession.initialize - Launching browser');

      // Prepare launch options
      const browserLaunchOptions = {
        headless: true,
        args: [
          '--no-sandbox',
          '--disable-setuid-sandbox',
          '--disable-dev-shm-usage',  // Un-comment this - crucial for VMs
          '--disable-extensions',
          '--js-flags=--max-old-space-size=4096',  // Reduce to 4GB for faster allocation
          '--disable-background-timer-throttling',
          '--disable-backgrounding-occluded-windows',
          '--disable-renderer-backgrounding',
          '--renderer-process-limit=4',  // Limit to CPU count
          '--disable-features=site-per-process',  // Reduces memory usage
          '--disable-translate',  // Disable unnecessary features
          '--disable-sync',
          '--disable-crash-reporter'
        ],
        ignoreDefaultArgs: ['--enable-automation'],
        timeout: 30000 // Increased for better reliability on limited CPU
      };

      // Add proxy configuration if specified in environment variables
      if (process.env.HTTP_PROXY || process.env.HTTPS_PROXY) {
        const proxyUrl = process.env.HTTPS_PROXY || process.env.HTTP_PROXY;
        this.firebase.log('Using proxy from environment:', proxyUrl);
        browserLaunchOptions.proxy = {
          server: proxyUrl
        };
      }

      this.browser = await chromium.launch(browserLaunchOptions);
      this.firebase.log('PlaywrightSession.initialize - Browser launched');

      this.firebase.log('PlaywrightSession.initialize - Creating context');
      // this.context = await this.browser.newContext({
      //   viewport: DEFAULT_CONFIG.videoSize,
      //   recordVideo: {
      //     dir: this.videoPath,
      //     //size: DEFAULT_CONFIG.videoSize
      //     size: { width: 1280, height: 720 },
      //     fps: 30,
      //     codec: 'vp8',
      //     frameTimeout: 1000,
      //     gopSize: 30,
      //     pixelFormat: 'yuv420p',
      //     scale: {
      //       mode: 'fit',          // 'fit' or 'fill' - determines how content is scaled
      //       preserveAspectRatio: true  // Maintains aspect ratio during scaling
      //     }
      //   }
      // });
      // Base context options
      const contextOptions = {
        viewport: DEFAULT_CONFIG.videoSize,
        acceptDownloads: true  // Enable download handling
      };

      // Enable video recording for non-interactive sessions or when process-video is true
      // if (this.sessionId !== 'interactive' || global.argv?.processVideo) {
      //   this.firebase.log('Enabling video recording with options:', {
      //     dir: this.videoPath,
      //     size: DEFAULT_CONFIG.videoSize
      //   });

      this.firebase.log('Video recording check:', {
        sessionId: this.sessionId,
        isInteractive: this.sessionId === 'interactive',
        processVideo: global.argv?.processVideo,
        testId: this.testId,
        testIdCheck: !this.testId.toLowerCase().includes('NOOOOOOOOOOOO!!!!!!!!')
      });

      if ((this.sessionId !== 'interactive' || global.argv?.processVideo) &&
        !this.testId.toLowerCase().includes('NOOOOOOOOOOOO!!!!!!!!')) {
        this.firebase.log('Enabling video recording with options:', {
          dir: this.videoPath,
          size: DEFAULT_CONFIG.videoSize
        });


        contextOptions.recordVideo = {
          dir: this.videoPath,
          size: DEFAULT_CONFIG.videoSize
        };
      } else {
        this.firebase.log('Video recording DISABLED - conditions not met');
      }

      // test to see if makes it through more sites, etc
      // contextOptions.userAgent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36';

      this.context = await this.browser.newContext(contextOptions);

      this.firebase.log('PlaywrightSession.initialize - Context created with video enabled:', !!contextOptions.recordVideo);

      // Set up video file detection in a non-blocking way
      if (contextOptions.recordVideo) {
        this.firebase.log('Setting up background video file detection');
        // Don't block initialization - run in background
        this.setupVideoLinkDetection();
      }

      this.firebase.log('PlaywrightSession.initialize - Creating new page');
      this.page = await this.context.newPage();
      
      // Set up download handling
      this.setupDownloadHandling();
      
      // Set up file chooser handling
      this.setupFileChooserHandling();

      ///await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36');

      this.firebase.log('PlaywrightSession.initialize - Page created, checking video:', {
        hasVideo: !!(this.page && this.page.video),
        videoPath: this.videoPath
      });

      // Setup frame navigation handling for target="_blank" links
      this.page.on('frameattached', async (frame) => {
        try {
          // Apply the same target="_blank" handling to newly attached frames
          if (frame.isDetached()) return;

          // Wait for the frame to load
          await frame.waitForLoadState('domcontentloaded').catch(() => {});

          // Add the same click interceptor to the frame
          await frame.evaluate(() => {
            if (!window._blankLinkInterceptorAdded) {
              // Tracking for user-initiated clicks
              let userClickedLink = null;

              // Only intercept actual user clicks (not programmatic/automated clicks)
              document.addEventListener('click', (event) => {
                const link = event.target.closest('a');
                if (link &&
                    (link.target === '_blank' || link.getAttribute('rel') === 'noopener') &&
                    // Only handle actual user-initiated clicks
                    event.isTrusted) {

                  // Remember this was a user-initiated click
                  userClickedLink = link;

                  // Prevent the default action
                  event.preventDefault();

                  // Get the href attribute
                  const href = link.href;
                  if (href && !href.startsWith('javascript:')) {
                    // Navigate in the current window (top frame)
                    window.top.location.href = href;
                  }

                  // Clear the reference after a short delay
                  setTimeout(() => {
                    userClickedLink = null;
                  }, 100);
                }
              }, true);

              window._blankLinkInterceptorAdded = true;
            }
          }).catch(() => {
            // Ignore errors for cross-origin frames
            this.firebase.debug('Could not add target="_blank" handler to frame - likely cross-origin');
          });
        } catch (e) {
          this.firebase.debug('Error handling frame attachment:', e);
        }
      });

      // Initialize stability detector if enabled
      if (this.stabilityOptions.enabled) {
        console.log('[Debug] Creating StabilityDetector with options:', this.stabilityOptions);
        this.stabilityDetector = new StabilityDetector(this.page, {
          enabled: true,  // Force enabled since we're inside the if block
          waitTime: this.stabilityOptions.waitTime,
          sensitivity: this.stabilityOptions.sensitivity,
          timeout: this.stabilityOptions.timeout,
          interval: this.stabilityOptions.interval,
          frameCount: this.stabilityOptions.frameCount,
          downscaleWidth: this.stabilityOptions.downscaleWidth
        });
        this.stabilityTimeoutCount = 0; // Reset timeout counter when creating new detector
        this.firebase.log('PlaywrightSession.initialize - Stability detector initialized');
      }

      // Only start screenshot interval if enabled
      if (this.enableLiveScreenshots) {
        this.startScreenshotInterval();
      }

      // Add this new section to set initial mouse position
      const viewport = this.page.viewportSize();
      this.currentMouseX = viewport.width / 2;
      this.currentMouseY = viewport.height / 2;

      // Move mouse to center initially
      await this.page.mouse.move(this.currentMouseX, this.currentMouseY);

      // Setup initial page elements
      await this.setupPageElements();
      this.firebase.log('PlaywrightSession.initialize - Page elements set up');

      // Keep all existing event listeners
      this.page.on('load', async () => {
        this.firebase.log('Page load event triggered');
        // try {
        //   await this.page.evaluate(() => {
        //     if (window._commandOverlay) {
        //       window._commandOverlay.textContent = '[":*wait-for-page-load"]';
        //       window._commandOverlay.style.opacity = '1';
        //     }
        //   });
        // } catch (e) {
        //   this.firebase.debug('Load overlay failed:', e);
        // }

        this.firebase.log('Page loaded, reinitializing elements...');
        await this.setupPageElements();
        // Reapply cursor position
        if (this.currentMouseX !== undefined && this.currentMouseY !== undefined) {
          await this.page.evaluate(({ x, y }) => {
            if (window._cursor) {
              window._cursor.style.transition = 'none';
              window._cursor.style.left = `${x}px`;
              window._cursor.style.top = `${y}px`;
            }
          }, {
            x: this.currentMouseX,
            y: this.currentMouseY
          });
        }
      });

      // Listen for frame navigation
      this.page.on('framenavigated', async frame => {
        if (frame === this.page.mainFrame()) {
          try {
            await this.page.evaluate(() => {
              if (window._commandOverlay) {
                window._commandOverlay.textContent = '[":*wait-for-navigation"]';
                window._commandOverlay.style.opacity = '1';
              }
            });
          } catch (e) {
            this.firebase.debug('Navigation overlay failed:', e);
          }

          this.firebase.log('Main frame navigated, reinitializing elements...');
          await this.setupPageElements();

          // Reset stability timeout counter on main frame navigation
          this.stabilityTimeoutCount = 0;
          if (this.stabilityOptions.enabled === false && this.stabilityDetector) {
            this.firebase.log('Re-enabling stability detection after navigation');
            this.stabilityOptions.enabled = true;
            console.log(chalk.green('🐴 Stability: RE-ENABLED after page navigation'));
          }

          // Reapply cursor position
          if (this.currentMouseX !== undefined && this.currentMouseY !== undefined) {
            await this.page.evaluate(({ x, y }) => {
              if (window._cursor) {
                window._cursor.style.transition = 'none';
                window._cursor.style.left = `${x}px`;
                window._cursor.style.top = `${y}px`;
              }
            }, {
              x: this.currentMouseX,
              y: this.currentMouseY
            });
          }
        }
      });

      // Start metrics polling after page is created
      this.startMetricsPolling();

      this.firebase.log('PlaywrightSession.initialize - Navigating to URL:', url);
      try {
        // Define navigation timeout in milliseconds
        const navigationTimeoutMs = 60000; // 60 seconds

        // Navigate to the URL with timeout options
        await this.page.goto(url, {
          timeout: navigationTimeoutMs,
          waitUntil: 'domcontentloaded'
        });

        this.firebase.log('PlaywrightSession.initialize - Navigation complete');
        this.firebase.log('Taking initial page screenshot...');
        await this.captureState('start');

        // Capture initial DOM state
        try {
          // Create directory for DOM coordinates data
          const domCoordsDir = path.join(this.basePath, 'dom_coords');
          await fsPromises.mkdir(domCoordsDir, { recursive: true });

          // Capture DOM elements
          const initialDomElements = await this.capturePageElements();

          if (initialDomElements) {
            // Save initial DOM state
            const initialDomPath = path.join(domCoordsDir, 'dom_coords_initial.json');
            await fsPromises.writeFile(
              initialDomPath,
              JSON.stringify(initialDomElements, null, 2)
            );
            this.firebase.log('Captured initial DOM state');
          }
        } catch (error) {
          this.firebase.warn('Failed to capture initial DOM state:', error);
          // Continue execution even if DOM capture fails
        }

        return { success: true, sessionId: this.sessionId };
      } catch (error) {
        this.firebase.error('PlaywrightSession.initialize - Navigation failed:', error);

        // Check if this is a timeout error
        if (error.name === 'TimeoutError' || error.message.includes('timeout')) {
          // Handle the timeout by showing the timeout page
          const result = await this.handleNavigationTimeout(url, 60000, error);

          // Set running state to false but don't throw the error
          await this.firebase.setRunningState(false);
          return result;
        }

        await this.firebase.setRunningState(false);
        throw error;
      }
    } catch (error) {
      console.error('PlaywrightSession.initialize - Fatal error:', error);
      throw error;
    }
  }

  async initUserParamsListener() {
    // Use this.clientId instead of trying to parse from session
    const paramsRef = this.firebase.db.ref(`users/${this.clientId}`);

    console.log('Initializing user params listener for client:', this.clientId);
    console.log('Using Firebase path:', `users/${this.clientId}`);

    // Get initial value once
    const snapshot = await paramsRef.once('value');
    this.userParams = snapshot.val() || {};

    //console.log('Initial user params value:', snapshot.val());

    // Listen for changes to specific children only
    paramsRef.on('child_changed', (snapshot) => {
      const key = snapshot.key;
      const value = snapshot.val();
      this.userParams[key] = value;
      console.log('User params updated:', this.userParams);
    });

    this.userParamsRef = paramsRef;
  }

  async startScreenshotInterval() {
    if (this.screenshotInterval) {
      clearInterval(this.screenshotInterval);
    }

    // Remove any existing refresh rate listener
    if (this.refreshRateListener) {
      this.userParamsRef?.child('refresh').off('value', this.refreshRateListener);
    }

    if (!this.userParams) {
      await this.initUserParamsListener();
    }

    // Convert refresh rate string to milliseconds
    const getIntervalMs = (refresh) => {
      switch (refresh) {
        case '0s': return 220;   // UPDATED: 10 FPS for "real-time"
        case '1s': return 900;   // 1 screenshot per second
        case '2s': return 1900;  // 1 screenshot every 2 seconds
        case '5s': return 4900;  // 1 screenshot every 5 seconds
        case '10s': return 9900; // 1 screenshot every 10 seconds
        default: return 900;     // Default to 1 per second
      }
    };

    let isProcessing = false;
    const shmPath = '/dev/shm/latest.jpg';
    const regularPath = path.join(this.basePath, 'latest.jpg');
    const useShm = await fsPromises.access('/dev/shm', fsPromises.constants.W_OK)
      .then(() => true)
      .catch(() => false);
    const latestPath = useShm ? shmPath : regularPath;

    const refresh = this.userParams?.refresh ?? '0s';
    let intervalMs = getIntervalMs(refresh);

    this.firebase.debug('Starting screenshot interval with refresh rate:', refresh, 'interval:', intervalMs + 'ms');

    const takeScreenshot = async () => {
      // if (!this.page || isProcessing) {
      //   this.firebase.debug('Screenshot skipped - no page or processing');
      //   return;
      // }
      try {
        isProcessing = true;
        const refresh = this.userParams?.refresh ?? '0s';
        //this.firebase.debug('Taking screenshot for mjpeg stream...');

        // Define settings based on refresh rate
        const settings = {
          '0s': {
            // width: this.userParams?.scaledpreview?.width ?? 1920,
            // quality: 45,
            // optimizeScans: true,
            // trellisQuantisation: true,
            // overshootDeringing: true,
            // optimizeCoding: true,
            // force: true,
            // fastShrink: true
            width: 800, //this.userParams?.scaledpreview?.width ?? 1000,
            quality: 50, // Balance between size and deterministic output
            progressive: false, // Critical for consistent byte patterns
            chromaSubsampling: '4:2:0', // Keep this for file size benefits
            trellisQuantisation: false, // Disable adaptive optimization
            optimizeScans: false, // Turn off variable optimization
            mozjpeg: false, // More deterministic without mozjpeg
            quantisationTable: 3, // Use a fixed table (0-8)
            fastShrink: false,
            effort: 10,
            force: true // Ensure consistent processing
          },
          '1s': { // temp cheap for previews
            width: 800, //this.userParams?.scaledpreview?.width ?? 1000,
            quality: 50, // Balance between size and deterministic output
            progressive: false, // Critical for consistent byte patterns
            chromaSubsampling: '4:2:0', // Keep this for file size benefits
            trellisQuantisation: false, // Disable adaptive optimization
            optimizeScans: false, // Turn off variable optimization
            mozjpeg: false, // More deterministic without mozjpeg
            quantisationTable: 3, // Use a fixed table (0-8)
            fastShrink: false,
            effort: 10,
            force: true // Ensure consistent processing
          },
          // '1s': {
          //   width: this.userParams?.scaledpreview?.width ?? 1920,
          //   quality: 70,
          //   optimizeScans: true,
          //   trellisQuantisation: true,
          //   optimizeCoding: true,
          //   force: true
          // },
          '2s': {
            width: this.userParams?.scaledpreview?.width ?? 1920,
            quality: 75,
            optimizeScans: true,
            optimizeCoding: true
          },
          '5s': {
            width: Math.min(1920, this.userParams?.scaledpreview?.width ?? 2560),
            quality: 75,
            optimizeScans: true,
            optimizeCoding: true
          },
          '10s': {
            width: null, // original size
            quality: 90
          }
        };

        const currentSettings = settings[refresh] || settings['0s'];

        const screenshotBuffer = await this.page.screenshot({
          type: 'jpeg',
          quality: 90  // High quality for streaming
        });

        // For file storage, use compressed version
        const compressedBuffer = await sharp(screenshotBuffer)
          .resize(currentSettings.width, null)
          .jpeg({
            quality: currentSettings.quality,
            ...currentSettings
          })
          .toBuffer();

        // Write compressed version to file
        await fsPromises.writeFile(latestPath, compressedBuffer);

        // Emit full resolution frame to stream clients
        if (global.frameEmitter) {
          const sessionKey = `${this.clientId}/${this.testId}/${this.sessionId}`;
          global.lastFrameBuffer[sessionKey] = screenshotBuffer;  // Full res
          global.frameEmitter.emit('frame', {
            sessionKey,
            buffer: screenshotBuffer,  // Full res
            timestamp: Date.now()
          });
          //this.firebase.debug(`Emitted frame for ${sessionKey}, buffer size: ${screenshotBuffer.length}`);
        } else {
          this.firebase.debug('No frameEmitter available!');
        }
      } catch (error) {
        this.firebase.debug('Screenshot interval error:', error);
      } finally {
        isProcessing = false;
      }
    };

    const startInterval = (ms) => {
      if (this.screenshotInterval) {
        clearInterval(this.screenshotInterval);
      }
      this.screenshotInterval = setInterval(takeScreenshot, ms);
      this.firebase.debug(`Screenshot interval started with ${ms}ms interval`);
      // Take first screenshot immediately
      takeScreenshot();
    };

    // Start initial interval
    startInterval(intervalMs);

    // Set up refresh rate listener
    this.refreshRateListener = (snapshot) => {
      const newRefresh = snapshot.val() ?? '0s';
      const newIntervalMs = getIntervalMs(newRefresh);

      this.firebase.debug('Refresh rate changed:', newRefresh, 'new interval:', newIntervalMs + 'ms');

      // Restart interval with new timing
      startInterval(newIntervalMs);
    };

    // Add listener for refresh rate changes
    this.userParamsRef?.child('refresh').on('value', this.refreshRateListener);
  }

  async showCommand(command) {
    // Add debug logging
    // console.log('\n[DEBUG] showCommand called:');
    // console.log('this.showCommandOverlay:', this.showCommandOverlay);
    console.log('command!', command);

    if (!this.showCommandOverlay || !this.page) {
      // console.log('[DEBUG] showCommand early return - overlay disabled or no page');
      return;
    }

    try {
      await this.page.evaluate((cmd) => {
        console.log('[DEBUG Browser] Showing command:', cmd);
        if (window._commandOverlay && window._rabbitizeShowOverlay) {
          window._commandOverlay.textContent = JSON.stringify(cmd);
          window._commandOverlay.style.opacity = '1';
          setTimeout(() => {
            if (window._commandOverlay) {
              window._commandOverlay.style.opacity = '0';
            }
          }, 2000);
        } else {
          console.log('[DEBUG Browser] No command overlay found or overlays disabled');
        }
      }, command);
    } catch (error) {
      this.firebase.warn('Failed to show command overlay:', error);
    }
  }

  async withTimeout(promise, timeoutMs = 5000, operation = 'operation') {
    // If this is an upload operation and asyncUploads is enabled in Firebase
    if (this.firebase?.asyncUploads &&
        (operation.includes('Upload') || operation.includes('upload'))) {
      try {
        // Just start the promise without waiting for it
        promise.catch(error => {
          this.firebase.warn(`Async ${operation} background error:`, error);
        });
        // Return immediately
        return true;
      } catch (error) {
        this.firebase.warn(`Failed to start async ${operation}:`, error);
        return null;
      }
    }

    // Default synchronous behavior
    return Promise.race([
      promise,
      new Promise((_, reject) =>
        setTimeout(() => reject(new Error(`${operation} timeout`)), timeoutMs)
      )
    ]).catch(error => {
      this.firebase.warn(`${operation} failed:`, error);
      // Continue execution
      return null;
    });
  }

  async captureState(label) {
    if (!this.page) {
      return {
        url: null,
        title: null,
        screenshotPath: null,
        timestamp: Date.now()
      };
    }

    try {
      // Remove colons from the label
      const safeLabel = label.replace(/:/g, '');
      const screenshotPath = path.join(this.screenshotsPath, `${safeLabel}.jpg`);
      const latestPath = path.join(this.basePath, 'latest.jpg');

      // Update cursor position before screenshot
      if (this.currentMouseX !== undefined && this.currentMouseY !== undefined) {
        await this.page.evaluate(({ x, y }) => {
          if (window._cursor) {
            window._cursor.style.left = `${x}px`;
            window._cursor.style.top = `${y}px`;
          }
        }, {
          x: this.currentMouseX,
          y: this.currentMouseY
        });
      }

      // Take high quality screenshot for streaming
      const highQualityBuffer = await this.page.screenshot({
        fullPage: false,
        type: 'jpeg',
        quality: 90  // High quality for streaming
      });

      // Create compressed version for file storage
      const compressedBuffer = await sharp(highQualityBuffer)
        .jpeg({ quality: 35 })
        .toBuffer();

      // Write compressed version to files
      await Promise.all([
        fsPromises.writeFile(screenshotPath, compressedBuffer),
        fsPromises.writeFile(latestPath, compressedBuffer)
      ]);

      // Emit high quality frame to stream clients
      if (global.frameEmitter && label === 'latest') {
        const sessionKey = `${this.clientId}/${this.testId}/${this.sessionId}`;
        global.lastFrameBuffer[sessionKey] = highQualityBuffer;
        global.frameEmitter.emit('frame', {
          sessionKey,
          buffer: highQualityBuffer,
          timestamp: Date.now()
        });
      }

      if (screenshotPath) {
        if (this.firebase?.asyncUploads) {
          // Use non-blocking upload directly
          this.firebase.uploadFileAsync(screenshotPath);

          if (label === 'latest') {
            this.firebase.uploadLatestScreenshot(screenshotPath)
              .catch(error => this.firebase.warn('Background latest screenshot upload failed:', error));
          }
        } else {
          // Use existing blocking upload with timeout
          await this.withTimeout(
            this.firebase.uploadFile(screenshotPath),
            25000,
            'Upload screenshot'
          );
          if (label === 'latest') {
            await this.withTimeout(
              this.firebase.uploadLatestScreenshot(screenshotPath),
              25000,
              'Upload latest screenshot'
            );
          }
        }
      }

      return {
        url: await this.page.url(),
        title: await this.page.title(),
        screenshotPath,
        timestamp: Date.now()
      };
    } catch (error) {
      this.firebase.warn('Failed to capture state:', error);
      return {
        url: null,
        title: null,
        screenshotPath: null,
        timestamp: Date.now(),
        error: error.message
      };
    }
  }

  async moveCursor(x, y, steps = 30) {
    if (!this.page) return;

    const startX = this.currentMouseX || 0;
    const startY = this.currentMouseY || 0;

    // First ensure cursor exists
    await this.setupPageElements();

    // Update cursor transition for smooth movement
    await this.page.evaluate(() => {
      if (window._cursor) {
        window._cursor.style.transition = 'transform 0ms, left 300ms ease-out, top 300ms ease-out';
      }
    });

    // Single smooth movement
    await this.page.evaluate(({ x, y }) => {
      if (window._cursor) {
        window._cursor.style.left = `${x}px`;
        window._cursor.style.top = `${y}px`;
      }
    }, { x, y });

    // Move actual mouse in steps for recording purposes
    for (let i = 0; i <= steps; i++) {
      const progress = i / steps;
      const currentX = startX + (x - startX) * progress;
      const currentY = startY + (y - startY) * progress;
      await this.page.mouse.move(currentX, currentY);
      await this.page.waitForTimeout(1);
    }

    // Check if cursor is over a link and update color accordingly
    await this.page.evaluate(({ x, y }) => {
      if (window._cursor) {
        // Get the element at the current cursor position
        const element = document.elementFromPoint(x, y);

        // Check if element or any of its ancestors is a link or draggable
        let isOverLink = false;
        let isOverDraggable = false;
        let currentElement = element;

        while (currentElement && !isOverLink && !isOverDraggable) {
          const computedStyle = window.getComputedStyle(currentElement);
          const cursorStyle = computedStyle.cursor;

          // Check for link-like elements
          if (currentElement.tagName === 'A' || cursorStyle === 'pointer') {
            isOverLink = true;
          }
          // Check for draggable elements
          else if (
            cursorStyle === 'grab' ||
            cursorStyle === 'grabbing' ||
            cursorStyle === 'move' ||
            cursorStyle === 'ns-resize' ||
            cursorStyle === 'ew-resize' ||
            cursorStyle === 'nwse-resize' ||
            cursorStyle === 'nesw-resize' ||
            cursorStyle === 'all-scroll' ||
            cursorStyle === 'col-resize' ||
            cursorStyle === 'row-resize' ||
            cursorStyle.includes('resize')
          ) {
            isOverDraggable = true;
          }

          currentElement = currentElement.parentElement;
        }

        // Update cursor color based on what it's hovering over
        if (isOverLink) {
          window._cursor.style.background = 'rgba(0, 255, 0, 0.5)';
          window._cursor.style.borderColor = 'green';
        } else if (isOverDraggable) {
          window._cursor.style.background = 'rgba(0, 0, 255, 0.5)';
          window._cursor.style.borderColor = 'blue';
        } else {
          window._cursor.style.background = 'rgba(255, 0, 0, 0.5)';
          window._cursor.style.borderColor = 'red';
        }
      }
    }, { x, y });

    // Reset cursor transition
    await this.page.evaluate(() => {
      if (window._cursor) {
        window._cursor.style.transition = 'all 50ms ease';
      }
    });

    // Store current mouse position
    this.currentMouseX = x;
    this.currentMouseY = y;
  }

  async signalCommand(command) {
    if (!this.page) return;

    try {
      const pattern = this.generateColorPattern(command);

      await this.page.evaluate((pattern) => {
        if (window._timecodeCorder) {
          Array.from(window._timecodeCorder.children).forEach((pixel, i) => {
            pixel.style.background = pattern[i];
          });
        }
      }, pattern);
    } catch (e) {
      console.debug('Timecode signal failed:', e);
    }
  }

  async createZoomedScreenshot(screenshotPath, mouseX, mouseY, command) {
    try {
      const image = sharp(screenshotPath);
      const metadata = await image.metadata();

      // Determine zoom factor based on command - safely handle non-string parts
      const isClickCommand = command?.some(part =>
        typeof part === 'string' && part.toLowerCase().includes('click')
      );
      const zoomFactor = isClickCommand ? 5.0 : 5.0;

      // Calculate zoom window boundaries - SMALLER window for more dramatic zoom
      const baseWindow = isClickCommand ? 200 : 300; // Smaller capture area = more zoom
      const halfWindow = baseWindow / 2;
      const centerX = Math.min(Math.max(mouseX, halfWindow), metadata.width - halfWindow);
      const centerY = Math.min(Math.max(mouseY, halfWindow), metadata.height - halfWindow);

      // Use _zoom suffix and jpg extension
      const zoomPath = screenshotPath.replace('_temp.png', '_zoom.jpg');
      // For zoom path creation

      // Extract and zoom region around mouse
      await image
        .extract({
          left: Math.max(0, Math.round(centerX - halfWindow)),
          top: Math.max(0, Math.round(centerY - halfWindow)),
          width: baseWindow,
          height: baseWindow
        })
        .resize({
          width: this.zoomWindowSize,  // Always output same size
          height: this.zoomWindowSize,
          fit: 'fill'
        })
        .jpeg({ quality: 20 })
        .toFile(zoomPath);

      return zoomPath;
    } catch (error) {
      this.firebase.warn('Failed to create zoomed screenshot:', error);
      return null;
    }
  }

  async executeCommand(command) {
    // Reset inactivity timer on command execution
    this.resetInactivityTimer();

    // Get command index at the start
    const commandIndex = this.commandCounter;

    // Track current command
    this.currentCommand = command;
    this.commandHistory.push(command);

    // Set initial status
    try {
      await this.firebase.db.ref(`${this.firebase.getBasePath()}/command-status/${commandIndex}`).set('running');
    } catch (e) {
      console.error('Failed to set initial command status:', e);
    }

    this.executedCommands.push(command);
    if (!this.page) {
      // Update status before returning error
      await this.firebase.db.ref(`${this.firebase.getBasePath()}/command-status/${commandIndex}`).set('error');
      return { success: false, error: 'Session not initialized' };
    }

    try {
      // Format command as string, removing double quotes
      const commandStr = Array.isArray(command)
        ? command.join(' ').replace(/"/g, '')
        : String(command).replace(/"/g, '');

      // Show command in overlay
      await this.showCommand(command);

      // Update both Firebase and Firestore with current commandIndex
      await Promise.all([
        this.firebase.setPhase(`executing_command ${commandIndex} - ${commandStr}`, {
          command,
          commandIndex
        }),
        this.firestore.setPhase(`executing_command ${commandIndex} - ${commandStr}`, {
          command,
          commandIndex
        })
      ]);
      //console.log(`Executing command #${commandIndex}:`, commandStr);

      let result;
      try {
        const timestamp = Date.now();
        const preState = await this.captureState(`${commandIndex}-pre-${command[0]}`);
        const preMetrics = await getResourceMetrics(this.page);

        // Before command starts, set signal
        await this.page.evaluate(() => {
          if (window._timecodeCorder) {
            Array.from(window._timecodeCorder.children).forEach(pixel => {
              pixel.style.background = 'red';
            });
          }
        });

        // Add command to timestamps array with placeholder for output
        this.commandTimestamps.push({
          command,
          timestamp: Date.now(),
          output: null  // Will be populated with case statement result
        });

        // Get the current command timestamp entry
        const currentCommand = this.commandTimestamps[this.commandTimestamps.length - 1];

        // Execute the command
        switch (command[0]) {
          case ':wait':
            const [_, seconds] = command;
            const startTime = Date.now();
            const endTime = startTime + (seconds * 1000);

            // Update countdown every 100ms
            while (Date.now() < endTime) {
              const remaining = Math.ceil((endTime - Date.now()) / 1000);
              try {
                await this.page.evaluate((remaining) => {
                  if (window._commandOverlay) {
                    window._commandOverlay.textContent = `[":wait" ${remaining}]`;
                  }
                }, remaining);
              } catch (e) {
                console.debug('Countdown update failed:', e);
              }
              await this.page.waitForTimeout(100);
            }
            break;

          case ':move-mouse':
            const [__, ___, x, y] = command;
            this.currentMouseX = Number(x);
            this.currentMouseY = Number(y);
            await this.moveCursor(this.currentMouseX, this.currentMouseY);
            await this.page.waitForTimeout(1000);
            break;

          case ':click':
            try {
             // console.log(`[${this.sessionId}] Starting click command execution (counter: ${this.commandCounter})`);

              // // Save command first
              // console.log(`[${this.sessionId}] Saving click command with counter: ${this.commandCounter}`);
              // await this.firebase.saveCommandResult(
              //   command,
              //   {
              //     success: true,
              //     type: 'click',
              //     position: {
              //       x: this.currentMouseX,
              //       y: this.currentMouseY
              //     }
              //   },
              //   this.commandCounter
              // );
              // console.log(`[${this.sessionId}] Command saved successfully`);

              // Original animation code
              // console.log(`[${this.sessionId}] Starting click animation`);
              try {
                await this.page.evaluate(() => {
                  if (window._cursor) {
                    window._cursor.style.transition = 'all 0.15s ease-out';
                    window._cursor.style.transform = 'translate(-50%, -50%) scale(2)';
                    window._cursor.style.background = 'rgba(255, 0, 0, 0.8)';
                  }
                });
              } catch (e) {
                console.debug('Click animation failed:', e);
              }

              // Wait for expansion animation
              await this.page.waitForTimeout(150);

              //console.log(`[${this.sessionId}] Executing click at ${this.currentMouseX}, ${this.currentMouseY}`);
              // Click
              await this.page.mouse.click(this.currentMouseX, this.currentMouseY);

              //console.log(`[${this.sessionId}] Click executed`);

              // Add ripple effect
              // console.log(`[${this.sessionId}] Adding ripple effect`);
              try {
                await this.page.evaluate(({ x, y }) => {
                  // Ripple
                  const ripple = document.createElement('div');
                  ripple.style.cssText = `
                    position: fixed;
                    left: ${x}px;
                    top: ${y}px;
                    width: 20px;
                    height: 20px;
                    background: rgba(255, 0, 0, 0.3);
                    border-radius: 50%;
                    pointer-events: none;
                    z-index: 999998;
                    animation: rabbitize-ripple 0.6s ease-out;
                  `;
                  document.body.appendChild(ripple);
                  setTimeout(() => ripple.remove(), 600);

                  // Reset cursor
                  if (window._cursor) {
                    window._cursor.style.transform = 'translate(-50%, -50%) scale(1)';
                    window._cursor.style.background = 'rgba(255, 0, 0, 0.5)';
                  }
                }, {
                  x: this.currentMouseX,
                  y: this.currentMouseY
                });
              } catch (e) {
                console.debug('🌀 Ripple effect cancelled by page navigation.');
              }

              //console.log(`[${this.sessionId}] Click command completed`);
              await this.page.waitForTimeout(850); // Total animation time
              break;
            } catch (e) {
              console.error(`[${this.sessionId}] Click command failed:`, e);
              throw e;
            }

          case ':drag':
            const [_drag, _dragFrom, fromX, fromY, _dragTo, toX, toY] = command;

            // Move to start position
            this.currentMouseX = Number(fromX);
            this.currentMouseY = Number(fromY);
            await this.moveCursor(this.currentMouseX, this.currentMouseY);

            // Start drag with mouse down
            await this.page.mouse.down();

            // Move to end position
            this.currentMouseX = Number(toX);
            this.currentMouseY = Number(toY);
            await this.moveCursor(this.currentMouseX, this.currentMouseY);

            // End drag with mouse up
            await this.page.mouse.up();
            break;

          case ':start-drag':
            const [_startDrag, _startFrom, startX, startY] = command;

            // Move to start position
            this.currentMouseX = Number(startX);
            this.currentMouseY = Number(startY);
            await this.moveCursor(this.currentMouseX, this.currentMouseY);

            // Start drag with mouse down
            await this.page.mouse.down();
            this.isDragging = true;

            // Add visual feedback for drag state
            try {
              await this.page.evaluate(() => {
                if (window._cursor) {
                  window._cursor.style.background = 'rgba(255, 0, 0, 0.8)';
                  window._cursor.style.transform = 'translate(-50%, -50%) scale(1.2)';
                }
              });
            } catch (e) {
              console.debug('Drag visual feedback failed:', e);
            }
            break;

          case ':end-drag':
            if (!this.isDragging) {
              console.warn('Received end-drag command without active drag');
              break;
            }

            const [_endDrag, _endFrom, endX, endY] = command;

            // Move to end position
            this.currentMouseX = Number(endX);
            this.currentMouseY = Number(endY);
            await this.moveCursor(this.currentMouseX, this.currentMouseY);

            // End drag with mouse up
            await this.page.mouse.up();
            this.isDragging = false;

            // Reset cursor appearance
            try {
              await this.page.evaluate(() => {
                if (window._cursor) {
                  window._cursor.style.background = 'rgba(255, 0, 0, 0.5)';
                  window._cursor.style.transform = 'translate(-50%, -50%) scale(1)';
                }
              });
            } catch (e) {
              console.debug('Drag end visual feedback failed:', e);
            }
            break;

          case ':right-click':
            try {
              await this.page.evaluate(() => {
                if (window._cursor) {
                  window._cursor.style.transition = 'all 0.15s ease-out';
                  window._cursor.style.transform = 'translate(-50%, -50%) scale(2)';
                  window._cursor.style.background = 'rgba(0, 0, 255, 0.8)'; // Blue for right click
                  window._cursor.style.boxShadow = '0 0 10px rgba(0, 0, 255, 0.5)';
                }
              });
            } catch (e) {
              console.debug('Right click animation failed:', e);
            }

            // Wait for expansion animation
            await this.page.waitForTimeout(150);

            // Click
            await this.page.mouse.click(this.currentMouseX, this.currentMouseY, { button: 'right' });

            // Add blue ripple effect
            await this.page.evaluate(({ x, y }) => {
              const ripple = document.createElement('div');
              ripple.style.cssText = `
                position: fixed;
                left: ${x}px;
                top: ${y}px;
                width: 20px;
                height: 20px;
                background: rgba(0, 0, 255, 0.3);
                border-radius: 50%;
                pointer-events: none;
                z-index: 999998;
                animation: rabbitize-ripple 0.6s ease-out;
              `;
              document.body.appendChild(ripple);
              setTimeout(() => ripple.remove(), 600);

              // Reset cursor
              if (window._cursor) {
                window._cursor.style.transform = 'translate(-50%, -50%) scale(1)';
                window._cursor.style.background = 'rgba(255, 0, 0, 0.5)';
                window._cursor.style.boxShadow = 'none';
              }
            }, {
              x: this.currentMouseX,
              y: this.currentMouseY
            });

            await this.page.waitForTimeout(850); // Total animation time
            break;

          case ':middle-click':
            try {
              await this.page.evaluate(() => {
                if (window._cursor) {
                  window._cursor.style.transition = 'all 0.15s ease-out';
                  window._cursor.style.transform = 'translate(-50%, -50%) scale(2)';
                  window._cursor.style.background = 'rgba(0, 255, 0, 0.8)'; // Green for middle click
                  window._cursor.style.boxShadow = '0 0 10px rgba(0, 255, 0, 0.5)';
                }
              });
            } catch (e) {
              console.debug('Middle click animation failed:', e);
            }

            // Wait for expansion animation
            await this.page.waitForTimeout(150);

            // Click
            await this.page.mouse.click(this.currentMouseX, this.currentMouseY, { button: 'middle' });

            // Add green ripple effect
            await this.page.evaluate(({ x, y }) => {
              const ripple = document.createElement('div');
              ripple.style.cssText = `
                position: fixed;
                left: ${x}px;
                top: ${y}px;
                width: 20px;
                height: 20px;
                background: rgba(0, 255, 0, 0.3);
                border-radius: 50%;
                pointer-events: none;
                z-index: 999998;
                animation: rabbitize-ripple 0.6s ease-out;
              `;
              document.body.appendChild(ripple);
              setTimeout(() => ripple.remove(), 600);

              // Reset cursor
              if (window._cursor) {
                window._cursor.style.transform = 'translate(-50%, -50%) scale(1)';
                window._cursor.style.background = 'rgba(255, 0, 0, 0.5)';
                window._cursor.style.boxShadow = 'none';
              }
            }, {
              x: this.currentMouseX,
              y: this.currentMouseY
            });

            await this.page.waitForTimeout(850); // Total animation time
            break;

          case ':scroll-wheel-up':
            const [_scrollUp, scrollUpAmount] = command;
            const upPixelsPerClick = 100; // Adjust this value to match your needs

            for (let i = 0; i < Number(scrollUpAmount); i++) {
              await this.page.mouse.wheel(0, -upPixelsPerClick);
              await this.page.waitForTimeout(2050); // Small delay between scrolls
            }
            break;

          case ':scroll-wheel-down':
            const [_scrollDown, scrollDownAmount] = command;
            const downPixelsPerClick = 100; // Adjust this value to match your needs

            for (let i = 0; i < Number(scrollDownAmount); i++) {
              await this.page.mouse.wheel(0, downPixelsPerClick);
              await this.page.waitForTimeout(200); // Small delay between scrolls
            }
            break;

          case ':keypress':
            const [_keypress, key] = command;
            if (key.includes('-')) {
              // Handle key combinations (e.g., "Control-P", "Shift-P")
              const [modifier, mainKey] = key.split('-');
              try {
                await this.page.keyboard.down(modifier);
                await this.page.keyboard.press(mainKey);
                await this.page.keyboard.up(modifier);
              } catch (e) {
                console.debug('Key combination failed:', e);
                // Make sure modifier key is released even if there's an error
                await this.page.keyboard.up(modifier);
              }
            } else {
              // Handle single keys as before
              await this.page.keyboard.press(key);
            }
            break;

          case ':click-hold':
            try {
              // Visual feedback for click-hold state
              await this.page.evaluate(() => {
                if (window._cursor) {
                  window._cursor.style.transition = 'all 0.15s ease-out';
                  window._cursor.style.transform = 'translate(-50%, -50%) scale(1.2)';
                  window._cursor.style.background = 'rgba(255, 0, 0, 0.8)';
                  window._cursor.style.boxShadow = '0 0 10px rgba(255, 0, 0, 0.5)';
                }
              });

              // Perform the mouse down
              await this.page.mouse.down();
              this.isMouseDown = true;  // Track mouse state

              await this.page.waitForTimeout(250); // Small delay for visual feedback
              break;
            } catch (e) {
              console.debug('Click-hold animation failed:', e);
              // Still perform the mouse down even if animation fails
              await this.page.mouse.down();
              this.isMouseDown = true;
            }
            break;

          case ':click-release':
            try {
              // Visual feedback for release
              await this.page.evaluate(() => {
                if (window._cursor) {
                  window._cursor.style.transform = 'translate(-50%, -50%) scale(1)';
                  window._cursor.style.background = 'rgba(255, 0, 0, 0.5)';
                  window._cursor.style.boxShadow = 'none';
                }
              });

              // Perform the mouse up
              await this.page.mouse.up();
              this.isMouseDown = false;  // Reset mouse state

              // Add ripple effect on release
              await this.page.evaluate(({ x, y }) => {
                const ripple = document.createElement('div');
                ripple.style.cssText = `
                  position: fixed;
                  left: ${x}px;
                  top: ${y}px;
                  width: 20px;
                  height: 20px;
                  background: rgba(255, 0, 0, 0.3);
                  border-radius: 50%;
                  pointer-events: none;
                  z-index: 999998;
                  animation: rabbitize-ripple 0.6s ease-out;
                `;
                document.body.appendChild(ripple);
                setTimeout(() => ripple.remove(), 600);
              }, {
                x: this.currentMouseX,
                y: this.currentMouseY
              });

              await this.page.waitForTimeout(150); // Small delay for visual feedback
              break;
            } catch (e) {
              console.debug('Click-release animation failed:', e);
              // Still perform the mouse up even if animation fails
              await this.page.mouse.up();
              this.isMouseDown = false;
            }
            break;

          case ':right-click-hold':
            try {
              await this.page.evaluate(() => {
                if (window._cursor) {
                  window._cursor.style.transition = 'all 0.15s ease-out';
                  window._cursor.style.transform = 'translate(-50%, -50%) scale(1.2)';
                  window._cursor.style.background = 'rgba(0, 0, 255, 0.8)'; // Blue for right click
                  window._cursor.style.boxShadow = '0 0 10px rgba(0, 0, 255, 0.5)';
                }
              });

              await this.page.mouse.down({ button: 'right' });
              this.isRightMouseDown = true;

              await this.page.waitForTimeout(150);
            } catch (e) {
              console.debug('Right-click-hold animation failed:', e);
              await this.page.mouse.down({ button: 'right' });
              this.isRightMouseDown = true;
            }
            break;

          case ':right-click-release':
            try {
              await this.page.evaluate(() => {
                if (window._cursor) {
                  window._cursor.style.transform = 'translate(-50%, -50%) scale(1)';
                  window._cursor.style.background = 'rgba(255, 0, 0, 0.5)';
                  window._cursor.style.boxShadow = 'none';
                }
              });

              await this.page.mouse.up({ button: 'right' });
              this.isRightMouseDown = false;

              // Blue ripple for right click
              await this.page.evaluate(({ x, y }) => {
                const ripple = document.createElement('div');
                ripple.style.cssText = `
                  position: fixed;
                  left: ${x}px;
                  top: ${y}px;
                  width: 20px;
                  height: 20px;
                  background: rgba(0, 0, 255, 0.3);
                  border-radius: 50%;
                  pointer-events: none;
                  z-index: 999998;
                  animation: rabbitize-ripple 0.6s ease-out;
                `;
                document.body.appendChild(ripple);
                setTimeout(() => ripple.remove(), 600);
              }, {
                x: this.currentMouseX,
                y: this.currentMouseY
              });

              await this.page.waitForTimeout(150);
            } catch (e) {
              console.debug('Right-click-release animation failed:', e);
              await this.page.mouse.up({ button: 'right' });
              this.isRightMouseDown = false;
            }
            break;

          case ':middle-click-hold':
            try {
              await this.page.evaluate(() => {
                if (window._cursor) {
                  window._cursor.style.transition = 'all 0.15s ease-out';
                  window._cursor.style.transform = 'translate(-50%, -50%) scale(1.2)';
                  window._cursor.style.background = 'rgba(0, 255, 0, 0.8)'; // Green for middle click
                  window._cursor.style.boxShadow = '0 0 10px rgba(0, 255, 0, 0.5)';
                }
              });

              await this.page.mouse.down({ button: 'middle' });
              this.isMiddleMouseDown = true;

              await this.page.waitForTimeout(250);
            } catch (e) {
              console.debug('Middle-click-hold animation failed:', e);
              await this.page.mouse.down({ button: 'middle' });
              this.isMiddleMouseDown = true;
            }
            break;

          case ':middle-click-release':
            try {
              await this.page.evaluate(() => {
                if (window._cursor) {
                  window._cursor.style.transform = 'translate(-50%, -50%) scale(1)';
                  window._cursor.style.background = 'rgba(255, 0, 0, 0.5)';
                  window._cursor.style.boxShadow = 'none';
                }
              });

              await this.page.mouse.up({ button: 'middle' });
              this.isMiddleMouseDown = false;

              // Green ripple for middle click
              await this.page.evaluate(({ x, y }) => {
                const ripple = document.createElement('div');
                ripple.style.cssText = `
                  position: fixed;
                  left: ${x}px;
                  top: ${y}px;
                  width: 20px;
                  height: 20px;
                  background: rgba(0, 255, 0, 0.3);
                  border-radius: 50%;
                  pointer-events: none;
                  z-index: 999998;
                  animation: rabbitize-ripple 0.6s ease-out;
                `;
                document.body.appendChild(ripple);
                setTimeout(() => ripple.remove(), 600);
              }, {
                x: this.currentMouseX,
                y: this.currentMouseY
              });

              await this.page.waitForTimeout(150);
            } catch (e) {
              console.debug('Middle-click-release animation failed:', e);
              await this.page.mouse.up({ button: 'middle' });
              this.isMiddleMouseDown = false;
            }
            break;


          case ':rabbit-eyes-DISABLED':
            const [_rabbitEyes, prompt, x1, y1, x2, y2] = command;
            let bucketPath;

            // Take a screenshot first to ensure we have the current state
            const preState = await this.captureState(`${commandIndex}-pre-${command[0]}`);

            // Wait for the screenshot to be uploaded
            await this.firebase.waitForUploads();

            // Get the latest screenshot path from the preState
            if (!preState?.screenshotPath) {
              throw new Error('Failed to capture screenshot for analysis');
            }

            // Check if we have coordinates for cropping
            if (x1 && y1 && x2 && y2) {
              const rect = {
                left: Math.min(Number(x1), Number(x2)),
                right: Math.max(Number(x1), Number(x2)),
                top: Math.min(Number(y1), Number(y2)),
                bottom: Math.max(Number(y1), Number(y2))
              };

              // Take a new screenshot for cropping
              const timestamp = Date.now();
              // const tempPath = path.join(this.screenshotsPath, `${commandIndex}_${timestamp}_temp.png`);
              // const cropPath = path.join(this.screenshotsPath, `${commandIndex}_${timestamp}_crop.jpg`);
              const tempPath = path.join(this.screenshotsPath, `${commandIndex}_temp.png`);
              const cropPath = path.join(this.screenshotsPath, `${commandIndex}_crop.jpg`);

              try {
                // Take high-quality PNG first
                await this.page.screenshot({ path: tempPath });

                // Crop and convert to JPG
                await sharp(tempPath)
                  .extract({
                    left: Math.round(rect.left),
                    top: Math.round(rect.top),
                    width: Math.round(rect.right - rect.left),
                    height: Math.round(rect.bottom - rect.top)
                  })
                  .jpeg({ quality: 55 })
                  .toFile(cropPath);

                // Clean up temp file
                await fsPromises.unlink(tempPath);

                // Upload cropped image
                await this.firebase.uploadFile(cropPath);

                // Wait for the upload to complete
                await this.firebase.waitForUploads();

                // Use the cropped image path instead
                const fullCropPath = preState.screenshotPath.replace(/-pre-.*\.jpg$/, '_crop.jpg');
                bucketPath = fullCropPath.split('rabbitize-runs/')[1];

                this.firebase.debug('Using cropped image path:', `clients/${bucketPath}`);
              } catch (e) {
                this.firebase.debug('Crop operation failed, falling back to full screenshot:', e);
                bucketPath = preState.screenshotPath.split('rabbitize-runs/')[1];
              }
            } else {
              bucketPath = preState.screenshotPath.split('rabbitize-runs/')[1];
              this.firebase.debug('Using full screenshot path:', preState.screenshotPath);
            }

            if (!bucketPath) {
              throw new Error(`Invalid screenshot path format: ${preState.screenshotPath}`);
            }

            // Get environment variables
            const utilityUrl = process.env.UTILITY_URL;
            const watershipDown = process.env.WATERSHIP_DOWN;

            // Debug environment variables and actual header value
            this.firebase.debug('Environment variables and header:', JSON.stringify({
              utilityUrl: utilityUrl || 'not set',
              actualHeader: {
                key: 'watership_down',
                value: watershipDown || 'not set'
              }
            }));

            if (!utilityUrl || !watershipDown) {
              throw new Error('Required environment variables not set');
            }


            let response;
            let lastError;
            let analysisResult;  // Declare at the top level of the command
            const maxRetries = 10;

            for (let attempt = 1; attempt <= maxRetries; attempt++) {
              try {
                // Create request details
                const headers = {
                  'Content-Type': 'application/json',
                  'watership_down': watershipDown
                };

                const body = JSON.stringify({
                  image_urls: [`clients/${bucketPath}`],
                  step_type: 'question',
                  prompt: prompt
                });

                // Debug request details with actual values
                this.firebase.debug('Request details:', JSON.stringify({
                  url: `${utilityUrl}/api/utility-llm`,
                  method: 'POST',
                  headers: headers,
                  body: body
                }, null, 2));

                // Make the request
                response = await fetch(`${utilityUrl}/api/utility-llm`, {
                  method: 'POST',
                  headers,
                  body
                });

                // Debug response details
                this.firebase.debug('Response details:', JSON.stringify({
                  status: response.status,
                  statusText: response.statusText,
                  headers: Object.fromEntries(response.headers.entries())
                }, null, 2));

                // Log the raw response for debugging
                const responseText = await response.text();
                this.firebase.debug('Raw API response:', responseText);

                if (!response.ok) {
                  const error = new Error(`API call failed: ${response.status} ${response.statusText}`);
                  error.responseText = responseText;
                  error.status = response.status;
                  throw error;
                }

                // Parse the response text back to JSON
                try {
                  analysisResult = JSON.parse(responseText);
                  this.firebase.debug('Parsed analysis result:', JSON.stringify(analysisResult, null, 2));
                  this.firebase.debug('Answer to display:', analysisResult.answer);
                } catch (e) {
                  const error = new Error(`Failed to parse API response: ${e.message}`);
                  error.responseText = responseText;
                  throw error;
                }

                // If we got here, we succeeded, so break the retry loop
                break;

              } catch (error) {
                lastError = error;
                // If it's not a 502/503 or it's the last attempt, rethrow
                if ((!error.status || (error.status !== 502 && error.status !== 503)) || attempt === maxRetries) {
                  throw error;
                }
                // Add exponential backoff delay between retries
                const delayMs = 5000 * Math.pow(2, attempt - 1); // 5s, 10s, 20s
                this.firebase.debug(`Retry attempt ${attempt} failed, waiting ${delayMs / 1000}s before next attempt`);
                await new Promise(resolve => setTimeout(resolve, delayMs));
              }
            }


            // let response;
            // let lastError;
            // let analysisResult;  // Declare at the top level of the command
            // const maxRetries = 3;

            // for (let attempt = 1; attempt <= maxRetries; attempt++) {
            //   try {
            //     // Create request details
            //     const headers = {
            //       'Content-Type': 'application/json',
            //       'watership_down': watershipDown
            //     };

            //     const body = JSON.stringify({
            //       image_urls: [`clients/${bucketPath}`],
            //       step_type: 'question',
            //       prompt: prompt
            //     });

            //     // Debug request details with actual values
            //     this.firebase.debug('Request details:', JSON.stringify({
            //       url: `${utilityUrl}/api/utility-llm`,
            //       method: 'POST',
            //       headers: headers,
            //       body: body
            //     }, null, 2));

            //     // Make the request
            //     response = await fetch(`${utilityUrl}/api/utility-llm`, {
            //       method: 'POST',
            //       headers,
            //       body
            //     });

            //     // Debug response details
            //     this.firebase.debug('Response details:', JSON.stringify({
            //       status: response.status,
            //       statusText: response.statusText,
            //       headers: Object.fromEntries(response.headers.entries())
            //     }, null, 2));

            //     // Log the raw response for debugging
            //     const responseText = await response.text();
            //     this.firebase.debug('Raw API response:', responseText);

            //     if (!response.ok) {
            //       const error = new Error(`API call failed: ${response.status} ${response.statusText}`);
            //       error.responseText = responseText;
            //       error.status = response.status;
            //       throw error;
            //     }

            //     // Parse the response text back to JSON
            //     try {
            //       analysisResult = JSON.parse(responseText);
            //       this.firebase.debug('Parsed analysis result:', JSON.stringify(analysisResult, null, 2));
            //       this.firebase.debug('Answer to display:', analysisResult.answer);
            //     } catch (e) {
            //       const error = new Error(`Failed to parse API response: ${e.message}`);
            //       error.responseText = responseText;
            //       throw error;
            //     }

            //     // If we got here, we succeeded, so break the retry loop
            //     break;

            //   } catch (error) {
            //     lastError = error;
            //     // If it's not a 502/503 or it's the last attempt, rethrow
            //     if ((!error.status || (error.status !== 502 && error.status !== 503)) || attempt === maxRetries) {
            //       throw error;
            //     }
            //     await new Promise(resolve => setTimeout(resolve, 5000));
            //   }
            // }

            // Only proceed with modal if we have a valid result
            if (analysisResult?.answer) {
              // Display the answer in a modal overlay
              try {
                await Promise.all([
                  this.firebase.setPhase(analysisResult.answer),
                  this.firestore.setPhase(analysisResult.answer)
                ]);

                await this.page.evaluate((answer) => {
                  if (!answer) {
                    console.error('No answer provided to modal');
                    return;
                  }
                  const modal = document.createElement('div');
                  modal.style.cssText = `
                      position: fixed;
                      top: 50%;
                      left: 50%;
                      transform: translate(-50%, -50%);
                      background: rgba(0, 0, 0, 0.9);
                      color: white;
                      padding: 40px;
                      border-radius: 10px;
                      font-family: monospace;
                      font-size: 40px;
                      font-weight: 700;
                      max-width: 80%;
                      z-index: 999999;
                      text-align: center;
                      box-shadow: 0 0 20px rgba(0,0,0,0.5);
                    `;
                  modal.textContent = answer;
                  modal.id = 'rabbit-eyes-modal'; // Add an ID for reliable removal
                  document.body.appendChild(modal);
                  console.log('Modal created with answer:', answer);
                }, analysisResult.answer);
              } catch (e) {
                console.debug('Modal creation failed:', e);
              }

              // Wait a moment for the modal to be visible
              await this.page.waitForTimeout(500);

              // Take a screenshot with the modal
              const postStateWithModal = await this.captureState(`${commandIndex}-modal-${command[0]}`);

              // Always remove the modal immediately after screenshot
              try {
                await this.page.evaluate(() => {
                  const modal = document.querySelector('#rabbit-eyes-modal');
                  if (modal) {
                    modal.remove();
                    console.log('Modal removed successfully');
                  } else {
                    // Fallback removal by style if ID not found
                    const modalByStyle = document.querySelector('div[style*="z-index: 999999"]');
                    if (modalByStyle) {
                      modalByStyle.remove();
                      console.log('Modal removed by style selector');
                    } else {
                      console.log('No modal found to remove');
                    }
                  }
                });
                // Add a small wait to ensure modal is fully removed
                await this.page.waitForTimeout(100);
              } catch (e) {
                console.debug('Modal removal failed:', e);
                // Additional attempt to force remove if first try fails
                try {
                  await this.page.evaluate(() => {
                    document.querySelectorAll('div[style*="z-index: 999999"]').forEach(el => el.remove());
                  });
                } catch (e2) {
                  console.debug('Forced modal removal also failed:', e2);
                }
              }

              // Store analysis results in result object for Firebase/Firestore
              result = {
                success: true,
                artifacts: {
                  analysis: analysisResult,
                  screenshot: preState.screenshotPath,
                  screenshotWithAnswer: postStateWithModal.screenshotPath,
                  prompt: prompt
                }
              };
            }
            break;

          case ':print-pdf':
            try {
              // Command format: [":print-pdf" "dialog"|"auto" "a4"|"letter" "portrait"|"landscape"]
              const mode = command[1] || 'auto';  // dialog or auto
              const format = command[2] || 'a4';  // a4 or letter
              const orientation = command[3] || 'portrait'; // portrait or landscape

              if (mode === 'dialog') {
                // Handle actual print dialog
                await this.page.evaluate(() => {
                  console.log('Please save PDF to the "rabbitize-runs" folder in your working directory');
                  window.print();
                });

                return {
                  success: true,
                  message: 'Print dialog opened - PDFs saved to rabbitize-runs will be uploaded at session end'
                };
              } else {
                // Direct PDF generation - save to both working directory and session directory
                const timestamp = Date.now();
                const filename = `rabbitize-${timestamp}.pdf`;

                // Save to working directory root for easy debugging
                const rootPdfPath = path.join(process.cwd(), filename);

                // Also save to session directory for upload
                const sessionPdfPath = path.join(this.basePath, 'pdfs', filename);

                // Ensure pdfs directory exists
                await fsPromises.mkdir(path.join(this.basePath, 'pdfs'), { recursive: true });

                // Generate the PDF
                await this.page.pdf({
                  path: rootPdfPath,  // Save to root first
                  format: format,
                  landscape: orientation === 'landscape',
                  printBackground: true,
                  margin: {
                    top: '20px',
                    right: '20px',
                    bottom: '20px',
                    left: '20px'
                  }
                });

                // Copy to session directory
                await fsPromises.copyFile(rootPdfPath, sessionPdfPath);

                // Upload to Firebase
                try {
                  await this.firebase.uploadFile(sessionPdfPath);
                  this.firebase.log(`PDF uploaded to Firebase: ${filename}`);
                } catch (uploadError) {
                  this.firebase.warn(`Failed to upload PDF: ${uploadError.message}`);
                }

                return {
                  success: true,
                  message: `PDF saved locally (${rootPdfPath}) and uploaded to Firebase`,
                  artifacts: {
                    pdf: rootPdfPath,
                    sessionPdf: sessionPdfPath
                  }
                };
              }
            } catch (error) {
              return {
                success: false,
                error: `Failed to generate PDF: ${error.message}`
              };
            }

          case ':width':
            const currentSize = await this.page.viewportSize();
            await this.page.setViewportSize({
              width: currentSize.width + Number(command[1]),
              height: currentSize.height
            });
            break;

          case ':height':
            const viewportSize = await this.page.viewportSize();
            await this.page.setViewportSize({
              width: viewportSize.width,
              height: viewportSize.height + Number(command[1])
            });
            break;

          case ':back':
            try {
              this.firebase.log('Navigating back in browser history');
              await this.page.evaluate(() => {
                if (window._commandOverlay) {
                  window._commandOverlay.textContent = '[":back"]';
                  window._commandOverlay.style.opacity = '1';
                }
              });

              // Go back in browser history
              await this.page.goBack();

              // Allow time for navigation and page loading
              await this.page.waitForTimeout(500);

              return {
                success: true,
                message: 'Navigated back in browser history'
              };
            } catch (error) {
              this.firebase.error('Back navigation failed:', error);
              return {
                success: false,
                error: `Failed to navigate back: ${error.message}`
              };
            }
            break;

          case ':forward':
            try {
              this.firebase.log('Navigating forward in browser history');
              await this.page.evaluate(() => {
                if (window._commandOverlay) {
                  window._commandOverlay.textContent = '[":forward"]';
                  window._commandOverlay.style.opacity = '1';
                }
              });

              // Go forward in browser history
              await this.page.goForward();

              // Allow time for navigation and page loading
              await this.page.waitForTimeout(500);

              return {
                success: true,
                message: 'Navigated forward in browser history'
              };
            } catch (error) {
              this.firebase.error('Forward navigation failed:', error);
              return {
                success: false,
                error: `Failed to navigate forward: ${error.message}`
              };
            }
            break;

          case ':set-download-path':
            try {
              const [_cmd, downloadPath] = command;
              if (!downloadPath) {
                return {
                  success: false,
                  error: 'Download path is required'
                };
              }
              
              // Resolve path relative to current working directory if not absolute
              const resolvedPath = path.isAbsolute(downloadPath) 
                ? downloadPath 
                : path.join(process.cwd(), downloadPath);
              
              // Create directory if it doesn't exist
              await fsPromises.mkdir(resolvedPath, { recursive: true });
              
              this.downloadPath = resolvedPath;
              this.firebase.log(`Download path set to: ${resolvedPath}`);
              
              return {
                success: true,
                message: `Downloads will be saved to: ${resolvedPath}`
              };
            } catch (error) {
              this.firebase.error('Failed to set download path:', error);
              return {
                success: false,
                error: error.message
              };
            }
            break;

          case ':set-upload-file':
            try {
              const [_cmd, ...filePaths] = command;
              if (!filePaths || filePaths.length === 0) {
                return {
                  success: false,
                  error: 'At least one file path is required'
                };
              }
              
              // Handle both single file and multiple files
              const resolvedPaths = [];
              for (const filePath of filePaths) {
                // Resolve path relative to current working directory if not absolute
                const resolvedPath = path.isAbsolute(filePath) 
                  ? filePath 
                  : path.join(process.cwd(), filePath);
                
                // Check if file exists
                const fileExists = await fsPromises.access(resolvedPath).then(() => true).catch(() => false);
                if (!fileExists) {
                  return {
                    success: false,
                    error: `File not found: ${resolvedPath}`
                  };
                }
                resolvedPaths.push(resolvedPath);
              }
              
              // Store as array for multiple files or single path for one file
              this.uploadFilePath = resolvedPaths.length === 1 ? resolvedPaths[0] : resolvedPaths;
              this.firebase.log(`Upload file(s) set to: ${resolvedPaths.join(', ')}`);
              
              return {
                success: true,
                message: `${resolvedPaths.length} file(s) ready for upload`,
                files: resolvedPaths
              };
            } catch (error) {
              this.firebase.error('Failed to set upload file:', error);
              return {
                success: false,
                error: error.message
              };
            }
            break;

          case ':url':
            try {
              const targetUrl = command[1];
              if (!targetUrl) {
                return {
                  success: false,
                  error: 'No URL provided for :url command'
                };
              }

              this.firebase.log('Navigating to URL:', targetUrl);
              await this.page.evaluate((url) => {
                if (window._commandOverlay) {
                  window._commandOverlay.textContent = `[":url" "${url}"]`;
                  window._commandOverlay.style.opacity = '1';
                }
              }, targetUrl);

              // Define navigation timeout
              const navigationTimeoutMs = 60000; // 60 seconds

              // Navigate to the specified URL with timeout
              await this.page.goto(targetUrl, {
                timeout: navigationTimeoutMs,
                waitUntil: 'domcontentloaded'
              });

              // Allow time for page to load completely
              await this.page.waitForTimeout(500);

              return {
                success: true,
                message: `Navigated to ${targetUrl}`,
                url: targetUrl
              };
            } catch (error) {
              this.firebase.error('URL navigation failed:', error);

              // Check if this is a timeout error
              if (error.name === 'TimeoutError' || error.message.includes('timeout')) {
                // Handle the timeout by showing the timeout page
                return await this.handleNavigationTimeout(command[1], 60000, error);
              }

              return {
                success: false,
                error: `Failed to navigate to URL: ${error.message}`
              };
            }
            break;

          case ':extract':
            // Check if we have 4 coordinates for rectangle selection
            if (command.length === 5) {
              const [_extract, x1, y1, x2, y2] = command;
              const rect = {
                left: Math.min(Number(x1), Number(x2)),
                right: Math.max(Number(x1), Number(x2)),
                top: Math.min(Number(y1), Number(y2)),
                bottom: Math.max(Number(y1), Number(y2))
              };

              // Take a screenshot for cropping

              const timestamp = Date.now();
              // const tempPath = path.join(this.screenshotsPath, `${commandIndex}_${timestamp}_temp.png`);
              // const cropPath = path.join(this.screenshotsPath, `${commandIndex}_${timestamp}_crop.jpg`);
              const tempPath = path.join(this.screenshotsPath, `${commandIndex}_temp.png`);
              const cropPath = path.join(this.screenshotsPath, `${commandIndex}_crop.jpg`);

              try {
                // Take high-quality PNG first
                await this.page.screenshot({ path: tempPath });

                // Crop and convert to JPG
                await sharp(tempPath)
                  .extract({
                    left: Math.round(rect.left),
                    top: Math.round(rect.top),
                    width: Math.round(rect.right - rect.left),
                    height: Math.round(rect.bottom - rect.top)
                  })
                  .jpeg({ quality: 55 })
                  .toFile(cropPath);

                // Clean up temp file
                await fsPromises.unlink(tempPath);

                // Upload cropped image
                await this.firebase.uploadFile(cropPath);
              } catch (e) {
                this.firebase.debug('Crop operation failed:', e);
              }

              // Continue with existing text extraction code...
              this.firebase.debug('⛏️  Extracting from rectangle: 🟫 ', JSON.stringify(rect));

              // Get text within the rectangular area
              const areaText = await this.page.evaluate((rect) => {
                console.log('Browser: Sampling rectangle:', rect);

                // Create a range for text selection
                const range = document.createRange();
                const seenText = new Set();
                const results = [];

                // Sample points in the rectangle
                const stepSize = 10;
                for (let x = rect.left; x <= rect.right; x += stepSize) {
                  for (let y = rect.top; y <= rect.bottom; y += stepSize) {
                    const elements = document.elementsFromPoint(x, y);
                    elements.forEach(el => {
                      // Skip if element is not a text container
                      if (!el.textContent?.trim()) return;

                      // Get all text nodes within this element
                      const walker = document.createTreeWalker(
                        el,
                        NodeFilter.SHOW_TEXT,
                        null,
                        false
                      );

                      let node;
                      while (node = walker.nextNode()) {
                        try {
                          range.setStart(node, 0);
                          range.setEnd(node, node.length);
                          const clientRects = range.getClientRects();

                          for (let i = 0; i < clientRects.length; i++) {
                            const r = clientRects[i];
                            // Check if this text rect intersects with our selection rect
                            if (!(r.right < rect.left ||
                              r.left > rect.right ||
                              r.bottom < rect.top ||
                              r.top > rect.bottom)) {

                              const text = node.textContent.trim();
                              if (text && !seenText.has(text)) {
                                seenText.add(text);
                                results.push({
                                  text,
                                  bounds: {
                                    left: r.left,
                                    right: r.right,
                                    top: r.top,
                                    bottom: r.bottom
                                  }
                                });
                              }
                              break; // Found intersection, move to next node
                            }
                          }
                        } catch (e) {
                          console.log('Error processing text node:', e);
                          continue;
                        }
                      }
                    });
                  }
                }

                console.log('Browser: Found text nodes:', results.length);
                return results;
              }, rect);

              this.firebase.debug('💎  Found text nodes:', areaText.length);

              result = {
                success: true,
                artifacts: {
                  elements: areaText,
                  bounds: rect
                }
              };

              // Show summary in overlay
              const textCount = areaText.length;
              await Promise.all([
                this.firebase.setPhase(`Extracted ${textCount} unique text segments from selection`),
                this.firestore.setPhase(`Extracted ${textCount} unique text segments from selection`)
              ]);
            } else {
              // Original single-point extraction code...
              // Original single-point extraction code
              const elementInfo = await this.page.evaluate(({ x, y }) => {
                const element = document.elementFromPoint(x, y);
                if (!element) return null;

                return {
                  text: element.textContent?.trim(),
                  tag: element.tagName.toLowerCase(),
                  id: element.id || null,
                  className: element.className || null
                };
              }, {
                x: this.currentMouseX,
                y: this.currentMouseY
              });

              if (!elementInfo) {
                return {
                  success: false,
                  error: 'No element found at cursor position'
                };
              }

              result = {
                success: true,
                artifacts: {
                  element: elementInfo
                }
              };

              await Promise.all([
                this.firebase.setPhase(`Extracted: ${elementInfo.text}`),
                this.firestore.setPhase(`Extracted: ${elementInfo.text}`)
              ]);
            }
            break;



            case ':rabbit-eyes': // temp
              // Check if we have 4 coordinates for rectangle selection
              if (command.length === 5) {
                const [_extract, prompt, x1, y1, x2, y2] = command;
                const rect = {
                  left: Math.min(Number(x1), Number(x2)),
                  right: Math.max(Number(x1), Number(x2)),
                  top: Math.min(Number(y1), Number(y2)),
                  bottom: Math.max(Number(y1), Number(y2))
                };

                // Take a screenshot for cropping

                const timestamp = Date.now();
                // const tempPath = path.join(this.screenshotsPath, `${commandIndex}_${timestamp}_temp.png`);
                // const cropPath = path.join(this.screenshotsPath, `${commandIndex}_${timestamp}_crop.jpg`);
                const tempPath = path.join(this.screenshotsPath, `${commandIndex}_temp.png`);
                const cropPath = path.join(this.screenshotsPath, `${commandIndex}_crop.jpg`);

                try {
                  // Take high-quality PNG first
                  await this.page.screenshot({ path: tempPath });

                  // Crop and convert to JPG
                  await sharp(tempPath)
                    .extract({
                      left: Math.round(rect.left),
                      top: Math.round(rect.top),
                      width: Math.round(rect.right - rect.left),
                      height: Math.round(rect.bottom - rect.top)
                    })
                    .jpeg({ quality: 55 })
                    .toFile(cropPath);

                  // Clean up temp file
                  await fsPromises.unlink(tempPath);

                  // Upload cropped image
                  await this.firebase.uploadFile(cropPath);
                } catch (e) {
                  this.firebase.debug('Crop operation failed:', e);
                }

                // Continue with existing text extraction code...
                this.firebase.debug('⛏️  Extracting from rectangle: 🟫 ', JSON.stringify(rect));

                // Get text within the rectangular area
                const areaText = await this.page.evaluate((rect) => {
                  console.log('Browser: Sampling rectangle:', rect);

                  // Create a range for text selection
                  const range = document.createRange();
                  const seenText = new Set();
                  const results = [];

                  // Sample points in the rectangle
                  const stepSize = 10;
                  for (let x = rect.left; x <= rect.right; x += stepSize) {
                    for (let y = rect.top; y <= rect.bottom; y += stepSize) {
                      const elements = document.elementsFromPoint(x, y);
                      elements.forEach(el => {
                        // Skip if element is not a text container
                        if (!el.textContent?.trim()) return;

                        // Get all text nodes within this element
                        const walker = document.createTreeWalker(
                          el,
                          NodeFilter.SHOW_TEXT,
                          null,
                          false
                        );

                        let node;
                        while (node = walker.nextNode()) {
                          try {
                            range.setStart(node, 0);
                            range.setEnd(node, node.length);
                            const clientRects = range.getClientRects();

                            for (let i = 0; i < clientRects.length; i++) {
                              const r = clientRects[i];
                              // Check if this text rect intersects with our selection rect
                              if (!(r.right < rect.left ||
                                r.left > rect.right ||
                                r.bottom < rect.top ||
                                r.top > rect.bottom)) {

                                const text = node.textContent.trim();
                                if (text && !seenText.has(text)) {
                                  seenText.add(text);
                                  results.push({
                                    text,
                                    bounds: {
                                      left: r.left,
                                      right: r.right,
                                      top: r.top,
                                      bottom: r.bottom
                                    }
                                  });
                                }
                                break; // Found intersection, move to next node
                              }
                            }
                          } catch (e) {
                            console.log('Error processing text node:', e);
                            continue;
                          }
                        }
                      });
                    }
                  }

                  console.log('Browser: Found text nodes:', results.length);
                  return results;
                }, rect);

                this.firebase.debug('💎  Found text nodes:', areaText.length);

                result = {
                  success: true,
                  artifacts: {
                    elements: areaText,
                    bounds: rect
                  }
                };

                // Show summary in overlay
                const textCount = areaText.length;
                await Promise.all([
                  this.firebase.setPhase(`Extracted ${textCount} unique text segments from selection`),
                  this.firestore.setPhase(`Extracted ${textCount} unique text segments from selection`)
                ]);
              } else {
                // Original single-point extraction code...
                // Original single-point extraction code
                const elementInfo = await this.page.evaluate(({ x, y }) => {
                  const element = document.elementFromPoint(x, y);
                  if (!element) return null;

                  return {
                    text: element.textContent?.trim(),
                    tag: element.tagName.toLowerCase(),
                    id: element.id || null,
                    className: element.className || null
                  };
                }, {
                  x: this.currentMouseX,
                  y: this.currentMouseY
                });

                if (!elementInfo) {
                  return {
                    success: false,
                    error: 'No element found at cursor position'
                  };
                }

                result = {
                  success: true,
                  artifacts: {
                    element: elementInfo
                  }
                };

                await Promise.all([
                  this.firebase.setPhase(`Extracted: ${elementInfo.text}`),
                  this.firestore.setPhase(`Extracted: ${elementInfo.text}`)
                ]);
              }
              break;



          case ':extract-page':
            // Extract all content from the page in a structured way
            const pageContent = await this.page.evaluate(() => {
              function getNodeText(node) {
                return node.textContent?.trim() || '';
              }

              function getNodeLevel(node) {
                const match = node.tagName.match(/H(\d)/i);
                return match ? parseInt(match[1]) : null;
              }

              function processNode(node, indentLevel = 0) {
                let markdown = '';
                const tag = node.tagName?.toLowerCase();

                // Skip invisible elements
                const style = window.getComputedStyle(node);
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
                  return '';
                }

                // Handle different element types
                switch (tag) {
                  case 'h1':
                  case 'h2':
                  case 'h3':
                  case 'h4':
                  case 'h5':
                  case 'h6':
                    const level = getNodeLevel(node);
                    markdown += `\n${'#'.repeat(level)} ${getNodeText(node)}\n`;
                    break;

                  case 'p':
                    const text = getNodeText(node);
                    if (text) markdown += `\n${text}\n`;
                    break;

                  case 'ul':
                  case 'ol':
                    markdown += '\n';
                    Array.from(node.children).forEach((li, index) => {
                      const bullet = tag === 'ul' ? '*' : `${index + 1}.`;
                      markdown += `${' '.repeat(indentLevel)}${bullet} ${getNodeText(li)}\n`;
                    });
                    break;

                  case 'table':
                    markdown += '\n';
                    // Process table header
                    const headers = Array.from(node.querySelectorAll('th')).map(th => th.textContent.trim());
                    if (headers.length) {
                      markdown += `| ${headers.join(' | ')} |\n`;
                      markdown += `| ${headers.map(() => '---').join(' | ')} |\n`;
                    }
                    // Process table rows
                    Array.from(node.querySelectorAll('tr')).forEach(tr => {
                      const cells = Array.from(tr.querySelectorAll('td')).map(td => td.textContent.trim());
                      if (cells.length) {
                        markdown += `| ${cells.join(' | ')} |\n`;
                      }
                    });
                    break;

                  case 'pre':
                  case 'code':
                    const codeText = getNodeText(node);
                    if (codeText) markdown += `\n\`\`\`\n${codeText}\n\`\`\`\n`;
                    break;

                  case 'blockquote':
                    const quoteText = getNodeText(node);
                    if (quoteText) markdown += `\n> ${quoteText}\n`;
                    break;

                  default:
                    // Recursively process child nodes for other elements
                    if (node.children && node.children.length) {
                      Array.from(node.children).forEach(child => {
                        markdown += processNode(child, indentLevel + 2);
                      });
                    }
                }

                return markdown;
              }

              // Start processing from body
              let content = processNode(document.body);

              // Clean up extra newlines and spaces
              content = content.replace(/\n{3,}/g, '\n\n')
                .replace(/^\s+|\s+$/g, '');

              return content;
            });

            // Store extraction results
            result = {
              success: true,
              artifacts: {
                content: pageContent,
                format: 'markdown'
              }
            };

            // Show summary in overlay
            const lineCount = pageContent.split('\n').length;
            await Promise.all([
              this.firebase.setPhase(`Extracted ${lineCount} lines of content in Markdown format`),
              this.firestore.setPhase(`Extracted ${lineCount} lines of content in Markdown format`)
            ]);
            break;

          default:
            return { success: false, error: `Unknown command: ${command[0]}` };
        }

        // After command completes, reset signal
        await this.page.evaluate(() => {
          if (window._timecodeCorder) {
            Array.from(window._timecodeCorder.children).forEach(pixel => {
              pixel.style.background = 'black';
            });
          }
        });

        // After command completes but before final state capture
        if (this.stabilityDetector && this.stabilityOptions.enabled) {
          try {
            await this.firebase.setPhase('waiting_for_stability');
            await this.stabilityDetector.waitForStability();
            // Reset timeout counter on success
            this.stabilityTimeoutCount = 0;
          } catch (error) {
            // Log stability timeout but don't fail the command
            this.firebase.warn('Stability wait failed:', error);

            // Increment timeout counter
            this.stabilityTimeoutCount++;

            // Check if we should disable stability detection
            if (this.stabilityTimeoutCount >= this.stabilityTimeoutThreshold) {
              this.firebase.log(`Disabling stability detection after ${this.stabilityTimeoutCount} consecutive timeouts`);
              this.stabilityOptions.enabled = false;

              // Also log to console for visibility
              console.log(chalk.yellow(`🐴 Stability: AUTO-DISABLED after ${this.stabilityTimeoutCount} consecutive timeouts`));
            } else {
              // Stop the detector to prevent cascading failures
              if (this.stabilityDetector) {
                await this.stabilityDetector.stop();
                // Re-create the detector for next time
                this.stabilityDetector = new StabilityDetector(this.page, {
                  enabled: true,
                  waitTime: this.stabilityOptions.waitTime,
                  sensitivity: this.stabilityOptions.sensitivity,
                  timeout: this.stabilityOptions.timeout,
                  interval: this.stabilityOptions.interval,
                  frameCount: this.stabilityOptions.frameCount,
                  downscaleWidth: this.stabilityOptions.downscaleWidth
                });
              }
            }
          }
        }

        // Take post-stability screenshot and track its timestamp
        const postStabilityTimestamp = Date.now();
        await this.firebase.setPhase('taking_post_stability_screenshot', {
          commandIndex,
          stabilityEnabled: !!(this.stabilityDetector && this.stabilityOptions.enabled),
          timestamp: postStabilityTimestamp
        });

        // Take screenshot after command with timeout
        //const tempPath = path.join(this.screenshotsPath, `${commandIndex}_${Date.now()}_temp.png`);
        const tempPath = path.join(this.screenshotsPath, `${commandIndex}_temp.png`);
        const screenshotPath = path.join(this.screenshotsPath, `${commandIndex}.jpg`);

        // Take initial screenshot as PNG for best quality before processing
        await this.page.screenshot({ path: tempPath });

        // Now capture postState using the stable screenshot
        const postState = await this.captureState(`${commandIndex}-post-${command[0]}`);
        const postMetrics = await getResourceMetrics(this.page);

        // Capture DOM elements and their coordinates for this step
        try {
          // Create directory for DOM coordinates data if it doesn't exist
          const domCoordsDir = path.join(this.basePath, 'dom_coords');
          await fsPromises.mkdir(domCoordsDir, { recursive: true });

          // Capture DOM elements with coordinates
          const domElements = await this.capturePageElements();

          if (domElements) {
            // Save to a JSON file with the command index in the filename
            const domCoordsPath = path.join(domCoordsDir, `dom_coords_${commandIndex}.json`);
            await fsPromises.writeFile(
              domCoordsPath,
              JSON.stringify(domElements, null, 2)
            );
            this.firebase.debug(`Saved DOM coordinates for command ${commandIndex} to ${domCoordsPath}`);

            // Also save the same data to latest.json in the parent directory
            const latestPath = path.join(this.basePath, 'latest.json');
            await fsPromises.writeFile(
              latestPath,
              JSON.stringify(domElements, null, 2)
            );
          }
        } catch (domCaptureError) {
          // Log error but don't interrupt the command execution
          this.firebase.warn(`Failed to capture DOM elements for command ${commandIndex}:`, domCaptureError);
        }

        // If the case statement returned a specific result, store it
        if (result?.artifacts || result?.success !== undefined) {
          currentCommand.output = result;
        }

        // Calculate total duration including stability wait
        const endTimestamp = Date.now();
        const duration = endTimestamp - timestamp;


        // Extract DOM to markdown for diffing
const domMarkdown = await this.page.evaluate(() => {
  // Get viewport dimensions
  const viewport = {
    left: 0,
    top: 0,
    right: window.innerWidth,
    bottom: window.innerHeight
  };

  console.log('Extracting text from viewport:', viewport);

  // Prepare text collection with position data for sorting
  const textItems = [];
  let traversalIndex = 0;

  try {
    // Traverse all text nodes in the document
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);

    while (walker.nextNode()) {
      const node = walker.currentNode;
      const text = node.textContent.trim();
      if (!text) continue;

      // Check visibility by inspecting ancestor styles
      let el = node.parentElement;
      let isVisible = true;
      while (el) {
        const style = window.getComputedStyle(el);
        if (
          style.display === 'none' ||
          style.visibility === 'hidden' ||
          style.opacity === '0'
        ) {
          isVisible = false;
          break;
        }
        el = el.parentElement;
      }
      if (!isVisible) continue;

      // Get position data for the text node
      const range = document.createRange();
      range.selectNodeContents(node);
      const rects = range.getClientRects();
      if (rects.length === 0) continue;

      // Check if the text intersects the viewport
      let intersects = false;
      for (const rect of rects) {
        if (
          rect.right >= viewport.left &&
          rect.left <= viewport.right &&
          rect.bottom >= viewport.top &&
          rect.top <= viewport.bottom
        ) {
          intersects = true;
          break;
        }
      }
      if (!intersects) continue;

      // Store text with position and traversal index
      const rect = rects[0]; // Use the first rectangle for sorting
      textItems.push({
        text,
        y: rect.top, // For vertical sorting
        x: rect.left, // For horizontal sorting
        index: traversalIndex++ // For stable tiebreaking
      });
    }

    // Sort text items: y-position, then x-position, then traversal order
    textItems.sort((a, b) => {
      const yDiff = Math.floor(a.y / 10) - Math.floor(b.y / 10); // 10px vertical bands
      if (yDiff !== 0) return yDiff;
      const xDiff = Math.floor(a.x / 10) - Math.floor(b.x / 10); // 10px horizontal bands
      if (xDiff !== 0) return xDiff;
      return a.index - b.index; // Stable sort using traversal order
    });

    // Construct consistent output format
    let textContent = '';
    let lastYBand = -999;

    textItems.forEach((item) => {
      const yBand = Math.floor(item.y / 10);
      if (yBand > lastYBand) {
        if (textContent) textContent += '\n';
        lastYBand = yBand;
      }
      textContent += item.text + ' ';
    });

    // Clean up the text
    textContent = textContent
      .replace(/\s+/g, ' ')      // Normalize whitespace
      .replace(/\n +/g, '\n')    // Remove leading spaces after newlines
      .replace(/\n{3,}/g, '\n\n') // Limit consecutive newlines
      .trim();                   // Trim start/end whitespace

    console.log(`Extracted ${textItems.length} text items from viewport`);
    return textContent;
  } catch (error) {
    console.error('Error in viewport text extraction:', error);
    return `Error extracting viewport text: ${error.message}`;
  }
});


        // // Extract DOM to markdown for diffing
        // const domMarkdown = await this.page.evaluate(() => {
        //   // Get viewport dimensions
        //   const viewport = {
        //     left: 0,
        //     top: 0,
        //     right: window.innerWidth,
        //     bottom: window.innerHeight
        //   };

        //   console.log('Extracting text from viewport:', viewport);

        //   // Prepare text collection with position data for sorting
        //   const textItems = [];
        //   const seenTextWithContext = new Set(); // Changed from seenTexts for more robust deduplication
        //   const processedElements = new Set();

        //   try {
        //     // Create range for text selection
        //     const range = document.createRange();

        //     // Sample points in viewport with a grid
        //     const stepSize = 5; // High sampling density
        //     for (let x = viewport.left; x <= viewport.right; x += stepSize) {
        //       for (let y = viewport.top; y <= viewport.bottom; y += stepSize) {
        //         // Get elements at this point - wrapped in try/catch
        //         let elements = [];
        //         try {
        //           elements = document.elementsFromPoint(x, y);
        //         } catch (pointError) {
        //           console.log('Error getting elements at point:', pointError);
        //         }

        //         // Process each element
        //         for (let i = 0; i < elements.length; i++) {
        //           const el = elements[i];

        //           // Skip if we've seen this element already
        //           const getElementPath = (el) => {
        //             let path = '';
        //             while (el && el.nodeType === Node.ELEMENT_NODE) {
        //               let selector = el.nodeName.toLowerCase();
        //               if (el.id) {
        //                 selector += '#' + el.id;
        //                 path = selector + (path ? ' > ' + path : '');
        //                 break;
        //               } else {
        //                 let sibling = el;
        //                 let siblingIndex = 1;
        //                 while (sibling = sibling.previousElementSibling) {
        //                   siblingIndex++;
        //                 }
        //                 selector += ':nth-child(' + siblingIndex + ')';
        //               }
        //               path = selector + (path ? ' > ' + path : '');
        //               el = el.parentNode;
        //             }
        //             return path;
        //           };

        //           const elementId = getElementPath(el);
        //           if (processedElements.has(elementId)) {
        //             continue;
        //           }
        //           processedElements.add(elementId);

        //           // Skip if element has no text content
        //           if (!el.textContent?.trim()) {
        //             continue;
        //           }

        //           // Check visibility - skip invisible elements
        //           let isVisible = true;
        //           try {
        //             const style = window.getComputedStyle(el);
        //             if (style.display === 'none' ||
        //                 style.visibility === 'hidden' ||
        //                 style.opacity === '0') {
        //               isVisible = false;
        //             }
        //           } catch (styleError) {
        //             console.log('Error checking element style:', styleError);
        //           }

        //           if (!isVisible) {
        //             continue;
        //           }

        //           // Process text nodes within this element
        //           try {
        //             const walker = document.createTreeWalker(
        //               el,
        //               NodeFilter.SHOW_TEXT,
        //               null,
        //               false
        //             );

        //             let node;
        //             while ((node = walker.nextNode())) {
        //               // Extract text from this node
        //               const text = node.textContent.trim();
        //               if (!text) continue;

        //               // Get position data for the text
        //               let rect = null;
        //               try {
        //                 range.setStart(node, 0);
        //                 range.setEnd(node, node.length);
        //                 const rects = range.getClientRects();

        //                 if (rects.length > 0) {
        //                   rect = rects[0];
        //                 }
        //               } catch (rangeError) {
        //                 console.log('Error getting text range:', rangeError);
        //               }

        //               if (!rect) {
        //                 continue;
        //               }

        //               // Check if in viewport
        //               if (rect.right >= viewport.left &&
        //                   rect.left <= viewport.right &&
        //                   rect.bottom >= viewport.top &&
        //                   rect.top <= viewport.bottom) {

        //                 // More robust text deduplication with position context
        //                 // Round positions to nearest 5px to allow for small variations
        //                 const textWithContext = `${text}|${Math.round(rect.top/5)*5}|${Math.round(rect.left/5)*5}`;
        //                 if (seenTextWithContext.has(textWithContext)) {
        //                   continue;
        //                 }
        //                 seenTextWithContext.add(textWithContext);

        //                 // Store with position info for sorting
        //                 textItems.push({
        //                   text,
        //                   tag: el.tagName.toLowerCase(),
        //                   y: rect.top, // For sorting vertically
        //                   x: rect.left, // For sorting horizontally within same y
        //                   bounds: {
        //                     left: rect.left,
        //                     right: rect.right,
        //                     top: rect.top,
        //                     bottom: rect.bottom
        //                   }
        //                 });
        //               }
        //             }
        //           } catch (walkerError) {
        //             console.log('Error walking text nodes:', walkerError);
        //           }
        //         }
        //       }
        //     }

        //     // More deterministic sorting with fixed precision and tiebreakers
        //     textItems.sort((a, b) => {
        //       // First sort by vertical position with fixed precision (10px bands)
        //       const yDiff = Math.floor(a.y / 10) - Math.floor(b.y / 10);
        //       if (yDiff !== 0) return yDiff;

        //       // Then by horizontal position with fixed precision
        //       const xDiff = Math.floor(a.x / 10) - Math.floor(b.x / 10);
        //       if (xDiff !== 0) return xDiff;

        //       // Finally by text content for complete determinism
        //       return a.text.localeCompare(b.text);
        //     });

        //     // Consistent output format - simple newline-separated text
        //     // This is more consistent than trying to recreate markdown structure
        //     let textContent = '';
        //     let lastYBand = -999;

        //     textItems.forEach(item => {
        //       const yBand = Math.floor(item.y / 10);

        //       // Add newline between vertical position bands
        //       if (yBand > lastYBand) {
        //         if (textContent) textContent += '\n';
        //         lastYBand = yBand;
        //       }

        //       // Add the text
        //       textContent += item.text + ' ';
        //     });

        //     // Clean up the text
        //     textContent = textContent
        //       .replace(/\s+/g, ' ')      // Normalize whitespace
        //       .replace(/\n +/g, '\n')    // Remove leading spaces after newlines
        //       .replace(/\n{3,}/g, '\n\n') // Limit consecutive newlines
        //       .trim();                   // Trim start/end whitespace

        //     console.log(`Extracted ${textItems.length} text items from viewport`);
        //     return textContent;
        //   } catch (error) {
        //     console.error('Error in viewport text extraction:', error);
        //     return `Error extracting viewport text: ${error.message}`;
        //   }
        // });

                // Extract DOM to markdown for diffing
                const domMarkdown2 = await this.page.evaluate(() => {
                  function getNodeText(node) {
                    return node.textContent?.trim() || '';
                  }

                  function getNodeLevel(node) {
                    const match = node.tagName.match(/H(\d)/i);
                    return match ? parseInt(match[1]) : null;
                  }

                  function processNode(node, indentLevel = 0) {
                    let markdown = '';
                    const tag = node.tagName?.toLowerCase();

                    // Skip invisible elements
                    const style = window.getComputedStyle(node);
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
                      return '';
                    }

                    // Handle different element types
                    switch (tag) {
                      case 'h1':
                      case 'h2':
                      case 'h3':
                      case 'h4':
                      case 'h5':
                      case 'h6':
                        const level = getNodeLevel(node);
                        markdown += `\n${'#'.repeat(level)} ${getNodeText(node)}\n`;
                        break;

                      case 'p':
                        const text = getNodeText(node);
                        if (text) markdown += `\n${text}\n`;
                        break;

                      case 'ul':
                      case 'ol':
                        markdown += '\n';
                        Array.from(node.children).forEach((li, index) => {
                          const bullet = tag === 'ul' ? '*' : `${index + 1}.`;
                          markdown += `${' '.repeat(indentLevel)}${bullet} ${getNodeText(li)}\n`;
                        });
                        break;

                      case 'table':
                        markdown += '\n';
                        // Process table header
                        const headers = Array.from(node.querySelectorAll('th')).map(th => th.textContent.trim());
                        if (headers.length) {
                          markdown += `| ${headers.join(' | ')} |\n`;
                          markdown += `| ${headers.map(() => '---').join(' | ')} |\n`;
                        }
                        // Process table rows
                        Array.from(node.querySelectorAll('tr')).forEach(tr => {
                          const cells = Array.from(tr.querySelectorAll('td')).map(td => td.textContent.trim());
                          if (cells.length) {
                            markdown += `| ${cells.join(' | ')} |\n`;
                          }
                        });
                        break;

                      case 'pre':
                      case 'code':
                        const codeText = getNodeText(node);
                        if (codeText) markdown += `\n\`\`\`\n${codeText}\n\`\`\`\n`;
                        break;

                      case 'blockquote':
                        const quoteText = getNodeText(node);
                        if (quoteText) markdown += `\n> ${quoteText}\n`;
                        break;

                      default:
                        // Recursively process child nodes for other elements
                        if (node.children && node.children.length) {
                          Array.from(node.children).forEach(child => {
                            markdown += processNode(child, indentLevel + 2);
                          });
                        }
                    }

                    return markdown;
                  }

                  // Start processing from body
                  let content = processNode(document.body);

                  // Clean up extra newlines and spaces
                  content = content.replace(/\n{3,}/g, '\n\n')
                                 .replace(/^\s+|\s+$/g, '');

                  return content;
                });

        // Merge any case-specific results with the final result
        result = {
          success: true,
          preState,
          postState,
          metrics: {
            pre: preMetrics,
            post: postMetrics
          },
          timing: {
            start: timestamp,
            end: endTimestamp,
            duration
          },
          // Include the DOM markdown
          domMarkdown,
          domMarkdown2,
          // Include any case-specific output
          ...(currentCommand.output || {})
        };

        // Save the latest DOM markdown to latest.md in the root folder
        try {
          const latestMdPath = path.join(this.basePath, 'latest.md');
          await fsPromises.writeFile(latestMdPath, domMarkdown2 || domMarkdown || '');
          // this.debug('Saved DOM markdown to latest.md');
        } catch (error) {
          this.warn('Failed to save latest.md', error);
        }

        // Save per-step DOM markdown to dom_snapshots folder
        try {
          const domSnapshotPath = path.join(this.domSnapshotsPath, `dom_${commandIndex}.md`);
          await fsPromises.writeFile(domSnapshotPath, domMarkdown2 || domMarkdown || '');
          // this.debug(`Saved DOM snapshot to dom_${commandIndex}.md`);
        } catch (error) {
          this.warn(`Failed to save dom_${commandIndex}.md`, error);
        }

        // Update command timestamp with final result and timing
        currentCommand.output = result;
        currentCommand.endTimestamp = endTimestamp;
        currentCommand.duration = duration;

        // Verify the temp file was just created (within last second)
        const tempStats = await fsPromises.stat(tempPath);
        const tempAge = Date.now() - tempStats.mtimeMs;
        if (tempAge > 1000) {
          this.firebase.warn('Post-stability screenshot may be stale', {
            commandIndex,
            tempAge,
            expectedTimestamp: postStabilityTimestamp,
            actualTimestamp: tempStats.mtimeMs
          });
        }

        // Generate thumbnail
        const thumbPath = path.join(this.screenshotsPath, `${commandIndex}_thumb.jpg`);
        await sharp(tempPath)
          .resize(500, null)
          .jpeg({ quality: 80 })
          .toFile(thumbPath);

        // Create zoomed version if we have mouse coordinates
        let zoomPath = null;
        if (this.currentMouseX !== undefined && this.currentMouseY !== undefined) {
          zoomPath = await this.createZoomedScreenshot(tempPath, this.currentMouseX, this.currentMouseY, command);
          if (zoomPath) {
            await this.firebase.uploadFile(zoomPath);
          }
        }

        // Convert main screenshot to JPG and clean up temp PNG
        await sharp(tempPath)
          .jpeg({ quality: 35 })
          .toFile(screenshotPath);

        // Log completion and reset phase
        await this.firebase.setPhase('post_stability_screenshot_complete', {
          commandIndex,
          originalTimestamp: postStabilityTimestamp,
          processingTime: Date.now() - postStabilityTimestamp,
          outputs: {
            main: screenshotPath,
            thumb: thumbPath,
            zoom: zoomPath
          }
        });

        await fsPromises.unlink(tempPath);

        // Save command result with timeout for both Firebase and Firestore
        await Promise.all([
          this.withTimeout(
            this.firebase.uploadFile(screenshotPath),
            25000,
            'Upload screenshot'
          ),
          this.withTimeout(
            this.firebase.uploadFile(thumbPath),
            25000,
            'Upload thumbnail'
          ),
          this.withTimeout(
            this.firebase.saveCommandResult(command, result, {
              pre: preState,
              post: postState,
              screenshot: screenshotPath,
              screenshotZoom: zoomPath,
              screenshotThumb: thumbPath,
              output: currentCommand.output  // Include the command-specific output
            }, commandIndex),
            5000,
            'Save command result to Firebase'
          ),
          this.withTimeout(
            this.firestore.addCommand(command, result, {
              pre: preState,
              post: postState,
              screenshot: screenshotPath,
              screenshotZoom: zoomPath,
              screenshotThumb: thumbPath,
              output: currentCommand.output  // Include the command-specific output
            }),
            5000,
            'Save command result to Firestore'
          ),
          // Update last-command-idx at the root level
          this.withTimeout(
            this.firebase.db.ref(`${this.firebase.getBasePath()}/last-command-idx`).set(commandIndex),
            5000,
            'Update last command index'
          )
        ]);

        // Increment counter only after command is fully executed
        this.commandCounter++;
        await this.firebase.db.ref(`${this.firebase.getBasePath()}/command-status/${commandIndex}`).set('done');

        // Record metrics for this command
        const commandDuration = Date.now() - timestamp;
        // await writeStepMetric(
        //   this.sessionId,
        //   commandIndex,
        //   Array.isArray(command) ? command.join(' ') : command,
        //   commandDuration,
        //   this.clientId,
        //   this.testId
        // );

        return result;
      } catch (error) {
        // Log the error - safely handle undefined error
        console.error('Execute error:', error?.message || 'Unknown error');
        await this.logger.error('Command failed:', error?.message || 'Unknown error');

        // Update command status to error
        try {
          await this.firebase.db.ref(`${this.firebase.getBasePath()}/command-status/${commandIndex}`).set('error');
        } catch (e) {
          console.error('Failed to set error status:', e?.message || 'Unknown error');
        }

        // Clear the queue if there are pending operations
        if (this.queueManager && this.queueManager.hasItems()) {
          console.log('Clearing queue due to command failure');
          this.queueManager.clearQueue();
        }

        // Handle specific "expected" behaviors - safely check error message
        if (error?.message) {
          if (error.message.includes('Execution context was destroyed')) {
            console.log('Note: Page navigation occurred during command execution');
            return { success: true, navigationOccurred: true };
          }

          if (error.message.includes('page: no object with guid')) {
            console.log('Note: Browser context changed during command execution');
            return { success: true, contextChanged: true };
          }
        }

        // For all other errors, return failure state with safe error message
        return {
          success: false,
          error: error?.message || 'Unknown error occurred',
          commandIndex, // Include command index in error response
          rawError: error // Include raw error for debugging if needed
        };
      }
    } catch (outerError) {
      // Handle outer error safely
      ////TEST////console.error('Outer execute error:', outerError?.message || 'Unknown error');
      ////TEST////await this.logger.error('Command failed (outer):', outerError?.message || 'Unknown error');

      // Still try to update command status and clear queue
      try {
        await this.firebase.db.ref(`${this.firebase.getBasePath()}/command-status/${commandIndex}`).set('error');
      } catch (e) {
        console.error('Failed to set error status (outer):', e?.message || 'Unknown error');
      }

      if (this.queueManager && this.queueManager.hasItems()) {
        console.log('Clearing queue due to outer error');
        this.queueManager.clearQueue();
      }

      // Return a safe error response
      return {
        success: false,
        error: outerError?.message || 'Unknown error in command execution',
        commandIndex,
        rawError: outerError // Include raw error for debugging if needed
      };
    }
  }

  async end() {
    // Clear screenshot interval at end
    if (this.screenshotInterval) {
      clearInterval(this.screenshotInterval);
      this.screenshotInterval = null;
    }

    // Clean up frame buffer for this session
    if (global.lastFrameBuffer) {
      const sessionKey = `${this.clientId}/${this.testId}/${this.sessionId}`;
      delete global.lastFrameBuffer[sessionKey];
    }

    if (!this.browser) {
      return { success: false, error: 'Session not initialized' };
    }

    try {
      await Promise.all([
        this.firebase.setPhase('ending_session'),
        this.firestore.setPhase('ending_session')
      ]);

      // // Write final browser duration metric
      // this.firebase.log('Writing final browser duration metric...');
      // try {
      //   await writeBrowserDurationMetric(this.sessionId, this.clientId, this.testId);
      //   this.firebase.log('Successfully wrote browser duration metric');
      // } catch (error) {
      //   this.firebase.error('Failed to write browser duration metric:', error);
      // }

      // Video processing has been moved to after video.saveAs() call
      // This section was attempting to process video before it was saved

      // Continue with the rest of end() method...

      this.firebase.log('PlaywrightSession: Finalizing session...');
      try {
        // Stop stability detector first
        if (this.stabilityDetector) {
          this.firebase.log('Stopping stability detector...');
          await this.stabilityDetector.stop();
          this.stabilityDetector = null;
        }

        // Set a flag to track if we need to process video
        let videoSaved = false;

        try {
          this.firebase.log('Attempting to save video recording...');

          if (this.context && this.context.pages()[0] && (this.sessionId !== 'interactive' || global.argv?.processVideo)) {
            const page = this.context.pages()[0];

            // Get video object
            this.firebase.log('Getting video object...');
            const video = await page.video();

            if (video) {
              this.firebase.log('Video object acquired, stopping recording by closing page...');

              // Stop recording by closing the page first
              await page.close();
              this.firebase.log('Page closed, recording stopped');

              // Now let Playwright handle saving the video
              this.firebase.log('Waiting for video to be saved...');
              await video.saveAs(path.join(this.videoPath, 'session.webm'));
              this.firebase.log('Video saved successfully');
              videoSaved = true;

              // Convert webm to mp4 if processVideo is true
              if (global.argv.processVideo) {
                this.firebase.log('Processing video conversion...');
                const inputPath = path.join(this.videoPath, 'session.webm');
                const outputPath = path.join(this.videoPath, 'session.mp4');

                try {
                  await this.processBasicVideo(inputPath, outputPath);

                  // Only process clips if createClipSegments is true
                  if (this.createClipSegments) {
                    this.firebase.log('Clip processing enabled - creating scene and timestamp based clips...');

                    // Create all necessary directories
                    const clipsPath = path.join(this.videoPath, 'clips');
                    const commandsTsPath = path.join(this.videoPath, 'commands_ts');
                    await Promise.all([
                      fsPromises.mkdir(clipsPath, { recursive: true }),
                      fsPromises.mkdir(commandsTsPath, { recursive: true })
                    ]);

                    // Save color pattern mapping for reference
                    await fsPromises.writeFile(
                      path.join(this.basePath, 'color-patterns.json'),
                      JSON.stringify(Object.fromEntries(this.colorPatterns), null, 2)
                    );

                    // Process both types of clips
                    await Promise.all([
                      this.processSceneBasedClips(outputPath, clipsPath),
                      this.processTimestampBasedClips(outputPath, commandsTsPath)
                    ]);
                  } else {
                    this.firebase.log('Clip processing disabled - skipping scene and timestamp based clips');
                  }

                  // Create 4x speed version (part of basic processing)
                  await this.create4xSpeedVersion(outputPath);
                } catch (conversionError) {
                  this.firebase.error('Video conversion failed:', conversionError);
                  // Continue execution even if conversion fails
                }
              }

              // Create small cover GIF
              const webmPath = path.join(this.videoPath, 'session.webm');
              const coverGifPath = path.join(this.videoPath, 'cover.gif');

              try {
                this.firebase.log('Creating small cover GIF...');

                // Verify source webm file exists first
                try {
                  const webmStats = await fsPromises.stat(webmPath);
                  this.firebase.log(`Source webm file verified: ${webmPath} (${webmStats.size} bytes)`);

                  if (webmStats.size === 0) {
                    throw new Error('Source webm file has zero size');
                  }
                } catch (webmError) {
                  throw new Error(`Source webm file unavailable: ${webmError.message}`);
                }

                // Execute ffmpeg with more detailed logging
                this.firebase.log(`Running ffmpeg command to generate cover.gif`);
                const ffmpegOutput = await execAsync(`ffmpeg -ss 2 -i "${webmPath}" \
                  -vf "fps=12,scale=-1:200:flags=lanczos,crop=200:200:(iw-200)/2:0,split[s0][s1];[s0]palettegen=max_colors=96:reserve_transparent=0:stats_mode=diff[p];[s1][p]paletteuse=dither=sierra2_4a:diff_mode=rectangle" \
                  -t 47 \
                  -loop 0 \
                  -y "${coverGifPath}" 2>&1`);

                this.firebase.log(`FFmpeg completed`);

                // Verify file was created and log details
                try {
                  const fileStats = await fsPromises.stat(coverGifPath);
                  this.firebase.log(`Cover GIF created successfully: ${coverGifPath} (${fileStats.size} bytes)`);

                  // Log the exact directory contents
                  const videoFiles = await fsPromises.readdir(this.videoPath);
                  this.firebase.log(`Video directory contents: ${JSON.stringify(videoFiles)}`);

                  // Try to manually copy it to another location as a test
                  const backupPath = path.join(this.basePath, 'cover-backup.gif');
                  await fsPromises.copyFile(coverGifPath, backupPath);
                  this.firebase.log(`Cover GIF backup created at: ${backupPath}`);
                } catch (verifyError) {
                  this.firebase.error(`Failed to verify cover GIF: ${verifyError.message}`);
                }
              } catch (gifError) {
                this.firebase.warn(`Failed to create cover GIF: ${gifError.message}`, {
                  command: `ffmpeg -ss 2 -i "${webmPath}" -vf "fps=12,scale=-1:70:flags=lanczos,crop=70:70:(iw-70)/2:0,split[s0][s1];[s0]palettegen=max_colors=96:reserve_transparent=0:stats_mode=diff[p];[s1][p]paletteuse=dither=sierra2_4a:diff_mode=rectangle" -t 45 -loop 0 -y "${coverGifPath}"`,
                  error: gifError
                });

                // Try alternative: create JPG thumbnail instead
                try {
                  this.firebase.log('Attempting to create JPG thumbnail instead...');
                  const jpgPath = path.join(this.videoPath, 'cover.jpg');

                  // Use ffmpeg to extract a single frame as JPG
                  await execAsync(`ffmpeg -ss 5 -i "${webmPath}" \
                    -vf "scale=-1:70:flags=lanczos,crop=70:70:(iw-70)/2:0" \
                    -frames:v 1 -y "${jpgPath}" 2>&1`);

                  const jpgStats = await fsPromises.stat(jpgPath);
                  this.firebase.log(`JPG thumbnail created as fallback: ${jpgPath} (${jpgStats.size} bytes)`);
                } catch (jpgError) {
                  this.firebase.error(`Failed to create JPG thumbnail: ${jpgError.message}`);
                }

                // Don't throw - this is a non-critical enhancement
              }
            } else {
              throw new Error('No video object available from page');
            }
          } else {
            throw new Error('No valid page context for video saving');
          }
        } catch (videoError) {
          this.firebase.error('Failed to save video:', videoError);
          throw videoError; // Rethrow to prevent further processing if video save fails
        }

        // Always close context and browser, even if video save fails
        if (this.context) {
          await Promise.race([
            this.context.close(),
            new Promise((_, reject) => setTimeout(() => reject(new Error('Context close timeout')), 5000))
          ]).catch(e => this.firebase.warn('Error closing context:', e));
        }

        if (this.browser) {
          await Promise.race([
            this.browser.close(),
            new Promise((_, reject) => setTimeout(() => reject(new Error('Browser close timeout')), 5000))
          ]).catch(e => this.firebase.warn('Error closing browser:', e));
        }

        // Clear references
        this.page = null;
        this.context = null;
        this.browser = null;

        // Only proceed with video processing if we successfully saved the video
        if (!videoSaved) {
          this.firebase.warn('Skipping video processing as video was not saved successfully');
        }

        // Write command timestamps for later video splitting
        const timestampPath = path.join(this.basePath, 'commands.json');
        await fsPromises.writeFile(timestampPath, JSON.stringify(this.commandTimestamps, null, 2));

        // Convert the single video file
        const inputPath = path.join(this.videoPath, 'session.webm');
        const outputPath = path.join(this.videoPath, 'session.mp4');
        const clipsPath = path.join(this.videoPath, 'clips');

        if (await fsPromises.access(inputPath).then(() => true).catch(() => false)) {
          this.firebase.log('Converting webm to mp4...');
          await Promise.all([
            this.firebase.setPhase('converting_to_mp4'),
            this.firestore.setPhase('converting_to_mp4')
          ]);

          // Skip all video processing if process-video is false
          if (!global.argv.processVideo) {
            this.firebase.log('Video processing skipped (--process-video=false)');

            // Before the final phase change, add job_json
            let job_json;
            if (this.originalBatchJson) {
              job_json = this.originalBatchJson;
            } else if (Array.isArray(this.executedCommands) && this.executedCommands.length > 0) {
              job_json = {
                url: this.initialUrl,
                commands: this.executedCommands
              };
            }

            if (job_json) {
              await Promise.all([
                this.firebase.setJobJson(job_json).catch(error => {
                  this.firebase.warn('Failed to save job_json to Firebase:', error);
                }),
                this.firestore.setSessionData({ job_json }).catch(error => {
                  console.error('Failed to save job_json to Firestore:', error);
                })
              ]);
            }

            const files = await fsPromises.readdir(this.basePath);
            for (const file of files) {
              const filePath = path.join(this.basePath, file);
              const stats = await fsPromises.stat(filePath);
              if (!stats.isDirectory()) {
                await this.withTimeout(
                  this.firebase.uploadFile(filePath),
                  25000,
                  `Upload ${file}`
                );
              }
            }

            // Clear metrics interval
            if (this.metricsInterval) {
              clearInterval(this.metricsInterval);
              this.metricsInterval = null;
            }

            // Save metrics log
            const metricsPath = path.join(this.basePath, 'metrics.json');
            await fsPromises.writeFile(metricsPath, JSON.stringify(this.metricsLog, null, 2));

            // Wait for all pending operations in both databases
            await Promise.all([
              this.firebase.waitForUploads(),
              this.firestore.waitForPendingOperations()
            ]);

            // Set final states in both databases
            await Promise.all([
              this.firebase.setRunningState(false),
              this.firestore.cleanupSession()
            ]);

            // Update spy path to indicate session has ended
            // try {
            //   await this.firebase.db.ref(`spy/${this.clientId}/${this.testId}`).set("images/spy-ended.jpg");
            //   this.firebase.log('Updated spy path to ended image');
            // } catch (spyError) {
            //   this.firebase.warn('Failed to update spy ended path:', spyError);
            //   // Don't fail session end if spy update fails
            // }

            // Mark session as fully complete before setting phase
            this.isFullyComplete = true;

            await Promise.all([
              this.firebase.setPhase('complete'),
              this.firestore.setPhase('complete')
            ]);

            // Create final execution summary
            const executionSummary = {
              success: true,
              clientId: this.clientId,
              testId: this.testId,
              sessionId: this.sessionId,
              initialUrl: this.initialUrl,
              commandCount: this.executedCommands.length,
              hasVideo: await fsPromises.access(path.join(this.videoPath, 'session.webm')).then(() => true).catch(() => false),
              metrics: {
                totalCommands: this.commandTimestamps.length,
                totalDuration: Date.now() - this.processStartTime,
                commandsExecuted: this.executedCommands.length
              },
              artifacts: {
                basePath: this.basePath,
                videoPath: this.videoPath,
                screenshotsPath: this.screenshotsPath
              }
            };

            // Write summary to stdout for Cloud Workflows to capture
            console.log('EXECUTION_SUMMARY=' + JSON.stringify(executionSummary));

            // Reset session state for next use
            this.page = null;
            this.context = null;
            this.browser = null;
            this.commandTimestamps = [];
            this.executedCommands = [];
            this.currentMouseX = undefined;
            this.currentMouseY = undefined;
            this.metricsLog = [];
            this.colorPatterns = new Map();
            this.firebase.log('PlaywrightSession: Success, ready for new session');

            // Save session metadata for historical tracking
            try {
              const sessionMetadata = {
                clientId: this.clientId,
                testId: this.testId,
                sessionId: this.sessionId,
                status: 'finished',
                startTime: this.processStartTime,
                endTime: Date.now(),
                duration: Date.now() - this.processStartTime,
                commandCount: this.commandCounter,
                phase: this.currentPhase || 'completed',
                hasVideo: fs.existsSync(path.join(this.videoPath, 'session.webm')),
                hasScreenshots: fs.existsSync(this.screenshotsPath),
                initialUrl: this.initialUrl || '',
                timestamp: new Date().toISOString()
              };

              await fsPromises.writeFile(
                path.join(this.basePath, 'session-metadata.json'),
                JSON.stringify(sessionMetadata, null, 2)
              );
              this.firebase.log('Saved session metadata for historical tracking');
            } catch (error) {
              this.firebase.warn('Failed to save session metadata:', error);
            }

            // Stop stability detector if it exists
            if (this.stabilityDetector) {
              await this.stabilityDetector.stop();
              this.stabilityDetector = null;
            }

            return executionSummary;
          }

          // await execAsync(`ffmpeg -i "${inputPath}" \
          //       -c:v libx264 \
          //       -preset medium \
          //       -tune film \
          //       -threads 4 \
          //       -thread_type frame \
          //       -movflags +faststart \
          //       -bf 2 \
          //       -g 30 \
          //       -crf 28 \
          //       -maxrate 2M \
          //       -bufsize 16M \
          //       -max_muxing_queue_size 1024 \
          //   -y "${outputPath}"`);

          // Create clips directory
          await fsPromises.mkdir(clipsPath, { recursive: true });

          // Save color pattern mapping for reference
          await fsPromises.writeFile(
            path.join(this.basePath, 'color-patterns.json'),
            JSON.stringify(Object.fromEntries(this.colorPatterns), null, 2)
          );

          if (this.createClipSegments) {
            this.firebase.log('Detecting scene changes in tracking pixels...');
            await Promise.all([
              this.firebase.setPhase('detecting_scene_changes_from_tracking_pixels'),
              this.firestore.setPhase('detecting_scene_changes_from_tracking_pixels')
            ]);

            const framesPath = path.join(clipsPath, 'frames');
            await fsPromises.mkdir(framesPath, { recursive: true });

            // First pass: analyze the tracking pixel area for scene changes using original webm
            await execAsync(
              `ffmpeg -i "${outputPath}" ` +
              `-thread_type frame -max_muxing_queue_size 1024 ` +
              `-vf "crop=4:4:in_w-4:in_h-4,select='gt(scene,0.15)',metadata=print" ` +
              `-f null - 2> "${path.join(framesPath, 'scenes.txt')}"`
            );

            // Read the generated scenes file and create clips
            const scenesText = await fsPromises.readFile(path.join(framesPath, 'scenes.txt'), 'utf8');
            const sceneTimestamps = scenesText.split('\n')
              .filter(line => line.includes('pts_time:'))
              .map(line => {
                const match = line.match(/pts_time:([\d.]+)/);
                return match ? parseFloat(match[1]) : null;
              })
              .filter(Boolean);

            this.firebase.log('Creating clips from detected scenes...');
            await Promise.all([
              this.firebase.setPhase('creating_clips_from_detected_scenes'),
              this.firestore.setPhase('creating_clips_from_detected_scenes')
            ]);

            for (let i = 0; i < sceneTimestamps.length - 1; i++) {
              const startTime = sceneTimestamps[i];
              const endTime = sceneTimestamps[i + 1];
              const duration = endTime - startTime;

              // Find the command that was active during this clip
              const clipStartMs = startTime * 1000;
              const clipEndMs = endTime * 1000;
              const sessionStartTime = this.commandTimestamps[0]?.timestamp || 0;
              const relativeStartMs = clipStartMs + sessionStartTime;

              // Find the last command that started before or during this clip
              const activeCommand = this.commandTimestamps
                .filter(cmd => cmd.timestamp <= relativeStartMs)
                .pop();

              // Create a descriptive filename
              let clipName;
              if (activeCommand) {
                // Find the index of this command in the commandTimestamps array
                const commandIndex = this.commandTimestamps.findIndex(cmd => cmd.timestamp === activeCommand.timestamp);
                const commandName = Array.isArray(activeCommand.command)
                  ? activeCommand.command.join('-')
                  : activeCommand.command;
                clipName = `clip_${i + 1}_${commandIndex}_${commandName.replace(/[^a-zA-Z0-9-]/g, '_')}`;
              } else {
                clipName = `clip_${i + 1}_unknown`;
              }

              const createClipCommand = `ffmpeg -i "${outputPath}" \
              -ss ${startTime} \
              -t ${duration} \
              -c:v libx264 \
              -preset medium \
              -tune film \
              -threads 4 \
              -thread_type frame \
              -movflags +faststart \
              -bf 2 \
              -g 30 \
              -crf 28 \
              -maxrate 2M \
              -bufsize 16M \
              -max_muxing_queue_size 1024 \
              -y "${path.join(clipsPath, `${clipName}.mp4`)}"`;

              await execAsync(createClipCommand);
            }

            // Save clip mapping information
            const clipMapping = {
              sessionStartTime: this.commandTimestamps[0]?.timestamp,
              clips: sceneTimestamps.slice(0, -1).map((startTime, i) => ({
                clipNumber: i + 1,
                startTime: startTime,
                endTime: sceneTimestamps[i + 1],
                command: this.commandTimestamps
                  .filter(cmd => cmd.timestamp <= (startTime * 1000 + (this.commandTimestamps[0]?.timestamp || 0)))
                  .pop()?.command || null
              }))
            };

            await fsPromises.writeFile(
              path.join(clipsPath, 'clip_mapping.json'),
              JSON.stringify(clipMapping, null, 2)
            );

            // Group clips by command index and create command-based videos and GIFs
            this.firebase.log('Creating command-based videos and GIFs...');
            await Promise.all([
              this.firebase.setPhase('creating_command_videos_and_gifs'),
              this.firestore.setPhase('creating_command_videos_and_gifs')
            ]);

            // Create directories for command-based outputs
            const commandVideosPath = path.join(this.videoPath, 'command_videos');
            const commandGifsPath = path.join(this.videoPath, 'command_gifs');
            await fsPromises.mkdir(commandVideosPath, { recursive: true });
            await fsPromises.mkdir(commandGifsPath, { recursive: true });

            // Group clips by command index
            const clipsByCommand = new Map();
            for (const clip of clipMapping.clips) {
              if (!clip.command) continue;

              // Find command index from the command timestamps
              const commandIndex = this.commandTimestamps.findIndex(cmd =>
                JSON.stringify(cmd.command) === JSON.stringify(clip.command)
              );
              if (commandIndex === -1) continue;

              if (!clipsByCommand.has(commandIndex)) {
                clipsByCommand.set(commandIndex, []);
              }
              clipsByCommand.get(commandIndex).push(clip);
            }

            // Process each command group
            for (const [commandIndex, clips] of clipsByCommand) {
              try {
                // Sort clips by startTime
                clips.sort((a, b) => a.startTime - b.startTime);

                // Create a file list for concatenation
                const listPath = path.join(clipsPath, `command_${commandIndex}_list.txt`);
                const fileList = clips.map(clip => {
                  const clipName = `clip_${clip.clipNumber}_${commandIndex}_${Array.isArray(clip.command) ? clip.command.join('-') : clip.command}`.replace(/[^a-zA-Z0-9-]/g, '_');
                  return `file '${path.join(clipsPath, clipName)}.mp4'`;
                }).join('\n');
                await fsPromises.writeFile(listPath, fileList);

                // Create concatenated MP4 for this command
                const commandVideoPath = path.join(commandVideosPath, `command_${commandIndex}.mp4`);
                await execAsync(`ffmpeg -f concat -safe 0 -i "${listPath}" -c copy -thread_type frame -max_muxing_queue_size 1024 -y "${commandVideoPath}"`);

                // Create GIF from the MP4
                const commandGifPath = path.join(commandGifsPath, `command_${commandIndex}.gif`);
                await execAsync(`ffmpeg -i "${commandVideoPath}" \
                  -vf "fps=10,scale=600:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=128:reserve_transparent=0[p];[s1][p]paletteuse=dither=bayer:bayer_scale=3" \
                  -max_muxing_queue_size 1024 \
                  -y "${commandGifPath}"`);

                // Clean up list file
                await fsPromises.unlink(listPath);
              } catch (error) {
                this.firebase.warn(`Failed to process command ${commandIndex}:`, error);
                // Continue with next command even if this one fails
              }
            }

            // Cleanup
            await fsPromises.unlink(path.join(framesPath, 'scenes.txt'));
          }

          const commandsTsPath = path.join(this.videoPath, 'commands_ts');

          // // Add timestamp-based command clips
          // this.firebase.log('Creating timestamp-based command clips...');
          // await Promise.all([
          //   this.firebase.setPhase('creating_timestamp_based_command_clips'),
          //   this.firestore.setPhase('creating_timestamp_based_command_clips')
          // ]);

          // // Create directory for timestamp-based command clips
          // const commandsTsPath = path.join(this.videoPath, 'commands_ts');
          // await fsPromises.mkdir(commandsTsPath, { recursive: true });

          // // Process each command based on timestamps
          // for (let i = 0; i < this.commandTimestamps.length; i++) {
          //   const command = this.commandTimestamps[i];
          //   const nextCommand = this.commandTimestamps[i + 1];

          //   // Calculate start and end times relative to video start
          //   const videoStartTime = this.commandTimestamps[0].timestamp;
          //   const startOffset = (command.timestamp - videoStartTime) / 1000; // Convert to seconds

          //   // For end time, use either next command start or current command end
          //   let endOffset;
          //   if (nextCommand) {
          //     endOffset = (nextCommand.timestamp - videoStartTime) / 1000;
          //   } else if (command.endTimestamp) {
          //     endOffset = (command.endTimestamp - videoStartTime) / 1000;
          //   } else {
          //     // If no end time available, use a default duration
          //     endOffset = startOffset + 5; // 5 seconds default
          //   }

          //   const duration = endOffset - startOffset;

          //   // Skip if duration is invalid
          //   if (duration <= 0) {
          //     this.firebase.warn(`Skipping command ${i} due to invalid duration: ${duration}s`);
          //     continue;
          //   }

          //   try {
          //     // Create descriptive filename
          //     const commandName = Array.isArray(command.command)
          //       ? command.command.join('-')
          //       : command.command;
          //     const safeCommandName = commandName.replace(/[^a-zA-Z0-9-]/g, '_');

          //     const clipPath = path.join(commandsTsPath, `command_${i}.mp4`);

          //     // Extract clip using ffmpeg
          //     await execAsync(`ffmpeg -i "${outputPath}" \
          //       -ss ${startOffset} \
          //       -t ${duration} \
          //       -c:v libx264 \
          //       -preset medium \
          //       -tune film \
          //       -threads 4 \
          //       -thread_type frame \
          //       -movflags +faststart \
          //       -bf 2 \
          //       -g 30 \
          //       -crf 28 \
          //       -maxrate 2M \
          //       -bufsize 16M \
          //       -max_muxing_queue_size 1024 \
          //       -y "${clipPath}"`);

          //     // Also create a GIF version
          //     const gifPath = path.join(commandsTsPath, `command_${i}.gif`);
          //     await execAsync(`ffmpeg -i "${clipPath}" \
          //       -vf "fps=10,scale=600:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=128:reserve_transparent=0[p];[s1][p]paletteuse=dither=bayer:bayer_scale=3" \
          //       -max_muxing_queue_size 1024 \
          //       -y "${gifPath}"`);

          //   } catch (error) {
          //     this.firebase.warn(`Failed to create timestamp-based clip for command ${i}:`, error);
          //     // Continue with next command even if this one fails
          //   }
          // }

          // // Save timestamp mapping information
          // const tsMapping = {
          //   videoStartTime: this.commandTimestamps[0].timestamp,
          //   commands: this.commandTimestamps.map((cmd, index) => ({
          //     commandIndex: index,
          //     command: cmd.command,
          //     startTime: (cmd.timestamp - this.commandTimestamps[0].timestamp) / 1000,
          //     endTime: cmd.endTimestamp
          //       ? (cmd.endTimestamp - this.commandTimestamps[0].timestamp) / 1000
          //       : null,
          //     duration: cmd.duration ? cmd.duration / 1000 : null
          //   }))
          // };

          // await fsPromises.writeFile(
          //   path.join(commandsTsPath, 'timestamp_mapping.json'),
          //   JSON.stringify(tsMapping, null, 2)
          // );

          // Create 4x speed version
          // await Promise.all([
          //   this.firebase.setPhase('creating_4x_video_version'),
          //   this.firestore.setPhase('creating_4x_video_version')
          // ]);

          // try {
          //   await execAsync(`ffmpeg -i "${outputPath}" \
          //     -filter:v "setpts=0.25*PTS" \
          //         -c:v libx264 \
          //         -preset medium \
          //         -tune film \
          //         -threads 4 \
          //         -thread_type frame \
          //         -movflags +faststart \
          //         -bf 2 \
          //         -g 30 \
          //         -crf 28 \
          //         -maxrate 2M \
          //         -bufsize 16M \
          //         -max_muxing_queue_size 1024 \
          //     -y "${path.join(this.videoPath, 'session_4x.mp4')}"`);
          // } catch (error) {
          //   this.firebase.error('Failed to create 4x speed video:', error);
          //   // Continue execution even if 4x speed creation fails
          // }

        } // End of if block for video processing

        // Clear metrics interval
        if (this.metricsInterval) {
          clearInterval(this.metricsInterval);
          this.metricsInterval = null;
        }

        // Save metrics log
        const metricsPath = path.join(this.basePath, 'metrics.json');
        await fsPromises.writeFile(metricsPath, JSON.stringify(this.metricsLog, null, 2));

        // Upload session files
        await Promise.all([
          this.firebase.setPhase('uploading_files'),
          this.firestore.setPhase('uploading_files')
        ]);

      } catch (error) {
        this.firebase.error('PlaywrightSession: End process failed:', error);
        return { success: false, error: error.message };
      }

      // Clear metrics interval
      if (this.metricsInterval) {
        clearInterval(this.metricsInterval);
        this.metricsInterval = null;
      }

      // Save metrics log
      const metricsPath = path.join(this.basePath, 'metrics.json');
      await fsPromises.writeFile(metricsPath, JSON.stringify(this.metricsLog, null, 2));

      // Upload session files
      await Promise.all([
        this.firebase.setPhase('uploading_files'),
        this.firestore.setPhase('uploading_files')
      ]);
      this.firebase.log('Uploading session files...');

      const dirs = ['screenshots', 'video', 'clips', 'video/clips', 'video/segments', 'video/command_gifs', 'video/command_videos', 'video/commands_ts', 'dom_coords'];
      for (const dir of dirs) {
        const dirPath = path.join(this.basePath, dir);
        if (await fsPromises.access(dirPath).then(() => true).catch(() => false)) {
          await this.withTimeout(
            this.firebase.uploadFile(dirPath),
            45000,
            `Upload ${dir} directory`
          );
        }
      }

      // Upload root level files
      const files = await fsPromises.readdir(this.basePath);
      for (const file of files) {
        // Skip latest.jpg from live screenshots
        if (file === 'latest.jpg') continue;

        const filePath = path.join(this.basePath, file);
        const stats = await fsPromises.stat(filePath);
        if (!stats.isDirectory()) {
          await this.withTimeout(
            this.firebase.uploadFile(filePath),
            25000,
            `Upload ${file}`
          );
        }
      }

      await this.withTimeout(
        this.firebase.flush(),
        5000,
        'Flush logs'
      );

      // Try to create a sharp thumbnail at this point if it doesn't exist yet
      try {
        const coverGifPath = path.join(this.videoPath, 'cover.gif');
        const coverSharpPath = path.join(this.videoPath, 'cover-sharp.jpg');

        // Check if either thumbnail already exists
        const gifExists = await fsPromises.access(coverGifPath).then(() => true).catch(() => false);
        const sharpExists = await fsPromises.access(coverSharpPath).then(() => true).catch(() => false);

        if (!gifExists && !sharpExists) {
          this.firebase.log('No thumbnail found, attempting to create one with sharp...');

          // Try to find the first screenshot to use as thumbnail
          const screenshots = await fsPromises.readdir(this.screenshotsPath);
          if (screenshots.length > 0) {
            const firstScreenshot = path.join(this.screenshotsPath, screenshots[0]);

            // Create a square thumbnail from the screenshot
            await sharp(firstScreenshot)
              .resize(70, 70, { fit: 'cover', position: 'center' })
              .jpeg({ quality: 85 })
              .toFile(coverSharpPath);

            const stats = await fsPromises.stat(coverSharpPath);
            this.firebase.log(`Created fallback thumbnail from screenshot: ${coverSharpPath} (${stats.size} bytes)`);
          } else {
            this.firebase.log('No screenshots found for fallback thumbnail');
          }
        }
      } catch (fallbackError) {
        this.firebase.warn(`Failed to create fallback thumbnail: ${fallbackError.message}`);
      }

      // Before the final phase change, add job_json
      let job_json;
      if (this.originalBatchJson) {
        job_json = this.originalBatchJson;
      } else if (Array.isArray(this.executedCommands) && this.executedCommands.length > 0) {
        job_json = {
          url: this.initialUrl,
          commands: this.executedCommands
        };
      }

      if (job_json) {
        await Promise.all([
          this.firebase.setJobJson(job_json).catch(error => {
            // Silent - no-op
          }),
          this.firestore.setSessionData({ job_json }).catch(error => {
            // Silent - no-op
          })
        ]);
      }

      // Wait for all pending operations (no-ops in local mode)
      await Promise.all([
        this.firebase.waitForUploads(),
        this.firestore.waitForPendingOperations()
      ]);

      // Set final states (no-ops in local mode)
      await Promise.all([
        this.firebase.setRunningState(false),
        this.firestore.cleanupSession()
      ]);

      // Update spy path to indicate session has ended
      // try {
      //   await this.firebase.db.ref(`spy/${this.clientId}/${this.testId}`).set("images/spy-ended.jpg");
      //   this.firebase.log('Updated spy path to ended image');
      // } catch (spyError) {
      //   this.firebase.warn('Failed to update spy ended path:', spyError);
      //   // Don't fail session end if spy update fails
      // }

      // Mark session as fully complete before setting phase
      this.isFullyComplete = true;

      await Promise.all([
        this.firebase.setPhase('complete'),
        this.firestore.setPhase('complete')
      ]);

      // Create final execution summary
      const executionSummary = {
        success: true,
        clientId: this.clientId,
        testId: this.testId,
        sessionId: this.sessionId,
        initialUrl: this.initialUrl,
        commandCount: this.executedCommands.length,
        hasVideo: await fsPromises.access(path.join(this.videoPath, 'session.webm')).then(() => true).catch(() => false),
        metrics: {
          totalCommands: this.commandTimestamps.length,
          totalDuration: Date.now() - this.processStartTime,
          commandsExecuted: this.executedCommands.length
        },
        artifacts: {
          basePath: this.basePath,
          videoPath: this.videoPath,
          screenshotsPath: this.screenshotsPath
        }
      };

      // Write summary to stdout for Cloud Workflows to capture
      console.log('EXECUTION_SUMMARY=' + JSON.stringify(executionSummary));

      // Reset session state for next use
      this.page = null;
      this.context = null;
      this.browser = null;
      this.commandTimestamps = [];
      this.executedCommands = [];
      this.currentMouseX = undefined;
      this.currentMouseY = undefined;
      this.metricsLog = [];
      this.colorPatterns = new Map();
      this.firebase.log('PlaywrightSession: Success, ready for new session');

      // Save session metadata for historical tracking
      try {
        const sessionMetadata = {
          clientId: this.clientId,
          testId: this.testId,
          sessionId: this.sessionId,
          status: 'finished',
          startTime: this.processStartTime,
          endTime: Date.now(),
          duration: Date.now() - this.processStartTime,
          commandCount: this.commandCounter,
          phase: this.currentPhase || 'completed',
          hasVideo: fs.existsSync(path.join(this.videoPath, 'session.webm')),
          hasScreenshots: fs.existsSync(this.screenshotsPath),
          initialUrl: this.initialUrl || '',
          timestamp: new Date().toISOString()
        };

        await fsPromises.writeFile(
          path.join(this.basePath, 'session-metadata.json'),
          JSON.stringify(sessionMetadata, null, 2)
        );
        this.firebase.log('Saved session metadata for historical tracking');
      } catch (error) {
        this.firebase.warn('Failed to save session metadata:', error);
      }

      // Stop stability detector if it exists
      if (this.stabilityDetector) {
        await this.stabilityDetector.stop();
        this.stabilityDetector = null;
      }

      return executionSummary;
    } catch (error) {
      this.firebase.error('PlaywrightSession: End process failed:', error);
      return { success: false, error: error.message };
    }
  }

  // Update quickEnd to handle Firestore
  async quickEnd() {
    try {
      if (this.stabilityDetector) {
        await this.stabilityDetector.stop();
        this.stabilityDetector = null;
      }

      if (this.browser) {
        await this.browser.close().catch(e => this.firebase.warn('Error closing browser:', e));
        this.browser = null;
      }

      // Update both databases
      await Promise.all([
        this.firebase.setRunningState(false),
        this.firestore.cleanupSession()
      ]);

      return { success: true };
    } catch (error) {
      this.firebase.error('Quick end failed:', error);
      return { success: false, error: error.message };
    }
  }

  async saveToFirebase(data) {
    if (!this.firebaseEnabled) return;

    try {
      const db = admin.database();
      const basePath = this.getBasePath();
      const cleanData = { ...data };
      delete cleanData.command; // Remove single command if it exists

      // Write each field separately to avoid implicit reads
      await Promise.all(Object.entries(cleanData).map(([key, value]) =>
        db.ref(`${basePath}/${key}`).set(value)
      ));

      // Set timestamp and updatedAt separately
      await Promise.all([
        db.ref(`${basePath}/timestamp`).set(admin.database.ServerValue.TIMESTAMP),
        db.ref(`${basePath}/updatedAt`).set(new Date().toISOString())
      ]);

      return true;
    } catch (error) {
      console.error('Failed to save to Firebase:', error);
      return false;
    }
  }

  async setPhase(phase, details = {}) {
    // Update local phase tracking
    this.currentPhase = phase;

    try {
      // Update both Firebase and Firestore
      await Promise.all([
        this.firebase.setPhase(phase, details),
        this.firestore.setPhase(phase, details)
      ]);

      queueManager.setFirebasePhase(phase, details);

      // Notify about phase change
      if (typeof global.onPhaseChange === 'function') {
        global.onPhaseChange(this, phase);
      }
    } catch (error) {
      console.error('Failed to set phase:', error);
      throw error;
    }
  }

  // Add the quickEnd method
  quickEnd = quickEnd;

  getBasePath() {
    return `clients/${this.clientId}/${this.testId}/${this.sessionId}`;
  }

  async resetWithNewIds(clientId, testId, options = {}) {
    // Store current session ID for cleanup
    const oldSessionId = this._sessionId;
    if (oldSessionId) {
      this.temporarySessionIds.add(oldSessionId);
    }

    try {
      // First clean up existing resources
      await this.quickEnd();

      // Clear any intervals/timeouts
      if (this.metricsInterval) {
        clearInterval(this.metricsInterval);
        this.metricsInterval = null;
      }

      // Close existing browser/context if they exist
      if (this.browser) {
        await this.browser.close().catch(e => this.firebase.warn('Error closing browser:', e));
        this.browser = null;
      }

      // Update instance variables
      this.clientId = clientId;
      this.testId = testId;
      // Use SESSION_ID env var if available, otherwise use timestamp
      this._sessionId = global.argv?.['session-id'] || process.env.SESSION_ID || new Date().toISOString().replace(/[:.]/g, '-');

      // Update optional configuration
      this.showCommandOverlay = options.showOverlay ?? this.showCommandOverlay;
      this.createClipSegments = options.clipSegments ?? this.createClipSegments;

      // Reset all paths
      this.basePath = path.join(process.cwd(), 'rabbitize-runs', this.clientId, this.testId, this.sessionId);
      this.screenshotsPath = path.join(this.basePath, 'screenshots');
      this.videoPath = path.join(this.basePath, 'video');
      this.domSnapshotsPath = path.join(this.basePath, 'dom_snapshots');

      // Reset all state variables
      this.commandCounter = 0;
      this.commandTimestamps = [];
      this.executedCommands = [];
      this.currentMouseX = undefined;
      this.currentMouseY = undefined;
      this.metricsLog = [];
      this.colorPatterns = new Map();

      // Create new Firebase instance with new session ID
      this.firebase = new FirebaseManager(this.clientId, this.testId, this.sessionId);
      this.firestore = new FirestoreManager(this.clientId, this.testId, this.sessionId);

      // Clean local files for new session
      await this.cleanupLocalFiles();

      // Reset global reference
      global.currentPlaywrightSession = this;

      // Update global argv with any new options
      if (global.argv && options) {
        Object.assign(global.argv, {
          clientId,
          testId,
          showOverlay: options.showOverlay ?? global.argv.showOverlay,
          clipSegments: options.clipSegments ?? global.argv.clipSegments,
          processVideo: options.processVideo ?? global.argv.processVideo,
          exitOnEnd: options.exitOnEnd ?? global.argv.exitOnEnd,
          meta: options.meta ?? global.argv.meta
        });
      }

      // Clean up the old session after new one is initialized
      if (oldSessionId && oldSessionId !== this.sessionId) {
        await this.cleanupTemporarySession(oldSessionId);
      }

      return {
        success: true,
        sessionId: this.sessionId
      };
    } catch (error) {
      this.firebase.error('Reset failed:', error);
      return {
        success: false,
        error: error.message
      };
    }
  }

  // Add method to reset/start inactivity timer
  resetInactivityTimer() {
    if (this.inactivityTimeout) {
      clearTimeout(this.inactivityTimeout);
    }

    this.inactivityTimeout = setTimeout(async () => {
      try {
        // Use locally tracked phase instead of reading from Firebase
        if (this.currentPhase && this.currentPhase.startsWith('command-')) {
          this.firebase.log('Session inactive for 15 minutes - auto-ending');

          await this.firebase.setPhase('auto_end_inactivity', {
            reason: 'Session inactive for 15 minutes',
            lastPhase: this.currentPhase,
            inactivityThreshold: this.INACTIVITY_LIMIT
          });

          await this.end();

          setTimeout(() => {
            process.exit(0);
          }, 5000);
        }
      } catch (error) {
        this.firebase.error('Error in inactivity timer:', error);
      }
    }, this.INACTIVITY_LIMIT);
  }

  // Start metrics polling
  startMetricsPolling() {
    if (this.metricsInterval) {
      clearInterval(this.metricsInterval);
    }

    this.metricsInterval = setInterval(async () => {
      if (this.page) {
        try {
          const metrics = await getResourceMetrics(this.page);

          // Add current command info to metrics map with index
          if (this.commandTimestamps.length > 0) {
            const lastCommand = this.commandTimestamps[this.commandTimestamps.length - 1];
            metrics.currentCommand = `executing_command ${this.commandCounter} - ${lastCommand.command.join(' ')}`;
            metrics.commandIndex = this.commandCounter;  // Just the number
            metrics.commandRaw = lastCommand.command;    // Original command array
          }

          // Add to local log without any limits
          this.metricsLog.push(metrics);

          // Add to Firestore for session_data.json
          await this.firestore.addMetrics(metrics);

          // POST metrics to local endpoint
          // try {
          //   await fetch('http://localhost:8899/api/worker-stats', {
          //     method: 'POST',
          //     headers: {
          //       'Content-Type': 'application/json',
          //     },
          //     body: JSON.stringify({
          //       'client-id': this.clientId,
          //       'test-id': this.testId,
          //       'stats-map': metrics
          //     })
          //   }).catch(error => {
          //     // Silently handle endpoint errors - don't want to spam logs
          //     //console.debug('Failed to post metrics:', error);
          //   });
          // } catch (error) {
          //   // Silently handle endpoint errors - don't want to spam logs
          //   //console.debug('Failed to post metrics:', error);
          // }
        } catch (error) {
          console.debug('Failed to collect metrics:', error);
        }
      }
    }, 1000);
  }

  async log(level, message, data = null) {
    if (!this.initialized) {
      // Only console log and buffer if we're not initialized
      console.log(`${level}: ${message}`, data);
      this.earlyLogs.push({ level, message, data, timestamp: new Date().toISOString() });
      return;
    }
    // Log to both Firebase and Firestore once initialized
    await Promise.all([
      this.firebase.log(level, message, data),
      this.firestore.log(level, message, data)
    ]);
  }

  async debug(message, data = null) {
    await this.log('debug', message, data);
  }

  async info(message, data = null) {
    await this.log('info', message, data);
  }

  async warn(message, data = null) {
    await this.log('warn', message, data);
  }

  async error(message, data = null) {
    await this.log('error', message, data);
  }

  // Add method to cleanup temporary sessions
  async cleanupTemporarySession(oldSessionId) {
    if (!oldSessionId || !this.temporarySessionIds.has(oldSessionId)) return;

    try {
      // Delete from Firestore
      const runHistoryRef = this.firestore.getRunHistoryCollection();
      await runHistoryRef.doc(oldSessionId).delete();

      // Delete from Firebase
      const oldBasePath = `clients/${this.clientId}/${this.testId}/${oldSessionId}`;
      await this.firebase.db.ref(oldBasePath).remove();

      this.temporarySessionIds.delete(oldSessionId);
      console.log(`Cleaned up temporary session: ${oldSessionId}`);
    } catch (error) {
      console.error('Failed to cleanup temporary session:', error);
    }
  }

  async setRunningState(isRunning) {
    try {
      // Set running state in session-specific path
      await this.firebase.db.ref(`${this.firebase.getBasePath()}/running`).set(isRunning);

      // For interactive sessions, only set flow-status to false (not to true)
      if (this.sessionId !== 'interactive' || !isRunning) {
        // Duplicate to session-independent path
        await this.firebase.db.ref(`flow-status/${this.clientId}/${this.testId}/running`).set(isRunning);
      }
    } catch (error) {
      this.firebase.warn('Failed to set running state:', error);
    }
  }

  // New helper methods for video processing
  async processBasicVideo(inputPath, outputPath) {
    this.firebase.log('Converting webm to mp4...');
    await Promise.all([
      this.firebase.setPhase('converting_to_mp4'),
      this.firestore.setPhase('converting_to_mp4')
    ]);

    try {
      const ffmpegCmd = `ffmpeg -i "${inputPath}" -c:v libx264 -preset medium -tune film -threads 4 -thread_type frame -movflags +faststart -bf 2 -g 30 -crf 28 -maxrate 2M -bufsize 16M -max_muxing_queue_size 1024 -y "${outputPath}"`;

      this.firebase.log('Executing ffmpeg command:', ffmpegCmd);
      const { stdout, stderr } = await execAsync(ffmpegCmd);

      if (stdout) this.firebase.log('ffmpeg stdout:', stdout);
      if (stderr) this.firebase.log('ffmpeg stderr:', stderr);

      // Verify the output file was created
      const stats = await fsPromises.stat(outputPath);
      this.firebase.log(`MP4 created successfully: ${outputPath} (${stats.size} bytes)`);
    } catch (error) {
      this.firebase.error('Failed to convert webm to mp4:', error);
      this.firebase.error('Error message:', error.message);
      if (error.stderr) this.firebase.error('ffmpeg stderr:', error.stderr);
      throw error; // Re-throw to maintain existing behavior
    }
  }

  async create4xSpeedVersion(outputPath) {
    await Promise.all([
      this.firebase.setPhase('creating_4x_video_version'),
      this.firestore.setPhase('creating_4x_video_version')
    ]);

    try {
      await execAsync(`ffmpeg -i "${outputPath}" \
        -filter:v "setpts=0.25*PTS" \
        -c:v libx264 \
        -preset medium \
        -tune film \
        -threads 4 \
        -thread_type frame \
        -movflags +faststart \
        -bf 2 \
        -g 30 \
        -crf 28 \
        -maxrate 2M \
        -bufsize 16M \
        -max_muxing_queue_size 1024 \
        -y "${path.join(this.videoPath, 'session_4x.mp4')}"`);
    } catch (error) {
      this.firebase.error('Failed to create 4x speed video:', error);
      // Continue execution even if 4x speed creation fails
    }
  }

  async processSceneBasedClips(outputPath, clipsPath) {
    this.firebase.log('Detecting scene changes in tracking pixels...');
    await Promise.all([
      this.firebase.setPhase('detecting_scene_changes_from_tracking_pixels'),
      this.firestore.setPhase('detecting_scene_changes_from_tracking_pixels')
    ]);

    const framesPath = path.join(clipsPath, 'frames');
    await fsPromises.mkdir(framesPath, { recursive: true });

    // First pass: analyze the tracking pixel area for scene changes using original webm
    await execAsync(
      `ffmpeg -i "${outputPath}" ` +
      `-thread_type frame -max_muxing_queue_size 1024 ` +
      `-vf "crop=4:4:in_w-4:in_h-4,select='gt(scene,0.15)',metadata=print" ` +
      `-f null - 2> "${path.join(framesPath, 'scenes.txt')}"`
    );

    // Read and process scenes
    const scenesText = await fsPromises.readFile(path.join(framesPath, 'scenes.txt'), 'utf8');
    const sceneTimestamps = scenesText.split('\n')
      .filter(line => line.includes('pts_time:'))
      .map(line => {
        const match = line.match(/pts_time:([\d.]+)/);
        return match ? parseFloat(match[1]) : null;
      })
      .filter(Boolean);

    // Create clips from scenes
    this.firebase.log('Creating clips from detected scenes...');
    await Promise.all([
      this.firebase.setPhase('creating_clips_from_detected_scenes'),
      this.firestore.setPhase('creating_clips_from_detected_scenes')
    ]);

    // Process each scene
    for (let i = 0; i < sceneTimestamps.length - 1; i++) {
      const startTime = sceneTimestamps[i];
      const endTime = sceneTimestamps[i + 1];
      const duration = endTime - startTime;

      // Find active command for this clip
      const clipStartMs = startTime * 1000;
      const clipEndMs = endTime * 1000;
      const sessionStartTime = this.commandTimestamps[0]?.timestamp || 0;
      const relativeStartMs = clipStartMs + sessionStartTime;

      const activeCommand = this.commandTimestamps
        .filter(cmd => cmd.timestamp <= relativeStartMs)
        .pop();

      // Create clip name
      let clipName;
      if (activeCommand) {
        const commandIndex = this.commandTimestamps.findIndex(cmd => cmd.timestamp === activeCommand.timestamp);
        const commandName = Array.isArray(activeCommand.command)
          ? activeCommand.command.join('-')
          : activeCommand.command;
        clipName = `clip_${i + 1}_${commandIndex}_${commandName.replace(/[^a-zA-Z0-9-]/g, '_')}`;
      } else {
        clipName = `clip_${i + 1}_unknown`;
      }

      // Create the clip
      await execAsync(`ffmpeg -i "${outputPath}" \
        -ss ${startTime} \
        -t ${duration} \
        -c:v libx264 \
        -preset medium \
        -tune film \
        -threads 4 \
        -thread_type frame \
        -movflags +faststart \
        -bf 2 \
        -g 30 \
        -crf 28 \
        -maxrate 2M \
        -bufsize 16M \
        -max_muxing_queue_size 1024 \
        -y "${path.join(clipsPath, `${clipName}.mp4`)}"`);
    }

    // Save clip mapping
    const clipMapping = {
      sessionStartTime: this.commandTimestamps[0]?.timestamp,
      clips: sceneTimestamps.slice(0, -1).map((startTime, i) => ({
        clipNumber: i + 1,
        startTime: startTime,
        endTime: sceneTimestamps[i + 1],
        command: this.commandTimestamps
          .filter(cmd => cmd.timestamp <= (startTime * 1000 + (this.commandTimestamps[0]?.timestamp || 0)))
          .pop()?.command || null
      }))
    };

    await fsPromises.writeFile(
      path.join(clipsPath, 'clip_mapping.json'),
      JSON.stringify(clipMapping, null, 2)
    );

    // Create command-based videos and GIFs
    await this.createCommandBasedMedia(outputPath, clipMapping, clipsPath);

    // Cleanup
    await fsPromises.unlink(path.join(framesPath, 'scenes.txt'));
  }

  async createCommandBasedMedia(outputPath, clipMapping, clipsPath) {
    this.firebase.log('Creating command-based videos and GIFs...');
    await Promise.all([
      this.firebase.setPhase('creating_command_videos_and_gifs'),
      this.firestore.setPhase('creating_command_videos_and_gifs')
    ]);

    const commandVideosPath = path.join(this.videoPath, 'command_videos');
    const commandGifsPath = path.join(this.videoPath, 'command_gifs');
    await fsPromises.mkdir(commandVideosPath, { recursive: true });
    await fsPromises.mkdir(commandGifsPath, { recursive: true });

    // Group clips by command index
    const clipsByCommand = new Map();
    for (const clip of clipMapping.clips) {
      if (!clip.command) continue;

      const commandIndex = this.commandTimestamps.findIndex(cmd =>
        JSON.stringify(cmd.command) === JSON.stringify(clip.command)
      );
      if (commandIndex === -1) continue;

      if (!clipsByCommand.has(commandIndex)) {
        clipsByCommand.set(commandIndex, []);
      }
      clipsByCommand.get(commandIndex).push(clip);
    }

    // Process each command group
    for (const [commandIndex, clips] of clipsByCommand) {
      try {
        clips.sort((a, b) => a.startTime - b.startTime);

        const listPath = path.join(clipsPath, `command_${commandIndex}_list.txt`);
        const fileList = clips.map(clip => {
          const clipName = `clip_${clip.clipNumber}_${commandIndex}_${Array.isArray(clip.command) ? clip.command.join('-') : clip.command}`.replace(/[^a-zA-Z0-9-]/g, '_');
          return `file '${path.join(clipsPath, clipName)}.mp4'`;
        }).join('\n');
        await fsPromises.writeFile(listPath, fileList);

        const commandVideoPath = path.join(commandVideosPath, `command_${commandIndex}.mp4`);
        await execAsync(`ffmpeg -f concat -safe 0 -i "${listPath}" -c copy -thread_type frame -max_muxing_queue_size 1024 -y "${commandVideoPath}"`);

        const commandGifPath = path.join(commandGifsPath, `command_${commandIndex}.gif`);
        await execAsync(`ffmpeg -i "${commandVideoPath}" \
          -vf "fps=10,scale=600:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=128:reserve_transparent=0[p];[s1][p]paletteuse=dither=bayer:bayer_scale=3" \
          -max_muxing_queue_size 1024 \
          -y "${commandGifPath}"`);

        await fsPromises.unlink(listPath);
      } catch (error) {
        this.firebase.warn(`Failed to process command ${commandIndex}:`, error);
      }
    }
  }

  async processTimestampBasedClips(outputPath, commandsTsPath) {
    this.firebase.log('Creating timestamp-based command clips...');
    await Promise.all([
      this.firebase.setPhase('creating_timestamp_based_command_clips'),
      this.firestore.setPhase('creating_timestamp_based_command_clips')
    ]);

    // Process each command based on timestamps
    for (let i = 0; i < this.commandTimestamps.length; i++) {
      const command = this.commandTimestamps[i];
      const nextCommand = this.commandTimestamps[i + 1];

      const videoStartTime = this.commandTimestamps[0].timestamp;
      const startOffset = (command.timestamp - videoStartTime) / 1000;
      const endOffset = nextCommand
        ? (nextCommand.timestamp - videoStartTime) / 1000
        : command.endTimestamp
          ? (command.endTimestamp - videoStartTime) / 1000
          : startOffset + 5;

      const duration = endOffset - startOffset;

      if (duration <= 0) {
        this.firebase.warn(`Skipping command ${i} due to invalid duration: ${duration}s`);
        continue;
      }

      try {
        const clipPath = path.join(commandsTsPath, `command_${i}.mp4`);
        await execAsync(`ffmpeg -i "${outputPath}" \
          -ss ${startOffset} \
          -t ${duration} \
          -c:v libx264 \
          -preset medium \
          -tune film \
          -threads 4 \
          -thread_type frame \
          -movflags +faststart \
          -bf 2 \
          -g 30 \
          -crf 28 \
          -maxrate 2M \
          -bufsize 16M \
          -max_muxing_queue_size 1024 \
          -y "${clipPath}"`);

        const gifPath = path.join(commandsTsPath, `command_${i}.gif`);
        await execAsync(`ffmpeg -i "${clipPath}" \
          -vf "fps=10,scale=600:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=128:reserve_transparent=0[p];[s1][p]paletteuse=dither=bayer:bayer_scale=3" \
          -max_muxing_queue_size 1024 \
          -y "${gifPath}"`);

      } catch (error) {
        this.firebase.warn(`Failed to create timestamp-based clip for command ${i}:`, error);
      }
    }

    // Save timestamp mapping
    const tsMapping = {
      videoStartTime: this.commandTimestamps[0].timestamp,
      commands: this.commandTimestamps.map((cmd, index) => ({
        commandIndex: index,
        command: cmd.command,
        startTime: (cmd.timestamp - this.commandTimestamps[0].timestamp) / 1000,
        endTime: cmd.endTimestamp
          ? (cmd.endTimestamp - this.commandTimestamps[0].timestamp) / 1000
          : null,
        duration: cmd.duration ? cmd.duration / 1000 : null
      }))
    };

    await fsPromises.writeFile(
      path.join(commandsTsPath, 'timestamp_mapping.json'),
      JSON.stringify(tsMapping, null, 2)
    );
  }

  // Add this as a new method in the PlaywrightSession class
  setupVideoLinkDetection() {
    // Create this function in a way that doesn't disrupt session if it fails
    (async () => {
      const runsRoot = path.join(process.cwd(), 'rabbitize-runs');
      const linkPath = path.join(runsRoot, 'live.webm');
      const maxAttempts = 10;
      let attempts = 0;
      let success = false;

      // Try periodically to find the file and create the link
      while (attempts < maxAttempts && !success) {
        attempts++;
        await new Promise(resolve => setTimeout(resolve, 2000)); // 2-second intervals

        try {
          // Check if video directory exists and has webm files
          if (await fsPromises.access(this.videoPath).then(() => true).catch(() => false)) {
            const files = await fsPromises.readdir(this.videoPath);
            const webmFile = files.find(file => file.endsWith('.webm'));

            if (webmFile) {
              // Remove existing link if it exists
              try {
                await fsPromises.unlink(linkPath);
              } catch (err) {
                if (err.code !== 'ENOENT') {
                  this.firebase.warn('Error removing existing live.webm link:', err);
                }
              }

              // Create the new link
              await fsPromises.symlink(path.join(this.videoPath, webmFile), linkPath);
              this.firebase.log('🏞️🏞️🏞️ Created symbolic link to video file:', {
                source: webmFile,
                link: 'live.webm',
                attempt: attempts
              });

              // // Update RTDB to signal that video is ready
              // try {
              //   await this.firebase.db.ref(`video-ready/${this.clientId}/${this.testId}`).set(true);
              //   this.firebase.log('Updated video-ready status in RTDB');
              // } catch (rtdbError) {
              //   this.firebase.warn('Failed to update video-ready status in RTDB:', rtdbError);
              // }

              // Update RTDB to signal that video is ready
              (async () => {
                try {
                  // Wait 12 seconds before updating RTDB
                  await new Promise(resolve => setTimeout(resolve, 3000));

                  await this.firebase.db.ref(`video-ready/${this.clientId}/${this.testId}`).set(true);
                  this.firebase.log('Updated video-ready status in RTDB after 3s delay');
                } catch (rtdbError) {
                  this.firebase.warn('Failed to update video-ready status in RTDB:', rtdbError);
                }
              })().catch(error => {
                this.firebase.warn('Error in delayed video-ready update:', error);
              });


              success = true;
              break;
            }
          }
        } catch (error) {
          this.firebase.warn(`Video symlink attempt ${attempts} failed:`, error);
        }
      }

      if (!success) {
        this.firebase.warn(`Failed to create video symlink after ${maxAttempts} attempts`);
      }
    })().catch(error => {
      this.firebase.error('Unexpected error in video link detection:', error);
    });
  }

  // Add method to set async uploads
  setAsyncUploads(enabled = true) {
    if (!this.firebase) return false;

    const oldValue = this.firebase.asyncUploads;
    this.firebase.asyncUploads = enabled;

    this.firebase.log(`Image uploads set to ${enabled ? 'async (non-blocking)' : 'sync (blocking)'} mode`);

    return oldValue;
  }

  // Add method to get current async uploads setting
  getAsyncUploads() {
    return this.firebase?.asyncUploads || false;
  }
  
  // Setup download handling to save files locally
  setupDownloadHandling() {
    if (!this.page) return;
    
    this.page.on('download', async (download) => {
      try {
        // Default to session base directory (same as screenshots), or use configured path
        const downloadDir = this.downloadPath || this.basePath;
        
        // Ensure download directory exists
        await fsPromises.mkdir(downloadDir, { recursive: true });
        
        // Get the suggested filename
        const suggestedFilename = download.suggestedFilename();
        const downloadPath = path.join(downloadDir, suggestedFilename);
        
        // Save the download
        await download.saveAs(downloadPath);
        
        this.firebase.log(`File downloaded: ${downloadPath}`);
        
        // If using a custom download path, also save a copy to the session directory
        if (this.downloadPath && this.downloadPath !== this.basePath) {
          const sessionDownloadPath = path.join(this.basePath, suggestedFilename);
          await fsPromises.copyFile(downloadPath, sessionDownloadPath);
          this.firebase.log(`File also copied to session directory: ${sessionDownloadPath}`);
        }
        
      } catch (error) {
        this.firebase.error('Failed to handle download:', error);
      }
    });
  }
  
  // Setup file chooser handling for upload dialogs
  setupFileChooserHandling() {
    if (!this.page) return;
    
    this.page.on('filechooser', async (fileChooser) => {
      try {
        if (this.uploadFilePath) {
          // Use the pre-configured file
          await fileChooser.setFiles(this.uploadFilePath);
          this.firebase.log(`File uploaded from: ${this.uploadFilePath}`);
          
          // Clear the upload file after use (single use)
          this.uploadFilePath = null;
        } else {
          // If no file is configured, log a warning
          this.firebase.warn('File chooser dialog opened but no file was configured. Use :set-upload-file command first.');
          
          // You could also implement a default behavior here, like:
          // - Upload a placeholder file
          // - Cancel the dialog
          // - Look for files in a default directory
        }
      } catch (error) {
        this.firebase.error('Failed to handle file chooser:', error);
      }
    });
  }

  // Add method to capture DOM elements and their coordinates
  async capturePageElements() {
    if (!this.page) return null;

    try {
      // Capture DOM elements with coordinates via page.evaluate
      return await this.page.evaluate(() => {
        // Define selectors for notable elements
        const importantSelectors = [
          // Headers and structural elements
          'h1, h2, h3, h4, h5, h6',
          // Interactive elements
          'button, a, select, input, textarea, [role="button"]',
          // Navigation elements
          'nav, .nav, .navigation, .menu',
          // Content containers
          'article, section, .card, .container, .content',
          // List items in small lists (avoid huge menus)
          'ul:not(:has(> li:nth-child(10))) > li, ol:not(:has(> li:nth-child(10))) > li',
          // Tables
          'table, th, td',
          // Images with alt text
          'img[alt]:not([alt=""])',
          // Elements with specific attributes
          '[data-testid], [aria-label]'
        ];

        const elements = [];

        // Use Set to track already processed elements
        const processedElements = new Set();

        // Query all elements matching our selectors
        document.querySelectorAll(importantSelectors.join(', ')).forEach(el => {
          // Skip if we've already processed this element
          if (processedElements.has(el)) return;
          processedElements.add(el);

          // Get positioning information
          const rect = el.getBoundingClientRect();

          // Skip elements with zero size or outside viewport
          if (rect.width <= 0 || rect.height <= 0 ||
              rect.bottom < 0 || rect.right < 0 ||
              rect.top > window.innerHeight || rect.left > window.innerWidth) {
            return;
          }

          // Check computed style for visibility
          const style = window.getComputedStyle(el);
          if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
            return;
          }

          // Get basic element properties
          const tagName = el.tagName.toLowerCase();
          const id = el.id || '';
          const classNames = Array.from(el.classList).join(' ');
          const text = el.textContent?.trim() || '';

          // Limit text length to avoid massive objects
          const truncatedText = text.length > 200 ? text.substring(0, 197) + '...' : text;

          // Get specific attributes for certain elements
          let attributes = {};

          if (tagName === 'a') {
            attributes.href = el.href || '';
          } else if (tagName === 'img') {
            attributes.alt = el.alt || '';
            attributes.src = el.src || '';
          } else if (tagName === 'input' || tagName === 'textarea') {
            attributes.placeholder = el.placeholder || '';
            attributes.type = el.type || '';
          } else if (tagName === 'button') {
            attributes.type = el.type || '';
          }

          // Also grab data attributes
          Array.from(el.attributes)
            .filter(attr => attr.name.startsWith('data-') || attr.name.startsWith('aria-'))
            .forEach(attr => {
              attributes[attr.name] = attr.value;
            });

          // Add element to our collection
          elements.push({
            tagName,
            id,
            classNames,
            text: truncatedText,
            attributes,
            position: {
              x: Math.round(rect.left),
              y: Math.round(rect.top),
              width: Math.round(rect.width),
              height: Math.round(rect.height),
              centerX: Math.round(rect.left + rect.width / 2),
              centerY: Math.round(rect.top + rect.height / 2)
            }
          });
        });

        // Add viewport dimensions
        const viewport = {
          width: window.innerWidth,
          height: window.innerHeight
        };

        // Add some basic page metadata
        const metadata = {
          title: document.title,
          url: window.location.href,
          timestamp: new Date().toISOString(),
          elementCount: elements.length
        };

        return {
          viewport,
          metadata,
          elements
        };
      });
    } catch (error) {
      this.firebase.warn('Failed to capture page elements:', error);
      return null;
    }
  }
}

module.exports = PlaywrightSession;