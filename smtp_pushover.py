#!/usr/bin/env python3
"""
SMTP to Pushover Notification Gateway (Threaded with Disk Persistence & Signal Handling)

================================================================================
OS PACKAGE REQUIREMENTS
================================================================================

Debian 13 (Trixie):
    $ sudo apt-get update
    $ sudo apt-get install python3 python3-requests python3-cryptography python3-aiosmtpd python3-passlib

Alpine Linux:
    $ apk update
    $ apk add python3 py3-requests py3-cryptography py3-aiosmtpd py3-passlib

If native packages are missing on your distribution, you can install pip
and use it (preferably within a virtual environment):
    $ pip install aiosmtpd requests cryptography passlib

================================================================================
SIGNALS
================================================================================
SIGINT / SIGTERM: Gracefully shuts down the SMTP listener and waits for queue to empty.
SIGUSR1: Atomically diffs and restarts SMTP listeners if their configs/certs have changed.
SIGUSR2: Reloads GATEWAY_CONFIG from disk and dynamically updates routing rules.
"""

# Standard library imports for system, regex, and threading operations
import os
import re
import json
import time
import uuid
import logging
import ssl
import datetime
import threading
import queue
import signal
import string
import hashlib
import base64
import smtplib
import email.utils
from email.message import EmailMessage

# External HTTP request handling
import requests

# Email parsing libraries to tear down incoming SMTP data blocks
from email import message_from_bytes, policy
from email.utils import parsedate_to_datetime
from aiosmtpd.controller import Controller
from aiosmtpd.smtp import SMTP

# Cryptography imports for generating our fallback self-signed certificates on the fly
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

# Attempt to load passlib for flawless crypt format verification (Debian/Alpine standard)
# If it's missing, we fail gracefully and log a warning if a hashed password is encountered.
try:
    from passlib.hash import sha256_crypt, sha512_crypt, md5_crypt
    HAS_PASSLIB = True
except ImportError:
    HAS_PASSLIB = False

# API Constraints and Size Limits
MAX_ATTACHMENT_BYTES = 5242880
MAX_TITLE_CHARS = 250
MAX_URL_CHARS = 512
MAX_URL_TITLE_CHARS = 100

# Establish baseline logging. The log level will be updated later once the config is parsed.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
aiosmtpd_logger = logging.getLogger('mail.log')

class SuppressUnrecognisedFilter(logging.Filter):
    """Silently drops aiosmtpd warnings caused by binary TLS probes unless in DEBUG mode."""
    def filter(self, record):
        # If the root logger is in DEBUG mode (level 10), let everything through
        if logging.getLogger().getEffectiveLevel() <= logging.DEBUG:
            return True
        # Otherwise, drop the log if it contains the TLS gibberish warning
        return "unrecognised" not in record.getMessage()

aiosmtpd_logger.addFilter(SuppressUnrecognisedFilter())

PUSHOVER_API_URL = "https://api.pushover.net/1/messages.json"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PID_FILE = "/tmp/smtp_pushover.pid"

# Global threading events used by OS signal handlers to safely communicate with the main loop
shutdown_event = threading.Event()
reload_event = threading.Event()
mappings_reload_event = threading.Event()


class GatewaySMTP(SMTP):
    """
    Custom SMTP handler to intercept and sanitize complex ESMTP parameters.
    Strict enterprise MTAs (like Solaris/Sendmail) often attach AUTH=<>, RET=HDRS, etc.
    The default aiosmtpd parser abruptly rejects unrecognized parameters with a 555 error.
    """
    async def smtp_MAIL(self, arg):
        if arg:
            # Safely excise unsupported ESMTP parameters appended to MAIL FROM
            arg = re.sub(r'(?i)\s+AUTH=[^\s]*', '', arg)
            arg = re.sub(r'(?i)\s+RET=[^\s]*', '', arg)
            arg = re.sub(r'(?i)\s+ENVID=[^\s]*', '', arg)
        return await super().smtp_MAIL(arg)

    async def smtp_RCPT(self, arg):
        if arg:
            # Safely excise unsupported ESMTP parameters appended to RCPT TO
            arg = re.sub(r'(?i)\s+ORCPT=[^\s]*', '', arg)
            arg = re.sub(r'(?i)\s+NOTIFY=[^\s]*', '', arg)
        return await super().smtp_RCPT(arg)

class GatewayController(Controller):
    """
    Custom controller to deploy our sanitized SMTP handler transparently.
    """
    def __init__(self, handler, **kwargs):
        # Intercept and store kwargs intended for the SMTP class so they aren't lost
        # by older aiosmtpd Controller initializations
        self._smtp_kwargs = kwargs.copy()
        super().__init__(handler, **kwargs)

    def factory(self):
        # Reconstruct the SMTP instance using our safely captured kwargs
        kwargs = self._smtp_kwargs.copy()

        # Remove kwargs strictly intended for the Controller's socket binding
        # so they don't crash the SMTP protocol's instantiation
        for k in ['hostname', 'port', 'server_hostname', 'ready_timeout']:
            kwargs.pop(k, None)

        # Merge any legacy properties aiosmtpd might have attached directly to `self`
        for attr in ['data_size_limit', 'enable_SMTPUTF8', 'ident', 'tls_context',
                     'tls_require_cert', 'authenticator', 'auth_require_tls',
                     'auth_exclude_mechanism', 'auth_callback_exceptions', 'timeout']:
            if hasattr(self, attr) and attr not in kwargs:
                kwargs[attr] = getattr(self, attr)

        # Instantiate our custom class natively to avoid event-loop bindings issues
        smtp_instance = GatewaySMTP(self.handler, **kwargs)

        # OVERRIDE: RFC 5321 restricts single email lines to 1000 characters.
        # Curl streams, concatenated HTML strings, and bad uuencodes frequently violate this.
        # We artificially inflate this to 10MB to prevent '500 Line too long' rejection errors.
        if hasattr(smtp_instance, 'command_size_limit'):
            smtp_instance.command_size_limit = 10485760
        if hasattr(smtp_instance, 'data_line_length_limit'):
            smtp_instance.data_line_length_limit = 10485760

        return smtp_instance


class GatewayState:
    """
    A thread-safe container to hold the application's configuration state.
    By storing everything here, we can atomically swap out configurations
    during a SIGUSR2 hot-reload without crashing active connections.
    """
    def __init__(self):
        self.smtp = {}
        self.pushover = {}
        self.smarthost = {}
        self.mappings = {"to": {}, "from": {}}
        self.regex_mappings = {"to": [], "from": []}
        self.config_file = None
        self.vault = {}

def get_bool(val, default=False):
    """Safely coerces strings, ints, or booleans from JSON into a Python boolean."""
    if val is None:
        return default
    return str(val).lower() in ("1", "true", "yes")

