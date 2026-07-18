import asyncio
import logging
import httpx
from contextlib import asynccontextmanager

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
        key = (loop, pool_type)

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
