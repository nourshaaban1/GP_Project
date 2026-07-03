import asyncio
import time
from typing import List, Dict, Any
from backend.agent_service import AgentService


async def run_single_task(task: Dict[str, Any]) -> Dict[str, Any]:
    events = []
    start = time.time()

    async with AgentService() as service:
        async for event in service.run_agent([
            {"role": "user", "content": task["input"]}
        ]):
            events.append(event)

    latency = time.time() - start

    return {
        "task": task,
        "events": events,
        "latency": latency
    }


async def run_all(tasks: List[Dict[str, Any]]):
    results = []
    for task in tasks:
        result = await run_single_task(task)
        results.append(result)
    return results