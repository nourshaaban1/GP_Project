"""
FastAPI Backend for Computer-Use Agent

Provides:
- WebSocket /ws/chat for streaming agent responses
- GET /download/{filename} for file downloads
- CORS support for Electron frontend
"""

import os
import logging
import asyncio
from pathlib import Path
from typing import Dict, Set
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import json

try:
    from .agent_service import AgentService
except ImportError:
    from agent_service import AgentService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Track active agent sessions for cleanup
active_sessions: Dict[str, AgentService] = {}

# Safe directory for file downloads (relative to working directory)
SAFE_DOWNLOAD_DIR = Path(os.getcwd()) / "agent_output"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler.
    Ensures all agent sessions are cleaned up on shutdown.
    """
    # Create safe download directory if it doesn't exist
    SAFE_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(f"Safe download directory: {SAFE_DOWNLOAD_DIR}")
    
    yield
    
    # Shutdown: cleanup all active sessions
    logger.info(f"Shutting down, cleaning up {len(active_sessions)} active sessions...")
    cleanup_tasks = [
        session.stop() 
        for session in active_sessions.values()
    ]
    if cleanup_tasks:
        await asyncio.gather(*cleanup_tasks, return_exceptions=True)
    active_sessions.clear()
    logger.info("All sessions cleaned up")


# Create FastAPI app
app = FastAPI(
    title="Computer-Use Agent API",
    description="WebSocket API for Computer-Use Agent interactions",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS for Electron frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for Electron
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """
    WebSocket endpoint for chat with the Computer-Use Agent.
    
    Input format:
        {"messages": [{"role": "user", "content": "..."}]}
    
    Output format:
        {"type": "agent", "text": "..."}
        {"type": "status", "text": "..."}
        {"type": "file_created", "path": "..."}
        {"type": "done"}
        {"type": "error", "text": "..."}
    """
    await websocket.accept()
    
    session_id = str(id(websocket))
    agent_service = None
    
    logger.info(f"WebSocket connection established: {session_id}")
    
    try:
        # Create and start agent service for this connection
        agent_service = AgentService()
        active_sessions[session_id] = agent_service
        
        await agent_service.start()
        
        # Send ready status
        await websocket.send_json({
            "type": "status",
            "text": "Agent ready"
        })
        
        # Main message loop
        while True:
            # Wait for client message
            data = await websocket.receive_text()
            
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "text": "Invalid JSON format"
                })
                continue
            
            messages = payload.get("messages", [])
            
            if not messages:
                await websocket.send_json({
                    "type": "error",
                    "text": "No messages provided"
                })
                continue
            
            logger.info(f"Processing {len(messages)} message(s) for session {session_id}")
            
            # Stream agent responses
            try:
                async for response in agent_service.run_agent(messages):
                    await websocket.send_json(response)
                    
                    # Small delay to prevent overwhelming client
                    await asyncio.sleep(0.01)
                
                # Send completion message
                await websocket.send_json({"type": "done"})
                
            except Exception as e:
                logger.error(f"Agent error in session {session_id}: {e}")
                await websocket.send_json({
                    "type": "error",
                    "text": f"Agent error: {str(e)}"
                })
    
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {session_id}")
    
    except Exception as e:
        logger.error(f"WebSocket error in session {session_id}: {e}")
        try:
            await websocket.send_json({
                "type": "error",
                "text": f"Connection error: {str(e)}"
            })
        except:
            pass
    
    finally:
        # Guaranteed cleanup
        if session_id in active_sessions:
            del active_sessions[session_id]
        
        if agent_service:
            try:
                await agent_service.stop()
            except Exception as e:
                logger.error(f"Error stopping agent for session {session_id}: {e}")
        
        logger.info(f"Session {session_id} cleaned up")


@app.get("/download/{filename:path}")
async def download_file(filename: str):
    """
    Download a file created by the agent.
    
    Args:
        filename: Name of the file to download
    
    Returns:
        FileResponse with the requested file
    
    Raises:
        HTTPException: 404 if file not found, 403 if path traversal detected
    """
    # Security: prevent path traversal
    if ".." in filename or filename.startswith("/") or filename.startswith("\\"):
        logger.warning(f"Path traversal attempt blocked: {filename}")
        raise HTTPException(
            status_code=403,
            detail="Invalid file path"
        )
    
    # Resolve file path safely
    file_path = SAFE_DOWNLOAD_DIR / filename
    
    # Ensure the resolved path is still within safe directory
    try:
        file_path = file_path.resolve()
        safe_dir = SAFE_DOWNLOAD_DIR.resolve()
        
        if not str(file_path).startswith(str(safe_dir)):
            logger.warning(f"Path escape attempt blocked: {filename}")
            raise HTTPException(
                status_code=403,
                detail="Invalid file path"
            )
    except Exception:
        raise HTTPException(
            status_code=403,
            detail="Invalid file path"
        )
    
    # Check if file exists
    if not file_path.exists() or not file_path.is_file():
        logger.info(f"File not found: {filename}")
        raise HTTPException(
            status_code=404,
            detail="File not found"
        )
    
    logger.info(f"Serving file: {filename}")
    
    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type="application/octet-stream"
    )


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "active_sessions": len(active_sessions)
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
