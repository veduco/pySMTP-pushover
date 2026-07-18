import asyncio
import logging
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
