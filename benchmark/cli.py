import sys
import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import json
import asyncio
from runner import run_all
from evaluator import evaluate_task
from metrics import aggregate
from report import save_report


async def main():
    with open("benchmark/tasks.json") as f:
        tasks = json.load(f)

    raw_results = await run_all(tasks)

    evaluated = [evaluate_task(r) for r in raw_results]

    metrics = aggregate(evaluated)

    print("\n=== RESULTS ===")
    for r in evaluated:
        print(r)

    print("\n=== METRICS ===")
    print(metrics)

    save_report(evaluated, metrics)


if __name__ == "__main__":
    asyncio.run(main())