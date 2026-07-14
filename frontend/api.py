import os
import json
import time
import signal
import re
import hashlib
import uuid
import datetime
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from core.config import SCRIPT_DIR, CONFIG_FILE, UI_CONFIG_FILE, SMTP_PID_FILE, load_clean_json, save_json, load_vault_safe

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), "templates")
templates = Jinja2Templates(directory=TEMPLATE_DIR)

def signal_smtp_app(restart_listeners=False):
    if not os.path.exists(SMTP_PID_FILE): return False
    with open(SMTP_PID_FILE, 'r') as f: pid = int(f.read().strip())
    try:
        os.kill(pid, signal.SIGUSR2)
        if restart_listeners:
            time.sleep(5.0)
            os.kill(pid, signal.SIGUSR1)
        return True
    except ProcessLookupError: return False

def generate_ui_cert():
    cert_path, key_path = "/tmp/ui_cert.pem", "/tmp/ui_key.pem"
    if os.path.exists(cert_path): return cert_path, key_path
    private_key = ec.generate_private_key(ec.SECP384R1())
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, str(uuid.uuid4()))])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = x509.CertificateBuilder().subject_name(subject).issuer_name(issuer).public_key(private_key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now).not_valid_after(now + datetime.timedelta(days=365)).sign(private_key, hashes.SHA256())
    with open(key_path, "wb") as f: f.write(private_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
    with open(cert_path, "wb") as f: f.write(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path

def resolve_vault_path(config_data=None):
    if config_data is None:
        config_data = load_clean_json(CONFIG_FILE)

    conf_dir = os.path.dirname(CONFIG_FILE) or "."
    v_path = config_data.get("smtp", {}).get("vault_file")

    if not v_path: return os.path.join(conf_dir, "vault.json")
    return os.path.normpath(os.path.join(conf_dir, v_path))

@asynccontextmanager
async def lifespan(app: FastAPI):
    v_path = resolve_vault_path()
    if not os.path.exists(v_path): save_json(v_path, {"app": {}, "user": {}, "smarthost": {}})
    yield

app = FastAPI(lifespan=lifespan)

@app.api_route("/healthcheck", methods=["GET", "HEAD"])
async def healthcheck_endpoint(request: Request): return {"status": "healthy"}

@app.get("/api/queue")
async def get_queue():
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
    return JSONResponse(items)

@app.post("/api/queue/{item_id}/retry")
async def retry_queue_item(item_id: str):
    config = load_clean_json(CONFIG_FILE)
    q_path = os.path.normpath(os.path.join(SCRIPT_DIR, config.get("smtp", {}).get("queue_dir", "queue")))
    filepath = os.path.join(q_path, f"{item_id}.json")
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r') as f: data = json.load(f)
            data["next_retry"] = 0; data["retry_count"] = 0
            save_json(filepath, data)
        except Exception: pass
    return JSONResponse({"status": "ok"})

@app.delete("/api/queue/{item_id}")
async def delete_queue_item(item_id: str):
    config = load_clean_json(CONFIG_FILE)
    q_path = os.path.normpath(os.path.join(SCRIPT_DIR, config.get("smtp", {}).get("queue_dir", "queue")))
    filepath = os.path.join(q_path, f"{item_id}.json")
    if os.path.exists(filepath):
        try: os.remove(filepath)
        except OSError: pass
    return JSONResponse({"status": "ok"})

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    config = load_clean_json(CONFIG_FILE)
    ui_config = load_clean_json(UI_CONFIG_FILE)

    v_path = resolve_vault_path(config)
    vault_data = load_vault_safe(v_path)

    safe_vault_meta = {"app": {}, "user": {}, "smarthost": {}}
    for vtype in ["app", "user", "smarthost"]:
        for alias, obj in vault_data.get(vtype, {}).items():
            safe_vault_meta[vtype][alias] = obj.get("epoch", 0)

    changed_config = False
    if "routes" not in config:
        config["routes"] = {}
        po = config.get("pushover", {})
        to_del = []
        for k, v in po.items():
            if k not in ["user", "token", "device", "sound", "url", "url_title", "tags", "priority", "ttl", "retry", "expire", "attachments", "force_plaintext", "disable_persistence"] and isinstance(v, dict):
                v["method"] = "pushover"; config["routes"][k] = v; to_del.append(k)
        for k in to_del: del po[k]
        changed_config = True

    if "disable_persistence" in config.get("pushover", {}):
        if "smtp" not in config: config["smtp"] = {}
        config["smtp"]["disable_persistence"] = config["pushover"]["disable_persistence"]
        del config["pushover"]["disable_persistence"]
        changed_config = True

    if "smarthost" not in config: config["smarthost"] = {"aliases": {}, "globals": {}}; changed_config = True
    if "smtp" not in config: config["smtp"] = {}
    if "default_route" not in config["smtp"]: config["smtp"]["default_route"] = "pushover"; changed_config = True

    auth_block = config.get("smtp", {}).get("auth", {})
    meta_block = config.get("smtp", {}).get("_smtp_meta", {})
    for user, pwd in list(auth_block.items()):
        if not pwd.startswith("$") and not re.match(r'^[a-fA-F0-9]{64}$', pwd):
            auth_block[user] = hashlib.sha256(pwd.encode('utf-8')).hexdigest()
            if user not in meta_block: meta_block[user] = int(time.time())
            changed_config = True

    if changed_config:
        config["smtp"]["auth"] = auth_block
        config["smtp"]["_smtp_meta"] = meta_block
        save_json(CONFIG_FILE, config)
        signal_smtp_app(restart_listeners=False)

    return templates.TemplateResponse("index.html", {
        "request": request, "config_json": json.dumps(config), "smtp_meta_json": json.dumps(config.get("smtp", {}).get("_smtp_meta", {})),
        "vault_meta_json": json.dumps(safe_vault_meta), "ui_config_json": json.dumps(ui_config),
        "ui_expand_adv": ui_config.get("expand_adv", False), "ui_vault_sort": ui_config.get("vault_sort", "name_asc"),
        "ui_smtp_sort": ui_config.get("smtp_sort", "name_asc"), "ui_smarthost_sort": ui_config.get("smarthost_sort", "alias_asc"),
        "ui_tz": ui_config.get("timezone", "UTC"), "ui_fmt": ui_config.get("date_format", "YYYY-MM-DD HH:mm:ss"),
        "ui_relative": ui_config.get("relative_time", True), "ui_loglevel": ui_config.get("ui_loglevel", "INFO")
    })

@app.post("/save/config")
async def save_config(config_json: str = Form(...), vault_json: str = Form(None)):
    try:
        parsed = json.loads(config_json)
        old_config = load_clean_json(CONFIG_FILE)

        v_path = resolve_vault_path(parsed)

        auth_block = parsed.get("smtp", {}).get("auth", {})
        meta_block = parsed.get("_smtp_meta", {})
        for user, pwd in list(auth_block.items()):
            if str(pwd).startswith("RAW:"):
                auth_block[user] = hashlib.sha256(pwd[4:].encode('utf-8')).hexdigest()
                if user not in meta_block: meta_block[user] = int(time.time())
        parsed["smtp"]["_smtp_meta"] = meta_block
        if "_smtp_meta" in parsed: del parsed["_smtp_meta"]
        save_json(CONFIG_FILE, parsed)

        if vault_json:
            vault_parsed = json.loads(vault_json)
            vault_data = load_vault_safe(v_path)
            new_vault = {"app": {}, "user": {}, "smarthost": {}}
            for vtype in ["app", "user"]:
                for item in vault_parsed.get(vtype, []):
                    name = item["name"]; tok = item["token"]; epoch = item["epoch"]
                    if tok == "__RETAIN__": tok = vault_data[vtype].get(name, {}).get("token", "")
                    new_vault[vtype][name] = {"token": tok, "epoch": epoch}
            for alias, tok in vault_parsed.get("smarthost", {}).items():
                if tok == "__RETAIN__": tok = vault_data.get("smarthost", {}).get(alias, {}).get("token", "")
                new_vault["smarthost"][alias] = {"token": tok, "epoch": int(time.time())}
            save_json(v_path, new_vault)

        old_smtp = old_config.get("smtp", {})
        new_smtp = parsed.get("smtp", {})
        if "_smtp_meta" in old_smtp: del old_smtp["_smtp_meta"]
        if "_smtp_meta" in new_smtp: del new_smtp["_smtp_meta"]
        signal_smtp_app(restart_listeners=(old_smtp != new_smtp))
        return HTMLResponse("Configuration successfully synchronized with the gateway daemon.")
    except Exception as e: return HTMLResponse(f"Error compiling config structure: {e}")

@app.post("/save/vault_state")
async def save_vault_state(vault_json: str = Form(...)):
    try:
        parsed = json.loads(vault_json)
        v_path = resolve_vault_path()
        vault_data = load_vault_safe(v_path)

        new_vault = {"app": {}, "user": {}, "smarthost": {}}
        for vtype in ["app", "user"]:
            for item in parsed.get(vtype, []):
                name = item["name"]; tok = item["token"]; epoch = item["epoch"]
                if tok == "__RETAIN__": tok = vault_data[vtype].get(name, {}).get("token", "")
                new_vault[vtype][name] = {"token": tok, "epoch": epoch}
            for alias, tok in parsed.get("smarthost", {}).items():
                if tok == "__RETAIN__": tok = vault_data.get("smarthost", {}).get(alias, {}).get("token", "")
                new_vault["smarthost"][alias] = {"token": tok, "epoch": int(time.time())}

        save_json(v_path, new_vault)
        signal_smtp_app(restart_listeners=False)
        return HTMLResponse("Token Vault safely synchronized with the gateway daemon.")
    except Exception as e: return HTMLResponse(f"Error parsing Vault Array: {e}")

@app.post("/save/ui")
async def save_ui(
    timezone: str = Form(...), date_format: str = Form(...),
    relative_time: bool = Form(False), expand_adv: bool = Form(False),
    vault_sort: str = Form("name_asc"), smtp_sort: str = Form("name_asc"), smarthost_sort: str = Form("alias_asc"),
    ui_loglevel: str = Form("INFO"), ui_listeners_json: str = Form("[]")
):
    try: listeners = json.loads(ui_listeners_json)
    except Exception: listeners = [{"bind": "0.0.0.0:8443", "https": True}]

    save_json(UI_CONFIG_FILE, {
        "listeners": listeners, "timezone": timezone, "date_format": date_format,
        "relative_time": relative_time, "expand_adv": expand_adv,
        "vault_sort": vault_sort, "smtp_sort": smtp_sort, "smarthost_sort": smarthost_sort, "ui_loglevel": ui_loglevel
    })
    os.kill(os.getpid(), signal.SIGUSR1)
    return HTMLResponse("UI engine configuration altered successfully.")
