import os
import hashlib
from core.security import TLSManager

def get_tls_context(listener_conf, fallback_hostname):
    """Retrieves the unified SSL context mapped to the specific listener constraints."""
    if not listener_conf.get("starttls"):
        return None

    # Delegate full resolution, SAN mapping, and context generation to the centralized wrapper
    ctx, _, _ = TLSManager.get_unified_context(
        cert_file=listener_conf.get("tls_cert_file"),
        key_file=listener_conf.get("tls_key_file"),
        bind_address=listener_conf.get("bind", "0.0.0.0:25"),
        listener_hostname=listener_conf.get("hostname", ""),
        global_hostname=fallback_hostname
    )

    return ctx

def get_file_hash(filepath):
    if not filepath or not os.path.exists(filepath):
        return ""
    try:
        with open(filepath, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()
    except Exception:
        return ""
