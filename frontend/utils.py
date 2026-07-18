import os
import signal
import logging
from core.config import SCRIPT_DIR, SMTP_PID_FILE, get_cached_ui_config
from core.security import TLSManager

def get_active_config_path():
    ui_cfg = get_cached_ui_config()
    return ui_cfg.get("local_config_path", os.path.join(SCRIPT_DIR, "config.json"))

def generate_ui_cert():
    """Delegates frontend certificate generation to the centralized memory-bound TLS wrapper."""
    _, cert_path, key_path = TLSManager.get_unified_context(
        cert_file=None,
        key_file=None,
        bind_address="Web UI Front-End",
        listener_hostname="ui"
    )
    return cert_path, key_path

def trigger_local_backend_reload(listeners_only=False):
    if not os.path.exists(SMTP_PID_FILE):
        return
    with open(SMTP_PID_FILE, 'r') as f:
        pid = int(f.read().strip())
    try:
        os.kill(pid, signal.SIGUSR2)
    except ProcessLookupError:
        pass
