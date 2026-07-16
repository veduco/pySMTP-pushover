import base64
import logging
import ssl
import email.utils
from email.message import EmailMessage
from email import message_from_bytes, policy
from core.config import PUSHOVER_API_URL
import httpx
import aiosmtplib

async def send_pushover(payload, client: httpx.AsyncClient):
    success = False
    error_msg = None

    # HTTPX explicitly requires string mappings when initiating multipart/form-data POSTs
    api_payload = {
        "token": str(payload["token"]), "user": str(payload["user"]), "message": str(payload["message"]),
        "title": str(payload["title"]), "timestamp": str(payload["timestamp"]), "html": "1" if payload.get("is_html") else "0"
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

        # Pipelined through the shared globally-locked connection pool
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

    if not sh_conf:
        error_msg = f"Alias '{alias}' is not defined in the configuration."
        logging.error(f"Smarthost relay failed. {error_msg}")
        return success, error_msg

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

        smtp_client = aiosmtplib.SMTP(hostname=host, port=port, timeout=15)
        await smtp_client.connect()
        await smtp_client.ehlo(local_ehlo)

        if sh_conf.get("starttls"):
            tls_context = ssl._create_unverified_context() if sh_conf.get("disable_tls_validation") else ssl.create_default_context()
            await smtp_client.starttls(server_hostname=host, tls_context=tls_context)
            await smtp_client.ehlo(local_ehlo)

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
