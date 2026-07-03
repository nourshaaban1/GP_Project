def check_file_success(events, expected_files):
    created = [
        e.get("path", "")
        for e in events
        if e["type"] == "file_created"
    ]
    return all(f in "".join(created) for f in expected_files)


def check_text_success(events, expected_keywords):
    text = " ".join(
        e["text"] for e in events if e["type"] == "agent"
    ).lower()

    return all(k.lower() in text for k in expected_keywords)


def evaluate_task(result):
    task = result["task"]
    events = result["events"]

    success = False

    if task["type"] == "file_task":
        success = check_file_success(events, task.get("expected_files", []))

    elif task["type"] == "text_task":
        success = check_text_success(events, task.get("expected_keywords", []))

    steps = len([e for e in events if e["type"] == "status"])
    errors = len([e for e in events if e["type"] == "error"])

    return {
        "task_id": task["id"],
        "success": success,
        "steps": steps,
        "errors": errors,
        "latency": result["latency"]
    }