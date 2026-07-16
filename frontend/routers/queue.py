import os
import json
import asyncio
import logging
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from frontend.state import app_state
from frontend.utils import get_active_config_path
from core.config import SCRIPT_DIR, UI_CONFIG_FILE, load_clean_json
from core.queue_store import get_queue_items, retry_queue_item, delete_queue_item

router = APIRouter(prefix="/api/queue")

@router.get("/stream")
async def queue_stream(request: Request):
    ui_config = load_clean_json(UI_CONFIG_FILE)
    bmode = ui_config.get("backend_mode", "local")

    if bmode == "remote":
        url = ui_config.get("remote_url", "")
        sec = ui_config.get("remote_secret", "")
        client = request.app.state.http_client

        async def event_proxy():
            try:
                # Explicitly override the default client timeout for the keepalive SSE connection stream
                async with client.stream("GET", f"{url.rstrip('/')}/api/stream", headers={"Authorization": f"Bearer {sec}"}, timeout=None) as response:
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
async def get_queue(request: Request):
    ui_config = load_clean_json(UI_CONFIG_FILE)
    bmode = ui_config.get("backend_mode", "local")

    if bmode == "remote":
        url = ui_config.get("remote_url", "")
        sec = ui_config.get("remote_secret", "")
        client = request.app.state.http_client
        try:
            r = await client.get(
                f"{url.rstrip('/')}/api/queue",
                headers={"Authorization": f"Bearer {sec}"},
                timeout=5.0
            )
            if r.status_code == 200:
                return JSONResponse(r.json())
        except Exception: pass
        return JSONResponse([])
    else:
        config = load_clean_json(get_active_config_path())
        q_path = os.path.normpath(os.path.join(SCRIPT_DIR, config.get("smtp", {}).get("queue_dir", "queue")))
        items = get_queue_items(q_path)
        return JSONResponse(items)

@router.post("/{item_id}/retry")
async def proxy_retry_queue_item(request: Request, item_id: str):
    ui_config = load_clean_json(UI_CONFIG_FILE)
    bmode = ui_config.get("backend_mode", "local")

    if bmode == "remote":
        url = ui_config.get("remote_url", "")
        sec = ui_config.get("remote_secret", "")
        client = request.app.state.http_client
        try:
            await client.post(
                f"{url.rstrip('/')}/api/queue/{item_id}/retry",
                headers={"Authorization": f"Bearer {sec}"},
                timeout=5.0
            )
        except Exception: pass
        return JSONResponse({"status": "ok"})
    else:
        config = load_clean_json(get_active_config_path())
        q_path = os.path.normpath(os.path.join(SCRIPT_DIR, config.get("smtp", {}).get("queue_dir", "queue")))
        retry_queue_item(q_path, item_id)
        return JSONResponse({"status": "ok"})

@router.delete("/{item_id}")
async def proxy_delete_queue_item(request: Request, item_id: str):
    ui_config = load_clean_json(UI_CONFIG_FILE)
    bmode = ui_config.get("backend_mode", "local")

    if bmode == "remote":
        url = ui_config.get("remote_url", "")
        sec = ui_config.get("remote_secret", "")
        client = request.app.state.http_client
        try:
            await client.delete(
                f"{url.rstrip('/')}/api/queue/{item_id}",
                headers={"Authorization": f"Bearer {sec}"},
                timeout=5.0
            )
        except Exception: pass
        return JSONResponse({"status": "ok"})
    else:
        config = load_clean_json(get_active_config_path())
        q_path = os.path.normpath(os.path.join(SCRIPT_DIR, config.get("smtp", {}).get("queue_dir", "queue")))
        delete_queue_item(q_path, item_id)
        return JSONResponse({"status": "ok"})
