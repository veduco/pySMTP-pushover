import asyncio
import logging
import httpx
import json
import hashlib
from contextlib import asynccontextmanager

def get_deterministic_hash(data: dict) -> str:
    """Produces a consistent SHA-256 hash of a dictionary by sorting keys and stripping whitespace."""
    if not data:
        return ""
    # Strip transient metadata before hashing
    safe_data = {k: v for k, v in data.items() if k not in ("_smtp_meta",)}
    serialized = json.dumps(safe_data, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(serialized.encode('utf-8')).hexdigest()

@asynccontextmanager
async def safe_async_lifecycle(context_name: str = "Stream"):
    """Globally centralizes ASGI cancellation and exception trapping to prevent memory leaks."""
    try:
        yield
    except asyncio.CancelledError:
        # Standard client disconnection; safely drop context without logging tracebacks.
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
