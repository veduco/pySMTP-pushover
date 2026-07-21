import logging
import urllib3
import httpx
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse
from frontend.state import app_state
from frontend.routers import queue, ui
from core.config import UI_CONFIG_FILE, load_clean_json, get_cached_ui_config
from core.utils import is_valid_network_target, HttpClientPool
from core.security import create_secure_app

# Silence urllib3 warnings against backend self-signed proxy certs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

background_task = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manages application startup and loop-aware HTTP client teardown limits seamlessly."""
    app_state["active_servers"] = app_state.get("active_servers", 0) + 1
    app_state["shutdown"] = False

    async def sync_loop():
        from frontend.utils import background_sync_worker
        while not app_state["shutdown"]:
            await asyncio.sleep(30)
            await background_sync_worker()

    global background_task
    if app_state["active_servers"] == 1:
        background_task = asyncio.create_task(sync_loop())

    try:
        yield
    finally:
        app_state["active_servers"] -= 1
        # Only tear down the global stream state if ALL server threads have exited/crashed
        if app_state["active_servers"] <= 0:
            app_state["shutdown"] = True
            if background_task:
                background_task.cancel()
            await HttpClientPool.close_all()

def frontend_config_resolver(request: Request):
    """Dynamically parses the UI file schema structure to extract real-time web panel settings."""
    ui_config = get_cached_ui_config()
    return {
        "allowed_cidrs": ui_config.get("allowed_cidrs", []),
        "trust_proxy": ui_config.get("trust_proxy", False),
        "trust_proxy_cidrs": ui_config.get("trust_proxy_cidrs", [])
    }

def frontend_pre_hook(request: Request):
    """Binds the specific event loop's HTTP client to the transient request state before dispatch."""
    ui_config = get_cached_ui_config()
    verify_tls = ui_config.get("remote_verify_tls", False)
    request.state.http_client = HttpClientPool.get_client("frontend", verify_tls=verify_tls)

# Instantiate the Frontend application utilizing the secure app factory
app = create_secure_app(
    app_type="frontend",
    config_resolver=frontend_config_resolver,
    lifespan_handler=lifespan,
    pre_hook=frontend_pre_hook
)

@app.post("/api/validate/network")
async def validate_network_target(request: Request):
    """Proxy validator endpoint routing local UI form constraints to core validation helpers."""
    try:
        data = await request.json()
        target = data.get("target", "")
        allow_cidr = data.get("allow_cidr", True)
        is_valid = is_valid_network_target(target, allow_cidr)
        return JSONResponse({"valid": is_valid})
    except Exception:
        return JSONResponse({"valid": False}, status_code=400)

# Mount Modular Routers
app.include_router(queue.router)
app.include_router(ui.router)
