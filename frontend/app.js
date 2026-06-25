/**
 * Computer-Use Agent - Frontend Application
 * 
 * WebSocket client for communicating with the FastAPI backend.
 * Handles message streaming, connection management, and file downloads.
 */

// Configuration
const CONFIG = {
    WS_URL: 'ws://localhost:8000/ws/chat',
    API_URL: 'http://localhost:8000',
    RECONNECT_DELAY: 3000,
    MAX_RECONNECT_ATTEMPTS: 5
};

// State
let socket = null;
let reconnectAttempts = 0;
let isAgentProcessing = false;
let currentAgentMessageEl = null;

// DOM Elements
const elements = {
    messages: document.getElementById('messages'),
    chatContainer: document.getElementById('chatContainer'),
    messageInput: document.getElementById('messageInput'),
    sendButton: document.getElementById('sendButton'),
    connectionStatus: document.getElementById('connectionStatus'),
    inputHint: document.getElementById('inputHint'),
    downloadsSection: document.getElementById('downloadsSection'),
    downloadsList: document.getElementById('downloadsList'),
    clearDownloads: document.getElementById('clearDownloads')
};

/**
 * Initialize the application
 */
function init() {
    setupEventListeners();
    connect();
}

/**
 * Setup event listeners
 */
function setupEventListeners() {
    // Send button click
    elements.sendButton.addEventListener('click', sendMessage);

    // Enter key to send (Shift+Enter for new line)
    elements.messageInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    // Auto-resize textarea
    elements.messageInput.addEventListener('input', () => {
        elements.messageInput.style.height = 'auto';
        elements.messageInput.style.height = Math.min(elements.messageInput.scrollHeight, 150) + 'px';
    });

    // Clear downloads
    elements.clearDownloads.addEventListener('click', clearDownloads);
}

/**
 * Connect to WebSocket server
 */
function connect() {
    if (socket && socket.readyState === WebSocket.OPEN) {
        return;
    }

    updateConnectionStatus('connecting');

    try {
        socket = new WebSocket(CONFIG.WS_URL);

        socket.onopen = handleOpen;
        socket.onmessage = handleMessage;
        socket.onerror = handleError;
        socket.onclose = handleClose;

    } catch (error) {
        console.error('Failed to create WebSocket:', error);
        scheduleReconnect();
    }
}

/**
 * Handle WebSocket open
 */
function handleOpen() {
    console.log('WebSocket connected');
    reconnectAttempts = 0;
    updateConnectionStatus('connected');
    enableInput();
}

/**
 * Handle incoming WebSocket message
 */
function handleMessage(event) {
    try {
        const data = JSON.parse(event.data);

        switch (data.type) {
            case 'agent':
                appendAgentMessage(data.text);
                break;

            case 'status':
                appendStatusMessage(data.text);
                break;

            case 'tool_result':
                appendToolResultMessage(data.text);
                break;

            case 'file_created':
                addDownloadLink(data.path);
                break;

            case 'done':
                handleAgentDone();
                break;

            case 'error':
                appendErrorMessage(data.text);
                handleAgentDone();
                break;

            default:
                console.log('Unknown message type:', data.type, data);
        }

    } catch (error) {
        console.error('Failed to parse message:', error);
    }
}

/**
 * Handle WebSocket error
 */
function handleError(error) {
    console.error('WebSocket error:', error);
    updateConnectionStatus('error');
}

/**
 * Handle WebSocket close
 */
function handleClose(event) {
    console.log('WebSocket closed:', event.code, event.reason);
    updateConnectionStatus('disconnected');
    disableInput();

    if (isAgentProcessing) {
        appendErrorMessage('Connection lost while processing. Please try again.');
        handleAgentDone();
    }

    scheduleReconnect();
}

/**
 * Schedule reconnection attempt
 */
function scheduleReconnect() {
    if (reconnectAttempts >= CONFIG.MAX_RECONNECT_ATTEMPTS) {
        elements.inputHint.textContent = 'Connection failed. Please restart the backend.';
        return;
    }

    reconnectAttempts++;
    const delay = CONFIG.RECONNECT_DELAY * reconnectAttempts;

    elements.inputHint.textContent = `Reconnecting in ${delay / 1000}s... (attempt ${reconnectAttempts}/${CONFIG.MAX_RECONNECT_ATTEMPTS})`;

    setTimeout(connect, delay);
}

/**
 * Send message to agent
 */
function sendMessage() {
    const text = elements.messageInput.value.trim();

    if (!text || !socket || socket.readyState !== WebSocket.OPEN || isAgentProcessing) {
        return;
    }

    // Clear welcome message if present
    const welcomeMessage = elements.messages.querySelector('.welcome-message');
    if (welcomeMessage) {
        welcomeMessage.remove();
    }

    // Add user message to UI
    appendUserMessage(text);

    // Clear input
    elements.messageInput.value = '';
    elements.messageInput.style.height = 'auto';

    // Send to backend
    const payload = {
        messages: [
            { role: 'user', content: text }
        ]
    };

    socket.send(JSON.stringify(payload));

    // Update UI state
    isAgentProcessing = true;
    currentAgentMessageEl = null;
    disableInput();
    elements.inputHint.textContent = 'Agent is processing...';
}

