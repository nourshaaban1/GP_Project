# Notive — AI Computer-Use Agent

Notive is a desktop application that lets you give an AI agent natural-language
instructions and watch it carry them out on a real (sandboxed) Linux desktop —
opening a browser, writing and running scripts, reading files, and so on. It's
built on three layers:

1. **Electron desktop shell** — renders the chat UI and talks to the backend.
2. **FastAPI backend** — handles user accounts, chat history, and streams
   agent activity over a WebSocket.
3. **[Cua](https://github.com/trycua/cua) (`cua-agent` / `cua-computer`)** —
   the open-source computer-use framework that actually drives a sandboxed
   Linux desktop (via Docker) on the model's behalf, using an LLM reached
   through OpenRouter.

> This README is written from the project's source files. Where the on-disk
> layout wasn't fully visible from those files, it's called out explicitly —
> adjust paths below if your local layout differs.

---

## How it all fits together

```
┌─────────────────────────┐        HTTPS / REST         ┌──────────────────────────┐
│   Electron App           │ ───────────────────────────▶ │   FastAPI Backend         │
│   (electron/main.js)     │  POST /token, /register,     │   (main.py)               │
│                           │  GET /sessions, /users/me    │                            │
│   ┌─────────────────┐    │                               │  ┌──────────────────────┐ │
│   │ frontend/        │    │        WebSocket              │  │ auth.py (JWT)         │ │
│   │ index.html        │◀──┼──────────────────────────────▶│  │ database.py (SQLite)  │ │
│   │ app.js            │    │  ws /ws/chat?token=...       │  │ agent_service.py      │ │
│   │ styles.css         │    │  &chat_session_id=...        │  └──────────┬───────────┘ │
│   └─────────────────┘    │                               │             │             │
└─────────────────────────┘                               └─────────────┼─────────────┘
                                                                          │
                                                                          ▼
                                                          ┌───────────────────────────────┐
                                                          │  cua-agent (ComputerAgent)      │
                                                          │  cua-computer (Computer)         │
                                                          │  → Docker container running       │
                                                          │    a Linux desktop (xfce)          │
                                                          │  → LLM calls routed through        │
                                                          │    OpenRouter (via litellm)         │
                                                          └───────────────────────────────┘
```

**Request flow, end to end:**

1. The Electron main process (`electron/main.js`) opens a sandboxed
   `BrowserWindow` (no Node integration, context isolation on) and loads
   `frontend/index.html`. `preload.js` exposes only a tiny, safe API to the
   page — all real work happens over plain `fetch`/`WebSocket` calls from
   `app.js`, not through Electron IPC.
2. The user signs in or registers from the in-app auth screen. `app.js`
   calls `POST /token` (form-encoded, since it's an OAuth2 password-flow
   endpoint) or `POST /register` (JSON), and stores the returned JWT.
3. `app.js` opens a WebSocket to `ws://localhost:8000/ws/chat`, passing the
   JWT and (optionally) an existing `chat_session_id` as query parameters —
   browsers can't set custom headers on a WebSocket handshake, so the token
   travels as a query param instead of an `Authorization` header.
4. `main.py` verifies the token, resolves or creates a `ChatSession` row for
   that user, and starts an `AgentService` (from `agent_service.py`), which:
   - boots a `Computer` sandbox (`cua-computer`, Docker provider, default
     image `trycua/cua-xfce:latest`)
   - wraps it in a `ComputerAgent` (`cua-agent`) configured to call an LLM
     through OpenRouter (via `litellm`, using the `openrouter/{model}`
     routing prefix)
5. As the agent thinks and acts (reasoning, screenshots, clicks, keystrokes,
   shell commands, file writes...), `agent_service.py` turns each raw event
   into a small typed message (`agent`, `status`, `tool_result`,
   `file_created`, `done`, `error`) and streams it back over the socket. Each
   message is also persisted to the `messages` table so chat history survives
   reconnects and app restarts.
6. Files the agent creates land in a server-side `agent_output/` directory
   and can be downloaded via `GET /download/{filename}`, authenticated the
   same way as any other REST call (a Bearer token — the frontend does an
   authenticated `fetch` + blob download rather than a plain link, since
   plain `<a href>` can't send an `Authorization` header).

---

## Tech stack

| Layer | Technology |
|---|---|
| Desktop shell | Electron 28 |
| Frontend | Vanilla HTML/CSS/JS (no framework/bundler) |
| Backend API | FastAPI + Uvicorn |
| Realtime transport | WebSockets |
| Auth | JWT (python-jose) + bcrypt password hashing (passlib) |
| Persistence | SQLite via SQLAlchemy ORM |
| Agent runtime | `cua-agent` / `cua-computer` (Cua open-source framework) |
| Sandbox | Docker container (`trycua/cua-xfce:latest` by default) |
| LLM access | OpenRouter, routed through `litellm` |

---

## Prerequisites

- **Python 3.12** (pinned in `.python-version`; `pyproject.toml` requires
  `>=3.12`)
- **Node.js** + **npm** (for the Electron shell — `package.json` targets
  Electron `^28.0.0`)
- **Docker**, running locally — the agent's sandbox uses
  `provider_type="docker"` by default, so Docker Desktop (or an equivalent
  daemon) must be up before you start a chat
- **An OpenRouter API key** — https://openrouter.ai — used to call whatever
  model you configure (default: `z-ai/glm-5.2`)

---

## Project structure

Based on the paths referenced in code (`main.js` loads
`../frontend/index.html` relative to `electron/`; `package.json`'s
`build.files` references `electron/**/*` and `frontend/**/*`):

```
project-root/
├── main.py                # FastAPI app, REST + WebSocket routes
├── agent_service.py        # Wraps cua-agent/cua-computer, streams events
├── auth.py                  # Password hashing, JWT issuance/validation
├── database.py               # SQLAlchemy models (User, ChatSession, Message)
├── chat_history.db            # SQLite DB, created automatically on first run
├── agent_output/                # Files the agent creates, served via /download
│
├── electron/
│   ├── main.js                    # Electron main process / BrowserWindow
│   └── preload.js                  # contextBridge, minimal renderer API
│
├── frontend/
│   ├── index.html                    # Auth screen + chat UI shell
│   ├── app.js                         # Auth, WebSocket client, session sidebar
│   └── styles.css                      # Glassmorphic UI styling
│
├── pyproject.toml     # Authoritative Python dependency list (see note below)
├── requirements.txt    # Legacy/alternate dependency list — currently stale
├── .python-version       # 3.12
├── .env.example            # Copy to .env and fill in
├── package.json               # Electron app manifest + electron-builder config
└── README.md
```

> ⚠️ **`requirements.txt` is out of date.** It predates the auth/database
> layer and is missing `sqlalchemy`, `passlib`, `python-jose`,
> `python-multipart`, and `bcrypt` — without these, `main.py` won't even
> import. Use `pyproject.toml` as the source of truth (see setup below), or
> update `requirements.txt` to match if you specifically need pip-style
> installs from it.

---

## Setup

### 1. Clone and configure environment variables

```bash
cp .env.example .env
```

Then edit `.env`:

| Variable | Purpose | Notes |
|---|---|---|
| `OPENROUTER_API_KEY` | Auth key for OpenRouter | Required — the agent can't call any model without it |
| `LLM_PROVIDER` | Provider routing hint | Defaults to `openrouter` |
| `LLM_MODEL` | Model to use | Defaults to `z-ai/glm-5.2`; must be an OpenRouter-served model, gets prefixed with `openrouter/` automatically |
| `LLM_TEMPERATURE` | Sampling temperature | Defaults to `0.7` |
| `LLM_MAX_TOKENS` | Max response tokens | Defaults to `3000` |
| `SECRET_KEY` | JWT signing secret | **Change this from the placeholder before any real use** — generate one with `openssl rand -hex 32` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | JWT lifetime | Defaults to `30` |

### 2. Install Python dependencies

Using [`uv`](https://docs.astral.sh/uv/) (recommended — the presence of
`pyproject.toml` + `.python-version` suggests this project was set up for it):

```bash
uv sync
```

Or with a plain virtualenv + pip:

```bash
python3.12 -m venv .venv
source .venv/bin/activate        # .venv\Scripts\activate on Windows
pip install -e .                 # installs from pyproject.toml
```

### 3. Pull the sandbox image

```bash
docker pull trycua/cua-xfce:latest
```

(You can substitute a different image/OS by passing `image=` /
`os_type=` when constructing `AgentService` in `agent_service.py`.)

### 4. Install Node dependencies for the Electron shell

```bash
npm install
```

---

## Running in development

You need **two processes** running: the backend, then the desktop app.

**Terminal 1 — backend:**

```bash
# with uv
uv run python main.py
# or, with your venv active
python main.py / uvicorn main:app --reload --port 8000
```

This starts Uvicorn on `http://localhost:8000`, creates `chat_history.db` and
its tables on first run (via `init_db()`), and creates the `agent_output/`
directory if it doesn't exist. Watch the logs — if `OPENROUTER_API_KEY` isn't
set you'll see a warning immediately.

**Terminal 2 — desktop app:**

```bash
npm run dev       # macOS/Linux, sets NODE_ENV=development (opens DevTools)
npm run dev:win   # Windows equivalent
# or just:
npm start
```

The Electron window loads `frontend/index.html`, which shows the sign-in
screen first. Register an account (or sign in if you already have one), and
you're in.

Since `main.js` hard-codes the frontend to talk to `ws://localhost:8000` and
`http://localhost:8000` (see `frontend/index.html`'s CSP `connect-src`), the
backend must already be running and reachable at that address before you
launch the app.

---

## API reference

All authenticated endpoints expect `Authorization: Bearer <token>`.

| Method & Path | Auth | Purpose |
|---|---|---|
| `POST /token` | — | Form-encoded login (`username`, `password`) → `{access_token, token_type}` |
| `POST /register` | — | JSON body `{username, password, email?}` → creates a user |
| `GET /users/me` | ✅ | Returns `{username}` for the current token |
| `GET /sessions` | ✅ | List the current user's chat sessions, most recently updated first |
| `POST /sessions` | ✅ | JSON body `{title}` → creates a new (empty) chat session |
| `GET /sessions/{id}` | ✅ | Full message history for one of the user's sessions |
| `WS /ws/chat?token=...&chat_session_id=...` | ✅ (query param) | Streams agent activity; creates a new session if `chat_session_id` is omitted |
| `GET /download/{filename}` | ✅ | Downloads a file the agent produced |
| `GET /health` | — | `{status, active_sessions}` liveness check |

**WebSocket message types (server → client):**

| `type` | Meaning |
|---|---|
| `status` | Human-readable status update (e.g. "Agent ready", a described mouse/keyboard action). First one on each connection also carries `session_id`. |
| `agent` | Text from the model — a spoken response or a reasoning step |
| `tool_result` | Output of a tool call (e.g. terminal output) |
| `file_created` | A file the agent produced is now downloadable |
| `done` | The agent has finished processing the current turn |
| `error` | Something went wrong |

**WebSocket message format (client → server):**

```json
{ "messages": [{ "role": "user", "content": "your instruction here" }] }
```

---

## Building a distributable

```bash
npm run build         
npm run build:win
npm run build:mac
npm run build:linux
```

`electron-builder` packages `electron/**/*` and `frontend/**/*` per
`package.json`'s `build` config. Note this only packages the Electron shell —
the FastAPI backend and Docker sandbox are not bundled and must be running
separately (or deployed remotely) for a built app to be useful.

---

## Troubleshooting

- **"Agent may fail to initialize" warning at backend startup** — `.env` is
  missing or `OPENROUTER_API_KEY` isn't set in it.
- **WebSocket closes immediately with no chat activity** — check the backend
  logs; a 4401 close code means the token was missing, invalid, expired, or
  the user no longer exists. Sign in again.
- **Agent never starts an action / hangs on "Agent ready"** — usually means
  Docker isn't running, or `trycua/cua-xfce:latest` hasn't been pulled yet.
- **`ModuleNotFoundError` on backend startup** — you likely installed from
  `requirements.txt`; see the dependency mismatch note above and install
  from `pyproject.toml` instead.
- **CORS/CSP errors in the Electron console** — the frontend's CSP only
  allows `connect-src` to `localhost:8000`; if you change the backend's
  host/port, update both `CONFIG.API_URL`/`CONFIG.WS_URL` in `app.js` and the
  `<meta http-equiv="Content-Security-Policy">` tag in `index.html`.

---

## Known limitations

- `SECRET_KEY` falls back to a hard-coded placeholder if unset — always
  override it via `.env` before anything beyond local testing.
- Downloaded files are stored in one shared directory, not scoped per user —
  any authenticated user can currently download any agent-generated file.
- `file_created` events aren't persisted to chat history, so download links
  don't reappear when reopening an old session — only in the live
  conversation that produced them.
- No token revocation / logout-everywhere — a leaked JWT is valid until it
  naturally expires (`ACCESS_TOKEN_EXPIRE_MINUTES`).

## License

MIT (per `package.json`).