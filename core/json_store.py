import json
import os
import uuid
import datetime
import ipaddress
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

def parse_bind_string(bind_str: str, default_port: int = 25):
    """Unified helper to safely separate bind interfaces from port numbers."""
    if not bind_str:
        return "0.0.0.0", default_port
    if ":" in bind_str:
        address, port = bind_str.rsplit(":", 1)
        return address, int(port)
    return bind_str, default_port

def is_valid_network_target(target: str, allow_cidr: bool = True) -> bool:
    """
    Validates if a target string is a valid IPv4/IPv6 address or CIDR block.
    Centralizes validation logic between frontend UI form bindings and backend access definitions.
    """
    if not target:
        return False

    target = target.strip()
    if target.lower() in ("localhost", "127.0.0.1", "::1"):
        return True

    try:
        if allow_cidr and '/' in target:
            ipaddress.ip_network(target, strict=False)
        else:
            ipaddress.ip_address(target)
        return True
    except ValueError:
        return False

def is_ip_allowed(client_ip: str, allowed_cidrs: list) -> bool:
    """
    Evaluates raw strings or subnet masks (e.g., '192.168.1.5', '10.0.0.0/24', 'localhost').
    Returns True if allowed_cidrs is empty/none (permissive mode definition).
    """
    if not allowed_cidrs:
        return True

    # Normalize string-bound loopback declarations
    if client_ip in ("localhost", "127.0.0.1", "::1"):
        normalized_ip = ipaddress.ip_address("127.0.0.1")
    else:
        try:
            normalized_ip = ipaddress.ip_address(client_ip)
        except ValueError:
            return False

    for cidr in allowed_cidrs:
        if not cidr:
            continue
        # Convert explicit address configurations into a standard rule definition
        if cidr in ("localhost", "127.0.0.1", "::1"):
            cidr = "127.0.0.1/32"
        elif "/" not in cidr:
            cidr = f"{cidr}/32"

        try:
            if normalized_ip in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue

    return False
