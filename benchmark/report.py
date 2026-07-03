import json

def save_report(results, metrics, path="benchmark/report.json"):
    with open(path, "w") as f:
        json.dump({
            "results": results,
            "metrics": metrics
        }, f, indent=2)