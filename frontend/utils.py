import os
import uuid
import datetime
import requests
import signal
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from core.config import SCRIPT_DIR, UI_CONFIG_FILE, SMTP_PID_FILE, load_clean_json

def get_active_config_path():
    ui_cfg = load_clean_json(UI_CONFIG_FILE)
    return ui_cfg.get("local_config_path", os.path.join(SCRIPT_DIR, "config.json"))

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

def trigger_backend_reload(ui_config, listeners_only=False):
    bmode = ui_config.get("backend_mode", "local")
    if bmode == "remote":
        url = ui_config.get("remote_url", "")
        sec = ui_config.get("remote_secret", "")
        verify_tls = ui_config.get("remote_verify_tls", False)
        ep = "/api/reload/listeners" if listeners_only else "/api/reload/config"
        try:
            requests.post(f"{url.rstrip('/')}{ep}", headers={"Authorization": f"Bearer {sec}"}, verify=verify_tls, timeout=5)
        except Exception: pass
    else:
        if not os.path.exists(SMTP_PID_FILE): return
        with open(SMTP_PID_FILE, 'r') as f: pid = int(f.read().strip())
        try:
            if listeners_only: os.kill(pid, signal.SIGUSR1)
            else: os.kill(pid, signal.SIGUSR2)
        except ProcessLookupError: pass

def resolve_vault_path(config_data=None):
    active_path = get_active_config_path()
    if config_data is None:
        config_data = load_clean_json(active_path)

    conf_dir = os.path.dirname(active_path) or "."
    v_path = config_data.get("smtp", {}).get("vault_file")

    if not v_path: return os.path.join(conf_dir, "vault.json")
    return os.path.normpath(os.path.join(conf_dir, v_path))
