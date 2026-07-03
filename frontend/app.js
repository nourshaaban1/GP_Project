/**
 * Computer-Use Agent - Frontend Application
 *
 * Handles:
 *  - Login / registration against the FastAPI backend's JWT auth endpoints
 *  - A WebSocket client that authenticates via ?token=... and resumes or
 *    creates chat sessions via ?chat_session_id=...
 *  - A session sidebar backed by GET /sessions and GET /sessions/{id}
 *  - Authenticated file downloads (the /download endpoint now requires a
 *    Bearer token, so plain <a href> links can't be used anymore)
 */

// Configuration
const CONFIG = {
    WS_URL: 'ws://localhost:8000/ws/chat',
    API_URL: 'http://localhost:8000',
    RECONNECT_DELAY: 3000,
    MAX_RECONNECT_ATTEMPTS: 5,
    TOKEN_STORAGE_KEY: 'notive_access_token'
};

// State
let socket = null;
let reconnectAttempts = 0;
let isAgentProcessing = false;
let intentionalClose = false; // true when *we* close the socket (switching/closing sessions)

let authToken = null;
let currentUsername = null;
let currentSessionId = null; // ChatSession.id the active socket is attached to
let sessionsCache = [];

let welcomeHTML = ''; // captured on load so "New Chat" can restore the welcome screen

// DOM Elements
const elements = {
    // Auth screen
    authScreen: document.getElementById('authScreen'),
    authTabs: document.querySelectorAll('.auth-tab'),
    loginForm: document.getElementById('loginForm'),
    loginUsername: document.getElementById('loginUsername'),
    loginPassword: document.getElementById('loginPassword'),
    loginSubmit: document.getElementById('loginSubmit'),
    registerForm: document.getElementById('registerForm'),
    registerUsername: document.getElementById('registerUsername'),
    registerEmail: document.getElementById('registerEmail'),
    registerPassword: document.getElementById('registerPassword'),
    registerSubmit: document.getElementById('registerSubmit'),
    authError: document.getElementById('authError'),

    // App shell
    appShell: document.getElementById('appShell'),
    sidebar: document.getElementById('sidebar'),
    newChatBtn: document.getElementById('newChatBtn'),
    sessionList: document.getElementById('sessionList'),
    currentUsernameEl: document.getElementById('currentUsername'),
    logoutBtn: document.getElementById('logoutBtn'),

    // Chat UI (unchanged from before)
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
    welcomeHTML = elements.messages.innerHTML;

    setupAuthEventListeners();
    setupAppEventListeners();

    restoreSession();
}

/* ============================================================
 * Auth
 * ============================================================ */

function setupAuthEventListeners() {
    elements.authTabs.forEach((tab) => {
        tab.addEventListener('click', () => {
            elements.authTabs.forEach((t) => t.classList.remove('active'));
            tab.classList.add('active');
            const isLogin = tab.dataset.tab === 'login';
            elements.loginForm.style.display = isLogin ? 'flex' : 'none';
            elements.registerForm.style.display = isLogin ? 'none' : 'flex';
            hideAuthError();
        });
    });

    elements.loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        hideAuthError();
        setAuthBusy(elements.loginSubmit, true, 'Signing in...');

        try {
            const token = await requestAccessToken(
                elements.loginUsername.value.trim(),
                elements.loginPassword.value
            );
            await onAuthenticated(token);
        } catch (err) {
            showAuthError(err.message || 'Sign in failed');
        } finally {
            setAuthBusy(elements.loginSubmit, false, 'Sign In');
        }
    });

    elements.registerForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        hideAuthError();
        setAuthBusy(elements.registerSubmit, true, 'Creating account...');

        const username = elements.registerUsername.value.trim();
        const password = elements.registerPassword.value;
        const email = elements.registerEmail.value.trim();

        try {
            await registerUser(username, password, email || null);
            // Auto sign-in right after successful registration
            const token = await requestAccessToken(username, password);
            await onAuthenticated(token);
        } catch (err) {
            showAuthError(err.message || 'Registration failed');
        } finally {
            setAuthBusy(elements.registerSubmit, false, 'Create Account');
        }
    });

    elements.logoutBtn.addEventListener('click', logout);
}

function setAuthBusy(button, busy, label) {
    button.disabled = busy;
    button.textContent = label;
}

function showAuthError(message) {
    elements.authError.textContent = message;
    elements.authError.style.display = 'block';
}

function hideAuthError() {
    elements.authError.style.display = 'none';
}

/**
 * POST /token — OAuth2PasswordRequestForm expects a form-encoded body,
 * not JSON.
 */
