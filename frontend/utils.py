import os
import uuid
import signal
import logging
from core.config import SCRIPT_DIR, SMTP_PID_FILE, get_cached_ui_config
from core.json_store import generate_self_signed_certificate

def get_active_config_path():
    ui_cfg = get_cached_ui_config()
    return ui_cfg.get("local_config_path", os.path.join(SCRIPT_DIR, "config.json"))

def generate_ui_cert():
    # Standardized warning matched cleanly with the backend engine signature
    logging.warning("No valid TLS certificate found for Web UI. Generating a random memory-bound certificate.")
    return generate_self_signed_certificate(str(uuid.uuid4()), "ui")

def trigger_local_backend_reload(listeners_only=False):
    if not os.path.exists(SMTP_PID_FILE):
        return
    with open(SMTP_PID_FILE, 'r') as f:
        pid = int(f.read().strip())
    try:
        os.kill(pid, signal.SIGUSR2)
    except ProcessLookupError:
        pass
