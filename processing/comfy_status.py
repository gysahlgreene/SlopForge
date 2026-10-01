import json


def prompt_failure(entry):
    status = entry.get("status", {})
    if not isinstance(status, dict) or status.get("status_str") != "error":
        return None
    messages = status.get("messages")
    details = json.dumps(messages, ensure_ascii=False) if messages else "No error details returned."
    return f"ComfyUI prompt failed: {details}"
