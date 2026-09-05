// store.js
//
// Minimal file-backed store, standing in for get_config()/save_config() from
// the Python dashboard (contend_BRIDGE_main.py). Swap readConfig/writeConfig
// for real DB calls when you outgrow a single JSON file.

const fs = require("fs");
const path = require("path");

// The bridge (BRIDGE/constants.py) reads WEB/data/config.json. This default used
// to be the cwd-relative "./data/config.json", and systemd runs the unit with
// WorkingDirectory=/home/forget/Arena — so the dashboard wrote a SECOND config at
// Arena/data/config.json that the bridge never read (models/tokens split-brain).
// Resolve against __dirname so the path is correct from any working directory.
const DATA_FILE = process.env.DATA_FILE || path.join(__dirname, "data", "config.json");

const DEFAULT_CONFIG = {
  api_keys: [],       // [{ name, key, rpm, created }]
  auth_tokens: [],     // [arena-auth-prod-v1... strings]
  cf_clearance: null,
  browser_cookies: {},
  models: null,        // Will be loaded from file, don't override
  usage: {},           // { [modelName]: requestCount }
};

function ensureDataFile() {
  const dir = path.dirname(DATA_FILE);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  if (!fs.existsSync(DATA_FILE)) {
    fs.writeFileSync(DATA_FILE, JSON.stringify(DEFAULT_CONFIG, null, 2));
  }
}

function readConfig() {
  ensureDataFile();
  try {
    const raw = fs.readFileSync(DATA_FILE, "utf8");
    const fileConfig = JSON.parse(raw);
    // Don't override models with default if they exist in file
    const merged = { ...DEFAULT_CONFIG, ...fileConfig };
    if (fileConfig.models && Array.isArray(fileConfig.models) && fileConfig.models.length > 0) {
      merged.models = fileConfig.models;
    }
    return merged;
  } catch {
    return { ...DEFAULT_CONFIG };
  }
}

function writeConfig(config) {
  ensureDataFile();
  fs.writeFileSync(DATA_FILE, JSON.stringify(config, null, 2));
  return config;
}

module.exports = { readConfig, writeConfig };
