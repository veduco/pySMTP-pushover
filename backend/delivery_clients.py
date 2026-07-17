import base64
import logging
import ssl
import email.utils
from email.message import EmailMessage
from email import message_from_bytes, policy
from core.config import PUSHOVER_API_URL
import httpx
import aiosmtplib

async def send_pushover(payload, client: httpx.AsyncClient, state=None):
    success = False
    error_msg = None

    target_token = payload.get("token", "")
    target_user = payload.get("user", "")

    if state and hasattr(state, "vault"):
        app_vault = state.vault.get("app", {})
        user_vault = state.vault.get("user", {})

        # 1. Clear & Explicit Token Resolution
        if target_token in app_vault:
            # It's an alias name; resolve it dynamically to the live key
            target_token = app_vault[target_token]
        elif target_token:
            # It's a raw key from a hardcoded route rule or pre-resolved matrix state.
            # Leave it untouched!
            pass
        else:
            # It's completely blank; fall back to the global default parameters
            global_token = state.pushover.get("token", "")
            target_token = app_vault.get(global_token, global_token)

        # 2. Clear & Explicit User Key Resolution
        if target_user in user_vault:
            # It's an alias name; resolve it dynamically to the live key
            target_user = user_vault[target_user]
        elif target_user:
            # It's a raw key from a hardcoded route rule or pre-resolved matrix state.
            # Leave it untouched!
            pass
        else:
            # It's completely blank; fall back to the global default parameters
            global_user = state.pushover.get("user", "")
            target_user = user_vault.get(global_user, global_user)

    # Final Guard: Drop the message only if both the route and global fallbacks are completely empty
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
        if param in payload: api_payload[param] = str(payload[param])

    try:
        post_kwargs = {}
        if payload.get("attachment_base64"):
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

    alias = payload.get("smarthost_alias")
    sh_conf = state.smarthost.get("aliases", {}).get(alias)

    # Alias check with dynamic fallback to global configuration settings
    if not sh_conf:
        global_alias = state.smarthost.get("globals", {}).get("alias")
        if global_alias and global_alias in state.smarthost.get("aliases", {}):
            logging.info(f"Smarthost alias '{alias}' was removed between retries. Falling back to global default relay '{global_alias}'.")
            alias = global_alias
            sh_conf = state.smarthost["aliases"][alias]
        else:
            logging.warning(f"Smarthost alert {payload['id']} dropped: Assigned relay alias '{alias}' has been deleted and no valid global default relay is configured.")
            return False, "DROP_ALERT"

    try:
        if payload.get("force_plaintext") or payload.get("disable_attachments"):
            raw_bytes = base64.b64decode(payload["raw_eml_base64"])
            original_msg = message_from_bytes(raw_bytes, policy=policy.default)
            raw_plain = ""; raw_html = ""
            for part in original_msg.walk():
                if part.get_content_maintype() == 'multipart': continue
                if "attachment" in str(part.get("Content-Disposition", "")): continue
                ctype = part.get_content_type()
                if ctype == "text/plain":
                    raw_plain = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors='replace')
                elif ctype == "text/html":
                    raw_html = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors='replace')

            msg = EmailMessage()
            for key, val in original_msg.items():
                if key.lower() not in ['content-type', 'mime-version', 'content-transfer-encoding', 'content-disposition']:
                    msg[key] = val
            if 'MIME-Version' not in msg:
                msg['MIME-Version'] = '1.0'

            if not msg.get('Subject'): msg['Subject'] = payload.get("title", "No Subject")
            if not msg.get('From'): msg['From'] = payload.get("sender", "gateway@localhost")
            if not msg.get('To'): msg['To'] = ", ".join(payload.get("recipients", []))
            if not msg.get('Date'): msg['Date'] = email.utils.formatdate(localtime=False)
            if not msg.get('Message-ID'): msg['Message-ID'] = email.utils.make_msgid()

            if payload.get("force_plaintext"):
                msg.set_content(raw_plain or payload.get("message", ""), charset="utf-8")
            else:
                msg.set_content(raw_plain or payload.get("message", ""), charset="utf-8")
                if raw_html: msg.add_alternative(raw_html, subtype="html", charset="utf-8")

            if not payload.get("disable_attachments") and payload.get("attachment_base64"):
                img_bytes = base64.b64decode(payload["attachment_base64"])
                maintype, subtype = payload["attachment_type"].split('/', 1)
                msg.add_attachment(img_bytes, maintype=maintype, subtype=subtype, filename=payload["attachment_name"])
            final_send_bytes = bytes(msg)
        else:
            final_send_bytes = base64.b64decode(payload["raw_eml_base64"])

        host = sh_conf.get("hostname")
        port = int(sh_conf.get("port", 25))
        local_ehlo = sh_conf.get("advertised_hostname")
        if not local_ehlo: local_ehlo = state.smtp.get("hostname")
        if not local_ehlo: local_ehlo = "localhost"

        use_tls = False
        start_tls = False
        tls_context = None

        if sh_conf.get("starttls"):
            tls_context = ssl._create_unverified_context() if sh_conf.get("disable_tls_validation") else ssl.create_default_context()
            if port == 465:
                use_tls = True
            else:
                start_tls = True

        # Inject parameters directly into constructor to leverage aiosmtplib's native negotiation state machine
        smtp_client = aiosmtplib.SMTP(
            hostname=host,
            port=port,
            local_hostname=local_ehlo,
            use_tls=use_tls,
            start_tls=start_tls,
            tls_context=tls_context,
            timeout=15
        )

        # Single call manages socket binding, initial EHLO, TLS handshaking, and secondary EHLO safely
        await smtp_client.connect()

        if sh_conf.get("auth"):
            sh_pass = state.vault.get("smarthost", {}).get(alias, "")
            await smtp_client.login(sh_conf.get("username", ""), sh_pass)

        await smtp_client.sendmail(payload.get("sender"), payload.get("recipients"), final_send_bytes)
        await smtp_client.quit()

        logging.info(f"Successfully relayed email '{payload['title']}' via Smarthost '{alias}'.")
        success = True
    except Exception as e:
        error_msg = repr(e)

    return success, error_msg
