import os
import uuid
import logging
import ssl
import datetime
import hashlib
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

def file_contains_private_key(filepath):
    try:
        with open(filepath, 'r') as f: return "PRIVATE KEY-----" in f.read()
    except Exception: return False

def get_tls_context(listener_conf, fallback_hostname):
    if not listener_conf.get("starttls"): return None
    cert_file = listener_conf.get("tls_cert_file")
    key_file = listener_conf.get("tls_key_file")
    cert_has_key = False
    if cert_file and os.path.isfile(cert_file) and os.access(cert_file, os.R_OK):
        cert_has_key = file_contains_private_key(cert_file)
    if cert_has_key and key_file: key_file = None
    files_ok = False
    if cert_file and os.path.isfile(cert_file) and os.access(cert_file, os.R_OK):
        if cert_has_key or (key_file and os.path.isfile(key_file) and os.access(key_file, os.R_OK)): files_ok = True
    if not files_ok:
        hostname = fallback_hostname or str(uuid.uuid4())
        bind_address = listener_conf.get("bind", "0.0.0.0:25")
        cert_file, key_file = generate_secp384r1_cert(hostname, bind_address)
    tls_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    tls_context.load_cert_chain(certfile=cert_file, keyfile=key_file)
    return tls_context

def generate_secp384r1_cert(hostname, bind_address):
    safe_bind = bind_address.replace(":", "_")
    cert_path = f"/tmp/smtp_pushover_cert_{safe_bind}.pem"
    key_path = f"/tmp/smtp_pushover_key_{safe_bind}.pem"
    if os.path.exists(cert_path) and os.path.exists(key_path): return cert_path, key_path

    logging.warning(f"Generating self-signed secp384r1 fallback cert for {hostname} on {bind_address}...")
    private_key = ec.generate_private_key(ec.SECP384R1())
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = x509.CertificateBuilder().subject_name(subject).issuer_name(issuer).public_key(private_key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now).not_valid_after(now + datetime.timedelta(days=365)).add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False).sign(private_key, hashes.SHA256())
    with open(key_path, "wb") as f: f.write(private_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
    with open(cert_path, "wb") as f: f.write(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path

def get_listen_params(listen_str):
    if ":" in listen_str:
        address, port = listen_str.rsplit(":", 1)
        return address, int(port)
    return listen_str, 25

def get_file_hash(filepath):
    if not filepath or not os.path.exists(filepath): return ""
    try:
        with open(filepath, 'rb') as f: return hashlib.sha256(f.read()).hexdigest()
    except Exception: return ""
