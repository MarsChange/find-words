const { app, BrowserWindow, dialog } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const http = require('http');
const net = require('net');
const fs = require('fs');

let mainWindow = null;
let backendProcess = null;

const DEFAULT_BACKEND_PORT = 8000;
let backendPort = DEFAULT_BACKEND_PORT;
let backendUrl = `http://localhost:${backendPort}`;
const IS_DEV = !app.isPackaged;

function isPortAvailable(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once('error', () => resolve(false));
    server.once('listening', () => {
      server.close(() => resolve(true));
    });
    server.listen(port, '127.0.0.1');
  });
}

async function findAvailablePort(startPort = DEFAULT_BACKEND_PORT, maxTries = 20) {
  for (let offset = 0; offset < maxTries; offset += 1) {
    const port = startPort + offset;
    const available = await isPortAvailable(port);
    if (available) return port;
  }
  throw new Error(`No available backend port found from ${startPort} to ${startPort + maxTries - 1}`);
}

/**
 * Resolve the path to the bundled Python backend executable.
 * In dev mode, we skip launching the backend (assume it runs separately).
 */
function getBackendPath() {
  if (IS_DEV) return null;

  const platform = process.platform;
  const exeName = platform === 'win32' ? 'findwords-server.exe' : 'findwords-server';

  // In packaged app, resources are in the 'resources' directory
  const resourcesPath = process.resourcesPath;
  const backendPath = path.join(resourcesPath, 'backend', exeName);

  if (fs.existsSync(backendPath)) return backendPath;

  // Fallback: check next to the app
  const altPath = path.join(path.dirname(app.getPath('exe')), 'backend', exeName);
  if (fs.existsSync(altPath)) return altPath;

  return null;
}

/**
 * Get the user data directory for storing database, uploads, and config.
 */
function getDataDir() {
  const dataDir = path.join(app.getPath('userData'), 'data');
  if (!fs.existsSync(dataDir)) {
    fs.mkdirSync(dataDir, { recursive: true });
  }
  return dataDir;
}

/**
 * Get the path to the built frontend dist directory.
 */
function getFrontendDistPath() {
  if (IS_DEV) return null;

  const distPath = path.join(process.resourcesPath, 'frontend-dist');
  if (fs.existsSync(distPath)) return distPath;

  return null;
}

/**
 * Start the Python backend as a subprocess.
 */
async function startBackend() {
  const backendPath = getBackendPath();
  if (!backendPath) {
    console.log('[Electron] Dev mode: skipping backend launch');
    return;
  }

  backendPort = await findAvailablePort(DEFAULT_BACKEND_PORT, 20);
  backendUrl = `http://localhost:${backendPort}`;

  const dataDir = getDataDir();
  const frontendDist = getFrontendDistPath();

  const env = {
    ...process.env,
    FINDWORDS_PORT: String(backendPort),
    FINDWORDS_DATA_DIR: dataDir,
    FINDWORDS_CONFIG_PATH: path.join(dataDir, 'config.json'),
    FINDWORDS_STATIC_DIR: frontendDist || '',
  };

  console.log(`[Electron] Starting backend: ${backendPath}`);
  console.log(`[Electron] Backend URL: ${backendUrl}`);
  console.log(`[Electron] Data directory: ${dataDir}`);

  backendProcess = spawn(backendPath, [], {
    env,
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  backendProcess.stdout.on('data', (data) => {
    console.log(`[Backend] ${data.toString().trim()}`);
  });

  backendProcess.stderr.on('data', (data) => {
    console.error(`[Backend] ${data.toString().trim()}`);
  });

  backendProcess.on('exit', (code) => {
    console.log(`[Electron] Backend exited with code ${code}`);
    backendProcess = null;
  });
}

/**
 * Wait for the backend to be ready by polling the health endpoint.
 */
function waitForBackend(retries = 240, interval = 500) {
  return new Promise((resolve, reject) => {
    let attempts = 0;

    const check = () => {
      attempts++;
      const req = http.get(`${backendUrl}/api/health`, (res) => {
        if (res.statusCode === 200) {
          resolve();
        } else if (attempts < retries) {
          setTimeout(check, interval);
        } else {
          reject(new Error('Backend health check failed'));
        }
      });

      req.on('error', () => {
        if (attempts < retries) {
          setTimeout(check, interval);
        } else {
          reject(new Error('Backend not reachable'));
        }
      });

      req.end();
    };

    check();
  });
}

/**
 * Create the main application window.
 */
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 900,
    minHeight: 600,
    title: '古籍词语检索分析系统',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  // In production, load from the backend server (which serves the frontend)
  // In dev, load from the Vite dev server
  if (IS_DEV) {
    mainWindow.loadURL('http://localhost:5173');
    mainWindow.webContents.openDevTools();
  } else {
    mainWindow.loadURL(backendUrl);
  }

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

/**
 * Stop the backend subprocess gracefully.
 */
function stopBackend() {
  if (!backendProcess) return;

  console.log('[Electron] Stopping backend...');

  if (process.platform === 'win32') {
    spawn('taskkill', ['/pid', backendProcess.pid.toString(), '/f', '/t']);
  } else {
    backendProcess.kill('SIGTERM');
  }

  // Force kill after 5 seconds
  setTimeout(() => {
    if (backendProcess) {
      backendProcess.kill('SIGKILL');
      backendProcess = null;
    }
  }, 5000);
}

// ── App lifecycle ───────────────────────────────────────────────────────────

app.on('ready', async () => {
  await startBackend();

  try {
    if (!IS_DEV) {
      await waitForBackend();
    }
  } catch (err) {
    dialog.showErrorBox(
      '启动失败',
      '后端服务启动失败，请重试。\n\n' + err.message,
    );
    app.quit();
    return;
  }

  createWindow();
});

app.on('window-all-closed', () => {
  stopBackend();
  app.quit();
});

app.on('before-quit', () => {
  stopBackend();
});

app.on('activate', () => {
  if (mainWindow === null) {
    createWindow();
  }
});
