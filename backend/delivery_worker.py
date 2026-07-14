import os
import time
import json
import logging
import base64
import smtplib
import queue
import requests
import ssl
import email.utils
from email.message import EmailMessage
from email import message_from_bytes, policy
from core.config import PUSHOVER_API_URL

def delivery_worker(msg_queue, state, shutdown_event):
    logging.debug("Delivery worker thread started.")
    while not shutdown_event.is_set():
        try: payload = msg_queue.get(timeout=1.0)
        except queue.Empty: continue

        if payload is None:
            msg_queue.task_done()
            break

        now = int(time.time())
        next_retry = payload.get("next_retry", 0)

        if not payload.get("disable_persistence"):
            filepath = os.path.join(state.smtp["queue_dir"], f"{payload['id']}.json")
            if payload.get("retry_count", 0) > 0:
                if not os.path.exists(filepath):
                    msg_queue.task_done()
                    continue
                try:
                    file_mtime = os.path.getmtime(filepath)
                    if payload.get("_last_mtime", 0) < file_mtime:
                        payload["_last_mtime"] = file_mtime
                        with open(filepath, 'r') as f: disk_data = json.load(f)
                        payload["next_retry"] = disk_data.get("next_retry", next_retry)
                        payload["retry_count"] = disk_data.get("retry_count", payload.get("retry_count"))
                        next_retry = payload["next_retry"]
                except Exception: pass

        if now < next_retry:
            msg_queue.put(payload)
            msg_queue.task_done()
            shutdown_event.wait(1.0)
            continue

        method = payload.get("method", "pushover")
        success = False
        error_msg = None

        if method == "pushover":
            api_payload = {
                "token": payload["token"], "user": payload["user"], "message": payload["message"],
                "title": payload["title"], "timestamp": payload["timestamp"], "html": 1 if payload.get("is_html") else 0
            }
            for param in ["device", "sound", "url", "url_title", "priority", "ttl", "tags", "retry", "expire"]:
                if param in payload: api_payload[param] = payload[param]
            try:
                post_kwargs = {}
                if payload.get("attachment_base64"):
                    img_bytes = base64.b64decode(payload["attachment_base64"])
                    files = {"attachment": (payload.get("attachment_name", "image.jpg"), img_bytes, payload.get("attachment_type", "image/jpeg"))}
                    post_kwargs = {"data": api_payload, "files": files}
                else: post_kwargs = {"json": api_payload}
                response = requests.post(PUSHOVER_API_URL, timeout=10, **post_kwargs)
                if response.status_code == 200:
                    logging.info(f"Successfully sent Pushover notification: '{payload['title']}'")
                    success = True
                else:
                    error_msg = f"HTTP {response.status_code}: {response.text}"
                    logging.error(f"Pushover API returned {error_msg}")
            except Exception as e:
                error_msg = repr(e)
                logging.error(f"Failed to communicate with Pushover API: {error_msg}")

        elif method == "smarthost":
            alias = payload.get("smarthost_alias")
            sh_conf = state.smarthost.get("aliases", {}).get(alias)
            if not sh_conf:
                error_msg = f"Alias '{alias}' is not defined in the configuration."
                logging.error(f"Smarthost relay failed. {error_msg}")
            else:
                try:
                    if payload.get("force_plaintext") or payload.get("disable_attachments"):
                        raw_bytes = base64.b64decode(payload["raw_eml_base64"])
                        original_msg = message_from_bytes(raw_bytes, policy=policy.default)
                        raw_plain = ""; raw_html = ""
                        for part in original_msg.walk():
                            if part.get_content_maintype() == 'multipart': continue
                            if "attachment" in str(part.get("Content-Disposition", "")): continue
                            ctype = part.get_content_type()
                            if ctype == "text/plain": raw_plain = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors='replace')
                            elif ctype == "text/html": raw_html = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors='replace')

                        msg = EmailMessage()
                        for key, val in original_msg.items():
                            if key.lower() not in ['content-type', 'mime-version', 'content-transfer-encoding', 'content-disposition']: msg[key] = val
                        if 'MIME-Version' not in msg: msg['MIME-Version'] = '1.0'

                        if not msg.get('Subject'): msg['Subject'] = payload.get("title", "No Subject")
                        if not msg.get('From'): msg['From'] = payload.get("sender", "gateway@localhost")
                        if not msg.get('To'): msg['To'] = ", ".join(payload.get("recipients", []))
                        if not msg.get('Date'): msg['Date'] = email.utils.formatdate(localtime=False)
                        if not msg.get('Message-ID'): msg['Message-ID'] = email.utils.make_msgid()

                        if payload.get("force_plaintext"): msg.set_content(raw_plain or payload.get("message", ""), charset="utf-8")
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

                    with smtplib.SMTP(host, port, timeout=15) as server:
                        server.ehlo(local_ehlo)
                        if sh_conf.get("starttls"):
                            if sh_conf.get("disable_tls_validation"): server.starttls(context=ssl._create_unverified_context())
                            else: server.starttls()
                            server.ehlo(local_ehlo)
                        if sh_conf.get("auth"):
                            sh_pass = state.vault.get("smarthost", {}).get(alias, "")
                            server.login(sh_conf.get("username", ""), sh_pass)
                        server.sendmail(payload.get("sender"), payload.get("recipients"), final_send_bytes)
                    logging.info(f"Successfully relayed email '{payload['title']}' via Smarthost '{alias}'.")
                    success = True
                except Exception as e:
                    error_msg = repr(e)

        if success:
            if not payload.get("disable_persistence"):
                filepath = os.path.join(state.smtp["queue_dir"], f"{payload['id']}.json")
                if os.path.exists(filepath):
                    try: os.remove(filepath)
                    except OSError: pass
        else:
            payload["retry_count"] = payload.get("retry_count", 0) + 1
            payload["last_error"] = error_msg or "Unknown error"
            payload["last_attempt"] = now
            backoff_delay = min(5 * (2 ** (payload["retry_count"] - 1)), state.smtp["max_retry_backoff"])
            payload["next_retry"] = now + backoff_delay
            logging.warning(f"Delivery failed for ID: {payload['id']}. Retrying in {backoff_delay}s.")
            if not payload.get("disable_persistence"):
                filepath = os.path.join(state.smtp["queue_dir"], f"{payload['id']}.json")
                if os.path.exists(filepath):
                    try:
                        with open(filepath, 'w') as f: json.dump(payload, f)
                    except Exception: pass
            msg_queue.put(payload)
        msg_queue.task_done()

def load_queue_from_disk(msg_queue, state):
    if not os.path.exists(state.smtp["queue_dir"]): return
    count = 0
    for filename in os.listdir(state.smtp["queue_dir"]):
        if filename.endswith(".json"):
            filepath = os.path.join(state.smtp["queue_dir"], filename)
            try:
                with open(filepath, 'r') as f:
                    msg_queue.put(json.load(f))
                    count += 1
            except Exception: pass
    if count > 0: logging.info(f"Read {count} messages from persistent store")