/**
 * Append user message to chat
 */
function appendUserMessage(text) {
    const messageEl = document.createElement('div');
    messageEl.className = 'message user-message';
    messageEl.innerHTML = `
        <div class="message-content">
            <div class="message-text">${escapeHtml(text)}</div>
            <div class="message-time">${formatTime(new Date())}</div>
        </div>
        <div class="message-avatar">👤</div>
    `;

    elements.messages.appendChild(messageEl);
    scrollToBottom();
}

/**
 * Append agent message as a new chat bubble
 */
function appendAgentMessage(text) {
    // Create a new agent message bubble for each message
    const messageEl = document.createElement('div');
    messageEl.className = 'message agent-message';
    messageEl.innerHTML = `
        <div class="message-avatar">🤖</div>
        <div class="message-content">
            <div class="message-text">${escapeHtml(text)}</div>
            <div class="message-time">${formatTime(new Date())}</div>
        </div>
    `;

    elements.messages.appendChild(messageEl);
    scrollToBottom();
}

/**
 * Append status message
 */
function appendStatusMessage(text) {
    const statusEl = document.createElement('div');
    statusEl.className = 'status-message';
    statusEl.innerHTML = `
        <span class="status-icon">⚙️</span>
        <span class="status-content">${escapeHtml(text)}</span>
    `;

    elements.messages.appendChild(statusEl);
    scrollToBottom();
}

/**
 * Append error message
 */
function appendErrorMessage(text) {
    const errorEl = document.createElement('div');
    errorEl.className = 'error-message';
    errorEl.innerHTML = `
        <span class="error-icon">⚠️</span>
        <span class="error-content">${escapeHtml(text)}</span>
    `;

    elements.messages.appendChild(errorEl);
    scrollToBottom();
}

/**
 * Append tool result message
 */
function appendToolResultMessage(text) {
    const resultEl = document.createElement('div');
    resultEl.className = 'tool-result-message';
    resultEl.innerHTML = `
        <span class="tool-icon">🔧</span>
        <span class="tool-content">${escapeHtml(text)}</span>
    `;

    elements.messages.appendChild(resultEl);
    scrollToBottom();
}

/**
 * Handle agent completion
 */
function handleAgentDone() {
    isAgentProcessing = false;
    currentAgentMessageEl = null;
    enableInput();
    elements.inputHint.textContent = 'Press Enter to send';
}

/**
 * Add download link for created file
 */
function addDownloadLink(filename) {
    // Show downloads section
    elements.downloadsSection.style.display = 'block';

    // Check if this file is already in the list
    const existingLinks = elements.downloadsList.querySelectorAll('a');
    for (const link of existingLinks) {
        if (link.textContent === filename) {
            return; // Already exists
        }
    }

    // Create download link
    const linkEl = document.createElement('a');
    linkEl.href = `${CONFIG.API_URL}/download/${encodeURIComponent(filename)}`;
    linkEl.className = 'download-link';
    linkEl.textContent = filename;
    linkEl.download = filename;
    linkEl.target = '_blank';

    elements.downloadsList.appendChild(linkEl);

    // Also show in chat
    const fileEl = document.createElement('div');
    fileEl.className = 'file-created-message';
    fileEl.innerHTML = `
        <span class="file-icon">📄</span>
        <span class="file-info">
            File created: <a href="${CONFIG.API_URL}/download/${encodeURIComponent(filename)}" target="_blank">${escapeHtml(filename)}</a>
        </span>
    `;

    elements.messages.appendChild(fileEl);
    scrollToBottom();
}

/**
 * Clear all downloads
 */
function clearDownloads() {
    elements.downloadsList.innerHTML = '';
    elements.downloadsSection.style.display = 'none';
}

/**
 * Update connection status UI
 */
function updateConnectionStatus(status) {
    const statusEl = elements.connectionStatus;
    const dot = statusEl.querySelector('.status-dot');
    const text = statusEl.querySelector('.status-text');

    statusEl.className = 'connection-status ' + status;

    switch (status) {
        case 'connected':
            text.textContent = 'Connected';
            break;
        case 'connecting':
            text.textContent = 'Connecting...';
            break;
        case 'disconnected':
            text.textContent = 'Disconnected';
            break;
        case 'error':
            text.textContent = 'Error';
            break;
    }
}

/**
 * Enable input controls
 */
function enableInput() {
    elements.messageInput.disabled = false;
    elements.sendButton.disabled = false;
    elements.messageInput.focus();
    elements.inputHint.textContent = 'Press Enter to send';
}

/**
 * Disable input controls
 */
function disableInput() {
    elements.messageInput.disabled = true;
    elements.sendButton.disabled = true;
}

/**
 * Scroll chat to bottom
 */
function scrollToBottom() {
    elements.chatContainer.scrollTop = elements.chatContainer.scrollHeight;
}

/**
 * Escape HTML to prevent XSS
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Format time for display
 */
function formatTime(date) {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', init);
