"""
Agent Service Layer

Encapsulates Computer and ComputerAgent lifecycle management.
Provides async streaming interface for agent output.
Guarantees cleanup on error or completion.
"""

import os
import logging
from typing import AsyncGenerator, List, Dict, Any, Optional
from contextlib import asynccontextmanager

from cua_agent import ComputerAgent
from computer import Computer
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AgentService:
    """
    Manages the lifecycle of a Computer-Use Agent session.
    
    Usage:
        async with AgentService() as service:
            async for message in service.run_agent(messages):
                print(message)
    """
    
    def __init__(
        self,
        model: str = "cua/anthropic/claude-3-5-sonnet-20241022",
        temperature: float = 0.7,
        os_type: str = "linux",
        provider_type: str = "docker",
        image: str = "trycua/cua-xfce:latest"
    ):
        """
        Initialize agent service configuration.
        
        Args:
            model: The AI model to use for the agent
            temperature: Model temperature for response generation
            os_type: Operating system type for the computer sandbox
            provider_type: Provider type (docker, etc.)
            image: Docker image for the sandbox
        """
        self.model = model
        self.temperature = temperature
        self.os_type = os_type
        self.provider_type = provider_type
        self.image = image
        
        self._computer: Optional[Computer] = None
        self._agent: Optional[ComputerAgent] = None
        self._is_running: bool = False
        
        # Ensure API key is set
        api_key = os.getenv("CUA_API_KEY")
        if api_key:
            os.environ["CUA_API_KEY"] = api_key
    
    async def start(self) -> None:
        """
        Initialize and start the Computer sandbox.
        
        Raises:
            RuntimeError: If service is already running
            Exception: If computer fails to start
        """
        if self._is_running:
            raise RuntimeError("Agent service is already running")
        
        logger.info("Starting Computer sandbox...")
        
        try:
            self._computer = Computer(
                os_type=self.os_type,
                provider_type=self.provider_type,
                image=self.image
            )
            
            await self._computer.run()
            
            self._agent = ComputerAgent(
                model=self.model,
                tools=[self._computer],
                temperature=self.temperature,
            )
            
            self._is_running = True
            logger.info("Agent service started successfully")
            
        except Exception as e:
            logger.error(f"Failed to start agent service: {e}")
            await self.stop()
            raise
    
    async def run_agent(
        self,
        messages: List[Dict[str, Any]]
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Run the agent with the given messages and stream output.
        
        Args:
            messages: List of message dictionaries with 'role' and 'content'
        
        Yields:
            Dict with 'type' and 'text' or other relevant data
            
        Raises:
            RuntimeError: If service is not running
        """
        if not self._is_running or not self._agent:
            raise RuntimeError("Agent service is not running. Call start() first.")
        
        logger.info(f"Running agent with {len(messages)} message(s)")
        
        try:
            async for result in self._agent.run(messages):
                # Log the full result for debugging
                logger.debug(f"Agent result: {result}")
                
                # Process each item in the output
                for item in result.get("output", []):
                    item_type = item.get("type")
                    
                    if item_type == "message":
                        # Extract and stream text content from message.
                        # The actual content type from cua_agent is "output_text", NOT "text".
                        content = item.get("content", [])
                        for content_item in content:
                            # Handle both "output_text" (cua_agent native) and "text" (fallback)
                            if content_item.get("type") in ("output_text", "text"):
                                text = content_item.get("text", "").strip()
                                if text:
                                    logger.info(f"Agent message: {text}")
                                    yield {
                                        "type": "agent",
                                        "text": text
                                    }
                    
                    elif item_type == "reasoning":
                        # Stream agent reasoning/thinking steps.
                        # These are the internal thought steps the model reports.
                        summary = item.get("summary", [])
                        for summary_item in summary:
                            if summary_item.get("type") == "summary_text":
                                reasoning_text = summary_item.get("text", "").strip()
                                if reasoning_text:
                                    logger.info(f"Agent reasoning: {reasoning_text}")
                                    yield {
                                        "type": "agent",
                                        "text": reasoning_text
                                    }
                    
                    elif item_type == "computer_call":
                        # The real action type is "computer_call", NOT "tool_use".
                        # Build a human-readable description of what the agent is doing.
                        action = item.get("action", {})
                        action_type = action.get("type", "unknown")
                        
                        action_descriptions = {
                            "screenshot": "Taking a screenshot to observe the screen",
                            "click": f"Clicking at position ({action.get('x', '?')}, {action.get('y', '?')})",
                            "double_click": f"Double-clicking at position ({action.get('x', '?')}, {action.get('y', '?')})",
                            "right_click": f"Right-clicking at position ({action.get('x', '?')}, {action.get('y', '?')})",
                            "type": f"Typing: \"{action.get('text', '')}\"",
                            "keypress": f"Pressing keys: {'+'.join(action.get('keys', []))}",
                            "scroll": f"Scrolling at ({action.get('x', '?')}, {action.get('y', '?')})",
                            "move": f"Moving mouse to ({action.get('x', '?')}, {action.get('y', '?')})",
                            "drag": "Dragging element on screen",
                            "wait": "Waiting for the screen to update",
                            "left_mouse_down": "Pressing mouse button down",
                            "left_mouse_up": "Releasing mouse button",
                            "terminate": "Task complete — stopping execution",
                        }
                        
                        description = action_descriptions.get(
                            action_type,
                            f"Performing action: {action_type}"
                        )
                        
                        logger.info(f"Computer action: {action_type} — {action}")
                        yield {
                            "type": "status",
                            "text": description
                        }
                    
                    elif item_type in ("computer_call_output", "function_call_output"):
                        # The real output types are "computer_call_output" and "function_call_output",
                        # NOT "tool_result". These contain the screenshot or text result of an action.
                        output = item.get("output", "")
                        
                        # Skip screenshot outputs (base64 images) — too large to stream as text
                        if isinstance(output, dict) and output.get("type") == "input_image":
                            logger.debug("Received screenshot output (skipping stream)")
                            continue
                        
                        # For text outputs (e.g., terminal results, error messages)
                        if isinstance(output, str) and output.strip():
                            logger.info(f"Tool output: {output}")
                            yield {
                                "type": "tool_result",
                                "text": output
                            }
                            
                            # Also check if a file was created
                            if "created" in output.lower():
                                yield {
                                    "type": "file_created",
                                    "path": output
                                }
                    
                    elif item_type == "function_call":
                        # A named function tool was called (not a computer action)
                        func_name = item.get("name", "unknown")
                        logger.info(f"Function call: {func_name}")
                        yield {
                            "type": "status",
                            "text": f"Calling function: {func_name}"
                        }
                    
                    else:
                        # Log any unrecognised item types for future debugging
                        logger.info(f"Unhandled output item type: '{item_type}' — {item}")
            
            logger.info("Agent run completed successfully")
            
        except Exception as e:
            logger.error(f"Agent run failed: {e}")
            yield {
                "type": "error",
                "text": str(e)
            }
            raise
    
    async def stop(self) -> None:
        """
        Stop the agent service and cleanup resources.
        
        Guarantees cleanup even if errors occur.
        """
        logger.info("Stopping agent service...")
        
        self._is_running = False
        self._agent = None
        
        if self._computer:
            try:
                await self._computer.disconnect()
                logger.info("Computer sandbox disconnected")
            except Exception as e:
                logger.error(f"Error disconnecting computer: {e}")
            finally:
                self._computer = None
        
        logger.info("Agent service stopped")
    
    @property
    def is_running(self) -> bool:
        """Check if the agent service is currently running."""
        return self._is_running
    
    async def __aenter__(self) -> "AgentService":
        """Async context manager entry."""
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit with guaranteed cleanup."""
        await self.stop()


@asynccontextmanager
async def create_agent_service(**kwargs) -> AsyncGenerator[AgentService, None]:
    """
    Factory function to create an agent service with guaranteed cleanup.
    
    Usage:
        async with create_agent_service() as service:
            async for msg in service.run_agent(messages):
                print(msg)
    """
    service = AgentService(**kwargs)
    try:
        await service.start()
        yield service
    finally:
        await service.stop()
