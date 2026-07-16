import os
import uuid
import ssl
import hashlib
from core.json_store import generate_self_signed_certificate

def file_contains_private_key(filepath):
    try:
        with open(filepath, 'r') as f:
            return "PRIVATE KEY-----" in f.read()
    except Exception:
        return False

def get_tls_context(listener_conf, fallback_hostname):
    if not listener_conf.get("starttls"):
        return None
    cert_file = listener_conf.get("tls_cert_file")
    key_file = listener_conf.get("tls_key_file")
    cert_has_key = False

    if cert_file and os.path.isfile(cert_file) and os.access(cert_file, os.R_OK):
        cert_has_key = file_contains_private_key(cert_file)
    if cert_has_key and key_file:
        key_file = None

    files_ok = False
    if cert_file and os.path.isfile(cert_file) and os.access(cert_file, os.R_OK):
        if cert_has_key or (key_file and os.path.isfile(key_file) and os.access(key_file, os.R_OK)):
            files_ok = True

    if not files_ok:
        hostname = fallback_hostname or str(uuid.uuid4())
        bind_address = listener_conf.get("bind", "0.0.0.0:25")
        safe_bind = bind_address.replace(":", "_")
        cert_file, key_file = generate_self_signed_certificate(hostname, f"smtp_pushover_{safe_bind}")

    tls_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    tls_context.load_cert_chain(certfile=cert_file, keyfile=key_file)
    return tls_context

def get_listen_params(listen_str):
    if ":" in listen_str:
        address, port = listen_str.rsplit(":", 1)
        return address, int(port)
    return listen_str, 25

def get_file_hash(filepath):
    if not filepath or not os.path.exists(filepath):
        return ""
    try:
        with open(filepath, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()
    except Exception:
        return ""
