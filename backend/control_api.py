import asyncio
import json
import logging
import os
import time
import copy
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends, HTTPException, Security
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import uvicorn
from backend.events import broker
from core.json_store import parse_bind_string
from core.security import create_secure_app, TLSManager
from core.utils import safe_async_lifecycle, get_deterministic_hash

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Safely yields the app context and cleans up ephemeral assets on teardown."""
    async with safe_async_lifecycle("Control API Lifespan"):
        yield
        await asyncio.sleep(0.01)
        TLSManager.cleanup()

def backend_config_resolver(request: Request):
    """Dynamically pulls ACL constraints mapped to the live Python core loops."""
    state_ref = getattr(request.app.state, "gateway_state", None)
    return {
        "allowed_cidrs": state_ref.smtp.get("allowed_cidrs", []) if state_ref else [],
        "trust_proxy": False,
        "trust_proxy_cidrs": []
    }

# Mount onto the centralized application infrastructure factory
app = create_secure_app(
    app_type="backend",
    config_resolver=backend_config_resolver,
    lifespan_handler=lifespan,
    excluded_paths=[]  # Enforce strict zero-leak isolation on the internal worker daemon
)

security = HTTPBearer()
active_server = None

async def verify_token(request: Request, creds: HTTPAuthorizationCredentials = Security(security)):
    secret = getattr(request.app.state, "secret", "")
    if not secret or creds.credentials != secret:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return creds.credentials

@app.post("/api/reload/listeners", dependencies=[Depends(verify_token)])
async def api_reload_listeners(request: Request):
    logging.info("Control API: Remote request received to hot-reload TCP listeners.")
    request.app.state.reload_event.set()
    return JSONResponse({"status": "listeners_reload_scheduled"})

@app.get("/api/stream", dependencies=[Depends(verify_token)])
async def api_stream_queue(request: Request):
    async def sse_generator():
        q = asyncio.Queue()
        current_state = broker.add_sub(q)

        # Leverage the centralized async lifecycle manager to absorb ASGI disconnections cleanly
        async with safe_async_lifecycle("Broker Subscription"):
            yield f"data: {json.dumps({'action': 'init', 'state': current_state})}\n\n"
            while True:
                event = await q.get()
                if event.get("action") == "shutdown":
                    break
                yield f"data: {json.dumps(event)}\n\n"

        # This executes safely outside the context once the loop terminates normally via a shutdown action
        broker.remove_sub(q)

    return StreamingResponse(
        sse_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
    )

@app.get("/api/config", dependencies=[Depends(verify_token)])
async def api_get_config(request: Request):
    """Serves entirely from the live in-memory AppState parameters with zero disk I/O."""
    state = request.app.state.gateway_state

    config = copy.deepcopy(state.raw_config)
    vault = copy.deepcopy(state.raw_vault)

    c_hash = get_deterministic_hash({"config": config, "vault": vault})

    if "smtp" in config and "api" in config["smtp"] and "secret" in config["smtp"]["api"]:
        config["smtp"]["api"]["secret"] = ""

    return JSONResponse({
        "config": config,
        "vault": vault,
        "smtp_meta": state.smtp.get("_smtp_meta", {}),
        "config_hash": c_hash
    })

@app.post("/api/save", dependencies=[Depends(verify_token)])
async def api_save_config(request: Request):
    try:
        from core.config import CONFIG_FILE, save_unified_config
        data = await request.json()

        save_unified_config(CONFIG_FILE, new_config=data.get("config"), new_vault=data.get("vault"))

        c_hash = get_deterministic_hash({"config": data.get("config", {}), "vault": data.get("vault", {})})

        request.app.state.mappings_reload_event.set()
        broker.publish("CONFIG_RELOADED", None)

        return JSONResponse({"status": "saved", "config_hash": c_hash})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)

@app.get("/api/queue", dependencies=[Depends(verify_token)])
async def api_get_queue(request: Request):
    from core.queue_store import get_queue_items
    state = request.app.state.gateway_state
    items = get_queue_items(state.smtp["queue_dir"])
    return JSONResponse(items)

@app.post("/api/queue/{item_id}/retry", dependencies=[Depends(verify_token)])
async def api_retry_queue_item(request: Request, item_id: str):
    from core.queue_store import retry_queue_item
    state = request.app.state.gateway_state
    retry_queue_item(state.smtp["queue_dir"], item_id)
    return JSONResponse({"status": "ok"})

@app.delete("/api/queue/{item_id}", dependencies=[Depends(verify_token)])
async def api_delete_queue_item(request: Request, item_id: str):
    from core.queue_store import delete_queue_item
    state = request.app.state.gateway_state
    delete_queue_item(state.smtp["queue_dir"], item_id)
    return JSONResponse({"status": "ok"})

@app.post("/api/test", dependencies=[Depends(verify_token)])
async def api_test_payload(request: Request):
    from backend.smtp_handler import PushoverSMTPHandler
    from backend.events import broker
    from backend.mail_parser import build_test_email

    data = await request.json()
    msg_queue = getattr(request.app.state, "msg_queue", None)
    if not msg_queue:
        return JSONResponse({"error": "Message queue not bound to API state"}, status_code=500)

    handler = PushoverSMTPHandler(request.app.state.gateway_state, msg_queue, broker)

    msg = build_test_email(data)

    class MockEnvelope:
        def __init__(self):
            self.mail_from = msg['From']
            self.rcpt_tos = [msg['To']]
            self.content = bytes(msg)

    # Bypass the network socket completely and invoke the SMTP parsing execution chain
    await handler.handle_DATA(None, None, MockEnvelope())
    return JSONResponse({"status": "ok"})

async def start_control_api(api_conf, reload_event, mappings_reload_event, gateway_state=None, msg_queue=None):
    global active_server

    app.state.secret = api_conf.get("secret", "")
    app.state.reload_event = reload_event
    app.state.mappings_reload_event = mappings_reload_event
    app.state.gateway_state = gateway_state
    app.state.msg_queue = msg_queue

    bind = api_conf.get("bind", "0.0.0.0:6443")
    host, port = parse_bind_string(bind, 6443)

    # Retrieve unified SSLContext and memory paths
    ctx, cert_path, key_path = TLSManager.get_unified_context(
        cert_file=api_conf.get("tls_cert_file"),
        key_file=api_conf.get("tls_key_file"),
        bind_address=bind,
        listener_hostname="control-api-internal",
        global_hostname="gateway-core"
    )

    logging.debug(f"Attempting to start HTTPS Control API listener at https://{host}:{port}")

    # Disable uvicorn's internal logging so our custom access_log_middleware handles everything uniformly
    config = uvicorn.Config(
        app=app, host=host, port=port, ssl_keyfile=key_path, ssl_certfile=cert_path,
        log_config=None, access_log=False
    )
    server = uvicorn.Server(config)
    active_server = server

    try:
        logging.info(f"HTTPS Control API listener started at https://{host}:{port}")
        await server.serve()
    except asyncio.CancelledError:
        logging.debug("Control API listener task successfully cancelled during shutdown.")
    except Exception as e:
        logging.critical(f"CRITICAL: Failed to bind Control API to {bind}. Error: {e}")

async def stop_control_api():
    global active_server
    # Signal connected SSE clients to cleanly close
    for q in broker.subs:
        try: q.put_nowait({"action": "shutdown"})
        except Exception: pass
    if active_server:
        active_server.should_exit = True
        await asyncio.sleep(0.05)
        active_server = None
