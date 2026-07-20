import base64
import logging
import ssl
import httpx
import aiosmtplib
from core.config import PUSHOVER_API_URL
from backend.mail_parser import MIMEBuilder

async def send_pushover(payload, client: httpx.AsyncClient, state=None):
    success = False
    error_msg = None

    if not state:
        return False, "Application state context missing."

    ctx = state.resolve_delivery_context("pushover", payload)

    target_token = ctx.get("token")
    target_user = ctx.get("user")

    if not target_token or not target_user:
        logging.warning(f"Pushover alert {payload['id']} dropped: Assigned alias or global fallback parameters are completely missing.")
        return False, "DROP_ALERT"

    api_payload = {
        "token": str(target_token),
        "user": str(target_user),
        "message": str(payload["message"]),
        "title": str(payload["title"]),
        "timestamp": str(payload["timestamp"]),
        "html": "1" if payload.get("is_html") else "0"
    }

    for param in ["device", "sound", "url", "url_title", "priority", "ttl", "tags", "retry", "expire"]:
        if param in ctx:
            api_payload[param] = str(ctx[param])

    try:
        post_kwargs = {}
        if payload.get("attachment_base64") and ctx.get("attachments"):
            img_bytes = base64.b64decode(payload["attachment_base64"])
            files = {"attachment": (payload.get("attachment_name", "image.jpg"), img_bytes, payload.get("attachment_type", "image/jpeg"))}
            post_kwargs = {"data": api_payload, "files": files}
        else:
            post_kwargs = {"json": api_payload}

        response = await client.post(PUSHOVER_API_URL, **post_kwargs)
        if response.status_code == 200:
            logging.info(f"Successfully sent Pushover notification: '{payload['title']}'")
            success = True
        else:
            error_msg = f"HTTP {response.status_code}: {response.text}"
            logging.error(f"Pushover API returned {error_msg}")
    except Exception as e:
        error_msg = repr(e)
        logging.error(f"Failed to communicate with Pushover API: {error_msg}")

    return success, error_msg


async def send_smarthost(payload, state):
    success = False
    error_msg = None

    ctx = state.resolve_delivery_context("smarthost", payload)
    alias = ctx.get("_resolved_alias")

    if not ctx.get("is_valid"):
        logging.warning(f"Smarthost alert {payload['id']} dropped: Assigned relay alias '{payload.get('smarthost_alias')}' has been deleted and no valid global default relay is configured.")
        return False, "DROP_ALERT"

    if alias != payload.get("smarthost_alias"):
        logging.info(f"Smarthost alias '{payload.get('smarthost_alias')}' was removed. Falling back to global default relay '{alias}'.")

    try:
        # Delegate complex MIME payload reconstruction to the dedicated builder class
        force_pt = ctx.get("force_plaintext", False)
        incl_att = ctx.get("attachments", True)

        final_send_bytes = MIMEBuilder.rebuild_payload_bytes(payload, force_plaintext=force_pt, include_attachments=incl_att)

        host = ctx.get("hostname")
        port = int(ctx.get("port", 25))
        local_ehlo = ctx.get("advertised_hostname")
        if not local_ehlo: local_ehlo = state.smtp.get("hostname")
        if not local_ehlo: local_ehlo = "localhost"

        use_tls = False
        start_tls = False
        tls_context = None

        if ctx.get("starttls"):
            tls_context = ssl._create_unverified_context() if ctx.get("disable_tls_validation") else ssl.create_default_context()
            if port == 465:
                use_tls = True
            else:
                start_tls = True

        smtp_client = aiosmtplib.SMTP(
            hostname=host,
            port=port,
            local_hostname=local_ehlo,
            use_tls=use_tls,
            start_tls=start_tls,
            tls_context=tls_context,
            timeout=15
        )

        await smtp_client.connect()

        if ctx.get("auth"):
            await smtp_client.login(ctx.get("username", ""), ctx.get("password", ""))

        await smtp_client.sendmail(payload.get("sender"), payload.get("recipients"), final_send_bytes)
        await smtp_client.quit()

        logging.info(f"Successfully relayed email '{payload['title']}' via Smarthost '{alias}'.")
        success = True
    except Exception as e:
        error_msg = repr(e)

    return success, error_msg
