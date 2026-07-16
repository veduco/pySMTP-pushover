import logging
import urllib3
import httpx
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from frontend.state import app_state
from frontend.routers import queue, ui
from core.config import UI_CONFIG_FILE, load_clean_json

# Silence urllib3 warnings against backend self-signed proxy certs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

@asynccontextmanager
async def lifespan(app: FastAPI):
    app_state["shutdown"] = False

    # Read the baseline UI config to apply global TLS policies
    ui_config = load_clean_json(UI_CONFIG_FILE)
    verify_tls = ui_config.get("remote_verify_tls", False)

    # Establish a highly concurrent socket pool
    limits = httpx.Limits(max_connections=100, max_keepalive_connections=20)
    async with httpx.AsyncClient(verify=verify_tls, limits=limits) as client:
        app.state.http_client = client
        yield

    app_state["shutdown"] = True

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
    ui_config = load_clean_json(UI_CONFIG_FILE)
    trust_proxy = ui_config.get("trust_proxy", False)
    real_ip = get_real_ip(request, trust_proxy)
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