def sanitize_input(val, max_len=256):
    """
    Sanitizes remote client strings to mitigate log injection and buffer overflows.
    Used exclusively on the username and password strings provided during SMTP authentication.
    """
    if not val:
        return ""
    # Enforce a safe upper length limit
    val = val[:max_len]
    # Filter out dangerous control characters (keep standard spaces and printable characters)
    printable = set(string.printable) - set("\r\n\t\x0b\x0c")
    return "".join(ch for ch in val if ch in printable).strip()

def verify_password(plain_password, stored_value):
    """Verifies a plain text password against a stored entry (which can be plain, sha256, or passlib hash)."""
    if not stored_value:
        return False

    # Check for native SHA-256 match generated via the UI Control Panel
    computed_sha = hashlib.sha256(plain_password.encode('utf-8')).hexdigest()
    if computed_sha == stored_value:
        return True

    # If it starts with a dollar sign, it's a Linux crypt hash (e.g., $5$ for SHA-256)
    if str(stored_value).startswith("$"):
        if HAS_PASSLIB:
            try:
                if stored_value.startswith("$5$"): return sha256_crypt.verify(plain_password, stored_value)
                elif stored_value.startswith("$6$"): return sha512_crypt.verify(plain_password, stored_value)
                elif stored_value.startswith("$1$"): return md5_crypt.verify(plain_password, stored_value)
            except Exception as e:
                logging.error(f"Error checking hash with passlib: {e}")
                return False
        else:
            logging.warning("Received a password hash but 'passlib' is not installed. Failed authentication.")
            return False

    # Fallback to plain text exact matching
    return plain_password == stored_value

class GatewayAuthenticator:
    """Implements custom validation and sanitization hooks for the aiosmtpd AUTH logic."""
    def __init__(self, state):
        self.state = state

    def __call__(self, server, session, envelope, mechanism, auth_data):
        # If no authentication is configured, we allow everyone through (Permissive mode)
        auth_dict = self.state.smtp.get("auth", {})
        if not auth_dict:
            return True

        # We only advertise and accept standard plain text mechanisms
        if mechanism not in ("PLAIN", "LOGIN"):
            return False

        raw_username = auth_data.login.decode('utf-8', errors='ignore')
        raw_password = auth_data.password.decode('utf-8', errors='ignore')

        username = sanitize_input(raw_username, max_len=128)
        password = sanitize_input(raw_password, max_len=256)

        if not username or not password:
            logging.warning("Rejected SMTP authentication containing invalid or malicious control symbols.")
            return False

        stored_password = auth_dict.get(username)
        if stored_password and verify_password(password, stored_password):
            logging.info(f"SMTP Authentication successful for user: {username}")
            return True

        logging.warning(f"Failed SMTP Authentication attempt for username: {username}")
        return False

