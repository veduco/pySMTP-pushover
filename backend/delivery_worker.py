import os
import time
import json
import logging
import queue
from backend.delivery_clients import send_pushover, send_smarthost

def delivery_worker(msg_queue, state, shutdown_event, broker=None):
    logging.debug("Delivery worker thread started.")
    while not shutdown_event.is_set():
        try:
            payload = msg_queue.get(timeout=1.0)
        except queue.Empty:
            continue

        if payload is None:
            msg_queue.task_done()
            break

        now = int(time.time())
        next_retry = payload.get("next_retry", 0)

        if not payload.get("disable_persistence"):
            filepath = os.path.join(state.smtp["queue_dir"], f"{payload['id']}.json")
            if payload.get("retry_count", 0) > 0:
                if not os.path.exists(filepath):
                    msg_queue.task_done()
                    continue
                try:
                    file_mtime = os.path.getmtime(filepath)
                    if payload.get("_last_mtime", 0) < file_mtime:
                        payload["_last_mtime"] = file_mtime
                        with open(filepath, 'r') as f: disk_data = json.load(f)
                        payload["next_retry"] = disk_data.get("next_retry", next_retry)
                        payload["retry_count"] = disk_data.get("retry_count", payload.get("retry_count"))
                        next_retry = payload["next_retry"]
                except Exception:
                    pass

        if now < next_retry:
            msg_queue.put(payload)
            msg_queue.task_done()
            shutdown_event.wait(1.0)
            continue

        method = payload.get("method", "pushover")

        # Execute the cleanly modularized delivery client block
        if method == "pushover":
            success, error_msg = send_pushover(payload)
        elif method == "smarthost":
            success, error_msg = send_smarthost(payload, state)
        else:
            success, error_msg = False, "Unknown delivery method."

        if success:
            if broker: broker.publish("delete", {"id": payload["id"]})
            if not payload.get("disable_persistence"):
                filepath = os.path.join(state.smtp["queue_dir"], f"{payload['id']}.json")
                if os.path.exists(filepath):
                    try: os.remove(filepath)
                    except OSError: pass
        else:
            payload["retry_count"] = payload.get("retry_count", 0) + 1
            payload["last_error"] = error_msg or "Unknown error"
            payload["last_attempt"] = now
            backoff_delay = min(5 * (2 ** (payload["retry_count"] - 1)), state.smtp["max_retry_backoff"])
            payload["next_retry"] = now + backoff_delay
            logging.warning(f"Delivery failed for ID: {payload['id']}. Retrying in {backoff_delay}s.")

            if broker: broker.publish("update", payload)

            if not payload.get("disable_persistence"):
                filepath = os.path.join(state.smtp["queue_dir"], f"{payload['id']}.json")
                if os.path.exists(filepath):
                    try:
                        with open(filepath, 'w') as f: json.dump(payload, f)
                    except Exception: pass
            msg_queue.put(payload)

        msg_queue.task_done()

def load_queue_from_disk(msg_queue, state):
    if not os.path.exists(state.smtp["queue_dir"]): return
    count = 0
    for filename in os.listdir(state.smtp["queue_dir"]):
        if filename.endswith(".json"):
            filepath = os.path.join(state.smtp["queue_dir"], filename)
            try:
                with open(filepath, 'r') as f:
                    msg_queue.put(json.load(f))
                    count += 1
            except Exception: pass
    if count > 0: logging.info(f"Read {count} messages from persistent store")
