"""
FastAPI Backend for Computer-Use Agent

Provides:
- WebSocket /ws/chat for streaming agent responses
- GET /download/{filename} for file downloads
- CORS support for Electron frontend
- User authentication and chat history
"""
import os
import logging
import asyncio
from pathlib import Path
from typing import Dict, Set, Optional
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from jose import JWTError
import json

from agent_service import AgentService
from database import init_db, get_db, SessionLocal, User, ChatSession, Message
from auth import (
    verify_password,
    get_password_hash,
    create_access_token,
    get_current_user,
    decode_token,
)
from sqlalchemy.orm import Session


class RegisterRequest(BaseModel):
    """Body for POST /register. Previously these were unannotated params,
    which FastAPI treats as query parameters — meaning the password would
    be sent (and logged) in the URL. Using a body model fixes that."""
    username: str
    password: str
    email: Optional[str] = None


class CreateSessionRequest(BaseModel):
    """Body for POST /sessions. Same query-param issue as RegisterRequest."""
    title: str

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

# Initialize database
init_db()


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

# Authentication endpoints
@app.post("/token")
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(),
                                db: Session = Depends(get_db)):
    """Login endpoint to get access token."""
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=30)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/register")
async def register_user(payload: RegisterRequest, db: Session = Depends(get_db)):
    """Register a new user."""
    # Check if username is taken
    existing_user = db.query(User).filter(User.username == payload.username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already registered")

    # Check if email is taken (only if provided — previously unchecked)
    if payload.email:
        existing_email = db.query(User).filter(User.email == payload.email).first()
        if existing_email:
            raise HTTPException(status_code=400, detail="Email already registered")

    # Create new user
    hashed_password = get_password_hash(payload.password)
    db_user = User(username=payload.username, email=payload.email, password_hash=hashed_password)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return {"message": "User created successfully"}

@app.get("/users/me")
async def read_users_me(current_user: str = Depends(get_current_user)):
    """Get current user information."""
    return {"username": current_user}

# Chat session endpoints
@app.get("/sessions")
async def get_user_sessions(current_user: str = Depends(get_current_user),
                           db: Session = Depends(get_db)):
    """Get all chat sessions for the current user."""
    user = db.query(User).filter(User.username == current_user).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    sessions = db.query(ChatSession).filter(
        ChatSession.user_id == user.id
    ).order_by(ChatSession.updated_at.desc()).all()

    return [
        {
            "id": session.id,
            "title": session.title,
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "updated_at": session.updated_at.isoformat() if session.updated_at else None
        }
        for session in sessions
    ]

@app.post("/sessions")
async def create_session(payload: CreateSessionRequest, current_user: str = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    """Create a new chat session for the current user."""
    user = db.query(User).filter(User.username == current_user).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    db_session = ChatSession(
        user_id=user.id,
        title=payload.title,
        updated_at=datetime.utcnow()
    )
    db.add(db_session)
    db.commit()
    db.refresh(db_session)

    return {
        "id": db_session.id,
        "title": db_session.title,
        "created_at": db_session.created_at.isoformat() if db_session.created_at else None
    }

@app.get("/sessions/{session_id}")
async def get_session_messages(session_id: int,
                              current_user: str = Depends(get_current_user),
                              db: Session = Depends(get_db)):
    """Get all messages for a specific chat session."""
    user = db.query(User).filter(User.username == current_user).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Verify session belongs to user
    session = db.query(ChatSession).filter(
        ChatSession.id == session_id,
        ChatSession.user_id == user.id
    ).first()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    messages = db.query(Message).filter(
        Message.session_id == session_id
    ).order_by(Message.created_at).all()

    return [
        {
            "type": msg.message_type,
            "text": msg.content,
            "timestamp": msg.created_at.isoformat() if msg.created_at else None
        }
        for msg in messages
    ]

# Configure CORS for Electron frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for Electron
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.websocket("/ws/chat")
async def websocket_chat(
    websocket: WebSocket,
    token: Optional[str] = None,
    chat_session_id: Optional[int] = None,
):
    """
    WebSocket endpoint for chat with the Computer-Use Agent.

    Connect as:
        ws://host/ws/chat?token=<JWT>              (starts a new chat session)
        ws://host/ws/chat?token=<JWT>&chat_session_id=<id>  (resumes an existing one)

    Auth: a valid access token (from POST /token) is required as a query
    param, since browser WebSocket clients can't set an Authorization
    header. Connections without a valid token for an existing user are
    rejected before any agent resources are allocated.

    Input format:
        {"messages": [{"role": "user", "content": "..."}]}
    
    Output format:
        {"type": "status", "text": "...", "session_id": <id>}   (on connect)
        {"type": "agent", "text": "..."}
        {"type": "status", "text": "..."}
        {"type": "file_created", "path": "..."}
        {"type": "done"}
        {"type": "error", "text": "..."}
    """
    await websocket.accept()

    ws_id = str(id(websocket))
    agent_service = None
    db: Session = SessionLocal()
    chat_session: Optional[ChatSession] = None

    logger.info(f"WebSocket connection established: {ws_id}")

    try:
        # --- Authenticate ---
        if not token:
            await websocket.send_json({"type": "error", "text": "Missing authentication token"})
            await websocket.close(code=4401)
            return

        try:
            username = decode_token(token)
        except JWTError:
            await websocket.send_json({"type": "error", "text": "Invalid or expired token"})
            await websocket.close(code=4401)
            return

        user = db.query(User).filter(User.username == username).first()
        if not user:
            await websocket.send_json({"type": "error", "text": "User not found"})
            await websocket.close(code=4401)
            return

        # --- Resolve or create the chat session this connection belongs to ---
        if chat_session_id is not None:
            chat_session = db.query(ChatSession).filter(
                ChatSession.id == chat_session_id,
                ChatSession.user_id == user.id,
            ).first()
            if not chat_session:
                await websocket.send_json({"type": "error", "text": "Chat session not found"})
                await websocket.close(code=4404)
                return
        else:
            chat_session = ChatSession(
                user_id=user.id,
                title="New Chat",
                updated_at=datetime.utcnow(),
            )
            db.add(chat_session)
            db.commit()
            db.refresh(chat_session)

        # Create and start agent service for this connection
        agent_service = AgentService()
        active_sessions[ws_id] = agent_service
        
        await agent_service.start()
        
        # Send ready status, including which chat session we're attached to
        # so the client can persist/display it (and reconnect to it later).
        await websocket.send_json({
            "type": "status",
            "text": "Agent ready",
            "session_id": chat_session.id,
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

            # Persist the incoming user message(s) before running the agent
            for m in messages:
                if m.get("role") == "user" and m.get("content"):
                    db.add(Message(
                        session_id=chat_session.id,
                        role="user",
                        content=str(m["content"]),
                        message_type="message",
                    ))
            chat_session.updated_at = datetime.utcnow()
            db.commit()
            
            logger.info(f"Processing {len(messages)} message(s) for chat session {chat_session.id}")
            
            # Stream agent responses, persisting each one as it's yielded
            try:
                async for response in agent_service.run_agent(
                    messages, db=db, session_id=chat_session.id
                ):
                    await websocket.send_json(response)
                    
                    # Small delay to prevent overwhelming client
                    await asyncio.sleep(0.01)
                
                # Send completion message
                await websocket.send_json({"type": "done"})
                
            except Exception as e:
                logger.error(f"Agent error in chat session {chat_session.id}: {e}")
                await websocket.send_json({
                    "type": "error",
                    "text": f"Agent error: {str(e)}"
                })
    
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {ws_id}")
    
    except Exception as e:
        logger.error(f"WebSocket error in session {ws_id}: {e}")
        try:
            await websocket.send_json({
                "type": "error",
                "text": f"Connection error: {str(e)}"
            })
        except:
            pass
    
    finally:
        # Guaranteed cleanup
        if ws_id in active_sessions:
            del active_sessions[ws_id]
        
        if agent_service:
            try:
                await agent_service.stop()
            except Exception as e:
                logger.error(f"Error stopping agent for session {ws_id}: {e}")

        db.close()
        
        logger.info(f"Connection {ws_id} cleaned up")


@app.get("/download/{filename:path}")
async def download_file(filename: str, current_user: str = Depends(get_current_user)):
    """
    Download a file created by the agent.

    Requires authentication — previously this endpoint was open to anyone,
    letting unauthenticated requests read any file the agent produced.

    Note: files are still stored in one shared SAFE_DOWNLOAD_DIR rather than
    per-user subdirectories, so any authenticated user can currently
    download any agent-generated file. If per-user isolation is needed,
    the agent's working/output directory should be namespaced by user_id
    (or chat_session_id) and that prefix enforced here.
    
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