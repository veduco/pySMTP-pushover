import os
import json
import re
import time
import uuid
import logging
import base64
import string
import hashlib
from email import message_from_bytes, policy
from email.utils import parsedate_to_datetime
from aiosmtpd.controller import Controller
from aiosmtpd.smtp import SMTP

from core.config import MAX_TITLE_CHARS, MAX_ATTACHMENT_BYTES, MAX_URL_CHARS, MAX_URL_TITLE_CHARS

try:
    from passlib.hash import sha256_crypt, sha512_crypt, md5_crypt
    HAS_PASSLIB = True
except ImportError:
    HAS_PASSLIB = False

def sanitize_input(val, max_len=256):
    if not val: return ""
    val = val[:max_len]
    printable = set(string.printable) - set("\r\n\t\x0b\x0c")
    return "".join(ch for ch in val if ch in printable).strip()

def verify_password(plain_password, stored_value):
    if not stored_value: return False
    computed_sha = hashlib.sha256(plain_password.encode('utf-8')).hexdigest()
    if computed_sha == stored_value: return True
    if str(stored_value).startswith("$"):
        if HAS_PASSLIB:
            try:
                if stored_value.startswith("$5$"): return sha256_crypt.verify(plain_password, stored_value)
                elif stored_value.startswith("$6$"): return sha512_crypt.verify(plain_password, stored_value)
                elif stored_value.startswith("$1$"): return md5_crypt.verify(plain_password, stored_value)
            except Exception: return False
        else: return False
    return plain_password == stored_value

class GatewaySMTP(SMTP):
    async def smtp_MAIL(self, arg):
        if arg:
            arg = re.sub(r'(?i)\s+AUTH=[^\s]*', '', arg)
            arg = re.sub(r'(?i)\s+RET=[^\s]*', '', arg)
            arg = re.sub(r'(?i)\s+ENVID=[^\s]*', '', arg)
        return await super().smtp_MAIL(arg)
    async def smtp_RCPT(self, arg):
        if arg:
            arg = re.sub(r'(?i)\s+ORCPT=[^\s]*', '', arg)
            arg = re.sub(r'(?i)\s+NOTIFY=[^\s]*', '', arg)
        return await super().smtp_RCPT(arg)

class GatewayController(Controller):
    def __init__(self, handler, **kwargs):
        self._smtp_kwargs = kwargs.copy()
        super().__init__(handler, **kwargs)

    def factory(self):
        kwargs = self._smtp_kwargs.copy()
        for k in ['hostname', 'port', 'server_hostname', 'ready_timeout']: kwargs.pop(k, None)
        for attr in ['data_size_limit', 'enable_SMTPUTF8', 'ident', 'tls_context', 'tls_require_cert', 'authenticator', 'auth_require_tls', 'auth_exclude_mechanism', 'auth_callback_exceptions', 'timeout']:
            if hasattr(self, attr) and attr not in kwargs: kwargs[attr] = getattr(self, attr)
        smtp_instance = GatewaySMTP(self.handler, **kwargs)
        if hasattr(smtp_instance, 'command_size_limit'): smtp_instance.command_size_limit = 10485760
        if hasattr(smtp_instance, 'data_line_length_limit'): smtp_instance.data_line_length_limit = 10485760
        return smtp_instance

class GatewayAuthenticator:
    def __init__(self, state): self.state = state
    def __call__(self, server, session, envelope, mechanism, auth_data):
        auth_dict = self.state.smtp.get("auth", {})
        if not auth_dict: return True
        if mechanism not in ("PLAIN", "LOGIN"): return False
        raw_username = auth_data.login.decode('utf-8', errors='ignore')
        raw_password = auth_data.password.decode('utf-8', errors='ignore')
        username = sanitize_input(raw_username, max_len=128)
        password = sanitize_input(raw_password, max_len=256)
        if not username or not password: return False
        stored_password = auth_dict.get(username)
        if stored_password and verify_password(password, stored_password):
            logging.info(f"SMTP Authentication successful for user: {username}")
            return True
        return False

