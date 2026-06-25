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

from computer import Computer
from agent import ComputerAgent
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
        model: str = "cua/anthropic/claude-haiku-4.5",
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
                        # Extract and stream text content from message
                        content = item.get("content", [])
                        for content_item in content:
                            if content_item.get("type") == "text":
                                text = content_item.get("text", "")
                                # Log to console
                                logger.info(f"Agent message: {text}")
                                # Stream to client
                                yield {
                                    "type": "agent",
                                    "text": text
                                }
                    
                    elif item_type == "tool_use":
                        # Report tool usage
                        tool_name = item.get("name", "unknown")
                        tool_input = item.get("input", {})
                        logger.info(f"Tool use: {tool_name} - {tool_input}")
                        yield {
                            "type": "status",
                            "text": f"Using tool: {tool_name}"
                        }
                    
                    elif item_type == "tool_result":
                        # Stream tool results
                        tool_output = item.get("output", "")
                        tool_content = item.get("content", [])
                        
                        # Log the tool result
                        logger.info(f"Tool result: {tool_output}")
                        
                        # Check for text content in tool result
                        for content_item in tool_content:
                            if isinstance(content_item, dict):
                                if content_item.get("type") == "text":
                                    result_text = content_item.get("text", "")
                                    yield {
                                        "type": "tool_result",
                                        "text": result_text
                                    }
                        
                        # Check for file creation
                        if isinstance(tool_output, str) and "created" in tool_output.lower():
                            yield {
                                "type": "file_created",
                                "path": tool_output
                            }
                    
                    else:
                        # Log any other item types
                        logger.info(f"Other output item: {item_type} - {item}")
            
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
