import os
import json
import asyncio
import logging
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from frontend.state import app_state
from frontend.utils import get_active_config_path
from core.config import SCRIPT_DIR, UI_CONFIG_FILE, load_clean_json
from core.queue_store import get_queue_items, retry_queue_item, delete_queue_item, get_queue_item_raw
from core.utils import safe_async_lifecycle

router = APIRouter(prefix="/api/queue")

@router.get("/stream")
async def queue_stream(request: Request):
    ui_config = load_clean_json(UI_CONFIG_FILE)
    bmode = ui_config.get("backend_mode", "local")

    if bmode == "remote":
        url = ui_config.get("remote_url", "")
        sec = ui_config.get("remote_secret", "")
        client = request.state.http_client

        async def event_proxy():
            async with safe_async_lifecycle("Remote API Proxy"):
                # Explicitly override the default client timeout for the keepalive SSE connection stream
                async with client.stream("GET", f"{url.rstrip('/')}/api/stream", headers={"Authorization": f"Bearer {sec}"}, timeout=None) as response:
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
    ui_config = load_clean_json(UI_CONFIG_FILE)
    bmode = ui_config.get("backend_mode", "local")

    if bmode == "remote":
        url = ui_config.get("remote_url", "")
        sec = ui_config.get("remote_secret", "")
        client = request.state.http_client
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

@router.get("/{item_id}/eml")
async def proxy_get_queue_item_eml(request: Request, item_id: str):
    ui_config = load_clean_json(UI_CONFIG_FILE)
    bmode = ui_config.get("backend_mode", "local")

    if bmode == "remote":
        url = ui_config.get("remote_url", "")
        sec = ui_config.get("remote_secret", "")
        client = request.state.http_client
        try:
            r = await client.get(
                f"{url.rstrip('/')}/api/queue/{item_id}/eml",
                headers={"Authorization": f"Bearer {sec}"},
                timeout=5.0
            )
            if r.status_code == 200:
                return JSONResponse(r.json())
        except Exception: pass
        return JSONResponse({"raw_eml_base64": ""})
    else:
        config = load_clean_json(get_active_config_path())
        q_path = os.path.normpath(os.path.join(SCRIPT_DIR, config.get("smtp", {}).get("queue_dir", "queue")))
        raw_b64 = get_queue_item_raw(q_path, item_id)
        return JSONResponse({"raw_eml_base64": raw_b64})

@router.post("/{item_id}/retry")
async def proxy_retry_queue_item(request: Request, item_id: str):
    ui_config = load_clean_json(UI_CONFIG_FILE)
    bmode = ui_config.get("backend_mode", "local")

    if bmode == "remote":
        url = ui_config.get("remote_url", "")
        sec = ui_config.get("remote_secret", "")
        client = request.state.http_client
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
        client = request.state.http_client
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

@router.post("/test")
async def proxy_test_payload(request: Request):
    data = await request.json()
    ui_config = load_clean_json(UI_CONFIG_FILE)
    bmode = ui_config.get("backend_mode", "local")

    if bmode == "remote":
        url = ui_config.get("remote_url", "")
        sec = ui_config.get("remote_secret", "")
        client = request.state.http_client
        try:
            r = await client.post(
                f"{url.rstrip('/')}/api/test",
                json=data,
                headers={"Authorization": f"Bearer {sec}"},
                timeout=5.0
            )
            if r.status_code != 200:
                return JSONResponse({"error": f"Backend returned {r.status_code}"}, status_code=400)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)
        return JSONResponse({"status": "ok"})
    else:
        import random
        import ssl
        import aiosmtplib
        from backend.mail_parser import build_test_email

        # 1. Parse your locally running gateway configuration parameters
        config = load_clean_json(get_active_config_path())
        listeners = config.get("smtp", {}).get("listeners", [])

        if not listeners:
            return JSONResponse({"error": "No SMTP listeners configured on the gateway core to route through."}, status_code=400)

        # 2. Filter listeners and apply sorting preferences (STARTTLS prioritized)
        tls_listeners = [l for l in listeners if l.get("starttls")]
        plain_listeners = [l for l in listeners if not l.get("starttls")]

        # 3. Randomly select an operational listener based on preference tiers
        selected_listener = random.choice(tls_listeners) if tls_listeners else random.choice(plain_listeners)

        # Safely extract loopback address targets and ports
        bind_str = selected_listener.get("bind", "127.0.0.1:25")
        _, port_str = bind_str.rsplit(":", 1) if ":" in bind_str else ("127.0.0.1", "25")
        target_port = int(port_str)
        use_starttls = selected_listener.get("starttls", False)

        # 4. Generate our standardized test email object mapping seamlessly
        msg = build_test_email(data)

        # 5. Connect and relay directly through the active loopback socket
        try:
            # Enforce unverified context relaxation rule so self-signed certs never drop connections
            tls_ctx = ssl._create_unverified_context()

            smtp_client = aiosmtplib.SMTP(
                hostname="127.0.0.1",
                port=target_port,
                use_tls=False,
                start_tls=use_starttls,
                tls_context=tls_ctx if use_starttls else None,
                timeout=5
            )

            await smtp_client.connect()
            await smtp_client.send_message(msg)
            await smtp_client.quit()

            return JSONResponse({"status": "ok"})
        except Exception as e:
            return JSONResponse({"error": f"Failed to relay payload through local listener 127.0.0.1:{target_port}: {e}"}, status_code=500)
