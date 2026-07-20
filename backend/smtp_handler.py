import os
import json
import re
import time
import uuid
import logging
import base64
import string
import hashlib
import threading
from aiosmtpd.smtp import SMTP

from core.config import ConfigOrchestrator
from backend.mail_parser import parse_email_content
from core.utils import is_ip_allowed

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
    async def smtp_CONNECT(self, server, session, envelope):
        session.allowed_cidrs = getattr(self.event_handler, "allowed_cidrs", [])
        client_ip = session.peer[0] if session.peer else "127.0.0.1"

        if session.allowed_cidrs and not is_ip_allowed(client_ip, session.allowed_cidrs):
            logging.warning(f"Inbound SMTP connection dropped: Remote IP {client_ip} violated whitelist boundaries.")
            return "554 Transaction rejected: Client IP access denied by gateway security ACL policy restrictions."

        return await super().smtp_CONNECT(server, session, envelope)

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
    def __init__(self, state, msg_queue, broker=None):
        self.state = state
        self.msg_queue = msg_queue
        self.broker = broker
        self.allowed_cidrs = state.smtp.get("allowed_cidrs", [])

        # Thread-safe in-memory cache rings tracking alert duplication bounds
        self._dedupe_cache = {}
        self._dedupe_lock = threading.Lock()
        self._max_cache_scale = 10000

    def _match_explicit_routes(self, sender, recipients):
        routes_to_trigger = []

        # Match Sender
        if sender in self.state.mappings.get("from", {}):
            logging.info(f"Matched sender address: {sender}")
            r = self.state.mappings["from"][sender].copy()
            r["_match_reason"] = f"Sender: {sender}"
            routes_to_trigger.append(r)

        for pattern, route_config in self.state.regex_mappings.get("from", []):
            if pattern.search(sender):
                logging.info(f"Matched sender regex '{pattern.pattern}' to: {sender}")
                r = route_config.copy()
                r["_match_reason"] = f"Sender Regex: {pattern.pattern}"
                routes_to_trigger.append(r)

        # Match Recipients
        for recipient in recipients:
            if recipient in self.state.mappings.get("to", {}):
                logging.info(f"Matched recipient address: {recipient}")
                r = self.state.mappings["to"][recipient].copy()
                r["_match_reason"] = f"Recipient: {recipient}"
                routes_to_trigger.append(r)

            for pattern, route_config in self.state.regex_mappings.get("to", []):
                if pattern.search(recipient):
                    logging.info(f"Matched recipient regex '{pattern.pattern}' to: {recipient}")
                    r = route_config.copy()
                    r["_match_reason"] = f"Recipient Regex: {pattern.pattern}"
                    routes_to_trigger.append(r)

        return routes_to_trigger

    def _apply_fallbacks(self, routes_to_trigger, sender, recipients):
        if not routes_to_trigger:
            def_route = self.state.smtp.get("default_route", "pushover")

            # Format clean addresses for the log output
            log_from = sender if sender else "Unknown"
            log_to = ", ".join(recipients) if recipients else "Unknown"
            base_log_msg = f"No explicit mappings matched [To: {log_to}, From: {log_from}]"

            if def_route == "pushover":
                if self.state.pushover.get("user") and self.state.pushover.get("token"):
                    logging.info(f"{base_log_msg}. Falling back to global Pushover catch-all.")
                    r = self.state.pushover.copy()
                    r["_match_reason"] = "Global Default Route"
                    routes_to_trigger.append(r)
                else:
                    logging.info(f"{base_log_msg}. No global Pushover catch-all defined. Ignoring message.")

            elif def_route == "smarthost":
                sh_alias = self.state.smarthost.get("globals", {}).get("alias")
                if sh_alias and sh_alias in self.state.smarthost.get("aliases", {}):
                    logging.info(f"{base_log_msg}. Falling back to global Smarthost catch-all.")
                    g = self.state.smarthost.get("globals", {}).copy()
                    g["method"] = "smarthost"
                    g["smarthost_alias"] = sh_alias
                    g["_match_reason"] = "Global Default Route"
                    routes_to_trigger.append(g)
                else:
                    logging.info(f"{base_log_msg}. Global Smarthost alias is invalid. Ignoring message.")

        return routes_to_trigger

    def _deduplicate_routes(self, routes_to_trigger):
        unique_routes = []
        seen_combinations = set()

        for route in routes_to_trigger:
            method = route.get("method", "pushover")
            if method == "pushover":
                combo_hash = f"push:{route.get('user')}:{route.get('token')}"
            else:
                combo_hash = f"smart:{route.get('smarthost_alias')}"

            if combo_hash not in seen_combinations:
                seen_combinations.add(combo_hash)
                unique_routes.append(route)

        return unique_routes

    def _is_duplicate_suppressed(self, parsed_data, sender, recipients, client_ip, unique_routes) -> bool:
        """Assembles signature strings dynamically from criteria options and flags exact matches via SHA-256."""
        if not self.state.smtp.get("dedupe_enabled", False):
            return False

        keys_to_build = self.state.smtp.get("dedupe_keys", ["sender", "match_reason", "message"])
        window_str = self.state.smtp.get("dedupe_window", "10m")
        window_seconds = ConfigOrchestrator.parse_duration_to_seconds(window_str)
        now = time.time()

        # Build signature block data array string elements
        signature_segments = []

        if "recipients" in keys_to_build:
            signature_segments.append(f"rcpt:{','.join(sorted(recipients))}")
        if "sender" in keys_to_build:
            signature_segments.append(f"from:{sender}")
        if "subject" in keys_to_build:
            signature_segments.append(f"sub:{parsed_data.get('title', '')}")
        if "match_reason" in keys_to_build:
            reasons = [r.get("_match_reason", "") for r in unique_routes if r.get("_match_reason")]
            signature_segments.append(f"reason:{','.join(sorted(reasons))}")
        if "message" in keys_to_build:
            body = parsed_data.get("body_html_processed") or parsed_data.get("body_plain_processed") or "(No message body)"
            signature_segments.append(f"body:{body}")
        if "senderip" in keys_to_build:
            signature_segments.append(f"ip:{client_ip}")

        # Compute pristine cryptographic SHA-256 identifier signature target
        sig_payload = "||".join(signature_segments).encode('utf-8', errors='replace')
        sig_hash = hashlib.sha256(sig_payload).hexdigest()

        with self._dedupe_lock:
            # Passive Eviction Pass: Purge expired records inline
            expired_keys = [k for k, expire_time in self._dedupe_cache.items() if now >= expire_time]
            for ek in expired_keys:
                del self._dedupe_cache[ek]

            # Enforce strict maximum capacity boundaries under heavy alert bursts
            if len(self._dedupe_cache) >= self._max_cache_scale:
                # O(1) eviction of the absolute oldest inserted element to maintain deterministic execution scale
                oldest_key = next(iter(self._dedupe_cache))
                del self._dedupe_cache[oldest_key]

            if sig_hash in self._dedupe_cache:
                logging.warning(f"Deduplication Triggered: Dropped incoming email signature tracking payload hash matching active window rules.")
                return True

            # Insert fresh deduplication contract into memory registry
            self._dedupe_cache[sig_hash] = now + window_seconds
            return False

    async def _enqueue_payloads(self, unique_routes, parsed_data, envelope, sender, recipients):
        raw_content = envelope.content
        title = parsed_data["title"]
        timestamp = parsed_data["timestamp"]
        best_image = parsed_data["best_image"]
        body_html_processed = parsed_data["body_html_processed"]
        body_plain_processed = parsed_data["body_plain_processed"]
        disable_persist = self.state.smtp.get("disable_persistence", False)

        for route in unique_routes:
            method = route.get("method", "pushover")

            # Delegate dynamic resolution to the centralized engine context
            ctx = self.state.resolve_delivery_context(method, route)

            force_pt = ctx.get("force_plaintext", False)
            attachments_enabled = ctx.get("attachments", True)

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
                "match_reason": route.get("_match_reason", "Test / Direct Injection"),
                "message": final_body,
                "title": title,
                "timestamp": timestamp,
                "is_html": is_html,
                "disable_persistence": disable_persist,
                "retry_count": 0,
                "sender": sender or "gateway@localhost",
                "recipients": recipients,
                "raw_eml_base64": base64.b64encode(raw_content).decode('ascii')
            }

            if method == "pushover":
                # Ensure tracking parameters are packed for final delivery context resolution
                payload["token"] = route.get("token", "")
                payload["user"] = route.get("user", "")
                for param in ["device", "sound", "url", "url_title", "priority", "ttl", "tags", "retry", "expire"]:
                    if route.get(param) is not None and route.get(param) != "":
                        payload[param] = route.get(param)
            else:
                payload["smarthost_alias"] = route.get("smarthost_alias", "")

            # Guarantee structural overrides are preserved across the persistence layer boundaries
            if "force_plaintext" in route: payload["force_plaintext"] = route["force_plaintext"]
            if "disable_attachments" in route: payload["disable_attachments"] = route["disable_attachments"]

            if attachments_enabled and best_image:
                payload["attachment_base64"] = base64.b64encode(best_image[3]).decode('ascii')
                payload["attachment_name"] = best_image[1]
                payload["attachment_type"] = best_image[2]

            if not disable_persist:
                filepath = os.path.join(self.state.smtp["queue_dir"], f"{payload['id']}.json")
                try:
                    with open(filepath, 'w') as f:
                        json.dump(payload, f)
                except Exception as e:
                    logging.warning(f"Disk persistence failed for {payload['id']}, falling back to pure in-memory queueing. Error: {e}")

            await self.msg_queue.put(payload)
            if self.broker:
                self.broker.publish("add", payload)

    async def handle_DATA(self, server, session, envelope):
        try:
            # 1. Parse the raw email byte payload
            parsed_data = parse_email_content(envelope.content)
            sender = envelope.mail_from.lower() if envelope.mail_from else ""
            recipients = [r.lower() for r in envelope.rcpt_tos]
            client_ip = session.peer[0] if session and session.peer else "127.0.0.1"

            # 2. Evaluate explicit routing rules
            routes = self._match_explicit_routes(sender, recipients)

            # 3. Apply global fallbacks if no explicit routes matched
            routes = self._apply_fallbacks(routes, sender, recipients)

            # 4. Deduplicate identical destinations
            unique_routes = self._deduplicate_routes(routes)

            # 5. Core Security Intercept Pass: Deduplication Evaluation
            if self._is_duplicate_suppressed(parsed_data, sender, recipients, client_ip, unique_routes):
                return '250 Message accepted for delivery' # Silent discard compliance contract

            # 6. Compile final payloads and dispatch to workers
            await self._enqueue_payloads(unique_routes, parsed_data, envelope, sender, recipients)

            return '250 Message accepted for delivery'
        except Exception as e:
            logging.error(f"Error processing email: {e}", exc_info=True)
            return '500 Internal Server Error'
