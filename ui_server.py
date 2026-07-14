#!/usr/bin/env python3
"""
FASH Stack UI for SMTP to Pushover Gateway

================================================================================
OS PACKAGE REQUIREMENTS
================================================================================
Debian 13 (Trixie):
    $ sudo apt-get update
    $ sudo apt-get install python3 python3-fastapi python3-uvicorn python3-jinja2 python3-multipart python3-cryptography

Alpine Linux:
    $ apk update
    $ apk add python3 py3-fastapi py3-uvicorn py3-jinja2 py3-multipart py3-cryptography
================================================================================
"""

import os
import json
import signal
import uuid
import ssl
import datetime
import threading
import time
import re
import logging
import hashlib
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
import uvicorn
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

# Define global logging before Uvicorn starts to prevent systemd from swallowing INFO blocks
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Dynamic Configuration Paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.environ.get("GATEWAY_CONFIG", os.path.join(SCRIPT_DIR, "config.json"))
UI_CONFIG_FILE = os.environ.get("UI_CONFIG", os.path.join(SCRIPT_DIR, "ui_config.json"))
VAULT_FILE = os.environ.get("VAULT_FILE", os.path.join(SCRIPT_DIR, "vault.json"))
VAULT_META_FILE = os.environ.get("VAULT_META_FILE", os.path.join(SCRIPT_DIR, "vault_meta.json"))
SMTP_PID_FILE = "/tmp/smtp_pushover.pid"

# Global threading events for perfect signal parity with smtp_pushover.py
ui_shutdown_event = threading.Event()
ui_reload_listeners_event = threading.Event()   # USR1 parities listener reloads
ui_reload_configs_event = threading.Event()     # USR2 parities configuration reloads

class EndpointFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Match both GET /healthcheck and HEAD /healthcheck by checking the URI path directly
        return "/healthcheck" not in record.getMessage()

logging.getLogger("uvicorn.access").addFilter(EndpointFilter())

def load_clean_json(filepath):
    if not os.path.exists(filepath): return {}
    try:
        with open(filepath, 'r') as f:
            content = f.read()
        content = re.sub(r'(^|\s)/\*.*?\*/', r'\1', content, flags=re.DOTALL)
        content = re.sub(r'(^|\s)(//|#).*', r'\1', content)
        return json.loads(content)
    except Exception:
        return {}

def save_json(filepath, data):
    with open(filepath, 'w') as f: json.dump(data, f, indent=2)

def load_vault_safe(filepath):
    v = load_clean_json(filepath)
    if "app" not in v and "user" not in v:
        return {"app": v, "user": {}, "smarthost": {}}
    return {"app": v.get("app", {}), "user": v.get("user", {}), "smarthost": v.get("smarthost", {})}

def init_vault():
    if not os.path.exists(VAULT_FILE): save_json(VAULT_FILE, {"app": {}, "user": {}, "smarthost": {}})
    if not os.path.exists(VAULT_META_FILE): save_json(VAULT_META_FILE, {"app": {}, "user": {}, "smarthost": {}})

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_vault()
    yield

app = FastAPI(lifespan=lifespan)

# Bind the template engine directly to the directory containing this python script
templates = Jinja2Templates(directory=SCRIPT_DIR)

def signal_smtp_app(restart_listeners=False):
    if not os.path.exists(SMTP_PID_FILE): return False
    with open(SMTP_PID_FILE, 'r') as f:
        pid = int(f.read().strip())
    try:
        os.kill(pid, signal.SIGUSR2)
        if restart_listeners:
            time.sleep(5.0)
            os.kill(pid, signal.SIGUSR1)
        return True
    except ProcessLookupError: return False