class PushoverSMTPHandler:
    """The core logic module triggered by aiosmtpd every time an email arrives."""
    def __init__(self, state, msg_queue):
        self.state = state
        self.msg_queue = msg_queue

    async def handle_DATA(self, server, session, envelope):
        try:
            # Solaris/Legacy MTA MIME Pre-Processor Fix:
            # Hand-rolled script outputs often completely forget the mandatory blank line between
            # MIME headers and the payload, or break header continuations (like charset) incorrectly.
            raw_content = envelope.content

            # 1. Correct syntax constraints for un-indented parameter extensions
            raw_content = re.sub(
                br'(Content-Type:\s*[^;\r\n]+;\r?\n)(charset=)',
                br'\1 \2',
                raw_content,
                flags=re.IGNORECASE
            )

            # 2. Inject missing blank line after boundary attributes if text content immediately follows
            raw_content = re.sub(
                br'(charset="?[a-zA-Z0-9\-]+"?\r?\n)(?!\r?\n|[ \t]*--)',
                br'\1\r\n',
                raw_content,
                flags=re.IGNORECASE
            )

            # Parse the raw email bytes into a structured Python object
            msg = message_from_bytes(raw_content, policy=policy.default)

            # Extract and gracefully truncate the title to meet API constraints
            title = msg.get("Subject", "No Subject")
            if len(title) > MAX_TITLE_CHARS:
                title = title[:MAX_TITLE_CHARS]

            # Extract the timestamp, falling back to current time if missing or malformed
            timestamp = int(time.time())
            date_header = msg.get("Date")
            if date_header:
                try:
                    dt = parsedate_to_datetime(date_header)
                    timestamp = int(dt.timestamp())
                except Exception as e:
                    logging.warning(f"Could not parse date '{date_header}': {e}. Using current time.")

            plain_body_raw = ""
            html_body_raw = ""
            valid_images = []

            # 1. Extract raw payloads and attachments from the email structure
            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    content_disposition = str(part.get("Content-Disposition"))

                    # Safely intercept valid images regardless of disposition (inline or attachment)
                    if content_type.startswith("image/"):
                        payload_bytes = part.get_payload(decode=True)
                        if payload_bytes:
                            size = len(payload_bytes)
                            if size <= MAX_ATTACHMENT_BYTES:
                                filename = str(part.get_filename() or "image.jpg")
                                valid_images.append((size, filename, content_type, payload_bytes))
                        continue

                    # We don't want to try and parse binary file attachments as text
                    if "attachment" in content_disposition:
                        continue

                    if content_type == "text/plain":
                        plain_body_raw = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors='replace')

                        # Recover any payload lines that were swallowed by the parser as malformed headers
                        # This happens if a legacy MTA script omits blank lines entirely before formatting dividers (e.g. ====)
                        if part.defects:
                            recovered_lines = []
                            for defect in part.defects:
                                if hasattr(defect, 'line') and defect.line:
                                    line_str = defect.line.decode('utf-8', errors='replace').strip() if isinstance(defect.line, bytes) else defect.line.strip()
                                    recovered_lines.append(line_str)
                            if recovered_lines:
                                plain_body_raw = '\n'.join(recovered_lines) + '\n' + plain_body_raw

                    elif content_type == "text/html":
                        html_body_raw = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors='replace')
            else:
                # Handle single-part emails that don't have boundaries
                raw_payload = msg.get_payload(decode=True)
                content_type = msg.get_content_type()
                if content_type.startswith("image/"):
                    if raw_payload:
                        size = len(raw_payload)
                        if size <= MAX_ATTACHMENT_BYTES:
                            filename = str(msg.get_filename() or "image.jpg")
                            valid_images.append((size, filename, content_type, raw_payload))
                else:
                    decoded_str = raw_payload.decode(msg.get_content_charset() or 'utf-8', errors='replace') if raw_payload else ""
                    if content_type == "text/html":
                        html_body_raw = decoded_str
                    else:
                        plain_body_raw = decoded_str
                        # Single-part recovery catch for malformed legacy headers
                        if msg.defects:
                            recovered_lines = []
                            for defect in msg.defects:
                                if hasattr(defect, 'line') and defect.line:
                                    line_str = defect.line.decode('utf-8', errors='replace').strip() if isinstance(defect.line, bytes) else defect.line.strip()
                                    recovered_lines.append(line_str)
                            if recovered_lines:
                                plain_body_raw = '\n'.join(recovered_lines) + '\n' + plain_body_raw

            # Sort valid images: descending by size (-x[0]), then ascending lexicographically by name (x[1])
            best_image = None
            if valid_images:
                valid_images.sort(key=lambda x: (-x[0], x[1]))
                best_image = valid_images[0]

            # 2. Pre-process formats for fast contextual assignment later
            body_html_processed = None
            if html_body_raw:
                # Erase entire blocks (and their contents) that contain metadata/CSS/scripts so they don't render as text
                processed = re.sub(r'<(style|script|head|title)[^>]*>.*?</\1>', '', html_body_raw, flags=re.IGNORECASE | re.DOTALL)

                # Protect <pre> blocks from whitespace destruction to preserve layout logic
                parts = re.split(r'(?i)(<pre[^>]*>.*?</pre>)', processed, flags=re.DOTALL)
                for i in range(len(parts)):
                    if not parts[i].lower().startswith('<pre'):
                        # Strip all literal source-code newlines and tabs from normal HTML
                        parts[i] = re.sub(r'[\r\n\t]+', ' ', parts[i])
                        # Translate structural HTML layout tags into literal newlines for Pushover
                        parts[i] = re.sub(r'<br\s*/?>', '\n', parts[i], flags=re.IGNORECASE)
                        parts[i] = re.sub(r'</(p|div|tr|h[1-6]|li|table)>', '\n\n', parts[i], flags=re.IGNORECASE)
                        parts[i] = re.sub(r'<hr[^>]*>', '\n---\n', parts[i], flags=re.IGNORECASE)
                        # Strip all HTML tags EXCEPT the specific formatting tags Pushover actually supports
                        parts[i] = re.sub(r'<(?!/?(a|b|i|u|font)\b)[^>]+>', '', parts[i], flags=re.IGNORECASE)
                        # Clean up excess whitespace and consecutive blank lines left behind by deleted tags
                        parts[i] = re.sub(r' {2,}', ' ', parts[i])
                        parts[i] = re.sub(r' ?\n ?', '\n', parts[i])
                    else:
                        # For <pre> blocks, just strip the outer <pre> tags themselves and leave the literal text alone!
                        parts[i] = re.sub(r'(?i)</?pre[^>]*>', '', parts[i])

                body_html_processed = ''.join(parts)
                body_html_processed = re.sub(r'\n{3,}', '\n\n', body_html_processed).strip()

            body_plain_processed = None
            if plain_body_raw:
                # For plain text, simply collapse 3+ consecutive newlines into exactly 2 (a single blank line)
                body_plain_processed = re.sub(r'(\r?\n[ \t]*){3,}', '\n\n', plain_body_raw).strip()

            # 3. Match Routes
            routes_to_trigger = []
            sender = envelope.mail_from.lower() if envelope.mail_from else ""
            if sender in self.state.mappings.get("from", {}):
                logging.info(f"Matched sender address: {sender}")
                routes_to_trigger.append(self.state.mappings["from"][sender])

            # Regex Fallback for Senders
            for pattern, route_config in self.state.regex_mappings.get("from", []):
                if pattern.search(sender):
                    logging.info(f"Matched sender regex '{pattern.pattern}' to: {sender}")
                    routes_to_trigger.append(route_config)

            for recipient in envelope.rcpt_tos:
                recipient = recipient.lower()
                if recipient in self.state.mappings.get("to", {}):
                    logging.info(f"Matched recipient address: {recipient}")
                    routes_to_trigger.append(self.state.mappings["to"][recipient])

                # Regex Fallback for Recipients
                for pattern, route_config in self.state.regex_mappings.get("to", []):
                    if pattern.search(recipient):
                        logging.info(f"Matched recipient regex '{pattern.pattern}' to: {recipient}")
                        routes_to_trigger.append(route_config)

            # If nobody matched, check if the global fallback catch-all is configured
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

            # Deduplicate Routes
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

            # 4. Contextual Formatting & Queuing
            for route in unique_routes:
                method = route.get("method", "pushover")

                # Determine Format Overrides based on method layered cascade
                if method == "pushover":
                    force_pt = route.get("force_plaintext", self.state.pushover.get("force_plaintext", False))
                    attachments_enabled = route.get("attachments", self.state.pushover.get("attachments", True))
                else:
                    g_smarthost = self.state.smarthost.get("globals", {})
                    sh_alias = route.get("smarthost_alias")
                    sh_conf = self.state.smarthost.get("aliases", {}).get(sh_alias, {})

                    force_pt = route.get("force_plaintext")
                    if force_pt is None:
                        force_pt = sh_conf.get("force_plaintext")
                        if force_pt is None:
                            force_pt = g_smarthost.get("force_plaintext", False)

                    route_disable_att = route.get("disable_attachments")
                    if route_disable_att is not None:
                        attachments_enabled = not route_disable_att
                    else:
                        sh_disable_att = sh_conf.get("disable_attachments")
                        if sh_disable_att is not None:
                            attachments_enabled = not sh_disable_att
                        else:
                            attachments_enabled = not g_smarthost.get("disable_attachments", False)

                disable_persist = self.state.smtp.get("disable_persistence", False)

                # Determine which pre-processed body format this specific route should get
                if not force_pt and body_html_processed is not None:
                    final_body = body_html_processed
                    is_html = True
                elif body_plain_processed is not None:
                    final_body = body_plain_processed
                    is_html = False
                elif body_html_processed is not None:
                    logging.warning(f"Route targeting '{method}' forced plaintext, but no text/plain part was found. Falling back to HTML payload.")
                    final_body = body_html_processed
                    is_html = True
                else:
                    final_body = "(No message body)"
                    is_html = False

                # Build the base payload dictionary
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
                    # Pass optional configuration constraints along if they exist for this route
                    for param in ["device", "sound", "url", "url_title", "priority", "ttl", "tags", "retry", "expire"]:
                        if param in route:
                            payload[param] = route[param]

                    # Ensure dynamic API length limits are applied contextually before queuing
                    if "url" in route and route["url"]:
                        payload["url"] = route["url"][:MAX_URL_CHARS]
                    if "url_title" in route and route["url_title"]:
                        payload["url_title"] = route["url_title"][:MAX_URL_TITLE_CHARS]
                else:
                    payload["smarthost_alias"] = route.get("smarthost_alias")
                    payload["force_plaintext"] = force_pt
                    payload["disable_attachments"] = not attachments_enabled
                    # Store the complete raw bytes in case we are forwarding unmodified
                    payload["raw_eml_base64"] = base64.b64encode(raw_content).decode('ascii')

                # Base64 encode the resolved image attachment for safe persistence queuing (if supported)
                if attachments_enabled and best_image:
                    payload["attachment_base64"] = base64.b64encode(best_image[3]).decode('ascii')
                    payload["attachment_name"] = best_image[1]
                    payload["attachment_type"] = best_image[2]

                # Step 1: Save it to disk for crash resilience (unless persistence is disabled)
                if not disable_persist:
                    filepath = os.path.join(self.state.smtp["queue_dir"], f"{payload['id']}.json")
                    with open(filepath, 'w') as f:
                        json.dump(payload, f)

                # Step 2: Queue it into memory for the background worker to pick up
                self.msg_queue.put(payload)
                logging.debug(f"Queued notification payload (ID: {payload['id']}, Method: {method}, HTML: {is_html}, Persistent: {not disable_persist})")

            # Always return a 250 OK to the SMTP client so it stops trying to send the email
            return '250 Message accepted for delivery'
        except Exception as e:
            logging.error(f"Error processing email: {e}", exc_info=True)
            return '500 Internal Server Error'

