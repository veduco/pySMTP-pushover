import logging
import urllib3
import httpx
import asyncio
import json
import base64
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse, RedirectResponse
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

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

@app.middleware("http")
async def oidc_middleware(request: Request, call_next):
    ui_config = get_cached_ui_config()
    if not ui_config.get("enable_oidc"):
        return await call_next(request)

    path = request.url.path
    if path.startswith("/auth/") or path == "/healthcheck" or path == "/favicon.ico":
        return await call_next(request)

    cookie = request.cookies.get("gateway_session")
    authorized = False

    if cookie:
        try:
            secret = ui_config.get("oidc_cookie_secret", "default_secret")
            kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=b"gateway-salt", iterations=100000)
            key = base64.urlsafe_b64encode(kdf.derive(secret.encode()))
            f = Fernet(key)

            data = json.loads(f.decrypt(cookie.encode()).decode())
            if data.get("exp", 0) > time.time():
                allowed_groups = ui_config.get("oidc_allowed_groups", [])
                user_groups = data.get("groups", [])

                # Verify RBAC claim logic
                if not allowed_groups or any(g in allowed_groups for g in user_groups):
                    authorized = True
                    request.state.user = data
        except Exception:
            pass

    if not authorized:
        if request.headers.get("hx-request"):
            # Inform HTMX to execute a full page reload if the XHR hits a dead session
            return HTMLResponse(status_code=401, headers={"HX-Redirect": "/auth/login"})

        if ui_config.get("oidc_auto_redirect", True):
            return RedirectResponse(url="/auth/login")
        else:
            return HTMLResponse(
                content="""
                <div style="font-family: system-ui; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; background: #f4f4f9;">
                    <div style="background: white; padding: 2.5rem; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); text-align: center;">
                        <h2 style="margin-top: 0;">Gateway Authentication</h2>
                        <p style="margin-bottom: 2rem; opacity: 0.8;">Single Sign-On is required to access this portal.</p>
                        <a href="/auth/login" style="background: #007bff; color: white; padding: 0.75rem 1.5rem; text-decoration: none; border-radius: 4px; font-weight: bold;">Login via Identity Provider</a>
                    </div>
                </div>
                """,
                status_code=401
            )

    return await call_next(request)

@app.get("/auth/login")
async def auth_login(request: Request):
    ui_config = get_cached_ui_config()
    issuer = ui_config.get("oidc_issuer_url", "").rstrip("/")
    client_id = ui_config.get("oidc_client_id", "")
    scopes = ui_config.get("oidc_scopes", "openid profile email")

    if not issuer or not client_id:
        return HTMLResponse("OIDC Configuration is incomplete.", status_code=500)

    try:
        res = await request.state.http_client.get(f"{issuer}/.well-known/openid-configuration")
        if res.status_code == 200:
            auth_url = res.json().get("authorization_endpoint")
            if auth_url:
                redirect_uri = f"{str(request.base_url).rstrip('/')}/auth/callback"
                login_url = f"{auth_url}?response_type=code&client_id={client_id}&redirect_uri={redirect_uri}&scope={scopes}"
                return RedirectResponse(url=login_url)
    except Exception as e:
        logging.error(f"Failed to fetch OIDC discovery document: {e}")

    return HTMLResponse("Failed to initiate OIDC login. Check issuer URL.", status_code=500)

@app.get("/auth/callback")
async def auth_callback(request: Request, code: str = None):
    if not code:
        return HTMLResponse("Authorization code missing.", status_code=400)

    ui_config = get_cached_ui_config()
    issuer = ui_config.get("oidc_issuer_url", "").rstrip("/")
    client_id = ui_config.get("oidc_client_id", "")
    client_secret = ui_config.get("oidc_client_secret", "")
    claim_name = ui_config.get("oidc_claim_name", "groups")

    try:
        client = request.state.http_client
        res = await client.get(f"{issuer}/.well-known/openid-configuration")
        token_url = res.json().get("token_endpoint")
        redirect_uri = f"{str(request.base_url).rstrip('/')}/auth/callback"

        token_res = await client.post(
            token_url,
            data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri, "client_id": client_id, "client_secret": client_secret}
        )

        if token_res.status_code == 200:
            id_token = token_res.json().get("id_token")
            if not id_token:
                return HTMLResponse("ID Token missing from IdP response.", status_code=500)

            payload_b64 = id_token.split(".")[1]
            payload_b64 += "=" * ((4 - len(payload_b64) % 4) % 4)
            id_data = json.loads(base64.urlsafe_b64decode(payload_b64).decode("utf-8"))

            session_data = {
                "sub": id_data.get("sub"),
                "email": id_data.get("email"),
                "groups": id_data.get(claim_name, []),
                "exp": time.time() + 86400
            }

            secret = ui_config.get("oidc_cookie_secret", "default_secret")
            kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=b"gateway-salt", iterations=100000)
            key = base64.urlsafe_b64encode(kdf.derive(secret.encode()))
            encrypted_session = Fernet(key).encrypt(json.dumps(session_data).encode()).decode()

            response = RedirectResponse(url="/")
            response.set_cookie(key="gateway_session", value=encrypted_session, httponly=True, samesite="lax", max_age=86400)
            logging.debug(f"OIDC Login successful for user: {session_data['email']}")
            return response

        else:
            logging.debug(f"OIDC Token Exchange Failed: {token_res.text}")
            return HTMLResponse(f"IdP Token Exchange failed: {token_res.status_code}", status_code=500)

    except Exception as e:
        logging.error(f"OIDC Callback Error: {e}")
        return HTMLResponse("Internal Error during OIDC callback.", status_code=500)

@app.get("/auth/logout")
async def auth_logout():
    response = RedirectResponse(url="/")
    response.delete_cookie("gateway_session")
    return response

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