@app.api_route("/healthcheck", methods=["GET", "HEAD"])
async def healthcheck_endpoint(request: Request):
    return {"status": "healthy"}

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    config = load_clean_json(CONFIG_FILE)
    ui_config = load_clean_json(UI_CONFIG_FILE)
    vault_entries = load_vault_safe(VAULT_META_FILE)

    changed_config = False

    # 1. Automatic Schema Migrations
    if "routes" not in config:
        config["routes"] = {}
        reserved_keys = ["user", "token", "device", "sound", "url", "url_title", "tags", "priority", "ttl", "retry", "expire", "attachments", "force_plaintext", "disable_persistence"]
        po = config.get("pushover", {})
        to_del = []
        for k, v in po.items():
            if k not in reserved_keys and isinstance(v, dict):
                v["method"] = "pushover"
                config["routes"][k] = v
                to_del.append(k)
        for k in to_del: del po[k]
        changed_config = True

    if "disable_persistence" in config.get("pushover", {}):
        if "smtp" not in config: config["smtp"] = {}
        config["smtp"]["disable_persistence"] = config["pushover"]["disable_persistence"]
        del config["pushover"]["disable_persistence"]
        changed_config = True

    if "smarthost" not in config:
        config["smarthost"] = {"aliases": {}, "globals": {}}
        changed_config = True

    if "smtp" not in config: config["smtp"] = {}
    if "default_route" not in config["smtp"]:
        config["smtp"]["default_route"] = "pushover"
        changed_config = True

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

    smtp_block = config.get("smtp", {})
    smtp_meta = smtp_block.get("_smtp_meta", {})

    # Load and populate the external index.html file cleanly
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "config_json": json.dumps(config),
            "smtp_meta_json": json.dumps(smtp_meta),
            "vault_meta_json": json.dumps(vault_entries),
            "ui_port": ui_config.get("port", 8443),
            "ui_https": ui_config.get("https", True),
            "ui_expand_adv": ui_config.get("expand_adv", False),
            "ui_vault_sort": ui_config.get("vault_sort", "name_asc"),
            "ui_smtp_sort": ui_config.get("smtp_sort", "name_asc"),
            "ui_smarthost_sort": ui_config.get("smarthost_sort", "alias_asc"),
            "ui_tz": ui_config.get("timezone", "UTC"),
            "ui_fmt": ui_config.get("date_format", "YYYY-MM-DD HH:mm:ss"),
            "ui_relative": ui_config.get("relative_time", True),
            "ui_loglevel": ui_config.get("ui_loglevel", "INFO"),
            "ui_cert": ui_config.get("tls_cert", ""),
            "ui_key": ui_config.get("tls_key", "")
        }
    )

@app.post("/save/config")
async def save_config(config_json: str = Form(...), vault_json: str = Form(None)):
    try:
        parsed = json.loads(config_json)
        old_config = load_clean_json(CONFIG_FILE)
        auth_block = parsed.get("smtp", {}).get("auth", {})
        meta_block = parsed.get("_smtp_meta", {})
        for user, pwd in list(auth_block.items()):
            if str(pwd).startswith("RAW:"):
                plain = pwd[4:]
                auth_block[user] = hashlib.sha256(plain.encode('utf-8')).hexdigest()
                if user not in meta_block: meta_block[user] = int(time.time())
        parsed["smtp"]["_smtp_meta"] = meta_block
        if "_smtp_meta" in parsed: del parsed["_smtp_meta"]
        save_json(CONFIG_FILE, parsed)

        # If the frontend bundled the vault payload, process and save the passwords securely
        if vault_json:
            vault_parsed = json.loads(vault_json)
            vault_data = load_vault_safe(VAULT_FILE)
            new_data = {"app": {}, "user": {}, "smarthost": {}}
            new_meta = {"app": {}, "user": {}, "smarthost": {}}

            for vtype in ["app", "user"]:
                for item in vault_parsed.get(vtype, []):
                    name = item["name"]; tok = item["token"]; epoch = item["epoch"]
                    if tok == "__RETAIN__": new_data[vtype][name] = vault_data[vtype].get(name, "")
                    else: new_data[vtype][name] = tok
                    new_meta[vtype][name] = epoch

            for alias, tok in vault_parsed.get("smarthost", {}).items():
                if tok == "__RETAIN__": new_data["smarthost"][alias] = vault_data.get("smarthost", {}).get(alias, "")
                else: new_data["smarthost"][alias] = tok
                new_meta["smarthost"][alias] = int(time.time())

            save_json(VAULT_FILE, new_data)
            save_json(VAULT_META_FILE, new_meta)

        old_smtp = old_config.get("smtp", {})
        new_smtp = parsed.get("smtp", {})
        if "_smtp_meta" in old_smtp: del old_smtp["_smtp_meta"]
        if "_smtp_meta" in new_smtp: del new_smtp["_smtp_meta"]
        needs_restart = (old_smtp != new_smtp)
        signal_smtp_app(restart_listeners=needs_restart)
        return HTMLResponse("Configuration successfully synchronized with the gateway daemon.")
    except Exception as e: return HTMLResponse(f"Error compiling config structure: {e}")

@app.post("/save/vault_state")
async def save_vault_state(vault_json: str = Form(...)):
    try:
        parsed = json.loads(vault_json)
        vault_data = load_vault_safe(VAULT_FILE)
        new_data = {"app": {}, "user": {}, "smarthost": {}}
        new_meta = {"app": {}, "user": {}, "smarthost": {}}

        for vtype in ["app", "user"]:
            for item in parsed.get(vtype, []):
                name = item["name"]; tok = item["token"]; epoch = item["epoch"]
                if tok == "__RETAIN__": new_data[vtype][name] = vault_data[vtype].get(name, "")
                else: new_data[vtype][name] = tok
                new_meta[vtype][name] = epoch

        # Handle the new dictionary-based Smarthost vault structure payload
        for alias, tok in parsed.get("smarthost", {}).items():
            if tok == "__RETAIN__": new_data["smarthost"][alias] = vault_data.get("smarthost", {}).get(alias, "")
            else: new_data["smarthost"][alias] = tok
            new_meta["smarthost"][alias] = int(time.time()) # Keep timestamp fresh on save

        save_json(VAULT_FILE, new_data)
        save_json(VAULT_META_FILE, new_meta)
        signal_smtp_app(restart_listeners=False)
        return HTMLResponse("Token Vault safely synchronized with the gateway daemon.")
    except Exception as e: return HTMLResponse(f"Error parsing Vault Array: {e}")

