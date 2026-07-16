import json
import os
import uuid
import datetime
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

def load_clean_json(filepath):
    if not os.path.exists(filepath):
        return {}
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except Exception:
        return {}

def save_json(filepath, data):
    try:
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

def load_vault_safe(vault_path):
    v = load_clean_json(vault_path)
    for vtype in ["app", "user", "smarthost"]:
        if vtype not in v or not isinstance(v[vtype], dict):
            v[vtype] = {}
    return v

def generate_self_signed_certificate(hostname: str, prefix_name: str):
    """
    Unified cryptographic utility to generate secure SECP384R1 certificates
    for SMTP listeners or Web UI endpoints when dedicated certs are missing.
    """
    cert_path = f"/tmp/{prefix_name}_cert.pem"
    key_path = f"/tmp/{prefix_name}_key.pem"
    if os.path.exists(cert_path) and os.path.exists(key_path):
        return cert_path, key_path

    private_key = ec.generate_private_key(ec.SECP384R1())
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
    now = datetime.datetime.now(datetime.timezone.utc)

    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        private_key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        now
    ).not_valid_after(
        now + datetime.timedelta(days=365)
    ).add_extension(
        x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False
    ).sign(private_key, hashes.SHA256())

    with open(key_path, "wb") as f:
        f.write(private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption()
        ))
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    return cert_path, key_path