class PushoverSMTPHandler:
    def __init__(self, state, msg_queue):
        self.state = state
        self.msg_queue = msg_queue

    async def handle_DATA(self, server, session, envelope):
        try:
            raw_content = envelope.content
            raw_content = re.sub(br'(Content-Type:\s*[^;\r\n]+;\r?\n)(charset=)', br'\1 \2', raw_content, flags=re.IGNORECASE)
            raw_content = re.sub(br'(charset="?[a-zA-Z0-9\-]+"?\r?\n)(?!\r?\n|[ \t]*--|[A-Za-z0-9\-]+:|[ \t]+[A-Za-z0-9\-]+=)', br'\1\r\n', raw_content, flags=re.IGNORECASE)

            msg = message_from_bytes(raw_content, policy=policy.default)
            title = msg.get("Subject", "No Subject")
            if len(title) > MAX_TITLE_CHARS: title = title[:MAX_TITLE_CHARS]

            timestamp = int(time.time())
            date_header = msg.get("Date")
            if date_header:
                try: timestamp = int(parsedate_to_datetime(date_header).timestamp())
                except Exception: pass

            plain_body_raw = ""
            html_body_raw = ""
            valid_images = []

            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    content_disposition = str(part.get("Content-Disposition"))
                    if content_type.startswith("image/"):
                        payload_bytes = part.get_payload(decode=True)
                        if payload_bytes:
                            size = len(payload_bytes)
                            if size <= MAX_ATTACHMENT_BYTES: valid_images.append((size, str(part.get_filename() or "image.jpg"), content_type, payload_bytes))
                        continue
                    if "attachment" in content_disposition: continue
                    if content_type == "text/plain":
                        plain_body_raw = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors='replace')
                        if part.defects:
                            recovered_lines = []
                            for defect in part.defects:
                                if hasattr(defect, 'line') and defect.line:
                                    line_str = defect.line.decode('utf-8', errors='replace').strip() if isinstance(defect.line, bytes) else defect.line.strip()
                                    recovered_lines.append(line_str)
                            if recovered_lines: plain_body_raw = '\n'.join(recovered_lines) + '\n' + plain_body_raw
                    elif content_type == "text/html":
                        html_body_raw = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors='replace')
            else:
                raw_payload = msg.get_payload(decode=True)
                content_type = msg.get_content_type()
                if content_type.startswith("image/"):
                    if raw_payload:
                        size = len(raw_payload)
                        if size <= MAX_ATTACHMENT_BYTES: valid_images.append((size, str(msg.get_filename() or "image.jpg"), content_type, raw_payload))
                else:
                    decoded_str = raw_payload.decode(msg.get_content_charset() or 'utf-8', errors='replace') if raw_payload else ""
                    if content_type == "text/html": html_body_raw = decoded_str
                    else:
                        plain_body_raw = decoded_str
                        if msg.defects:
                            recovered_lines = []
                            for defect in msg.defects:
                                if hasattr(defect, 'line') and defect.line:
                                    line_str = defect.line.decode('utf-8', errors='replace').strip() if isinstance(defect.line, bytes) else defect.line.strip()
                                    recovered_lines.append(line_str)
                            if recovered_lines: plain_body_raw = '\n'.join(recovered_lines) + '\n' + plain_body_raw

            best_image = None
            if valid_images:
                valid_images.sort(key=lambda x: (-x[0], x[1]))
                best_image = valid_images[0]

            body_html_processed = None
            if html_body_raw:
                processed = re.sub(r'<(style|script|head|title)[^>]*>.*?</\1>', '', html_body_raw, flags=re.IGNORECASE | re.DOTALL)
                parts = re.split(r'(?i)(<pre[^>]*>.*?</pre>)', processed, flags=re.DOTALL)
                for i in range(len(parts)):
                    if not parts[i].lower().startswith('<pre'):
                        parts[i] = re.sub(r'[\r\n\t]+', ' ', parts[i])
                        parts[i] = re.sub(r'<br\s*/?>', '\n', parts[i], flags=re.IGNORECASE)
                        parts[i] = re.sub(r'</(p|div|tr|h[1-6]|li|table)>', '\n\n', parts[i], flags=re.IGNORECASE)
                        parts[i] = re.sub(r'<hr[^>]*>', '\n---\n', parts[i], flags=re.IGNORECASE)
                        parts[i] = re.sub(r'<(?!/?(a|b|i|u|font)\b)[^>]+>', '', parts[i], flags=re.IGNORECASE)
                        parts[i] = re.sub(r' {2,}', ' ', parts[i])
                        parts[i] = re.sub(r' ?\n ?', '\n', parts[i])
                    else:
                        parts[i] = re.sub(r'(?i)</?pre[^>]*>', '', parts[i])
                body_html_processed = ''.join(parts)
                body_html_processed = re.sub(r'\n{3,}', '\n\n', body_html_processed).strip()

            body_plain_processed = None
            if plain_body_raw:
                body_plain_processed = re.sub(r'(\r?\n[ \t]*){3,}', '\n\n', plain_body_raw).strip()

            routes_to_trigger = []
            sender = envelope.mail_from.lower() if envelope.mail_from else ""
            if sender in self.state.mappings.get("from", {}):
                logging.info(f"Matched sender address: {sender}")
                routes_to_trigger.append(self.state.mappings["from"][sender])

            for pattern, route_config in self.state.regex_mappings.get("from", []):
                if pattern.search(sender):
                    logging.info(f"Matched sender regex '{pattern.pattern}' to: {sender}")
                    routes_to_trigger.append(route_config)

            for recipient in envelope.rcpt_tos:
                recipient = recipient.lower()
                if recipient in self.state.mappings.get("to", {}):
                    logging.info(f"Matched recipient address: {recipient}")
                    routes_to_trigger.append(self.state.mappings["to"][recipient])

                for pattern, route_config in self.state.regex_mappings.get("to", []):
                    if pattern.search(recipient):
                        logging.info(f"Matched recipient regex '{pattern.pattern}' to: {recipient}")
                        routes_to_trigger.append(route_config)

            if not routes_to_trigger:
                def_route = self.state.smtp.get("default_route", "pushover")
                if def_route == "pushover":
                    if self.state.pushover.get("user") and self.state.pushover.get("token"):
                        logging.info("No explicit mappings matched. Falling back to global Pushover catch-all.")
                        routes_to_trigger.append(self.state.pushover)
                    else:
                        logging.info("No explicit mappings matched and no global Pushover catch-all defined. Ignoring message.")
                elif def_route == "smarthost":
                    sh_alias = self.state.smarthost.get("globals", {}).get("alias")
                    if sh_alias and sh_alias in self.state.smarthost.get("aliases", {}):
                        logging.info("No explicit mappings matched. Falling back to global Smarthost catch-all.")
                        g = self.state.smarthost.get("globals", {}).copy()
                        g["method"] = "smarthost"
                        g["smarthost_alias"] = sh_alias
                        routes_to_trigger.append(g)
                    else:
                        logging.info("No explicit mappings matched and global Smarthost alias is invalid. Ignoring message.")

            unique_routes = []
            seen_combinations = set()
            for route in routes_to_trigger:
                method = route.get("method", "pushover")
                if method == "pushover": combo_hash = f"push:{route.get('user')}:{route.get('token')}"
                else: combo_hash = f"smart:{route.get('smarthost_alias')}"
                if combo_hash not in seen_combinations:
                    seen_combinations.add(combo_hash)
                    unique_routes.append(route)

            for route in unique_routes:
                method = route.get("method", "pushover")
                if method == "pushover":
                    force_pt = route.get("force_plaintext", self.state.pushover.get("force_plaintext", False))
                    attachments_enabled = route.get("attachments", self.state.pushover.get("attachments", True))
                else:
                    g_smarthost = self.state.smarthost.get("globals", {})
                    sh_alias = route.get("smarthost_alias")
                    sh_conf = self.state.smarthost.get("aliases", {}).get(sh_alias, {})
                    force_pt = route.get("force_plaintext")
                    if force_pt is None: force_pt = sh_conf.get("force_plaintext")
                    if force_pt is None: force_pt = g_smarthost.get("force_plaintext", False)
                    route_disable_att = route.get("disable_attachments")
                    if route_disable_att is not None: attachments_enabled = not route_disable_att
                    else:
                        sh_disable_att = sh_conf.get("disable_attachments")
                        if sh_disable_att is not None: attachments_enabled = not sh_disable_att
                        else: attachments_enabled = not g_smarthost.get("disable_attachments", False)

                disable_persist = self.state.smtp.get("disable_persistence", False)

                if not force_pt and body_html_processed is not None:
                    final_body = body_html_processed
                    is_html = True
                elif body_plain_processed is not None:
                    final_body = body_plain_processed
                    is_html = False
                elif body_html_processed is not None:
                    final_body = body_html_processed
                    is_html = True
                else:
                    final_body = "(No message body)"
                    is_html = False

                payload = {
                    "id": uuid.uuid4().hex,
                    "method": method,
                    "message": final_body,
                    "title": title,
                    "timestamp": timestamp,
                    "is_html": is_html,
                    "disable_persistence": disable_persist,
                    "retry_count": 0,
                    "sender": sender or "gateway@localhost",
                    "recipients": envelope.rcpt_tos
                }

                if method == "pushover":
                    payload["user"] = route["user"]
                    payload["token"] = route["token"]
                    for param in ["device", "sound", "url", "url_title", "priority", "ttl", "tags", "retry", "expire"]:
                        if param in route: payload[param] = route[param]
                    if "url" in route and route["url"]: payload["url"] = route["url"][:MAX_URL_CHARS]
                    if "url_title" in route and route["url_title"]: payload["url_title"] = route["url_title"][:MAX_URL_TITLE_CHARS]
                else:
                    payload["smarthost_alias"] = route.get("smarthost_alias")
                    payload["force_plaintext"] = force_pt
                    payload["disable_attachments"] = not attachments_enabled
                    payload["raw_eml_base64"] = base64.b64encode(raw_content).decode('ascii')

                if attachments_enabled and best_image:
                    payload["attachment_base64"] = base64.b64encode(best_image[3]).decode('ascii')
                    payload["attachment_name"] = best_image[1]
                    payload["attachment_type"] = best_image[2]

                if not disable_persist:
                    filepath = os.path.join(self.state.smtp["queue_dir"], f"{payload['id']}.json")
                    with open(filepath, 'w') as f: json.dump(payload, f)

                self.msg_queue.put(payload)
            return '250 Message accepted for delivery'
        except Exception as e:
            logging.error(f"Error processing email: {e}", exc_info=True)
            return '500 Internal Server Error'
