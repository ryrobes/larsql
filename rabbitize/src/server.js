// src/server.js
const express = require('express');
const PlaywrightSession = require('./PlaywrightSession');
const yargs = require('yargs/yargs');
const { hideBin } = require('yargs/helpers');

// Parse command line arguments
const argv = yargs(hideBin(process.argv))
  .option('show-overlay', {
    alias: 'o',
    type: 'boolean',
    description: 'Show command overlay in recordings',
    default: true
  })
  .argv;

const app = express();
app.use(express.json());

const sessionOptions = {
  showCommandOverlay: argv.showOverlay
};

const session = new PlaywrightSession('test123', 'sessions', sessionOptions);

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

// Export only the app, not the server
module.exports = app;