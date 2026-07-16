import os
import json
import signal
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from frontend.config_manager import ConfigManager
from core.config import UI_CONFIG_FILE, load_clean_json, save_json

router = APIRouter()
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "templates")
HTML_DIR = os.path.join(TEMPLATE_DIR, "html")
JS_DIR = os.path.join(TEMPLATE_DIR, "js")

templates = Jinja2Templates(directory=[HTML_DIR, JS_DIR])

@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    ui_config = load_clean_json(UI_CONFIG_FILE)
    # Feed the global HTTP client into the ConfigManager wrapper
    manager = ConfigManager(ui_config, http_client=request.app.state.http_client)

    config, vault_data, smtp_meta, config_ok = await manager.get_config()

    safe_vault_meta = {"app": {}, "user": {}, "smarthost": {}}
    if config_ok:
        for vtype in ["app", "user", "smarthost"]:
            for alias, obj in vault_data.get(vtype, {}).items():
                epoch_val = obj.get("epoch", 0) if isinstance(obj, dict) else 0
                safe_vault_meta[vtype][alias] = epoch_val

    safe_ui_config = ui_config.copy()

    return templates.TemplateResponse("index.html", {
        "request": request, "config_json": json.dumps(config), "smtp_meta_json": json.dumps(smtp_meta),
        "vault_meta_json": json.dumps(safe_vault_meta), "ui_config_json": json.dumps(safe_ui_config),
        "config_ok": config_ok, "backend_mode": manager.bmode,
        "ui_expand_adv": safe_ui_config.get("expand_adv", False), "ui_vault_sort": safe_ui_config.get("vault_sort", "name_asc"),
        "ui_smtp_sort": safe_ui_config.get("smtp_sort", "name_asc"), "ui_smarthost_sort": safe_ui_config.get("smarthost_sort", "alias_asc"),
        "ui_tz": safe_ui_config.get("timezone", "UTC"), "ui_fmt": safe_ui_config.get("date_format", "YYYY-MM-DD HH:mm:ss"),
        "ui_relative": safe_ui_config.get("relative_time", True), "ui_loglevel": safe_ui_config.get("ui_loglevel", "INFO"),
        "ui_trust_proxy": safe_ui_config.get("trust_proxy", True)
    })

# Add the Request parameter injection here so we can hook the client state securely
@router.post("/save/config")
async def save_config(request: Request, config_json: str = Form(...), vault_json: str = Form(None)):
    ui_config = load_clean_json(UI_CONFIG_FILE)
    manager = ConfigManager(ui_config, http_client=request.app.state.http_client)

    try:
        parsed = json.loads(config_json)
        if isinstance(parsed, str):
            parsed = json.loads(parsed)

        vault_parsed = None
        if vault_json:
            vault_parsed = json.loads(vault_json)
            if isinstance(vault_parsed, str):
                vault_parsed = json.loads(vault_parsed)

        success_message = await manager.save_config(parsed, vault_parsed)

        # Returns simple HTML without triggering the UI process overlay
        return HTMLResponse(success_message)
    except Exception as e:
        return HTMLResponse(f"Error compiling config structure: {e}", status_code=500)

@router.post("/save/ui")
async def save_ui(
    timezone: str = Form(...), date_format: str = Form(...),
    relative_time: bool = Form(False), expand_adv: bool = Form(False), trust_proxy: bool = Form(False),
    vault_sort: str = Form("name_asc"), smtp_sort: str = Form("name_asc"), smarthost_sort: str = Form("alias_asc"),
    ui_loglevel: str = Form("INFO"), ui_listeners_json: str = Form("[]"),
    backend_mode: str = Form("local"), remote_url: str = Form(""), remote_secret: str = Form(""),
    local_config_path: str = Form(""), remote_verify_tls: bool = Form(False)
):
    try: listeners = json.loads(ui_listeners_json)
    except Exception: listeners = [{"bind": "0.0.0.0:8443", "https": True}]

    save_json(UI_CONFIG_FILE, {
        "listeners": listeners, "timezone": timezone, "date_format": date_format,
        "relative_time": relative_time, "expand_adv": expand_adv, "trust_proxy": trust_proxy,
        "vault_sort": vault_sort, "smtp_sort": smtp_sort, "smarthost_sort": smarthost_sort,
        "ui_loglevel": ui_loglevel, "backend_mode": backend_mode,
        "remote_url": remote_url, "remote_secret": remote_secret,
        "local_config_path": local_config_path, "remote_verify_tls": remote_verify_tls
    })

    if backend_mode == "local" and local_config_path:
        os.environ["GATEWAY_CONFIG"] = local_config_path

    os.kill(os.getpid(), signal.SIGUSR1)

    res = HTMLResponse("UI engine configuration and Backend modes altered successfully. Reconnecting...")
    res.headers["HX-Trigger"] = "reconnectLink"
    return res
