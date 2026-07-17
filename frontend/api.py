import logging
import urllib3
import httpx
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse
from frontend.state import app_state
from frontend.routers import queue, ui
from core.config import UI_CONFIG_FILE, load_clean_json
from core.json_store import is_ip_allowed

# Silence urllib3 warnings against backend self-signed proxy certs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Thread-safe / Loop-aware HTTP client registry
_http_clients = {}

def get_http_client():
    loop = asyncio.get_running_loop()
    if loop not in _http_clients:
        ui_config = load_clean_json(UI_CONFIG_FILE)
        verify_tls = ui_config.get("remote_verify_tls", False)
        limits = httpx.Limits(max_connections=100, max_keepalive_connections=20)
        _http_clients[loop] = httpx.AsyncClient(verify=verify_tls, limits=limits)
    return _http_clients[loop]

@asynccontextmanager
async def lifespan(app: FastAPI):
    app_state["active_servers"] = app_state.get("active_servers", 0) + 1
    app_state["shutdown"] = False
    try:
        yield
    finally:
        app_state["active_servers"] -= 1
        # Only tear down the global stream state if ALL server threads have exited/crashed
        if app_state["active_servers"] <= 0:
            app_state["shutdown"] = True
            for loop, client in list(_http_clients.items()):
                try: await client.aclose()
                except Exception: pass
            _http_clients.clear()

app = FastAPI(lifespan=lifespan)

def get_real_ip(request: Request, trust_proxy: bool):
    if not trust_proxy: return request.client.host if request.client else "127.0.0.1"
    forwarded = request.headers.get("Forwarded")
    if forwarded:
        for part in forwarded.split(',')[0].split(';'):
            if part.strip().lower().startswith("for="):
                val = part.strip()[4:].strip('"\'')
                if val.startswith('['): return val.split(']')[0][1:]
                if val.count(':') == 1: return val.split(':')[0]
                return val
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        val = xff.split(',')[0].strip()
        if val.startswith('['): return val.split(']')[0][1:]
        if val.count(':') == 1: return val.split(':')[0]
        return val
    return request.client.host if request.client else "127.0.0.1"

@app.middleware("http")
async def access_log_middleware(request: Request, call_next):
    # Bind the specific event loop's client to the transient request state
    request.state.http_client = get_http_client()

    ui_config = load_clean_json(UI_CONFIG_FILE)
    trust_proxy = ui_config.get("trust_proxy", False)
    real_ip = get_real_ip(request, trust_proxy)

    allowed_cidrs = ui_config.get("allowed_cidrs", [])
    if allowed_cidrs and not is_ip_allowed(real_ip, allowed_cidrs):
        logging.warning(f"Web UI access connection rejected: Client IP {real_ip} is not whitelisted.")
        return HTMLResponse("<h1>403 Forbidden</h1><p>Access denied by CIDR policy configuration rules.</p>", status_code=403)

    response = await call_next(request)
    path = request.url.path
    if path not in ["/healthcheck", "/api/queue", "/api/queue/stream"]:
        http_version = request.scope.get("http_version", "1.1")
        query = f"?{request.url.query}" if request.url.query else ""
        logging.info(f'{real_ip} - "{request.method} {path}{query} HTTP/{http_version}" {response.status_code}')
    return response

@app.api_route("/healthcheck", methods=["GET", "HEAD"])
async def healthcheck_endpoint(request: Request): return {"status": "healthy"}

# Mount Modular Routers
app.include_router(queue.router)
app.include_router(ui.router)