def delivery_worker(msg_queue, state):
    """
    Unified background worker thread running continuously.
    Pops messages off the memory queue and multiplexes them to Pushover API or Smarthost relays.
    Handles exponential backoff cleanly via interruptible sleeps to prevent thread-locking.
    """
    logging.debug("Delivery worker thread started.")
    while not shutdown_event.is_set():
        try:
            # Short interruptible wait allows fast exit on SIGTERM
            payload = msg_queue.get(timeout=1.0)
        except queue.Empty:
            continue

        # A payload of None is our signal from the main thread to shut down cleanly
        if payload is None:
            msg_queue.task_done()
            break

        now = int(time.time())
        next_retry = payload.get("next_retry", 0)

        if now < next_retry:
            # Not time for this message to retry yet. Put it back in the queue.
            msg_queue.put(payload)
            msg_queue.task_done()
            # Brief sleep prevents 100% CPU lock if queue is entirely composed of items waiting for backoff
            shutdown_event.wait(1.0)
            continue

        # Real-Time UI Deletion Sync: If the file was removed from the disk via the UI, drop it from memory.
        if not payload.get("disable_persistence"):
            filepath = os.path.join(state.smtp["queue_dir"], f"{payload['id']}.json")
            if payload.get("retry_count", 0) > 0 and not os.path.exists(filepath):
                logging.info(f"Message ID {payload['id']} was deleted by UI. Dropping from memory queue.")
                msg_queue.task_done()
                continue

        method = payload.get("method", "pushover")
        success = False
        error_msg = None

        if method == "pushover":
            api_payload = {
                "token": payload["token"],
                "user": payload["user"],
                "message": payload["message"],
                "title": payload["title"],
                "timestamp": payload["timestamp"],
                "html": 1 if payload.get("is_html") else 0
            }

            for param in ["device", "sound", "url", "url_title", "priority", "ttl", "tags", "retry", "expire"]:
                if param in payload:
                    api_payload[param] = payload[param]

            try:
                post_kwargs = {}
                if payload.get("attachment_base64"):
                    img_bytes = base64.b64decode(payload["attachment_base64"])
                    files = {
                        "attachment": (payload.get("attachment_name", "image.jpg"), img_bytes, payload.get("attachment_type", "image/jpeg"))
                    }
                    post_kwargs = {"data": api_payload, "files": files}
                else:
                    post_kwargs = {"json": api_payload}

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
                    # Determine if we need to synthesize a new email boundary to satisfy formatting constraints
                    if payload.get("force_plaintext") or payload.get("disable_attachments"):
                        msg = EmailMessage()
                        msg['Subject'] = payload.get("title", "No Subject")
                        msg['From'] = payload.get("sender", "gateway@localhost")
                        msg['To'] = ", ".join(payload.get("recipients", []))
                        msg['Date'] = email.utils.formatdate(localtime=False)
                        msg['Message-ID'] = email.utils.make_msgid()

                        if payload.get("is_html"):
                            msg.set_content(payload.get("message", ""), subtype="html", charset="utf-8")
                        else:
                            msg.set_content(payload.get("message", ""), charset="utf-8")

                        # If attachments aren't disabled, reattach the parsed image representation
                        if not payload.get("disable_attachments") and payload.get("attachment_base64"):
                            img_bytes = base64.b64decode(payload["attachment_base64"])
                            maintype, subtype = payload["attachment_type"].split('/', 1)
                            msg.add_attachment(img_bytes, maintype=maintype, subtype=subtype, filename=payload["attachment_name"])

                        raw_bytes = bytes(msg)
                    else:
                        # Stream the entirely unmodified raw bytes exactly as they hit the listener
                        raw_bytes = base64.b64decode(payload["raw_eml_base64"])

                    host = sh_conf.get("hostname")
                    port = int(sh_conf.get("port", 25))

                    # Dynamically compute EHLO inheritance block
                    local_ehlo = sh_conf.get("advertised_hostname")
                    if not local_ehlo: local_ehlo = state.smtp.get("hostname")
                    if not local_ehlo: local_ehlo = "localhost"

                    with smtplib.SMTP(host, port, timeout=15) as server:
                        server.ehlo(local_ehlo)
                        if sh_conf.get("starttls"):
                            if sh_conf.get("disable_tls_validation"):
                                server.starttls(context=ssl._create_unverified_context())
                            else:
                                server.starttls()
                            server.ehlo(local_ehlo)
                        if sh_conf.get("auth"):
                            # Securely access the relay password directly from the unencrypted vault memory context
                            sh_pass = state.vault.get("smarthost", {}).get(alias, "")
                            server.login(sh_conf.get("username", ""), sh_pass)

                        server.sendmail(payload.get("sender"), payload.get("recipients"), raw_bytes)

                    logging.info(f"Successfully relayed email '{payload['title']}' via Smarthost '{alias}'.")
                    success = True
                except Exception as e:
                    error_msg = repr(e)
                    logging.error(f"Smarthost relay failed for '{alias}': {error_msg}")


        if success:
            # Clean up the persistence file on disk now that it's safely delivered
            if not payload.get("disable_persistence"):
                filepath = os.path.join(state.smtp["queue_dir"], f"{payload['id']}.json")
                if os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                    except OSError as e:
                        logging.error(f"Failed to delete disk queue file {filepath}: {e}")
        else:
            # Handle failure with exponential backoff and update the UI readable parameters
            payload["retry_count"] = payload.get("retry_count", 0) + 1
            payload["last_error"] = error_msg or "Unknown error"
            payload["last_attempt"] = now

            backoff_delay = min(5 * (2 ** (payload["retry_count"] - 1)), state.smtp["max_retry_backoff"])
            payload["next_retry"] = now + backoff_delay

            logging.warning(f"Delivery failed for ID: {payload['id']}. Retrying in {backoff_delay}s.")

            # Update the disk file so if the app crashes during the sleep, we remember the retry count
            if not payload.get("disable_persistence"):
                filepath = os.path.join(state.smtp["queue_dir"], f"{payload['id']}.json")
                if os.path.exists(filepath):
                    try:
                        with open(filepath, 'w') as f:
                            json.dump(payload, f)
                    except Exception as e:
                        logging.error(f"Failed to update retry metadata on disk: {e}")

            msg_queue.put(payload)

        msg_queue.task_done()

