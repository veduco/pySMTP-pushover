import os
import json
import asyncio
import requests
import httpx
import logging
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from frontend.state import app_state
from frontend.utils import get_active_config_path
from core.config import SCRIPT_DIR, UI_CONFIG_FILE, load_clean_json, save_json

router = APIRouter(prefix="/api/queue")

@router.get("/stream")
async def queue_stream(request: Request):
    ui_config = load_clean_json(UI_CONFIG_FILE)
    bmode = ui_config.get("backend_mode", "local")

    if bmode == "remote":
        url = ui_config.get("remote_url", "")
        sec = ui_config.get("remote_secret", "")
        verify_tls = ui_config.get("remote_verify_tls", False)

        async def event_proxy():
            try:
                async with httpx.AsyncClient(verify=verify_tls, timeout=None) as client:
                    async with client.stream("GET", f"{url.rstrip('/')}/api/stream", headers={"Authorization": f"Bearer {sec}"}) as response:
                        iterator = response.aiter_text().__aiter__()
                        while not app_state["shutdown"]:
                            if await request.is_disconnected(): break
                            try:
                                chunk = await asyncio.wait_for(iterator.__anext__(), timeout=2.0)
                                yield chunk
                            except asyncio.TimeoutError:
                                yield ": keepalive\n\n"
                            except StopAsyncIteration:
                                break
            except asyncio.CancelledError: pass
            except Exception as e: logging.error(f"Remote queue stream proxy error: {e}")

        return StreamingResponse(event_proxy(), media_type="text/event-stream")
    else:
        async def fallback_stream():
            yield f"data: {json.dumps({'action': 'init', 'state': {}})}\n\n"
            while not app_state["shutdown"]:
                if await request.is_disconnected(): break
                yield ": keepalive\n\n"
                await asyncio.sleep(2.0)

        return StreamingResponse(fallback_stream(), media_type="text/event-stream")

@router.get("")
async def get_queue():
    ui_config = load_clean_json(UI_CONFIG_FILE)
    bmode = ui_config.get("backend_mode", "local")

    if bmode == "remote":
        url = ui_config.get("remote_url", "")
        sec = ui_config.get("remote_secret", "")
        verify_tls = ui_config.get("remote_verify_tls", False)
        try:
            r = requests.get(f"{url.rstrip('/')}/api/queue", headers={"Authorization": f"Bearer {sec}"}, verify=verify_tls, timeout=5)
            if r.status_code == 200: return JSONResponse(r.json())
        except Exception: pass
        return JSONResponse([])
    else:
        config = load_clean_json(get_active_config_path())
        q_path = os.path.normpath(os.path.join(SCRIPT_DIR, config.get("smtp", {}).get("queue_dir", "queue")))
        items = []
        if os.path.exists(q_path):
            for fname in os.listdir(q_path):
                if fname.endswith(".json"):
                    try:
                        with open(os.path.join(q_path, fname), "r") as f:
                            data = json.load(f)
                            items.append({
                                "id": data.get("id"), "title": data.get("title", "No Subject"), "method": data.get("method", "pushover"),
                                "retry_count": data.get("retry_count", 0), "last_attempt": data.get("last_attempt", 0), "next_retry": data.get("next_retry", 0),
                                "last_error": data.get("last_error", "None"), "sender": data.get("sender", "gateway@localhost"), "timestamp": data.get("timestamp", 0)
                            })
                    except Exception: pass
        items.sort(key=lambda x: x["last_attempt"] if x["last_attempt"] else x["timestamp"], reverse=True)
        return JSONResponse(items)

@router.post("/{item_id}/retry")
async def retry_queue_item(item_id: str):
    ui_config = load_clean_json(UI_CONFIG_FILE)
    bmode = ui_config.get("backend_mode", "local")

    if bmode == "remote":
        url = ui_config.get("remote_url", "")
        sec = ui_config.get("remote_secret", "")
        verify_tls = ui_config.get("remote_verify_tls", False)
        try: requests.post(f"{url.rstrip('/')}/api/queue/{item_id}/retry", headers={"Authorization": f"Bearer {sec}"}, verify=verify_tls, timeout=5)
        except Exception: pass
        return JSONResponse({"status": "ok"})
    else:
        config = load_clean_json(get_active_config_path())
        q_path = os.path.normpath(os.path.join(SCRIPT_DIR, config.get("smtp", {}).get("queue_dir", "queue")))
        filepath = os.path.join(q_path, f"{item_id}.json")
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r') as f: data = json.load(f)
                data["next_retry"] = 0; data["retry_count"] = 0
                save_json(filepath, data)
            except Exception: pass
        return JSONResponse({"status": "ok"})

@router.delete("/{item_id}")
async def delete_queue_item(item_id: str):
    ui_config = load_clean_json(UI_CONFIG_FILE)
    bmode = ui_config.get("backend_mode", "local")

    if bmode == "remote":
        url = ui_config.get("remote_url", "")
        sec = ui_config.get("remote_secret", "")
        verify_tls = ui_config.get("remote_verify_tls", False)
        try: requests.delete(f"{url.rstrip('/')}/api/queue/{item_id}", headers={"Authorization": f"Bearer {sec}"}, verify=verify_tls, timeout=5)
        except Exception: pass
        return JSONResponse({"status": "ok"})
    else:
        config = load_clean_json(get_active_config_path())
        q_path = os.path.normpath(os.path.join(SCRIPT_DIR, config.get("smtp", {}).get("queue_dir", "queue")))
        filepath = os.path.join(q_path, f"{item_id}.json")
        if os.path.exists(filepath):
            try: os.remove(filepath)
            except OSError: pass
        return JSONResponse({"status": "ok"})
