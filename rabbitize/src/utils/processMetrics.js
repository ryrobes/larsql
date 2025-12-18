const pidusage = require('pidusage');
const { exec } = require('child_process');
const util = require('util');
const execAsync = util.promisify(exec);

class ProcessMetricsCollector {
  constructor(browser) {
    this.browser = browser;
    this.pid = null;
  }

  async initialize() {
    try {
      const browserName = this.browser.browserType().name();
      let processNames;

      switch (browserName) {
        case 'chromium':
          processNames = ['chromium_headless']; // 'chrome', 'chromium', 'chromium-browser',
          break;
        case 'firefox':
          processNames = ['firefox', 'firefox-bin', 'firefox-esr'];
          break;
        case 'webkit':
          processNames = ['webkit', 'safari', 'webkit2-daemon', 'WebKitWebProcess'];
          break;
        default:
          console.debug(`Unknown browser type: ${browserName}`);
          return false;
      }

      // Create grep pattern for all possible process names
      const grepPattern = processNames.join('\\|');
      const { stdout } = await execAsync(`ps aux | grep -i '${grepPattern}' | grep -v grep`);

      const processes = stdout.split('\n')
        .filter(line => processNames.some(name =>
          line.toLowerCase().includes(name.toLowerCase())
        ))
        .map(line => parseInt(line.split(/\s+/)[1]))
        .filter(pid => !isNaN(pid));

      // Take the first matching process
      this.pid = processes[0];

      if (!this.pid) {
        console.debug(`Could not get process ID for ${browserName}`);
        return false;
      }

      //console.debug(`Found ${browserName} process with PID: ${this.pid}`);
      return true;
    } catch (error) {
      console.debug('Failed to initialize process metrics:', error);
      return false;
    }
  }

  async getMetrics() {
    if (!this.pid) {
      return null;
    }

    try {
      const stats = await pidusage(this.pid);
      const cpuCount = require('os').cpus().length;

      return {
        timestamp: Date.now(),
        process: {
          pid: this.pid,
          cpu: {
            percentage: stats.cpu,
            normalizedPercentage: stats.cpu / cpuCount,
            coreCount: cpuCount
          },
          memory: {
            bytes: stats.memory,
            megabytes: Math.round(stats.memory / 1024 / 1024 * 100) / 100
          },
          elapsed: stats.elapsed,
          ppid: stats.ppid
        }
      };
    } catch (error) {
      console.debug('Failed to collect process metrics:', error);
      return null;
    }
  }
}

module.exports = { ProcessMetricsCollector };