async function requestAccessToken(username, password) {
    const body = new URLSearchParams();
    body.append('username', username);
    body.append('password', password);

    const res = await fetch(`${CONFIG.API_URL}/token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body
    });

    if (!res.ok) {
        const detail = await safeErrorDetail(res);
        throw new Error(detail || 'Incorrect username or password');
    }

    const data = await res.json();
    return data.access_token;
}

/**
 * POST /register — this one takes a JSON body (RegisterRequest).
 */
async function registerUser(username, password, email) {
    const res = await fetch(`${CONFIG.API_URL}/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password, email })
    });

    if (!res.ok) {
        const detail = await safeErrorDetail(res);
        throw new Error(detail || 'Registration failed');
    }

    return res.json();
}

async function safeErrorDetail(res) {
    try {
        const data = await res.json();
        return data.detail;
    } catch {
        return null;
    }
}

/**
 * Called once we have a fresh token, whether from login or register.
 */
async function onAuthenticated(token) {
    localStorage.setItem(CONFIG.TOKEN_STORAGE_KEY, token);
    authToken = token;

    const me = await fetchCurrentUser();
    currentUsername = me.username;

    showApp();
    await loadSessionsAndStart();
}

/**
 * On startup, check for a saved token and validate it against /users/me
 * before trusting it (it may have expired, or the user may have been
 * deleted server-side).
 */
async function restoreSession() {
    const saved = localStorage.getItem(CONFIG.TOKEN_STORAGE_KEY);
    if (!saved) {
        showAuth();
        return;
    }

    authToken = saved;

    try {
        const me = await fetchCurrentUser();
        currentUsername = me.username;
        showApp();
        await loadSessionsAndStart();
    } catch {
        localStorage.removeItem(CONFIG.TOKEN_STORAGE_KEY);
        authToken = null;
        showAuth();
    }
}

async function fetchCurrentUser() {
    const res = await fetch(`${CONFIG.API_URL}/users/me`, {
        headers: { Authorization: `Bearer ${authToken}` }
    });
    if (!res.ok) {
        throw new Error('Session expired');
    }
    return res.json();
}

function logout() {
    closeSocket({ intentional: true });
    localStorage.removeItem(CONFIG.TOKEN_STORAGE_KEY);
    authToken = null;
    currentUsername = null;
    currentSessionId = null;
    sessionsCache = [];
    reconnectAttempts = 0;

    elements.messages.innerHTML = welcomeHTML;
    elements.sessionList.innerHTML = '<div class="session-list-empty">No previous chats yet</div>';
    elements.loginPassword.value = '';

    showAuth();
}

function showAuth() {
    elements.appShell.style.display = 'none';
    elements.authScreen.style.display = 'flex';
}

function showApp() {
    elements.authScreen.style.display = 'none';
    elements.appShell.style.display = 'flex';
    elements.currentUsernameEl.textContent = currentUsername || '';
}

/**
 * Wrapper around fetch() that attaches the auth header and treats a 401
 * as "the session is no longer valid" — logging the user out rather than
 * leaving them stuck against a dead token.
 */
async function authFetch(path, options = {}) {
    const res = await fetch(`${CONFIG.API_URL}${path}`, {
        ...options,
        headers: {
            ...(options.headers || {}),
            Authorization: `Bearer ${authToken}`
        }
    });

    if (res.status === 401) {
        logout();
        throw new Error('Session expired, please sign in again');
    }

    return res;
}

/* ============================================================
 * Sessions sidebar
 * ============================================================ */

function setupAppEventListeners() {
    elements.sendButton.addEventListener('click', sendMessage);

    elements.messageInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    elements.messageInput.addEventListener('input', () => {
        elements.messageInput.style.height = 'auto';
        elements.messageInput.style.height = Math.min(elements.messageInput.scrollHeight, 150) + 'px';
    });

    elements.clearDownloads.addEventListener('click', clearDownloads);

    elements.messages.addEventListener('click', (e) => {
        const card = e.target.closest('.suggestion-card');
        if (card && !elements.messageInput.disabled) {
            const prompt = card.getAttribute('data-prompt');
            if (prompt) {
                elements.messageInput.value = prompt;
                elements.messageInput.focus();
                elements.messageInput.dispatchEvent(new Event('input'));
            }
        }

        const downloadBtn = e.target.closest('.download-link');
        if (downloadBtn && downloadBtn.dataset.filename) {
            downloadFile(downloadBtn.dataset.filename);
        }
    });

    elements.downloadsList.addEventListener('click', (e) => {
        const downloadBtn = e.target.closest('.download-link');
        if (downloadBtn && downloadBtn.dataset.filename) {
            downloadFile(downloadBtn.dataset.filename);
        }
    });

    elements.newChatBtn.addEventListener('click', startNewChat);

    elements.sessionList.addEventListener('click', (e) => {
        const renameBtn = e.target.closest('.rename-btn');
        if (renameBtn && renameBtn.dataset.sessionId) {
            e.stopPropagation();
            startRenameSession(Number(renameBtn.dataset.sessionId));
            return;
        }

        const deleteBtn = e.target.closest('.delete-btn');
        if (deleteBtn && deleteBtn.dataset.sessionId) {
            e.stopPropagation();
            handleDeleteSession(Number(deleteBtn.dataset.sessionId));
            return;
        }

        const main = e.target.closest('.session-item-main');
        if (main && main.dataset.sessionId) {
            selectSession(Number(main.dataset.sessionId));
        }
    });
}

