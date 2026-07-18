import os
import time
import json
import logging
import asyncio
import httpx
from backend.delivery_clients import send_pushover, send_smarthost
from core.utils import HttpClientPool

def _purge_queue_item_record(payload_id, state, broker):
    """Uniformly synchronization utility to clear completed or dropped alerts from RAM and disk states."""
    if broker:
        broker.publish("delete", {"id": payload_id})
    if not state.smtp.get("disable_persistence", False):
        filepath = os.path.join(state.smtp["queue_dir"], f"{payload_id}.json")
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except OSError:
                pass

async def async_worker_task(worker_id, async_q, state, broker, pushover_client):
    while True:
        payload = await async_q.get()
        if payload is None:
            async_q.task_done()
            break

        now = int(time.time())
        next_retry = payload.get("next_retry", 0)

        if not payload.get("disable_persistence"):
            filepath = os.path.join(state.smtp["queue_dir"], f"{payload['id']}.json")
            if payload.get("retry_count", 0) > 0:
                if not os.path.exists(filepath):
                    async_q.task_done()
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
            async def delayed_requeue(p):
                await asyncio.sleep(1.0)
                await async_q.put(p)
            asyncio.create_task(delayed_requeue(payload))
            async_q.task_done()
            continue

        method = payload.get("method", "pushover")

        if method == "pushover":
            success, error_msg = await send_pushover(payload, pushover_client, state=state)
        elif method == "smarthost":
            success, error_msg = await send_smarthost(payload, state)
        else:
            success, error_msg = False, "Unknown delivery method."

        if success:
            _purge_queue_item_record(payload["id"], state, broker)
        else:
            if error_msg == "DROP_ALERT":
                _purge_queue_item_record(payload["id"], state, broker)
                async_q.task_done()
                continue

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
            await async_q.put(payload)

        async_q.task_done()

async def async_delivery_manager(msg_queue, state, num_workers, broker):
    pushover_client = HttpClientPool.get_client("pushover", verify_tls=True)
    try:
        workers = [
            asyncio.create_task(async_worker_task(i, msg_queue, state, broker, pushover_client))
            for i in range(num_workers)
        ]
        await asyncio.gather(*workers, return_exceptions=True)
    finally:
        await HttpClientPool.close_all()

def load_queue_from_disk(msg_queue, state, broker=None):
    if not os.path.exists(state.smtp["queue_dir"]): return
    count = 0
    for filename in os.listdir(state.smtp["queue_dir"]):
        if filename.endswith(".json"):
            filepath = os.path.join(state.smtp["queue_dir"], filename)
            try:
                with open(filepath, 'r') as f:
                    data = json.load(f)
                    msg_queue.put_nowait(data)

                    if broker and "id" in data:
                        broker.state[data["id"]] = data

                    count += 1
            except Exception: pass
    if count > 0: logging.info(f"Read {count} messages from persistent store")
