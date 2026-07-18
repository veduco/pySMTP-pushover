import logging
from typing import Callable, List
from fastapi import Request
from fastapi.responses import JSONResponse, HTMLResponse
from core.json_store import is_ip_allowed

def get_real_ip(request: Request, trust_proxy: bool, trust_proxy_cidrs: list) -> str:
    """Safely extracts the origin client IP, validating against proxy trust rules."""
    client_ip = request.client.host if request.client else "127.0.0.1"

    if not trust_proxy:
        return client_ip

    # If the user defined a whitelist, but the connection originates from an untrusted node, immediately drop back to the raw client IP
    if trust_proxy_cidrs and not is_ip_allowed(client_ip, trust_proxy_cidrs):
        return client_ip

    forwarded = request.headers.get("Forwarded")
    if forwarded:
        for part in forwarded.split(',')[0].split(';'):
            if part.strip().lower().startswith("for="):
                val = part.strip()[4:].strip('"\'')
                if val.startswith('['): return val.split(']')[0][1:]
                if val.count(':') == 1: return val.split(':')[0]
                return val

    xff = request.headers.get("X-Forwarded-For")
    if xff:
        val = xff.split(',')[0].strip()
        if val.startswith('['): return val.split(']')[0][1:]
        if val.count(':') == 1: return val.split(':')[0]
        return val

    return client_ip

def build_access_middleware(
    app_type: str,
    config_resolver: Callable[[Request], dict],
    excluded_paths: List[str] = None,
    pre_hook: Callable[[Request], None] = None
):
    """
    Polymorphic middleware factory that unifies ACL blocking, proxy resolution,
    and HTTP access logging across both gateway microservices.
    """
    if excluded_paths is None:
        excluded_paths = ["/healthcheck"]

    async def access_log_middleware(request: Request, call_next):
        # Execute transient injections before processing (e.g. threading http clients into state)
        if pre_hook:
            pre_hook(request)

        # Resolve context-specific firewall configurations
        config = config_resolver(request)
        trust_proxy = config.get("trust_proxy", False)
        trust_proxy_cidrs = config.get("trust_proxy_cidrs", [])
        allowed_cidrs = config.get("allowed_cidrs", [])

        real_ip = get_real_ip(request, trust_proxy, trust_proxy_cidrs)

        # Unified ACL Enforcement Boundary
        if allowed_cidrs and not is_ip_allowed(real_ip, allowed_cidrs):
            if app_type == "frontend":
                logging.warning(f"Web UI access connection rejected: Client IP {real_ip} is not whitelisted.")
                return HTMLResponse("<h1>403 Forbidden</h1><p>Access denied by CIDR policy configuration rules.</p>", status_code=403)
            else:
                logging.warning(f"Control API endpoint connection dropped: Client IP {real_ip} is unauthorized.")
                return JSONResponse({"error": "Forbidden: Access denied by network policy rules."}, status_code=403)

        response = await call_next(request)

        path = request.url.path
        if path not in excluded_paths:
            http_version = request.scope.get("http_version", "1.1")
            query = f"?{request.url.query}" if request.url.query else ""
            logging.info(f'{real_ip} - "{request.method} {path}{query} HTTP/{http_version}" {response.status_code}')

        return response

    return access_log_middleware