async function loadSessionsAndStart() {
    await loadSessions();
    if (sessionsCache.length > 0) {
        await selectSession(sessionsCache[0].id);
    } else {
        startNewChat();
    }
}

async function loadSessions() {
    try {
        const res = await authFetch('/sessions');
        if (!res.ok) return;
        sessionsCache = await res.json();
        renderSessionList();
    } catch (err) {
        console.error('Failed to load sessions:', err);
    }
}

function renderSessionList() {
    if (sessionsCache.length === 0) {
        elements.sessionList.innerHTML = '<div class="session-list-empty">No previous chats yet</div>';
        return;
    }

    elements.sessionList.innerHTML = sessionsCache
        .map((s) => {
            const active = s.id === currentSessionId ? ' active' : '';
            const time = s.updated_at ? formatTime(new Date(s.updated_at)) : '';
            const safeTitle = escapeHtml(s.title || 'Untitled chat');
            return `
                <div class="session-item${active}" data-session-id="${s.id}">
                    <div class="session-item-main" data-session-id="${s.id}">
                        <div class="session-item-title" data-session-id="${s.id}">${safeTitle}</div>
                        <div class="session-item-time">${time}</div>
                    </div>
                    <div class="session-item-actions">
                        <button type="button" class="session-action-btn rename-btn" data-session-id="${s.id}" title="Rename chat">✎</button>
                        <button type="button" class="session-action-btn delete-btn" data-session-id="${s.id}" title="Delete chat">🗑</button>
                    </div>
                </div>
            `;
        })
        .join('');
}

/**
 * Swap a session's title for an inline <input> so it can be renamed
 * without leaving the sidebar. Commits on Enter/blur, cancels on Escape.
 */
function startRenameSession(id) {
    const titleEl = elements.sessionList.querySelector(
        `.session-item-title[data-session-id="${id}"]`
    );
    const session = sessionsCache.find((s) => s.id === id);
    if (!titleEl || !session) return;

    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'session-rename-input';
    input.value = session.title || '';
    input.maxLength = 200;

    titleEl.replaceWith(input);
    input.focus();
    input.select();

    let settled = false;

    const commit = async () => {
        if (settled) return;
        settled = true;
        const newTitle = input.value.trim();
        if (newTitle && newTitle !== session.title) {
            await renameSession(id, newTitle);
        } else {
            renderSessionList(); // no real change — just redraw normally
        }
    };

    const cancel = () => {
        if (settled) return;
        settled = true;
        renderSessionList();
    };

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            commit();
        } else if (e.key === 'Escape') {
            e.preventDefault();
            cancel();
        }
    });

    input.addEventListener('blur', commit);
}