def load_queue_from_disk(msg_queue, state):
    """Runs once on startup to grab any pending messages off the disk and put them back into memory."""
    if not os.path.exists(state.smtp["queue_dir"]):
        return
    for filename in os.listdir(state.smtp["queue_dir"]):
        if filename.endswith(".json"):
            filepath = os.path.join(state.smtp["queue_dir"], filename)
            try:
                with open(filepath, 'r') as f:
                    msg_queue.put(json.load(f))
            except Exception as e:
                logging.error(f"Failed to load queued file {filepath}: {e}")

def load_config(is_reload=False):
    """
    Loads and merges the GATEWAY_CONFIG JSON.
    Returns a populated GatewayState object. If is_reload is False (i.e. startup),
    any severe validation failures will cause the script to exit.
    """
    raw_env = os.environ.get("GATEWAY_CONFIG")
    if not raw_env:
        logging.error("Environment variable GATEWAY_CONFIG is not set.")
        if not is_reload: exit(1)
        return None

    # ENFORCEMENT: We now require a strict file path for proper UI interaction.
    file_path = os.path.normpath(os.path.join(SCRIPT_DIR, raw_env.strip()))
    if not os.path.isfile(file_path):
        logging.error(f"GATEWAY_CONFIG must point to a valid file path. File not found: {file_path}")
        if not is_reload: exit(1)
        return None

    try:
        with open(file_path, 'r') as f:
            json_str = f.read()
    except Exception as e:
        logging.error(f"Failed to read GATEWAY_CONFIG file '{file_path}': {e}")
        if not is_reload: exit(1)
        return None

    # Load the JSON Vault to swap out API token aliases securely
    vault_file = os.environ.get("VAULT_FILE", os.path.join(SCRIPT_DIR, "vault.json"))
    vault_data = {"app": {}, "user": {}, "smarthost": {}}
    if os.path.exists(vault_file):
        try:
            with open(vault_file, 'r') as f:
                raw_v = json.load(f)
                # Handle seamless migration from legacy flat vault arrays dynamically
                if "app" not in raw_v and "user" not in raw_v:
                    vault_data["app"] = raw_v
                else:
                    vault_data = {
                        "app": raw_v.get("app", {}),
                        "user": raw_v.get("user", {}),
                        "smarthost": raw_v.get("smarthost", {})
                    }
        except Exception as e:
            logging.warning(f"Could not load vault file {vault_file}: {e}")

    # --- Strip Comments Safely ---
    # Strip block comments /* ... */ at the start of the string or preceded by whitespace
    json_str = re.sub(r'(^|\s)/\*.*?\*/', r'\1', json_str, flags=re.DOTALL)
    # Strip line comments // and # at the start of the string or preceded by whitespace
    json_str = re.sub(r'(^|\s)(//|#).*', r'\1', json_str)

    try:
        config_root = json.loads(json_str)

        # Transparent Migration: Dynamically restructure legacy schema elements into the new multi-routing format
        if "routes" not in config_root:
            config_root["routes"] = {}
            reserved_keys = ["user", "token", "device", "sound", "url", "url_title", "tags", "priority", "ttl", "retry", "expire", "attachments", "force_plaintext", "disable_persistence"]
            po = config_root.get("pushover", {})
            to_del = []
            for k, v in po.items():
                if k not in reserved_keys and isinstance(v, dict):
                    v["method"] = "pushover"
                    config_root["routes"][k] = v
                    to_del.append(k)
            for k in to_del: del po[k]

        if "disable_persistence" in config_root.get("pushover", {}):
            if "smtp" not in config_root: config_root["smtp"] = {}
            config_root["smtp"]["disable_persistence"] = config_root["pushover"]["disable_persistence"]
            del config_root["pushover"]["disable_persistence"]

        smtp_json = config_root.get("smtp", {})
        pushover_json = config_root.get("pushover", {})
        smarthost_json = config_root.get("smarthost", {"aliases": {}, "globals": {}})
        routes_json = config_root.get("routes", {})

        new_state = GatewayState()
        new_state.config_file = file_path
        new_state.vault = vault_data

        # 1. Parse and Merge SMTP Infrastructure Settings from JSON
        new_state.smtp = {
            "default_route": smtp_json.get("default_route", "pushover"),
            "disable_persistence": get_bool(smtp_json.get("disable_persistence", False)),
            "auth": smtp_json.get("auth", {}),
            "queue_dir": smtp_json.get("queue_dir", "queue"),
            "hostname": smtp_json.get("hostname"),
            "tls_cert_file": smtp_json.get("tls_cert_file"),
            "tls_key_file": smtp_json.get("tls_key_file"),
            "max_retry_backoff": int(smtp_json.get("max_retry_backoff", 21600)),
            "loglevel": smtp_json.get("loglevel", "INFO").upper()
        }

        # Parse listener definitions
        listeners = smtp_json.get("listeners")
        if not isinstance(listeners, list) or len(listeners) == 0:
            listeners = [{"bind": "0.0.0.0:25", "starttls": False}]

        # Clean listener inputs
        for l in listeners:
            l["bind"] = l.get("bind", "0.0.0.0:25")
            l["starttls"] = get_bool(l.get("starttls"))
            if "hostname" in l and str(l["hostname"]).strip():
                l["hostname"] = str(l["hostname"]).strip()
            # Inherit global TLS files if starttls is enabled and local configs are missing
            if l["starttls"]:
                l["tls_cert_file"] = l.get("tls_cert_file", new_state.smtp.get("tls_cert_file"))
                l["tls_key_file"] = l.get("tls_key_file", new_state.smtp.get("tls_key_file"))

        new_state.smtp["listeners"] = listeners
        new_state.smtp["queue_dir"] = os.path.normpath(os.path.join(SCRIPT_DIR, new_state.smtp["queue_dir"]))

        # 2. Parse Smarthost Configurations
        new_state.smarthost = {
            "aliases": {},
            "globals": {
                "alias": smarthost_json.get("globals", {}).get("alias"),
                "force_plaintext": get_bool(smarthost_json.get("globals", {}).get("force_plaintext", False)),
                "disable_attachments": get_bool(smarthost_json.get("globals", {}).get("disable_attachments", False))
            }
        }

        for alias, sh in smarthost_json.get("aliases", {}).items():
            new_state.smarthost["aliases"][alias] = {
                "hostname": sh.get("hostname", ""),
                "port": int(sh.get("port", 25)),
                "advertised_hostname": sh.get("advertised_hostname", ""),
                "starttls": get_bool(sh.get("starttls")),
                "disable_tls_validation": get_bool(sh.get("disable_tls_validation")),
                "auth": get_bool(sh.get("auth")),
                "username": sh.get("username", ""),
                "disable_attachments": get_bool(sh.get("disable_attachments")),
                "force_plaintext": get_bool(sh.get("force_plaintext")),
            }

        # Check for global aliases and perform dynamic Vault substitution mapped across both legacy flat and explicit structures
        global_user = pushover_json.get("user")
        if global_user: global_user = vault_data["user"].get(global_user, vault_data["app"].get(global_user, global_user))

        global_token = pushover_json.get("token")
        if global_token: global_token = vault_data["app"].get(global_token, global_token)

        # 3. Parse and Merge Global Pushover Settings
        new_state.pushover = {
            "method": "pushover",
            "user": global_user,
            "token": global_token,
            "device": pushover_json.get("device"),
            "sound": pushover_json.get("sound"),
            "url": pushover_json.get("url"),
            "url_title": pushover_json.get("url_title"),
            "tags": pushover_json.get("tags"),
            "priority": pushover_json.get("priority"),
            "ttl": pushover_json.get("ttl"),
            "retry": pushover_json.get("retry"),
            "expire": pushover_json.get("expire"),
            "attachments": get_bool(pushover_json.get("attachments", True)),
            "force_plaintext": get_bool(pushover_json.get("force_plaintext"))
        }

        # Cast and validate global integers securely
        for int_param in ["priority", "ttl", "retry", "expire"]:
            val = new_state.pushover.get(int_param)
            if val is not None and str(val).strip():
                try:
                    new_state.pushover[int_param] = int(val)
                except ValueError:
                    logging.warning(f"Invalid global integer '{val}' for {int_param}. Ignored.")
                    new_state.pushover[int_param] = None

        if new_state.pushover.get("priority") == 2:
            r_val = new_state.pushover.get("retry")
            e_val = new_state.pushover.get("expire")
            if r_val is None or e_val is None or r_val < 30 or e_val > 10800:
                logging.error("Global priority is 2, but valid 'retry' (>=30) and 'expire' (<=10800) are not properly defined.")
                if not is_reload: exit(1)
                return None

        # Validate Global String Constraints
        if new_state.pushover.get("url") and len(new_state.pushover["url"]) > MAX_URL_CHARS:
            logging.warning(f"Validation Warning: Global 'url' exceeds {MAX_URL_CHARS} characters. It will be truncated when sending.")
        if new_state.pushover.get("url_title") and len(new_state.pushover["url_title"]) > MAX_URL_TITLE_CHARS:
            logging.warning(f"Validation Warning: Global 'url_title' exceeds {MAX_URL_TITLE_CHARS} characters. It will be truncated when sending.")

        # 4. Parse Email Address Routing Mappings
        for key, config in routes_json.items():
            if not isinstance(config, dict): continue

            match_type = config.get("match", "to").lower()
            if match_type not in ("to", "from", "both"):
                logging.error(f"Validation Failed: Configuration entry '{key}' has invalid match rule '{match_type}'. Ignored.")
                continue

            method = config.get("method", "pushover")
            route_config = {"method": method}

            if method == "smarthost":
                route_config["smarthost_alias"] = config.get("smarthost_alias")
                if "force_plaintext" in config:
                    route_config["force_plaintext"] = get_bool(config["force_plaintext"])
                if "disable_attachments" in config:
                    route_config["disable_attachments"] = get_bool(config["disable_attachments"])
            else:
                # Route-level Alias Vault translation dynamically catching legacy and nested scopes
                user_key = config.get("user")
                if user_key:
                    user_key = vault_data["user"].get(user_key, vault_data["app"].get(user_key, user_key))
                else:
                    user_key = new_state.pushover.get("user")

                app_token = config.get("token")
                if app_token:
                    app_token = vault_data["app"].get(app_token, app_token)

                if not user_key or not app_token:
                    logging.error(f"Missing required 'user' or 'token' definitions for address: {key}. Ignored.")
                    continue

                route_config["user"] = user_key
                route_config["token"] = app_token

                if "force_plaintext" in config:
                    route_config["force_plaintext"] = get_bool(config["force_plaintext"])
                if "attachments" in config:
                    route_config["attachments"] = get_bool(config["attachments"])

                for string_param in ["device", "sound", "url", "url_title", "tags"]:
                    val = config.get(string_param, new_state.pushover.get(string_param))
                    if val and str(val).strip(): route_config[string_param] = str(val).strip()

                if "url" in route_config and len(route_config["url"]) > MAX_URL_CHARS:
                    logging.warning(f"Validation Warning: Route '{key}' 'url' exceeds {MAX_URL_CHARS} characters. It will be truncated when sending.")
                if "url_title" in route_config and len(route_config["url_title"]) > MAX_URL_TITLE_CHARS:
                    logging.warning(f"Validation Warning: Route '{key}' 'url_title' exceeds {MAX_URL_TITLE_CHARS} characters. It will be truncated when sending.")

                for int_param in ["priority", "ttl", "retry", "expire"]:
                    val = config.get(int_param, new_state.pushover.get(int_param))
                    if val is not None and str(val).strip():
                        try:
                            parsed_val = int(val)
                            if int_param == "priority" and not (-2 <= parsed_val <= 2): continue
                            if int_param == "retry" and parsed_val < 30: continue
                            if int_param == "expire" and parsed_val > 10800: continue
                            route_config[int_param] = parsed_val
                        except ValueError: pass

                if route_config.get("priority") == 2 and ("retry" not in route_config or "expire" not in route_config):
                    logging.error(f"Validation Failed: Route '{key}' has priority 2 but is missing valid 'retry' or 'expire'. Ignored.")
                    continue

            is_regex = False
            email_key = key

            if key.lower().startswith("regex:"):
                is_regex = True
                pattern_str = key[6:].strip()
                try:
                    compiled_pattern = re.compile(pattern_str, re.IGNORECASE)
                except re.error as e:
                    logging.error(f"Invalid regex pattern '{pattern_str}' for key '{key}': {e}. Ignored.")
                    continue
            else:
                email_key = key.lower()

            if is_regex:
                if match_type in ("to", "both"): new_state.regex_mappings["to"].append((compiled_pattern, route_config))
                if match_type in ("from", "both"): new_state.regex_mappings["from"].append((compiled_pattern, route_config))
            else:
                if match_type in ("to", "both"): new_state.mappings["to"][email_key] = route_config
                if match_type in ("from", "both"): new_state.mappings["from"][email_key] = route_config

        has_mappings = bool(new_state.mappings["to"] or new_state.mappings["from"] or new_state.regex_mappings["to"] or new_state.regex_mappings["from"])

        # Ensure we have at least *some* viable configuration before returning success
        if not has_mappings:
            if new_state.smtp["default_route"] == "pushover" and not (new_state.pushover.get("user") and new_state.pushover.get("token")):
                logging.error("No valid email routing matrices survived validation, and no global Pushover catch-all is defined.")
                if not is_reload: exit(1)
                return None
            elif new_state.smtp["default_route"] == "smarthost" and not new_state.smarthost["globals"].get("alias"):
                logging.error("No valid email routing matrices survived validation, and no global Smarthost catch-all is defined.")
                if not is_reload: exit(1)
                return None

        return new_state

    except json.JSONDecodeError as e:
        logging.error(f"Failed to parse GATEWAY_CONFIG JSON contents: {e}")
        if not is_reload: exit(1)
        return None

