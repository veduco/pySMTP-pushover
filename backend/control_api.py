import asyncio
import json
import logging
import ssl
import os
import time
from aiohttp import web
from backend.events import broker
from backend.server import generate_secp384r1_cert

active_runner = None

@web.middleware
async def access_log_middleware(request, handler):
    response = await handler(request)
    path = request.path
    if path not in ["/healthcheck"]:
        ip = request.remote
        logging.info(f'{ip} - "{request.method} {path} HTTP/{request.version.major}.{request.version.minor}" {response.status}')
    return response

def require_auth(func):
    async def wrapper(request):
        secret = request.app.get('secret')
        auth_header = request.headers.get('Authorization')
        if not secret or auth_header != f"Bearer {secret}":
            return web.json_response({"error": "Unauthorized"}, status=401)
        return await func(request)
    return wrapper

@require_auth
async def api_reload_config(request):
    logging.info("Control API: Remote request received to reload full configuration.")
    request.app['mappings_reload_event'].set()
    broker.publish("CONFIG_RELOADED", None)
    return web.json_response({"status": "reload_scheduled"})

@require_auth
async def api_reload_listeners(request):
    logging.info("Control API: Remote request received to hot-reload TCP listeners.")
    request.app['reload_event'].set()
    return web.json_response({"status": "listeners_reload_scheduled"})

@require_auth
async def api_stream_queue(request):
    response = web.StreamResponse(headers={
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive'
    })
    await response.prepare(request)

    q = asyncio.Queue()
    current_state = broker.add_sub(q)

    try:
        await response.write(f"data: {json.dumps({'action': 'init', 'state': current_state})}\n\n".encode('utf-8'))
        while True:
            event = await q.get()
            if event.get("action") == "shutdown":
                break
            await response.write(f"data: {json.dumps(event)}\n\n".encode('utf-8'))
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    finally:
        broker.remove_sub(q)
    return response

@require_auth
async def api_get_config(request):
    from core.config import load_clean_json, CONFIG_FILE
    conf_dir = os.path.dirname(CONFIG_FILE) or "."
    config = load_clean_json(CONFIG_FILE)

    v_path = config.get("smtp", {}).get("vault_file")
    v_path = os.path.normpath(os.path.join(conf_dir, v_path)) if v_path else os.path.join(conf_dir, "vault.json")
    vault = load_clean_json(v_path)
    return web.json_response({
        "config": config,
        "vault": vault,
        "smtp_meta": config.get("smtp", {}).get("_smtp_meta", {})
    })

@require_auth
async def api_save_config(request):
    try:
        from core.config import save_json, CONFIG_FILE, load_clean_json
        from core.json_store import load_vault_safe
        data = await request.json()
        conf_dir = os.path.dirname(CONFIG_FILE) or "."

        if "config" in data:
            new_cfg = data["config"]
            if not new_cfg.get("smtp", {}).get("api", {}).get("secret", ""):
                old_cfg = load_clean_json(CONFIG_FILE)
                if "smtp" in new_cfg and "api" in new_cfg["smtp"]:
                    new_cfg["smtp"]["api"]["secret"] = old_cfg.get("smtp", {}).get("api", {}).get("secret", "")
            save_json(CONFIG_FILE, new_cfg)

        if "vault" in data:
            v_path = data.get("config", {}).get("smtp", {}).get("vault_file")
            v_path = os.path.normpath(os.path.join(conf_dir, v_path)) if v_path else os.path.join(conf_dir, "vault.json")

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

        return web.json_response({"status": "saved"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)

@require_auth
async def api_get_queue(request):
    from core.config import load_clean_json, CONFIG_FILE, SCRIPT_DIR
    config = load_clean_json(CONFIG_FILE)
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
    return web.json_response(items)

@require_auth
async def api_retry_queue_item(request):
    item_id = request.match_info['item_id']
    from core.config import load_clean_json, CONFIG_FILE, SCRIPT_DIR, save_json
    config = load_clean_json(CONFIG_FILE)
    q_path = os.path.normpath(os.path.join(SCRIPT_DIR, config.get("smtp", {}).get("queue_dir", "queue")))
    filepath = os.path.join(q_path, f"{item_id}.json")
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r') as f: data = json.load(f)
            data["next_retry"] = 0; data["retry_count"] = 0
            save_json(filepath, data)
        except Exception: pass
    return web.json_response({"status": "ok"})

@require_auth
async def api_delete_queue_item(request):
    item_id = request.match_info['item_id']
    from core.config import load_clean_json, CONFIG_FILE, SCRIPT_DIR
    config = load_clean_json(CONFIG_FILE)
    q_path = os.path.normpath(os.path.join(SCRIPT_DIR, config.get("smtp", {}).get("queue_dir", "queue")))
    filepath = os.path.join(q_path, f"{item_id}.json")
    if os.path.exists(filepath):
        try: os.remove(filepath)
        except OSError: pass
    return web.json_response({"status": "ok"})

async def on_shutdown_hook(app):
    for q in broker.subs:
        try:
            q.put_nowait({"action": "shutdown"})
        except Exception:
            pass

async def start_control_api(api_conf, reload_event, mappings_reload_event):
    global active_runner
    app = web.Application(middlewares=[access_log_middleware])
    app['secret'] = api_conf.get("secret", "")
    app['reload_event'] = reload_event
    app['mappings_reload_event'] = mappings_reload_event

    app.on_shutdown.append(on_shutdown_hook)

    app.router.add_post('/api/reload/config', api_reload_config)
    app.router.add_post('/api/reload/listeners', api_reload_listeners)
    app.router.add_get('/api/stream', api_stream_queue)
    app.router.add_get('/api/config', api_get_config)
    app.router.add_post('/api/save', api_save_config)
    app.router.add_get('/api/queue', api_get_queue)
    app.router.add_post('/api/queue/{item_id}/retry', api_retry_queue_item)
    app.router.add_delete('/api/queue/{item_id}', api_delete_queue_item)

    bind = api_conf.get("bind", "0.0.0.0:6443")
    host, port_str = bind.rsplit(":", 1) if ":" in bind else (bind, "6443")
    port = int(port_str)

    cert = api_conf.get("tls_cert_file")
    key = api_conf.get("tls_key_file")

    ssl_ctx = None
    if not (cert and os.path.exists(cert) and key and os.path.exists(key)):
        logging.warning("No valid TLS certificate found for Control API. Generating a random memory-bound certificate.")
        cert, key = generate_secp384r1_cert(host, bind)

    ssl_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ssl_ctx.load_cert_chain(certfile=cert, keyfile=key)

    logging.debug(f"Attempting to start HTTPS Control API listener at https://{host}:{port}")

    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host, port, ssl_context=ssl_ctx)
    try:
        await site.start()
        active_runner = runner
        logging.info(f"HTTPS Control API listener started at https://{host}:{port}")
    except Exception as e:
        logging.critical(f"CRITICAL: Failed to bind Control API to {bind}. Error: {e}")

async def stop_control_api():
    global active_runner
    if active_runner:
        try:
            await active_runner.cleanup()
        except Exception:
            pass
        active_runner = None
