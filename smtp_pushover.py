#!/usr/bin/env python3
"""
SMTP to Pushover Notification Gateway (Threaded with Disk Persistence & Signal Handling)

================================================================================
OS PACKAGE REQUIREMENTS
================================================================================

Debian 13 (Trixie):
    $ sudo apt-get update
    $ sudo apt-get install python3 python3-pip python3-requests python3-cryptography python3-aiosmtpd python3-passlib

Alpine Linux:
    $ apk update
    $ apk add python3 py3-pip py3-requests py3-cryptography py3-aiosmtpd py3-passlib

If native packages are missing, use pip (or a virtual environment):
    $ pip install aiosmtpd requests cryptography passlib

================================================================================
ENVIRONMENT VARIABLES & JSON CONFIGURATION
================================================================================

GATEWAY_CONFIG (Required):
    Can be configured as an inline JSON string OR as a relative/absolute file path
    pointing to a valid JSON configuration file (e.g., 'config.json').

    *NOTE:* This parser supports inline comments as long as they are at the beginning
    of a line, or preceded by at least one whitespace character.
    Supported formats: `// comment`, `# comment`, `/* comment */`.

    This object contains two distinct operational layers:

    1. "pushover" (Required):
       Coordinates routing logic and Pushover API token sets.
       - Root-level "user", "token", and optional formatting parameters ("device",
         "sound", "url", "url_title", "priority", "ttl") establish a global fallback state.
       - If an email hits an unmapped address, it acts as a Catch-All using these
         global API keys. If a global "token" is omitted, unmapped addresses are dropped.
       - Root-level "force_plaintext" (bool) sets a global preference for skipping HTML payloads.
       - Root-level "disable_persistence" (bool) disables writing payloads to the disk queue.
       - Email routing objects accept an optional "user" (to target different accounts),
         a required "token" (to target different Pushover apps), and optional formatting overrides.
       - Optional formatting keys for Pushover payload:
           * "device": string (target specific devices)
           * "sound": string (override default alert sound)
           * "url": string (supplementary URL to attach)
           * "url_title": string (title for the supplementary URL)
           * "priority": int (between -2 and 2)
           * "ttl": int (time to live in seconds)
       - Email routing objects support a "match" filter key:
           * "to" (Default): Matches when the key is found in the email recipients.
           * "from": Matches when the key is the email's envelope sender.
           * "both": Triggers if the address is present as either the sender or receiver.
       - Regex Routing: Prefix a routing key with "regex:" to evaluate it as a regular
         expression instead of an exact string match (e.g., "regex:.*@domain\\.com$").

    2. "smtp" (Optional):
       Configures the infrastructure, logging, TLS, and client authentication.
       - "auth": A dictionary mapping SMTP authentication usernames to passwords.
         Passwords can be raw strings or standard Linux modular crypt hashes ($5$, $6$).
         If "auth" is omitted or empty, permissive access is granted to all clients.
       - "listeners": A list of endpoint objects to bind the SMTP server to.
           * "bind": Address and port (e.g., "0.0.0.0:25")
           * "hostname": Optional string overriding the global SMTP greeting banner for this specific endpoint.
           * "starttls": Boolean to enable STARTTLS support on this listener.
           * "tls_cert_file": Path to PEM certificate (can contain private key).
           * "tls_key_file": Path to private key file.
       - "queue_dir": Path to store messages on disk.
       - "hostname": Common Name (CN) for fallback self-signed TLS certificates and global SMTP greeting.
       - "tls_cert_file": Global fallback Path to PEM certificate for all listeners.
       - "tls_key_file": Global fallback Path to private key file for all listeners.
       - "max_retry_backoff": Max seconds to wait during exponential retries.
       - "loglevel": Logging verbosity (DEBUG, INFO, WARNING, ERROR).

    ----------------------------------------------------------------------------
    GATEWAY_CONFIG EXAMPLE:
    ----------------------------------------------------------------------------
    {
      "pushover": {
        "user": "GLOBAL_PUSHOVER_USER_KEY",
        "token": "GLOBAL_CATCH_ALL_APP_TOKEN",
        "force_plaintext": true,
        "disable_persistence": false,
        "sound": "magic",
        "buddy@example.com": {
          "match": "to",
          "token": "APP_SPECIFIC_TOKEN_A",
          "device": "buddys_iphone",
          "priority": 1
        },
        "regex:^server-(alpha|beta|gamma)@local\\.lan$": {
          "match": "from",
          "token": "APP_SPECIFIC_TOKEN_B",
          "priority": 2,
          "sound": "siren"
        }
      },
      "smtp": {
        "auth": {
          "rocky": "plaintext_password_123",
          "bella": "$5$rounds=5000$staticsaltstring$UoK8w6yQ61VvG3V..."
        },
        "tls_cert_file": "/etc/ssl/certs/global.pem",
        "tls_key_file": "/etc/ssl/private/global.key",
        "listeners": [
          {
            "bind": "0.0.0.0:25"
          },
          {
            "bind": "0.0.0.0:587",
            "hostname": "secure.gateway.local",
            "starttls": true,
            "tls_cert_file": "/etc/ssl/certs/custom.pem",
            "tls_key_file": "/etc/ssl/private/custom.key"
          }
        ],
        "queue_dir": "/tmp/queue",
        "hostname": "gateway.local",
        "max_retry_backoff": 21600,
        "loglevel": "info"
      }
    }

ENVIRONMENT VARIABLE OVERRIDES:
    Any infrastructure setting defined in the "smtp" JSON block, as well as the global
    "force_plaintext" and "disable_persistence" settings, can be explicitly overridden
    by defining the corresponding OS environment variable. Environment variables always
    take precedence.
    - QUEUE_DIR
    - LISTEN (Overrides the listeners list to a single endpoint)
    - STARTTLS
    - TLS_CERT_FILE
    - TLS_KEY_FILE
    - HOSTNAME
    - FORCE_PLAINTEXT
    - DISABLE_PERSISTENCE
    - MAX_RETRY_BACKOFF
    - LOGLEVEL

================================================================================
SIGNALS
================================================================================
SIGINT / SIGTERM: Gracefully shuts down the SMTP listener and waits for queue to empty.
SIGUSR1: Atomically diffs and restarts SMTP listeners if their configs/certs have changed.
SIGUSR2: Reloads GATEWAY_CONFIG from disk (only works if configured as a file path).
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

# External HTTP request handling
import requests

# Email parsing libraries to tear down incoming SMTP data blocks
from email import message_from_bytes, policy
from email.utils import parsedate_to_datetime
from aiosmtpd.controller import Controller

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

# Global threading events used by OS signal handlers to safely communicate with the main loop
shutdown_event = threading.Event()
reload_event = threading.Event()
mappings_reload_event = threading.Event()


class GatewayState:
    """
    A thread-safe container to hold the application's configuration state.
    By storing everything here, we can atomically swap out configurations
    during a SIGUSR2 hot-reload without crashing active connections.
    """
    def __init__(self):
        self.smtp = {}
        self.pushover = {}
        self.mappings = {"to": {}, "from": {}}
        self.regex_mappings = {"to": [], "from": []}
        self.config_file = None


def get_bool(val, default=False):
    """Safely coerces strings, ints, or booleans from JSON/EnvVars into a Python boolean."""
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
    """Verifies a plain text password against a stored entry (which can be plain or a crypt hash)."""
    if not stored_value:
        return False

    # If it starts with a dollar sign, it's a Linux crypt hash (e.g., $5$ for SHA-256)
    if str(stored_value).startswith("$"):
        if HAS_PASSLIB:
            try:
                if stored_value.startswith("$5$"):
                    return sha256_crypt.verify(plain_password, stored_value)
                elif stored_value.startswith("$6$"):
                    return sha512_crypt.verify(plain_password, stored_value)
                elif stored_value.startswith("$1$"):
                    return md5_crypt.verify(plain_password, stored_value)
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
            # Parse the raw email bytes into a structured Python object
            msg = message_from_bytes(envelope.content, policy=policy.default)

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

            # 1. Extract raw payloads from the email structure
            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    content_disposition = str(part.get("Content-Disposition"))

                    # We don't want to try and parse binary attachments as text
                    if "attachment" in content_disposition:
                        continue

                    if content_type == "text/plain":
                        plain_body_raw = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors='replace')
                    elif content_type == "text/html":
                        html_body_raw = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors='replace')
            else:
                # Handle single-part emails that don't have boundaries
                raw_payload = msg.get_payload(decode=True).decode(msg.get_content_charset() or 'utf-8', errors='replace')
                if msg.get_content_type() == "text/html":
                    html_body_raw = raw_payload
                else:
                    plain_body_raw = raw_payload

            # 2. Pre-process formats for fast contextual assignment later
            body_html_processed = None
            if html_body_raw:
                # Pushover translates ALL newlines into <br> tags. To prevent massive gaps,
                # we must behave like a web browser: strip literal whitespace and rely on structural HTML tags.

                # Strip all literal source-code newlines and tabs
                processed = re.sub(r'[\r\n\t]+', ' ', html_body_raw)

                # Erase entire blocks (and their contents) that contain metadata/CSS/scripts so they don't render as text
                processed = re.sub(r'<(style|script|head|title)[^>]*>.*?</\1>', '', processed, flags=re.IGNORECASE)

                # Translate structural HTML layout tags into literal newlines for Pushover to understand
                processed = re.sub(r'<br\s*/?>', '\n', processed, flags=re.IGNORECASE)
                processed = re.sub(r'</(p|div|tr|h[1-6]|li|table)>', '\n\n', processed, flags=re.IGNORECASE)
                processed = re.sub(r'<hr[^>]*>', '\n---\n', processed, flags=re.IGNORECASE)

                # Strip all HTML tags EXCEPT the specific formatting tags Pushover actually supports
                processed = re.sub(r'<(?!/?(a|b|i|u|font)\b)[^>]+>', '', processed, flags=re.IGNORECASE)

                # Clean up excess whitespace and consecutive blank lines left behind by deleted tags
                processed = re.sub(r' {2,}', ' ', processed)
                processed = re.sub(r' ?\n ?', '\n', processed)
                body_html_processed = re.sub(r'\n{3,}', '\n\n', processed).strip()

            body_plain_processed = None
            if plain_body_raw:
                # For plain text, simply collapse 3+ consecutive newlines into exactly 2 (a single blank line)
                body_plain_processed = re.sub(r'(\r?\n[ \t]*){3,}', '\n\n', plain_body_raw).strip()

            # 3. Match Routes
            # We determine who gets the notification based on the sender or recipients
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

            # If nobody matched, check if the global fallback catch-all is configured
            if not routes_to_trigger:
                if self.state.pushover.get("user") and self.state.pushover.get("token"):
                    logging.info("No explicit from/to mappings matched. Falling back to global catch-all.")
                    routes_to_trigger.append(self.state.pushover)
                else:
                    logging.info("No explicit from/to mappings matched and no global catch-all defined. Ignoring message.")

            # Deduplicate Routes
            # If an email matches both a 'from' and a 'to' mapping pointing to the same token, don't spam the user twice.
            unique_routes = []
            seen_combinations = set()
            for route in routes_to_trigger:
                combo_hash = f"{route['user']}:{route['token']}"
                if combo_hash not in seen_combinations:
                    seen_combinations.add(combo_hash)
                    unique_routes.append(route)

            # 4. Contextual Formatting & Queuing
            for route in unique_routes:
                # Prioritize route-specific flags, fallback to the global setting
                force_pt = route.get("force_plaintext", self.state.pushover.get("force_plaintext", False))
                disable_persist = route.get("disable_persistence", self.state.pushover.get("disable_persistence", False))

                # Determine which pre-processed body format this specific route should get
                if not force_pt and body_html_processed is not None:
                    final_body = body_html_processed
                    is_html = True
                elif body_plain_processed is not None:
                    final_body = body_plain_processed
                    is_html = False
                else:
                    final_body = "(No message body)"
                    is_html = False

                # Build the base payload dictionary
                payload = {
                    "id": uuid.uuid4().hex,
                    "user": route["user"],
                    "token": route["token"],
                    "message": final_body,
                    "title": title,
                    "timestamp": timestamp,
                    "is_html": is_html,
                    "disable_persistence": disable_persist,
                    "retry_count": 0
                }

                # Pass optional configuration constraints along if they exist for this route
                for param in ["device", "sound", "priority", "ttl"]:
                    if param in route:
                        payload[param] = route[param]

                # Ensure dynamic API length limits are applied contextually before queuing
                if "url" in route:
                    payload["url"] = route["url"][:MAX_URL_CHARS]
                if "url_title" in route:
                    payload["url_title"] = route["url_title"][:MAX_URL_TITLE_CHARS]

                # Step 1: Save it to disk for crash resilience (unless persistence is disabled)
                if not disable_persist:
                    filepath = os.path.join(self.state.smtp["queue_dir"], f"{payload['id']}.json")
                    with open(filepath, 'w') as f:
                        json.dump(payload, f)

                # Step 2: Queue it into memory for the background worker to pick up
                self.msg_queue.put(payload)
                logging.debug(f"Queued notification payload (ID: {payload['id']}, HTML: {is_html}, Persistent: {not disable_persist})")

            # Always return a 250 OK to the SMTP client so it stops trying to send the email
            return '250 Message accepted for delivery'
        except Exception as e:
            logging.error(f"Error processing email: {e}", exc_info=True)
            return '500 Internal Server Error'


def pushover_worker(msg_queue, state):
    """
    Background worker thread running continuously.
    Pops messages off the memory queue and sends them to the Pushover API.
    Handles exponential backoff if the API is down or rate-limited.
    """
    logging.debug("Pushover worker thread started.")
    while True:
        # Blocks here until an item is available in the queue
        payload = msg_queue.get()

        # A payload of None is our signal from the main thread to shut down cleanly
        if payload is None:
            msg_queue.task_done()
            break

        api_payload = {
            "token": payload["token"],
            "user": payload["user"],
            "message": payload["message"],
            "title": payload["title"],
            "timestamp": payload["timestamp"]
        }

        if payload.get("is_html"):
            api_payload["html"] = 1
        else:
            api_payload["html"] = 0

        # Extract and apply any optional API parameters mapped to this notification
        for param in ["device", "sound", "url", "url_title", "priority", "ttl"]:
            if param in payload:
                api_payload[param] = payload[param]

        success = False
        try:
            # 10-second timeout ensures the worker thread doesn't hang indefinitely on a dead network connection
            response = requests.post(PUSHOVER_API_URL, json=api_payload, timeout=10)
            if response.status_code == 200:
                logging.info(f"Successfully sent notification: '{payload['title']}' (ID: {payload['id']})")
                success = True
            else:
                logging.error(f"Pushover API returned {response.status_code}: {response.text}")
        except Exception as e:
            logging.error(f"Failed to communicate with Pushover API: {e}")

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
            # Handle failure with exponential backoff: 2^retry_count, capped by max_retry_backoff limit
            payload["retry_count"] = payload.get("retry_count", 0) + 1
            backoff_delay = min(2 ** payload["retry_count"], state.smtp["max_retry_backoff"])
            logging.warning(f"Delivery failed for ID: {payload['id']}. Attempt #{payload['retry_count']}. Retrying in {backoff_delay}s.")

            # Update the disk file so if the app crashes during the sleep, we remember the retry count
            if not payload.get("disable_persistence"):
                filepath = os.path.join(state.smtp["queue_dir"], f"{payload['id']}.json")
                if os.path.exists(filepath):
                    try:
                        with open(filepath, 'w') as f:
                            json.dump(payload, f)
                    except Exception as e:
                        logging.error(f"Failed to update retry metadata on disk: {e}")

            # Sleep the thread and push the item back to the end of the line
            time.sleep(backoff_delay)
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
                    payload = json.load(f)
                    msg_queue.put(payload)
            except Exception as e:
                logging.error(f"Failed to load queued file {filepath}: {e}")


def load_config(is_reload=False):
    """
    Loads and merges the GATEWAY_CONFIG JSON and any environment variable overrides.
    Returns a populated GatewayState object. If is_reload is False (i.e. startup),
    any severe validation failures will cause the script to exit.
    """
    raw_env = os.environ.get("GATEWAY_CONFIG")
    if not raw_env:
        logging.error("Environment variable GATEWAY_CONFIG is not set.")
        if not is_reload: exit(1)
        return None

    raw_env = raw_env.strip()

    # If it doesn't look like JSON, assume it's a file path
    is_file = not raw_env.startswith("{")
    file_path = None

    if is_file:
        file_path = os.path.normpath(os.path.join(SCRIPT_DIR, raw_env))
        try:
            with open(file_path, 'r') as f:
                json_str = f.read()
        except Exception as e:
            logging.error(f"Failed to read GATEWAY_CONFIG file '{file_path}': {e}")
            if not is_reload: exit(1)
            return None
    else:
        json_str = raw_env

    # --- Strip Comments Safely ---
    # Strip block comments /* ... */ at the start of the string or preceded by whitespace
    json_str = re.sub(r'(^|\s)/\*.*?\*/', r'\1', json_str, flags=re.DOTALL)
    # Strip line comments // and # at the start of the string or preceded by whitespace
    json_str = re.sub(r'(^|\s)(//|#).*', r'\1', json_str)

    try:
        config_root = json.loads(json_str)
        smtp_json = config_root.get("smtp", {})
        pushover_json = config_root.get("pushover", {})

        new_state = GatewayState()
        new_state.config_file = file_path

        # 1. Parse and Merge SMTP Infrastructure Settings from JSON
        new_state.smtp = {
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

        # Layer OS Environment Variables on top (these take strict precedence)
        if "QUEUE_DIR" in os.environ: new_state.smtp["queue_dir"] = os.environ["QUEUE_DIR"]
        if "HOSTNAME" in os.environ: new_state.smtp["hostname"] = os.environ["HOSTNAME"]
        if "TLS_CERT_FILE" in os.environ: new_state.smtp["tls_cert_file"] = os.environ["TLS_CERT_FILE"]
        if "TLS_KEY_FILE" in os.environ: new_state.smtp["tls_key_file"] = os.environ["TLS_KEY_FILE"]
        if "MAX_RETRY_BACKOFF" in os.environ: new_state.smtp["max_retry_backoff"] = int(os.environ["MAX_RETRY_BACKOFF"])
        if "LOGLEVEL" in os.environ: new_state.smtp["loglevel"] = os.environ["LOGLEVEL"].upper()

        env_bind = os.environ.get("LISTEN")
        env_tls = os.environ.get("STARTTLS")

        # Override to single listener only if explicitly declared via Listener environment variables
        if env_bind or env_tls:
            new_state.smtp["listeners"] = [{
                "bind": env_bind if env_bind else "0.0.0.0:25",
                "starttls": get_bool(env_tls),
                "tls_cert_file": new_state.smtp.get("tls_cert_file"),
                "tls_key_file": new_state.smtp.get("tls_key_file")
            }]
        else:
            new_state.smtp["listeners"] = listeners

        # Clean absolute/relative paths for the active queue directory
        new_state.smtp["queue_dir"] = os.path.normpath(os.path.join(SCRIPT_DIR, new_state.smtp["queue_dir"]))

        # 2. Parse and Merge Global Pushover Settings
        new_state.pushover = {
            "user": pushover_json.get("user"),
            "token": pushover_json.get("token"),
            "device": pushover_json.get("device"),
            "sound": pushover_json.get("sound"),
            "url": pushover_json.get("url"),
            "url_title": pushover_json.get("url_title"),
            "priority": pushover_json.get("priority"),
            "ttl": pushover_json.get("ttl"),
            "force_plaintext": get_bool(pushover_json.get("force_plaintext")),
            "disable_persistence": get_bool(pushover_json.get("disable_persistence"))
        }

        # Again, env vars take precedence for global flags
        if "FORCE_PLAINTEXT" in os.environ:
            new_state.pushover["force_plaintext"] = get_bool(os.environ["FORCE_PLAINTEXT"])
        if "DISABLE_PERSISTENCE" in os.environ:
            new_state.pushover["disable_persistence"] = get_bool(os.environ["DISABLE_PERSISTENCE"])

        # Validate Global String Constraints
        if new_state.pushover.get("url") and len(new_state.pushover["url"]) > MAX_URL_CHARS:
            logging.warning(f"Validation Warning: Global 'url' exceeds {MAX_URL_CHARS} characters. It will be truncated when sending.")
        if new_state.pushover.get("url_title") and len(new_state.pushover["url_title"]) > MAX_URL_TITLE_CHARS:
            logging.warning(f"Validation Warning: Global 'url_title' exceeds {MAX_URL_TITLE_CHARS} characters. It will be truncated when sending.")

        # 3. Parse Email Address Mappings
        for key, config in pushover_json.items():
            # Skip reserved root keys to focus purely on email addresses
            if key in ("user", "token", "device", "sound", "url", "url_title", "priority", "ttl", "force_plaintext", "disable_persistence") or not isinstance(config, dict):
                continue

            match_type = config.get("match", "to").lower()

            # Explicit input validation requirement for "match" parameter values
            if match_type not in ("to", "from", "both"):
                logging.error(f"Validation Failed: Configuration entry '{key}' has invalid match rule '{match_type}'. Ignored.")
                continue

            user_key = config.get("user", new_state.pushover.get("user"))
            app_token = config.get("token")

            if not user_key or not app_token:
                logging.error(f"Missing required 'user' or 'token' definitions for address: {key}. Ignored.")
                continue

            route_config = {"user": user_key, "token": app_token}

            # Apply route-specific boolean overrides if they exist inside this email block
            if "force_plaintext" in config:
                route_config["force_plaintext"] = get_bool(config["force_plaintext"])
            if "disable_persistence" in config:
                route_config["disable_persistence"] = get_bool(config["disable_persistence"])

            # Handle optional Pushover string parameters (device, sound, url, url_title)
            # If defined locally in this route, it overrides the global setting.
            for string_param in ["device", "sound", "url", "url_title"]:
                val = config.get(string_param, new_state.pushover.get(string_param))
                if val and str(val).strip():
                    route_config[string_param] = str(val).strip()

            # Validate Route String Constraints
            if "url" in route_config and len(route_config["url"]) > MAX_URL_CHARS:
                logging.warning(f"Validation Warning: Route '{key}' 'url' exceeds {MAX_URL_CHARS} characters. It will be truncated when sending.")
            if "url_title" in route_config and len(route_config["url_title"]) > MAX_URL_TITLE_CHARS:
                logging.warning(f"Validation Warning: Route '{key}' 'url_title' exceeds {MAX_URL_TITLE_CHARS} characters. It will be truncated when sending.")

            # Handle optional Pushover integer parameters (priority, ttl)
            for int_param in ["priority", "ttl"]:
                val = config.get(int_param, new_state.pushover.get(int_param))
                if val is not None and str(val).strip():
                    try:
                        parsed_val = int(val)
                        # Priority must strictly be between -2 and 2 inclusive
                        if int_param == "priority" and not (-2 <= parsed_val <= 2):
                            logging.warning(f"Priority {parsed_val} for {key} is out of bounds (-2 to 2). Ignored.")
                            continue
                        route_config[int_param] = parsed_val
                    except ValueError:
                        logging.warning(f"Invalid integer '{val}' for {int_param} on {key}. Ignored.")

            # Regex vs String detection
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
                if match_type in ("to", "both"):
                    new_state.regex_mappings["to"].append((compiled_pattern, route_config))
                if match_type in ("from", "both"):
                    new_state.regex_mappings["from"].append((compiled_pattern, route_config))
            else:
                if match_type in ("to", "both"):
                    new_state.mappings["to"][email_key] = route_config
                if match_type in ("from", "both"):
                    new_state.mappings["from"][email_key] = route_config

        # Ensure we have at least *some* viable configuration before returning success
        has_mappings = bool(new_state.mappings["to"] or new_state.mappings["from"] or new_state.regex_mappings["to"] or new_state.regex_mappings["from"])
        if not has_mappings and not (new_state.pushover.get("user") and new_state.pushover.get("token")):
            logging.error("No valid email routing matrices survived validation, and no global catch-all is defined.")
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

    logging.warning(f"TLS files missing, unreadable, or hostname changed. Generating self-signed secp384r1 fallback cert for {hostname} on {bind_address}...")
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

    # 1. Parse unified state configuration and apply side-effects
    app_state = load_config(is_reload=False)
    apply_logging_level(app_state.smtp["loglevel"])
    os.makedirs(app_state.smtp["queue_dir"], exist_ok=True)

    auth_status = "Enabled" if app_state.smtp.get("auth") else "Disabled (Permissive)"
    catch_all_status = bool(app_state.pushover.get("user") and app_state.pushover.get("token"))
    total_mapped = len(app_state.mappings["to"]) + len(app_state.mappings["from"]) + len(app_state.regex_mappings["to"]) + len(app_state.regex_mappings["from"])

    src = f"file '{app_state.config_file}'" if app_state.config_file else "environment context"
    logging.info(f"Loaded config from {src}. Explicit rules: {total_mapped}. Catch-all: {catch_all_status}. SMTP Auth: {auth_status}")

    # 2. Setup thread-safe queue and retrieve un-sent disk persistence items
    msg_queue = queue.Queue()
    load_queue_from_disk(msg_queue, app_state)

    # 3. Start the background Pushover worker thread
    worker_thread = threading.Thread(target=pushover_worker, args=(msg_queue, app_state), daemon=True)
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
        ctrl = Controller(
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

                        ctrl = Controller(
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
                        app_state.mappings.clear(); app_state.mappings.update(new_state.mappings)
                        app_state.regex_mappings.clear(); app_state.regex_mappings.update(new_state.regex_mappings)

                        # Apply immediate dynamic system effects
                        apply_logging_level(app_state.smtp["loglevel"])
                        os.makedirs(app_state.smtp["queue_dir"], exist_ok=True)

                        new_auth_status = "Enabled" if app_state.smtp.get("auth") else "Disabled (Permissive)"
                        new_catch_all = bool(app_state.pushover.get("user") and app_state.pushover.get("token"))
                        new_total = len(app_state.mappings["to"]) + len(app_state.mappings["from"]) + len(app_state.regex_mappings["to"]) + len(app_state.regex_mappings["from"])

                        logging.info(f"Reload success. Mappings tracked: {new_total}. Catch-all: {new_catch_all}. SMTP Auth: {new_auth_status}")
                        logging.info("Note: Changes to listener endpoints or TLS settings require a SIGUSR1 to take effect.")
                    else:
                        logging.warning("Config reload failed. Retaining active rules matrix.")
                else:
                    logging.info("GATEWAY_CONFIG is defined as an inline JSON string environment variable. Ignoring SIGUSR2.")

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

        logging.info("Shutdown complete.")
