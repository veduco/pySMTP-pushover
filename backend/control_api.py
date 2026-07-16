import asyncio
import json
import logging
import os
import time
from fastapi import FastAPI, Request, Depends, HTTPException, Security
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import uvicorn
from backend.events import broker
from backend.server import generate_secp384r1_cert

# Disable built-in docs to keep the attack surface microscopic
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
security = HTTPBearer()
active_server = None

@app.middleware("http")
async def access_log_middleware(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path not in ["/healthcheck"]:
        ip = request.client.host if request.client else "127.0.0.1"
        http_version = request.scope.get("http_version", "1.1")
        logging.info(f'{ip} - "{request.method} {path} HTTP/{http_version}" {response.status_code}')
    return response

async def verify_token(request: Request, creds: HTTPAuthorizationCredentials = Security(security)):
    secret = getattr(request.app.state, "secret", "")
    if not secret or creds.credentials != secret:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return creds.credentials

@app.post("/api/reload/config", dependencies=[Depends(verify_token)])
async def api_reload_config(request: Request):
    logging.info("Control API: Remote request received to reload full configuration.")
    request.app.state.mappings_reload_event.set()
    broker.publish("CONFIG_RELOADED", None)
    return JSONResponse({"status": "reload_scheduled"})

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
        try:
            yield f"data: {json.dumps({'action': 'init', 'state': current_state})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                event = await q.get()
                if event.get("action") == "shutdown":
                    break
                yield f"data: {json.dumps(event)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            broker.remove_sub(q)

    return StreamingResponse(sse_generator(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})

@app.get("/api/config", dependencies=[Depends(verify_token)])
async def api_get_config(request: Request):
    """Serves entirely from the live in-memory AppState parameters."""
    from core.config import load_clean_json, CONFIG_FILE
    state = request.app.state.gateway_state

    # Mirror runtime structure back to the schema format for UI ingestion
    config = {
        "smtp": state.smtp.copy(),
        "pushover": state.pushover,
        "smarthost": state.smarthost,
        "routes": load_clean_json(CONFIG_FILE).get("routes", {})  # Baseline tracks raw keys for UI diffs
    }

    if "secret" in config["smtp"].get("api", {}):
        config["smtp"]["api"]["secret"] = ""

    vault = load_clean_json(state.vault_file)
    return JSONResponse({
        "config": config,
        "vault": vault,
        "smtp_meta": state.smtp.get("_smtp_meta", {})
    })

@app.post("/api/save", dependencies=[Depends(verify_token)])
async def api_save_config(request: Request):
    try:
        from core.config import save_json, CONFIG_FILE, load_clean_json
        from core.json_store import load_vault_safe
        data = await request.json()
        state = request.app.state.gateway_state
        conf_dir = os.path.dirname(CONFIG_FILE) or "."

        if "config" in data:
            new_cfg = data["config"]
            if not new_cfg.get("smtp", {}).get("api", {}).get("secret", ""):
                old_cfg = load_clean_json(CONFIG_FILE)
                if "smtp" in new_cfg and "api" in new_cfg["smtp"]:
                    new_cfg["smtp"]["api"]["secret"] = old_cfg.get("smtp", {}).get("api", {}).get("secret", "")
            save_json(CONFIG_FILE, new_cfg)

        if "vault" in data:
            v_path = state.vault_file
            vault_parsed = data["vault"]
            old_vault_data = load_vault_safe(v_path)
            new_vault = {"app": {}, "user": {}, "smarthost": {}}

            for vtype in ["app", "user"]:
                if isinstance(vault_parsed.get(vtype), list):
                    for item in vault_parsed.get(vtype, []):
                        name = item["name"]; tok = item["token"]; epoch = item["epoch"]
                        if not tok: tok = old_vault_data.get(vtype, {}).get(name, {}).get("token", "")
                        new_vault[vtype][name] = {"token": tok, "epoch": epoch}
                else:
                    new_vault[vtype] = vault_parsed.get(vtype, {})

            for alias, tok in vault_parsed.get("smarthost", {}).items():
                if not tok: tok = old_vault_data.get("smarthost", {}).get(alias, {}).get("token", "")
                new_vault["smarthost"][alias] = {"token": tok, "epoch": int(time.time())}

            save_json(v_path, new_vault)

        return JSONResponse({"status": "saved"})
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

async def start_control_api(api_conf, reload_event, mappings_reload_event, gateway_state=None):
    global active_server

    app.state.secret = api_conf.get("secret", "")
    app.state.reload_event = reload_event
    app.state.mappings_reload_event = mappings_reload_event
    app.state.gateway_state = gateway_state

    bind = api_conf.get("bind", "0.0.0.0:6443")
    host, port_str = bind.rsplit(":", 1) if ":" in bind else (bind, "6443")
    port = int(port_str)

    cert = api_conf.get("tls_cert_file")
    key = api_conf.get("tls_key_file")

    if not (cert and os.path.exists(cert) and key and os.path.exists(key)):
        logging.warning("No valid TLS certificate found for Control API. Generating a random memory-bound certificate.")
        cert, key = generate_secp384r1_cert(host, bind)

    logging.debug(f"Attempting to start HTTPS Control API listener at https://{host}:{port}")

    # Disable uvicorn's internal logging so our custom access_log_middleware handles everything uniformly
    config = uvicorn.Config(
        app=app, host=host, port=port, ssl_keyfile=key, ssl_certfile=cert,
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
