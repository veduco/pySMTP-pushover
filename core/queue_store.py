import os
import json
from core.json_store import save_json

def get_queue_items(queue_dir: str):
    """Scans the designated queue directory and returns a sorted list of standardized item payloads."""
    items = []
    if os.path.exists(queue_dir):
        for fname in os.listdir(queue_dir):
            if fname.endswith(".json"):
                try:
                    with open(os.path.join(queue_dir, fname), "r") as f:
                        data = json.load(f)
                        items.append({
                            "id": data.get("id"),
                            "title": data.get("title", "No Subject"),
                            "method": data.get("method", "pushover"),
                            "match_reason": data.get("match_reason", "Unknown Route"),
                            "retry_count": data.get("retry_count", 0),
                            "last_attempt": data.get("last_attempt", 0),
                            "next_retry": data.get("next_retry", 0),
                            "last_error": data.get("last_error", "None"),
                            "sender": data.get("sender", "gateway@localhost"),
                            "timestamp": data.get("timestamp", 0)
                        })
                except Exception:
                    pass
    # Sort descending by last attempt timestamp, falling back to creation timestamp
    items.sort(key=lambda x: x["last_attempt"] if x["last_attempt"] else x["timestamp"], reverse=True)
    return items

def retry_queue_item(queue_dir: str, item_id: str):
    """Resets the backoff timers for a specific queue item to trigger an immediate delivery retry."""
    filepath = os.path.join(queue_dir, f"{item_id}.json")
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            data["next_retry"] = 0
            data["retry_count"] = 0
            save_json(filepath, data)
            return True
        except Exception:
            pass
    return False

def delete_queue_item(queue_dir: str, item_id: str):
    """Forcefully unlinks a stuck queue item from the persistence layer."""
    filepath = os.path.join(queue_dir, f"{item_id}.json")
    if os.path.exists(filepath):
        try:
            os.remove(filepath)
            return True
        except OSError:
            pass
    return False
