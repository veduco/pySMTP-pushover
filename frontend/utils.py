import os
import signal
import logging
import asyncio
from core.config import SCRIPT_DIR, SMTP_PID_FILE, get_cached_ui_config, ConfigOrchestrator
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

async def background_sync_worker():
    """Background task evaluating pending host synchronization states."""
    ui_cfg = get_cached_ui_config()
    if ui_cfg.get("backend_mode", "local") != "remote":
        return

    # Initialize Orchestrator to hold the mutable host references
    orch = ConfigOrchestrator(ui_cfg, http_client=None)

    # Filter the instances directly from the orchestrator so status updates map correctly
    needs_sync = [h for h in orch.remote_hosts if h.get("sync_status") in ("failed", "pending")]
    if not needs_sync:
        return

    logging.info(f"Background Sync Worker: Attempting to resolve {len(needs_sync)} out-of-sync nodes.")

    # 1. Fetch source of truth from primary
    config, vault, _, ok, primary_hash = await orch.get_config()
    if not ok:
        logging.warning("Background Sync Worker: Failed to retrieve baseline configuration from primary node. Aborting cycle.")
        return

    # 2. Push directly using the fan-out mechanism natively to the filtered subset
    await orch.fan_out_config(config, vault, primary_hash, specific_hosts=needs_sync)