async function renameSession(id, title) {
    try {
        const res = await authFetch(`/sessions/${id}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title })
        });
        if (!res.ok) {
            throw new Error((await safeErrorDetail(res)) || `Rename failed (${res.status})`);
        }
        await loadSessions(); // re-pull from server so truncation/formatting stays authoritative
    } catch (err) {
        console.error('Failed to rename session:', err);
        appendErrorMessage(`Failed to rename chat: ${err.message}`);
        renderSessionList();
    }
}

async function handleDeleteSession(id) {
    const session = sessionsCache.find((s) => s.id === id);
    const label = session ? session.title || 'Untitled chat' : 'this chat';

    const confirmed = window.confirm(`Delete "${label}"? This can't be undone.`);
    if (!confirmed) return;

    try {
        const res = await authFetch(`/sessions/${id}`, { method: 'DELETE' });
        if (!res.ok) {
            throw new Error((await safeErrorDetail(res)) || `Delete failed (${res.status})`);
        }

        sessionsCache = sessionsCache.filter((s) => s.id !== id);

        if (id === currentSessionId) {
            // selectSession/startNewChat already close the socket, clear the
            // chat pane, and re-render the sidebar — no need to do it twice.
            if (sessionsCache.length > 0) {
                await selectSession(sessionsCache[0].id);
            } else {
                startNewChat();
            }
        } else {
            renderSessionList();
        }
    } catch (err) {
        console.error('Failed to delete session:', err);
        appendErrorMessage(`Failed to delete chat: ${err.message}`);
    }
}

async function selectSession(id) {
    if (id === currentSessionId && socket && socket.readyState === WebSocket.OPEN) {
        return; // already on this session
    }

    closeSocket({ intentional: true });
    currentSessionId = id;
    elements.messages.innerHTML = '';
    clearDownloads();
    renderSessionList();

    try {
        const res = await authFetch(`/sessions/${id}`);
        if (res.ok) {
            const history = await res.json();
            history.forEach(renderHistoryMessage);
        }
    } catch (err) {
        console.error('Failed to load session history:', err);
    }

    connect();
}

function startNewChat() {
    closeSocket({ intentional: true });
    currentSessionId = null;
    elements.messages.innerHTML = welcomeHTML;
    clearDownloads();
    renderSessionList();
    connect();
}

function renderHistoryMessage(msg) {
    const time = msg.timestamp ? new Date(msg.timestamp) : new Date();
    switch (msg.type) {
        case 'message': // persisted user messages use message_type "message"
            appendUserMessage(msg.text, time);
            break;
        case 'agent':
            appendAgentMessage(msg.text, time);
            break;
        case 'status':
            appendStatusMessage(msg.text);
            break;
        case 'tool_result':
            appendToolResultMessage(msg.text);
            break;
        default:
            break;
    }
}

/* ============================================================
 * WebSocket
 * ============================================================ */

function connect() {
    if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
        return;
    }
    if (!authToken) {
        return;
    }

    updateConnectionStatus('connecting');

    let url = `${CONFIG.WS_URL}?token=${encodeURIComponent(authToken)}`;
    if (currentSessionId) {
        url += `&chat_session_id=${encodeURIComponent(currentSessionId)}`;
    }

    try {
        socket = new WebSocket(url);
        socket.onopen = handleOpen;
        socket.onmessage = handleMessage;
        socket.onerror = handleError;
        socket.onclose = handleClose;
    } catch (error) {
        console.error('Failed to create WebSocket:', error);
        scheduleReconnect();
    }
}

function closeSocket({ intentional = false } = {}) {
    if (!socket) return;
    intentionalClose = intentional;
    if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
        socket.close();
    }
    socket = null;
}

function handleOpen() {
    console.log('WebSocket connected');
    reconnectAttempts = 0;
    updateConnectionStatus('connected');
    enableInput();
}