def file_contains_private_key(filepath):
    """Checks if a file contains standard PEM private key boundaries."""
    try:
        with open(filepath, 'r') as f:
            content = f.read()
            return "PRIVATE KEY-----" in content
    except Exception:
        return False

def get_tls_context(listener_conf, fallback_hostname):
    """Sets up the SSL context based on config vars, handles overloads, or generates fallback certs."""
    if not listener_conf.get("starttls"):
        return None

    cert_file = listener_conf.get("tls_cert_file")
    key_file = listener_conf.get("tls_key_file")
    cert_has_key = False

    # Check if a provided certificate file already contains its own private key
    if cert_file and os.path.isfile(cert_file) and os.access(cert_file, os.R_OK):
        cert_has_key = file_contains_private_key(cert_file)

    if cert_has_key and key_file:
        logging.warning("Both a combined TLS_CERT_FILE and separate TLS_KEY_FILE were specified. Cert takes precedence.")
        key_file = None

    files_ok = False
    if cert_file and os.path.isfile(cert_file) and os.access(cert_file, os.R_OK):
        if cert_has_key or (key_file and os.path.isfile(key_file) and os.access(key_file, os.R_OK)):
            files_ok = True

    # If the user requested TLS but provided bad or no files, we safely generate our own to satisfy the requirement
    if not files_ok:
        hostname = fallback_hostname or str(uuid.uuid4())
        bind_address = listener_conf.get("bind", "0.0.0.0:25")
        cert_file, key_file = generate_secp384r1_cert(hostname, bind_address)

    tls_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    tls_context.load_cert_chain(certfile=cert_file, keyfile=key_file)
    return tls_context

