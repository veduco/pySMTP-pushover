import asyncio
import logging
import httpx
import json
import hashlib
import copy
import ipaddress
from contextlib import asynccontextmanager

def get_deterministic_hash(data: dict) -> str:
    """Produces a consistent SHA-256 hash of a dictionary by sorting keys and stripping whitespace."""
    if not data:
        return ""

    safe_data = copy.deepcopy(data)

    # Deep strip transient tracking blocks to prevent false diff flags from timestamps
    if "config" in safe_data and isinstance(safe_data["config"], dict):
        if "smtp" in safe_data["config"] and "_smtp_meta" in safe_data["config"]["smtp"]:
            del safe_data["config"]["smtp"]["_smtp_meta"]

    serialized = json.dumps(safe_data, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(serialized.encode('utf-8')).hexdigest()

@asynccontextmanager
async def safe_async_lifecycle(context_name: str = "Stream"):
    """Globally centralizes ASGI cancellation and exception trapping to prevent memory leaks."""
    try:
        yield
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logging.error(f"[{context_name}] Lifecycle interrupted: {e}")

class HttpClientPool:
    """Centralized HTTP connection pooling factory for normalized client execution."""
    _clients = {}

    @classmethod
    def get_client(cls, pool_type: str = "default", verify_tls: bool = True, timeout: float = 15.0) -> httpx.AsyncClient:
        loop = asyncio.get_running_loop()
        key = (loop, pool_type, verify_tls)

        if key not in cls._clients:
            if pool_type == "pushover":
                limits = httpx.Limits(max_connections=1, max_keepalive_connections=1)
            elif pool_type == "frontend":
                limits = httpx.Limits(max_connections=100, max_keepalive_connections=20)
            else:
                limits = httpx.Limits(max_connections=10, max_keepalive_connections=5)

            cls._clients[key] = httpx.AsyncClient(verify=verify_tls, limits=limits, timeout=timeout)

        return cls._clients[key]

    @classmethod
    async def close_all(cls):
        for key, client in list(cls._clients.items()):
            try:
                await client.aclose()
            except Exception:
                pass
        cls._clients.clear()

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
