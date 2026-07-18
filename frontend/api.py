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
from core.json_store import is_valid_network_target
from core.security import build_access_middleware
from core.utils import HttpClientPool

# Silence urllib3 warnings against backend self-signed proxy certs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
            await HttpClientPool.close_all()

app = FastAPI(lifespan=lifespan)

def frontend_config_resolver(request: Request):
    """Dynamically parses the UI file schema structure to extract real-time web panel settings."""
    ui_config = load_clean_json(UI_CONFIG_FILE)
    return {
        "allowed_cidrs": ui_config.get("allowed_cidrs", []),
        "trust_proxy": ui_config.get("trust_proxy", False),
        "trust_proxy_cidrs": ui_config.get("trust_proxy_cidrs", [])
    }

def frontend_pre_hook(request: Request):
    """Binds the specific event loop's HTTP client to the transient request state before dispatch."""
    ui_config = load_clean_json(UI_CONFIG_FILE)
    verify_tls = ui_config.get("remote_verify_tls", False)
    request.state.http_client = HttpClientPool.get_client("frontend", verify_tls=verify_tls)

# Wire up the unified security factory module
app.middleware("http")(build_access_middleware(
    app_type="frontend",
    config_resolver=frontend_config_resolver,
    excluded_paths=["/healthcheck", "/api/queue", "/api/queue/stream", "/api/validate/network"],
    pre_hook=frontend_pre_hook
))

@app.post("/api/validate/network")
async def validate_network_target(request: Request):
    try:
        data = await request.json()
        target = data.get("target", "")
        allow_cidr = data.get("allow_cidr", True)
        is_valid = is_valid_network_target(target, allow_cidr)
        return JSONResponse({"valid": is_valid})
    except Exception:
        return JSONResponse({"valid": False}, status_code=400)

@app.api_route("/healthcheck", methods=["GET", "HEAD"])
async def healthcheck_endpoint(request: Request): return {"status": "healthy"}

# Mount Modular Routers
app.include_router(queue.router)
app.include_router(ui.router)
