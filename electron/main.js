/**
 * Electron Main Process
 * 
 * Creates and manages the application window.
 * Loads the frontend from the local files.
 */

const { app, BrowserWindow, shell } = require('electron');
const path = require('path');

// Keep a global reference to prevent garbage collection
let mainWindow = null;

/**
 * Create the main application window
 */
function createWindow() {
    mainWindow = new BrowserWindow({
        width: 1200,
        height: 800,
        minWidth: 600,
        minHeight: 500,
        title: 'Computer-Use Agent',
        icon: path.join(__dirname, '../frontend/icon.png'),
        backgroundColor: '#0f0f0f',
        webPreferences: {
            // Security: Use preload script instead of direct Node access
            preload: path.join(__dirname, 'preload.js'),

            // Security settings
            nodeIntegration: false,
            contextIsolation: true,
            sandbox: true,
            webSecurity: true,

            // Disable potentially dangerous features
            allowRunningInsecureContent: false,
            experimentalFeatures: false,
        },
        // Window styling
        frame: true,
        titleBarStyle: 'default',
        show: false, // Show after ready-to-show
    });

    // Load the frontend
    mainWindow.loadFile(path.join(__dirname, '../frontend/index.html'));

    // Show window when ready (prevents visual flash)
    mainWindow.once('ready-to-show', () => {
        mainWindow.show();

        // Open DevTools in development
        if (process.env.NODE_ENV === 'development') {
            mainWindow.webContents.openDevTools();
        }
    });

    // Handle external links - open in default browser
    mainWindow.webContents.setWindowOpenHandler(({ url }) => {
        // Only allow http/https links
        if (url.startsWith('http://') || url.startsWith('https://')) {
            shell.openExternal(url);
        }
        return { action: 'deny' };
    });

    // Handle window close
    mainWindow.on('closed', () => {
        mainWindow = null;
    });

    // Prevent navigation to external URLs
    mainWindow.webContents.on('will-navigate', (event, url) => {
        const frontendUrl = `file://${path.join(__dirname, '../frontend/').replace(/\\/g, '/')}`;
        if (!url.startsWith(frontendUrl) && !url.startsWith('file://')) {
            event.preventDefault();
            console.log('Navigation blocked:', url);
        }
    });
}

// App lifecycle handlers
app.whenReady().then(() => {
    createWindow();

    // macOS: Re-create window when dock icon is clicked
    app.on('activate', () => {
        if (BrowserWindow.getAllWindows().length === 0) {
            createWindow();
        }
    });
});

// Quit when all windows are closed (except on macOS)
app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') {
        app.quit();
    }
});

// Security: Prevent new window creation
app.on('web-contents-created', (event, contents) => {
    contents.on('new-window', (event) => {
        event.preventDefault();
    });
});

// Handle any uncaught errors
process.on('uncaughtException', (error) => {
    console.error('Uncaught exception:', error);
});

process.on('unhandledRejection', (error) => {
    console.error('Unhandled rejection:', error);
});
