import os
import json
import asyncio
import logging
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from frontend.state import app_state
from frontend.utils import get_active_config_path
from core.config import load_clean_json, ConfigOrchestrator, get_cached_ui_config, load_config
from core.queue_store import get_queue_items, retry_queue_item, delete_queue_item, get_queue_item_raw
from core.utils import safe_async_lifecycle, HttpClientPool

router = APIRouter(prefix="/api/queue")

def _get_local_queue_dir():
    """Safely resolves the local queue directory identically to the backend daemon."""
    state = load_config(ignore_missing=True, config_path=get_active_config_path())
    return state.smtp.get("queue_dir", "data/queue") if state else "data/queue"

@router.get("/stream")
async def queue_stream(request: Request):
    ui_config = get_cached_ui_config()
    bmode = ui_config.get("backend_mode", "local")

    if bmode == "remote":
        orch = ConfigOrchestrator(ui_config)
        url, sec = orch.get_primary_target_ctx()
        client = request.state.http_client

        async def event_proxy():
            async with safe_async_lifecycle("Remote API Proxy"):
                async with client.stream("GET", f"{url}/api/stream", headers={"Authorization": f"Bearer {sec}"}, timeout=None) as response:
                    if response.status_code != 200:
                        yield f"data: {json.dumps({'action': 'error', 'message': f'Upstream gateway returned HTTP {response.status_code}'})}\n\n"
                        return

                    iterator = response.aiter_text().__aiter__()
                    while not app_state["shutdown"]:
                        try:
                            chunk = await asyncio.wait_for(iterator.__anext__(), timeout=2.0)
                            yield chunk
                        except asyncio.TimeoutError:
                            yield ": keepalive\n\n"
                        except StopAsyncIteration:
                            break

        return StreamingResponse(event_proxy(), media_type="text/event-stream")
    else:
        async def fallback_stream():
            async with safe_async_lifecycle("Local File Watcher"):
                yield f"data: {json.dumps({'action': 'init', 'state': {}})}\n\n"
                while not app_state["shutdown"]:
                    yield ": keepalive\n\n"
                    await asyncio.sleep(2.0)

        return StreamingResponse(fallback_stream(), media_type="text/event-stream")

@router.get("")
async def get_queue(request: Request):
    ui_config = get_cached_ui_config()
    if ui_config.get("backend_mode", "local") == "remote":
        orch = ConfigOrchestrator(ui_config)
        url, sec = orch.get_primary_target_ctx()
        ok, data, _ = await HttpClientPool.safe_request(request.state.http_client, "GET", f"{url}/api/queue", headers={"Authorization": f"Bearer {sec}"}, timeout=5.0)
        if ok and isinstance(data, list):
            return JSONResponse(data)
        return JSONResponse([])
    else:
        return JSONResponse(get_queue_items(_get_local_queue_dir()))

@router.get("/{item_id}/eml")
async def proxy_get_queue_item_eml(request: Request, item_id: str):
    ui_config = get_cached_ui_config()
    if ui_config.get("backend_mode", "local") == "remote":
        orch = ConfigOrchestrator(ui_config)
        url, sec = orch.get_primary_target_ctx()
        ok, data, _ = await HttpClientPool.safe_request(request.state.http_client, "GET", f"{url}/api/queue/{item_id}/eml", headers={"Authorization": f"Bearer {sec}"}, timeout=5.0)
        if ok and isinstance(data, dict):
            return JSONResponse(data)
        return JSONResponse({"raw_eml_base64": ""})
    else:
        return JSONResponse({"raw_eml_base64": get_queue_item_raw(_get_local_queue_dir(), item_id)})

@router.post("/{item_id}/retry")
async def proxy_retry_queue_item(request: Request, item_id: str):
    ui_config = get_cached_ui_config()
    if ui_config.get("backend_mode", "local") == "remote":
        orch = ConfigOrchestrator(ui_config)
        url, sec = orch.get_primary_target_ctx()
        await HttpClientPool.safe_request(request.state.http_client, "POST", f"{url}/api/queue/{item_id}/retry", headers={"Authorization": f"Bearer {sec}"}, timeout=5.0)
        return JSONResponse({"status": "ok"})
    else:
        retry_queue_item(_get_local_queue_dir(), item_id)
        return JSONResponse({"status": "ok"})

@router.delete("/{item_id}")
async def proxy_delete_queue_item(request: Request, item_id: str):
    ui_config = get_cached_ui_config()
    if ui_config.get("backend_mode", "local") == "remote":
        orch = ConfigOrchestrator(ui_config)
        url, sec = orch.get_primary_target_ctx()
        await HttpClientPool.safe_request(request.state.http_client, "DELETE", f"{url}/api/queue/{item_id}", headers={"Authorization": f"Bearer {sec}"}, timeout=5.0)
        return JSONResponse({"status": "ok"})
    else:
        delete_queue_item(_get_local_queue_dir(), item_id)
        return JSONResponse({"status": "ok"})

@router.post("/test")
async def proxy_test_payload(request: Request):
    data = await request.json()
    ui_config = get_cached_ui_config()
    if ui_config.get("backend_mode", "local") == "remote":
        orch = ConfigOrchestrator(ui_config)
        url, sec = orch.get_primary_target_ctx()
        ok, resp_data, status = await HttpClientPool.safe_request(request.state.http_client, "POST", f"{url}/api/test", json=data, headers={"Authorization": f"Bearer {sec}"}, timeout=5.0)

        if not ok:
            err_msg = resp_data.get("error", f"Backend returned {status}") if isinstance(resp_data, dict) else f"Backend returned {status} - {resp_data}"
            return JSONResponse({"error": err_msg}, status_code=status if status else 500)

        return JSONResponse({"status": "ok"})
    else:
        import random
        import ssl
        import aiosmtplib
        from backend.mail_parser import build_test_email

        config = load_clean_json(get_active_config_path())
        listeners = config.get("smtp", {}).get("listeners", [])
        if not listeners: return JSONResponse({"error": "No SMTP listeners configured on the gateway core to route through."}, status_code=400)

        tls_listeners = [l for l in listeners if l.get("starttls")]
        plain_listeners = [l for l in listeners if not l.get("starttls")]
        selected_listener = random.choice(tls_listeners) if tls_listeners else random.choice(plain_listeners)

        bind_str = selected_listener.get("bind", "127.0.0.1:25")
        target_host, target_port = parse_bind_string(bind_str, 25)
        use_starttls = selected_listener.get("starttls", False)
        connect_host = "127.0.0.1" if target_host in ("0.0.0.0", "") else target_host

        msg = build_test_email(data)

        try:
            tls_ctx = ssl._create_unverified_context()
            smtp_client = aiosmtplib.SMTP(hostname=connect_host, port=target_port, use_tls=False, start_tls=use_starttls, tls_context=tls_ctx if use_starttls else None, timeout=5)
            await smtp_client.connect()
            await smtp_client.send_message(msg)
            await smtp_client.quit()
            return JSONResponse({"status": "ok"})
        except Exception as e:
            return JSONResponse({"error": f"Failed to relay payload through local listener {connect_host}:{target_port}: {e}"}, status_code=500)