def generate_secp384r1_cert(hostname, bind_address):
    """Generates a self-signed secp384r1 TLS certificate and writes it to temporary files."""
    safe_bind = bind_address.replace(":", "_")
    cert_path = f"/tmp/smtp_pushover_cert_{safe_bind}.pem"
    key_path = f"/tmp/smtp_pushover_key_{safe_bind}.pem"

    # Skip regeneration if fallback files matching this bind already exist AND match the requested hostname
    if os.path.exists(cert_path) and os.path.exists(key_path):
        try:
            with open(cert_path, "rb") as f:
                existing_cert = x509.load_pem_x509_certificate(f.read())
                cn_attributes = existing_cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
                if cn_attributes and cn_attributes[0].value == hostname:
                    return cert_path, key_path
        except Exception as e:
            logging.debug(f"Failed to parse existing fallback cert for {bind_address}: {e}")

    logging.warning(f"Generating self-signed secp384r1 fallback cert for {hostname} on {bind_address}...")
    private_key = ec.generate_private_key(ec.SECP384R1())
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = x509.CertificateBuilder().subject_name(subject).issuer_name(issuer).public_key(
        private_key.public_key()
    ).serial_number(x509.random_serial_number()).not_valid_before(now).not_valid_after(
        now + datetime.timedelta(days=365)
    ).add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False).sign(private_key, hashes.SHA256())

    with open(key_path, "wb") as f:
        f.write(private_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path

def apply_logging_level(loglevel_str):
    """Applies the configured log level to the main script and dynamically throttles aiosmtpd chatter."""
    log_level = getattr(logging, loglevel_str, logging.INFO)

    # 1. Update the Root Logger (Gate 1)
    logging.getLogger().setLevel(log_level)

    # 2. Update ALL attached Handlers (Gate 2) to prevent third-party lock-out
    for handler in logging.getLogger().handlers:
        handler.setLevel(log_level)

    # Suppress verbose aiosmtpd TCP connection logging unless explicitly debugging
    if log_level > logging.DEBUG:
        aiosmtpd_logger.setLevel(logging.WARNING)
    else:
        aiosmtpd_logger.setLevel(logging.DEBUG)

def get_listen_params(listen_str):
    """Extracts the IP address and port from the 'listen' config string."""
    if ":" in listen_str:
        address, port = listen_str.rsplit(":", 1)
        return address, int(port)
    # Fallback to port 25 if the user only specified an IP
    return listen_str, 25

def get_file_hash(filepath):
    """Safely computes the SHA256 hash of a file for exact modification detection."""
    if not filepath or not os.path.exists(filepath):
        return ""
    try:
        with open(filepath, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()
    except Exception:
        return ""

def sig_handler(signum, frame):
    """Handles OS signals by setting thread-safe events to be caught in the main execution loop."""
    if signum in (signal.SIGINT, signal.SIGTERM):
        logging.info(f"Received signal {signum}. Initiating shutdown...")
        shutdown_event.set()
    elif hasattr(signal, 'SIGUSR1') and signum == signal.SIGUSR1:
        logging.info("Received SIGUSR1. Scheduling TCP listener and TLS reload...")
        reload_event.set()
    elif hasattr(signal, 'SIGUSR2') and signum == signal.SIGUSR2:
        logging.info("Received SIGUSR2. Scheduling full configuration reload...")
        mappings_reload_event.set()

if __name__ == "__main__":
    # Register OS Signal Handlers
    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)
    if hasattr(signal, 'SIGUSR1'): signal.signal(signal.SIGUSR1, sig_handler)
    if hasattr(signal, 'SIGUSR2'): signal.signal(signal.SIGUSR2, sig_handler)

    # Write PID for UI sidecar to hook into
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))

    # 1. Parse unified state configuration and apply side-effects
    app_state = load_config(is_reload=False)
    apply_logging_level(app_state.smtp["loglevel"])
    os.makedirs(app_state.smtp["queue_dir"], exist_ok=True)

    auth_status = "Enabled" if app_state.smtp.get("auth") else "Disabled (Permissive)"
    total_mapped = len(app_state.mappings["to"]) + len(app_state.mappings["from"]) + len(app_state.regex_mappings["to"]) + len(app_state.regex_mappings["from"])
    logging.info(f"Loaded config from file '{app_state.config_file}'. Explicit rules: {total_mapped}. Global Routing Method: {app_state.smtp['default_route']}. SMTP Auth: {auth_status}")

    # 2. Setup thread-safe queue and retrieve un-sent disk persistence items
    msg_queue = queue.Queue()
    load_queue_from_disk(msg_queue, app_state)

    # 3. Start the background Delivery worker thread
    worker_thread = threading.Thread(target=delivery_worker, args=(msg_queue, app_state), daemon=True)
    worker_thread.start()

    # 4. Configure and spin up the aiosmtpd listener(s)
    handler = PushoverSMTPHandler(app_state, msg_queue)
    authenticator = GatewayAuthenticator(app_state)

    # Tracks currently active listener state for intelligent selective diffing on SIGUSR1
    active_controllers = {}

    for l_conf in app_state.smtp["listeners"]:
        bind = l_conf["bind"]
        listen_address, listen_port = get_listen_params(bind)
        eff_hostname = l_conf.get("hostname", app_state.smtp.get("hostname"))

        tls_context = get_tls_context(l_conf, eff_hostname)
        # Passing authenticator handles built-in ESMTP auth advertisement automatically
        ctrl = GatewayController(
            handler, hostname=listen_address, port=listen_port, server_hostname=eff_hostname,
            tls_context=tls_context, authenticator=authenticator, auth_require_tls=False
        )
        ctrl.start()

        active_controllers[bind] = {
            "controller": ctrl,
            "config": {
                "hostname": eff_hostname,
                "starttls": l_conf.get("starttls", False),
                "tls_cert_file": l_conf.get("tls_cert_file"),
                "tls_key_file": l_conf.get("tls_key_file"),
                "cert_hash": get_file_hash(l_conf.get("tls_cert_file")),
                "key_hash": get_file_hash(l_conf.get("tls_key_file"))
            }
        }
        starttls_status = "enabled" if tls_context else "disabled"
        logging.info(f"Starting SMTP server on {listen_address}:{listen_port} (STARTTLS: {starttls_status}, Hostname: {eff_hostname})")

    try:
        # 5. Enter main loop to monitor for OS signals
        while not shutdown_event.is_set():

            # TCP Listener / TLS Hot-Reload (SIGUSR1)
            if reload_event.is_set():
                reload_event.clear()
                logging.info("Checking listeners for dynamic network or TLS modifications...")

                current_binds = set(active_controllers.keys())
                new_binds = set(l["bind"] for l in app_state.smtp["listeners"])

                # 1. Gracefully shut down any binds removed from the configuration entirely
                for bind in current_binds - new_binds:
                    logging.info(f"Removing deprecated listener on {bind}...")
                    active_controllers[bind]["controller"].stop()
                    del active_controllers[bind]

                # 2. Iterate through requested binds, comparing effective configurations for diffs
                for l_conf in app_state.smtp["listeners"]:
                    bind = l_conf["bind"]
                    eff_hostname = l_conf.get("hostname", app_state.smtp.get("hostname"))
                    eff_cert = l_conf.get("tls_cert_file")
                    eff_key = l_conf.get("tls_key_file")

                    eff_config = {
                        "hostname": eff_hostname,
                        "starttls": l_conf.get("starttls", False),
                        "tls_cert_file": eff_cert,
                        "tls_key_file": eff_key,
                        "cert_hash": get_file_hash(eff_cert),
                        "key_hash": get_file_hash(eff_key)
                    }

                    needs_restart = False
                    if bind not in active_controllers:
                        logging.info(f"New listener declaration discovered for {bind}. Starting...")
                        needs_restart = True
                    else:
                        if active_controllers[bind]["config"] != eff_config:
                            logging.info(f"Configuration or TLS modification detected for {bind}. Restarting listener...")
                            active_controllers[bind]["controller"].stop()
                            needs_restart = True

                    if needs_restart:
                        listen_address, listen_port = get_listen_params(bind)
                        tls_context = get_tls_context(l_conf, eff_hostname)

                        ctrl = GatewayController(
                            handler, hostname=listen_address, port=listen_port, server_hostname=eff_hostname,
                            tls_context=tls_context, authenticator=authenticator, auth_require_tls=False
                        )
                        ctrl.start()
                        active_controllers[bind] = {"controller": ctrl, "config": eff_config}

                        starttls_status = "enabled" if tls_context else "disabled"
                        logging.info(f"Listener {bind} hot-reload complete (STARTTLS: {starttls_status}, Hostname: {eff_hostname}).")

            # Full Config Data Hot-Reload (SIGUSR2)
            if mappings_reload_event.is_set():
                mappings_reload_event.clear()
                if app_state.config_file:
                    logging.info(f"Reloading gateway configurations from file '{app_state.config_file}'...")
                    new_state = load_config(is_reload=True)
                    if new_state is not None:
                        # Atomically mutate the active state container objects so running threads aren't corrupted
                        app_state.smtp.clear(); app_state.smtp.update(new_state.smtp)
                        app_state.pushover.clear(); app_state.pushover.update(new_state.pushover)
                        app_state.smarthost.clear(); app_state.smarthost.update(new_state.smarthost)
                        app_state.mappings.clear(); app_state.mappings.update(new_state.mappings)
                        app_state.regex_mappings.clear(); app_state.regex_mappings.update(new_state.regex_mappings)
                        app_state.vault.clear(); app_state.vault.update(new_state.vault)

                        # Apply immediate dynamic system effects
                        apply_logging_level(app_state.smtp["loglevel"])
                        os.makedirs(app_state.smtp["queue_dir"], exist_ok=True)

                        new_auth_status = "Enabled" if app_state.smtp.get("auth") else "Disabled (Permissive)"
                        new_total = len(app_state.mappings["to"]) + len(app_state.mappings["from"]) + len(app_state.regex_mappings["to"]) + len(app_state.regex_mappings["from"])

                        logging.info(f"Reload success. Mappings tracked: {new_total}. Global Routing Method: {app_state.smtp['default_route']}. SMTP Auth: {new_auth_status}")
                        logging.info("Note: Changes to listener endpoints or TLS settings require a SIGUSR1 to take effect.")
                    else:
                        logging.warning("Config reload failed. Retaining active rules matrix.")

            # Pause briefly to prevent the while loop from maxing out the CPU
            shutdown_event.wait(1.0)

    except KeyboardInterrupt:
        # Fallback if standard keyboard interrupt fires before the signal handler intercepts it
        logging.info("Keyboard interrupt received.")
    finally:
        logging.info("Shutting down... Flashing queues to disk safely...")
        for data in active_controllers.values():
            data["controller"].stop()

        # Inject the None payload to signal the worker thread to break its loop
        msg_queue.put(None)
        worker_thread.join()

        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)

        logging.info("Shutdown complete.")
