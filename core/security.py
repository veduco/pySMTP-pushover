import logging
import os
import ssl
import uuid
import tempfile
import ipaddress
from datetime import datetime, timedelta
from typing import Callable, List, Tuple
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

from core.utils import is_ip_allowed, parse_bind_string

class TLSManager:
    """Centralized Cryptographic Asset Assurance Wrapper."""

    _ephemeral_files = []

    @staticmethod
    def _file_contains_private_key(filepath: str) -> bool:
        try:
            with open(filepath, 'r') as f:
                return "PRIVATE KEY-----" in f.read()
        except Exception:
            return False

    @classmethod
    def get_unified_context(
        cls,
        cert_file: str = None,
        key_file: str = None,
        bind_address: str = "0.0.0.0:25",
        listener_hostname: str = "",
        global_hostname: str = ""
    ) -> Tuple[ssl.SSLContext, str, str]:
        """
        Validates existing TLS assets. If invalid, generates an ephemeral, memory-bound
        certificate matching the specified SAN fallback rules, returning a unified SSLContext.
        """
        host, _ = parse_bind_string(bind_address, 25)

        cert_valid = cert_file and os.path.isfile(cert_file) and os.access(cert_file, os.R_OK)
        key_valid = key_file and os.path.isfile(key_file) and os.access(key_file, os.R_OK)

        if cert_valid:
            if cls._file_contains_private_key(cert_file):
                key_file = None
                key_valid = True

        if cert_valid and key_valid:
            ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            ctx.load_cert_chain(certfile=cert_file, keyfile=key_file)
            return ctx, cert_file, key_file

        # Fallback Hierarchy: Specific Listener -> Global Route -> Random UUID
        target_hostname = listener_hostname or global_hostname or str(uuid.uuid4())
        logging.warning(f"Valid TLS assets missing for {bind_address}. Generating ephemeral in-memory certificate for '{target_hostname}'.")

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, target_hostname),
        ])

        san_list = [x509.DNSName(target_hostname)]
        if host and host not in ("0.0.0.0", "", "::"):
            try:
                ip = ipaddress.ip_address(host)
                san_list.append(x509.IPAddress(ip))
            except ValueError:
                if host != target_hostname:
                    san_list.append(x509.DNSName(host))

        cert = x509.CertificateBuilder().subject_name(
            subject
        ).issuer_name(
            issuer
        ).public_key(
            key.public_key()
        ).serial_number(
            x509.random_serial_number()
        ).not_valid_before(
            datetime.utcnow()
        ).not_valid_after(
            datetime.utcnow() + timedelta(days=365)
        ).add_extension(
            x509.SubjectAlternativeName(san_list),
            critical=False,
        ).sign(key, hashes.SHA256())

        cert_pem = cert.public_bytes(serialization.Encoding.PEM)
        key_pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        )

        # Utilize tmpfs directly to avoid disk persistence while satisfying Python's ssl file requirements
        cert_temp = tempfile.NamedTemporaryFile(delete=False, suffix=".crt")
        cert_temp.write(cert_pem)
        cert_temp.close()

        key_temp = tempfile.NamedTemporaryFile(delete=False, suffix=".key")
        key_temp.write(key_pem)
        key_temp.close()

        cls._ephemeral_files.extend([cert_temp.name, key_temp.name])

        ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ctx.load_cert_chain(certfile=cert_temp.name, keyfile=key_temp.name)

        return ctx, cert_temp.name, key_temp.name

    @classmethod
    def cleanup(cls):
        """Releases and unlinks all ephemeral tmpfs cryptographic assets from memory."""
        for f in cls._ephemeral_files:
            try:
                os.remove(f)
            except OSError:
                pass
        cls._ephemeral_files.clear()

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

def create_secure_app(
    app_type: str,
    config_resolver: Callable[[Request], dict],
    lifespan_handler=None,
    pre_hook: Callable[[Request], None] = None,
    excluded_paths: List[str] = None
) -> FastAPI:
    """
    Centralized monolithic application factory generating identical ASGI framework
    configurations and unified middleware boundaries.
    """
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan_handler)

    if excluded_paths is None:
        excluded_paths = ["/healthcheck"] if app_type == "frontend" else []

    if app_type == "frontend":
        excluded_paths.extend(["/api/queue", "/api/queue/stream", "/api/validate/network"])

    app.middleware("http")(build_access_middleware(
        app_type=app_type,
        config_resolver=config_resolver,
        excluded_paths=excluded_paths,
        pre_hook=pre_hook
    ))

    # Explicit Frontend-Only Endpoint Isolation Pass
    if app_type == "frontend":
        @app.api_route("/healthcheck", methods=["GET", "HEAD"])
        async def healthcheck_endpoint(request: Request):
            return JSONResponse({"status": "healthy"})

    return app