@app.post("/save/ui")
async def save_ui(
    port: int = Form(...), timezone: str = Form(...), date_format: str = Form(...),
    relative_time: bool = Form(False), expand_adv: bool = Form(False), https: bool = Form(False), tls_cert: str = Form(""), tls_key: str = Form(""),
    vault_sort: str = Form("name_asc"), smtp_sort: str = Form("name_asc"), smarthost_sort: str = Form("alias_asc"), ui_loglevel: str = Form("INFO")
):
    ui_config = {
        "port": port, "timezone": timezone, "date_format": date_format,
        "relative_time": relative_time, "expand_adv": expand_adv, "https": https, "tls_cert": tls_cert, "tls_key": tls_key,
        "vault_sort": vault_sort, "smtp_sort": smtp_sort, "smarthost_sort": smarthost_sort, "ui_loglevel": ui_loglevel
    }
    save_json(UI_CONFIG_FILE, ui_config)
    # Native signal handler notification triggers loop rotation
    os.kill(os.getpid(), signal.SIGUSR1)
    return HTMLResponse("UI engine configuration altered successfully.")

def generate_ui_cert():
    cert_path, key_path = "/tmp/ui_cert.pem", "/tmp/ui_key.pem"
    if os.path.exists(cert_path): return cert_path, key_path
    private_key = ec.generate_private_key(ec.SECP384R1())
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, str(uuid.uuid4()))])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = x509.CertificateBuilder().subject_name(subject).issuer_name(issuer).public_key(
        private_key.public_key()
    ).serial_number(x509.random_serial_number()).not_valid_before(now).not_valid_after(
        now + datetime.timedelta(days=365)
    ).sign(private_key, hashes.SHA256())
    with open(key_path, "wb") as f: f.write(private_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
    with open(cert_path, "wb") as f: f.write(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path

if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda s, f: ui_shutdown_event.set())
    signal.signal(signal.SIGTERM, lambda s, f: ui_shutdown_event.set())
    if hasattr(signal, 'SIGUSR1'): signal.signal(signal.SIGUSR1, lambda s, f: ui_reload_listeners_event.set())
    if hasattr(signal, 'SIGUSR2'): signal.signal(signal.SIGUSR2, lambda s, f: ui_reload_configs_event.set())

    while not ui_shutdown_event.is_set():
        if ui_reload_configs_event.is_set():
            ui_reload_configs_event.clear()
            # Re-read configurations seamlessly from disk context. FastAPI intercepts state on pull.
            logging.info("Caught SIGUSR2 inside UI process space. Configuration cache cleared.")

        ui_config = load_clean_json(UI_CONFIG_FILE)
        port = ui_config.get("port", 8443)
        use_https = ui_config.get("https", True)

        # Implement Dynamic Logging Levels for the UI Thread and Uvicorn
        ui_loglevel_str = ui_config.get("ui_loglevel", "INFO")
        log_level = getattr(logging, ui_loglevel_str.upper(), logging.INFO)
        logging.getLogger().setLevel(log_level)
        for handler in logging.getLogger().handlers:
            handler.setLevel(log_level)

        if use_https:
            cert_file, key_file = ui_config.get("tls_cert"), ui_config.get("tls_key")
            if not cert_file or not os.path.exists(cert_file): cert_file, key_file = generate_ui_cert()
            server_config = uvicorn.Config(app, host="0.0.0.0", port=port, ssl_keyfile=key_file, ssl_certfile=cert_file, log_level=ui_loglevel_str.lower())
        else:
            server_config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level=ui_loglevel_str.lower())

        server = uvicorn.Server(server_config)
        t = threading.Thread(target=server.run)
        t.start()

        while t.is_alive():
            if ui_reload_configs_event.is_set():
                ui_reload_configs_event.clear()
                logging.info("Caught SIGUSR2 inside UI process space. Configuration cache cleared.")

            if ui_reload_listeners_event.is_set() or ui_shutdown_event.is_set():
                server.should_exit = True
                if ui_reload_listeners_event.is_set():
                    ui_reload_listeners_event.clear()
                    logging.info("Caught SIGUSR1 inside UI process space. Hot-reloading network port binders...")
                break
            time.sleep(1)
        t.join()
