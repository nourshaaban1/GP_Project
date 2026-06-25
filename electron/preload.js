/**
 * Electron Preload Script
 * 
 * Runs in a separate context with limited Node.js access.
 * Provides a secure bridge between renderer and main process.
 * 
 * Note: For this application, we don't need to expose any Node APIs
 * since the frontend communicates directly with the backend via WebSocket.
 */

const { contextBridge } = require('electron');

// Expose a minimal API to the renderer process
contextBridge.exposeInMainWorld('electronAPI', {
    // App info
    getAppVersion: () => process.versions.electron,
    getPlatform: () => process.platform,

    // Log helper (for debugging)
    log: (...args) => {
        console.log('[Renderer]', ...args);
    }
});

// Log when preload is complete
console.log('Preload script loaded successfully');
