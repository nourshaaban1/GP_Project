def aggregate(results):
    total = len(results)
    success = sum(1 for r in results if r["success"])

    avg_steps = sum(r["steps"] for r in results) / total
    avg_latency = sum(r["latency"] for r in results) / total

    return {
        "total_tasks": total,
        "success_rate": success / total,
        "avg_steps": avg_steps,
        "avg_latency": avg_latency
    }