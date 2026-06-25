# Computer-Use Agent Project Documentation

## Overview

This project implements a Computer-Use Agent that can control a computer environment to perform various tasks. It combines a FastAPI backend with an Electron frontend to create a desktop application that allows users to interact with an AI agent capable of controlling a computer sandbox.

## Architecture

### High-Level Architecture

```
┌─────────────────┐    WebSocket    ┌──────────────────┐    Docker    ┌─────────────────┐
│   Electron      │ ◄──────────────►│   FastAPI        │ ◄───────────►│   Computer      │
│   Frontend      │                 │   Backend        │              │   Sandbox       │
│                 │                 │                  │              │  (Linux)        │
└─────────────────┘                 └──────────────────┘              └─────────────────┘
        │                                      │                               │
        │           REST API                   │                               │
        └──────────────────────────────────────┘                               │
        │                                                                      │
        │           File Downloads                                           │
        └──────────────────────────────────────────────────────────────────────┘
```

### Components

1. **Electron Frontend** - Desktop application interface
2. **FastAPI Backend** - WebSocket API and file serving
3. **Computer Sandbox** - Docker container running Linux environment
4. **Agent Service** - Manages the AI agent lifecycle

## Codebase Structure

```
Project Root/
├── backend/                 # FastAPI backend implementation
│   ├── main.py             # Main FastAPI application
│   └── agent_service.py    # Agent service layer
├── electron/                # Electron desktop application
│   └── main.js             # Electron main process
├── frontend/                # Frontend web application
│   ├── index.html          # Main HTML file
│   ├── styles.css          # Styling
│   └── app.js              # Frontend JavaScript
├── main.py                 # Standalone agent example
├── requirements.txt        # Python dependencies
├── package.json            # Node.js dependencies
└── pyproject.toml          # Python project configuration
```

## Frontend Implementation

### Electron Main Process (electron/main.js)

- Creates and manages the application window
- Implements security measures:
  - Context isolation
  - Sandbox mode
  - Web security enabled
  - Navigation restrictions
- Loads frontend from local files
- Handles external links by opening in default browser

### Frontend Web Application (frontend/)

#### HTML Structure (frontend/index.html)
- Header with connection status
- Chat container for messages
- Downloads section for file access
- Input area for user instructions

#### CSS Styling (frontend/styles.css)
- Modern dark-themed interface
- Responsive design
- Chat bubble styling for different message types

#### JavaScript Logic (frontend/app.js)
- WebSocket client implementation
- Message streaming handling
- Connection management with reconnection logic
- File download handling
- UI state management

## Backend Implementation

### FastAPI Application (backend/main.py)

#### Features
- WebSocket endpoint (`/ws/chat`) for real-time communication
- File download endpoint (`/download/{filename}`) with security measures
- CORS middleware for Electron frontend compatibility
- Application lifespan management for cleanup
- Health check endpoint (`/health`)

#### Security Measures
- Path traversal prevention for file downloads
- Safe directory restriction for file access
- Input validation for WebSocket messages

#### WebSocket Communication Protocol
```json
// Client to Server
{
  "messages": [
    {"role": "user", "content": "instruction text"}
  ]
}

// Server to Client
{
  "type": "agent|status|tool_result|file_created|done|error",
  "text": "message content"
}
```

### Agent Service Layer (backend/agent_service.py)

#### Responsibilities
- Manages Computer sandbox lifecycle
- Handles agent initialization and cleanup
- Provides async streaming interface for agent output
- Guarantees resource cleanup on error or completion

#### Key Methods
- `start()` - Initialize and start Computer sandbox
- `run_agent()` - Execute agent with messages and stream output
- `stop()` - Cleanup resources and disconnect Computer

## Main Application Entry Point

### Standalone Example (main.py)
Demonstrates direct usage of the Computer-Use Agent:
- Initializes Computer sandbox with Docker provider
- Creates ComputerAgent with specified model
- Runs a sample task (download PDF and summarize)
- Ensures proper cleanup

## Dependencies

### Python Dependencies (requirements.txt)
- `cua-agent` - Core agent functionality
- `cua-computer` - Computer control capabilities
- `cua-som` - OmniParser for GUI element detection
- `litellm` - Language model interface
- `python-dotenv` - Environment variable management
- `google-cloud-aiplatform` - Google Cloud AI services
- `fastapi` - Backend web framework
- `uvicorn` - ASGI server
- `websockets` - WebSocket support

### Node.js Dependencies (package.json)
- `electron` - Desktop application framework
- `electron-builder` - Application packaging

## Workflows

### 1. Application Startup
1. Electron main process starts
2. Creates application window with security settings
3. Loads frontend from local files
4. Frontend establishes WebSocket connection to backend

### 2. User Interaction Flow
1. User types instruction in frontend input
2. Frontend sends message via WebSocket
3. Backend receives message and starts agent
4. Agent executes tasks in Computer sandbox
5. Backend streams responses back to frontend
6. Frontend displays messages in chat interface

### 3. File Handling
1. Agent creates files in safe download directory
2. Backend serves files via download endpoint
3. Frontend displays download links
4. User can access files through browser download

### 4. Error Handling
1. WebSocket errors trigger reconnection logic
2. Agent errors are streamed to frontend
3. Backend ensures cleanup on session end
4. Path traversal attempts are blocked

## Security Considerations

1. **Frontend Security**
   - Context isolation and sandbox mode
   - Navigation restrictions
   - External link handling

2. **Backend Security**
   - Path traversal prevention
   - Safe directory enforcement
   - Input validation

3. **Sandbox Security**
   - Docker container isolation
   - Limited OS access
   - Controlled environment

## Development and Deployment

### Running the Application
1. Start the FastAPI backend: `uvicorn backend.main:app --reload`
2. Start the Electron frontend: `npm start`

### Building for Distribution
- Use `electron-builder` to package the application
- Configured for Windows, macOS, and Linux targets

## API Endpoints

### WebSocket
- `ws://localhost:8000/ws/chat` - Chat interface for agent communication

### HTTP
- `GET /download/{filename}` - Download files created by agent
- `GET /health` - Health check endpoint

## Message Types

### From Backend to Frontend
1. `agent` - Text output from the AI agent
2. `status` - Status updates about agent operations
3. `tool_result` - Results from tool executions
4. `file_created` - Notification of file creation
5. `done` - Agent task completion
6. `error` - Error messages

## Configuration

### Environment Variables
- `CUA_API_KEY` - API key for Computer-Use Agent services
- `NODE_ENV` - Node.js environment (development/production)

### WebSocket Configuration
- URL: `ws://localhost:8000/ws/chat`
- Reconnection delay: 3 seconds
- Maximum reconnection attempts: 5

## File Structure Safety

- All agent-created files are stored in `agent_output/` directory
- Download endpoint restricts access to this directory only
- Path traversal attempts are explicitly blocked

This documentation provides a comprehensive overview of the Computer-Use Agent project, covering its architecture, implementation details, workflows, and security considerations.