function handleMessage(event) {
    try {
        const data = JSON.parse(event.data);

        // The first "status" message on a fresh connection carries the
        // chat_session_id the backend resolved/created for us.
        if (data.session_id) {
            const isNewSession = currentSessionId !== data.session_id;
            currentSessionId = data.session_id;
            if (isNewSession) {
                loadSessions();
            }
        }

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

function handleError(error) {
    console.error('WebSocket error:', error);
    updateConnectionStatus('error');
}

function handleClose(event) {
    console.log('WebSocket closed:', event.code, event.reason);
    updateConnectionStatus('disconnected');
    disableInput();

    if (intentionalClose) {
        // We closed this on purpose (switching sessions, logging out) —
        // don't flash an error or schedule a reconnect.
        intentionalClose = false;
        return;
    }

    // 4401: auth rejected (missing/invalid/expired token, or user gone)
    if (event.code === 4401) {
        appendErrorMessage('Your session has expired. Please sign in again.');
        logout();
        return;
    }

    // 4404: the chat_session_id we asked for doesn't belong to this user
    // (or no longer exists) — fall back to starting a fresh session.
    if (event.code === 4404) {
        currentSessionId = null;
    }

    if (isAgentProcessing) {
        appendErrorMessage('Connection lost while processing. Please try again.');
        handleAgentDone();
    }

    scheduleReconnect();
}

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

/* ============================================================
 * Chat actions
 * ============================================================ */

function sendMessage() {
    const text = elements.messageInput.value.trim();

    if (!text || !socket || socket.readyState !== WebSocket.OPEN || isAgentProcessing) {
        return;
    }

    const welcomeMessage = elements.messages.querySelector('.welcome-message');
    if (welcomeMessage) {
        welcomeMessage.remove();
    }

    appendUserMessage(text);

    elements.messageInput.value = '';
    elements.messageInput.style.height = 'auto';

    const payload = {
        messages: [{ role: 'user', content: text }]
    };

    socket.send(JSON.stringify(payload));

    isAgentProcessing = true;
    disableInput();
    elements.inputHint.textContent = 'Agent is processing...';
}

function appendUserMessage(text, time = new Date()) {
    const messageEl = document.createElement('div');
    messageEl.className = 'message user-message';
    messageEl.innerHTML = `
        <div class="message-content">
            <div class="message-text">${escapeHtml(text)}</div>
            <div class="message-time">${formatTime(time)}</div>
        </div>
        <div class="message-avatar">👤</div>
    `;

    elements.messages.appendChild(messageEl);
    scrollToBottom();
}

function appendAgentMessage(text, time = new Date()) {
    const messageEl = document.createElement('div');
    messageEl.className = 'message agent-message';
    messageEl.innerHTML = `
        <div class="message-avatar">🪐</div>
        <div class="message-content">
            <div class="agent-header">
                <span class="agent-header-orb"></span>
                <span>Notive</span>
            </div>
            <div class="message-text">${escapeHtml(text)}</div>
            <div class="message-time">${formatTime(time)}</div>
        </div>
    `;

    elements.messages.appendChild(messageEl);
    scrollToBottom();
}

function appendStatusMessage(text) {
    const statusEl = document.createElement('div');
    statusEl.className = 'status-message';
    statusEl.innerHTML = `
        <span class="status-icon">✦</span>
        <span class="status-content">${escapeHtml(text)}</span>
    `;

    elements.messages.appendChild(statusEl);
    scrollToBottom();
}

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

function handleAgentDone() {
    isAgentProcessing = false;
    enableInput();
    elements.inputHint.textContent = 'Press Enter to send';
}

/* ============================================================
 * Downloads (now authenticated — /download requires a Bearer token,
 * so plain <a href> links can't be used; we fetch + blob instead)
 * ============================================================ */

function addDownloadLink(filename) {
    elements.downloadsSection.style.display = 'block';

    const existing = elements.downloadsList.querySelectorAll('.download-link');
    for (const btn of existing) {
        if (btn.dataset.filename === filename) {
            return; // already listed
        }
    }

    const btnEl = document.createElement('button');
    btnEl.type = 'button';
    btnEl.className = 'download-link';
    btnEl.textContent = filename;
    btnEl.dataset.filename = filename;
    elements.downloadsList.appendChild(btnEl);

    const fileEl = document.createElement('div');
    fileEl.className = 'file-created-message';
    fileEl.innerHTML = `
        <span class="file-icon">📄</span>
        <span class="file-info">
            File created:
            <button type="button" class="download-link" data-filename="${escapeHtml(filename)}">${escapeHtml(filename)}</button>
        </span>
    `;

    elements.messages.appendChild(fileEl);
    scrollToBottom();
}

async function downloadFile(filename) {
    const buttons = document.querySelectorAll(
        `.download-link[data-filename="${cssEscape(filename)}"]`
    );
    buttons.forEach((b) => (b.disabled = true));

    try {
        const res = await authFetch(`/download/${encodeURIComponent(filename)}`);
        if (!res.ok) {
            throw new Error(`Download failed (${res.status})`);
        }

        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
    } catch (err) {
        console.error('Download failed:', err);
        appendErrorMessage(`Failed to download "${filename}": ${err.message}`);
    } finally {
        buttons.forEach((b) => (b.disabled = false));
    }
}

/** Minimal CSS.escape fallback for building an attribute selector safely. */
function cssEscape(value) {
    return String(value).replace(/["\\]/g, '\\$&');
}

function clearDownloads() {
    elements.downloadsList.innerHTML = '';
    elements.downloadsSection.style.display = 'none';
}

/* ============================================================
 * UI helpers
 * ============================================================ */

function updateConnectionStatus(status) {
    const statusEl = elements.connectionStatus;
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

function enableInput() {
    elements.messageInput.disabled = false;
    elements.sendButton.disabled = false;
    elements.messageInput.focus();
    elements.inputHint.textContent = 'Press Enter to send';
}

function disableInput() {
    elements.messageInput.disabled = true;
    elements.sendButton.disabled = true;
}

function scrollToBottom() {
    elements.chatContainer.scrollTop = elements.chatContainer.scrollHeight;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatTime(date) {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', init);