const pidusage = require('pidusage');
const fs = require('fs').promises;
const path = require('path');

// No-op metrics module - maintains interface but doesn't use Google Cloud Monitoring

let metricStartTime = null;
let metricInterval = null;
let metricsEnabled = false;
let metricsQueue = [];

async function initializeMetrics() {
    // Silent initialization
    metricsEnabled = true;
    metricStartTime = Date.now();
}

async function getResourceMetrics() {
    try {
        const stats = await pidusage(process.pid);
        const memoryMB = stats.memory / 1024 / 1024;
        const cpuPercent = stats.cpu;
        
        const metrics = {
            timestamp: Date.now(),
            cpu: cpuPercent.toFixed(2),
            memory: memoryMB.toFixed(2),
            elapsed: metricStartTime ? Date.now() - metricStartTime : 0
        };

        // Console log for debugging if needed
        // console.log('Metrics:', metrics);
        
        return metrics;
    } catch (error) {
        console.error('Failed to get resource metrics:', error);
        return null;
    }
}

async function startMetricsCollection(interval = 5000, sessionPath = null) {
    if (!metricsEnabled) return;
    
    // Silent start - no console output
    
    metricInterval = setInterval(async () => {
        const metrics = await getResourceMetrics();
        if (metrics && sessionPath) {
            try {
                const metricsPath = path.join(sessionPath, 'metrics.json');
                await fs.writeFile(metricsPath, JSON.stringify(metrics, null, 2));
            } catch (error) {
                console.error('Failed to write metrics to file:', error);
            }
        }
    }, interval);
}

async function stopMetricsCollection() {
    if (metricInterval) {
        clearInterval(metricInterval);
        metricInterval = null;
    }
    // Silent stop
}

async function writeStepMetric(stepName, clientId, testId, labels = {}) {
    // Silent no-op
    return Promise.resolve();
}

async function writeBrowserDurationMetric(clientId, testId, durationMs, labels = {}) {
    // Silent no-op
    return Promise.resolve();
}

async function flushMetrics() {
    // No-op - no metrics to flush
    return Promise.resolve();
}

module.exports = {
    initializeMetrics,
    getResourceMetrics,
    startMetricsCollection,
    stopMetricsCollection,
    writeStepMetric,
    writeBrowserDurationMetric,
    flushMetrics
};